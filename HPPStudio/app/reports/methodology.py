"""Bagian laporan yang menjelaskan MODEL PERHITUNGAN (v139).

Isi modul ini adalah DOKUMENTASI dari algoritma yang diterapkan engine v138
(`engine/dispatch.py`, `engine/bess_modes.py`, `engine/kpi.py`,
`engine/finance.py`, `engine/multiyear.py`, `engine/simulation.py`) — modul
ini TIDAK menjalankan atau mengubah perhitungan apa pun. Semua flag dibaca dari
`SystemParams` hasil `to_system_params(cfg)` (nilai EFEKTIF yang benar-benar
dipakai engine, termasuk aturan otomatis seperti "interlock → DEG charging
off"), sehingga uraian di laporan selalu sesuai dengan simulasi yang dijalankan.

Fungsi publik:
  arch_spec(A, cfg, p)              → dict untuk charts.fig_architecture
  power_path_rows(A, cfg, p)        → baris tabel jalur aliran daya
  dispatch_rows(A, cfg, p)          → baris tabel strategi dispatch
  adv_active(p)                     → daftar mode Advanced yang aktif
  advanced_section(D, A, cfg, p)    → sub-bab Bagian 2 (mode Advanced)
  advanced_results(D, A, cfg, p)    → sub-bab Bagian 4 (kinerja EMS)
  methodology(D, A, cfg, p, tech, finx) → Lampiran A lengkap
"""
from __future__ import annotations

import numpy as np

from . import common as K
from .common import L

_n = K.fmt_n
_pct = K.fmt_pct


def _arrow(txt):
    return str(txt).replace('->', '→')


def _yn(b):
    return L('Ya', 'Yes') if b else L('Tidak', 'No')


def _g(p, name, default=None):
    return getattr(p, name, default) if p is not None else default


# ============================================================ mode Advanced ===
# (kunci, flag SystemParams, prioritas SystemParams, nama EN, nama ID)
_MODES = [
    ('reserve', 'm_reserve', 'prio_reserve', 'Operating Reserve', 'Cadangan Operasi'),
    ('backup', 'm_backup', 'prio_backup', 'Backup', 'Backup (Cadangan Outage)'),
    ('pv_smooth', 'm_pv_smooth', 'prio_pv_smooth', 'PV Smoothing', 'Smoothing PV'),
    ('firming', 'm_firming', 'prio_firming', 'Firming', 'Firming'),
    ('dg_minload', 'm_dg_minload', 'prio_dg_minload', 'DG Minimum Loading',
     'Minimum Loading DG'),
    ('load_shift', 'm_load_shift', 'prio_load_shift', 'Load Shifting',
     'Load Shifting (Geser Energi)'),
    ('peak_shave', 'm_peak_shave', 'prio_peak_shave', 'Peak Shaving',
     'Peak Shaving (Pangkas Puncak)'),
]
_TARGET = {0: ('Grid lalu DEG (Both)', 'Grid then DEG (Both)'),
           1: ('Grid saja', 'Grid only'), 2: ('DEG saja', 'DEG only')}


def is_advanced(p) -> bool:
    return int(round(float(_g(p, 'bess_mode', 0) or 0))) == 1


def adv_active(p):
    """[(key, nama, prioritas)] mode Advanced aktif, terurut seperti engine
    (nomor prioritas, lalu urutan default spec)."""
    if not is_advanced(p):
        return []
    out = []
    default = ['reserve', 'backup', 'pv_smooth', 'firming', 'dg_minload',
               'load_shift', 'peak_shave']
    for key, flag, prio, en, idn in _MODES:
        if float(_g(p, flag, 0) or 0) > 0.5:
            out.append((key, L(idn, en), int(_g(p, prio, 1) or 1)))
    out.sort(key=lambda r: (r[2], default.index(r[0])))
    return out


def _mode_settings(key, p, cfg):
    """Ringkasan setelan satu mode (teks)."""
    if key == 'pv_smooth':
        up, dn = _g(p, 'pv_ramp_up_kwmin', 0.0), _g(p, 'pv_ramp_dn_kwmin', 0.0)
        lim = lambda v: (f"{_n(v, 1)} kW/min" if v and v > 0
                         else L('tanpa batas', 'unlimited'))
        return (f"MA {int(_g(p, 'smoothing_window', 1) or 1)} "
                + L('langkah', 'steps') + f"; ramp ↑ {lim(up)}, ↓ {lim(dn)}")
    if key == 'firming':
        if int(_g(p, 'firming_trigger', 0) or 0) == 1:
            win = (L('waktu', 'time') + f" {_n(_g(p, 'firming_time_start', 0), 1)}–"
                   f"{_n(_g(p, 'firming_time_end', 0), 1)} h")
        else:
            win = (L('daya PV', 'PV power') + f" > {_n(_g(p, 'firming_pv_start', 0), 1)} kW "
                   + L('mulai', 'start') + f", < {_n(_g(p, 'firming_pv_end', 0), 1)} kW "
                   + L('berhenti', 'stop'))
        return L('target', 'target') + f" {_n(_g(p, 'firming_kw', 0), 1)} kW; " + win
    if key == 'dg_minload':
        return L('loading minimum DEG', 'DEG minimum loading') + \
            f" {_pct(cfg.get('deg_min_loading', 0.0), 0)}"
    if key == 'load_shift':
        s, e = int(_g(p, 'arb_peak_start', 0) or 0), int(_g(p, 'arb_peak_end', 0) or 0)
        txt = L('jendela puncak', 'peak window') + f" {s:02d}:00–{e:02d}:00"
        to = cfg.get('tariff_offpeak_per_kwh')
        if to is not None:
            txt += L('; tarif luar-puncak ', '; off-peak tariff ') + K.fmt_rp(to) + '/kWh'
        return txt
    if key == 'peak_shave':
        return L('ambang', 'threshold') + f" {_n(_g(p, 'peak_shave_kw', 0), 1)} kW"
    if key == 'reserve':
        return (L('energi cadangan', 'reserved energy')
                + f" {_pct(_g(p, 'reserve_frac', 0.0), 0)} "
                + L('kapasitas guna', 'of usable')
                + f"; {L('daya PCS ditahan', 'PCS power held')} {_n(_g(p, 'reserve_kw', 0), 1)} kW")
    if key == 'backup':
        return L('aktif saat Grid DAN DEG tak tersedia', 'active when Grid AND DEG are unavailable')
    return '-'


def _mode_role(key):
    return {
        'reserve': L("Menahan sebagian energi guna & daya PCS; mode lain tidak boleh "
                     "memakainya.",
                     "Holds back part of the usable energy and PCS power; other modes "
                     "may not use it."),
        'backup': L("Saat outage total (Grid dan DEG tak tersedia), BESS + PV mengambil "
                    "alih seluruh beban; di luar outage BESS hanya mengisi dari surplus "
                    "PV (siaga).",
                    "During a total outage (Grid and DEG unavailable), BESS + PV take "
                    "over the entire load; outside outages the BESS only charges from "
                    "PV surplus (standby)."),
        'pv_smooth': L("Output PV+BESS mengikuti setpoint rata-rata bergerak PV yang "
                       "laju naik/turunnya dibatasi; BESS menutup selisihnya.",
                       "PV+BESS output follows a ramp-limited moving-average PV "
                       "setpoint; the BESS covers the difference."),
        'firming': L("PV+BESS memasok daya konstan (target) selama jendela firming; di "
                     "luar jendela PV hanya mengisi BESS.",
                     "PV+BESS deliver a constant target power during the firming "
                     "window; outside it PV only charges the BESS."),
        'dg_minload': L("BESS menyerap output tambahan genset agar genset tidak "
                        "beroperasi di bawah loading minimum.",
                        "The BESS absorbs extra genset output so the genset never "
                        "runs below its minimum loading."),
        'load_shift': L("Mengisi dari surplus PV di luar jendela puncak dan melepas "
                        "energi di jendela puncak untuk menggantikan suplai target.",
                        "Charges from PV surplus outside the peak window and "
                        "discharges during it to displace the target supply."),
        'peak_shave': L("Discharge saat beban neto pada suplai target melebihi "
                        "ambang.",
                        "Discharges when the net load on the target supply exceeds "
                        "the threshold."),
    }[key]


