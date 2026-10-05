"""Ekspor hasil simulasi & optimasi ke Excel/CSV (tanpa membutuhkan MS Excel)."""
from __future__ import annotations
import numpy as np
import pandas as pd

from ..config.i18n import tr
from ..engine.numeric import snap_zero
from ..config.parameters import soh_curve_active, parse_soh_curve


# --------------------------------------------------------------------------
_PRIO_SHORT = {
    'PV -> Grid -> BESS -> DEG': 'PV-Grid-BESS-DEG',
    'PV -> BESS -> Grid -> DEG': 'PV-BESS-Grid-DEG',
    'Grid -> PV -> BESS -> DEG': 'Grid-PV-BESS-DEG',
}
_CHG_SHORT = {'PV -> Grid': 'chgPV-Grid', 'Grid -> PV': 'chgGrid-PV'}


def _slug(text: str, maxlen: int = 28) -> str:
    """Potongan nama aman untuk nama file."""
    keep = []
    for ch in str(text).strip():
        if ch.isalnum() or ch in '-_':
            keep.append(ch)
        elif ch in ' .,/\\':
            keep.append('-')
    out = '-'.join(filter(None, ''.join(keep).split('-')))
    return out[:maxlen] or 'NA'


def export_filename(cfg: dict, prefix: str, ext: str = 'xlsx',
                    pv_kwp: float | None = None,
                    bess_kwh: float | None = None,
                    include_caps: bool = True) -> str:
    """<prefix>_<project>_<site>_<kapasitas>_<load prio>_<charge prio>.<ext>

    Komponen yang tidak ada pada sistem otomatis dihilangkan — baik dari
    bagian kapasitas maupun dari rantai prioritas. Contoh tanpa grid:
    ``PV-BESS-Grid-DEG`` menjadi ``PV-BESS-DEG``.
    """
    pv = float(cfg.get('pv_kwp', 0.0) if pv_kwp is None else pv_kwp)
    bs = float(cfg.get('bess_kwh', 0.0) if bess_kwh is None else bess_kwh)
    has = {
        'PV': pv > 0,
        'BESS': bs > 0,
        'GRID': bool(cfg.get('grid_enabled', True))
                and float(cfg.get('grid_kw', 0) or 0) > 0,
        'DEG': _deg_present(cfg),
    }

    caps = []
    if has['PV']:
        caps.append(f'PV{pv:g}kWp')
    if has['BESS']:
        caps.append(f'BESS{bs:g}kWh')
    if has['GRID']:
        caps.append(f'GRID{float(cfg.get("grid_kw", 0)):g}kW')
    if has['DEG']:
        caps.append(f'DEG{_deg_total_kw(cfg):g}kW')

    parts = [prefix,
             _slug(cfg.get('project_name', 'Project')),
             _slug(cfg.get('site_name') or cfg.get('location') or 'Site')]
    if caps and include_caps:
        parts.append('-'.join(caps))
    lp = _filter_chain(cfg.get('load_priority', ''), has)
    if lp:
        parts.append(lp)
    if has['BESS']:
        from ..config.parameters import grid_charge_allowed
        chg_has = dict(has)
        chg_has['GRID'] = has['GRID'] and grid_charge_allowed(cfg)
        cp = _filter_chain(cfg.get('charge_priority', ''), chg_has,
                           prefix='chg')
        if cp:
            # 'strict' hanya bermakna bila kedua sumber tersedia
            both = chg_has['GRID'] and chg_has['PV']
            parts.append(cp + ('-strict' if (both and cfg.get(
                'strict_charge_priority')) else ''))
    return '_'.join(p for p in parts if p) + '.' + ext


def _deg_count(cfg: dict) -> int:
    try:
        return int(str(cfg.get('deg_count', '1')))
    except Exception:
        return 1


def _deg_present(cfg: dict) -> bool:
    try:
        n = int(str(cfg.get('deg_count', '1')))
    except Exception:
        n = 1
    kw = [cfg.get('deg1_kw', 0), cfg.get('deg2_kw', 0), cfg.get('deg3_kw', 0)]
    return n > 0 and sum(float(k or 0) for k in kw[:n]) > 0


def _deg_total_kw(cfg: dict) -> float:
    try:
        n = int(str(cfg.get('deg_count', '1')))
    except Exception:
        n = 1
    kw = [cfg.get('deg1_kw', 0), cfg.get('deg2_kw', 0), cfg.get('deg3_kw', 0)]
    return float(sum(float(k or 0) for k in kw[:n]))


def _filter_chain(chain: str, has: dict, prefix: str = '') -> str:
    """'PV -> Grid -> BESS -> DEG' -> 'PV-BESS-DEG' bila grid tak ada."""
    if not chain:
        return ''
    toks = [t.strip() for t in str(chain).split('->') if t.strip()]
    keep = [t for t in toks if has.get(t.upper().replace('-', ''), True)]
    if not keep:
        return ''
    return (prefix + '-'.join(keep)) if prefix else '-'.join(keep)


def _eff_grid_interlock(cfg: dict) -> bool:
    """Status efektif (bukan sekadar centang): interlock grid hanya
    berlaku pada mode prioritas yang memisahkan grid dari PV-BESS."""
    from ..config.parameters import grid_interlock_active
    return bool(grid_interlock_active(cfg))


def _eff_grid_charge(cfg: dict) -> bool:
    from ..config.parameters import grid_charge_allowed
    return bool(grid_charge_allowed(cfg))


