"""Simulasi multi-year sepanjang project lifetime.

Setiap tahun disimulasikan penuh 8760 jam dengan parameter yang terdegradasi:
  PV      : kWp_efektif(y) = kWp × (1 − pv_degradation)^(y−1)
  BESS    : E_efektif(y)  = E   × (1 − bess_degradation)^(y−1)
            (limit daya charge/discharge ikut faktor yang sama)
Seluruh tahun dihitung SEKALIGUS memakai sumbu batch engine dispatch yang
tervektorisasi, sehingga 20–30 tahun selesai dalam hitungan detik.

Finansial multi-year: harga energi (solar, tarif grid, tarif ekspor) naik
mengikuti inflasi; OPEX & baseline dihitung dari energi hasil simulasi tahun
tersebut; NPV/IRR/LCOE/payback memakai discount rate.
"""
from __future__ import annotations
import numpy as np

from .dispatch import simulate, _system_vals
from .kpi import technical_kpis, DIESEL_LHV_KWH_PER_L
from .finance import capex, irr, _npv, capex_scoped, lcoe_energy_scoped, _FINANCE_SCOPES
from .numeric import snap_dict, snap_zero
from .simulation import SimulationEngine
from ..config import intervals as ivals



def bess_soh_schedule(cfg: dict, years: int):
    """Jejak SOH BESS per tahun beserta tahun penggantian.

    SOH terdegradasi tiap tahun sebesar bess_degradation — ATAU mengikuti
    kurva SOH impor (bess_soh_source = 'SOH Curve (Excel)'). BESS diganti baru
    (SOH kembali 100%) bila:
      * umur pakai mencapai bess_lifetime_y, ATAU
      * SOH turun di bawah bess_soh_threshold.
    Tahun-1 memakai unit baru (SOH 100%) dan TIDAK dihitung sebagai
    penggantian karena sudah termasuk CAPEX awal.

    Kembalikan (soh (Y,), replaced (Y,) bool, age (Y,)).
    """
    deg = float(cfg.get('bess_degradation', 0.0))
    # Model SOH: 'SOH Curve (Excel)' → SOH(umur) dari tabel impor pengguna
    # (umur 0 = unit baru; direset tiap penggantian); selain itu degradasi
    # tahunan konstan (1 − deg)^umur (perilaku lama, byte-identik).
    from ..config.parameters import soh_curve_active, soh_from_curve
    curve = cfg.get('bess_soh_curve') if soh_curve_active(cfg) else None
    life = int(cfg.get('bess_lifetime_y', 0) or 0)
    thr = float(cfg.get('bess_soh_threshold', 0.0) or 0.0)
    soh = np.ones(years)
    replaced = np.zeros(years, dtype=bool)
    ages = np.zeros(years, dtype=int)
    age = 0                       # umur unit terpasang (tahun penuh)
    cur = 1.0
    for y in range(years):
        if y > 0:
            age += 1
            cur = (soh_from_curve(curve, age) if curve
                   else (1.0 - deg) ** age)
            need = ((life > 0 and age >= life)
                    or (thr > 0.0 and cur < thr))
            if need and float(cfg.get('bess_kwh', 0.0)) > 0:
                age = 0
                cur = 1.0
                replaced[y] = True
        soh[y] = cur
        ages[y] = age
    return soh, replaced, ages


def _my_dt_h(cfg: dict) -> float:
    """dt (jam) satu langkah Multi-Year = interval_dt_h('sim_interval').

    SAMA persis dgn Dashboard/Optimization/Results — Multi-Year TIDAK LAGI
    memaksa 1 jam. Untuk '1 hour' hasilnya 1.0 (jalur kanon utuh)."""
    return ivals.interval_dt_h(str(cfg.get('sim_interval', '1 hour')))


