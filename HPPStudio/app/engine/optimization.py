"""OptimizationEngine — grid search seluruh kombinasi sizing.

Strategi kecepatan (jauh melampaui Excel):
1. VEKTORISASI SUMBU KOMBINASI: satu loop 8760 langkah mensimulasikan
   ribuan kombinasi sekaligus lewat operasi array NumPy.
2. MULTIPROCESSING: kombinasi dipecah menjadi chunk dan dibagikan ke seluruh
   core CPU (ProcessPoolExecutor), aman untuk PyInstaller (freeze_support).
Kecepatan tipikal: ~400 simulasi tahunan/detik per core.
"""
from __future__ import annotations

import os
import itertools
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass

import numpy as np

from .dispatch import simulate
from .numeric import snap_zero
from .kpi import technical_kpis
from .finance import financial_kpis


# --------------------------------------------------------------------------
# Process pool yang tahan-banting untuk batch multi-site.
#
# Latar: satu ProcessPoolExecutor dipakai untuk seluruh batch. Bila SATU
# proses pekerja mati (tekanan memori di laptop, gangguan antivirus, atau
# crash native pada .exe hasil bundel), seluruh pool menjadi "broken" dan
# setiap site berikutnya ikut gagal — inilah penyebab aplikasi tampak
# "force stop" saat menjalankan batch. Dua pembungkus berikut membuat pool
# (a) mendaur-ulang pekerja agar memori tidak menumpuk sepanjang batch, dan
# (b) selalu dapat ditutup tanpa menggantung thread.
_MAX_TASKS_PER_CHILD = 100     # daur-ulang pekerja -> batasi RSS pada batch panjang


def make_pool(workers: int):
    """ProcessPoolExecutor dengan daur-ulang pekerja bila tersedia
    (Python 3.11+). Pada 3.10 argumennya tidak ada -> dibuat biasa."""
    try:
        return ProcessPoolExecutor(max_workers=workers,
                                   max_tasks_per_child=_MAX_TASKS_PER_CHILD)
    except TypeError:
        return ProcessPoolExecutor(max_workers=workers)


def safe_shutdown(ex) -> None:
    """Tutup pool tanpa pernah menggantung: coba rapi dengan batas waktu,
    lalu lepas paksa bila belum selesai (pool yang sudah broken bisa
    menggantung shutdown(wait=True) pada sebagian platform)."""
    if ex is None:
        return

    def _close():
        try:
            ex.shutdown(wait=True)
        except Exception:
            pass

    t = threading.Thread(target=_close, daemon=True)
    t.start()
    t.join(timeout=8.0)
    if t.is_alive():                       # masih menutup -> jangan tunggu
        try:
            ex.shutdown(wait=False)
        except Exception:
            pass

OBJECTIVES = {
    # nama            (kunci KPI/finansial, arah: min|max)
    'Min LCOE':                 ('lcoe', 'min'),
    'Max NPV':                  ('npv', 'max'),
    'Min CAPEX':                ('capex', 'min'),
    'Min Payback':              ('payback_years', 'min'),
    'Max Renewable Fraction':   ('renewable_fraction', 'max'),
    'Min Diesel Fuel':          ('diesel_fuel_l', 'min'),
    'Min Grid Import':          ('grid_import_kwh', 'min'),
    'Min Unused Energy (Curtailment)':            ('pv_excess_kwh', 'min'),
    'Min Unserved Energy':      ('unserved_kwh', 'min'),
}

# (kunci KPI, operator) — nilai None berarti constraint tidak aktif
CONSTRAINT_DEFS = {
    'max_pv_excess_ratio':     ('pv_excess_ratio', '<='),
    'min_renewable_fraction':  ('renewable_fraction', '>='),
    'max_lcoe':                ('lcoe', '<='),
    'max_capex':               ('capex', '<='),
    'max_diesel_fuel_l':       ('diesel_fuel_l', '<='),
    'target_diesel_reduction': ('diesel_reduction_vs_only', '>='),
    'max_unserved_kwh':        ('unserved_kwh', '<='),
}


@dataclass
class SweepRange:
    start: float
    stop: float
    step: float

    def values(self) -> np.ndarray:
        if self.step <= 0 or self.stop < self.start:
            return np.array([self.start], float)
        n = int(np.floor((self.stop - self.start) / self.step + 1e-9)) + 1
        return self.start + self.step * np.arange(n)


def build_grid(pv: SweepRange, inv: SweepRange, bess: SweepRange,
               link_inv_by_ratio: float | None = None) -> np.ndarray:
    """Kembalikan array (N,3): kolom kwp, kw_inv, kwh_bess.
    Bila link_inv_by_ratio diisi, inverter = kwp/rasio (mengurangi dimensi)."""
    pv_v = pv.values()
    bess_v = bess.values()
    if link_inv_by_ratio:
        combos = [(p, p / link_inv_by_ratio, b)
                  for p, b in itertools.product(pv_v, bess_v)]
    else:
        combos = list(itertools.product(pv_v, inv.values(), bess_v))
    return np.array(combos, float)