def advanced_section(D, A, cfg, p):
    """Sub-bab 'Strategi EMS BESS Advanced' (hanya bila mode Advanced)."""
    act = adv_active(p)
    if not is_advanced(p):
        return
    D.sub(L('Strategi EMS BESS Mode Advanced', 'Advanced BESS EMS Strategy'))
    D.p(L("Studi ini memakai **Dispatch Mode = Advanced**: BESS dikendalikan oleh "
          "Energy Management System (EMS) multi-mode berbasis prioritas. Satu unit "
          "BESS menjalankan beberapa **fungsi peran BESS** (BESS role functions) "
          "sekaligus dalam setiap langkah waktu, berbagi satu **anggaran SOC** (energi "
          "yang boleh dipakai) dan satu **anggaran PCS** (daya charge/discharge) menurut "
          "nomor prioritas (1 = tertinggi). Dispatch BESS baku (BESS melayani beban "
          "pada rantai prioritas) dinonaktifkan; aturan dasar lain — rantai prioritas "
          "beban untuk PV/Grid/DEG, interlock, dan batas perangkat — tetap berlaku.",
          "This study uses **Dispatch Mode = Advanced**: the BESS is controlled by a "
          "priority-based multi-mode Energy Management System (EMS). A single BESS "
          "performs several **BESS role functions** simultaneously in each time step, "
          "sharing one **SOC budget** (energy it may use) and one **PCS budget** "
          "(charge/discharge power) by priority number (1 = highest). The standard "
          "BESS dispatch (BESS serving load within the priority chain) is disabled; the "
          "other base rules — the load priority chain for PV/Grid/DEG, interlocks and "
          "device limits — still apply."))
    if not act:
        D.note(L("Tidak ada fungsi peran BESS yang diaktifkan: pada mode Advanced BESS "
                 "tidak beroperasi (idle).",
                 "No BESS role function is enabled: in Advanced mode the BESS stays "
                 "idle."))
        return
    rows = [[str(pr), name, _mode_settings(k, p, cfg), _mode_role(k)]
            for k, name, pr in act]
    D.table([L('Prioritas', 'Priority'), L('Fungsi aktif', 'Active function'),
             L('Setelan', 'Settings'), L('Peran', 'Role')], rows,
            align=['c', 'l', 'l', 'l'], widths=[0.10, 0.20, 0.30, 0.40], font=7.5,
            caption=L('Fungsi peran BESS yang aktif (urutan pemrosesan)',
                      'Active BESS role functions (processing order)'))
    tgt = int(_g(p, 'adv_target', 0) or 0)
    tl = _TARGET.get(tgt, _TARGET[0])
    D.bullets([
        L(f"**Target discharge:** {tl[0]} — suplai yang dikurangi saat BESS "
          "discharge (dipakai Peak Shaving & Load Shifting sebagai beban neto).",
          f"**Discharge target:** {tl[1]} — the supply displaced when the BESS "
          "discharges (used by Peak Shaving & Load Shifting as the net load)."),
        L("**Urutan pemrosesan:** fungsi diproses dari prioritas tertinggi; tiap fungsi "
          "hanya memakai sisa anggaran SOC/PCS setelah fungsi sebelumnya. Smoothing/"
          "Firming dan Backup dihitung lebih dulu (pra-proses) karena menggantikan "
          "profil injeksi PV.",
          "**Processing order:** functions are processed from the highest priority; "
          "each uses only the SOC/PCS budget left by the previous ones. Smoothing/"
          "Firming and Backup are evaluated first (pre-processing) because they replace "
          "the PV injection profile."),
        L("**Satu arah per langkah:** seluruh permintaan charge dan discharge "
          "dinetkan, sehingga BESS hanya charge ATAU discharge dalam satu langkah.",
          "**One direction per step:** all charge and discharge requests are netted, "
          "so the BESS either charges OR discharges in any step."),
        L("Pasangan **Smoothing ↔ Firming** dan **Operating Reserve ↔ Backup** saling "
          "eksklusif; maksimum lima fungsi aktif bersamaan.",
          "The pairs **Smoothing ↔ Firming** and **Operating Reserve ↔ Backup** are "
          "mutually exclusive; at most five functions can be active together."),
    ])
    D.p(L("Terminologi yang dipakai pada mode Advanced:",
          "Terminology used for the Advanced mode:"), keep=True)
    D.table([L('Istilah', 'Term'), L('Arti dalam studi ini', 'Meaning in this study')],
            [[r[0], r[1]] for r in _terms()], align=['l', 'l'], widths=[0.27, 0.73],
            font=7.5, caption=L('Terminologi EMS BESS', 'BESS EMS terminology'))


def _terms():
    return [
        ('EMS / co-dispatch',
         L("Pengendali energi yang menjalankan beberapa fungsi BESS dalam satu langkah "
           "dengan satu baterai, berbagi anggaran SOC & PCS menurut prioritas.",
           "Energy controller that runs several BESS functions in one step with one "
           "battery, sharing the SOC & PCS budget by priority.")),
        (L('Anggaran SOC / PCS', 'SOC / PCS budget'),
         L("Daya discharge (D) dan charge (C) maksimum yang tersedia pada langkah itu, "
           "dibatasi energi tersimpan, jendela SOC, cadangan, dan rating PCS.",
           "Maximum discharge (D) and charge (C) power available in the step, bounded "
           "by stored energy, SOC window, reserve and PCS rating.")),
        (L('Target discharge', 'Discharge target'),
         L("Suplai yang digantikan discharge BESS: Grid, DEG, atau keduanya (grid "
           "lebih dulu).",
           "Supply displaced by BESS discharge: Grid, DEG, or both (grid first).")),
        (L('Beban neto', 'Net load'),
         L("Daya yang masih dipasok suplai target (grid dan/atau DEG) setelah PV.",
           "Power still supplied by the target supply (grid and/or DEG) after PV.")),
        ('Plant Injection (Plant Inj)',
         L("Daya gabungan PV + BESS yang disalurkan ke rel AC.",
           "Combined PV + BESS power delivered to the AC bus.")),
        (L('Setpoint / MA Setpoint', 'Setpoint / MA setpoint'),
         L("Target Plant Injection. Smoothing: rata-rata bergerak kausal PV ENetAC "
           "sepanjang W langkah sebelumnya, dibatasi laju ramp. Firming: target daya "
           "konstan.",
           "Plant-injection target. Smoothing: causal moving average of PV ENetAC over "
           "the previous W steps, ramp-limited. Firming: constant target power.")),
        (L('Batas ramp', 'Ramp limit'),
         L("Perubahan setpoint maksimum per menit (kW/min), naik dan turun terpisah.",
           "Maximum setpoint change per minute (kW/min), up and down separately.")),
        (L('Jendela firming', 'Firming window'),
         L("Periode firming aktif: berbasis daya PV (mulai saat PV > ambang pagi, "
           "berhenti saat PV < ambang sore) atau berbasis jam.",
           "Period in which firming is active: PV-power based (starts when PV > morning "
           "threshold, stops when PV < evening threshold) or clock based.")),
        ('Firming Target Met',
         L("Persentase waktu dalam jendela firming saat Plant Injection mencapai target.",
           "Share of time within the firming window in which plant injection meets "
           "the target.")),
        (L('Jendela puncak', 'Peak window'),
         L("Jam discharge Load Shifting; di luar jendela BESS mengisi dari surplus PV. "
           "Impor grid dipisah puncak/luar-puncak untuk tarif ToU.",
           "Load-shifting discharge hours; outside the window the BESS charges from PV "
           "surplus. Grid import is split peak/off-peak for ToU tariffs.")),
        (L('Cadangan operasi', 'Operating reserve'),
         L("Energi (fraksi kapasitas guna) & daya PCS yang ditahan untuk kejadian tak "
           "terduga; menaikkan batas SOC bawah efektif mode lain.",
           "Energy (fraction of usable capacity) and PCS power held for contingencies; "
           "raises the effective lower SOC limit for the other modes.")),
        (L('Outage total', 'Total outage'),
         L("Langkah waktu ketika grid padam DAN tidak ada kapasitas DEG tersedia.",
           "Time step in which the grid is down AND no DEG capacity is available.")),
        (L('Kurtailmen', 'Curtailment'),
         L("Energi PV yang tersedia tetapi tidak dapat disalurkan ke beban, BESS, "
           "maupun ekspor.",
           "Available PV energy that cannot be delivered to load, BESS or export.")),
    ]