def _my_prepare(load, pv_norm, grid_status, cfg: dict, deg_status=None,
                datetimes=None):
    """Basis simulasi Multi-Year — IDENTIK dengan Dashboard (_SimWorker) pada
    JENDELA SIMULASI YANG SAMA: kembalikan (L, P, G, dt_h, n, D, ann).

    Jendela (titik mulai + durasi) diambil dari setelan proyek BERSAMA lewat
    `ivals.resolve_sim_window(cfg, ...)` — RUMUS & SUMBER yang SAMA persis
    dipakai header Dashboard. Jadi jika Dashboard disetel mis. "Start: Jul,
    Durasi: 1 bulan", Multi-Year tahun-1 juga menyimulasikan Juli (1 bulan)
    lalu diekstrapolasi ke setahun -> tahun-1 Multi-Year == Dashboard, apa pun
    setelan Start/Durasi (permintaan pengguna). Keduanya memakai
    `build_sim_arrays` + `annualization_factor_h` yang sama.

    * '1 hour' + jendela PENUH (start=0, durasi=setahun): data per-jam APA
      ADANYA (tak diresample), dt=1, ann=1 -> byte-identik jalur lama (paritas
      Excel/canon). Ini setelan baku & jalur yg divalidasi selftest/canon.
    * '1 hour' + jendela SEBAGIAN (mis. Juli/1 bulan): dijendela via
      build_sim_arrays lalu diekstrapolasi (ann>1) -- SAMA dgn Dashboard.
    * '30 minute' (jendela setahun penuh): dt=0.5, ann=1.
    * Interval sub-tahun ('1 minute' dst.): jendela terbatas interval +
      ekstrapolasi (ann>1) -- PERSIS Dashboard.
    """
    lab = str(cfg.get('sim_interval', '1 hour'))
    load = np.asarray(load, float)
    pv_norm = np.asarray(pv_norm, float)
    grid_status = np.asarray(grid_status, float)
    n_src = int(load.size)
    start_h, win_h = ivals.resolve_sim_window(cfg, n_src, datetimes)
    # Jalur cepat byte-identik: '1 hour', mulai dari 0, jendela mencakup SELURUH
    # data -> data apa adanya (termasuk 8784 kabisat), dt=1, ann=1.
    if lab == '1 hour' and start_h == 0 and win_h >= n_src:
        return (load, pv_norm, grid_status, 1.0, n_src, deg_status, 1.0)
    L, P, G, dt_h, n, D = ivals.build_sim_arrays(
        load, pv_norm, grid_status, datetimes, lab,
        start_h=start_h, window_h=win_h, deg=deg_status)
    ann = ivals.annualization_factor_h(max(1e-9, n * dt_h))
    return L, P, G, float(dt_h), int(n), D, float(ann)


def _my_scale_acc(acc: dict, dt, ann) -> dict:
    """Skala akumulator PERSIS spt SimulationEngine.run() (jalur Dashboard/
    Optimization/Results, lihat simulation.py): akumulator ENERGI ×ann,
    akumulator per-LANGKAH ×dt×ann. dt=1 & ann=1 (mis. '1 hour'/'30 minute'
    setahun penuh) -> TAK berubah (byte-identik). Ini yang menjamin KPI teknis
    tahun-1 Multi-Year == Dashboard utk interval apa pun."""
    dt = float(np.asarray(dt).reshape(-1)[0])
    ann = float(ann)
    if ann == 1.0 and dt == 1.0:
        return acc
    out = dict(acc)
    for k in SimulationEngine._ENERGY_ACC:
        if k in out:
            out[k] = np.asarray(out[k], float) * ann
    for k in SimulationEngine._STEP_ACC:
        if k in out:
            out[k] = np.asarray(out[k], float) * dt * ann
    return out


def _year_params(cfg: dict, years: int) -> dict:
    """Parameter dispatch per tahun untuk simulasi multi-year.

    Dibangun dari to_system_params(cfg) lalu _system_vals(sp) — SUMBER
    KONFIGURASI YANG SAMA PERSIS dengan jalur single-year (Dashboard → Run
    Simulation). Hanya kapasitas yang terdegradasi (PV, BESS, dan limit
    charge/discharge BESS) yang diberi faktor per tahun; seluruh opsi dispatch
    lain (load priority + split, charge priority, strict, semua interlock,
    DEG-split, izin charging, dsb.) diwarisi apa adanya. Dengan begitu formula
    dispatch multi-year DIJAMIN identik dengan single-year.

    Kembalikan (vals_dict, f_b) — nilai skalar akan di-broadcast otomatis oleh
    engine ke sumbu tahun; hanya 4 kapasitas berikut yang menjadi array (Y,).
    """
    from ..config.parameters import to_system_params
    f_pv = (1.0 - float(cfg['pv_degradation'])) ** np.arange(years)
    f_b, _repl, _age = bess_soh_schedule(cfg, years)   # SOH tiap tahun
    sp = to_system_params(cfg)
    v = _system_vals(sp)                               # konfigurasi kanonik
    # dt mengikuti 'sim_interval' bila jendelanya setahun penuh (1 hour/30
    # minute) -- selaras Dashboard/Optimization/Results (lihat _my_dt_h).
    # Interval lebih halus (jendela < 1 tahun) TETAP basis 1 jam.
    v['dt'] = _my_dt_h(cfg)
    # kapasitas terdegradasi per tahun (sisa field tetap skalar → broadcast)
    v['pv_kwp'] = np.asarray(sp.pv_kwp, float) * f_pv
    v['bess'] = np.asarray(sp.bess_kwh, float) * f_b
    v['max_chg'] = np.asarray(sp.max_charge_kw, float) * f_b
    v['max_dhg'] = np.asarray(sp.max_discharge_kw, float) * f_b
    return v, f_b