# ---------------------------------------------------------------------------
# Parameter EKSTRA yang dioptimasi pada mode Advanced (di luar PV/INV/BESS).
#   VECT  = dapat divektorkan per-kombinasi dalam SATU panggilan simulate
#           (menjadi kolom grid, diterapkan sebagai array (N,)).
#   SCALAR= harus KONSTAN per panggilan simulate (mis. jendela MA) -> di-loop
#           per nilai di run(); grid dikelompokkan menurut kolom ini.
_VECT_EXTRA = ('firming_kw', 'max_charge_cap', 'max_discharge_cap',
               'reserve_frac', 'reserve_kw')
_SCALAR_EXTRA = ('smoothing_window',)

# Akumulator yang diskalakan saat DURASI simulasi < setahun (ekstrapolasi ke
# setahun) — IDENTIK dengan SimulationEngine agar hasil Optimization konsisten
# dgn simulasi Dashboard pada jendela yang sama. Energi (kWh) ×annualize;
# langkah (jam operasi) ×dt×annualize. annualize=1 & dt=1 -> no-op (bit-identik).
# CATATAN: 'firm_time_ok'/'firm_time_window' (dasar "Firming Target Met (%)")
# SENGAJA TIDAK dimasukkan ke salah satu tuple ini — metrik itu adalah RASIO
# waktu (menit tercapai / total menit) dalam jendela yang BENAR-BENAR
# disimulasikan, dan harus mencerminkan APA ADANYA jendela tsb tanpa
# diekstrapolasi/dianualisasi ke setahun (lihat kpi.py firm_met_pct).
_ENERGY_ACC = ('load', 'pv_gen', 'pv_inv_out', 'pv_excess', 'chg', 'chg_pv',
               'chg_grid', 'chg_deg', 'dhg', 'grid_import', 'grid_export',
               'grid_import_peak', 'grid_import_offpeak',
               'deg_energy', 'served_pvbs', 'served_grid', 'unserved',
               'deg1_energy', 'deg2_energy', 'deg3_energy',
                   'selfcons', 'selfcons_pv', 'selfcons_bess', 'selfcons_grid',
                   'selfcons_deg', 'selfcons_uns')
_STEP_ACC = ('deg_hours', 'outage_hours_total', 'deg_loading_sum')


def build_grid_extra(base_grid: np.ndarray,
                     extras):
    """Perluas grid (N,3) [kwp,kw_inv,kwh_bess] dengan kolom parameter ekstra
    (mode Advanced). `extras` = [(key, values), ...].

    Kembalikan (grid_ext, keys): grid_ext (M, 3+K) = product Cartesian tiap
    baris sizing dengan tiap kombinasi nilai ekstra; keys = urutan kolom ekstra
    (kolom 3..). Bila extras kosong -> grid & [] apa adanya (jalur Standard)."""
    base_grid = np.asarray(base_grid, float)
    if not extras:
        return base_grid, []
    keys = [k for k, _ in extras]
    val_lists = [np.unique(np.asarray(v, float).reshape(-1)) for _, v in extras]
    tail = list(itertools.product(*val_lists))
    tail = np.asarray(tail, float)
    m = len(tail)
    if m == 0:
        return base_grid, []
    g = np.repeat(base_grid, m, axis=0)              # (N*m, 3)
    t = np.tile(tail, (len(base_grid), 1))           # (N*m, K)
    return np.hstack([g, t]), keys