def advanced_results(D, A, cfg, p):
    """Sub-bab kinerja EMS Advanced (Bagian 4) dari deret hasil simulasi."""
    act = adv_active(p)
    if not act:
        return
    s = A.get('series')
    kpi = A['kpi']
    dt = A['dt']
    ann = 8760.0 / A['window_h'] if A['window_h'] > 0 else 1.0

    def ser(k):
        if s is None or k not in s:
            return None
        a = np.asarray(s[k], float)
        return a.reshape(len(a), -1)[:, 0]
    rows = []
    keys = {k for k, _n2, _p in act}
    if 'pv_smooth' in keys or 'firming' in keys:
        ra, rp = ser('pv_ramp_act'), ser('plant_inj_ramp')
        if ra is not None and rp is not None and ra.size > 1:
            per_min = 1.0 / (dt * 60.0)
            rows.append([L('Laju ramp PV maks. (tanpa BESS)', 'Max PV ramp rate (without BESS)'),
                         _n(np.max(np.abs(ra[1:])) * per_min, 2), 'kW/min'])
            rows.append([L('Laju ramp Plant Injection maks. (PV+BESS)',
                           'Max plant-injection ramp rate (PV+BESS)'),
                         _n(np.max(np.abs(rp[1:])) * per_min, 2), 'kW/min'])
            for lab_id, lab_en, lim in (('naik', 'up', _g(p, 'pv_ramp_up_kwmin', 0.0)),
                                        ('turun', 'down', _g(p, 'pv_ramp_dn_kwmin', 0.0))):
                if 'pv_smooth' in keys and lim and lim > 0:
                    sign = 1.0 if lab_en == 'up' else -1.0
                    b = np.mean(sign * ra[1:] * per_min > lim + 1e-9)
                    a_ = np.mean(sign * rp[1:] * per_min > lim + 1e-9)
                    rows.append([L(f'Langkah melampaui batas ramp {lab_id} (tanpa → dengan BESS)',
                                   f'Steps exceeding ramp-{lab_en} limit (without → with BESS)'),
                                 f"{_pct(b, 1)} → {_pct(a_, 1)}", '%'])
    if 'firming' in keys:
        rows.append([L('Firming Target Met (waktu)', 'Firming target met (time)'),
                     _n(kpi.get('firm_met_pct', 0.0), 1), '%'])
        rows.append([L('Durasi jendela firming (periode simulasi)',
                       'Firming window duration (simulated period)'),
                     _n(kpi.get('firm_time_window_h', 0.0), 1), 'h'])
    tgt = int(_g(p, 'adv_target', 0) or 0)
    gl, dg, cd = ser('grid_load'), ser('deg'), ser('chg_deg')
    if ('peak_shave' in keys or 'load_shift' in keys) and gl is not None:
        dgl = np.maximum((dg if dg is not None else 0.0)
                         - (cd if cd is not None else 0.0), 0.0)
        net = gl if tgt == 1 else (dgl if tgt == 2 else gl + dgl)
        net = np.asarray(net, float) * np.ones_like(gl)
        if 'peak_shave' in keys:
            thr = float(_g(p, 'peak_shave_kw', 0.0) or 0.0)
            rows.append([L('Puncak beban neto suplai target (setelah BESS)',
                           'Peak net load on target supply (after BESS)'), _n(np.max(net), 1), 'kW'])
            rows.append([L('Ambang peak shaving', 'Peak-shaving threshold'), _n(thr, 1), 'kW'])
            rows.append([L('Waktu di atas ambang', 'Time above threshold'),
                         _n(np.sum(net > thr + 1e-6) * dt * ann), L('jam/thn', 'h/yr')])
    if 'load_shift' in keys:
        dh = ser('dhg')
        if dh is not None:
            sph = max(1, int(round(1.0 / dt)))
            hod = (np.arange(dh.size) * dt) % 24.0
            s0, e0 = float(_g(p, 'arb_peak_start', 0) or 0), float(_g(p, 'arb_peak_end', 0) or 0)
            on = ((hod >= s0) & (hod < e0)) if s0 <= e0 else ((hod >= s0) | (hod < e0))
            rows.append([L('Discharge BESS di jendela puncak', 'BESS discharge in peak window'),
                         _n(np.sum(dh[on]) * dt * ann), L('kWh/thn', 'kWh/yr')])
        pk, op = kpi.get('grid_import_peak_kwh', 0.0), kpi.get('grid_import_offpeak_kwh', 0.0)
        if (pk or 0) + (op or 0) > 0:
            rows.append([L('Impor grid — jam puncak / luar puncak', 'Grid import — peak / off-peak'),
                         f"{_n(pk)} / {_n(op)}", L('kWh/thn', 'kWh/yr')])
    if 'dg_minload' in keys:
        rows.append([L('Energi genset ke BESS (menjaga loading minimum)',
                       'Genset energy to BESS (holding minimum loading)'),
                     _n(kpi.get('deg_charge_kwh', 0.0)), L('kWh/thn', 'kWh/yr')])
        rows.append([L('Loading rata-rata genset', 'Average genset loading'),
                     _pct(kpi.get('diesel_avg_loading', 0.0), 1), '%'])
    if 'reserve' in keys:
        smin, smax = _f(cfg.get('soc_min'), 0.1), _f(cfg.get('soc_max'), 0.95)
        fr = float(_g(p, 'reserve_frac', 0.0) or 0.0)
        floor = smin + fr * (smax - smin)
        rows.append([L('Batas SOC bawah efektif (dengan cadangan)',
                       'Effective lower SOC limit (with reserve)'), _pct(floor, 1), '%'])
        rows.append([L('SOC minimum teramati', 'Minimum observed SOC'),
                     _pct(kpi.get('soc_min', 0.0), 1), '%'])
        rows.append([L('Energi cadangan ditahan', 'Reserved energy held'),
                     _n(fr * A['usable_kwh'], 1), 'kWh'])
    if 'backup' in keys:
        gs, ds = ser('grid_status'), ser('deg_status')
        if gs is not None:
            no_deg = (A['kw_deg'] <= 0)
            deg_down = np.ones_like(gs, bool) if no_deg else (
                (ds == 0.0) if ds is not None else np.zeros_like(gs, bool))
            grid_down = (gs <= 0) | (not A['grid_on'])
            out = grid_down & deg_down
            pb, un = ser('pvbs_load'), ser('unserved')
            rows.append([L('Durasi outage total', 'Total-outage duration'),
                         _n(np.sum(out) * dt * ann), L('jam/thn', 'h/yr')])
            if pb is not None:
                rows.append([L('Beban dilayani PV+BESS saat outage total',
                               'Load served by PV+BESS during total outage'),
                             _n(np.sum(pb[out]) * dt * ann), L('kWh/thn', 'kWh/yr')])
            if un is not None:
                rows.append([L('Beban tak terlayani saat outage total',
                               'Unserved load during total outage'),
                             _n(np.sum(un[out]) * dt * ann), L('kWh/thn', 'kWh/yr')])
    if not rows:
        return
    D.sub(L('Kinerja EMS BESS Advanced', 'Advanced BESS EMS Performance'))
    D.p(L("Indikator berikut mengukur seberapa baik tiap fungsi peran BESS mencapai "
          "tujuannya, dihitung dari deret hasil simulasi (nilai per tahun dianualisasi "
          "bila periode simulasi < 1 tahun).",
          "The indicators below measure how well each BESS role function achieves its "
          "objective, computed from the simulated time series (per-year values are "
          "annualised when the simulated period is shorter than one year)."), keep=True)
    D.table([L('Indikator', 'Indicator'), L('Nilai', 'Value'), L('Satuan', 'Unit')], rows,
            align=['l', 'r', 'l'], widths=[0.62, 0.22, 0.16],
            caption=L('Indikator kinerja EMS BESS', 'BESS EMS performance indicators'))


def _f(x, d=0.0):
    try:
        v = float(x)
        return v if v == v else d
    except (TypeError, ValueError):
        return d


# ====================================================== strategi dispatch ===
def dispatch_rows(A, cfg, p):
    """Tabel strategi dispatch dari nilai EFEKTIF engine (SystemParams)."""
    from ..config import parameters as PR
    rows = []
    grid, deg, bess = A['grid_on'], A['has_deg'], A['has_bess']
    rows.append([L('Mode dispatch', 'Dispatch mode'),
                 'Advanced (EMS multi-mode)' if is_advanced(p) else 'Standard'])
    try:
        if grid and bool(_g(p, 'load_priority_split', False)):
            rows.append([L('Prioritas beban — grid tersedia', 'Load priority — grid available'),
                         _arrow(PR.load_priority_label(cfg.get('load_priority_on'), cfg))])
            rows.append([L('Prioritas beban — grid padam', 'Load priority — grid unavailable'),
                         _arrow(PR.load_priority_off_label(cfg.get('load_priority_off'), cfg))])
        elif grid:
            rows.append([L('Prioritas pasokan beban', 'Load supply priority'),
                         _arrow(PR.load_priority_label(cfg.get('load_priority'), cfg))])
        else:
            rows.append([L('Prioritas pasokan beban (off-grid)', 'Load supply priority (off-grid)'),
                         _arrow(PR.load_priority_off_label(cfg.get('load_priority'), cfg))])
    except Exception:
        rows += [list(r) for r in K.load_priority_rows(cfg)]
    if bess:
        rows.append([L('Prioritas pengisian BESS', 'BESS charging priority'),
                     'PV → Grid' if int(_g(p, 'charge_priority', 0) or 0) == 0 else 'Grid → PV'])
        rows.append([L('Strict charging priority', 'Strict charging priority'),
                     _yn(_g(p, 'strict_charge_priority', False))])
        if grid:
            gc = bool(_g(p, 'grid_charge_enabled', False))
            rows.append([L('Pengisian Grid → BESS', 'Grid → BESS charging'),
                         (_yn(gc) + (f" (SOC < {_pct(_g(p, 'charge_from_grid_below_soc', 0), 0)})"
                                     if gc else ''))])
    if grid and deg:
        rows.append([L('Interlock DEG – Grid (transfer switch)', 'DEG – Grid interlock (transfer switch)'),
                     _yn(_g(p, 'deg_grid_interlock', False))])
    if grid:
        rows.append([L('Interlock Grid – PV/BESS', 'Grid – PV/BESS interlock'),
                     _yn(_g(p, 'grid_interlock', False))])
    if deg:
        if bool(_g(p, 'deg_options_split', False)):
            rows.append([L('Interlock DEG – PV/BESS (grid ada / padam)',
                           'DEG – PV/BESS interlock (grid on / off)'),
                         f"{_yn(_g(p, 'deg_interlock_on'))} / {_yn(_g(p, 'deg_interlock_off'))}"])
            if bess:
                on = _g(p, 'deg_charge_on') and not _g(p, 'deg_interlock_on')
                off = _g(p, 'deg_charge_off') and not _g(p, 'deg_interlock_off')
                rows.append([L('Pengisian DEG → BESS (grid ada / padam)',
                               'DEG → BESS charging (grid on / off)'),
                             f"{_yn(on)} / {_yn(off)}"])
        else:
            rows.append([L('Interlock DEG – PV/BESS', 'DEG – PV/BESS interlock'),
                         _yn(_g(p, 'deg_interlock', True))])
            if bess:
                rows.append([L('Pengisian DEG → BESS', 'DEG → BESS charging'),
                             _yn(_g(p, 'deg_charge_enabled', False)
                                 and not _g(p, 'deg_interlock', True))])
        if A['n_deg'] > 1:
            rows.append([L('Genset dapat sinkron (load sharing)', 'Gensets can synchronise (load sharing)'),
                         _yn(_g(p, 'deg_sync', True))])
        da = bool(_g(p, 'deg_always', False))
        gf = int(_g(p, 'deg_grid_former', 0) or 0)
        rows.append([L('DEG wajib selalu menyala (saat grid padam)',
                       'DEG must always run (when grid unavailable)'),
                     _yn(da) + ((' — ' + L('grid-forming', 'grid-forming') + ': '
                                 + ('Auto' if gf == 0 else f'DEG-{gf}')) if da else '')])
    if grid:
        rows.append([L('Ekspor surplus PV ke grid', 'PV surplus export to grid'),
                     _yn(_g(p, 'allow_export', False))])
    return rows


