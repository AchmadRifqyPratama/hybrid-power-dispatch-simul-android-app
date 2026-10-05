"""Dispatch engine — port setia dari logika Excel (sheet Results, kolom H..AF).

Setiap jam dievaluasi dengan urutan dependensi persis seperti formula Excel:

    Z  = SOC awal jam (kWh)            = AA jam sebelumnya
    Q  = PV ENetAC (kW)                = profil * kWp / basis   (kolom Q)
    P  = total genset diesel (kW)      = M+N+O                  (kolom M,N,O,P)
    V  = charge BESS dari PV (kW)      (kolom V)
    X  = discharge BESS (kW)           (kolom X)
    AC = beban dilayani PV+BESS (kW)   (kolom AC)
    AD = grid untuk beban (kW)         (kolom AD)
    J  = sisa kapasitas grid (kW)      (kolom J)
    W  = charge BESS dari grid (kW)    (kolom W)
    U  = V+W ; I = AD+W ; S = output inverter PV ; T = PV excess
    AA = SOC akhir jam (kWh) ; AF = surplus suplai

Implementasi tervektorisasi pada sumbu KOMBINASI: seluruh kandidat sizing
(N kombinasi) disimulasikan serentak per langkah waktu, sehingga optimasi
ribuan kombinasi hanya butuh satu loop 8760 langkah dengan operasi array.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np

from .numeric import snap_zero
from . import bess_modes

HOURS_YEAR = 8760
HOURS_LEAP = 8784

# Faktor EMA (exponential moving average) untuk PV Smoothing (mode Advanced):
# ema[t] = α·PV[t] + (1−α)·ema[t−1]. Internal (bukan input pengguna); output
# PV+BESS lalu dibatasi laju naik/turunnya (pv_ramp_up/dn_kwmin).
PV_EMA_ALPHA = 0.3


@dataclass
class SystemParams:
    """Parameter satu kandidat sistem. Semua daya kW, energi kWh, fraksi 0-1."""
    pv_kwp: float = 37.5            # kapasitas array PV (DC)
    pv_inv_kw: float = 30.0         # kapasitas inverter PV (AC)
    pv_base_annual: float = 1103.76 # kWp pembangkit acuan profil ENetAC
    pv_degradation: float = 0.005   # per tahun (dipakai modul finance)
    bess_kwh: float = 215.0         # kapasitas nominal BESS
    soc_init: float = 0.5
    soc_min: float = 0.1
    soc_max: float = 0.95
    rte: float = 0.913              # round-trip efficiency
    max_charge_kw: float = 108.0
    max_discharge_kw: float = 108.0
    charge_from_grid_below_soc: float = 0.6
    bess_degradation: float = 0.02  # per tahun (finance)
    # Self consumption BESS (aux: HVAC/BMS/PCS idle) — kWh per JAM (= kW
    # konstan) selama BESS terpasang. Beban TAMBAHAN di atas beban pengguna.
    # 0 = nonaktif (byte-identik perilaku lama).
    bess_self_cons_kw: float = 0.0
    # Pemasok self consumption: 0 = PV+BESS (sisa → Grid lalu DEG),
    # 1 = DEG/Grid (Grid lalu DEG; sisa → PV+BESS).
    bess_sc_source: int = 0
    grid_enabled: bool = True
    grid_kw: float = 23.0
    grid_min_loading: float = 0.01
    grid_max_loading: float = 1.0
    allow_export: bool = False      # ekstensi opsional (default: setia ke Excel)
    load_priority: float = 0.0      # 0 = PV→BESS→Grid→DEG (Excel), 1 = Grid→PV→BESS→DEG
    load_priority_split: bool = False   # True = pakai skenario terpisah per status grid
    load_priority_on: float = 0.0       # skenario saat grid tersedia (status 1)
    load_priority_off: float = 2.0      # skenario saat grid padam (status 0)
    charge_priority: float = 0.0    # 0 = PV→Grid, 1 = Grid→PV
    strict_charge_priority: bool = False  # sumber prioritas kedua menunggu
    grid_charge_enabled: bool = True  # False = grid tidak boleh charge BESS
    deg_charge_enabled: bool = False  # True = DEG (saat menyala) boleh charge BESS
    deg_interlock: bool = True        # True = beban dari (Grid+PVBESS) ATAU DEG eksklusif
    # Opsi DEG per status grid (mirror load_priority_split). Bila
    # deg_options_split True, engine memakai *_on saat grid tersedia dan *_off
    # saat grid padam; bila False, deg_interlock / deg_charge_enabled global.
    deg_options_split: bool = False
    deg_interlock_on: bool = True     # DEG interlock PV-BESS saat grid tersedia
    deg_interlock_off: bool = True    # DEG interlock PV-BESS saat grid padam
    deg_charge_on: bool = False       # Allow DEG charging saat grid tersedia
    deg_charge_off: bool = False      # Allow DEG charging saat grid padam
    grid_interlock: bool = False      # True = beban dari Grid ATAU PV-BESS (eksklusif)
    deg_grid_interlock: bool = True   # True = DEG hanya menyala saat grid tidak tersedia
    deg_sync: bool = True             # True = genset boleh paralel/berbagi beban (kini).
    #                                   False = tak sinkron: satu genset menyala pada satu
    #                                   waktu, terkecil dulu, naik ke lebih besar saat penuh.
    deg_always: bool = False          # True = DEG WAJIB selalu nyala di minimum loading;
    #                                   surplus (beban < min load) mengisi BESS bila SOC<maks.
    deg_grid_former: int = 0          # DEG grid-forming pilihan: 0=Auto(terkecil),1/2/3=DEG-1/2/3
    deg_min_loading: float = 0.0      # Lmin seragam; dgn DEG-charging jadi target minimum
    deg_kw: tuple = (30.0, 0.0, 0.0)        # kapasitas DEG-1..3
    deg_max_loading: tuple = (1.0, 0.0, 0.0)
    deg_efficiency: float = 0.33    # efisiensi listrik genset (finance/fuel)
    interval_h: float = 1.0
    # --- BESS lanjutan (opt-in). Standard: bess_mode=0 → jalur Excel murni.
    #     Advanced: bess_mode=1 mengaktifkan EMS multi-mode berbasis PRIORITAS:
    #     satu baterai melayani beberapa mode sekaligus, berbagi anggaran SOC &
    #     PCS menurut urutan prioritas (lihat bess_modes.codispatch). ---
    bess_mode: int = 0              # 0 = Standard, 1 = Advanced (multi-mode)
    # mode enable (1/0) — beberapa boleh aktif serentak
    m_pv_smooth: int = 0            # PV Smoothing (EMA + batas ramp PV+BESS)
    m_firming: int = 0              # Firming (PV+BESS = daya konstan base load)
    m_load_shift: int = 0           # Load Shifting / Energy Shifting
    m_peak_shave: int = 0           # Peak Shaving (net load > ambang)
    m_dg_minload: int = 0           # DG Minimum Loading (serap kelebihan DG)
    m_reserve: int = 0              # Operating Reserve (jaga SOC/PCS cadangan)
    m_backup: int = 0               # Backup (BESS+PV ambil alih saat Grid&DEG outage)
    # parameter mode
    peak_shave_kw: float = 0.0      # ambang net load utk Peak Shaving (kW)
    firming_kw: float = 0.0         # target daya konstan PV+BESS (kW)
    firming_trigger: int = 0        # jendela Firming: 0=PV Power, 1=Time
    firming_pv_start: float = 0.0   # (PV Power) PV EnetAC mulai Firming (kW)
    firming_pv_end: float = 0.0     # (PV Power) PV EnetAC berhenti Firming (kW)
    firming_time_start: float = 0.0 # (Time) jam mulai Firming (h)
    firming_time_end: float = 0.0   # (Time) jam berhenti Firming (h)
    arb_peak_start: float = 0.0     # jam awal jendela discharge Load Shifting
    arb_peak_end: float = 0.0       # jam akhir jendela discharge Load Shifting
    pv_ramp_up_kwmin: float = 0.0   # batas laju NAIK sinyal target (kW/menit)
    pv_ramp_dn_kwmin: float = 0.0   # batas laju TURUN sinyal target (kW/menit)
    smoothing_window: int = 10      # ukuran jendela Moving Average PV (langkah)
    reserve_frac: float = 0.0       # fraksi energi guna ditahan sbg cadangan
    reserve_kw: float = 0.0         # daya PCS ditahan sbg cadangan (kW)
    # Target discharge mode Advanced: 0=Both (grid lalu DEG), 1=Grid saja,
    # 2=DEG saja. Menentukan suplai mana yang dikurangi discharge BESS.
    adv_target: int = 0
    # nomor prioritas co-dispatch tiap mode (1 = tertinggi; default = spec).
    # Skala 1-5 (bukan 1-7): Smoothing<->Firming & Reserve<->Backup saling
    # eksklusif (GUI, lihat parameters_page._mutual_exclusive) -> maks 5
    # mode DISPATCH aktif bersamaan (satu dari tiap pasangan + 3 mode lain).
    prio_pv_smooth: int = 2
    prio_firming: int = 2
    prio_load_shift: int = 4
    prio_peak_shave: int = 5
    prio_dg_minload: int = 3
    prio_reserve: int = 1
    prio_backup: int = 1
    # kompat-mundur (tak dipakai EMS multi-mode, disimpan agar tak error)
    bess_function: int = 0
    bess_target: int = 0
    pv_smooth_ramp_kw: float = 0.0

    def as_vector_fields(self) -> dict:
        return dict(
            pv_kwp=self.pv_kwp, pv_inv_kw=self.pv_inv_kw,
            bess_kwh=self.bess_kwh,
            max_chg=self.max_charge_kw, max_dhg=self.max_discharge_kw,
        )


@dataclass
class SimulationResult:
    """Hasil simulasi: KPI teknis agregat + deret waktu opsional."""
    kpi: dict
    series: dict | None = None      # dict nama -> np.ndarray (T,) bila direkam
    params: SystemParams | None = None
    monthly: dict | None = None


def _deg_dispatch_nosync(ae, need_deg, d1, d2, d3, lmax):
    """Alokasi genset mode TIDAK SINKRON: hanya SATU genset menyala sekaligus.

    Genset TERKECIL (kapasitas > 0) yang max-loading-nya sanggup memikul AE
    yang menyala; bila AE melampauinya, naik ke genset lebih besar; bila tak ada
    satu genset pun yang sanggup, genset TERBESAR berjalan pada max loading (sisa
    beban menjadi unserved). Genset berkapasitas 0 diabaikan. Mengembalikan
    (m, n, o) — output tiap unit pada urutan asli (DEG-1..3)."""
    ae = np.asarray(ae, float)
    lmax_s = float(np.asarray(lmax).reshape(-1)[0])
    caps = [float(np.asarray(d).reshape(-1)[0]) for d in (d1, d2, d3)]
    order = [i for i in sorted(range(3), key=lambda k: caps[k]) if caps[i] > 0]
    out = [np.zeros_like(ae), np.zeros_like(ae), np.zeros_like(ae)]
    if not order:
        return out[0], out[1], out[2]
    sel = np.full(np.shape(ae), order[-1], dtype=np.int64)   # default: terbesar
    for i in reversed(order):            # unit lebih kecil menimpa bila sanggup
        sel = np.where(ae <= caps[i] * lmax_s + 1e-9, i, sel)
    for i in order:
        on = need_deg & (sel == i)
        out[i] = np.maximum(0.0, np.round(
            np.where(on, np.minimum(ae, caps[i] * lmax_s), 0.0), 6))
    return out[0], out[1], out[2]


def _deg_run_cap_nosync(base_kw, d1, d2, d3, lmax):
    """Kapasitas genset TUNGGAL yang menyala (mode tidak sinkron) untuk `base_kw`
    — dipakai menghitung target minimum loading. Genset terkecil yang sanggup;
    bila tak ada, genset terbesar. 0 bila tak ada genset."""
    base = np.asarray(base_kw, float)
    lmax_s = float(np.asarray(lmax).reshape(-1)[0])
    caps = [float(np.asarray(d).reshape(-1)[0]) for d in (d1, d2, d3)]
    order = [i for i in sorted(range(3), key=lambda k: caps[k]) if caps[i] > 0]
    if not order:
        return np.zeros_like(base)
    run = np.full(np.shape(base), caps[order[-1]], dtype=float)
    for i in reversed(order):
        run = np.where(base <= caps[i] * lmax_s + 1e-9, caps[i], run)
    return run


def _deg_dispatch(ae, need_deg, d1, d2, d3, lmax, sync=True):
    """Alokasi genset bertingkat dengan load sharing weighted-average kapasitas.

    Tahap 1 : AE ≤ D1·Lmax                → DEG-1 sendiri (M = AE)
    Tahap 2 : D1·Lmax < AE ≤ (D1+D2)·Lmax → DEG-1 & DEG-2 berbagi
              proporsional kapasitas: Mi = AE · Di / (D1+D2)
    Tahap 3 : AE > (D1+D2)·Lmax           → ketiganya berbagi
              proporsional kapasitas: Mi = AE · Di / (D1+D2+D3)
    Contoh tahap 2: AE=100, D1=120, D2=240 → M=33.33, N=66.67.

    Bila sync=False: hanya SATU genset menyala (lihat _deg_dispatch_nosync)."""
    if not sync:
        return _deg_dispatch_nosync(ae, need_deg, d1, d2, d3, lmax)
    th1 = d1 * lmax
    th2 = (d1 + d2) * lmax
    s12 = np.maximum(d1 + d2, 1e-300)
    s123 = np.maximum(d1 + d2 + d3, 1e-300)
    stage1 = ae <= th1
    stage2 = (~stage1) & (ae <= th2)
    m = np.where(stage1, ae, np.where(stage2, ae * d1 / s12, ae * d1 / s123))
    n = np.where(stage1, 0.0, np.where(stage2, ae * d2 / s12, ae * d2 / s123))
    o = np.where(stage1 | stage2, 0.0, ae * d3 / s123)
    m = np.maximum(0.0, np.round(np.where(need_deg, m, 0.0), 6))
    n = np.maximum(0.0, np.round(np.where(need_deg, n, 0.0), 6))
    o = np.maximum(0.0, np.round(np.where(need_deg, o, 0.0), 6))
    return m, n, o


def _system_vals(p: 'SystemParams') -> dict:
    """Bangun dict skalar 'vals' dari SystemParams — SATU sumber kebenaran
    konfigurasi dispatch. Dipakai oleh simulate() (run tunggal) DAN oleh
    simulasi multi-year (di-broadcast per tahun), sehingga formula dispatch
    kedua jalur DIJAMIN identik. Kunci dict harus sama persis dengan yang
    dibaca di badan simulate()."""
    g = lambda name: np.asarray(getattr(p, name), dtype=float)
    deg1, deg2, deg3 = (np.asarray(x, float) for x in p.deg_kw)
    d1max, d2max = (np.asarray(x, float) for x in p.deg_max_loading[:2])
    grid_on = 1.0 if p.grid_enabled else 0.0
    return dict(
        pv_kwp=g('pv_kwp'), pv_inv=g('pv_inv_kw'), pv_base=g('pv_base_annual'),
        bess=g('bess_kwh'), soc_init=g('soc_init'), soc_min=g('soc_min'),
        soc_max=g('soc_max'), rte=g('rte'), max_chg=g('max_charge_kw'),
        max_dhg=g('max_discharge_kw'), chg_soc=g('charge_from_grid_below_soc'),
        bess_self_cons=g('bess_self_cons_kw'),
        bess_sc_source=np.asarray(float(getattr(p, 'bess_sc_source', 0) or 0)),
        grid_kw=g('grid_kw') * grid_on, grid_min=g('grid_min_loading'),
        grid_max=g('grid_max_loading'), dt=g('interval_h'),
        deg1=deg1, deg2=deg2, deg3=deg3, d1max=d1max, d2max=d2max,
        allow_export=np.asarray(1.0 if p.allow_export else 0.0),
        load_priority=g('load_priority'), charge_priority=g('charge_priority'),
        load_priority_split=np.asarray(1.0 if p.load_priority_split else 0.0),
        load_priority_on=g('load_priority_on'),
        load_priority_off=g('load_priority_off'),
        strict_charge=np.asarray(1.0 if p.strict_charge_priority else 0.0),
        grid_charge_enabled=np.asarray(1.0 if p.grid_charge_enabled else 0.0),
        deg_charge_enabled=np.asarray(1.0 if p.deg_charge_enabled else 0.0),
        deg_interlock=np.asarray(1.0 if p.deg_interlock else 0.0),
        deg_sync=np.asarray(1.0 if p.deg_sync else 0.0),
        deg_always=np.asarray(1.0 if p.deg_always else 0.0),
        deg_grid_former=np.asarray(float(getattr(p, 'deg_grid_former', 0) or 0)),
        deg_options_split=np.asarray(1.0 if p.deg_options_split else 0.0),
        deg_interlock_on=np.asarray(1.0 if p.deg_interlock_on else 0.0),
        deg_interlock_off=np.asarray(1.0 if p.deg_interlock_off else 0.0),
        deg_charge_on=np.asarray(1.0 if p.deg_charge_on else 0.0),
        deg_charge_off=np.asarray(1.0 if p.deg_charge_off else 0.0),
        grid_interlock=np.asarray(1.0 if p.grid_interlock else 0.0),
        deg_grid_interlock=np.asarray(1.0 if p.deg_grid_interlock else 0.0),
        deg_min_loading=g('deg_min_loading'),
        bess_mode=np.asarray(float(getattr(p, 'bess_mode', 0) or 0)),
        m_pv_smooth=np.asarray(float(getattr(p, 'm_pv_smooth', 0) or 0)),
        m_firming=np.asarray(float(getattr(p, 'm_firming', 0) or 0)),
        m_load_shift=np.asarray(float(getattr(p, 'm_load_shift', 0) or 0)),
        m_peak_shave=np.asarray(float(getattr(p, 'm_peak_shave', 0) or 0)),
        m_dg_minload=np.asarray(float(getattr(p, 'm_dg_minload', 0) or 0)),
        m_reserve=np.asarray(float(getattr(p, 'm_reserve', 0) or 0)),
        m_backup=np.asarray(float(getattr(p, 'm_backup', 0) or 0)),
        peak_shave_kw=g('peak_shave_kw'),
        firming_kw=g('firming_kw'),
        firming_trigger=np.asarray(float(getattr(p, 'firming_trigger', 0) or 0)),
        firming_pv_start=g('firming_pv_start'),
        firming_pv_end=g('firming_pv_end'),
        firming_time_start=np.asarray(float(getattr(p, 'firming_time_start', 0) or 0)),
        firming_time_end=np.asarray(float(getattr(p, 'firming_time_end', 0) or 0)),
        arb_peak_start=np.asarray(float(getattr(p, 'arb_peak_start', 0) or 0)),
        arb_peak_end=np.asarray(float(getattr(p, 'arb_peak_end', 0) or 0)),
        pv_ramp_up_kwmin=g('pv_ramp_up_kwmin'),
        pv_ramp_dn_kwmin=g('pv_ramp_dn_kwmin'),
        smoothing_window=np.asarray(float(getattr(p, 'smoothing_window', 10) or 10)),
        reserve_frac=g('reserve_frac'),
        reserve_kw=g('reserve_kw'),
        adv_target=np.asarray(float(getattr(p, 'adv_target', 0) or 0)),
        prio_pv_smooth=np.asarray(float(getattr(p, 'prio_pv_smooth', 2) or 2)),
        prio_firming=np.asarray(float(getattr(p, 'prio_firming', 3) or 3)),
        prio_load_shift=np.asarray(float(getattr(p, 'prio_load_shift', 5) or 5)),
        prio_peak_shave=np.asarray(float(getattr(p, 'prio_peak_shave', 6) or 6)),
        prio_dg_minload=np.asarray(float(getattr(p, 'prio_dg_minload', 4) or 4)),
        prio_reserve=np.asarray(float(getattr(p, 'prio_reserve', 1) or 1)),
        prio_backup=np.asarray(float(getattr(p, 'prio_backup', 1) or 1)),
    )


def simulate(load: np.ndarray,
             pv_norm: np.ndarray,
             grid_status: np.ndarray,
             p,                       # SystemParams ATAU dict array (batch)
             n_combos: int | None = None,
             record: bool = False,
             progress=None,
             deg_status: np.ndarray | None = None) -> dict:   # callback(done, total) untuk indikator %
    """Jalankan dispatch.

    load        : (T,) beban per jam [kW]
    pv_norm     : (T,) profil PV basis [kW per plant basis]
    grid_status : (T,) 1 = PLN hidup, 0 = padam
    p           : SystemParams (single) atau dict berisi skalar/array (N,)
                  untuk mode batch (kunci = nama field SystemParams).
    record      : simpan deret waktu penuh (hanya untuk run tunggal / N kecil)
    deg_status  : (T,) opsional, dari kolom import "DEG Status": 0 = DEG TAK
                  TERSEDIA jam itu (kapasitas SEMUA unit DEG di-nol-kan jam
                  itu — spt outage/maintenance terjadwal); != 0 (termasuk 1
                  ATAU kode 'Auto') = DEG TERSEDIA seperti biasa, keputusan
                  nyala/tidaknya TETAP murni mengikuti dispatch normal (Load
                  Supply Priority, DEG Interlock, dll di halaman Parameters)
                  — status HANYA menyatakan ketersediaan, BUKAN memaksa DEG
                  menyala. None (default, tak diimpor) -> TAK ADA pengaruh
                  sama sekali, byte-identik perilaku lama.

    Return dict berisi akumulator KPI (masing-masing skalar atau array (N,))
    dan, bila record=True, kunci 'series' berisi deret (T,) / (T,N).
    """
    T = len(load)
    if deg_status is not None:
        deg_status = np.asarray(deg_status, float)
    if isinstance(p, SystemParams):
        vals = _system_vals(p)
        N = 1
    else:
        vals = {k: np.asarray(v, dtype=float) for k, v in p.items()}
        N = n_combos or max(int(np.size(v)) for v in vals.values())

    kwp, pinv = vals['pv_kwp'], vals['pv_inv']
    E, dt = vals['bess'], vals['dt']
    soc_min_e = vals['soc_min'] * E
    soc_max_e = vals['soc_max'] * E
    srte = np.sqrt(vals['rte'])
    max_chg, max_dhg = vals['max_chg'], vals['max_dhg']
    chg_soc = vals['chg_soc']
    Hg = vals['grid_kw']                      # kapasitas grid (0 bila off)
    gmin, gmax = vals['grid_min'], vals['grid_max']
    deg1, deg2, deg3 = vals['deg1'], vals['deg2'], vals['deg3']
    d1max, d2max = vals['d1max'], vals['d2max']
    allow_export = vals.get('allow_export', np.asarray(0.0))
    pv_scale = kwp / vals['pv_base']
    # --- BESS lanjutan: EMS multi-mode berbasis PRIORITAS (mode Advanced) ---
    # bess_mode: 0=Standard, 1=Advanced. Di Advanced, BESS dikendalikan oleh
    # co-dispatch prioritas (bess_modes.codispatch) — dispatch BESS baku
    # (load-serving) DINONAKTIFKAN (d_pot/head_chg=0) & seluruh aksi baterai
    # dihitung blok multi-mode. Bila _adv_on False, seluruh blok DILEWATI →
    # jalur Standard bit-identik. Flag mode & param bersifat SKALAR (satu
    # konfigurasi per run, termasuk batch optimasi).
    _adv_on = int(round(float(np.max(np.asarray(
        vals.get('bess_mode', 0.0), float))))) == 1
    _sg = lambda k: float(np.max(np.asarray(vals.get(k, 0.0), float)))
    _md = dict(
        pv_smooth=_sg('m_pv_smooth') > 0.5, firming=_sg('m_firming') > 0.5,
        load_shift=_sg('m_load_shift') > 0.5,
        peak_shave=_sg('m_peak_shave') > 0.5,
        dg_minload=_sg('m_dg_minload') > 0.5,
        reserve=_sg('m_reserve') > 0.5, backup=_sg('m_backup') > 0.5,
        peak_kw=np.asarray(vals.get('peak_shave_kw', 0.0), float),
        firming_kw=np.asarray(vals.get('firming_kw', 0.0), float),
        firm_trigger=int(round(float(np.max(np.asarray(
            vals.get('firming_trigger', 0.0), float))))),   # 0=PV Power, 1=Time
        firm_pv_start=np.asarray(vals.get('firming_pv_start', 0.0), float),
        firm_pv_end=np.asarray(vals.get('firming_pv_end', 0.0), float),
        firm_t_start=float(np.max(np.asarray(vals.get('firming_time_start', 0.0), float))),
        firm_t_end=float(np.max(np.asarray(vals.get('firming_time_end', 0.0), float))),
        arb_start=_sg('arb_peak_start'), arb_end=_sg('arb_peak_end'),
        pv_up_kwmin=np.asarray(vals.get('pv_ramp_up_kwmin', 0.0), float),
        pv_dn_kwmin=np.asarray(vals.get('pv_ramp_dn_kwmin', 0.0), float),
        ma_window=max(1, int(round(_sg('smoothing_window') or 10))),  # jendela MA
        resv_frac=np.asarray(vals.get('reserve_frac', 0.0), float),
        resv_kw=np.asarray(vals.get('reserve_kw', 0.0), float),
        target=int(round(float(np.max(np.asarray(
            vals.get('adv_target', 0.0), float))))))
    _md['arb_wrap'] = _md['arb_start'] > _md['arb_end']
    # Backup vs Reserve: nomor Priority (dropdown, spt mode lain) menentukan
    # siapa 'menang' saat Backup mengambil alih penuh di jam outage (Grid&DEG
    # sama2 tak tersedia) -- bila Priority Backup ≤ Priority Reserve (1=
    # tertinggi; seri -> Backup menang), Backup BOLEH menembus floor SOC &
    # daya PCS yang ditahan Reserve utk jam itu; selain itu Backup tetap
    # menghormatinya spt mode lain. Reserve tak aktif -> tak ada floor utk
    # ditembus -> Backup otomatis 'menang' (tak relevan).
    _bk_prio = _sg('prio_backup') or 1
    _rv_prio = _sg('prio_reserve') or 1
    _md['backup_beats_reserve'] = (not (_sg('m_reserve') > 0.5)
                                   or (_bk_prio <= _rv_prio))
    # urutan pemrosesan mode aksi menurut nomor prioritas (1 = lebih dulu);
    # tie-break stabil oleh urutan default spec.
    _prio = {'pv_smooth': _sg('prio_pv_smooth') or 2,
             'firming': _sg('prio_firming') or 2,
             'dg_minload': _sg('prio_dg_minload') or 3,
             'load_shift': _sg('prio_load_shift') or 4,
             'peak_shave': _sg('prio_peak_shave') or 5,
             'backup': _bk_prio}
    _default = ['backup', 'pv_smooth', 'firming', 'dg_minload', 'load_shift',
               'peak_shave']
    _md['order'] = sorted(_default, key=lambda k: (_prio[k], _default.index(k)))
    # BESS aktif di mode Advanced hanya bila minimal satu mode DISPATCH menyala.
    _adv_post = _adv_on and any(_md[k] for k in (
        'pv_smooth', 'firming', 'load_shift', 'peak_shave', 'dg_minload',
        'reserve', 'backup'))
    _resv_on = _adv_on and _md['reserve'] and (
        bool(np.any(_md['resv_frac'] > 0)) or bool(np.any(_md['resv_kw'] > 0)))
    _resv_e = _md['resv_frac'] * (soc_max_e - soc_min_e)  # energi cadangan (kWh)
    _pv_prev = None                                       # state ramp target (delivered)
    _ema_prev = None                                      # (tak dipakai; MA precompute)
    # Setpoint Smoothing = Moving Average PV EnetAC (window = INPUT), lalu DIGESER
    # 1 langkah agar KAUSAL: setpoint yang berlaku di langkah t dihitung HANYA dari
    # PV EnetAC SEBELUM t (W nilai berakhir di t-1) — tidak melihat PV saat ini.
    # (spec: sp_raw[t+1] = rata-rata PV EnetAC[t .. t-W+1]). Dipracompute atas profil
    # PV (min(pv_norm×scale, pinv)) → MA TRAILING, lalu shift.
    _ma_win = int(_md['ma_window'])
    _up_step = float(np.max(np.asarray(_md['pv_up_kwmin'], float))) * (dt * 60.0)
    _dn_step = float(np.max(np.asarray(_md['pv_dn_kwmin'], float))) * (dt * 60.0)
    _ma_pv = None
    _ma_pv_pure = None            # MA MURNI PV EnetAC (telemetri "MA Setpoint")
    _ld_eff_all = None            # beban SISA utk PV/BESS (Smoothing), lihat bawah
    if _adv_post and _md['pv_smooth']:
        # qinv per langkah = min(pv_norm×scale, pinv, BEBAN SISA). Pertahankan
        # bentuk alami (skalar utk 1 konfigurasi, (nc,) utk batch) agar broadcast
        # loop utuh. Basis SETPOINT (target MA) dibatasi beban SISA — PV di atas
        # beban SISA tak pernah masuk target MA — TAPI perbandingan gap/injeksi
        # aktual di dalam loop tetap pakai PV mentah (_qinv_r), sehingga PV di
        # atas target otomatis jadi kandidat CHARGE BESS (bukan target smoothing
        # itu sendiri). Hanya berlaku Smoothing; Firming tetap qinv tanpa batas
        # beban (target konstan, lihat blok firming di dalam loop).
        _sc = np.asarray(pv_scale, float)
        _pn = np.asarray(pv_norm, float).reshape((-1,) + (1,) * _sc.ndim)
        _ld_all = np.asarray(load, float).reshape((-1,) + (1,) * _sc.ndim)
        # --- BEBAN SISA utk PV/BESS: bila 'DEG Must Always Run' aktif & grid tak
        # tersedia jam itu, genset grid-forming WAJIB melayani beban lebih dulu
        # hingga floor minimum-loading-nya (blok must-run di bawah, ~baris 1257) —
        # PV/BESS TAK PERLU (Smoothing tak perlu discharge utk) menanggung porsi
        # yang sudah dijamin DEG. Rumus & seleksi genset grid-forming IDENTIK dgn
        # blok must-run (hanya dimajukan, murni fungsi ae/grid_status/kapasitas
        # DEG — tak bergantung hasil shaping) agar basis MA memakai residual yg
        # benar. Di luar deg_always aktif (default) -> ld_eff = beban penuh,
        # TAK BERUBAH (byte-identik perilaku lama).
        _da_pre = bool(np.max(np.asarray(vals.get('deg_always', 0.0), float)) > 0)
        _lmin_pre = np.asarray(vals.get('deg_min_loading', 0.0), float)
        _capv_pre = [float(np.asarray(x).reshape(-1)[0]) for x in (deg1, deg2, deg3)]
        _pos_pre = [i for i in range(3) if _capv_pre[i] > 0]
        _ismall_pre = min(_pos_pre, key=lambda i: _capv_pre[i]) if _pos_pre else -1
        _gf_pre = int(round(float(np.max(np.asarray(
            vals.get('deg_grid_former', 0.0), float))))) - 1
        _auto_gf_pre = _gf_pre not in _pos_pre
        _iform_pre = _gf_pre if not _auto_gf_pre else _ismall_pre
        _deg_has_any_pre = _iform_pre >= 0
        # 'DEG Status' per-jam (opsional): pilihan genset grid-forming
        # (_iform_pre dst., di atas) tetap NAMEPLATE (struktural, tak berubah
        # per-jam) — hanya BESARAN kapasitas yg dipakai utk floor di bawah
        # yg di-nol-kan jam2 DEG tak tersedia (0), agar basis beban-sisa
        # Smoothing konsisten dgn masking di loop utama. deg_status=None ->
        # mask=1 penuh -> byte-identik lama.
        if deg_status is not None:
            _avail_pre = (deg_status.reshape((-1,) + (1,) * _sc.ndim)
                          != 0.0).astype(float)
            deg1p, deg2p, deg3p = deg1 * _avail_pre, deg2 * _avail_pre, deg3 * _avail_pre
        else:
            deg1p, deg2p, deg3p = deg1, deg2, deg3
        if _da_pre and _deg_has_any_pre:
            _floor0_pre = deg1p * _lmin_pre
            _floor1_pre = deg2p * _lmin_pre
            _floor2_pre = deg3p * _lmin_pre
            if _auto_gf_pre:
                _BIGpre = 1e18
                _d0p = np.where(deg1p > 0, np.abs(_floor0_pre - _ld_all)
                                + 1e-9 * deg1p, _BIGpre)
                _d1p = np.where(deg2p > 0, np.abs(_floor1_pre - _ld_all)
                                + 1e-9 * deg2p, _BIGpre)
                _d2p = np.where(deg3p > 0, np.abs(_floor2_pre - _ld_all)
                                + 1e-9 * deg3p, _BIGpre)
                _gf0p = (_d0p <= _d1p) & (_d0p <= _d2p)
                _gf1p = (_d1p < _d0p) & (_d1p <= _d2p)
                _gf2p = (_d2p < _d0p) & (_d2p < _d1p)
                _floor_sel_pre = (_floor0_pre * _gf0p + _floor1_pre * _gf1p
                                  + _floor2_pre * _gf2p)
            else:
                _capsm_pre = [deg1p, deg2p, deg3p][_iform_pre]
                _floor_sel_pre = _capsm_pre * _lmin_pre
            _gna_pre = (np.asarray(grid_status, float).reshape(
                (-1,) + (1,) * _sc.ndim) <= 0) | (np.asarray(Hg, float) <= 0)
            _deg_want_pre = np.where(_gna_pre, np.minimum(_ld_all, _floor_sel_pre),
                                     0.0)
        else:
            _deg_want_pre = np.zeros_like(_ld_all)
        _ld_eff_all = np.maximum(0.0, _ld_all - _deg_want_pre)
        _q_all = np.minimum(np.minimum(_pn * _sc, np.asarray(pinv, float)),
                            _ld_eff_all)                             # (T, *scale.shape)
        if _ma_win <= 1:
            _ma_tr = _q_all                                          # MA trailing (W=1)
        else:
            _cs = np.cumsum(_q_all, axis=0)
            _ma_tr = np.empty_like(_q_all)
            _nT = _q_all.shape[0]
            _k = np.minimum(np.arange(1, _nT + 1), _ma_win).astype(float)
            _k = _k.reshape((-1,) + (1,) * (_q_all.ndim - 1))        # broadcast axis-0
            _ma_tr[:_ma_win] = _cs[:_ma_win] / _k[:_ma_win]         # awal (parsial)
            if _nT > _ma_win:
                _ma_tr[_ma_win:] = (_cs[_ma_win:] - _cs[:-_ma_win]) / float(_ma_win)
        # geser 1 langkah (KAUSAL): setpoint[t] = MA(PV[t-W .. t-1]); t=0 → PV[0]
        _ma_pv = np.empty_like(_ma_tr)
        _ma_pv[0] = _q_all[0]
        _ma_pv[1:] = _ma_tr[:-1]
        # --- MA MURNI utk TELEMETRI "MA Setpoint" -----------------------------
        # Moving average PV EnetAC yang DIBATASI INVERTER SAJA (min(PV×scale,
        # pinv)), TANPA batas beban-sisa (_ld_eff). Inilah nilai "MA Setpoint"
        # yang ditampilkan/diekspor: benar-benar HANYA rata-rata bergerak PV
        # EnetAC, INDEPENDEN dari beban (permintaan pengguna: "MA setpoint
        # harusnya independent, hanya mengkalkulasi moving average PV EnetAC").
        # Dispatch (di dalam loop) TETAP memakai _ma_pv (dibatasi beban sisa)
        # utk menentukan discharge/charge & Plant Inj -> NUMERIK DISPATCH TAK
        # BERUBAH SAMA SEKALI; hanya nilai telemetri yang dilaporkan yang kini
        # murni MA PV EnetAC (bisa > Plant Inj/PV wBESS saat beban kecil, mis.
        # 150 kW vs 45 kW pada beban 45 kW -- itulah yang diharapkan pengguna).
        _qraw_all = np.minimum(_pn * _sc, np.asarray(pinv, float))
        if _ma_win <= 1:
            _ma_tr_p = _qraw_all
        else:
            _csp = np.cumsum(_qraw_all, axis=0)
            _ma_tr_p = np.empty_like(_qraw_all)
            _ma_tr_p[:_ma_win] = _csp[:_ma_win] / _k[:_ma_win]
            if _nT > _ma_win:
                _ma_tr_p[_ma_win:] = (_csp[_ma_win:] - _csp[:-_ma_win]) \
                    / float(_ma_win)
        _ma_pv_pure = np.empty_like(_ma_tr_p)
        _ma_pv_pure[0] = _qraw_all[0]
        _ma_pv_pure[1:] = _ma_tr_p[:-1]
    _prev_dgn = None                    # DEG/Grid wPV langkah-1 (telemetri ramp)
    _prev_dga = None                    # DEG/Grid wPVBESS langkah-1
    _prev_pvb = None                    # PV only langkah-1
    _prev_pva = None                    # PV wBESS langkah-1
    _prev_plant = None                  # Plant Inj (PV+BESS neto) langkah-1
    _sp_prev = None                     # setpoint DISPATCH (dibatasi beban) langkah-1
                                         # -- basis ramp target dispatch (BUKAN injeksi
                                         # aktual), lihat blok Smoothing di bawah
    _sp_pure_prev = None                # setpoint TELEMETRI (MA murni PV EnetAC, tanpa
                                         # batas beban) langkah-1 -- basis ramp utk nilai
                                         # "MA Setpoint" yang dilaporkan/diekspor
    _firm_started = False               # Firming (PV Power): PV sudah > start hari ini
    _firm_ended = False                 # Firming (PV Power): PV sudah < end (sore) hari ini
    _firm_hod_prev = -1.0               # jam-of-day langkah-1 (deteksi ganti hari)
    _tou_split = _adv_on and _md['load_shift']            # akumulasi impor ToU
    lp = int(round(float(np.max(np.asarray(vals.get('load_priority', 0.0))))))
    split_lp = bool(np.max(np.asarray(
        vals.get('load_priority_split', 0.0), float)) > 0)
    lp_on = int(round(float(np.max(np.asarray(
        vals.get('load_priority_on', 0.0))))))
    lp_off = int(round(float(np.max(np.asarray(
        vals.get('load_priority_off', 2.0))))))
    cp = int(round(float(np.max(np.asarray(vals.get('charge_priority', 0.0))))))
    strict = bool(np.max(np.asarray(vals.get('strict_charge', 0.0), float)) > 0)
    gchg = np.asarray(vals.get('grid_charge_enabled', 1.0), float) > 0
    dchg = bool(np.max(np.asarray(vals.get('deg_charge_enabled', 0.0), float)) > 0)
    lmin_deg = np.asarray(vals.get('deg_min_loading', 0.0), float)
    deg_sync = bool(np.max(np.asarray(vals.get('deg_sync', 1.0), float)) > 0)
    deg_always = bool(np.max(np.asarray(vals.get('deg_always', 0.0), float)) > 0)
    ilock = bool(np.max(np.asarray(vals.get('deg_interlock', 1.0), float)) > 0)
    gilock = bool(np.max(np.asarray(vals.get('grid_interlock', 0.0),
                                    float)) > 0)
    dg_ilock = bool(np.max(np.asarray(
        vals.get('deg_grid_interlock', 1.0), float)) > 0)
    if ilock:
        dchg = False   # interlock: bus DEG terpisah -> mustahil charge BESS
    # --- Opsi DEG per status grid (deg_options_split) ---
    # Bila aktif, 'DEG Interlock with PV-BESS' dan 'Allow DEG Charging' dipilih
    # terpisah untuk grid tersedia (status 1) vs padam (status 0). Aturan
    # interlock -> charging OFF ditegakkan per regime. Bila nonaktif, kedua
    # regime memakai nilai global (ilock/dchg) -> byte-identik perilaku lama.
    deg_split = bool(np.max(np.asarray(
        vals.get('deg_options_split', 0.0), float)) > 0)
    il_on = bool(np.max(np.asarray(vals.get('deg_interlock_on', 1.0), float)) > 0)
    il_off = bool(np.max(np.asarray(vals.get('deg_interlock_off', 1.0), float)) > 0)
    dc_on = bool(np.max(np.asarray(vals.get('deg_charge_on', 0.0), float)) > 0)
    dc_off = bool(np.max(np.asarray(vals.get('deg_charge_off', 0.0), float)) > 0)
    if il_on:
        dc_on = False
    if il_off:
        dc_off = False
    # nilai efektif per regime (default ke global bila dimensi tak displit)
    lp_on_e, lp_off_e = (lp_on, lp_off) if split_lp else (lp, lp)
    il_on_e, il_off_e = (il_on, il_off) if deg_split else (ilock, ilock)
    dc_on_e, dc_off_e = (dc_on, dc_off) if deg_split else (dchg, dchg)
    # Izin "DEG mengisi BESS" untuk fitur DEG-selalu-nyala (aktif saat GRID
    # PADAM): ikuti toggle 'Allow DEG Charging to BESS'. Bila opsi displit,
    # pakai izin saat grid padam (dc_off). Interlock DEG–PV/BESS meniadakannya
    # (bus terpisah -> sudah tercermin di dchg/dc_off di atas). Ditangkap SEBELUM
    # loop agar tak tertimpa oleh shadowing 'dchg' di dalam loop regime.
    deg_chg_ok = dc_off if deg_split else dchg
    any_split = split_lp or deg_split
    has_bess = E > 0
    E_safe = np.where(has_bess, E, 1.0)       # hindari div-by-zero saat BESS 0

    vec = (N > 1) or (not isinstance(p, SystemParams))   # batch selalu vektor
    shape = (N,) if vec else ()
    Z = np.broadcast_to(vals['soc_init'] * E, shape).astype(float).copy() \
        if vec else float(np.asarray(vals['soc_init'] * E).reshape(-1)[0]) * np.ones(())

    zeros = np.zeros(shape) if vec else np.zeros(())
    acc = {k: zeros.copy() for k in (
        'load', 'pv_gen', 'pv_inv_out', 'pv_excess', 'chg', 'chg_pv', 'chg_grid',
        'chg_deg',
        'dhg', 'grid_import', 'grid_export', 'deg_energy', 'deg_hours',
        'deg_loading_sum', 'served_pvbs', 'served_grid', 'unserved',
        'deg1_energy', 'deg2_energy', 'deg3_energy',
        'grid_import_peak', 'grid_import_offpeak',
        'outage_hours_total',
        # Firming: WAKTU (jam) di dalam firming window di mana Plant Inj
        # BENAR-BENAR mencapai target ('firm_time_ok') vs TOTAL waktu firming
        # window ('firm_time_window') — dasar "Firming Target Met (%)" =
        # waktu tercapai / total waktu window (bukan energi; lihat kpi.py).
        # SENGAJA tak dianualisasi/diekstrapolasi (lihat optimization.py
        # _ENERGY_ACC/_STEP_ACC) — mencerminkan APA ADANYA jendela simulasi
        # yang dipilih pengguna. Nol di mode lain/Standard.
        'firm_time_ok', 'firm_time_window')}
    soc_lo = np.full(shape, np.inf) if vec else np.array(np.inf)
    soc_hi = np.full(shape, -np.inf) if vec else np.array(-np.inf)
    deg_cap_tot = deg1 + deg2 + deg3
    # Mode tidak sinkron: hanya SATU genset menyala -> kapabilitas maksimum =
    # genset TERBESAR (bukan jumlah). Dipakai untuk deg_cap_max di bawah.
    deg_cap_one = np.maximum(np.maximum(deg1, deg2), deg3)
    # DEG selalu nyala: genset grid-forming (baseload minimum-loading) yang
    # menyala lebih dulu. Pilihan pengguna 'deg_grid_former':
    #   0 = Auto  -> per jam pilih genset yang MINIMUM LOADING-nya PALING DEKAT
    #                ke beban (|cap·Lmin − beban| terkecil; seri -> kapasitas
    #                lebih kecil). Beban rendah -> genset kecil (paling mendekati
    #                minimum loadingnya).
    #   1/2/3 = DEG-1/2/3 (tetap). Pilihan tak valid (unit 0 kW) -> Auto.
    _capvals = [float(np.asarray(x).reshape(-1)[0]) for x in (deg1, deg2, deg3)]
    _pos = [i for i in range(3) if _capvals[i] > 0]
    _ismall = min(_pos, key=lambda i: _capvals[i]) if _pos else -1
    _gf = int(round(float(np.max(np.asarray(
        vals.get('deg_grid_former', 0.0), float))))) - 1   # 0-based; -1 = Auto
    _auto_gf = _gf not in _pos                             # True -> load-adaptive
    _iform = _gf if not _auto_gf else _ismall             # unit TETAP (non-auto)
    # masker & kapasitas grid-former TETAP (dipakai bila BUKAN auto)
    deg_small0 = (_iform == 0)
    deg_small1 = (_iform == 1)
    deg_small2 = (_iform == 2)
    deg_cap_small = _capvals[_iform] if _iform >= 0 else 0.0
    deg_has_any = _iform >= 0
    # floor tiap unit (kW) utk Auto load-adaptive: cap·Lmin
    _floor0 = deg1 * lmin_deg
    _floor1 = deg2 * lmin_deg
    _floor2 = deg3 * lmin_deg
    # --- Nilai NAMEPLATE (kapasitas terpasang) sebelum override 'DEG Status'
    # per-jam — dipakai utk RESET tiap langkah (lihat blok masking di awal
    # loop) agar override jam t-1 tak "nempel" ke jam t. deg_status=None ->
    # variabel di atas TAK PERNAH di-reset/di-mask -> byte-identik lama.
    deg1_base, deg2_base, deg3_base = deg1, deg2, deg3
    deg_cap_tot_base, deg_cap_one_base = deg_cap_tot, deg_cap_one
    deg_cap_small_base = deg_cap_small
    _floor0_base, _floor1_base, _floor2_base = _floor0, _floor1, _floor2

    rec = {k: np.zeros((T,) + shape) for k in (
        'pv', 'pv_inv_out', 'pv_excess', 'load', 'deg', 'grid', 'grid_export',
        'chg', 'dhg', 'bess_net', 'soc', 'unserved',
        'grid_load', 'grid_status', 'chg_pv', 'chg_grid', 'chg_deg',
        'deg1', 'deg2', 'deg3', 'pvbs_load', 'cap_start', 'cap_end',
        'dg_ramp_act', 'dg_ramp_smooth', 'pv_ramp_act', 'pv_ramp_smooth',
        'plant_inj', 'plant_inj_ramp', 'pv_before', 'pv_after',
        'ma_setpoint', 'deg_status')}   if record else None

    # --- Self consumption BESS (aux) — beban TAMBAHAN kW konstan selama BESS
    # terpasang. Pemasok (bess_sc_source): 0 = PV+BESS dulu (PV langsung, lalu
    # discharge BESS; sisa → Grid lalu DEG), 1 = DEG/Grid dulu (Grid, lalu DEG;
    # sisa → kelebihan PV lalu BESS). Tak terpenuhi semua → 'selfcons_uns'.
    # Nilai 0 (baku) → blok dilewati sepenuhnya (byte-identik perilaku lama).
    sc_kw = np.maximum(0.0, np.asarray(vals.get('bess_self_cons', 0.0), float))
    _sc_src = int(round(float(np.max(np.asarray(
        vals.get('bess_sc_source', 0.0), float)))))
    _sc_on = bool(np.any(sc_kw > 0)) and bool(np.any(has_bess))
    pinv_base, max_dhg_base = pinv, max_dhg
    for _k in ('selfcons', 'selfcons_pv', 'selfcons_bess', 'selfcons_grid',
               'selfcons_deg', 'selfcons_uns'):
        acc[_k] = zeros.copy()
    if record:
        rec['self_cons'] = np.zeros((T,) + shape)
        rec['self_cons_deg'] = np.zeros((T,) + shape)

    _pstep = max(1, T // 100)                 # lapor progres ~tiap 1%
    for t in range(T):
        if progress is not None and t % _pstep == 0:
            progress(t, T)
        ae = load[t]
        # --- 'DEG Status' per-jam (opsional, dari import Excel) ------------
        # 0 -> DEG TAK TERSEDIA jam ini: kapasitas SEMUA unit di-nol-kan
        # (persis spt outage/maintenance terjadwal) -- SELURUH cascade di
        # bawah (deg_cap_tot>0, need_deg, _deg_dispatch, blok must-run
        # deg_always, dll) otomatis melihat DEG sbg tak ada jam ini, murni
        # lewat variabel deg1/deg2/deg3 (& turunannya) yg di-shadow di sini.
        # != 0 (termasuk 'Auto'/1) -> tersedia spt biasa; nyala/tidaknya
        # TETAP murni keputusan dispatch normal (load priority/interlock),
        # bukan dipaksa. RESET ke nameplate tiap langkah (jangan sampai
        # override jam t-1 nempel ke jam t). deg_status=None -> blok ini
        # dilewati sepenuhnya -> byte-identik lama.
        if deg_status is not None:
            if deg_status[t] == 0.0:
                deg1 = deg2 = deg3 = 0.0
                deg_cap_tot = deg_cap_one = deg_cap_small = 0.0
                _floor0 = _floor1 = _floor2 = 0.0
            else:
                deg1, deg2, deg3 = deg1_base, deg2_base, deg3_base
                deg_cap_tot, deg_cap_one = deg_cap_tot_base, deg_cap_one_base
                deg_cap_small = deg_cap_small_base
                _floor0, _floor1, _floor2 = _floor0_base, _floor1_base, _floor2_base
        Lg = grid_status[t] * (Hg > 0)        # grid tersedia jam ini
        Hh = np.where(Lg > 0, Hg, Hg)         # kapasitas fisik tetap; L yang memutus
        q = pv_norm[t] * pv_scale
        # --- Self consumption BESS: pra-alokasi PV+BESS (sumber 0) ----------
        Z_start = Z
        _sc_t = _sc_pv = _sc_pvq = _sc_b = _sc_g = _sc_d = _sc_uns = 0.0
        if _sc_on:
            pinv = pinv_base
            max_dhg = max_dhg_base
            _sc_t = np.where(has_bess, sc_kw, 0.0) * np.ones_like(np.asarray(q, float))
            _sc_need = _sc_t
            if _sc_src == 0:
                # PV langsung (lewat inverter) → kapasitas PV & inverter yg
                # tersisa utk dispatch normal berkurang sebesar itu
                _sc_pv = np.minimum(_sc_t, np.maximum(0.0, np.minimum(q, pinv)))
                _sc_pvq = _sc_pv
                q = q - _sc_pv
                pinv = np.maximum(0.0, pinv - _sc_pv)
                # sisa → discharge BESS (SOC & PCS yg tersisa utk dispatch berkurang)
                _r = _sc_t - _sc_pv
                _sc_b = np.where(has_bess, np.minimum(np.minimum(_r, max_dhg),
                                 np.maximum(0.0, (Z - soc_min_e) / dt * srte)), 0.0)
                Z = Z - _sc_b * dt / srte
                max_dhg = np.maximum(0.0, max_dhg - _sc_b)
                _sc_need = _r - _sc_b
        # =====================================================================
        # PRA-PROSES SHAPING PV (Smoothing / Firming) — bentuk SETPOINT sp,
        # BESS mengisi selisih thd PV EnetAC, lalu sp jadi PENGGANTI PV EnetAC
        # untuk seluruh load-serving di bawah (DEG/Grid melayani beban − sp).
        #   Firming : sp = target konstan (input), malam (PV=0) → 0.
        #   Smoothing: sp = MA kausal PV EnetAC (opsional dibatasi ramp).
        # Plant Inj = sp (STRICT). Charge (sp<PV): injeksi tepat sp, kelebihan PV di
        # luar yg ter-charge DI-CURTAIL. Discharge (sp>PV): injeksi = PV + discharge
        # tercapai (turun di bawah sp hanya bila batre/PCS tak sanggup). RTE & PCS
        # lewat anggaran D/C. DEG/Grid melayani beban − injeksi (load priority sp→DEG).
        # =====================================================================
        _q_raw = q                             # PV EnetAC mentah (telemetri/pv_gen)
        _sf_on = _adv_post and (_md['pv_smooth'] or _md['firming'])
        _Xsf = 0.0; _Usf = 0.0                 # discharge/charge shaping (kW)
        if _sf_on:
            _qinv_r = np.minimum(_q_raw, pinv)
            _rfe = _md['resv_frac'] * (soc_max_e - soc_min_e)
            _flr = soc_min_e + np.where(_md['reserve'], _rfe, 0.0)
            _Dsf = np.where(has_bess, np.maximum(0.0, (Z - _flr) / dt * srte), 0.0)
            _Dsf = np.minimum(_Dsf, max_dhg)
            if _md['reserve']:
                _Dsf = np.maximum(0.0, _Dsf - _md['resv_kw'])
            _Csf = np.where(has_bess, np.maximum(0.0, (soc_max_e - Z) / dt / srte), 0.0)
            _Csf = np.minimum(_Csf, max_chg)
            if _md['firming']:                 # setpoint konstan dlm JENDELA firming
                _hod_sf = (t * dt) % 24.0       # jam-of-day (skalar)
                if _md['firm_trigger'] == 1:   # ---- Time: jendela [start,end) jam ----
                    _ts = _md['firm_t_start']; _te = _md['firm_t_end']
                    _fon = ((_hod_sf >= _ts) & (_hod_sf < _te) if _ts <= _te
                            else (_hod_sf >= _ts) | (_hod_sf < _te))
                    _fon = np.asarray(_fon)
                else:                          # ---- PV Power: mesin-status harian ----
                    if (t == 0) or (_hod_sf < _firm_hod_prev):   # ganti hari → reset
                        _firm_started = False; _firm_ended = False
                    # pagi: PV > start → MULAI (tetap on); sore: setelah mulai, PV <
                    # end → BERHENTI (tetap off) hingga reset tengah malam berikutnya.
                    _firm_started = np.asarray(_firm_started) | (_qinv_r > _md['firm_pv_start'])
                    _firm_ended = np.asarray(_firm_ended) | (
                        np.asarray(_firm_started) & (_qinv_r < _md['firm_pv_end']))
                    _fon = np.asarray(_firm_started) & (~np.asarray(_firm_ended))
                    _firm_hod_prev = _hod_sf
                # Butuh PV utk firming (malam/tanpa PV → 0). Di luar jendela: sp=0 →
                # (model strict) injeksi 0, PV dipakai CHARGE BESS saja.
                _fon = np.asarray(_fon) & (_qinv_r > 1e-9)
                _sp = np.where(_fon, np.asarray(_md['firming_kw'], float), 0.0)
                _sp_pure = _sp                 # Firming: target konstan sudah "murni"
                                               # (tak dibatasi beban) -> telemetri = _sp
            else:                              # smoothing: MA kausal (opsional +batas ramp)
                # basis Smoothing = PV dibatasi BEBAN SISA (di atas beban SISA
                # dicurtail LEBIH DULU, sebelum masuk logika smoothing/BESS sama
                # sekali — Smoothing hanya menghaluskan porsi PV yang harus
                # disuplai ke beban). Beban SISA = beban dikurangi porsi yang
                # SUDAH dijamin DEG (must-run grid-forming, lihat _ld_eff_all di
                # atas) — bila DEG sendiri sudah menanggung sebagian/seluruh
                # beban lewat floor minimum-loading-nya, PV/BESS tak perlu
                # (Smoothing tak perlu discharge utk) menanggung porsi itu lagi;
                # kelebihan PV langsung jadi kandidat charge BESS/curtail biasa,
                # bukan target MA. Di luar deg_always aktif, ld_eff==beban penuh
                # (tak berubah). Firming (di atas) TETAP pakai _qinv_r tanpa
                # batas beban — tak berubah.
                _ld_eff_t = _ld_eff_all[t] if _ld_eff_all is not None else ae
                _qinv_sm = np.minimum(_qinv_r, _ld_eff_t)
                _spr = np.asarray(_ma_pv[t] if _ma_pv is not None else _qinv_sm, float)
                # Basis batas ramp = SETPOINT (target) langkah SEBELUMNYA
                # (_sp_prev), BUKAN injeksi aktual yg terkirim (_I_inj lama).
                # MA Setpoint HARUS murni fungsi dari MA PV EnetAC + batas
                # ramp yg dikonfigurasi -- lepas sama sekali dari keterbatasan
                # SOC/PCS nyata. Bila basisnya dibiarkan ikut injeksi aktual,
                # kekurangan riil BESS di satu langkah (SOC/PCS mentok) akan
                # "menular" ke basis ramp langkah berikutnya, mencemari target
                # dgn keterbatasan nyata -- padahal target (Plant Inj/PV wBESS
                # TANPA batasan real) SEHARUSNYA boleh berbeda dari realisasi
                # (PV wBESS aktual) justru pada jam2 seperti itu (mis. beban
                # kecil & BESS sudah tak ada headroom SOC/PCS).
                _bs = _qinv_sm if _sp_prev is None else _sp_prev
                _upk = np.asarray(_md['pv_up_kwmin'], float) * (dt * 60.0)
                _dnk = np.asarray(_md['pv_dn_kwmin'], float) * (dt * 60.0)
                _hi = _bs + np.where(_upk > 0, _upk, np.inf)
                _lo = _bs - np.where(_dnk > 0, _dnk, np.inf)
                _sp = np.maximum(0.0, np.clip(_spr, _lo, _hi))
                # Setpoint TELEMETRI "MA Setpoint" = MA MURNI PV EnetAC (tanpa
                # batas beban) + batas ramp yang SAMA. Dihitung TERPISAH dari
                # _sp (dispatch, dibatasi beban) & TIDAK dipakai di dispatch
                # mana pun -- semata utk kolom "MA Setpoint" yang dilaporkan,
                # agar benar-benar hanya rata-rata bergerak PV EnetAC (lihat
                # precompute _ma_pv_pure di atas).
                _spr_pure = np.asarray(
                    _ma_pv_pure[t] if _ma_pv_pure is not None else _qinv_r, float)
                _bs_pure = _qinv_r if _sp_pure_prev is None else _sp_pure_prev
                _hi_p = _bs_pure + np.where(_upk > 0, _upk, np.inf)
                _lo_p = _bs_pure - np.where(_dnk > 0, _dnk, np.inf)
                _sp_pure = np.maximum(0.0, np.clip(_spr_pure, _lo_p, _hi_p))
            # Basis pembanding sp: SELALU PV EnetAC mentah (_qinv_r, tanpa batas
            # beban) utk KEDUA mode — persis rumus asal. Yang dibatasi beban SISA
            # hanyalah basis SETPOINT (_sp, di atas: precompute _ma_pv/_qinv_sm)
            # utk Smoothing. Efeknya: bila PV > beban SISA (sp kecil, PV besar),
            # gap = sp − PV sangat NEGATIF → BESS men-CHARGE selisihnya (sebatas
            # SOC/PCS, _Csf) alih-alih mengejar sp yang sudah rendah lewat
            # discharge; sisa yang BESS tak sanggup serap baru benar2 ter-curtail
            # (lihat _pv_inj/S/Texc di bawah). Bila PV < sp (baterai tak sanggup
            # capai target), discharge tetap bekerja spt biasa.
            _gap = _sp - _qinv_r
            _Xsf = np.maximum(0.0, np.minimum(_gap, _Dsf))       # sp>PV → discharge (SOC&PCS)
            _Usf = np.maximum(0.0, np.minimum(-_gap, _Csf))      # sp<PV → charge (SOC&PCS)
            # Plant Inj STRICT: charge (sp<PV) → injeksi tepat sp (kelebihan PV
            # charge BESS bila ada headroom, sisanya curtail); discharge (sp>PV)
            # → injeksi = PV + discharge tercapai (≤ sp, lihat catatan di atas).
            _I_inj = np.maximum(0.0, np.where(_gap >= 0.0, _qinv_r + _Xsf, _sp))
            if _md['pv_smooth'] and not _md['firming']:
                _sp_prev = _sp                # basis ramp dispatch langkah berikut
                                               # (bukan _I_inj aktual, lihat catatan di atas)
                _sp_pure_prev = _sp_pure      # basis ramp telemetri MA murni langkah berikut
            q = _I_inj                        # PV EFEKTIF utk load-serving = injeksi
            if _md['firming']:
                # Constraint UTAMA optimasi Firming: Plant Inj harus SELALU
                # capai target sepanjang jendela. "Firming Target Met (%)" =
                # WAKTU tercapai ÷ TOTAL waktu firming window (bukan energi):
                # shortfall = sisa gap yg TAK terpenuhi krn keterbatasan
                # SOC/PCS (nol pada sisi charge/surplus, sebab injeksi charge
                # selalu tepat = target); langkah dianggap 'tercapai' bila
                # shortfall ~ 0 (toleransi kecil utk galat pembulatan).
                _fshort = np.where(_gap >= 0.0, np.maximum(0.0, _gap - _Xsf), 0.0)
                _fok = np.asarray(_fon) & (_fshort <= 1e-6)
                acc['firm_time_window'] += np.where(_fon, dt, 0.0)
                acc['firm_time_ok'] += np.where(_fok, dt, 0.0)

        # =====================================================================
        # Backup: BESS (+PV bila tersedia) mengambil alih PENUH pelayanan beban
        # saat outage TOTAL jam ini (Grid DAN DEG sama-sama tak tersedia) --
        # mengesampingkan Smoothing/Firming (bila dikombinasikan) kapan pun
        # outage terjadi, siang maupun malam. Di luar outage: TAK berbuat
        # apa-apa di sini -- BESS tetap boleh charge dari surplus PV lewat
        # peran co-dispatch 'backup' biasa (lihat bess_modes._backup, dipanggil
        # di codispatch() di bawah) agar siap utk outage berikutnya, TAPI tak
        # pernah discharge di luar outage (spt diminta: "BESS discharge hanya
        # ketika DEG/Grid outage").
        # =====================================================================
        _bk_on = _adv_post and _md['backup']
        if _bk_on:
            _qinv_bk = np.minimum(_q_raw, pinv)
            _bk_grid_down = (grid_status[t] == 0) | (Hg <= 0)
            _bk_deg_down = deg_cap_tot <= 1e-9
            _bk_outage = np.asarray(_bk_grid_down) & np.asarray(_bk_deg_down)
            # Anggaran discharge: PENUH (abaikan floor SOC & reserve_kw) bila
            # Priority Backup menang atas Priority Reserve (_md['backup_beats_
            # reserve'], lihat penjelasan di atas); selain itu tetap hormati
            # floor & reserve_kw spt mode co-dispatch lain.
            _bk_floor = np.where(
                _md['backup_beats_reserve'], soc_min_e,
                soc_min_e + np.where(_md['reserve'], _resv_e, 0.0))
            _Dbk = np.where(has_bess, np.maximum(
                0.0, (Z - _bk_floor) / dt * srte), 0.0)
            _Dbk = np.minimum(_Dbk, max_dhg)
            if not _md['backup_beats_reserve']:
                _Dbk = np.maximum(0.0, _Dbk - np.where(
                    _md['reserve'], _md['resv_kw'], 0.0))
            _Cbk = np.where(has_bess, np.maximum(
                0.0, (soc_max_e - Z) / dt / srte), 0.0)
            _Cbk = np.minimum(_Cbk, max_chg)
            _gap_bk = ae - _qinv_bk       # >0 kurang (discharge); <0 surplus (charge)
            _Xbk = np.where(_bk_outage, np.minimum(
                np.maximum(0.0, _gap_bk), _Dbk), 0.0)
            _Ubk = np.where(_bk_outage, np.minimum(
                np.maximum(0.0, -_gap_bk), _Cbk), 0.0)
            # Plant Inj STRICT spt Smoothing/Firming: kekurangan (gap>=0) → PV+
            # discharge (≤ beban); surplus (gap<0) → tepat beban (kelebihan PV
            # charge BESS/curtail, bukan diinjeksi lebih dari beban).
            _I_inj_bk = np.where(_gap_bk >= 0.0,
                                 np.minimum(ae, _qinv_bk + _Xbk), ae)
            q = np.where(_bk_outage, _I_inj_bk, q)
            # Outage → Backup MENGGANTIKAN (bukan menambah) shaping Smoothing/
            # Firming jam itu (sudah dihitung di atas bila _sf_on) — override
            # penuh sesuai spesifikasi ("Backup override penuh kapan pun outage").
            _Xsf = np.where(_bk_outage, _Xbk, _Xsf)
            _Usf = np.where(_bk_outage, _Ubk, _Usf)
            if _sf_on:
                # sinkronkan variabel shaping yg dipakai blok S/Texc/telemetri
                # di bawah (~baris 1546+) agar konsisten dgn override outage.
                _qinv_r = np.where(_bk_outage, _qinv_bk, _qinv_r)
                _I_inj = np.where(_bk_outage, _I_inj_bk, _I_inj)
                _sp = np.where(_bk_outage, _I_inj_bk, _sp)

        d_pot = np.maximum(0.0, (Z - soc_min_e) / dt * srte)
        d_pot = np.where(has_bess, d_pot, 0.0)
        grid_off = (grid_status[t] == 0) | (Hg <= 0)
        head_chg = np.maximum(0.0, (soc_max_e - Z) / dt / srte)
        head_chg = np.where(has_bess, head_chg, 0.0)
        # EMS multi-mode (Advanced): BESS dikendalikan penuh oleh co-dispatch
        # prioritas (pasca-proses). Nonaktifkan dispatch BESS baku agar tak
        # bentrok; seluruh charge/discharge dihitung blok multi-mode di bawah.
        if _adv_post:
            d_pot = np.zeros_like(d_pot)
            head_chg = np.zeros_like(head_chg)

        deg_cap_max = (deg_cap_tot if deg_sync else deg_cap_one) * d1max
        #             sync: Σ Di·Lmax ; tak sinkron: max(Di)·Lmax (satu genset)
        # Kapabilitas nyata tiap bus pada jam ini (dipakai untuk menilai
        # 'sanggup atau tidak'): PV dibatasi inverter, BESS dibatasi PCS.
        pv_cap = np.minimum(q, pinv)
        d_cap = np.minimum(d_pot, max_dhg)

        def _grid_serve(rem):
            """Pasokan grid ke beban: minimum loading dihormati, namun
            tidak pernah melebihi sisa beban yang memang perlu dilayani."""
            rem = np.maximum(np.asarray(rem, float), 0.0)
            return np.minimum(
                np.maximum(gmin * Hg, np.minimum(gmax * Hg, rem)), rem)

        # --- Interlock DEG–Grid: bus grid dan bus genset saling kunci
        # (seperti transfer switch). Bila grid + PV/BESS tidak sanggup
        # memikul beban jam ini, sistem BERALIH ke genset: grid dilepas
        # dan genset memikul beban — bukan membiarkan beban tak terlayani.
        if dg_ilock and not any_split and lp not in (4, 5):
            grid_cap_t = np.where(grid_off, 0.0, gmax * Hg)
            if gilock:
                # grid & PV-BESS juga saling kunci -> tidak bisa dijumlahkan;
                # yang menentukan adalah bus terkuat di antara keduanya
                other_cap = np.maximum(grid_cap_t, pv_cap + d_cap)
            else:
                other_cap = grid_cap_t + pv_cap + d_cap
            transfer = ((~grid_off) & (deg_cap_tot > 0)
                        & (other_cap < ae - 1e-9))
            grid_off = grid_off | transfer


        def _strict_charge(Vc, Wc):
            """Mode strict: sumber prioritas kedua menunggu — grid tidak
            mengisi selama PV masih mengisi (PV→Grid), atau sebaliknya."""
            if not strict:
                return Vc, Wc
            if cp == 0:
                return Vc, np.where(Vc > 1e-9, 0.0, Wc)
            return np.where(Wc > 1e-9, 0.0, Vc), Wc

        def _deg_charge(base_kw, on_mask, Vc, Wc, x_now=None):
            """Charge dari DEG HANYA untuk mengangkat genset ke minimum
            loading-nya (mencegah operasi di bawah Lmin). Unit yang menyala
            mengikuti tahap alokasi; kekurangan terhadap Σ(D_run)·Lmin
            dialihkan ke BESS sebatas limit charge & headroom SOC."""
            if not dchg:
                return np.zeros_like(np.asarray(base_kw, float))
            if deg_sync:
                th1 = deg1 * d1max
                th2 = (deg1 + deg2) * d1max
                run_cap = np.where(base_kw <= th1, deg1,
                                   np.where(base_kw <= th2, deg1 + deg2,
                                            deg_cap_tot))
            else:                         # tidak sinkron: satu genset menyala
                run_cap = _deg_run_cap_nosync(base_kw, deg1, deg2, deg3, d1max)
            deficit = np.maximum(0.0, run_cap * lmin_deg - base_kw)
            gate = on_mask & has_bess
            if x_now is not None:      # tak boleh charge saat discharge
                gate = gate & (np.asarray(x_now) <= 0)
            return np.where(gate, np.maximum(0.0, np.minimum(np.minimum(
                deficit, np.maximum(max_chg - Vc - Wc, 0.0)),
                np.maximum(head_chg - Vc - Wc, 0.0))), 0.0)

        # Skenario per status grid: load priority (lp) dan/atau opsi DEG
        # (interlock PV-BESS, DEG charging) bisa berbeda saat grid tersedia
        # (status 1) vs padam (status 0). Bila salah satu split aktif, hitung
        # kedua regime — masing-masing membawa (lp, ilock, dchg) sendiri — lalu
        # pilih per jam menurut grid_off. Bila tidak, sekali jalan.
        __regimes = ([(lp_on_e, il_on_e, dc_on_e), (lp_off_e, il_off_e, dc_off_e)]
                     if any_split else [(lp, ilock, dchg)])
        __caps = []
        for lp, ilock, dchg in __regimes:
            if gilock:
                # ================= Grid INTERLOCK dengan PV-BESS =================
                # Beban dilayani Grid ATAU PV-BESS secara eksklusif (bus terpisah).
                # Pemilihan sumber MENGIKUTI Load Supply Priority:
                #   * mode 'Grid -> ...'  : grid diutamakan selama sanggup
                #     memikul seluruh beban jam itu;
                #   * mode 'PV -> ...'    : PV-BESS diutamakan selama sanggup.
                # Saat grid padam, PV-BESS (lalu DEG) yang memikul.
                pvbs_able = (pv_cap + d_cap) >= (ae - 1e-12)
                # Bus grid dianggap sanggup bila grid — DITAMBAH genset saat DEG
                # boleh paralel dengan grid — mampu memikul beban jam itu.
                firm_cap = np.where(grid_off, 0.0, gmax * Hg)
                if not dg_ilock:
                    firm_cap = firm_cap + deg_cap_max
                grid_able = (~grid_off) & (firm_cap >= (ae - 1e-12))
                if lp in (1, 3, 5):               # Grid lebih dulu
                    serve_pvbs = (~grid_able) & (pvbs_able | grid_off)
                else:                             # PV-BESS lebih dulu
                    serve_pvbs = pvbs_able | grid_off
                pv_load_p = np.minimum(pv_cap, ae)
                x_p = np.maximum(0.0, np.minimum(
                    np.minimum(np.maximum(ae - pv_load_p, 0.0), max_dhg), d_pot))
                ad_g = np.where(grid_off, 0.0, _grid_serve(ae))

                pv_to_load = np.where(serve_pvbs, pv_load_p, 0.0)
                X = np.where(serve_pvbs, x_p, 0.0)
                AC = pv_to_load + X
                AD = np.where(serve_pvbs, 0.0, ad_g)
                resid = np.maximum(0.0, ae - AC - AD)
                need_deg = (resid > 1e-9) & (deg_cap_tot > 0)
                if dg_ilock:      # DEG tidak boleh paralel dengan grid
                    need_deg = need_deg & (grid_off | serve_pvbs)
                if ilock:      # DEG eksklusif terhadap PV-BESS
                    excl = need_deg
                    pv_to_load = np.where(excl, 0.0, pv_to_load)
                    X = np.where(excl, 0.0, X)
                    AC = np.where(excl, 0.0, AC)
                    if dg_ilock:          # grid pun dilepas (DEG memikul semua)
                        AD = np.where(excl, 0.0, AD)
                    else:                 # grid tetap memasok porsinya
                        AD = np.where(excl & (~grid_off), ad_g, AD)
                    base_req = np.where(excl,
                                        np.maximum(0.0, ae - AD), 0.0)
                else:
                    base_req = np.where(need_deg, resid, 0.0)
                # headroom grid hanya bila bus grid tersambung (grid melayani beban)
                J = np.where(grid_off | serve_pvbs, 0.0,
                             np.maximum(0.0, gmax * Hg - AD))
                inv_head = np.maximum(0.0, pinv - pv_to_load)
                v_avail = np.maximum(0.0, q - pv_to_load)
                soc_ok = (gchg & (~grid_off) & (~serve_pvbs)
                          & (Z / E_safe < chg_soc) & has_bess)
                if cp == 0:
                    V = np.maximum(0.0, np.minimum(np.minimum(v_avail, max_chg),
                                                   np.minimum(head_chg, inv_head)))
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(np.minimum(
                            J, np.maximum(max_chg - V, 0.0)),
                            np.maximum(head_chg - V, 0.0))), 0.0)
                else:
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(
                            np.minimum(J, max_chg), head_chg)), 0.0)
                    V = np.maximum(0.0, np.minimum(np.minimum(
                            v_avail, np.maximum(max_chg - W, 0.0)),
                            np.minimum(np.maximum(head_chg - W, 0.0), inv_head)))
                V, W = _strict_charge(V, W)
                Cd = _deg_charge(base_req, need_deg, V, W, X)
                deg_req = np.where(need_deg, base_req + Cd, 0.0)
                m, n_, o = _deg_dispatch(deg_req, need_deg, deg1, deg2, deg3,
                                         d1max, sync=deg_sync)
                P = m + n_ + o
                deg_on = P > 0
                deg_load = P - Cd
                pv_direct = pv_to_load
            elif lp == 0 and ilock:
                # ---- Mode A (PV → Grid → BESS → DEG) + interlock PV-BESS ----
                #  DEG interlock grid  : DEG hanya saat grid padam, memikul
                #                        SELURUH beban.
                #  DEG paralel grid    : DEG menyala bila PV+BESS+grid tak
                #                        sanggup; grid tetap memikul porsinya
                #                        dan DEG menutup sisanya.
                grid_cap = np.where(grid_off, 0.0, gmax * Hg)
                if dg_ilock:
                    need_deg = (grid_off & ((pv_cap + d_cap) < ae)
                                & (deg_cap_tot > 0))
                    ad_deg = np.zeros_like(np.asarray(ae, float))
                else:
                    # rantai PV → Grid → DEG → BESS: genset dipakai sebelum
                    # BESS, jadi kesanggupan dinilai TANPA potensi discharge
                    need_deg = (((pv_cap + grid_cap) < ae - 1e-9)
                                & (deg_cap_tot > 0))
                    ad_deg = np.where(grid_off, 0.0, _grid_serve(ae))
                deg_base = np.maximum(0.0, ae - ad_deg)
                m, n_, o = _deg_dispatch(deg_base, need_deg,
                                         deg1, deg2, deg3, d1max, sync=deg_sync)
                P = m + n_ + o
                deg_on = P > 0
                x_need = np.where(pv_cap < ae,
                                  np.maximum(0.0, (ae - pv_cap)
                                             - np.where(grid_off, 0.0,
                                                        gmax * Hg)),
                                  0.0)
                X = np.where(deg_on, 0.0,
                             np.maximum(0.0, np.minimum(np.minimum(x_need, max_dhg), d_pot)))
                AC = np.where(deg_on, 0.0,
                              np.where(grid_off,
                                       np.minimum(ae, pv_cap + X),
                                       np.minimum(ae - gmin * Hg,
                                                  pv_cap + X)))
                AC = np.maximum(AC, 0.0)
                AD = np.where(deg_on, ad_deg,
                              np.where(grid_off, 0.0, _grid_serve(ae - AC)))
                J = np.where(grid_off, 0.0, np.maximum(0.0, Hg * gmax - AD))
                # PV yang tersalur ke beban & sisa kapasitas inverter untuk charge
                pv_to_load = np.where(deg_on, 0.0, np.maximum(0.0, AC - X))
                inv_head = np.maximum(0.0, pinv - pv_to_load)
                v_avail = np.where(deg_on, q,
                                   np.maximum(0.0, q - np.where(grid_off, ae,
                                       np.maximum(0.0, ae - gmin * Hg))))
                V = np.maximum(0.0, np.minimum(np.minimum(v_avail, max_chg),
                                               np.minimum(head_chg, inv_head)))
                w_lim = np.where(deg_on, Hg * gmax, J)
                soc_ok = gchg & (~grid_off) & (Z / E_safe < chg_soc) & has_bess
                if cp == 0:      # PV lebih dulu, grid mengisi sisa kapasitas
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(np.minimum(
                            w_lim, np.maximum(max_chg - V, 0.0)),
                            np.maximum(head_chg - V, 0.0))), 0.0)
                else:            # grid lebih dulu, PV mengisi sisa
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(
                            np.minimum(w_lim, max_chg), head_chg)), 0.0)
                    V = np.maximum(0.0, np.minimum(np.minimum(
                            v_avail, np.maximum(max_chg - W, 0.0)),
                            np.minimum(np.maximum(head_chg - W, 0.0), inv_head)))
                V, W = _strict_charge(V, W)
                Cd = _deg_charge(np.where(deg_on, deg_base, 0.0), deg_on, V, W, X)
                deg_req = np.where(need_deg, deg_base + Cd, 0.0)
                m, n_, o = _deg_dispatch(deg_req, need_deg, deg1, deg2, deg3,
                                         d1max, sync=deg_sync)
                P = m + n_ + o
                deg_load = P - Cd
                pv_direct = pv_to_load
            elif lp == 0:
                # ---- Mode A tanpa interlock: saat grid padam DEG hanya menutup residu,
                #      PV & BESS tetap melayani beban paralel dengan DEG ----
                if dg_ilock:
                    # rantai PV → Grid → BESS → DEG (DEG hanya saat grid padam)
                    pvdA = np.where(grid_off, np.minimum(pv_cap, ae), 0.0)
                    x_off = np.maximum(0.0, np.minimum(np.minimum(
                                np.maximum(ae - pvdA, 0.0), max_dhg), d_pot))
                    x_on = np.where(pv_cap < ae,
                                    np.maximum(0.0, (ae - pv_cap)
                                               - gmax * Hg), 0.0)
                    X = np.where(grid_off, x_off,
                                 np.maximum(0.0, np.minimum(np.minimum(
                                     x_on, max_dhg), d_pot)))
                    r = np.where(grid_off, np.maximum(0.0, ae - pvdA - X), 0.0)
                    AC = np.where(grid_off, pvdA + X,
                                  np.maximum(0.0, np.minimum(
                                      ae - gmin * Hg, pv_cap + X)))
                    AD = np.where(grid_off, 0.0, _grid_serve(ae - AC))
                else:
                    # rantai PV → Grid → DEG → BESS: genset boleh paralel dengan
                    # grid dan dipakai SEBELUM BESS
                    pv_l = np.where(grid_off, np.minimum(pv_cap, ae),
                                    np.minimum(pv_cap,
                                               np.maximum(0.0,
                                                          ae - gmin * Hg)))
                    AD = np.where(grid_off, 0.0, _grid_serve(ae - pv_l))
                    rem = np.maximum(0.0, ae - pv_l - AD)
                    r = np.minimum(rem, deg_cap_max)          # porsi genset
                    rem2 = np.maximum(0.0, rem - r)
                    X = np.maximum(0.0, np.minimum(np.minimum(rem2, max_dhg),
                                                   d_pot))
                    pvdA = pv_l
                    AC = pv_l + X
                need_deg = (r > 1e-12) & (deg_cap_tot > 0)
                J = np.where(grid_off, 0.0, np.maximum(0.0, Hg * gmax - AD))
                pv_to_load = np.where(grid_off, pvdA, np.maximum(0.0, AC - X))
                inv_head = np.maximum(0.0, pinv - pv_to_load)
                v_avail = np.where(grid_off, np.maximum(0.0, q - pvdA),
                                   np.maximum(0.0, q - np.maximum(0.0, ae - gmin * Hg)))
                V = np.maximum(0.0, np.minimum(np.minimum(v_avail, max_chg),
                                               np.minimum(head_chg, inv_head)))
                soc_ok = gchg & (~grid_off) & (Z / E_safe < chg_soc) & has_bess
                if cp == 0:      # PV lebih dulu, grid mengisi sisa kapasitas
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(np.minimum(
                            J, np.maximum(max_chg - V, 0.0)),
                            np.maximum(head_chg - V, 0.0))), 0.0)
                else:            # grid lebih dulu, PV mengisi sisa
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(
                            np.minimum(J, max_chg), head_chg)), 0.0)
                    V = np.maximum(0.0, np.minimum(np.minimum(
                            v_avail, np.maximum(max_chg - W, 0.0)),
                            np.minimum(np.maximum(head_chg - W, 0.0), inv_head)))
                V, W = _strict_charge(V, W)
                Cd = _deg_charge(r, need_deg, V, W, X)
                deg_req = np.where(need_deg, r + Cd, 0.0)
                m, n_, o = _deg_dispatch(deg_req, need_deg, deg1, deg2, deg3,
                                         d1max, sync=deg_sync)
                P = m + n_ + o
                deg_on = P > 0
                deg_load = P - Cd
                pv_direct = pv_to_load
            elif lp == 1:
                # ------- Mode B -------
                #  DEG interlock grid : Grid → PV → BESS → DEG
                #  DEG paralel grid   : Grid → DEG → PV → BESS
                AD = np.where(grid_off, 0.0, _grid_serve(ae))
                r1 = np.maximum(0.0, ae - AD)
                if dg_ilock:
                    pv_direct = np.minimum(pv_cap, r1)
                    r2 = np.maximum(0.0, r1 - pv_direct)
                    X = np.maximum(0.0, np.minimum(np.minimum(r2, max_dhg), d_pot))
                    r3 = np.maximum(0.0, r2 - X)
                    need_deg = ((r3 > 1e-12) & (deg_cap_tot > 0)
                                & grid_off)   # DEG hanya saat grid tak tersedia
                else:
                    r3 = np.minimum(r1, deg_cap_max)          # genset lebih dulu
                    rem = np.maximum(0.0, r1 - r3)
                    pv_direct = np.minimum(pv_cap, rem)
                    rem2 = np.maximum(0.0, rem - pv_direct)
                    X = np.maximum(0.0, np.minimum(np.minimum(rem2, max_dhg),
                                                   d_pot))
                    need_deg = (r3 > 1e-12) & (deg_cap_tot > 0)
                if ilock:
                    # interlock: DEG eksklusif terhadap PV-BESS. Grid tetap
                    # memasok porsinya bila DEG boleh paralel dengan grid.
                    excl = need_deg
                    if dg_ilock:
                        AD = np.where(excl, 0.0, AD)
                    pv_direct = np.where(excl, 0.0, pv_direct)
                    X = np.where(excl, 0.0, X)
                    base_req = np.where(excl, np.maximum(0.0, ae - AD), 0.0)
                else:
                    base_req = np.where(need_deg, r3, 0.0)
                AC = pv_direct + X
                J = np.where(grid_off, 0.0, np.maximum(0.0, Hg * gmax - AD))
                surplus = np.maximum(0.0, q - pv_direct)
                soc_ok = gchg & (~grid_off) & (Z / E_safe < chg_soc) & has_bess
                inv_head = np.maximum(0.0, pinv - pv_direct)
                if cp == 0:
                    V = np.maximum(0.0, np.minimum(np.minimum(surplus, max_chg),
                                                   np.minimum(head_chg, inv_head)))
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(np.minimum(
                            J, np.maximum(max_chg - V, 0.0)),
                            np.maximum(head_chg - V, 0.0))), 0.0)
                else:
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(
                            np.minimum(J, max_chg), head_chg)), 0.0)
                    V = np.maximum(0.0, np.minimum(np.minimum(
                            surplus, np.maximum(max_chg - W, 0.0)),
                            np.minimum(np.maximum(head_chg - W, 0.0), inv_head)))
                V, W = _strict_charge(V, W)
                Cd = _deg_charge(base_req, need_deg, V, W, X)
                deg_req = np.where(need_deg, base_req + Cd, 0.0)
                m, n_, o = _deg_dispatch(deg_req, need_deg, deg1, deg2, deg3,
                                         d1max, sync=deg_sync)
                P = m + n_ + o
                deg_on = P > 0
                deg_load = P - Cd
            elif lp == 3:
                # ---- Mode B (paralel): Grid → PV → BESS → DEG ----
                #  Hanya ditawarkan saat DEG TIDAK interlock dengan grid
                #  (dg_ilock False). Grid memikul beban lebih dulu (hormati
                #  min/max loading), PV lalu BESS menutup sisanya, dan genset
                #  menjadi cadangan TERAKHIR — namun boleh menyala PARALEL
                #  dengan grid untuk menutup kekurangan yang tak sanggup
                #  dipikul grid + PV + BESS. Berbeda dari 'Grid → PV → BESS →
                #  DEG' saat DEG interlock grid (kode 1, dg_ilock), yang hanya
                #  menyalakan genset ketika grid padam.
                AD = np.where(grid_off, 0.0, _grid_serve(ae))
                r1 = np.maximum(0.0, ae - AD)
                pv_direct = np.minimum(pv_cap, r1)
                r2 = np.maximum(0.0, r1 - pv_direct)
                X = np.maximum(0.0, np.minimum(np.minimum(r2, max_dhg), d_pot))
                r3 = np.maximum(0.0, r2 - X)
                need_deg = (r3 > 1e-12) & (deg_cap_tot > 0)   # boleh paralel grid
                if ilock:
                    # DEG eksklusif terhadap PV-BESS; grid tetap memasok
                    # porsinya (DEG paralel grid, grid tidak dilepas).
                    excl = need_deg
                    pv_direct = np.where(excl, 0.0, pv_direct)
                    X = np.where(excl, 0.0, X)
                    base_req = np.where(excl, np.maximum(0.0, ae - AD), 0.0)
                else:
                    base_req = np.where(need_deg, r3, 0.0)
                AC = pv_direct + X
                J = np.where(grid_off, 0.0, np.maximum(0.0, Hg * gmax - AD))
                surplus = np.maximum(0.0, q - pv_direct)
                soc_ok = gchg & (~grid_off) & (Z / E_safe < chg_soc) & has_bess
                inv_head = np.maximum(0.0, pinv - pv_direct)
                if cp == 0:
                    V = np.maximum(0.0, np.minimum(np.minimum(surplus, max_chg),
                                                   np.minimum(head_chg, inv_head)))
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(np.minimum(
                            J, np.maximum(max_chg - V, 0.0)),
                            np.maximum(head_chg - V, 0.0))), 0.0)
                else:
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(
                            np.minimum(J, max_chg), head_chg)), 0.0)
                    V = np.maximum(0.0, np.minimum(np.minimum(
                            surplus, np.maximum(max_chg - W, 0.0)),
                            np.minimum(np.maximum(head_chg - W, 0.0), inv_head)))
                V, W = _strict_charge(V, W)
                Cd = _deg_charge(base_req, need_deg, V, W, X)
                deg_req = np.where(need_deg, base_req + Cd, 0.0)
                m, n_, o = _deg_dispatch(deg_req, need_deg, deg1, deg2, deg3,
                                         d1max, sync=deg_sync)
                P = m + n_ + o
                deg_on = P > 0
                deg_load = P - Cd
            elif lp == 4:
                # ---- Mode Auto by Grid Status ----
                #  Strategi berpindah otomatis tiap jam menurut ketersediaan grid:
                #  GRID TERSEDIA : beban Grid → DEG → PV → BESS (genset membantu
                #     bila beban > grid), charge Grid → PV (sisa grid mengisi
                #     BESS); grid, DEG, PV, BESS boleh paralel (tanpa interlock).
                #  GRID PADAM    : beban PV → BESS → DEG dengan DEG interlock
                #     PV-BESS (saat genset menyala ia memikul seluruh beban, PV
                #     hanya mengisi BESS, BESS tidak discharge), charge PV saja.
                #  Hanya berlaku saat DEG tidak interlock grid (dg_ilock False).

                # ===== Regime A — grid tersedia: Grid → DEG → PV → BESS =====
                AD_on = _grid_serve(ae)
                rA1 = np.maximum(0.0, ae - AD_on)
                degA = np.minimum(rA1, deg_cap_max)            # DEG kedua (paralel)
                remA = np.maximum(0.0, rA1 - degA)
                pv_onL = np.minimum(pv_cap, remA)              # PV ketiga
                remA2 = np.maximum(0.0, remA - pv_onL)
                X_on = np.maximum(0.0, np.minimum(np.minimum(remA2, max_dhg),
                                                  d_pot))       # BESS keempat
                need_on = (degA > 1e-12) & (deg_cap_tot > 0)
                base_on = np.where(need_on, degA, 0.0)
                AC_on = pv_onL + X_on
                J_on = np.maximum(0.0, Hg * gmax - AD_on)      # sisa kapasitas grid
                inv_head_on = np.maximum(0.0, pinv - pv_onL)
                surplus_on = np.maximum(0.0, q - pv_onL)
                soc_ok_on = gchg & (Z / E_safe < chg_soc) & has_bess
                # charge priority Grid → PV: grid mengisi BESS lebih dulu
                W_on = np.where(soc_ok_on, np.maximum(0.0, np.minimum(
                    np.minimum(J_on, max_chg), head_chg)), 0.0)
                V_on = np.maximum(0.0, np.minimum(np.minimum(
                    surplus_on, np.maximum(max_chg - W_on, 0.0)),
                    np.minimum(np.maximum(head_chg - W_on, 0.0), inv_head_on)))
                # strict: sumber prioritas kedua menunggu. Regime ini memakai
                # urutan tetap Grid → PV (charge), jadi PV menunggu selama grid
                # masih mengisi BESS. Tanpa strict, keduanya boleh paralel
                # (perilaku default 'Auto' — byte-identik saat strict off).
                if strict:
                    V_on = np.where(W_on > 1e-9, 0.0, V_on)
                Cd_on = _deg_charge(base_on, need_on, V_on, W_on, X_on)

                # ===== Regime B — grid padam: PV → BESS → DEG (interlock) =====
                pv_off0 = np.minimum(pv_cap, ae)               # PV pertama
                x_needB = np.maximum(0.0, ae - pv_off0)
                X_off0 = np.maximum(0.0, np.minimum(np.minimum(x_needB, max_dhg),
                                                    d_pot))     # BESS kedua
                # DEG interlock PV-BESS: genset menyala hanya bila PV+BESS tak
                # sanggup memikul beban, lalu memikul SELURUH beban (eksklusif).
                need_off = ((pv_cap + d_cap) < ae - 1e-9) & (deg_cap_tot > 0)
                pv_offL = np.where(need_off, 0.0, pv_off0)
                X_off = np.where(need_off, 0.0, X_off0)
                base_off = np.where(need_off, np.asarray(ae, float), 0.0)
                AC_off = pv_offL + X_off
                inv_head_off = np.maximum(0.0, pinv - pv_offL)
                surplus_off = np.maximum(0.0, q - pv_offL)
                V_off = np.maximum(0.0, np.minimum(np.minimum(surplus_off, max_chg),
                                                   np.minimum(head_chg,
                                                              inv_head_off)))
                W_off = np.zeros_like(np.asarray(V_off, float))
                Cd_off = _deg_charge(base_off, need_off, V_off, W_off, X_off)

                # ===== gabungkan menurut status grid tiap jam =====
                AD = np.where(grid_off, 0.0, AD_on)
                pv_direct = np.where(grid_off, pv_offL, pv_onL)
                X = np.where(grid_off, X_off, X_on)
                AC = np.where(grid_off, AC_off, AC_on)
                need_deg = np.where(grid_off, need_off, need_on)
                base_req = np.where(grid_off, base_off, base_on)
                J = np.where(grid_off, 0.0, J_on)
                V = np.where(grid_off, V_off, V_on)
                W = np.where(grid_off, W_off, W_on)
                Cd = np.where(grid_off, Cd_off, Cd_on)
                deg_req = np.where(need_deg, base_req + Cd, 0.0)
                m, n_, o = _deg_dispatch(deg_req, need_deg, deg1, deg2, deg3,
                                         d1max, sync=deg_sync)
                P = m + n_ + o
                deg_on = P > 0
                deg_load = P - Cd
            elif lp == 5:
                # ---- Mode Grid → PV → BESS → DEG, interlock DEG↔PV-BESS
                #      HANYA saat grid padam ----
                #  Grid ADA  : grid → PV → BESS → DEG, genset boleh paralel
                #     penuh dengan Grid & PV-BESS (hanya menutup kekurangan yang
                #     tak sanggup dipikul grid+PV+BESS).
                #  Grid PADAM: PV → BESS → DEG dengan DEG interlock PV-BESS —
                #     begitu genset menyala ia memikul SELURUH beban, PV hanya
                #     mengisi BESS, BESS tidak discharge.
                #  Hanya berlaku saat DEG tidak interlock grid (dg_ilock False).
                AD = np.where(grid_off, 0.0, _grid_serve(ae))
                r1 = np.maximum(0.0, ae - AD)
                pv_direct = np.minimum(pv_cap, r1)
                r2 = np.maximum(0.0, r1 - pv_direct)
                X = np.maximum(0.0, np.minimum(np.minimum(r2, max_dhg), d_pot))
                r3 = np.maximum(0.0, r2 - X)
                need_deg = (r3 > 1e-12) & (deg_cap_tot > 0)
                # Interlock PV-BESS hanya saat grid padam; saat grid ada DEG
                # paralel penuh dengan Grid & PV-BESS.
                excl = need_deg & grid_off
                pv_direct = np.where(excl, 0.0, pv_direct)
                X = np.where(excl, 0.0, X)
                base_req = np.where(excl, np.maximum(0.0, ae - AD),
                                    np.where(need_deg, r3, 0.0))
                AC = pv_direct + X
                J = np.where(grid_off, 0.0, np.maximum(0.0, Hg * gmax - AD))
                surplus = np.maximum(0.0, q - pv_direct)
                soc_ok = gchg & (~grid_off) & (Z / E_safe < chg_soc) & has_bess
                inv_head = np.maximum(0.0, pinv - pv_direct)
                if cp == 0:
                    V = np.maximum(0.0, np.minimum(np.minimum(surplus, max_chg),
                                                   np.minimum(head_chg, inv_head)))
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(np.minimum(
                            J, np.maximum(max_chg - V, 0.0)),
                            np.maximum(head_chg - V, 0.0))), 0.0)
                else:
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(
                            np.minimum(J, max_chg), head_chg)), 0.0)
                    V = np.maximum(0.0, np.minimum(np.minimum(
                            surplus, np.maximum(max_chg - W, 0.0)),
                            np.minimum(np.maximum(head_chg - W, 0.0), inv_head)))
                V, W = _strict_charge(V, W)
                Cd = _deg_charge(base_req, need_deg, V, W, X)
                deg_req = np.where(need_deg, base_req + Cd, 0.0)
                m, n_, o = _deg_dispatch(deg_req, need_deg, deg1, deg2, deg3,
                                         d1max, sync=deg_sync)
                P = m + n_ + o
                deg_on = P > 0
                deg_load = P - Cd
            else:
                # ---- Mode C: PV → BESS → Grid → DEG ----
                #  Setelah PV, BESS yang menutup kekurangan beban; grid baru
                #  mengambil sisanya (tetap menghormati minimum loading grid).
                target = np.where(grid_off, np.asarray(ae, float),
                                  np.maximum(0.0, ae - gmin * Hg))
                pv_to_load0 = np.minimum(pv_cap, target)
                x_need = np.maximum(0.0, target - pv_to_load0)
                X = np.maximum(0.0, np.minimum(np.minimum(x_need, max_dhg), d_pot))
                AC0 = pv_to_load0 + X
                resid = np.maximum(0.0, ae - AC0 - np.where(
                    grid_off, 0.0, np.minimum(Hg * gmax, np.maximum(
                        ae - AC0, gmin * Hg))))
                if ilock:
                    if dg_ilock:
                        need_deg = (grid_off & ((pv_cap + d_cap) < ae)
                                    & (deg_cap_tot > 0))
                    else:
                        gcap = np.where(grid_off, 0.0, gmax * Hg)
                        need_deg = (((pv_cap + d_cap + gcap) < ae - 1e-9)
                                    & (deg_cap_tot > 0))
                    base_req = np.where(need_deg, np.asarray(ae, float), 0.0)
                else:
                    need_deg = (resid > 1e-12) & (deg_cap_tot > 0)
                    if dg_ilock:
                        need_deg = need_deg & grid_off
                    base_req = np.where(need_deg, resid, 0.0)
                excl = need_deg & ilock
                pv_to_load = np.where(excl, 0.0, pv_to_load0)
                X = np.where(excl, 0.0, X)
                AC = np.where(excl, 0.0, AC0)
                AD = np.where(grid_off, 0.0,
                              np.where(excl & dg_ilock, 0.0,
                                       _grid_serve(ae - AC)))
                if not dg_ilock:      # grid tetap memasok -> DEG hanya sisanya
                    base_req = np.where(excl, np.maximum(0.0, ae - AD), base_req)
                J = np.where(grid_off, 0.0, np.maximum(0.0, Hg * gmax - AD))
                inv_head = np.maximum(0.0, pinv - pv_to_load)
                v_avail = np.maximum(0.0, q - pv_to_load)
                soc_ok = gchg & (~grid_off) & (Z / E_safe < chg_soc) & has_bess
                if cp == 0:
                    V = np.maximum(0.0, np.minimum(np.minimum(v_avail, max_chg),
                                                   np.minimum(head_chg, inv_head)))
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(np.minimum(
                            np.where(excl, Hg * gmax, J),
                            np.maximum(max_chg - V, 0.0)),
                            np.maximum(head_chg - V, 0.0))), 0.0)
                else:
                    W = np.where(soc_ok, np.maximum(0.0, np.minimum(np.minimum(
                            np.where(excl, Hg * gmax, J), max_chg), head_chg)), 0.0)
                    V = np.maximum(0.0, np.minimum(np.minimum(
                            v_avail, np.maximum(max_chg - W, 0.0)),
                            np.minimum(np.maximum(head_chg - W, 0.0), inv_head)))
                V, W = _strict_charge(V, W)
                Cd = _deg_charge(base_req, need_deg, V, W, X)
                deg_req = np.where(need_deg, base_req + Cd, 0.0)
                m, n_, o = _deg_dispatch(deg_req, need_deg, deg1, deg2, deg3,
                                         d1max, sync=deg_sync)
                P = m + n_ + o
                deg_on = P > 0
                deg_load = P - Cd
                pv_direct = pv_to_load
            if any_split:
                __caps.append((AD, AC, X, V, W, Cd, pv_direct, deg_load,
                               P, m, n_, o))
        if any_split:
            (AD1, AC1, X1, V1, W1, Cd1, pvd1, dl1, P1, m1, n1, o1) = __caps[0]
            (AD0, AC0, X0, V0, W0, Cd0, pvd0, dl0, P0, m0, n0, o0) = __caps[1]
            _sel = grid_off      # True -> pakai skenario grid padam (status 0)
            AD = np.where(_sel, AD0, AD1)
            AC = np.where(_sel, AC0, AC1)
            X = np.where(_sel, X0, X1)
            V = np.where(_sel, V0, V1)
            W = np.where(_sel, W0, W1)
            Cd = np.where(_sel, Cd0, Cd1)
            pv_direct = np.where(_sel, pvd0, pvd1)
            deg_load = np.where(_sel, dl0, dl1)
            m = np.where(_sel, m0, m1)
            n_ = np.where(_sel, n0, n1)
            o = np.where(_sel, o0, o1)
            P = m + n_ + o
            deg_on = P > 0
        exp_lp = lp_on if split_lp else lp
        # BESS tidak boleh charge & discharge pada jam yang sama:
        # pelayanan beban (discharge) diprioritaskan, charging ditunda.
        no_dis = X <= 0
        V = np.where(no_dis, V, 0.0)
        W = np.where(no_dis, W, 0.0)
        Cd = np.where(no_dis, Cd, 0.0)
        # --- DEG WAJIB selalu nyala (opsional) --------------------------------
        # HANYA berlaku saat GRID TIDAK TERSEDIA jam ini (padam) atau proyek
        # memang TANPA GRID. Saat grid tersedia -> DEG bekerja normal (last-
        # resort), blok ini tak berpengaruh. Saat grid tak tersedia, genset
        # bertindak sebagai sumber UTAMA yang wajib nyala (grid-forming): minimal
        # SATU genset (terkecil) MELAYANI BEBAN lebih dulu — menggeser impor
        # (grid off), discharge BESS, LALU PV.
        #   * Bila beban < MINIMUM LOADING:
        #       - 'Allow DEG Charging to BESS' AKTIF  -> DEG naik ke minimum
        #         loading & surplus (floor - beban) mengisi BESS (SOC<maks, PCS
        #         cukup); PV yg tergeser mengisi BESS dg sisa ruang, selebihnya
        #         di-curtail (mis. beban rendah + BESS penuh -> PV ter-curtail).
        #       - 'Allow DEG Charging to BESS' NONAKTIF -> DEG hanya sebesar
        #         beban (di bawah floor), TIDAK mencari beban lain / tidak isi BESS.
        # deg_always=False -> blok dilewati -> byte-identik kanon.
        if deg_always and deg_has_any:
            # grid tak tersedia jam ini (padam) ATAU tak ada grid (Hg<=0).
            # Sinyal bersih — lepas dari transfer interlock DEG–grid di atas.
            gna = (np.asarray(grid_status[t], float) <= 0) | (Hg <= 0)
            onm = m > 1e-9; onn = n_ > 1e-9; ono = o > 1e-9
            anyon = onm | onn | ono
            cap_on = deg1 * onm + deg2 * onn + deg3 * ono   # kapasitas unit nyala
            # Pilih genset grid-forming (yang dinyalakan bila DEG semula mati).
            # Auto: per jam, genset yang floor (cap·Lmin) PALING DEKAT ke beban
            # (ae) -> beban rendah = genset kecil, paling mendekati minimum
            # loadingnya; seri dipecah ke kapasitas lebih kecil (penalti eps·cap).
            # Non-auto: unit tetap pilihan pengguna (deg_small*).
            if _auto_gf:
                _BIG = 1e18
                _d0 = np.where(deg1 > 0, np.abs(_floor0 - ae) + 1e-9 * deg1, _BIG)
                _d1 = np.where(deg2 > 0, np.abs(_floor1 - ae) + 1e-9 * deg2, _BIG)
                _d2 = np.where(deg3 > 0, np.abs(_floor2 - ae) + 1e-9 * deg3, _BIG)
                gf0 = (_d0 <= _d1) & (_d0 <= _d2)
                gf1 = (_d1 < _d0) & (_d1 <= _d2)
                gf2 = (_d2 < _d0) & (_d2 < _d1)
                gf_cap = deg1 * gf0 + deg2 * gf1 + deg3 * gf2
            else:
                gf0, gf1, gf2, gf_cap = (deg_small0, deg_small1, deg_small2,
                                         deg_cap_small)
            # floor must-run = floor genset GRID-FORMING (cap·Lmin). Saat beban
            # tinggi & butuh >1 genset, floor ini tak mengikat (P sudah > floor).
            gf_floor = gf_cap * lmin_deg
            floor = gf_floor                                 # daya minimum-loading gf
            # unit penerima daya tambahan: unit pertama yang nyala; bila DEG mati,
            # genset grid-forming (gf*) — menjaga aturan 'satu genset' & m+n_+o=P.
            t0 = np.where(anyon, onm, gf0)
            t1 = np.where(anyon, onn & ~onm, gf1)
            t2 = np.where(anyon, ono & ~onm & ~onn, gf2)
            # (1) DEG melayani beban hingga floor sbg sumber UTAMA: ambil-alih
            #     grid (off), lalu discharge BESS, LALU PV (PV yg tergeser jadi
            #     kandidat charge/curtail). Urutan menjaga PV & baterai selama
            #     masih dibutuhkan; PV baru tergeser saat over-generasi.
            deg_want = np.where(gna, np.minimum(ae, floor), 0.0)
            need = np.maximum(0.0, deg_want - deg_load)
            d_take = np.minimum(need, X)                     # ambil-alih discharge
            X = np.maximum(0.0, X - d_take)
            AC = np.maximum(0.0, AC - d_take)
            need = need - d_take
            p_take = np.minimum(need, pv_direct)             # ambil-alih PV
            pv_direct = np.maximum(0.0, pv_direct - p_take)
            AC = np.maximum(0.0, AC - p_take)
            add_serve = d_take + p_take
            m = m + np.where(t0, add_serve, 0.0)
            n_ = n_ + np.where(t1, add_serve, 0.0)
            o = o + np.where(t2, add_serve, 0.0)
            deg_load = deg_load + add_serve
            P = m + n_ + o
            # (2) discharge bisa berhenti (digantikan DEG) -> perbarui no_dis
            #     hanya utk kombinasi gna; charge PV/grid yg ditunda tetap ditunda.
            no_dis = np.where(gna, X <= 1e-12, no_dis)
            # (3) surplus floor -> mengisi BESS HANYA bila 'Allow DEG Charging to
            #     BESS' aktif (deg_chg_ok). Bila TIDAK diizinkan & beban < floor,
            #     DEG hanya sebesar beban (di bawah floor) — tak mencari beban
            #     lain. Bila diizinkan, DEG naik ke floor & surplus mengisi BESS
            #     (prioritas), sebatas PCS & headroom SOC.
            U_pre = V + W + Cd
            top_up = np.where(gna, np.maximum(0.0, floor - P), 0.0)
            room = np.minimum(np.minimum(
                top_up, np.maximum(max_chg - U_pre, 0.0)),
                np.maximum(head_chg - U_pre, 0.0))
            extra = np.where(gna & no_dis & has_bess & deg_chg_ok,
                             np.maximum(room, 0.0), 0.0)
            m = m + np.where(t0, extra, 0.0)
            n_ = n_ + np.where(t1, extra, 0.0)
            o = o + np.where(t2, extra, 0.0)
            Cd = Cd + extra
            P = m + n_ + o
            deg_on = P > 1e-9
            # (4) PV yg tergeser dari beban mengisi BESS dg SISA ruang; selebihnya
            #     ter-curtail (S & Texc dihitung ulang di bawah dari pv_direct+V).
            U_now = V + W + Cd
            pv_room = np.minimum(np.maximum(max_chg - U_now, 0.0),
                                 np.maximum(head_chg - U_now, 0.0))
            pv_extra = np.where(gna & no_dis & has_bess,
                                np.minimum(p_take, np.maximum(pv_room, 0.0)), 0.0)
            V = V + pv_extra
            # (5) Genset GRID-FORMING = unit UTAMA yang nyala. Bila ia sanggup
            #     memikul SELURUH output DEG jam ini sendiri (P ≤ cap·Lmax),
            #     pindahkan seluruh P ke unit grid-forming (unit lain 0) — apa pun
            #     genset yang dipilih dispatch dasar. Bila butuh >1 genset
            #     (P > kapasitas gf), biarkan alokasi apa adanya. Hanya saat grid
            #     tak tersedia (gna); total P & Cd (chg_deg) tetap.
            gf_max = gf_cap * d1max
            do_redist = gna & (P > 1e-9) & (P <= gf_max + 1e-9)
            m = np.where(do_redist, gf0 * P, m)
            n_ = np.where(do_redist, gf1 * P, n_)
            o = np.where(do_redist, gf2 * P, o)
            deg_on = P > 1e-9
        # =====================================================================
        # EMS BESS multi-mode (Advanced) — co-dispatch berbasis PRIORITAS.
        # Guarded oleh _adv_post; Standard melewatinya (bit-identik). Dispatch
        # BESS baku sudah dinonaktifkan (d_pot/head_chg=0) → seluruh aksi
        # baterai dihitung bess_modes.codispatch: charge (PV surplus/grid/DEG)
        # & discharge (melayani beban, kurangi grid lalu DEG) dgn anggaran
        # SOC/PCS berbagi + cadangan. Energi lestari (served tetap = ae).
        # =====================================================================
        _onpk_step = False
        if _adv_post:
            _dgmin = (deg1 * (m > 1e-9) + deg2 * (n_ > 1e-9)
                      + deg3 * (o > 1e-9)) * lmin_deg
            _grid_room = np.where(grid_off, 0.0,
                                  np.maximum(0.0, Hg * gmax - AD - W))
            _hod = (t * dt) % 24.0
            _qinv_t = np.minimum(q, pinv)
            _stt = dict(qinv=_qinv_t, pvd=pv_direct, ae=ae, AD=AD,
                        dl=deg_load, P=P, dgmin=_dgmin, Z=Z, smin=soc_min_e,
                        smax=soc_max_e, mchg=max_chg, mdhg=max_dhg, srte=srte,
                        dt=dt, hasb=has_bess, goff=grid_off,
                        grid_room=_grid_room, hod=_hod,
                        ma_pv=(_ma_pv[t] if _ma_pv is not None else _qinv_t))
            _o, _pv_prev, _ema_prev = bess_modes.codispatch(
                _stt, _md, _pv_prev, _ema_prev,
                pre_dis=_Xsf, pre_chg=_Usf, skip_sf=_sf_on)
            _cpv = _o['cpv']; _cgr = _o['cgr']; _cdg = _o['cdg']
            # Shaping PV (Smoothing/Firming): charge PV→BESS (Usf) & discharge
            # BESS→beban (Xsf). Xsf sudah masuk beban terlayani lewat q=injeksi
            # (pv_direct); di sini hanya dicatat ke akumulator BESS (SOC & dhg).
            if _sf_on or _bk_on:
                V = V + _Usf
                X = X + _Xsf
            # (a) CHARGE: PV surplus (V), grid (W), DEG excess (Cd → naikkan P)
            V = V + _cpv; W = W + _cgr
            _fup = np.where(P > 1e-12, (P + _cdg) / np.maximum(P, 1e-12), 1.0)
            m = m * _fup; n_ = n_ * _fup; o = o * _fup
            P = m + n_ + o; Cd = Cd + _cdg
            # (b) DISCHARGE: layani beban (AC), kurangi suplai TARGET. Target
            #     0=Both (grid lalu DEG), 1=Grid saja, 2=DEG saja. Energi
            #     terlayani lestari (served = ae).
            _tgt = _md['target']
            if _tgt == 1:                          # Grid saja
                _dis = np.minimum(_o['dis'], AD)
                _adr = _dis; AD = AD - _adr
                _dlr = np.zeros_like(np.asarray(_dis, float))
            elif _tgt == 2:                        # DEG saja
                _dis = np.minimum(_o['dis'], deg_load)
                _adr = np.zeros_like(np.asarray(_dis, float))
                _dlr = _dis
            else:                                  # Both (baku) — grid lalu DEG
                _dis = np.minimum(_o['dis'], AD + deg_load)
                _adr = np.minimum(_dis, AD); AD = AD - _adr
                _dlr = np.minimum(np.maximum(_dis - _adr, 0.0), deg_load)
            _fdn = np.where(P > 1e-12, (P - _dlr) / np.maximum(P, 1e-12), 0.0)
            m = m * _fdn; n_ = n_ * _fdn; o = o * _fdn; P = m + n_ + o
            X = X + _dis; AC = AC + _dis
            deg_load = np.maximum(0.0, P - Cd)
            deg_on = P > 1e-9
            if _tou_split:
                _onpk_step = (((_hod >= _md['arb_start'])
                               and (_hod < _md['arb_end']))
                              if not _md['arb_wrap'] else
                              ((_hod >= _md['arb_start'])
                               or (_hod < _md['arb_end'])))
        U = V + W + Cd
        I = np.where(grid_off, 0.0, AD + W)
        # S — output inverter PV ; T — excess (= curtailment)
        S = np.minimum(pv_direct + V, pinv)
        S = np.maximum(S, 0.0)
        Texc = np.where(np.abs(q - S) < 1e-6, 0.0, q - S)
        # ekspor opsional: kelebihan PV → grid, dibatasi inverter & headroom grid
        exp_gate = (~deg_on) if exp_lp == 0 else np.ones_like(np.asarray(deg_on), dtype=bool)
        exp = np.where((allow_export > 0) & (~grid_off) & exp_gate,
                       np.maximum(0.0, np.minimum(np.minimum(Texc, pinv - S), J - W)),
                       0.0)
        S = S + exp
        Texc = q - S
        # Shaping PV (Smoothing/Firming): q di atas = INJEKSI (pengganti PV EnetAC).
        # PV — Inverter Out (S) = PV EnetAC yg BENAR-BENAR DIPAKAI (diinjeksi dari PV +
        # di-charge ke BESS); sisanya CURTAIL. Bila di luar jendela firming & baterai
        # penuh: injeksi=0 & charge=0 → S=0, seluruh PV EnetAC jadi Unused/Curtail.
        if _sf_on:
            # PV — Inverter Out (S) = PV yg BENAR2 tersalur: melayani beban
            # langsung (pv_direct, dibatasi PV EnetAC mentah _qinv_r — pv_direct
            # bisa memuat andil discharge BESS yg "menumpang" lewat q=injeksi,
            # jadi TAK dipakai apa adanya) + charge BESS dari PV (V — SUDAH
            # final: mencakup _Usf shaping & charge-PV mode lain via codispatch,
            # baris di atas). pv_direct SENDIRI sudah final pasca SELURUH
            # cascade dispatch (termasuk pengambilalihan DEG "Must Always Run"/
            # interlock DEG–PV-BESS) — beda dgn rumus lama yg pakai _I_inj
            # mentah (SEBELUM cascade), sehingga bisa mencatat energi sbg
            # "dipakai" padahal cascade belakangan tak benar2 menyalurkannya
            # (lihat investigasi kolom Unused/Curtailment). Batas akhir _qinv_r
            # menjaga S tak pernah melebihi PV EnetAC itu sendiri.
            _pv_serve = np.minimum(_qinv_r, np.maximum(0.0, pv_direct))
            S = np.minimum(np.minimum(_pv_serve + V, _qinv_r), pinv)
            Texc = np.maximum(0.0, _q_raw - S)             # curtail = PV EnetAC − dipakai
            exp = np.zeros_like(np.asarray(S, float))
        # --- Self consumption BESS: pasca-alokasi Grid → DEG (→ PV+BESS) -----
        if _sc_on:
            _groom = np.where(grid_off, 0.0, np.maximum(0.0, Hg * gmax - I))
            _sc_g = np.minimum(_sc_need, _groom)
            I = I + _sc_g
            _sc_need = _sc_need - _sc_g
            _Ppos = P > 1e-9
            if deg_sync:
                _rrun = deg_cap_tot * d1max - P
            else:
                _rrun = (deg1 * (m > 1e-9) + deg2 * (n_ > 1e-9)
                         + deg3 * (o > 1e-9)) * d1max - P
            # DEG yg mati boleh dinyalakan (unit grid-forming) bila grid tak
            # tersedia atau DEG tak dikunci dgn grid
            _cstart = (~_Ppos) & (grid_off | (not dg_ilock))
            _droom = np.where(_Ppos, np.maximum(0.0, _rrun),
                              np.where(_cstart, deg_cap_small * d1max, 0.0))
            _sc_d = np.minimum(_sc_need, _droom)
            _fsc = np.where(_Ppos, (P + _sc_d) / np.maximum(P, 1e-12), 1.0)
            m = m * _fsc; n_ = n_ * _fsc; o = o * _fsc
            _stsc = (~_Ppos) & (_sc_d > 0)
            if deg_small0:
                m = m + np.where(_stsc, _sc_d, 0.0)
            elif deg_small1:
                n_ = n_ + np.where(_stsc, _sc_d, 0.0)
            elif deg_small2:
                o = o + np.where(_stsc, _sc_d, 0.0)
            P = m + n_ + o
            deg_on = P > 1e-9
            _sc_need = _sc_need - _sc_d
            if _sc_src == 1:
                # cadangan: kelebihan PV (curtail) lalu sisa kemampuan BESS
                _pvx = np.maximum(0.0, np.minimum(Texc, pinv - S))
                _sc_pv = np.minimum(_sc_need, _pvx)
                Texc = Texc - _sc_pv
                _sc_need = _sc_need - _sc_pv
                _bcap = np.where(has_bess, np.maximum(0.0, np.minimum(
                    max_dhg - X,
                    (Z + U * dt * srte - X * dt / srte - soc_min_e) / dt * srte)), 0.0)
                _sc_b = np.minimum(_sc_need, _bcap)
                Z = Z - _sc_b * dt / srte
                _sc_need = _sc_need - _sc_b
            _sc_uns = np.where(_sc_need < 1e-6, 0.0, np.maximum(0.0, _sc_need))
        # PV only (grafik) = PV EnetAC mentah; PV wBESS = injeksi (Plant Inj).
        if _sf_on:
            _pv_before = _q_raw; _pv_after = _I_inj
        else:
            _pv_before = S; _pv_after = S
        # MA Setpoint (telemetri/ekspor): utk Smoothing = MA MURNI PV EnetAC
        # (`_sp_pure`, dibatasi inverter SAJA + batas ramp, INDEPENDEN dari
        # beban); utk Firming = target konstan (`_sp_pure` == `_sp`). Nilai ini
        # SENGAJA lepas dari beban & dari batasan real (SOC/PCS/kurtailmen):
        # Plant Inj aktual (`plant_inj`) mengikuti yang BENAR2 tersalur (dibatasi
        # beban/baterai) dan BISA berbeda -- mis. beban kecil: MA Setpoint 150 kW
        # sementara PV wBESS aktual 45 kW. Nol di luar mode Shaping.
        _sp_rec = (np.asarray(_sp_pure, float) if _sf_on
                  else np.zeros_like(np.asarray(S, float)))
        # Telemetri LAJU RAMP (grafik EMS): Δ antar-langkah.
        #   DEG/Grid wPV      (tanpa BESS) = max(0, beban − PV mentah)
        #   DEG/Grid wPVBESS  (dgn BESS)   = pembangkitan grid+DEG AKTUAL = I + P
        #   PV only           = PV mentah (pv_before)
        #   PV wBESS          = PV+BESS efektif (pv_after)
        _dgn_t = np.maximum(0.0, ae - _pv_before)
        _dga_t = np.asarray(I, float) + np.asarray(P, float)
        _pvb_t = np.asarray(_pv_before, float)
        _pva_t = np.asarray(_pv_after, float)
        # Plant Inj (level injeksi PV+BESS). Utk shaping (sf): = injeksi STRICT (_I_inj),
        # sudah memperhitungkan curtail saat batre penuh (jadi bukan q+X−U yg akan
        # melebih-hitung). Non-sf: = PV EnetAC mentah + (discharge − charge).
        if _sf_on:
            _plant_t = np.asarray(_I_inj, float)
        else:
            _plant_t = np.asarray(_q_raw, float) + np.asarray(X, float) - np.asarray(U, float)
        _z_r = np.zeros_like(np.asarray(_dga_t, float))
        if _prev_dgn is None:
            _dg_ramp_act = _z_r; _dg_ramp_smooth = _z_r.copy()
            _pv_ramp_act = _z_r.copy(); _pv_ramp_smooth = _z_r.copy()
            _plant_inj_ramp = _z_r.copy()
        else:
            _dg_ramp_act = _dgn_t - _prev_dgn
            _dg_ramp_smooth = _dga_t - _prev_dga
            _pv_ramp_act = _pvb_t - _prev_pvb
            _pv_ramp_smooth = _pva_t - _prev_pva
            _plant_inj_ramp = _plant_t - _prev_plant
        _prev_dgn = _dgn_t; _prev_dga = _dga_t
        _prev_pvb = _pvb_t; _prev_pva = _pva_t; _prev_plant = _plant_t
        # SOC akhir
        AA = np.clip(Z + U * dt * srte - X * dt / srte, soc_min_e, soc_max_e)
        AA = np.where(has_bess, AA, 0.0)
        served = AC + AD + deg_load
        uns = np.maximum(0.0, ae - served)
        # sisa pembulatan floating-point (mis. 6e-09 kW) bukan energi
        # tak terlayani; dinolkan SEBELUM diakumulasi agar tidak
        # menumpuk menjadi angka semu di ringkasan tahunan
        uns = np.where(uns < 1e-6, 0.0, uns)

        acc['load'] += ae * dt
        acc['pv_gen'] += (_q_raw + _sc_pvq) * dt   # pembangkitan PV EnetAC MENTAH
        acc['pv_inv_out'] += (S + _sc_pv) * dt
        acc['pv_excess'] += Texc * dt
        acc['chg'] += U * dt
        acc['chg_pv'] += V * dt
        acc['chg_grid'] += W * dt
        acc['chg_deg'] += Cd * dt
        acc['dhg'] += (X + _sc_b) * dt
        if _sc_on:
            acc['selfcons'] += (_sc_t - _sc_uns) * dt
            acc['selfcons_pv'] += _sc_pv * dt
            acc['selfcons_bess'] += _sc_b * dt
            acc['selfcons_grid'] += _sc_g * dt
            acc['selfcons_deg'] += _sc_d * dt
            acc['selfcons_uns'] += _sc_uns * dt
        acc['grid_import'] += I * dt
        if _tou_split:                       # pisah impor puncak/luar-puncak (ToU)
            acc['grid_import_peak'] += (I * dt) if _onpk_step else 0.0
            acc['grid_import_offpeak'] += (I * dt) if not _onpk_step else 0.0
        acc['grid_export'] += exp * dt
        acc['deg_energy'] += P * dt
        acc['deg1_energy'] += m * dt
        acc['deg2_energy'] += n_ * dt
        acc['deg3_energy'] += o * dt
        acc['deg_hours'] += deg_on.astype(float)
        # Loading% relatif ke kapasitas terpasang: sync -> total; tak sinkron ->
        # kapasitas genset yang benar-benar menyala (yang outputnya > 0).
        _deg_denom = (deg_cap_tot if deg_sync else
                      deg1 * (m > 0) + deg2 * (n_ > 0) + deg3 * (o > 0))
        acc['deg_loading_sum'] += np.where(
            deg_on, P / np.maximum(_deg_denom, 1e-9), 0.0)
        acc['served_pvbs'] += AC * dt
        acc['served_grid'] += AD * dt
        acc['unserved'] += uns * dt
        acc['outage_hours_total'] += float(grid_status[t] == 0)
        soc_frac = np.where(has_bess, AA / E_safe, 0.0)
        soc_lo = np.minimum(soc_lo, soc_frac)
        soc_hi = np.maximum(soc_hi, soc_frac)

        if record:
            for k, val in (('pv', _q_raw + _sc_pvq), ('pv_inv_out', S + _sc_pv),
                           ('pv_excess', Texc),
                           ('load', ae * np.ones_like(S)), ('deg', P), ('grid', I),
                           ('grid_export', exp), ('chg', U), ('dhg', X + _sc_b),
                           ('bess_net', U - X - _sc_b), ('soc', soc_frac),
                           ('self_cons', _sc_t - _sc_uns),
                           ('self_cons_deg', _sc_d),
                           ('unserved', uns),
                           ('grid_load', AD), ('chg_pv', V), ('chg_grid', W),
                           ('chg_deg', Cd), ('deg1', m), ('deg2', n_),
                           ('deg3', o), ('pvbs_load', AC),
                           ('cap_start', Z_start), ('cap_end', AA),
                           ('dg_ramp_act', _dg_ramp_act),
                           ('dg_ramp_smooth', _dg_ramp_smooth),
                           ('pv_ramp_act', _pv_ramp_act),
                           ('pv_ramp_smooth', _pv_ramp_smooth),
                           ('plant_inj', _plant_t),
                           ('plant_inj_ramp', _plant_inj_ramp),
                           ('pv_before', _pv_before), ('pv_after', _pv_after),
                           ('ma_setpoint', _sp_rec),
                           ('grid_status',
                            np.full_like(np.asarray(S, float),
                                         float(grid_status[t]))),
                           # kode DEG Status jam ini (0=OFF/1=ON/2=Auto, lihat
                           # app.data.importer.DEG_STATUS_*); deg_status=None
                           # (tak diimpor) -> catat sbg 2.0 (Auto) sepanjang
                           # waktu, konsisten dgn "tak ada override".
                           ('deg_status',
                            np.full_like(np.asarray(S, float),
                                         2.0 if deg_status is None
                                         else float(deg_status[t])))):
                rec[k][t] = val
        Z = AA

    if progress is not None:
        progress(T, T)
    acc['soc_min_seen'] = soc_lo
    acc['soc_max_seen'] = soc_hi
    # sisa pembulatan floating-point (mis. 3e-07) dianggap nol
    acc = {k: snap_zero(v) for k, v in acc.items()}
    out = {'acc': acc, 'n': N}
    # metadata Smoothing (utk grafik ramp & ekspor): jendela MA & batas ramp
    # per-langkah (kW/langkah). Hanya bermakna bila Smoothing aktif.
    out['ma_window'] = int(_ma_win)
    out['ramp_up_step'] = float(_up_step)
    out['ramp_dn_step'] = float(_dn_step)
    out['pv_smooth_on'] = bool(_adv_post and _md['pv_smooth'])
    if record:
        out['series'] = {k: snap_zero(v) for k, v in rec.items()}
    return out