def _simulate_chunk(args):
    (chunk, load, pv_norm, grid_status, base, cost_cfg, col_map,
     scalar_disp, deg_status) = args
    kwp, kw_inv, kwh_bess = chunk[:, 0], chunk[:, 1], chunk[:, 2]
    # daya charge/discharge mengikuti C-rate dasar (PCS 108 kW per 215 kWh basis)
    crate = float(base.get('bess_c_rate', 108.0 / 215.0))
    # --- kolom ekstra (mode Advanced yg dioptimasi) -> override per-kombinasi ---
    # col_map: list (key, col_index) untuk parameter VECT yg di-sweep.
    ex = {}
    for key, ci in (col_map or []):
        ex[key] = np.asarray(chunk[:, ci], float)
    _exv = lambda key, default: ex[key] if key in ex else default
    # daya PCS: bila di-sweep pakai nilai kolom langsung, else C-rate×BESS (cap)
    max_chg = np.minimum(crate * kwh_bess, base.get('max_charge_cap', 1e12))
    max_dhg = np.minimum(crate * kwh_bess, base.get('max_discharge_cap', 1e12))
    if 'max_charge_cap' in ex:
        max_chg = ex['max_charge_cap']
    if 'max_discharge_cap' in ex:
        max_dhg = ex['max_discharge_cap']
    p = dict(
        pv_kwp=kwp, pv_inv=kw_inv, pv_base=base['pv_base_annual'],
        bess=kwh_bess, soc_init=base['soc_init'], soc_min=base['soc_min'],
        soc_max=base['soc_max'], rte=base['rte'],
        max_chg=max_chg,
        max_dhg=max_dhg,
        chg_soc=base['charge_from_grid_below_soc'],
        bess_self_cons=float(base.get('bess_self_cons_kw', 0.0) or 0.0),
        bess_sc_source=float(base.get('bess_sc_source', 0) or 0),
        grid_kw=base['grid_kw'] if base.get('grid_enabled', True) else 0.0,
        grid_min=base['grid_min_loading'], grid_max=base['grid_max_loading'],
        dt=base['interval_h'],
        deg1=base['deg_kw'][0], deg2=base['deg_kw'][1], deg3=base['deg_kw'][2],
        d1max=base['deg_max_loading'][0], d2max=base['deg_max_loading'][1],
        allow_export=1.0 if base.get('allow_export', False) else 0.0,
        load_priority=float(base.get('load_priority', 0.0)),
        load_priority_split=1.0 if base.get('load_priority_split') else 0.0,
        load_priority_on=float(base.get('load_priority_on', 0.0)),
        load_priority_off=float(base.get('load_priority_off', 2.0)),
        charge_priority=float(base.get('charge_priority', 0.0)),
        strict_charge=1.0 if base.get('strict_charge_priority',
                                      False) else 0.0,
        grid_charge_enabled=1.0 if base.get('grid_charge_enabled', True) else 0.0,
        deg_charge_enabled=1.0 if base.get('deg_charge_enabled', False) else 0.0,
        deg_interlock=1.0 if base.get('deg_interlock', True) else 0.0,
        grid_interlock=1.0 if base.get('grid_interlock', False) else 0.0,
        deg_grid_interlock=1.0 if base.get('deg_grid_interlock',
                                           True) else 0.0,
        deg_min_loading=float(base.get('deg_min_loading', 0.0)),
        # --- opsi dispatch DEG lanjutan (harus diteruskan agar Optimization
        #     memakai perilaku yang sama dgn simulasi 1-tahun) ---
        deg_sync=1.0 if base.get('deg_sync', True) else 0.0,
        deg_always=1.0 if base.get('deg_always', False) else 0.0,
        deg_grid_former=float(base.get('deg_grid_former', 0) or 0),
        deg_options_split=1.0 if base.get('deg_options_split', False) else 0.0,
        deg_interlock_on=1.0 if base.get('deg_interlock_on', True) else 0.0,
        deg_interlock_off=1.0 if base.get('deg_interlock_off', True) else 0.0,
        deg_charge_on=1.0 if base.get('deg_charge_on', False) else 0.0,
        deg_charge_off=1.0 if base.get('deg_charge_off', False) else 0.0,
        # --- EMS BESS multi-mode; Standard = semua 0 → no-op (bit-identik) ---
        bess_mode=float(base.get('bess_mode', 0) or 0),
        adv_target=float(base.get('adv_target', 0) or 0),
        m_pv_smooth=float(base.get('m_pv_smooth', 0) or 0),
        m_firming=float(base.get('m_firming', 0) or 0),
        m_load_shift=float(base.get('m_load_shift', 0) or 0),
        m_peak_shave=float(base.get('m_peak_shave', 0) or 0),
        m_dg_minload=float(base.get('m_dg_minload', 0) or 0),
        m_reserve=float(base.get('m_reserve', 0) or 0),
        m_backup=float(base.get('m_backup', 0) or 0),
        peak_shave_kw=float(base.get('peak_shave_kw', 0.0) or 0.0),
        firming_kw=_exv('firming_kw', float(base.get('firming_kw', 0.0) or 0.0)),
        arb_peak_start=float(base.get('arb_peak_start', 0.0) or 0.0),
        arb_peak_end=float(base.get('arb_peak_end', 0.0) or 0.0),
        pv_ramp_up_kwmin=float(base.get('pv_ramp_up_kwmin', 0.0) or 0.0),
        pv_ramp_dn_kwmin=float(base.get('pv_ramp_dn_kwmin', 0.0) or 0.0),
        reserve_frac=_exv('reserve_frac',
                          float(base.get('reserve_frac', 0.0) or 0.0)),
        reserve_kw=_exv('reserve_kw', float(base.get('reserve_kw', 0.0) or 0.0)),
        # --- param Advanced SKALAR (satu nilai per panggilan simulate); di
        #     mode Advanced yg dioptimasi, 'smoothing_window' di-loop di run()
        #     sehingga konstan per panggilan. Standard: bess_mode=0 -> tak dipakai.
        smoothing_window=float(base.get('smoothing_window', 1) or 1),
        firming_trigger=float(base.get('firming_trigger', 0) or 0),
        firming_pv_start=float(base.get('firming_pv_start', 0.0) or 0.0),
        firming_pv_end=float(base.get('firming_pv_end', 0.0) or 0.0),
        firming_time_start=float(base.get('firming_time_start', 0.0) or 0.0),
        firming_time_end=float(base.get('firming_time_end', 0.0) or 0.0),
    )
    raw = simulate(load, pv_norm, grid_status, p, n_combos=len(chunk),
                   deg_status=deg_status)
    acc = raw['acc']
    # Durasi simulasi < setahun → ekstrapolasi akumulator ke setahun (identik
    # SimulationEngine). Default (dt=1, annualize=1) → tidak ada perubahan.
    dt = float(base.get('interval_h', 1.0) or 1.0)
    ann = float(base.get('annualize', 1.0) or 1.0)
    if ann != 1.0 or dt != 1.0:
        acc = dict(acc)
        for _k in _ENERGY_ACC:
            if _k in acc:
                acc[_k] = np.asarray(acc[_k], float) * ann
        for _k in _STEP_ACC:
            if _k in acc:
                acc[_k] = np.asarray(acc[_k], float) * dt * ann
    kpi = technical_kpis(acc, dict(
        bess_kwh=kwh_bess, soc_min=base['soc_min'], soc_max=base['soc_max'],
        deg_fuel_rate=base.get('deg_fuel_rate')))
    fin = financial_kpis(kpi, dict(kwp=kwp, kw_inv=kw_inv, kwh_bess=kwh_bess,
                                   kw_deg=sum(base['deg_kw'])),
                         {**cost_cfg,
                          'pv_degradation': base.get('pv_degradation', 0.0)})
    fin.pop('cashflow', None)
    row = {**{k: np.asarray(v).reshape(-1) for k, v in kpi.items()},
           **{k: np.asarray(v).reshape(-1) for k, v in fin.items()},
           'kwp': kwp, 'kw_inv': kw_inv, 'kwh_bess': kwh_bess,
           'pcs_kw': np.asarray(p['max_chg'], float)
                     * np.ones_like(kwh_bess)}
    # Kolom nilai parameter Advanced (utk tabel & "Terapkan Terbaik"). Dipancarkan
    # menurut MODE yang aktif (bukan hanya bila di-sweep) sehingga kolomnya tetap
    # muncul & PCS diganti pada mode Manual MAUPUN Auto:
    #   * Manual  → nilai yang DIOPTIMASI (dari kolom grid / grup window).
    #   * Auto    → nilai yang DIPAKAI (max chg/dhg = C-rate×BESS; window/target
    #               dari Parameters). max_chg/max_dhg & firming_kw sudah memuat
    #               nilai swept bila ada (ex), else nilai turunan/base.
    _ones = np.ones_like(kwh_bess)
    _adv = float(base.get('bess_mode', 0) or 0) > 0.5
    _sm = _adv and float(base.get('m_pv_smooth', 0) or 0) > 0.5
    _fm = _adv and float(base.get('m_firming', 0) or 0) > 0.5
    _rv = _adv and float(base.get('m_reserve', 0) or 0) > 0.5
    if _sm or _fm:            # daya PCS dioptimasi/dipakai → ganti kolom PCS
        row['opt_max_charge'] = np.asarray(max_chg, float) * _ones
        row['opt_max_discharge'] = np.asarray(max_dhg, float) * _ones
    if _sm:                   # panjang jendela MA (skalar per grup / Parameters)
        row['opt_smoothing_window'] = \
            float(base.get('smoothing_window', 1) or 1) * _ones
    if _fm:                   # target daya firming (swept bila ada, else base)
        _fk = ex['firming_kw'] if 'firming_kw' in ex \
            else float(base.get('firming_kw', 0.0) or 0.0)
        row['opt_firming_kw'] = np.asarray(_fk, float) * _ones
        # Seberapa lama (waktu, bukan energi) kandidat MENCAPAI target power
        # sepanjang firming window (constraint UTAMA optimasi Firming — lihat
        # _apply_ranking): waktu tercapai ÷ total waktu window, dari jendela
        # simulasi INI apa adanya (tak diekstrapolasi — lihat kpi.py
        # firm_met_pct & _ENERGY_ACC/_STEP_ACC di atas). 100% = Plant Inj
        # selalu = target (tak pernah kurang) sepanjang jendela; di bawah itu
        # menandakan BESS/PCS sizing tak cukup pada sebagian jendela.
        row['opt_firm_met_pct'] = np.asarray(
            kpi.get('firm_met_pct', 100.0), float).reshape(-1)
    if _rv:                   # operating reserve: SOC fraction & daya PCS ditahan
        _rf = ex['reserve_frac'] if 'reserve_frac' in ex \
            else float(base.get('reserve_frac', 0.0) or 0.0)
        _rk = ex['reserve_kw'] if 'reserve_kw' in ex \
            else float(base.get('reserve_kw', 0.0) or 0.0)
        row['opt_reserve_frac'] = np.asarray(_rf, float) * _ones
        row['opt_reserve_kw'] = np.asarray(_rk, float) * _ones
    # KPI turunan untuk constraint "diesel reduction vs diesel-only"
    # Fuel diesel-only = laju efektif (L/kWh) × seluruh beban tahunan.
    rate_eff = base.get('deg_fuel_rate_eff', 1.0 / (0.33 * 10.0))
    fuel_only = np.asarray(kpi['annual_load_kwh']).reshape(-1) * rate_eff
    row['diesel_reduction_vs_only'] = 1.0 - row['diesel_fuel_l'] / np.maximum(fuel_only, 1e-9)
    return row