# =========================================================== arsitektur ===
def arch_spec(A, cfg, p):
    sz = A['sizes']
    C = K.C
    cols = []
    if A['has_pv']:
        cols.append(dict(key='pv', color=C['pv'],
                         top=(L('Array PV', 'PV array'), f"{_n(sz['kwp'], 1)} kWp"),
                         mid=(L('Inverter PV', 'PV inverter'), f"{_n(sz['kw_inv'], 1)} kW AC"),
                         link='DC', flow='down'))
    if A['has_bess']:
        cols.append(dict(key='bess', color=C['bess'],
                         top=('BESS', f"{_n(sz['kwh_bess'], 0)} kWh · "
                              f"{_n(A['usable_kwh'], 0)} " + L('guna', 'usable')),
                         mid=('PCS', f"{_n(cfg.get('max_charge_kw'), 0)}/"
                              f"{_n(cfg.get('max_discharge_kw'), 0)} kW"),
                         link='DC', flow='both'))
    if A['has_deg']:
        caps = [c for c in A['deg_caps'] if c > 0]
        rating = (f"{len(caps)} × {_n(caps[0], 0)} kW" if len(set(caps)) == 1
                  else f"{len(caps)} × (" + ' + '.join(_n(c, 0) for c in caps) + ') kW')
        sync = len(caps) > 1 and bool(_g(p, 'deg_sync', True))
        cols.append(dict(key='deg', color=C['deg'],
                         top=(L('Genset diesel', 'Diesel genset'), rating),
                         mid=((L('Panel sinkron', 'Sync panel'), L('berbagi beban', 'load sharing'))
                              if sync else
                              (L('Panel genset', 'Genset panel'),
                               L('satu unit per waktu', 'one unit at a time')
                               if len(caps) > 1 else 'AMF')),
                         link='AC', flow='down'))
    if A['grid_on']:
        exp = bool(_g(p, 'allow_export', False))
        cols.append(dict(key='grid', color=C['grid'],
                         top=(L('Grid utilitas', 'Utility grid'), f"{_n(cfg.get('grid_kw'), 1)} kW"),
                         mid=(L('PCC & kWh meter', 'PCC & kWh meter'),
                              L('ekspor-impor', 'import-export') if exp
                              else L('impor saja', 'import only')),
                         link='AC', flow='both' if exp else 'down'))
    peak = A.get('peak_kw', float('nan'))
    load_sub = ((L('puncak', 'peak') + f" {_n(peak, 1)} kW · ") if peak == peak else '') + \
        f"{_n(A['load_kwh'] / 1000.0, 1)} MWh/" + L('thn', 'yr')
    act = adv_active(p)
    ems_sub = ((f"Advanced · {len(act)} " + L('fungsi', 'functions')) if is_advanced(p)
               else L('Dispatch standar', 'Standard dispatch'))
    return dict(columns=cols, load=(L('Beban', 'Load'), load_sub),
                ems=(L('EMS / pengendali pembangkit', 'EMS / plant controller'), ems_sub),
                ats=bool(A['grid_on'] and A['has_deg'] and _g(p, 'deg_grid_interlock', False)),
                bus_label=L('Rel AC', 'AC bus'))


def power_path_rows(A, cfg, p):
    """[jalur, diizinkan, kondisi] — diturunkan dari flag efektif engine."""
    rows = []
    grid, deg, bess, pv = A['grid_on'], A['has_deg'], A['has_bess'], A['has_pv']
    adv = is_advanced(p)
    if pv:
        rows.append(['PV → ' + L('Beban', 'Load'), _yn(True),
                     L('sesuai rantai prioritas, dibatasi inverter',
                       'per priority chain, limited by the inverter')])
    if pv and bess:
        rows.append(['PV → BESS', _yn(True),
                     L('surplus PV, dibatasi sisa kapasitas inverter, PCS & SOC maks.',
                       'PV surplus, limited by remaining inverter capacity, PCS & max SOC')])
    if bess:
        rows.append(['BESS → ' + L('Beban', 'Load'), _yn(True),
                     L('menurut fungsi EMS Advanced yang aktif', 'according to the active '
                       'Advanced EMS functions') if adv else
                     L('menutup kekurangan sesuai rantai prioritas, di atas SOC min.',
                       'covers shortfall per priority chain, above min SOC')])
    if grid:
        rows.append(['Grid → ' + L('Beban', 'Load'), _yn(True),
                     L('menghormati loading minimum/maksimum grid',
                       'respecting grid minimum/maximum loading')])
        if bess:
            gc = bool(_g(p, 'grid_charge_enabled', False))
            rows.append(['Grid → BESS', _yn(gc),
                         (L('hanya bila SOC < ', 'only when SOC < ')
                          + _pct(_g(p, 'charge_from_grid_below_soc', 0), 0)) if gc else '-'])
    if deg:
        if grid and _g(p, 'deg_grid_interlock', False):
            cond = L('hanya saat grid padam atau tidak sanggup (transfer)',
                     'only when the grid is down or insufficient (transfer)')
        else:
            cond = L('saat sumber berprioritas lebih tinggi tidak mencukupi',
                     'when higher-priority sources are insufficient')
        if _g(p, 'deg_always', False):
            cond += L('; wajib menyala saat grid padam', '; must run when grid is down')
        rows.append(['DEG → ' + L('Beban', 'Load'), _yn(True), cond])
        if bess:
            dchg = (bool(_g(p, 'deg_charge_enabled', False)) and not _g(p, 'deg_interlock', True)) \
                or (bool(_g(p, 'deg_options_split', False))
                    and ((_g(p, 'deg_charge_on') and not _g(p, 'deg_interlock_on'))
                         or (_g(p, 'deg_charge_off') and not _g(p, 'deg_interlock_off'))))
            dmin = adv and float(_g(p, 'm_dg_minload', 0) or 0) > 0.5
            rows.append(['DEG → BESS', _yn(dchg or dmin),
                         L('hanya untuk menaikkan genset ke loading minimum',
                           'only to lift the genset to its minimum loading')
                         if (dchg or dmin) else '-'])
    if grid and pv:
        ex = bool(_g(p, 'allow_export', False))
        rows.append(['PV → Grid (' + L('ekspor', 'export') + ')', _yn(ex),
                     L('kelebihan PV saja, dibatasi inverter & kapasitas grid',
                       'PV excess only, limited by inverter & grid capacity') if ex else '-'])
    if grid and deg:
        rows.append([L('DEG paralel Grid', 'DEG in parallel with Grid'),
                     _yn(not _g(p, 'deg_grid_interlock', False)), '-'])
    if deg and (pv or bess):
        par = not _g(p, 'deg_interlock', True)
        rows.append([L('DEG paralel PV/BESS', 'DEG in parallel with PV/BESS'), _yn(par),
                     '-' if par else L('saat genset memikul beban, PV hanya mengisi BESS & '
                                       'BESS tidak discharge',
                                       'while the genset carries load, PV only charges the '
                                       'BESS and the BESS does not discharge')])
    if grid and (pv or bess):
        rows.append([L('Grid paralel PV/BESS', 'Grid in parallel with PV/BESS'),
                     _yn(not _g(p, 'grid_interlock', False)), '-'])
    return rows