def system_presence(cfg: dict) -> dict:
    """Komponen apa saja yang benar-benar ada pada sistem ini."""
    return {
        'PV': float(cfg.get('pv_kwp', 0) or 0) > 0,
        'BESS': float(cfg.get('bess_kwh', 0) or 0) > 0,
        'GRID': bool(cfg.get('grid_enabled', True))
                and float(cfg.get('grid_kw', 0) or 0) > 0,
        'DEG': _deg_present(cfg),
    }


def info_dataframe(cfg: dict, extra: list | None = None) -> pd.DataFrame:
    """Lembar identitas — hanya memuat baris yang relevan dengan sistem.

    Komponen yang tidak ada (mis. tanpa grid) beserta seluruh opsi yang
    bergantung padanya tidak dituliskan, dan rantai prioritas dipangkas
    mengikuti komponen yang tersedia.
    """
    from datetime import datetime
    has = system_presence(cfg)
    pvbs = has['PV'] or has['BESS']

    rows = [
        (tr('Project Name'), cfg.get('project_name', '')),
        (tr('Customer'), cfg.get('customer', '')),
        (tr('Site Name'), cfg.get('site_name', '')),
        (tr('Location'), cfg.get('location', '')),
        (tr('Simulation Year'), cfg.get('simulation_year', '')),
        (tr('Exported At'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ('', ''),
    ]
    # ---- konfigurasi sistem ----
    if has['PV']:
        rows += [('PV Capacity (kWp)', cfg.get('pv_kwp', '')),
                 ('PV Inverter (kW)', cfg.get('pv_inv_kw', ''))]
    if has['BESS']:
        rows += [('BESS Nominal (kWh)', cfg.get('bess_kwh', '')),
                 ('BESS Max Charge (kW)', cfg.get('max_charge_kw', '')),
                 ('BESS Max Discharge (kW)', cfg.get('max_discharge_kw', ''))]
        try:
            _scv = float(cfg.get('bess_self_cons_kw', 0.0) or 0.0)
        except (TypeError, ValueError):
            _scv = 0.0
        if _scv > 0:
            rows += [('BESS Self Consumption (kWh/h)', _scv),
                     (tr('Self Consumption Supplied by'),
                      cfg.get('bess_sc_source', 'PV+BESS'))]
    if has['GRID']:
        rows += [('Grid Capacity (kW)', cfg.get('grid_kw', ''))]
    if has['DEG']:
        rows += [(tr('Total DEG'), cfg.get('deg_count', '')),
                 ('DEG Capacity (kW)', _deg_total_kw(cfg))]

    # ---- strategi dispatch (hanya yang berlaku) ----
    strategi = []
    lp = _filter_chain(cfg.get('load_priority', ''), has)
    if lp:
        strategi.append((tr('Load Supply Priority'), lp.replace('-', ' -> ')))
    if has['BESS']:
        chg_has = dict(has)
        chg_has['GRID'] = has['GRID'] and _eff_grid_charge(cfg)
        cp = _filter_chain(cfg.get('charge_priority', ''), chg_has)
        if cp:
            strategi.append((tr('BESS Charging Priority'),
                             cp.replace('-', ' -> ')))
        if chg_has['GRID'] and has['PV']:
            strategi.append((tr('Strict Charging Priority'),
                             bool(cfg.get('strict_charge_priority', False))))
        if has['GRID']:
            strategi.append((tr('Allow Grid Charging to BESS'),
                             _eff_grid_charge(cfg)))
        if has['DEG']:
            strategi.append((tr('Allow DEG Charging to BESS'),
                             bool(cfg.get('deg_charge_enabled', False))
                             and not bool(cfg.get('deg_interlock', True))))
    if has['GRID'] and pvbs:
        strategi.append((tr('Grid Interlock with PV-BESS'),
                         _eff_grid_interlock(cfg)))
    if has['GRID'] and has['DEG']:
        strategi.append((tr('DEG Interlock with Grid'),
                         bool(cfg.get('deg_grid_interlock', True))))
    if has['DEG'] and pvbs:
        strategi.append((tr('DEG Interlock with PV-BESS'),
                         bool(cfg.get('deg_interlock', True))))
    if has['GRID'] and pvbs:
        strategi.append(('PV-BESS Export to Grid',
                         bool(cfg.get('allow_export', False))))
    if strategi:
        rows += [('', '')] + strategi

    if extra:
        rows += [('', '')] + list(extra)
    return pd.DataFrame(rows, columns=[tr('Item'), 'Value'])


def annual_summary(kpi: dict, cfg: dict, year=None) -> dict:
    """Satu baris ringkasan tahunan bergaya tabel rekap (lihat sheet
    'Ringkasan Tahunan'). Nilai skalar; untuk multi-year tiap tahun satu baris.
    """
    def v(key, default=0.0):
        x = kpi.get(key, default)
        return float(np.asarray(x).reshape(-1)[0])

    load = v('annual_load_kwh')
    grid_use = v('grid_import_kwh')
    grid_load = v('grid_supply_ratio') * load
    pvbs_load = v('pvbs_supply_ratio') * load
    deg_load = v('diesel_energy_kwh') - v('deg_charge_kwh')
    pv_inv = v('annual_pv_inverter_out_kwh')
    chg_pv = v('pv_charge_kwh')
    grid_kw = (float(cfg.get('grid_kw', 0.0))
               if cfg.get('grid_enabled', True) else 0.0)
    hours = 8760.0
    has = system_presence(cfg)
    n_deg = _deg_count(cfg)
    row = {
        tr('Tahun'): year if year is not None else cfg.get('simulation_year', ''),
        # ---- Grid ----
        tr('Grid — Total Use (kWh)'): grid_use,
        tr('Grid — After Load (kWh)'): max(grid_use - grid_load, 0.0),
        tr('Grid — Loading'): (grid_use / (grid_kw * hours)
                               if grid_kw > 0 else 0.0),
        tr('Grid — Outage (jam)'): v('outage_hours', 0.0),
        # ---- DEG ----
        tr('DEG-1 (kWh)'): v('deg1_energy_kwh'),
        tr('DEG-2 (kWh)'): v('deg2_energy_kwh'),
        tr('DEG-3 (kWh)'): v('deg3_energy_kwh'),
        tr('DEG — Total (kWh)'): v('diesel_energy_kwh'),
        tr('DEG — Runtime (jam)'): v('diesel_runtime_h'),
        tr('DEG — Fuel (L)'): v('diesel_fuel_l'),
        # ---- PV ----
        tr('PV — ENetAC (kWh)'): v('annual_pv_generation_kwh'),
        tr('PV — After Load (kWh)'): max(
            v('annual_pv_generation_kwh')
            - max(pvbs_load - v('annual_battery_discharge_kwh'), 0.0), 0.0),
        tr('PV — Inverter Out (kWh)'): pv_inv,
        tr('PV — Unused/Curtailment (kWh)'): v('pv_excess_kwh'),
        # ---- BESS ----
        tr('BESS — Charge (kWh)'): v('annual_battery_charge_kwh'),
        tr('BESS — Charge from PV (kWh)'): chg_pv,
        tr('BESS — Charge from Grid (kWh)'): v('grid_charge_kwh', 0.0),
        tr('BESS — Charge from DEG (kWh)'): v('deg_charge_kwh'),
        tr('BESS — Discharge (kWh)'): v('annual_battery_discharge_kwh'),
        tr('BESS — Balance (kWh)'): (v('annual_battery_charge_kwh')
                                     - v('annual_battery_discharge_kwh')),
        tr('BESS — Throughput (kWh)'): v('battery_throughput_kwh'),
        tr('BESS — Cycles'): v('battery_cycles'),
        tr('BESS — SOC Min'): v('soc_min'),
        tr('BESS — SOC Max'): v('soc_max'),
        # ---- Load ----
        tr('Load — PV+BESS (kWh)'): pvbs_load,
        tr('Load — Grid (kWh)'): grid_load,
        tr('Load — DEG (kWh)'): deg_load,
        tr('Load — Needed (kWh)'): load,
        tr('Load — Unserved (kWh)'): v('unserved_kwh'),
        tr('Renewable Fraction'): v('renewable_fraction'),
        tr('PV Curtailment'): v('pv_excess_ratio'),
    }
    # buang kolom komponen yang tidak ada pada sistem ini
    drop = []
    if not has['GRID']:
        drop += [k for k in row if k.startswith(tr('Grid —'))
                 or k == tr('Load — Grid (kWh)')
                 or k == tr('BESS — Charge from Grid (kWh)')]
    if not has['DEG']:
        drop += [k for k in row if k.startswith(tr('DEG'))
                 or k == tr('Load — DEG (kWh)')
                 or k == tr('BESS — Charge from DEG (kWh)')]
    else:
        for i in (1, 2, 3):
            if i > n_deg:
                drop.append(tr(f'DEG-{i} (kWh)'))
    if not has['BESS']:
        drop += [k for k in row if k.startswith(tr('BESS —'))]
    if not has['PV']:
        drop += [k for k in row if k.startswith(tr('PV —'))
                 or k == tr('PV Curtailment')
                 or k == tr('BESS — Charge from PV (kWh)')]
    if not (has['PV'] or has['BESS']):
        drop.append(tr('Load — PV+BESS (kWh)'))
    for k in set(drop):
        row.pop(k, None)
    return {k: (snap_zero(val) if isinstance(val, float) else val)
            for k, val in row.items()}


def annual_summary_frame(kpi: dict, cfg: dict, years=None) -> pd.DataFrame:
    """DataFrame ringkasan: satu baris (single-year) atau per tahun."""
    if years is None:
        return pd.DataFrame([annual_summary(kpi, cfg)])
    rows = []
    for i, y in enumerate(years):
        one = {k: (np.asarray(v).reshape(-1)[i]
                   if np.size(v) == len(years) else v)
               for k, v in kpi.items()}
        rows.append(annual_summary(one, cfg, year=int(y)))
    return pd.DataFrame(rows)


def _coerce_datetimes(datetimes, n: int) -> pd.DatetimeIndex:
    """Kembalikan DatetimeIndex tepat sepanjang n. Bila lebih panjang → potong;
    lebih pendek/kosong → perpanjang memakai langkah (step) yang terdeteksi."""
    try:
        dti = pd.DatetimeIndex(datetimes) if datetimes is not None \
            else pd.DatetimeIndex([])
    except Exception:
        dti = pd.DatetimeIndex([])
    if len(dti) == n:
        return dti
    if len(dti) > n:
        return dti[:n]
    step = (dti[1] - dti[0]) if len(dti) >= 2 else pd.Timedelta(hours=1)
    base = dti[0] if len(dti) else pd.Timestamp('2025-01-01')
    return pd.DatetimeIndex([base + step * k for k in range(n)])


def _sim_datetimes(result: dict, datetimes) -> pd.DatetimeIndex:
    """Datetime index sepanjang deret hasil simulasi (jendela), dibangun dari
    metadata result (sim_interval + window_start_h). Menghindari mismatch antara
    datetimes DATA penuh (mis. 1 menit setahun = 525.600) & deret ter-jendela."""
    n = int(len(np.asarray(result['series']['load']).reshape(-1)))
    try:
        if datetimes is not None and len(datetimes) == n:
            return pd.DatetimeIndex(datetimes)
    except Exception:
        pass
    lab = str(result.get('sim_interval', '1 hour'))
    start_h = int(result.get('window_start_h', 0) or 0)
    try:
        from ..config import intervals as iv
        start = iv.window_start_datetime(datetimes, start_h)
        return pd.DatetimeIndex(iv.make_datetimes(lab, n, start=start))
    except Exception:
        return _coerce_datetimes(datetimes, n)


def series_dataframe(series: dict, datetimes, cfg: dict | None = None
                     ) -> pd.DataFrame:
    """Tabel per jam bergaya rekap: Datetime | Grid | DEG | PV | BESS | Load."""
    cfg = cfg or {}
    n = len(np.asarray(series['load']).reshape(-1))

    def col(key, scale=1.0):
        arr = np.asarray(series.get(key, np.zeros(n)))
        return snap_zero(arr.reshape(len(arr), -1)[:, 0] * scale)

    gkw = (float(cfg.get('grid_kw', 0) or 0)
           if cfg.get('grid_enabled', True) else 0.0)
    has = system_presence(cfg)
    n_deg = _deg_count(cfg)
    grid_use = col('grid')
    # Datetime HARUS sepanjang deret (n). Data resolusi tinggi (mis. 1 menit
    # setahun) menyimpan datetimes lebih panjang dari jendela simulasi → samakan
    # panjangnya agar DataFrame tak gagal ("All arrays must be of the same length").
    dti = _coerce_datetimes(datetimes, n)
    data = {tr('Datetime'): dti}
    data[tr('Grid — Total Use (kW)')] = grid_use
    grid_to_load = col('grid_load')
    data[tr('Grid — After Load (kW)')] = np.maximum(
        grid_use - grid_to_load, 0.0)          # sisa grid (mis. utk charge)
    data[tr('Grid — Loading')] = (grid_use / gkw if gkw > 0
                                  else np.zeros(n))
    data[tr('Grid — Status')] = col('grid_status')
    # DEG Status (import Excel, opsional): kode numerik 0/1/2 dulu (spt kolom
    # lain, ikut alur snap_zero di bawah) -> DIKONVERSI ke label '0'/'1'/'A'
    # SETELAH blok pembersihan (bukan di sini) -- kolom ini TEKS, tak boleh
    # ikut np.asarray(v, float) blanket di bawah (akan gagal utk 'A'). Tak
    # diimpor -> dicatat 2.0 (Auto) sepanjang waktu oleh dispatch.py -> 'A'.
    data[tr('DEG — Status')] = col('deg_status')
    for i in (1, 2, 3):
        data[tr(f'DEG-{i} (kW)')] = col(f'deg{i}')
    data[tr('DEG — Total (kW)')] = col('deg')
    data[tr('PV — ENetAC (kW)')] = col('pv')
    pv_to_load = np.maximum(col('pvbs_load') - col('dhg'), 0.0)
    data[tr('PV — After Load (kW)')] = np.maximum(
        col('pv') - pv_to_load, 0.0)           # sisa PV setelah beban
    data[tr('PV — Inverter Out (kW)')] = col('pv_inv_out')
    data[tr('PV — Unused/Curtailment (kW)')] = col('pv_excess')
    # Kolom simulasi shaping (Smoothing/Firming): PV & DEG/Grid, tanpa vs dgn BESS.
    # Term: PV only ≡ PV EnetAC (col 'pv'); PV with BESS ≡ Plant Inj (col 'plant_inj').
    _load_kw = col('load')
    data[tr('PV only (kW)')] = col('pv')                    # = PV EnetAC
    data[tr('PV with BESS (kW)')] = col('plant_inj')        # = Plant Inj (PV+BESS neto)
    # MA Setpoint: target yg HARUS dicapai Plant Inj/PV wBESS TANPA batasan
    # real (SOC/PCS/kurtailmen) — MA kausal PV (Smoothing) atau target konstan
    # (Firming). Bila ada kurtailmen/batasan, 'PV with BESS' di atas mengikuti
    # actual yg tersalur, bisa beda dari kolom ini. Nol di luar mode shaping.
    data[tr('MA Setpoint (kW)')] = col('ma_setpoint')
    data[tr('DEG with PV only (kW)')] = np.maximum(         # DEG/Grid tanpa BESS
        _load_kw - col('pv'), 0.0)
    data[tr('DEG with PV+BESS (kW)')] = col('grid') + col('deg')  # grid+DEG aktual
    data[tr('BESS — Charge (kW)')] = col('chg')
    data[tr('BESS — Charge from PV (kW)')] = col('chg_pv')
    data[tr('BESS — Charge from Grid (kW)')] = col('chg_grid')
    data[tr('BESS — Charge from DEG (kW)')] = col('chg_deg')
    data[tr('BESS — Discharge (kW)')] = col('dhg')
    data[tr('BESS — Balance (kW)')] = col('bess_net')
    data[tr('BESS — Cap Start (kWh)')] = col('cap_start')
    data[tr('BESS — Cap End (kWh)')] = col('cap_end')
    data[tr('BESS — SOC')] = col('soc')
    data[tr('Load — PV+BESS (kW)')] = col('pvbs_load')
    data[tr('Load — Grid (kW)')] = grid_to_load
    data[tr('Load — DEG (kW)')] = np.maximum(
        col('deg') - col('chg_deg') - col('self_cons_deg'), 0.0)
    data[tr('Load — Needed (kW)')] = col('load')
    data[tr('Load — Unserved (kW)')] = col('unserved')
    if has['BESS'] and float(np.sum(col('self_cons'))) > 0:
        data[tr('BESS — Self Consumption (kW)')] = col('self_cons')
    if has['GRID'] and float(np.sum(col('grid_export'))) > 0:
        data[tr('Grid — Export (kW)')] = col('grid_export')
    drop = []
    if not has['GRID']:
        drop += [k for k in data if k.startswith(tr('Grid —'))
                 or k == tr('Grid — Status')
                 or k == tr('Load — Grid (kW)')
                 or k == tr('BESS — Charge from Grid (kW)')]
    if not has['DEG']:
        drop += [k for k in data if k.startswith(tr('DEG'))
                 or k == tr('Load — DEG (kW)')
                 or k == tr('BESS — Charge from DEG (kW)')]
    else:
        for i in (1, 2, 3):
            if i > n_deg:
                drop.append(tr(f'DEG-{i} (kW)'))
    if not has['BESS']:
        drop += [k for k in data if k.startswith(tr('BESS —'))]
    if not has['PV']:
        drop += [k for k in data if k.startswith(tr('PV —'))
                 or k == tr('BESS — Charge from PV (kW)')]
    if not (has['PV'] or has['BESS']):
        drop.append(tr('Load — PV+BESS (kW)'))
    for k in set(drop):
        data.pop(k, None)
    # Bersihkan sisa pembulatan floating-point yang MUNCUL dari aritmatika kolom
    # (mis. col('pv') − pv_to_load = 1.78e-15) → snap ke 0 pada nilai final.
    # DEG — Status DIKECUALIKAN dari cast float blanket ini (kolom TEKS
    # '0'/'1'/'A', bukan kW) -- lihat konversi kode->label di bawah.
    _dt_key = tr('Datetime')
    _deg_status_key = tr('DEG — Status')
    data = {k: (v if k in (_dt_key, _deg_status_key)
               else snap_zero(np.asarray(v, float)))
            for k, v in data.items()}
    if _deg_status_key in data:
        from .importer import deg_status_to_label
        data[_deg_status_key] = [deg_status_to_label(c) for c in data[_deg_status_key]]
    return pd.DataFrame(data)


def dispatch_config_frame(cfg: dict) -> pd.DataFrame:
    """SELURUH setelan 'Dispatch Strategy' (dispatch energy) → tabel Key/Setting/
    Value untuk sheet konfigurasi di ekspor Excel."""
    from ..config.parameters import SCHEMA
    rows = []
    for p in SCHEMA.get('Dispatch Strategy', []):
        if getattr(p, 'dtype', '') == 'heading':
            rows.append(('', '— %s —' % tr(p.label), ''))     # pemisah sub-bagian
            continue
        v = cfg.get(p.key, p.default)
        unit = (' ' + tr(p.unit)) if getattr(p, 'unit', '') else ''
        rows.append((p.key, tr(p.label), '%s%s' % (v, unit)))
    return pd.DataFrame(rows, columns=['Key', tr('Setting'), tr('Value')])


def export_simulation(path: str, result: dict, datetimes, cfg: dict | None = None):
    # datetimes DATA penuh bisa lebih panjang dari deret ter-jendela → bangun
    # index yang sepanjang deret dari metadata simulasi (sim_interval + start).
    dts = _sim_datetimes(result, datetimes)
    df = series_dataframe(result['series'], dts, cfg)
    kpi = pd.DataFrame(sorted(result['kpi'].items()), columns=['KPI', 'Value'])
    # Window Moving Average Smoothing — hanya bila mode Smoothing aktif.
    _extra = []
    if result.get('pv_smooth_on') and result.get('ma_window') is not None:
        _w = int(result['ma_window'])
        kpi = pd.concat([kpi, pd.DataFrame(
            [('smoothing_ma_window', _w)], columns=['KPI', 'Value'])],
            ignore_index=True)
        _extra.append((tr('MA Window (Smoothing)'), _w))
    fin = None
    if result.get('finance'):
        fin = pd.DataFrame([(k, v) for k, v in result['finance'].items()
                            if not isinstance(v, np.ndarray)],
                           columns=['KPI', 'Value'])
    if path.lower().endswith('.csv'):
        df.to_csv(path, index=False)
    else:
        with pd.ExcelWriter(path, engine='openpyxl') as xw:
            if cfg is not None:
                info_dataframe(cfg, _extra or None).to_excel(
                    xw, sheet_name=tr('Info'), index=False)
                annual_summary_frame(result['kpi'], cfg).T.reset_index()\
                    .rename(columns={'index': tr('Item'), 0: tr('Nilai')})\
                    .to_excel(xw, sheet_name=tr('Ringkasan Tahunan'),
                              index=False)
                # SELURUH konfigurasi dispatch energy (Dispatch Strategy)
                dispatch_config_frame(cfg).to_excel(
                    xw, sheet_name=tr('Dispatch Config'), index=False)
            kpi.to_excel(xw, sheet_name='KPI', index=False)
            if fin is not None:
                fin.to_excel(xw, sheet_name=tr('Finance'), index=False)
            df.to_excel(xw, sheet_name='TimeSeries', index=False)


def export_optimization(path: str, res: dict, top_n: int | None = None,
                        cfg: dict | None = None):
    order = res['rank_order']
    if top_n:
        order = order[:top_n]
    cols = ['kwp', 'kw_inv', 'dc_ac_ratio', 'kwh_bess', 'pcs_kw',
            # nilai parameter Advanced yg dioptimasi (hanya bila di-sweep)
            'opt_smoothing_window', 'opt_firming_kw', 'opt_firm_met_pct',
            'opt_max_charge', 'opt_max_discharge',
            'opt_reserve_frac', 'opt_reserve_kw',
            'bess_autonomy_h', 'feasible', 'lcoe', 'npv', 'capex',
            'payback_years', 'irr', 'renewable_fraction', 'pvbs_supply_ratio',
            'annual_pv_generation_kwh', 'diesel_energy_kwh',
            'diesel_fuel_l', 'diesel_reduction_vs_only', 'grid_import_kwh',
            'pv_excess_ratio', 'unserved_kwh', 'battery_cycles']
    # Samakan dgn tabel di layar: DC/AC selalu dihapus; PCS dihapus utk
    # Smoothing/Firming (diganti Max BESS Charge/Discharge yg dioptimasi).
    drop = {'dc_ac_ratio'}
    if 'opt_max_charge' in res:
        drop.add('pcs_kw')
    data = {c: snap_zero(np.asarray(res[c])[order])
            for c in cols if c in res and c not in drop}
    df = pd.DataFrame(data)
    df.insert(0, tr('Opsi'), np.arange(1, len(df) + 1))
    if path.lower().endswith('.csv'):
        df.to_csv(path, index=False)
    else:
        with pd.ExcelWriter(path, engine='openpyxl') as xw:
            if cfg is not None:
                extra = [('Objective', ' > '.join(
                    res.get('objectives_used', []))),
                    ('Kandidat dievaluasi', len(res['kwp'])),
                    ('Feasible', int(np.sum(res['feasible'])))]
                info_dataframe(cfg, extra).to_excel(
                    xw, sheet_name=tr('Info'), index=False)
            df.to_excel(xw, sheet_name=tr('Hasil Optimasi'), index=False)
    return df


def export_multi_year(path: str, res: dict, cfg: dict | None = None,
                      hourly: dict | None = None):
    """`hourly`: {tahun: (datetimes, series)} — bila diberikan, tiap
    tahun mendapat sheet tabel per jam tersendiri."""
    """Tulis hasil simulasi multi-year (per tahun) ke Excel."""
    import pandas as pd
    k, f = res['kpi'], res['finance']
    df = pd.DataFrame({
        tr('Tahun'): res['years'],
        tr('PV Efektif (kWp)'): res['pv_kwp_eff'],
        tr('BESS SOH'): np.asarray(res.get(
            'bess_soh', np.ones(len(res['years'])))),
        tr('BESS Efektif (kWh)'): res['bess_kwh_eff'],
        tr('Ganti BESS (Rp)'): f.get('repl_y', np.zeros(len(res['years']))),
        tr('PV Generation (kWh)'): k['annual_pv_generation_kwh'],
        tr('Renewable Fraction'): k['renewable_fraction'],
        'BESS Discharge (kWh)': k['annual_battery_discharge_kwh'],
        tr('Diesel Fuel (L)'): k['diesel_fuel_l'],
        tr('Grid Import (kWh)'): k['grid_import_kwh'],
        tr('Grid Export (kWh)'): k.get('grid_export_kwh', 0.0),
        tr('Unused/Curtailment (kWh)'): k['pv_excess_kwh'],
        tr('Unserved (kWh)'): k['unserved_kwh'],
        tr('OPEX (Rp)'): f['opex_y'],
        tr('Baseline (Rp)'): f['baseline_y'],
        tr('Savings (Rp)'): f['savings_y'],
        tr('Cashflow Kumulatif (Rp)'): f['cum_cashflow'],
    })
    summ = pd.DataFrame({
        tr('Metrik'): [tr('CAPEX'), tr('NPV'), tr('IRR'), tr('ROI'), tr('Payback (th)'),
                   'LCOE (Rp/kWh)', tr('Jumlah Penggantian BESS'),
                   tr('Total Biaya Penggantian BESS (Rp)')],
        tr('Nilai'): [f['capex'], f['npv'], f['irr'], f['roi'],
                  f['payback_years'], f['lcoe'],
                  f.get('bess_replacements', 0),
                  f.get('bess_replacement_total', 0.0)],
    })
    with pd.ExcelWriter(path, engine='openpyxl') as xw:
        if cfg is not None:
            extra = [(tr('Project Lifetime (th)'), cfg.get('project_lifetime_y', '')),
                     (tr('Discount Rate'), cfg.get('discount_rate', '')),
                     (tr('Inflation'), cfg.get('inflation', '')),
                     ('PV Degradation / th', cfg.get('pv_degradation', '')),
                     (('BESS SOH Curve' if soh_curve_active(cfg) else
                       'BESS Degradation / th'),
                      ('; '.join(f'{y:g}: {v:.4f}' for y, v in
                                 parse_soh_curve(cfg.get('bess_soh_curve')))
                       if soh_curve_active(cfg)
                       else cfg.get('bess_degradation', ''))),
                     (tr('BESS Lifetime (th)'), cfg.get('bess_lifetime_y', '')),
                     (tr('BESS SOH Threshold'), cfg.get('bess_soh_threshold', ''))]
            info_dataframe(cfg, extra).to_excel(xw, sheet_name=tr('Info'),
                                                index=False)
        df.to_excel(xw, sheet_name=tr('Per Tahun'), index=False)
        if cfg is not None:
            annual_summary_frame(res['kpi'], cfg, years=res['years']).to_excel(
                xw, sheet_name=tr('Ringkasan Tahunan'), index=False)
        for yr, (dts_y, ser_y) in sorted((hourly or {}).items()):
            series_dataframe(ser_y, dts_y, cfg).to_excel(
                xw, sheet_name=f'{tr("Tahun")} {yr}'[:31], index=False)
        summ.to_excel(xw, sheet_name=tr('Ringkasan Lifetime'), index=False)


# --------------------------------------------------------------------------
BATCH_COLS = [
    ('kwp', 'PV (kWp)', 2), ('kw_inv', 'INV (kW)', 2),
    ('dc_ac_ratio', 'DC/AC', 2), ('kwh_bess', 'BESS (kWh)', 0),
    ('pcs_kw', 'PCS (kW)', 2), ('bess_autonomy_h', 'BESS Autonomy (jam)', 2),
    ('lcoe', 'LCOE (Rp/kWh)', 0), ('npv', 'NPV (Rp)', 0),
    ('capex', 'CAPEX (Rp)', 0), ('payback_years', 'Payback (th)', 2),
    ('renewable_fraction', 'Renewable Fraction', 6),
    ('annual_pv_generation_kwh', 'PV Generation (kWh/th)', 0),
    ('diesel_energy_kwh', 'Diesel Energy (kWh/th)', 0),
    ('diesel_fuel_l', 'Diesel Fuel (L/th)', 0),
    ('grid_import_kwh', 'Grid Import (kWh/th)', 0),
    ('pv_excess_ratio', 'PV Curtailment', 6),
    ('unserved_kwh', 'Unserved (kWh/th)', 1),
]


def batch_summary_frame(rows: list) -> pd.DataFrame:
    """Satu baris per site: sizing terbaik & KPI-nya."""
    data = []
    for r in rows:
        res, best = r['res'], r['res']['rank_order'][0]
        one = {tr('Site'): r['site'],
               tr('Beban (kWh/th)'): snap_zero(float(
                   np.asarray(res['annual_load_kwh']).reshape(-1)[best]))
               if 'annual_load_kwh' in res else ''}
        for key, label, _dec in BATCH_COLS:
            if key not in res:
                continue
            v = float(np.asarray(res[key]).reshape(-1)[best])
            one[tr(label)] = snap_zero(v)
        one[tr('Objective')] = ' > '.join(res.get('objectives_used', []))
        one[tr('Kandidat dievaluasi')] = int(len(np.asarray(res['kwp'])))
        one[tr('Feasible')] = int(np.sum(res['feasible']))
        data.append(one)
    return pd.DataFrame(data)


def export_batch_optimization(path: str, rows: list, cfg: dict | None = None,
                              top_n: int = 50):
    """Tulis hasil optimasi banyak site: satu ringkasan + sheet per site."""
    summ = batch_summary_frame(rows)
    if path.lower().endswith('.csv'):
        summ.to_csv(path, index=False)
        return summ
    with pd.ExcelWriter(path, engine='openpyxl') as xw:
        if cfg is not None:
            extra = [(tr('Jumlah Site'), len(rows)),
                     (tr('Site'), ', '.join(r['site'] for r in rows))]
            info_dataframe(cfg, extra).to_excel(xw, sheet_name=tr('Info'),
                                                index=False)
        summ.to_excel(xw, sheet_name=tr('Ringkasan Site'), index=False)
        used = set()
        for r in rows:
            name = _slug(r['site'], 28) or 'Site'
            sheet, i = name[:31], 2
            while sheet in used:
                sheet = f'{name[:28]}_{i}'[:31]
                i += 1
            used.add(sheet)
            order = r['res']['rank_order'][:top_n]
            cols = ['kwp', 'kw_inv', 'dc_ac_ratio', 'kwh_bess', 'pcs_kw',
                    'bess_autonomy_h', 'feasible', 'lcoe', 'npv', 'capex',
                    'payback_years', 'renewable_fraction',
                    'annual_pv_generation_kwh', 'diesel_energy_kwh',
                    'diesel_fuel_l', 'grid_import_kwh', 'pv_excess_ratio',
                    'unserved_kwh']
            df = pd.DataFrame({c: snap_zero(np.asarray(r['res'][c])[order])
                               for c in cols if c in r['res']})
            df.insert(0, tr('Opsi'), np.arange(1, len(df) + 1))
            df.to_excel(xw, sheet_name=sheet, index=False)
    return summ


def batch_multi_year_summary_frame(rows: list) -> pd.DataFrame:
    """Ringkasan lifetime per site untuk batch multi-year multi-site."""
    out = []
    for r in rows:
        res = r['res']
        k, f = res['kpi'], res['finance']
        sz = r.get('sizing', {})

        def _y1(key):
            return float(np.asarray(k[key]).reshape(-1)[0])

        out.append({
            tr('Site'): r['site'],
            tr('Custom Sizing'): tr('Ya') if r.get('custom') else tr('Tidak'),
            tr('PV (kWp)'): snap_zero(float(sz.get('pv_kwp', float(
                np.asarray(res['pv_kwp_eff']).reshape(-1)[0])))),
            tr('INV (kW)'): snap_zero(float(sz.get('kw_inv', 0.0))),
            tr('BESS (kWh)'): snap_zero(float(sz.get('bess_kwh', float(
                np.asarray(res['bess_kwh_eff']).reshape(-1)[0])))),
            tr('PCS (kW)'): snap_zero(float(sz.get('pcs_kw', 0.0))),
            tr('Self Cons. (kWh/h)'): snap_zero(float(sz.get('self_cons_kw', 0.0) or 0.0)),
            tr('Lifetime (th)'): int(len(res['years'])),
            tr('LCOE Lifetime (Rp/kWh)'): snap_zero(float(f['lcoe'])),
            tr('NPV (Rp)'): snap_zero(float(f['npv'])),
            tr('IRR (%)'): snap_zero(float(f['irr']) * 100.0),
            tr('ROI (%)'): snap_zero(float(f['roi']) * 100.0),
            tr('Payback (th)'): snap_zero(float(f['payback_years'])),
            tr('CAPEX (Rp)'): snap_zero(float(f['capex'])),
            tr('Penggantian BESS'): int(f.get('bess_replacements', 0)),
            tr('RF Th-1 (%)'): snap_zero(_y1('renewable_fraction') * 100.0),
            tr('Beban Th-1 (kWh)'): snap_zero(_y1('annual_load_kwh')),
            tr('Diesel Th-1 (L)'): snap_zero(_y1('diesel_fuel_l')),
            tr('Grid Import Th-1 (kWh)'): snap_zero(_y1('grid_import_kwh')),
            tr('Unserved Th-1 (kWh)'): snap_zero(_y1('unserved_kwh')),
        })
    return pd.DataFrame(out)


def _my_year_frame(res: dict) -> pd.DataFrame:
    """Tabel per tahun (satu site) — kolom sama dgn tabel Multi-Year di GUI."""
    k, f = res['kpi'], res['finance']
    yrs = np.asarray(res['years'])
    soh = np.asarray(res.get('bess_soh', np.ones(len(yrs)))) * 100.0
    return pd.DataFrame({
        tr('Tahun'): yrs,
        tr('PV Efektif (kWp)'): snap_zero(np.asarray(res['pv_kwp_eff'])),
        tr('BESS SOH (%)'): snap_zero(soh),
        tr('BESS Efektif (kWh)'): snap_zero(np.asarray(res['bess_kwh_eff'])),
        tr('Battery Discharge (kWh)'): snap_zero(
            np.asarray(k['annual_battery_discharge_kwh'])),
        tr('Battery Throughput (kWh)'): snap_zero(
            np.asarray(k['battery_throughput_kwh'])),
        tr('PV Gen (kWh)'): snap_zero(np.asarray(k['annual_pv_generation_kwh'])),
        tr('RF (%)'): snap_zero(np.asarray(k['renewable_fraction']) * 100.0),
        tr('Fuel (L)'): snap_zero(np.asarray(k['diesel_fuel_l'])),
        tr('Grid Imp (kWh)'): snap_zero(np.asarray(k['grid_import_kwh'])),
        tr('Unused (kWh)'): snap_zero(np.asarray(k['pv_excess_kwh'])),
        tr('Unserved (kWh)'): snap_zero(np.asarray(k['unserved_kwh'])),
        tr('OPEX (Rp)'): snap_zero(np.asarray(f['opex_y'])),
        tr('Savings (Rp)'): snap_zero(np.asarray(f['savings_y'])),
        tr('Kumulatif (Rp)'): snap_zero(np.asarray(f['cum_cashflow'])),
    })


def export_batch_multi_year(path: str, rows: list, cfg: dict | None = None):
    """Tulis hasil multi-year banyak site: ringkasan lifetime + sheet per site
    (tabel per tahun)."""
    summ = batch_multi_year_summary_frame(rows)
    if path.lower().endswith('.csv'):
        summ.to_csv(path, index=False)
        return summ
    with pd.ExcelWriter(path, engine='openpyxl') as xw:
        if cfg is not None:
            extra = [(tr('Jumlah Site'), len(rows)),
                     (tr('Site'), ', '.join(r['site'] for r in rows))]
            info_dataframe(cfg, extra).to_excel(xw, sheet_name=tr('Info'),
                                                index=False)
        summ.to_excel(xw, sheet_name=tr('Ringkasan Site'), index=False)
        used = set()
        for r in rows:
            name = _slug(r['site'], 28) or 'Site'
            sheet, i = name[:31], 2
            while sheet in used:
                sheet = f'{name[:28]}_{i}'[:31]
                i += 1
            used.add(sheet)
            _my_year_frame(r['res']).to_excel(xw, sheet_name=sheet, index=False)
    return summ