# Objective IMPLISIT (tak muncul di dropdown Priority) yang otomatis
# diprioritaskan PALING UTAMA saat mode Firming aktif: maksimalkan WAKTU
# (bukan energi) di mana Plant Inj. BENAR-BENAR mencapai target power
# sepanjang firming window (lihat dispatch.py 'firm_time_ok'/'firm_time_window'
# & kpi.py 'firm_met_pct', dibaca apa adanya oleh _simulate_chunk sbg
# 'opt_firm_met_pct' — TIDAK diekstrapolasi ke setahun, hanya mencerminkan
# jendela simulasi yang dipilih pengguna). Kandidat yang benar-benar mencapai
# target sepanjang jendela (met% ~100) SELALU diutamakan; objective pilihan
# user (LCOE dkk.) hanya memutus seri di antara kandidat yang sama-sama
# (hampir) mencapai target.
# Label deskriptif langsung dipakai sbg 'objective' (tampil apa adanya pada
# 'Objective' hasil export/ringkasan, spt 'Min LCOE' dkk. — bukan token
# internal) agar rantai prioritas tetap terbaca, mis. "Firming: Reach Target
# Power > Min LCOE".
_FIRM_OBJ_KEY = 'Firming: Reach Target Power'
_FIRM_OBJ_KPI = ('opt_firm_met_pct', 'max')