def run_lifetime(load, pv_norm, grid_status, cfg: dict,
                 deg_status=None, datetimes=None, progress=None) -> dict:
    """Kembalikan dict: years (1..Y), kpi{key: array (Y,)},
    finance{per_year & agregat lifetime}.

    deg_status : (T,) opsional, dari kolom import "DEG Status" (halaman
                 Data) — sama persis tiap tahun (bukan sumbu Y), disiarkan
                 oleh engine ke setiap tahun dalam sumbu batch. None (tak
                 diimpor) -> mekanisme dorman, byte-identik perilaku lama
                 (lihat app.engine.dispatch.simulate).
    datetimes  : (T,) opsional — timestamp asli profil (halaman Data),
                 dipakai HANYA utk deteksi interval sumber saat 'sim_interval'
                 (Parameters) bukan '1 hour' (lihat _my_prepare).
                 None -> deteksi jatuh ke heuristik jumlah baris (cukup andal
                 utk data per-jam biasa, 8760/8784 baris).
    progress   : callback opsional progress(done, total) — diteruskan ke
                 simulate() (per langkah waktu, semua tahun sekaligus dalam
                 sumbu batch). Dipakai halaman Multi-Year utk menampilkan %.
    """
    years = int(cfg['project_lifetime_y'])
    params, f_b = _year_params(cfg, years)
    deg_status = (np.asarray(deg_status, float)
                 if deg_status is not None else None)
    # Basis simulasi IDENTIK Dashboard (jendela penuh interval, start=0),
    # termasuk dt & faktor annualisasi -> tahun-1 == Dashboard (lihat
    # _my_prepare/_my_scale_acc).
    L, P, G, dt_h, n, D, ann = _my_prepare(
        load, pv_norm, grid_status, cfg, deg_status=deg_status,
        datetimes=datetimes)
    params['dt'] = dt_h
    raw = simulate(L, P, G, params, n_combos=years, deg_status=D,
                   progress=progress)
    acc = _my_scale_acc(raw['acc'], dt_h, ann)
    from ..config.parameters import deg_fuel_rates
    kpi = technical_kpis(acc, dict(
        bess_kwh=params['bess'], soc_min=cfg['soc_min'],
        soc_max=cfg['soc_max'], deg_fuel_rate=deg_fuel_rates(cfg)))
    kpi = {k: np.asarray(v, float).reshape(-1) if np.size(v) == years
           else np.full(years, float(np.asarray(v).reshape(-1)[0]))
           for k, v in kpi.items()}
    soh, replaced, ages = bess_soh_schedule(cfg, years)
    fin = _finance_lifetime(kpi, cfg, replaced=replaced)
    return dict(years=np.arange(1, years + 1), kpi=kpi, finance=fin,
                pv_kwp_eff=np.asarray(params['pv_kwp'], float),
                bess_kwh_eff=np.asarray(params['bess'], float),
                bess_soh=soh, bess_replaced=replaced, bess_age=ages)