# ============================================================ metodologi ===
def methodology(D, A, cfg, p, tech, finx):
    """Lampiran A — Metodologi & Persamaan (sesuai algoritma engine v138)."""
    D.section(L('Metodologi & Persamaan', 'Methodology & Equations'), appendix_letter='A')
    eq = lambda s: D.add(t='eq', latex=s)
    D.p(L("Lampiran ini mendokumentasikan model perhitungan yang dipakai dalam studi ini "
          "(mesin dispatch, indikator teknis, model finansial dan simulasi umur "
          "proyek). Notasi: Δt = durasi langkah (jam); seluruh daya dalam kW dan energi "
          "dalam kWh; indeks t = langkah waktu, y = tahun proyek.",
          "This appendix documents the calculation model used in this study (dispatch "
          "engine, technical indicators, financial model and project-lifetime "
          "simulation). Notation: Δt = step duration (h); all power in kW and energy in "
          "kWh; index t = time step, y = project year."))

    if tech:
        # ---- A.1 kerangka simulasi -----------------------------------------
        D.sub(L('Kerangka Simulasi & Anualisasi', 'Simulation Framework & Annualisation'))
        D.p(L("Simulasi berjalan kronologis per langkah waktu Δt (1 jam, 30 menit, atau "
              "lebih halus) atas deret beban, profil PV ENetAC, status grid, dan (opsional) "
              "status ketersediaan DEG. Profil PV diskalakan dari kapasitas acuan profil "
              "ke kapasitas terpasang. Bila periode yang disimulasikan kurang dari setahun, "
              "akumulator energi diekstrapolasi ke setahun; jam operasi dihitung dari "
              "jumlah langkah × Δt lalu dianualisasi dengan faktor yang sama. Rasio (RF, "
              "siklus, loading) tidak berubah oleh anualisasi.",
              "The simulation runs chronologically in time steps Δt (1 h, 30 min or "
              "finer) over the load series, PV ENetAC profile, grid status and "
              "(optionally) DEG availability status. The PV profile is scaled from the "
              "profile reference capacity to the installed capacity. When the simulated "
              "period is shorter than one year, energy accumulators are extrapolated to "
              "one year; operating hours are counted as steps × Δt and annualised with "
              "the same factor. Ratios (RF, cycles, loading) are unaffected by "
              "annualisation."))
        eq(r'$q_t = p_t\,\dfrac{kWp}{kWp_{ref}},\qquad k_{ann} = \dfrac{8760}{n\,\Delta t},'
           r'\qquad E^{yr} = k_{ann}\sum_t x_t\,\Delta t,\qquad h^{yr} = k_{ann}\,\Delta t\sum_t \mathbf{1}[\cdot]_t$')
        D.p(L("Simbol utama per langkah: L = beban; q = PV tersedia (ENetAC); S = output "
              "inverter PV; T = kurtailmen; AC = beban dilayani PV+BESS; AD = beban dilayani "
              "grid; X = discharge BESS; V, W, C_D = charge BESS dari PV, grid, DEG; U = V+W+C_D; "
              "P = output DEG total; I = impor grid; Z = energi tersimpan BESS; E = kapasitas "
              "nominal; η = efisiensi round-trip; H = kapasitas sambungan grid.",
              "Main per-step symbols: L = load; q = available PV (ENetAC); S = PV inverter "
              "output; T = curtailment; AC = load served by PV+BESS; AD = load served by "
              "grid; X = BESS discharge; V, W, C_D = BESS charge from PV, grid, DEG; "
              "U = V+W+C_D; P = total DEG output; I = grid import; Z = BESS stored energy; "
              "E = nominal capacity; η = round-trip efficiency; H = grid connection capacity."))

        # ---- A.2 model BESS --------------------------------------------------
        D.sub(L('Model BESS', 'BESS Model'))
        D.p(L("Efisiensi round-trip dibagi rata ke sisi charge dan discharge (√η). "
              "Potensi discharge dan ruang charge tiap langkah dibatasi energi tersimpan, "
              "jendela SOC, dan rating PCS. BESS tidak boleh charge dan discharge pada "
              "langkah yang sama: bila ada discharge untuk beban, seluruh charge ditunda.",
              "Round-trip efficiency is split evenly between charge and discharge (√η). "
              "Discharge potential and charge headroom in each step are bounded by stored "
              "energy, the SOC window and the PCS rating. The BESS cannot charge and "
              "discharge in the same step: when it discharges to serve load, all charging "
              "is deferred."))
        eq(r'$X_t \leq \min\!\left(P_{dis},\ \dfrac{(Z_t - SOC_{min}E)\sqrt{\eta}}{\Delta t}\right),'
           r'\qquad U_t \leq \min\!\left(P_{ch},\ \dfrac{SOC_{max}E - Z_t}{\sqrt{\eta}\,\Delta t}\right),'
           r'\qquad X_t\,U_t = 0$')
        eq(r'$Z_{t+1} = \mathrm{clip}\!\left(Z_t + U_t\sqrt{\eta}\,\Delta t - \dfrac{X_t\,\Delta t}'
           r'{\sqrt{\eta}},\ SOC_{min}E,\ SOC_{max}E\right)$')

        # ---- A.3 PV, grid, rantai prioritas ---------------------------------
        D.sub(L('PV, Grid & Rantai Prioritas Beban', 'PV, Grid & Load Priority Chain'))
        D.p(L("Seluruh aliran PV melewati satu inverter: PV untuk beban dan PV untuk charge "
              "berbagi kapasitas inverter, dan PV yang tidak tersalur menjadi kurtailmen "
              "(atau ekspor bila diizinkan). Grid memasok beban dengan menghormati loading "
              "minimum dan maksimum, namun tidak pernah melebihi sisa beban.",
              "All PV flows pass through one inverter: PV to load and PV to charge share "
              "the inverter capacity, and undelivered PV becomes curtailment (or export when "
              "allowed). The grid supplies load respecting its minimum and maximum loading, "
              "but never more than the remaining load."))
        eq(r'$S_t = \min(pv_{load,t} + V_t,\ P_{inv}),\qquad T_t = q_t - S_t - Exp_t,'
           r'\qquad Exp_t \leq \min(T_t,\ P_{inv} - S_t,\ g_{max}H - AD_t - W_t)$')
        eq(r'$AD_t = \min\!\left(\max\!\left(g_{min}H,\ \min(g_{max}H,\ r_t)\right),\ r_t\right),'
           r'\qquad I_t = AD_t + W_t$')
        D.p(L("Beban dipasok berurutan menurut rantai prioritas yang dipilih: setiap sumber "
              "mengambil sebanyak mungkin dari sisa beban dalam batas kemampuannya "
              "(PV ≤ inverter, BESS ≤ PCS & SOC, grid ≤ g_max·H, DEG ≤ ΣD·L_max), lalu sisa "
              "diteruskan ke sumber berikutnya:",
              "Load is supplied sequentially along the selected priority chain: each "
              "source takes as much of the remaining load as it can within its capability "
              "(PV ≤ inverter, BESS ≤ PCS & SOC, grid ≤ g_max·H, DEG ≤ ΣD·L_max), and the "
              "remainder passes to the next source:"), keep=True)
        eq(r'$r_0 = L_t,\qquad s_k = \min(Cap_{k,t},\ r_{k-1}),\qquad r_k = r_{k-1} - s_k$')
        eq(r'$Unserved_t = \max\!\left(0,\ L_t - AC_t - AD_t - (P_t - C_{D,t})\right)$')
        D.table([L('Rantai', 'Chain'), L('Perilaku', 'Behaviour')], _chain_rows(),
                align=['l', 'l'], widths=[0.34, 0.66], font=7.5,
                caption=L('Rantai prioritas beban yang tersedia di engine',
                          'Load priority chains available in the engine'))
        D.p(L("Bila opsi Load Priority Follows Grid Status aktif, engine menghitung dua "
              "skenario (grid tersedia dan grid padam) dan memilih hasilnya per langkah "
              "menurut status grid; hal yang sama berlaku untuk DEG Options Follow Grid "
              "Status (interlock DEG–PV/BESS dan izin charging DEG).",
              "When Load Priority Follows Grid Status is enabled, the engine evaluates "
              "two scenarios (grid available and grid down) and selects the result per step "
              "according to grid status; the same applies to DEG Options Follow Grid "
              "Status (DEG–PV/BESS interlock and DEG charging permission)."))

        # ---- A.4 interlock & charging ---------------------------------------
        D.sub(L('Interlock & Aturan Pengisian', 'Interlocks & Charging Rules'))
        D.bullets([
            L("**Interlock DEG–Grid** (transfer switch): grid dan genset tidak pernah "
              "memasok bersamaan. Bila grid + PV + BESS tidak sanggup memikul beban, sistem "
              "beralih ke genset dan grid dilepas pada langkah itu.",
              "**DEG–Grid interlock** (transfer switch): grid and genset never supply "
              "together. If grid + PV + BESS cannot carry the load, the system transfers to "
              "the genset and the grid is disconnected for that step."),
            L("**Interlock DEG–PV/BESS:** saat genset memikul beban, PV hanya mengisi BESS "
              "dan BESS tidak discharge; interlock ini otomatis meniadakan charging dari DEG.",
              "**DEG–PV/BESS interlock:** while the genset carries load, PV only charges the "
              "BESS and the BESS does not discharge; this interlock automatically disables "
              "DEG charging."),
            L("**Interlock Grid–PV/BESS:** beban dilayani grid ATAU PV-BESS secara eksklusif; "
              "PV-BESS dipakai bila sanggup memikul seluruh beban (atau grid padam), selain "
              "itu grid yang memikul dan PV hanya mengisi BESS.",
              "**Grid–PV/BESS interlock:** load is served by grid OR PV-BESS exclusively; "
              "PV-BESS is used when it can carry the whole load (or the grid is down), "
              "otherwise the grid carries it and PV only charges the BESS."),
            L("**Prioritas pengisian** PV → Grid atau Grid → PV menentukan sumber yang "
              "mengisi lebih dulu dari sisa PCS & ruang SOC; pada mode strict sumber kedua "
              "menunggu sampai sumber pertama berhenti mengisi. Grid hanya mengisi saat "
              "SOC < ambang Charge from Grid below SOC.",
              "**Charging priority** PV → Grid or Grid → PV sets which source charges first "
              "from the remaining PCS & SOC headroom; in strict mode the second source "
              "waits until the first stops charging. The grid only charges while SOC < the "
              "Charge from Grid below SOC threshold."),
        ])
        eq(r'$W_t \leq \min\!\left(g_{max}H - AD_t,\ P_{ch} - V_t,\ '
           r'\dfrac{SOC_{max}E - Z_t}{\sqrt{\eta}\,\Delta t} - V_t\right)\ \ \mathrm{if}\ \ '
           r'Z_t/E < SOC_{grid}$')

        if A['has_deg']:
            # ---- A.5 genset --------------------------------------------------
            D.sub(L('Alokasi Genset, Loading Minimum & Bahan Bakar',
                    'Genset Allocation, Minimum Loading & Fuel'))
            D.p(L("**Genset sinkron** (load sharing): unit dinyalakan bertahap menurut "
                  "ambang ΣD·L_max dan beban AE dibagi proporsional kapasitas unit yang "
                  "menyala.",
                  "**Synchronised gensets** (load sharing): units are started in stages "
                  "against ΣD·L_max thresholds and the load AE is shared in proportion to "
                  "the capacity of the running units."), keep=True)
            eq(r'$AE \leq D_1L_{max}:\ M_1 = AE;\qquad AE \leq (D_1+D_2)L_{max}:\ '
               r'M_i = AE\,\dfrac{D_i}{D_1+D_2};\qquad \mathrm{else}:\ '
               r'M_i = AE\,\dfrac{D_i}{D_1+D_2+D_3}$')
            D.p(L("**Genset tidak sinkron:** hanya satu unit menyala — unit terkecil yang "
                  "sanggup memikul AE; bila tak ada, unit terbesar pada loading maksimum "
                  "(sisa menjadi beban tak terlayani).",
                  "**Non-synchronised gensets:** only one unit runs — the smallest unit able "
                  "to carry AE; if none can, the largest unit at maximum loading (the rest "
                  "becomes unserved load)."), keep=True)
            eq(r'$i^{*} = \mathrm{arg\,min}_{\,i\,:\,D_iL_{max} \geq AE}\ D_i,\qquad '
               r'M_{i^{*}} = \min(AE,\ D_{i^{*}}L_{max})$')
            D.p(L("**Charging dari DEG** (bila diizinkan dan tanpa interlock DEG–PV/BESS): "
                  "genset menaikkan output hanya sebesar kekurangan terhadap loading minimum "
                  "unit yang menyala, dan kelebihannya mengisi BESS.",
                  "**DEG charging** (when allowed and without DEG–PV/BESS interlock): the "
                  "genset raises its output only by the shortfall against the minimum "
                  "loading of the running units, and the excess charges the BESS."), keep=True)
            eq(r'$C_{D,t} = \min\!\left(\max(0,\ \sum_{run}D_iL_{min} - P^{base}_t),\ '
               r'P_{ch} - V_t - W_t,\ \dfrac{SOC_{max}E - Z_t}{\sqrt{\eta}\,\Delta t} - V_t - W_t\right)$')
            D.p(L("**DEG wajib selalu menyala** (opsional, hanya saat grid tidak tersedia): "
                  "satu genset grid-forming memikul beban lebih dulu sampai loading "
                  "minimumnya, menggantikan discharge BESS lalu PV. Pada pilihan Auto, unit "
                  "grid-forming dipilih per langkah sebagai unit yang loading minimumnya "
                  "paling dekat dengan beban. Kolom DEG Status = 0 menandai jam DEG tidak "
                  "tersedia (kapasitas seluruh unit = 0 pada jam itu).",
                  "**DEG must always run** (optional, only when the grid is unavailable): "
                  "one grid-forming genset carries load first up to its minimum loading, "
                  "displacing BESS discharge and then PV. With Auto, the grid-forming unit is "
                  "chosen per step as the unit whose minimum loading is closest to the load. "
                  "A DEG Status value of 0 marks hours in which the DEG is unavailable (all "
                  "unit capacities = 0 in that hour)."), keep=True)
            eq(r'$i_{gf} = \mathrm{arg\,min}_{\,i}\ \left|D_iL_{min} - L_t\right|,\qquad '
               r'\mathrm{Fuel} = \sum_{i}r_i\,E_{DEG,i},\qquad '
               r'h_{run} = \Delta t\sum_t\mathbf{1}[P_t > 0]$')

        # ---- A.6 Advanced EMS -----------------------------------------------
        if is_advanced(p):
            _adv_method(D, eq, p)

        # ---- A.7 indikator kinerja -------------------------------------------
        D.sub(L('Indikator Kinerja Teknis', 'Technical Performance Indicators'))
        eq(r'$RF = \dfrac{\sum AC_t\,\Delta t}{\sum L_t\,\Delta t},\qquad '
           r'n_{cyc} = \dfrac{\sum X_t\,\Delta t}{E\,(SOC_{max} - SOC_{min})},\qquad '
           r'r_{curt} = \dfrac{\sum T_t\,\Delta t}{\sum q_t\,\Delta t}$')
        eq(r'$SR = \dfrac{\sum (AC_t + AD_t + P_t)\,\Delta t}{\sum L_t\,\Delta t},\qquad '
           r'\overline{LF}_{DEG} = \dfrac{1}{h_{run}}\sum_{P_t>0}\dfrac{P_t}{\sum D_i}\,\Delta t$')
        D.p(L("Fraksi terbarukan (RF) dihitung sebagai porsi beban yang dilayani PV+BESS. "
              "Klasifikasi mode operasi membagi tiap langkah ke 32 kasus: status grid "
              "(1/0) × PV (tersedia/tidak) × BESS (charge / tak dapat charge / discharge / "
              "tak dapat discharge) × DEG (ON/OFF).",
              "The renewable fraction (RF) is the share of load served by PV+BESS. The "
              "operating-mode classification assigns each step to one of 32 cases: grid "
              "status (1/0) × PV (available/not) × BESS (charge / cannot charge / "
              "discharge / cannot discharge) × DEG (ON/OFF)."))

    if finx:
        _fin_method(D, eq, A, cfg)

    # ---- umur proyek (teknis & finansial) -----------------------------------
    D.sub(L('Simulasi Multi-Year (Umur Proyek)', 'Multi-Year Simulation (Project Lifetime)'))
    D.p(L("Seluruh tahun proyek disimulasikan dengan mesin dispatch dan opsi yang sama "
          "dengan tahun-1 (dalam satu batch tervektorisasi); hanya kapasitas yang "
          "berubah. Kapasitas PV terdegradasi tiap tahun; kapasitas BESS dan limit daya "
          "PCS mengikuti SOH. BESS diganti (SOH kembali 100%) bila umurnya mencapai BESS "
          "lifetime ATAU SOH turun di bawah ambang; biaya penggantian tereskalasi inflasi.",
          "Every project year is simulated with the same dispatch engine and options as "
          "year 1 (in one vectorised batch); only capacities change. PV capacity degrades "
          "each year; BESS capacity and PCS power limits follow the SOH. The BESS is "
          "replaced (SOH back to 100%) when its age reaches the BESS lifetime OR the SOH "
          "falls below the threshold; the replacement cost is inflation-escalated."))
    eq(r'$kWp_y = kWp\,(1-\delta_{PV})^{\,y-1},\qquad SOH_y = (1-\delta_{B})^{\,a_y},\qquad '
       r'E_y = E\,SOH_y,\qquad P_{ch/dis,y} = P_{ch/dis}\,SOH_y$')
    eq(r'$\mathrm{replace\ in\ year}\ y \Leftrightarrow a_y \geq \mathrm{life}_{B}\ \vee\ '
       r'SOH_y < SOH_{thr}\quad (a_y \rightarrow 0)$')

    if tech:
        D.sub(L('Validasi & Invarian', 'Validation & Invariants'))
        D.p(L("Mesin dispatch diuji terhadap invarian fisis untuk seluruh kombinasi opsi: "
              "keseimbangan energi (pasokan = beban terlayani + pengisian BESS + "
              "kurtailmen), tidak ada over-serve, tidak ada beban tak terlayani selama "
              "sumber masih sanggup, SOC selalu di dalam jendela, dan seluruh batas daya "
              "perangkat dihormati. Jalur mode Standard setahun per jam identik dengan "
              "model referensi independen (deviasi < 10⁻⁶ kWh). Pengujian verifikasi "
              "dilakukan terpisah; laporan ini tidak mengulangnya.",
              "The dispatch engine is tested against physical invariants for every option "
              "combination: energy balance (supply = served load + BESS charging + "
              "curtailment), no over-serve, no unserved load while a source is still able, "
              "SOC always within its window, and all device power limits respected. The "
              "one-year hourly Standard path is identical to an independent reference "
              "model (deviation < 10⁻⁶ kWh). The verification tests are run separately; "
              "this report does not re-run them."))