# Toleransi utk level Firming (implisit) pada _apply_ranking: SANGAT kecil
# (bukan 0 murni, agar noise floating-point pada nilai met% yg BENAR-BENAR
# identik tak memecahnya jadi bin berbeda scr sembarangan) -- BERBEDA dari
# `tol` pengguna (mis. 1%) yg dipakai ANTAR-objective pilihan user. Alasan:
# constraint firming adalah PALING UTAMA (bukan preferensi yg boleh
# "dianggap seri" dlm pita longgar) -- kandidat 99.4% vs 100.0% HARUS tetap
# terurut ketat (100.0% lebih dulu), tak boleh dianggap seri lalu
# diputuskan oleh LCOE dkk. hanya krn selisihnya < toleransi pengguna.
_FIRM_TOL = 1e-9


def _apply_ranking(res: dict, objective, tol: float,
                    firm_priority: bool = False) -> dict:
    """Urutkan hasil menurut objective tunggal ATAU daftar prioritas
    (lexicographic dengan pita toleransi antar level).

    `firm_priority=True` (mode Firming aktif) menyisipkan objective implisit
    _FIRM_OBJ_KEY di urutan PALING DEPAN (prioritas tertinggi), di atas
    seluruh objective yang dipilih user -- level ini SELALU diurutkan KETAT
    (lihat _FIRM_TOL), bukan memakai `tol` pengguna, sehingga max Firming
    Target Met (%) benar2 mendominasi murni sebelum objective pilihan user
    (mis. Min LCOE) dipakai sbg pemutus seri."""
    feas = res['feasible']
    objectives = ([objective] if isinstance(objective, str)
                  else [o for o in objective if o and o in OBJECTIVES])
    if not objectives:
        objectives = ['Min LCOE']
    if firm_priority and _FIRM_OBJ_KPI[0] in res:
        objectives = [_FIRM_OBJ_KEY] + objectives
    sort_keys = []
    for li, obj in enumerate(objectives):
        key, direction = (_FIRM_OBJ_KPI if obj == _FIRM_OBJ_KEY
                          else OBJECTIVES[obj])
        sc = res[key].astype(float).copy()
        if direction == 'max':
            sc = -sc
        sc = np.where(np.isnan(sc), np.inf, sc)
        sc[~feas] = np.inf
        if li < len(objectives) - 1:
            finite = sc[np.isfinite(sc)]
            best = float(finite.min()) if finite.size else 0.0
            eff_tol = _FIRM_TOL if obj == _FIRM_OBJ_KEY \
                else max(float(tol), 1e-9)
            step = max(abs(best), 1.0) * eff_tol
            sc = np.where(np.isfinite(sc),
                          np.floor((sc - best) / step), np.inf)
        sort_keys.append(sc)
    res['rank_order'] = np.lexsort(tuple(reversed(sort_keys)))
    res['objectives_used'] = objectives
    return res