def _finance_lifetime(kpi: dict, cfg: dict, replaced=None) -> dict:
    years = int(cfg['project_lifetime_y'])
    r = float(cfg['discount_rate'])
    infl = float(cfg['inflation'])
    esc = (1.0 + infl) ** np.arange(years)          # tahun-1 = 1.0
    disc = (1.0 + r) ** np.arange(1, years + 1)

    n = int(str(cfg.get('deg_count', '1')))
    kw_deg = sum([cfg['deg1_kw'], cfg['deg2_kw'], cfg['deg3_kw']][:n])
    cap = float(np.asarray(capex(cfg['pv_kwp'], cfg['pv_inv_kw'],
                                 cfg['bess_kwh'], kw_deg, cfg)).reshape(-1)[0])

    fuel = kpi['diesel_fuel_l']
    grid = kpi['grid_import_kwh']
    exp = kpi.get('grid_export_kwh', np.zeros(years))
    loadk = kpi['annual_load_kwh']
    served = loadk - kpi['unserved_kwh']

    # Biaya grid: ToU (puncak/luar-puncak) bila Arbitrage aktif & tarif
    # off-peak diset; selain itu tarif flat (jalur lama, tak berubah).
    gpk = kpi.get('grid_import_peak_kwh')
    gof = kpi.get('grid_import_offpeak_kwh')
    _to = cfg.get('tariff_offpeak_per_kwh')
    if (gpk is not None and gof is not None and _to is not None
            and float(np.sum(gpk) + np.sum(gof)) > 0):
        grid_cost = (np.asarray(gpk, float) * cfg['grid_tariff_per_kwh']
                     + np.asarray(gof, float) * float(_to))
    else:
        grid_cost = grid * cfg['grid_tariff_per_kwh']
    # SEMUA komponen OPEX (termasuk O&M dari CAPEX) eskalasi inflasi tiap
    # tahun (esc) -- SELARAS dgn financial_kpis() (finance.py, jalur Dashboard/
    # Optimization/Results): op_y = opex1 * esc, di mana opex1 = annual_opex()
    # MENCAKUP om_fraction*cap. Sebelumnya om_fraction*cap TAK dikalikan esc
    # di sini (beda dgn fuel/grid/ekspor tepat di sebelahnya) -- inkonsistensi
    # yg membuat LCOE/NPV lifetime Multi-Year menyimpang dari Dashboard walau
    # KPI teknis tahun-1 sudah identik. BUKAN pencacahan ganda inflasi harga:
    # fuel/grid di atas memakai LITER/kWh HASIL SIMULASI aktual tahun itu
    # (sudah mencerminkan degradasi kapasitas riil) dikalikan HARGA yg
    # dieskalasi -- persis pola yg sama berlaku utk O&M (biaya jasa/tenaga
    # kerja O&M turut naik mengikuti inflasi, bukan tetap flat sepanjang umur
    # proyek).
    opex_y = (cfg['om_fraction'] * cap * esc
              + fuel * cfg['diesel_price_per_l'] * esc
              + grid_cost * esc
              - exp * cfg.get('export_tariff_per_kwh', 0.0) * esc)

    # --- Financial Analysis scope (Parameters > Finance) ----------------
    # SAMA spt Results/Optimization (lihat finance.py financial_kpis()):
    # HANYA memengaruhi CAPEX/OPEX/LCOE yg ditampilkan (kartu & tabel per-
    # tahun) lewat cap_lcoe/opex_y_disp di bawah. `cap`/`opex_y` whole-
    # system DI ATAS TAK DISENTUH — dipakai apa adanya utk save_y/flows/
    # NPV/IRR/ROI/Payback/cum_cashflow, sehingga itu semua TETAP selalu
    # whole-system persis spt sebelum fitur ini ada, tanpa terkecuali.
    scope = str(cfg.get('finance_scope', 'PV-BESS-DEG') or 'PV-BESS-DEG')
    if scope not in _FINANCE_SCOPES:
        scope = 'PV-BESS-DEG'
    cap_lcoe = float(np.asarray(capex_scoped(
        cfg['pv_kwp'], cfg['pv_inv_kw'], cfg['bess_kwh'], kw_deg, cfg,
        scope)).reshape(-1)[0])
    if scope == 'PV-BESS':
        # OPEX PV-BESS = HANYA O&M dari CAPEX PV-BESS (tanpa BBM/grid/ekspor,
        # tak terkait teknologi ini) — selaras annual_opex_scoped() single-year.
        # O&M ikut eskalasi inflasi (esc) — lihat catatan di opex_y whole-
        # system di atas.
        opex_y_disp = cfg['om_fraction'] * cap_lcoe * esc
    elif scope == 'DEG':
        # OPEX DEG = O&M dari CAPEX DEG + BBM + grid − ekspor (spt formula
        # penuh di atas, hanya basis CAPEX-nya yg jadi CAPEX DEG saja).
        opex_y_disp = (cfg['om_fraction'] * cap_lcoe * esc
                       + fuel * cfg['diesel_price_per_l'] * esc
                       + grid_cost * esc
                       - exp * cfg.get('export_tariff_per_kwh', 0.0) * esc)
    else:
        opex_y_disp = opex_y   # 'PV-BESS-DEG' (baku) — identik whole-system

    from ..config.parameters import deg_fuel_rate_eff
    rate_eff = deg_fuel_rate_eff(cfg)      # L/kWh; Fuel = laju × energi diesel
    if cfg.get('baseline_mode', 'diesel_only') == 'diesel_only':
        base_energy_cost = (loadk * rate_eff * cfg['diesel_price_per_l'])
    else:
        gridpart = np.minimum(loadk, grid)
        base_energy_cost = (gridpart * cfg['grid_tariff_per_kwh']
                            + (loadk - gridpart) * rate_eff
                            * cfg['diesel_price_per_l'])
    base_y = base_energy_cost * esc
    # biaya penggantian BESS pada tahun terjadinya (mengikuti inflasi)
    bess_capex_unit = (float(cfg.get('bess_kwh', 0.0))
                       * float(cfg.get('bess_cost_per_kwh', 0.0)))
    repl_y = np.zeros(years)
    if replaced is not None:
        repl_y = np.asarray(replaced, bool) * bess_capex_unit * esc
    # Penggantian BESS adalah aset PV-BESS -> ikut LCOE pada scope 'PV-BESS'
    # & 'PV-BESS-DEG' (baku), DIKECUALIKAN pada scope 'DEG' (bukan aset DEG).
    # save_y/flows/NPV/IRR/ROI/Payback di bawah TETAP pakai repl_y PENUH
    # (whole-system) — tak terpengaruh scope, sama spt opex_y di atas.
    repl_y_disp = np.zeros(years) if scope == 'DEG' else repl_y
    save_y = base_y - opex_y - repl_y

    flows = np.concatenate(([-cap], save_y))
    cum = np.cumsum(flows)
    npv = float(_npv(r, flows))
    ir = irr(flows)
    payback = np.nan
    pos = np.where(cum >= 0)[0]
    if pos.size:
        y = int(pos[0])
        payback = 0.0 if y == 0 else (y - 1) + (-cum[y - 1]) / max(flows[y], 1e-9)
    roi = (save_y.sum() - cap) / max(cap, 1e-9)
    energy_lcoe = np.asarray(lcoe_energy_scoped(kpi, scope), float).reshape(-1)
    if energy_lcoe.size == 1 and served.size > 1:
        energy_lcoe = np.full(served.size, float(energy_lcoe[0]))
    lcoe = ((cap_lcoe + ((opex_y_disp + repl_y_disp) / disc).sum())
            / max((energy_lcoe / disc).sum(), 1e-9))
    return snap_dict(dict(capex=cap_lcoe, opex_y=opex_y_disp, repl_y=repl_y,
                          bess_replacements=int(np.sum(repl_y > 0)),
                          bess_replacement_total=float(repl_y.sum()),
                          baseline_y=base_y, savings_y=save_y,
                cum_cashflow=cum[1:], flows=flows, npv=npv,
                irr=float(np.asarray(ir).reshape(-1)[0]),
                roi=roi, payback_years=payback, lcoe=lcoe))