def _chain_rows():
    return [
        ['PV → Grid → BESS → DEG',
         L("PV lebih dulu (menyisakan loading minimum grid), grid memikul sisanya, BESS "
           "hanya menutup kekurangan di atas kapasitas grid, DEG cadangan terakhir.",
           "PV first (leaving the grid minimum loading), grid carries the rest, BESS only "
           "covers shortfall above grid capacity, DEG last resort.")],
        ['Grid → PV → BESS → DEG',
         L("Grid lebih dulu hingga loading maksimum; PV lalu BESS menutup sisanya; DEG "
           "cadangan terakhir.",
           "Grid first up to its maximum loading; PV then BESS cover the rest; DEG last "
           "resort.")],
        ['PV → BESS → Grid → DEG',
         L("PV lalu BESS lebih dulu (menyisakan loading minimum grid); grid mengambil "
           "sisanya; DEG cadangan terakhir — memaksimalkan energi surya.",
           "PV then BESS first (leaving the grid minimum loading); grid takes the rest; DEG "
           "last resort — maximises solar use.")],
        ['PV → Grid → DEG → BESS · Grid → DEG → PV → BESS',
         L("Varian saat DEG boleh paralel dengan grid: genset naik sebelum BESS.",
           "Variants when the DEG may run in parallel with the grid: the genset steps in "
           "before the BESS.")],
        ['Grid → PV → BESS → DEG (' + L('paralel', 'parallel') + ')',
         L("Genset cadangan terakhir tetapi boleh menyala paralel dengan grid.",
           "Genset is last resort but may run in parallel with the grid.")],
        ['Auto by Grid Status',
         L("Grid ada: Grid → DEG → PV → BESS, charge Grid → PV. Grid padam: PV → BESS → DEG "
           "dengan interlock DEG–PV/BESS, charge dari PV.",
           "Grid on: Grid → DEG → PV → BESS, charging Grid → PV. Grid down: PV → BESS → DEG "
           "with DEG–PV/BESS interlock, charging from PV.")],
        ['Grid → PV → BESS → DEG (auto-interlock)',
         L("Seperti rantai Grid dahulu; interlock DEG–PV/BESS hanya aktif saat grid padam.",
           "As the grid-first chain; the DEG–PV/BESS interlock is active only when the grid "
           "is down.")],
        [L('Grid padam / off-grid', 'Grid down / off-grid'),
         L("Posisi grid tidak berpengaruh: PV → BESS → DEG, PV → DEG → BESS, atau "
           "DEG → PV → BESS.",
           "The grid position has no effect: PV → BESS → DEG, PV → DEG → BESS, or "
           "DEG → PV → BESS.")],
    ]