class OptimizationEngine:
    def __init__(self, load, pv_norm, grid_status,
                 base_params: dict, cost_cfg: dict,
                 extra_cols=None, deg_status=None):
        self.load = np.asarray(load, float)
        self.pv_norm = np.asarray(pv_norm, float)
        self.grid_status = np.asarray(grid_status, float)
        self.base = base_params
        self.cost = cost_cfg
        # Kolom parameter Advanced yg dioptimasi (kolom 3.. pada grid). None/[]
        # -> jalur Standard (grid 3-kolom, numerik identik).
        self.extra_cols = list(extra_cols or [])
        # DEG Status (T,) opsional, dari kolom import "DEG Status" (halaman
        # Data) — lihat app.engine.dispatch.simulate(). None (tak diimpor)
        # -> mekanisme dorman, byte-identik perilaku lama (lihat _t_deg_status.py).
        self.deg_status = (np.asarray(deg_status, float)
                           if deg_status is not None else None)

    def _firm_priority(self) -> bool:
        """True bila mode Firming aktif (Advanced) -> constraint PALING
        UTAMA optimasi adalah Plant Inj. selalu mencapai target power
        sepanjang firming window (lihat _FIRM_OBJ_KEY/_apply_ranking)."""
        adv = float(self.base.get('bess_mode', 0) or 0) > 0.5
        return adv and float(self.base.get('m_firming', 0) or 0) > 0.5

    # ------------------------------------------------------------------
    def _eval_grid(self, grid, base, col_map, scalar_disp,
                   workers, chunk_size, progress_cb, cancel_flag,
                   executor, pool_state):
        """Evaluasi SATU grid (kolom sizing + ekstra) dengan `base` tetap.
        Kembalikan dict kolom hasil (ter-snap, ter-concat) ATAU None bila
        dibatalkan. Feasibility/ranking dihitung pemanggil."""
        chunks = [grid[i:i + chunk_size]
                  for i in range(0, len(grid), chunk_size)]
        args = [(c, self.load, self.pv_norm, self.grid_status,
                 base, self.cost, col_map, scalar_disp, self.deg_status)
                for c in chunks]

        def _serial():
            out, d = [], 0
            for a in args:
                if cancel_flag is not None and cancel_flag.is_set():
                    return None
                out.append(_simulate_chunk(a))
                d += len(a[0])
                if progress_cb:
                    progress_cb(d, len(grid))
            return out

        rows = None
        if workers == 1 or len(chunks) == 1:
            rows = _serial()
        else:
            ex = executor or make_pool(workers)
            own = executor is None
            broken = False
            got, done = [], 0
            try:
                futs = {ex.submit(_simulate_chunk, a): len(a[0])
                        for a in args}
                for f in as_completed(futs):
                    if cancel_flag is not None and cancel_flag.is_set():
                        for fu in futs:
                            fu.cancel()
                        if own:
                            safe_shutdown(ex)
                        return None
                    try:
                        got.append(f.result())
                    except (BrokenProcessPool, Exception):
                        broken = True
                        break
                    done += futs[f]
                    if progress_cb:
                        progress_cb(done, len(grid))
            except (BrokenProcessPool, Exception):
                broken = True
            finally:
                if own:
                    safe_shutdown(ex)
            if broken:
                if pool_state is not None:
                    pool_state['broken'] = True   # beri tahu batch: buat ulang
                rows = _serial()                  # jaring pengaman (identik)
            else:
                rows = got
        if rows is None:
            return None
        return {k: snap_zero(np.concatenate([r[k] for r in rows]))
                for k in rows[0]}

    def run(self, grid: np.ndarray, objective,
            constraints: dict | None = None,
            workers: int | None = None, chunk_size: int = 400,
            progress_cb=None, cancel_flag=None, tol: float = 0.01,
            executor=None, pool_state=None):
        """grid (N, 3+K) -> dict kolom hasil (N,), indeks terurut objective
        (string tunggal ATAU list prioritas [P1, P2, ...] dengan toleransi
        `tol` antar level), plus mask feasible menurut constraints.

        Kolom 0..2 = kwp, kw_inv, kwh_bess. Kolom 3.. = parameter Advanced yg
        dioptimasi (urutan = self.extra_cols). Parameter VECT diterapkan
        per-kombinasi; parameter SCALAR (smoothing_window) di-loop per nilai
        (grid dikelompokkan) agar konstan tiap panggilan simulate.

        `pool_state` (dict opsional): bila pool proses mati di tengah jalan,
        perhitungan otomatis jatuh ke mode serial (numerik identik) dan
        pool_state['broken'] diset True agar pemanggil (batch) dapat membuat
        ulang pool untuk site berikutnya."""
        constraints = constraints or {}
        workers = workers or max(1, (os.cpu_count() or 2) - 1)
        grid = np.asarray(grid, float)
        extra_cols = list(self.extra_cols or [])
        col_index = {k: 3 + i for i, k in enumerate(extra_cols)}
        vect_map = [(k, col_index[k]) for k in extra_cols if k in _VECT_EXTRA]
        scalar_keys = [k for k in extra_cols if k in _SCALAR_EXTRA]
        total = len(grid)
        # Ukuran chunk ADAPTIF: pecah jadi ~120 bagian agar progress bar bergerak
        # bertahap (bukan lompat 0→100), sambil menjaga chunk cukup besar untuk
        # tetap efisien secara vektor. Hasil numerik TIDAK bergantung pada ukuran
        # chunk (tiap kombinasi dihitung independen) → jalur Standard tetap identik.
        chunk_size = int(min(chunk_size, max(40, total // 120))) or 1

        if scalar_keys:
            # Hanya smoothing_window (SCALAR) yg didukung: kelompokkan grid
            # menurut nilainya lalu evaluasi tiap grup dgn base yg disesuaikan.
            skey = scalar_keys[0]
            sidx = col_index[skey]
            gvals = np.unique(grid[:, sidx])
            # satu pool bersama utk seluruh grup (hindari buat/tutup berulang)
            own_ex = None
            ex_use = executor
            if ex_use is None and workers > 1 and total > chunk_size:
                own_ex = make_pool(workers)
                ex_use = own_ex
            parts, offset = [], 0
            try:
                for gval in gvals:
                    sub = grid[np.isclose(grid[:, sidx], gval)]
                    if not len(sub):
                        continue
                    base_g = {**self.base, skey: float(gval)}

                    def _pcb(d, t, off=offset):
                        if progress_cb:
                            progress_cb(off + d, total)

                    part = self._eval_grid(
                        sub, base_g, vect_map, {skey: float(gval)},
                        workers, chunk_size, _pcb, cancel_flag,
                        ex_use, pool_state)
                    if part is None:
                        return None
                    parts.append(part)
                    offset += len(sub)
            finally:
                if own_ex is not None:
                    safe_shutdown(own_ex)
            if not parts:
                return None
            res = {k: np.concatenate([p[k] for p in parts])
                   for k in parts[0]}
        else:
            res = self._eval_grid(grid, self.base, vect_map, {},
                                  workers, chunk_size, progress_cb,
                                  cancel_flag, executor, pool_state)
            if res is None:
                return None

        n = len(res['kwp'])
        feas = np.ones(n, bool)
        for name, val in constraints.items():
            if val is None or name not in CONSTRAINT_DEFS:
                continue
            key, op = CONSTRAINT_DEFS[name]
            x = res[key]
            feas &= (x <= val) if op == '<=' else (x >= val)
        res['feasible'] = feas
        res['dc_ac_ratio'] = res['kwp'] / np.maximum(res['kw_inv'], 1e-9)
        # BESS autonomy: energi usable / rata-rata beban (jam)
        usable = (float(self.base.get('soc_max', 1.0))
                  - float(self.base.get('soc_min', 0.0)))
        avg_load = float(np.mean(self.load)) if len(self.load) else 0.0
        res['bess_autonomy_h'] = (res['kwh_bess'] * usable
                                  / max(avg_load, 1e-9))

        _apply_ranking(res, objective, tol, firm_priority=self._firm_priority())
        return res

    # ------------------------------------------------------------------
    def auto_bounds(self) -> tuple[float, float, float]:
        """Batas atas pencarian otomatis dari profil beban & PV.
        PV: cukup untuk ±3× energi beban tahunan (atau 2× beban puncak);
        INV: setara batas PV; BESS: ±4× energi harian rata-rata
        (atau 8× beban puncak selama 1 jam)."""
        e_load = float(np.sum(self.load))
        peak = float(np.max(self.load)) if len(self.load) else 1.0
        yield_per_kwp = float(np.sum(self.pv_norm)) / max(
            float(self.base.get('pv_base_annual', 1.0)), 1e-9)
        pv_hi = max(2.0 * peak, 3.0 * e_load / max(yield_per_kwp, 1e-9))
        inv_hi = pv_hi
        daily = e_load / max(len(self.load) / 24.0, 1.0)
        bess_hi = max(8.0 * peak, 4.0 * daily)
        return pv_hi, inv_hi, bess_hi

    def run_auto(self, objective, constraints: dict | None = None,
                 workers: int | None = None, progress_cb=None,
                 cancel_flag=None, tol: float = 0.01,
                 rounds: int = 5, coarse: tuple = (10, 10),
                 topk: int = 6, refine_pts: int = 5, dcac: float = 1.1,
                 executor=None, pool_state=None):
        """Optimasi otomatis tanpa range/step (ala HOMER Optimizer).

        Mencari PV (kWp) dan BESS (kWh) pada batas otomatis; kapasitas
        inverter diikat fisik INV = PV / dcac. Grid kasar disempitkan
        iteratif di sekitar kandidat terbaik hingga resolusi tercapai.
        Mengembalikan dict berformat sama dengan run() atas seluruh
        kombinasi yang dievaluasi."""
        pv_hi, _inv_hi, bess_hi = self.auto_bounds()
        # Resolusi pencarian mengikuti perangkat nyata: kelipatan satu
        # modul PV (mis. 625 Wp -> 0,625 kWp) dan 1 kWh untuk BESS,
        # sehingga setiap kandidat dapat direalisasikan di lapangan.
        mod_kwp = float(self.base.get('pv_module_wp', 0.0) or 0.0) / 1000.0
        res_floor = (mod_kwp if mod_kwp > 0 else 0.01, 1.0)
        axes = [np.linspace(0.0, pv_hi, coarse[0]),
                np.linspace(0.0, bess_hi, coarse[1])]
        steps = [ax[1] - ax[0] for ax in axes]

        seen: set = set()

        def _snap(v, step):
            """Selaraskan ke kisi resolusi (kelipatan `step`) agar tiap
            kandidat merupakan ukuran yang benar-benar dapat dipasang."""
            return round(max(round(float(v) / step), 0) * step, 6)

        def _new_grid(cands_axes):
            combos = []
            for pv_ax, bs_ax in cands_axes:
                for a in pv_ax:
                    for c in bs_ax:
                        key = (_snap(a, res_floor[0]), _snap(c, res_floor[1]))
                        if key in seen:
                            continue
                        seen.add(key)
                        combos.append((key[0], key[0] / dcac, key[1]))
            return np.asarray(combos, float)

        merged: dict | None = None
        total_done = 0
        # PROGRESS BERBASIS RONDE (permil 0..1000): fraksi = (ronde_selesai +
        # fraksi_dalam_ronde) / total_ronde. MONOTON NAIK sepanjang jalan (ronde
        # naik; dalam satu ronde d/t naik dari 0→1) sehingga bar TAK PERNAH
        # mundur. Sebelumnya penyebut = jumlah kombinasi yang TUMBUH tiap ronde,
        # jadi bar melompat mundur (mis. 100% di akhir ronde-1 → turun saat
        # ronde-2 mulai) & 100% bukan berarti selesai. Basis ronde dipilih (bukan
        # jumlah kombinasi) karena total kombinasi Auto tak diketahui di muka
        # (dedup + konvergensi dini). Nilai 100% FINAL diset pemanggil saat
        # worker benar-benar selesai (lihat optimization_page._done).
        _prog_rounds = max(1, int(rounds))
        # Executor & jumlah worker berjalan; bila pool mati di satu ronde,
        # ronde berikutnya lanjut serial agar tidak memakai pool yang broken.
        cur_ex = executor
        cur_workers = workers

        def _merge(part):
            nonlocal merged
            skip = {'rank_order', 'objectives_used'}
            part = {k: v for k, v in part.items() if k not in skip}
            if merged is None:
                merged = {k: np.asarray(v) for k, v in part.items()}
            else:
                for k in skip:
                    merged.pop(k, None)
                for k in part:
                    merged[k] = np.concatenate([merged[k], part[k]])

        rnd = 0
        grid = _new_grid([tuple(axes)])
        for rnd in range(rounds):
            if len(grid):
                base_done = total_done

                def _cb(d, t, r=rnd):
                    if progress_cb:
                        # (ronde selesai + fraksi ronde ini) / total ronde, skala
                        # permil; ≤ 999 (100% disisakan utk sinyal selesai).
                        frac = (r + float(d) / max(float(t), 1.0)) / _prog_rounds
                        progress_cb(min(int(frac * 1000), 999), 1000)

                _ps = {'broken': False}
                part = self.run(grid, objective, constraints,
                                workers=cur_workers, executor=cur_ex,
                                progress_cb=_cb, cancel_flag=cancel_flag,
                                tol=tol, pool_state=_ps)
                if part is None:          # dibatalkan
                    return None
                if _ps.get('broken'):
                    if pool_state is not None:
                        pool_state['broken'] = True
                    cur_ex, cur_workers = None, 1   # sisa ronde: serial aman
                total_done += len(grid)
                _merge(part)

            _apply_ranking(merged, objective, tol,
                          firm_priority=self._firm_priority())
            if all(st <= fl for st, fl in zip(steps, res_floor)):
                break
            order = merged['rank_order']
            picks, used = [], set()
            for idx in order[:max(topk * 10, 50)]:
                key = (_snap(merged['kwp'][idx], res_floor[0]),
                       _snap(merged['kwh_bess'][idx], res_floor[1]))
                if key in used:
                    continue
                used.add(key)
                picks.append(key)
                if len(picks) >= topk:
                    break
            steps = [max(st * 2.0 / (refine_pts - 1), fl)
                     for st, fl in zip(steps, res_floor)]
            cands_axes = []
            for (cp, cb) in picks:
                half = (refine_pts - 1) / 2
                pv_ax = np.clip(np.linspace(cp - steps[0] * half,
                                            cp + steps[0] * half,
                                            refine_pts), 0.0, pv_hi)
                bs_ax = np.clip(np.linspace(cb - steps[1] * half,
                                            cb + steps[1] * half,
                                            refine_pts), 0.0, bess_hi)
                cands_axes.append((np.unique(pv_ax), np.unique(bs_ax)))
            grid = _new_grid(cands_axes)
            if not len(grid):
                break

        # buang sisa kandidat kembar (ukuran PV & BESS sama persis)
        pairs = np.stack([np.round(merged['kwp'], 6),
                          np.round(merged['kwh_bess'], 6)], axis=1)
        _, keep = np.unique(pairs, axis=0, return_index=True)
        if len(keep) < len(pairs):
            keep = np.sort(keep)
            merged = {k: (v[keep] if isinstance(v, np.ndarray)
                          and v.shape[:1] == pairs.shape[:1] else v)
                      for k, v in merged.items()}
        _apply_ranking(merged, objective, tol, firm_priority=self._firm_priority())
        merged['auto_evaluated'] = total_done
        merged['auto_rounds'] = rnd + 1
        merged['auto_bounds'] = (pv_hi, bess_hi)
        merged['auto_dcac'] = dcac
        return merged