def year_hourly_series(load, pv_norm, grid_status, cfg: dict, year: int,
                       deg_status=None, datetimes=None) -> dict:
    """Deret waktu untuk tahun ke-`year` (1-indeks) pada simulasi multi-year
    (pada basis 'sim_interval' — SAMA dgn Dashboard, lihat _my_prepare):
    memakai kapasitas PV & BESS yang sudah terdegradasi/ter-reset sesuai
    jadwal SOH.

    deg_status : (T,) opsional — lihat run_lifetime(). None -> dorman.
    datetimes  : (T,) opsional — lihat run_lifetime().
    """
    years = int(cfg['project_lifetime_y'])
    y = int(np.clip(year, 1, years)) - 1
    params, _ = _year_params(cfg, years)
    one = {}
    for k, v in params.items():
        arr = np.asarray(v)
        one[k] = float(arr.reshape(-1)[y]) if arr.size == years else v
    deg_status = (np.asarray(deg_status, float)
                 if deg_status is not None else None)
    L, P, G, dt_h, n, D, _ann = _my_prepare(
        load, pv_norm, grid_status, cfg, deg_status=deg_status,
        datetimes=datetimes)
    one['dt'] = dt_h
    raw = simulate(L, P, G, one, n_combos=1, record=True, deg_status=D)
    return raw['series']


def year_series_datetimes(cfg: dict, n_rows: int, start='2025-01-01'):
    """DatetimeIndex sepanjang deret year_hourly_series (basis 'sim_interval',
    lihat _my_prepare/make_datetimes) — dipakai halaman/ekspor Multi-Year utk
    memberi timestamp pd deret per-tahun. n_rows = panjang deret hasil."""
    lab = str(cfg.get('sim_interval', '1 hour'))
    try:
        return ivals.make_datetimes(lab, int(n_rows), start=start)
    except Exception:
        import pandas as pd
        return pd.date_range(start, periods=int(n_rows), freq='h')