def _adv_method(D, eq, p):
    act = adv_active(p)
    keys = [k for k, _n2, _p in act]
    D.sub(L('EMS BESS Mode Advanced', 'Advanced-Mode BESS EMS'))
    D.p(L("Pada mode Advanced, dispatch BESS baku dinonaktifkan dan seluruh aksi baterai "
          "dihitung oleh co-dispatch berbasis prioritas. Anggaran awal tiap langkah "
          "memperhitungkan cadangan operasi; tiap fungsi aktif, menurut urutan prioritas, "
          "mengambil dari sisa anggaran; permintaan charge dan discharge lalu dinetkan "
          "menjadi satu arah.",
          "In Advanced mode the standard BESS dispatch is disabled and every battery action "
          "is computed by the priority-based co-dispatch. The initial budget of each step "
          "accounts for the operating reserve; each active function, in priority order, "
          "draws from the remaining budget; charge and discharge requests are then netted "
          "into a single direction."), keep=True)
    eq(r'$Z_{floor} = SOC_{min}E + f_{res}(SOC_{max}-SOC_{min})E$')
    eq(r'$D_t = \min\!\left(P_{dis},\ \dfrac{(Z_t - Z_{floor})\sqrt{\eta}}{\Delta t}\right) - P_{res},\quad '
       r'C_t = \min\!\left(P_{ch},\ \dfrac{SOC_{max}E - Z_t}{\sqrt{\eta}\,\Delta t}\right)$')
    eq(r'$X^{net}_t = \max\!\left(0,\ \sum_m X_{m,t} - \sum_m U_{m,t}\right),\qquad '
       r'U^{net}_t = \max\!\left(0,\ \sum_m U_{m,t} - \sum_m X_{m,t}\right)$')
    if 'pv_smooth' in keys:
        D.p(L("**Smoothing PV** — setpoint = rata-rata bergerak kausal PV ENetAC (dibatasi "
              "inverter dan beban sisa) atas W langkah sebelumnya, lalu dibatasi laju ramp "
              "terhadap setpoint langkah sebelumnya. BESS discharge bila setpoint > PV dan "
              "charge bila setpoint < PV; kelebihan yang tidak terserap BESS dikurtail.",
              "**PV Smoothing** — setpoint = causal moving average of PV ENetAC (capped by "
              "the inverter and residual load) over the previous W steps, then ramp-limited "
              "against the previous setpoint. The BESS discharges when setpoint > PV and "
              "charges when setpoint < PV; excess the BESS cannot absorb is curtailed."),
            keep=True)
        eq(r'$MA_t = \dfrac{1}{W}\sum_{k=1}^{W}\tilde q_{t-k},\qquad '
           r'sp_t = \mathrm{clip}\!\left(MA_t,\ sp_{t-1} - 60R_{dn}\Delta t,\ sp_{t-1} + 60R_{up}\Delta t\right)$')
        eq(r'$X_t = \min(\max(0,sp_t - q_t), D_t),\quad U_t = \min(\max(0,q_t - sp_t), C_t)$')
    if 'firming' in keys:
        D.p(L("**Firming** — dalam jendela firming (dan saat PV > 0), setpoint = target "
              "daya konstan; di luar jendela setpoint = 0 sehingga PV hanya mengisi BESS. "
              "Jendela berbasis daya PV bekerja sebagai mesin-status harian (mulai saat PV > "
              "ambang pagi, berhenti saat PV < ambang sore, reset tengah malam).",
              "**Firming** — within the firming window (and while PV > 0), setpoint = "
              "constant target power; outside the window setpoint = 0 so PV only charges the "
              "BESS. The PV-power window is a daily state machine (starts when PV > morning "
              "threshold, stops when PV < evening threshold, resets at midnight)."), keep=True)
        eq(r'$sp_t = P_{firm}\,\mathbf{1}[t \in \mathrm{window},\ q_t > 0],\qquad '
           r'Met = \dfrac{\sum_{window}\Delta t\,\mathbf{1}[sp_t - q_t - X_t \leq 10^{-6}]}'
           r'{\sum_{window}\Delta t}$')
    if 'backup' in keys:
        D.p(L("**Backup** — pada outage total (grid padam dan kapasitas DEG = 0), BESS + PV "
              "memikul beban penuh dan menggantikan Smoothing/Firming. Bila prioritas Backup "
              "≤ prioritas Reserve, Backup boleh memakai energi & daya cadangan. Di luar "
              "outage BESS hanya mengisi dari surplus PV.",
              "**Backup** — in a total outage (grid down and DEG capacity = 0), BESS + PV "
              "carry the full load and override Smoothing/Firming. If the Backup priority ≤ "
              "the Reserve priority, Backup may use the reserved energy and power. Outside "
              "outages the BESS only charges from PV surplus."), keep=True)
        eq(r'$X_t = \min(\max(0, L_t - q_t),\ D^{bk}_t),\qquad '
           r'U_t = \min(\max(0, q_t - L_t),\ C_t)\qquad (\mathrm{total\ outage})$')
    if 'dg_minload' in keys:
        D.p(L("**Minimum Loading DG** — BESS menyerap output tambahan genset sebesar "
              "kekurangan terhadap loading minimum unit yang menyala (output genset "
              "dinaikkan sebesar nilai yang sama).",
              "**DG Minimum Loading** — the BESS absorbs extra genset output equal to the "
              "shortfall against the minimum loading of the running units (genset output is "
              "raised by the same amount)."), keep=True)
        eq(r'$C_{D,t} = \min\!\left(\max(0,\ \sum_{run}D_iL_{min} - P^{load}_t),\ C_t\right)$')
    if 'load_shift' in keys:
        D.p(L("**Load Shifting** — di jendela puncak BESS discharge menggantikan beban neto "
              "suplai target; di luar jendela BESS mengisi dari surplus PV. Impor grid "
              "dipisah puncak/luar-puncak untuk perhitungan tarif ToU.",
              "**Load Shifting** — in the peak window the BESS discharges to displace the net "
              "load on the target supply; outside the window it charges from PV surplus. Grid "
              "import is split peak/off-peak for the ToU tariff calculation."), keep=True)
        eq(r'$X_t = \min(N_t - X^{prev}_t,\ D_t)\ \ (t \in \mathrm{peak}),\qquad '
           r'U_t = \min(q^{surplus}_t,\ C_t)\ \ (t \notin \mathrm{peak})$')
    if 'peak_shave' in keys:
        D.p(L("**Peak Shaving** — BESS discharge sebesar kelebihan beban neto suplai target "
              "di atas ambang.",
              "**Peak Shaving** — the BESS discharges by the excess of the net load on the "
              "target supply above the threshold."), keep=True)
        eq(r'$X_t = \min\!\left(\max(0,\ N_t - X^{prev}_t - P_{thr}),\ D_t\right)$')
    D.note(L("N_t = beban neto suplai target (Grid, DEG, atau Grid + DEG sesuai Discharge "
             "Target); X^prev = discharge yang sudah dialokasikan fungsi berprioritas lebih "
             "tinggi pada langkah yang sama. Discharge mengurangi suplai target (grid "
             "lebih dulu pada pilihan Both).",
             "N_t = net load on the target supply (Grid, DEG, or Grid + DEG per the "
             "Discharge Target); X^prev = discharge already allocated by higher-priority "
             "functions in the same step. Discharge reduces the target supply (grid first "
             "for the Both option)."))


def _fin_method(D, eq, A, cfg):
    scope = str(cfg.get('finance_scope', 'PV-BESS-DEG') or 'PV-BESS-DEG')
    D.sub(L('Model Biaya: CAPEX, OPEX & Baseline', 'Cost Model: CAPEX, OPEX & Baseline'))
    D.p(L("CAPEX menjumlahkan biaya per satuan kapasitas dan biaya tetap sistem. OPEX "
          "tahunan mencakup O&M (fraksi CAPEX), bahan bakar, dan biaya impor grid "
          "dikurangi pendapatan ekspor; bila Load Shifting aktif dan tarif luar-puncak "
          "diisi, impor grid dikenai tarif ToU. Baseline adalah biaya energi tanpa PV+BESS.",
          "CAPEX sums the per-unit capacity costs and fixed system costs. Annual OPEX "
          "covers O&M (fraction of CAPEX), fuel and grid import cost minus export revenue; "
          "when Load Shifting is active and an off-peak tariff is set, grid import is "
          "charged at ToU tariffs. The baseline is the energy cost without PV+BESS."))
    eq(r'$CAPEX = c_{PV}kWp + c_{inv}kW_{inv} + c_{B}E + c_{DEG}kW_{DEG} + c_{EPC}kWp + '
       r'C_{acc} + C_{log}$')
    eq(r'$OPEX_1 = f_{OM}\,CAPEX + \mathrm{Fuel}\,c_{fuel} + C_{grid} - E_{exp}c_{exp},\qquad '
       r'C_{grid} = E_{pk}c_{grid} + E_{opk}c_{opk}\ \ (\mathrm{ToU})\ \ \mathrm{or}\ \ E_{imp}c_{grid}$')
    eq(r'$B^{diesel}_1 = E_L\,r_{eff}\,c_{fuel},\qquad '
       r'B^{grid+diesel}_1 = E_g c_{grid} + (E_L - E_g)\,r_{eff}\,c_{fuel},\quad E_g = \min(E_L, E_{imp})$')
    D.sub(L('Arus Kas & Indikator Investasi', 'Cash Flow & Investment Indicators'))
    D.p(L("Arus kas tahun-0 = −CAPEX sistem penuh. Tanpa simulasi multi-year, arus kas "
          "tahun y adalah penghematan tahun-1 yang dieskalasi inflasi. Dengan multi-year, "
          "energi, bahan bakar, dan impor grid diambil dari simulasi tiap tahun (harga "
          "dieskalasi) dan biaya penggantian BESS dikurangkan pada tahun terjadinya. "
          "NPV, IRR, payback, dan ROI selalu dihitung atas sistem penuh.",
          "Year-0 cash flow = −full-system CAPEX. Without a multi-year run, the year-y "
          "cash flow is the year-1 saving escalated by inflation. With multi-year, energy, "
          "fuel and grid import are taken from each year's simulation (prices escalated) "
          "and BESS replacement cost is deducted in the year it occurs. NPV, IRR, payback "
          "and ROI are always computed for the full system."))
    eq(r'$CF_y = (B_1 - OPEX_1)(1+i)^{\,y-1}\quad \mathrm{(year\!-\!1\ projection)},\qquad '
       r'CF_y = B_y - OPEX_y - R_y\quad \mathrm{(multi\!-\!year)}$')
    eq(r'$NPV = \sum_{y=0}^{Y}\dfrac{CF_y}{(1+d)^{y}},\qquad \sum_{y=0}^{Y}\dfrac{CF_y}{(1+IRR)^{y}} = 0,'
       r'\qquad ROI = \dfrac{\sum_{y\geq1}CF_y - CAPEX}{CAPEX}$')
    eq(r'$PB = (y^{*}-1) + \dfrac{-Cum_{y^{*}-1}}{CF_{y^{*}}},\qquad '
       r'y^{*} = \min\{y : Cum_y \geq 0\}$')
    D.p(L("IRR dicari numerik dengan metode bagi-dua pada rentang −95% hingga +200% "
          "(toleransi 10⁻⁶, maks. 200 iterasi); bila NPV tidak berganti tanda, IRR "
          "ditampilkan ‘-’.",
          "IRR is found numerically by bisection over −95% to +200% (tolerance 10⁻⁶, max. "
          "200 iterations); if NPV does not change sign, IRR is shown as ‘-’."))
    D.sub(L('LCOE & Cakupan Analisis', 'LCOE & Analysis Scope'))
    D.p(L(f"LCOE membagi biaya terdiskonto dengan energi terlayani terdiskonto. Cakupan "
          f"Financial Analysis pada studi ini: **{scope}**. PV-BESS-DEG = seluruh sistem "
          "dan beban terlayani total; PV-BESS = CAPEX PV/inverter/BESS + biaya tetap, OPEX "
          "hanya O&M, energi = beban dilayani PV+BESS; DEG = CAPEX genset + biaya tetap, "
          "OPEX penuh, energi = beban dilayani grid + DEG. Cakupan hanya memengaruhi LCOE "
          "serta CAPEX/OPEX yang ditampilkan.",
          f"LCOE divides discounted cost by discounted served energy. Financial Analysis "
          f"scope in this study: **{scope}**. PV-BESS-DEG = whole system and total served "
          "load; PV-BESS = PV/inverter/BESS CAPEX + fixed costs, OPEX = O&M only, energy = "
          "load served by PV+BESS; DEG = genset CAPEX + fixed costs, full OPEX, energy = "
          "load served by grid + DEG. The scope only affects LCOE and the displayed "
          "CAPEX/OPEX."))
    eq(r'$LCOE = \dfrac{CAPEX_s + \sum_{y=1}^{Y}\dfrac{OPEX_{s,1}(1+i)^{\,y-1}}{(1+d)^{y}}}'
       r'{\sum_{y=1}^{Y}\dfrac{E_s(1-\delta_{PV})^{\,y-1}}{(1+d)^{y}}}\ \ \mathrm{(year\!-\!1)}$')
    eq(r'$LCOE = \dfrac{CAPEX_s + \sum_{y}\dfrac{OPEX_{s,y} + R_y}{(1+d)^{y}}}{\sum_{y}\dfrac{E_{s,y}}{(1+d)^{y}}}'
       r'\ \ \mathrm{(multi\!-\!year)}$')
