"""Modul finansial: CAPEX, OPEX, LCOE, cashflow, NPV, IRR, ROI, payback.

Model biaya sederhana namun transparan (semua unit cost dapat diedit):
  CAPEX = pv_cost*kWp + inv_cost*kW_inv + bess_cost*kWh + deg_cost*kW_deg + fixed
  OPEX/thn = om_frac*CAPEX + fuel_l*harga_solar + grid_import*tarif
  Baseline = biaya operasi tanpa PV+BESS (diesel-only atau grid+diesel eksisting)
  Cashflow tahun ke-i = penghematan(i) dgn degradasi PV & inflasi harga energi
Semua fungsi menerima skalar atau array (N,).
"""
from __future__ import annotations
import numpy as np

from .numeric import snap_dict


def capex(kwp, kw_inv, kwh_bess, kw_deg, c) -> np.ndarray:
    return (np.asarray(kwp) * c['pv_cost_per_kwp']
            + np.asarray(kw_inv) * c['inverter_cost_per_kw']
            + np.asarray(kwh_bess) * c['bess_cost_per_kwh']
            + np.asarray(kw_deg) * c['deg_cost_per_kw']
            + np.asarray(kwp) * c.get('epc_cost_per_kwp', 0.0)   # EPC per kWp PV
            + c.get('accessories_cost', 0.0)                     # CAPEX tetap
            + c.get('logistic_cost', 0.0))                       # CAPEX tetap


_FINANCE_SCOPES = ('DEG', 'PV-BESS', 'PV-BESS-DEG')


def _capex_pv_bess_only(kwp, kw_inv, kwh_bess, c) -> np.ndarray:
    """Komponen CAPEX PV + Inverter + BESS SAJA (tanpa DEG, tanpa biaya
    tetap sistem — Accessories/Logistic selalu ditambahkan terpisah, lihat
    capex_scoped, sesuai keputusan produk: biaya tetap selalu diikutkan
    penuh apa pun scope-nya)."""
    return (np.asarray(kwp) * c['pv_cost_per_kwp']
            + np.asarray(kw_inv) * c['inverter_cost_per_kw']
            + np.asarray(kwh_bess) * c['bess_cost_per_kwh']
            + np.asarray(kwp) * c.get('epc_cost_per_kwp', 0.0))


def _capex_deg_only(kw_deg, c) -> np.ndarray:
    """Komponen CAPEX genset DIESEL saja (bagian "DEG" dari scope
    "DEG"/Grid gabungan — Grid sendiri tak punya CAPEX pada model ini)."""
    return np.asarray(kw_deg) * c['deg_cost_per_kw']


def capex_scoped(kwp, kw_inv, kwh_bess, kw_deg, c, scope: str) -> np.ndarray:
    """CAPEX menurut parameter "Financial Analysis" (Parameters > Finance).

    'PV-BESS-DEG' (baku) — SELURUH sistem, memanggil capex() APA ADANYA
    (bit-identik dgn perilaku sebelum fitur ini ada).
    'PV-BESS' — PV + Inverter + BESS saja, + biaya tetap sistem (Accessories
    + Logistic, SELALU diikutkan penuh apa pun scope-nya — keputusan produk).
    'DEG' — genset Diesel saja (bagian CAPEX; Grid tak punya CAPEX di model
    ini), + biaya tetap sistem.
    """
    if scope == 'PV-BESS':
        return (_capex_pv_bess_only(kwp, kw_inv, kwh_bess, c)
                + c.get('accessories_cost', 0.0) + c.get('logistic_cost', 0.0))
    if scope == 'DEG':
        return (_capex_deg_only(kw_deg, c)
                + c.get('accessories_cost', 0.0) + c.get('logistic_cost', 0.0))
    return capex(kwp, kw_inv, kwh_bess, kw_deg, c)   # 'PV-BESS-DEG' (baku)


def _grid_energy_cost(grid_kwh, c, peak_kwh=None, offpeak_kwh=None):
    """Biaya energi impor grid. Time-of-Use (ToU): bila energi puncak/luar-
    puncak tersedia (Arbitrage aktif) DAN tarif off-peak diset, impor jam
    puncak dikenai Grid Tariff & impor luar-puncak dikenai Off-Peak Tariff.
    Selain itu tarif flat (jalur lama, tak berubah)."""
    tp = c['grid_tariff_per_kwh']
    to = c.get('tariff_offpeak_per_kwh')
    if peak_kwh is not None and offpeak_kwh is not None and to is not None:
        pk = np.asarray(peak_kwh, float)
        of = np.asarray(offpeak_kwh, float)
        if float(np.sum(pk) + np.sum(of)) > 0:
            return pk * tp + of * float(to)
    return np.asarray(grid_kwh) * tp


def annual_opex(cap, fuel_l, grid_kwh, c, export_kwh=0.0,
                grid_peak_kwh=None, grid_offpeak_kwh=None):
    return (c['om_fraction'] * np.asarray(cap)
            + np.asarray(fuel_l) * c['diesel_price_per_l']
            + _grid_energy_cost(grid_kwh, c, grid_peak_kwh, grid_offpeak_kwh)
            - np.asarray(export_kwh) * c.get('export_tariff_per_kwh', 0.0))


def annual_opex_scoped(cap_scoped, fuel_l, grid_kwh, c, scope: str,
                       export_kwh=0.0, grid_peak_kwh=None,
                       grid_offpeak_kwh=None):
    """OPEX/tahun menurut "Financial Analysis" scope — `cap_scoped` HARUS
    berasal dari capex_scoped() dgn scope YANG SAMA (basis %O&M).

    'PV-BESS' — HANYA O&M (%CAPEX PV-BESS+tetap); bahan bakar/biaya grid/
    kredit ekspor semuanya transaksi DEG-Grid, tak relevan bagi subsistem
    PV-BESS sendiri.
    'DEG' & 'PV-BESS-DEG' (baku) — memanggil annual_opex() APA ADANYA (utk
    'PV-BESS-DEG' ini bit-identik dgn perilaku sebelum fitur ini ada, karena
    cap_scoped == capex() penuh); bedanya hanya basis %O&M yang dipakai
    (CAPEX DEG+tetap utk 'DEG', CAPEX PENUH utk 'PV-BESS-DEG')."""
    if scope == 'PV-BESS':
        return c['om_fraction'] * np.asarray(cap_scoped)
    return annual_opex(cap_scoped, fuel_l, grid_kwh, c, export_kwh,
                       grid_peak_kwh, grid_offpeak_kwh)


def _fuel_rate_eff(c) -> float:
    """Laju bahan bakar efektif (L/kWh) untuk baseline diesel agregat.
    Kompatibel-mundur: turunkan dari `deg_efficiency` bila laju tak tersedia."""
    r = c.get('deg_fuel_rate_eff')
    if r is not None:
        return float(r)
    try:
        eff = float(c.get('deg_efficiency', 0.33)) or 0.33
    except (TypeError, ValueError):
        eff = 0.33
    return 1.0 / (eff * 10.0)


def baseline_cost(load_kwh, grid_kwh_base, c):
    """Biaya energi tahunan bila TANPA PV+BESS.
    mode 'diesel_only'  : seluruh beban dari genset
    mode 'grid_diesel'  : impor grid seperti histori + sisa dari genset.
    Fuel (L) = laju (L/kWh) × energi diesel (kWh)."""
    load = np.asarray(load_kwh, float)
    rate = _fuel_rate_eff(c)
    if c.get('baseline_mode', 'diesel_only') == 'diesel_only':
        fuel = load * rate
        return fuel * c['diesel_price_per_l']
    gridpart = np.minimum(load, np.asarray(grid_kwh_base, float))
    fuel = (load - gridpart) * rate
    return gridpart * c['grid_tariff_per_kwh'] + fuel * c['diesel_price_per_l']


def lcoe_energy_scoped(kpi: dict, scope: str):
    """Energi (kWh) dasar LCOE menurut "Financial Analysis" scope.

    'PV-BESS-DEG' (baku) — beban terlayani TOTAL (annual_load − unserved),
    persis rumus lama (bit-identik).
    'PV-BESS' — HANYA energi beban yang benar2 dilayani via PV+BESS
    (kpi['served_pvbs_kwh'] — sama sumbernya dgn 'renewable_fraction' di
    kpi.py, jadi konsisten dgn definisi "PV-BESS" di tempat lain aplikasi).
    'DEG' — energi beban dilayani Grid + Diesel genset gabung
    (served_grid_kwh + diesel_energy_kwh — selaras label "DEG/Grid" yg
    dipakai di grafik EMS/Dashboard)."""
    if scope == 'PV-BESS':
        return np.asarray(kpi.get('served_pvbs_kwh', 0.0), float)
    if scope == 'DEG':
        return (np.asarray(kpi.get('served_grid_kwh', 0.0), float)
                + np.asarray(kpi.get('diesel_energy_kwh', 0.0), float))
    return (np.asarray(kpi['annual_load_kwh'], float)
            - np.asarray(kpi['unserved_kwh'], float))


def _npv(rate, flows):
    flows = np.asarray(flows, float)
    disc = (1.0 + rate) ** np.arange(flows.shape[-1])
    return (flows / disc).sum(axis=-1)


def irr(flows, lo=-0.95, hi=2.0, tol=1e-6, itmax=200):
    """IRR via bisection; NaN bila tidak konvergen. flows shape (...,Y+1)."""
    flows = np.atleast_2d(np.asarray(flows, float))
    out = np.full(flows.shape[0], np.nan)
    for i, f in enumerate(flows):
        a, b = lo, hi
        fa, fb = _npv(a, f), _npv(b, f)
        if np.sign(fa) == np.sign(fb):
            continue
        for _ in range(itmax):
            m = 0.5 * (a + b)
            fm = _npv(m, f)
            if abs(fm) < tol:
                break
            if np.sign(fm) == np.sign(fa):
                a, fa = m, fm
            else:
                b, fb = m, fm
        out[i] = 0.5 * (a + b)
    return out if out.size > 1 else float(out[0])


def financial_kpis(kpi: dict, sizes: dict, c: dict) -> dict:
    """kpi = hasil technical_kpis ; sizes = kwp,kw_inv,kwh_bess,kw_deg ;
    c = dict parameter biaya (lihat defaults.json grup finance).

    `c['finance_scope']` (Parameters > Finance > "Financial Analysis";
    baku 'PV-BESS-DEG') mempersempit KPI 'lcoe', 'capex' & 'opex_year1' yang
    DIKEMBALIKAN (dipakai halaman Results & Optimization Constraints) ke
    komponen biaya & energi teknologi terpilih SAJA — lihat capex_scoped/
    annual_opex_scoped/lcoe_energy_scoped. 'npv'/'irr'/'roi'/'payback_years'/
    'cashflow'/'baseline_cost_year1'/'savings_year1' TETAP dihitung dari
    SELURUH sistem (CAPEX & OPEX penuh) TERLEPAS dari scope — metrik2 ini
    mengukur keputusan investasi TOTAL (penghematan vs baseline tanpa
    PV+BESS), bukan biaya per-teknologi spt LCOE. Scope 'PV-BESS-DEG' (baku)
    bit-identik dgn perilaku sebelum fitur ini ada, di SEMUA KPI."""
    scope = str(c.get('finance_scope', 'PV-BESS-DEG') or 'PV-BESS-DEG')
    if scope not in _FINANCE_SCOPES:
        scope = 'PV-BESS-DEG'
    cap = capex(sizes['kwp'], sizes['kw_inv'], sizes['kwh_bess'], sizes['kw_deg'], c)
    opex1 = annual_opex(cap, kpi['diesel_fuel_l'], kpi['grid_import_kwh'], c,
                        export_kwh=kpi.get('grid_export_kwh', 0.0),
                        grid_peak_kwh=kpi.get('grid_import_peak_kwh'),
                        grid_offpeak_kwh=kpi.get('grid_import_offpeak_kwh'))
    base1 = baseline_cost(kpi['annual_load_kwh'], kpi['grid_import_kwh'], c)
    years = int(c['project_lifetime_y'])
    r = float(c['discount_rate'])
    infl = float(c['inflation'])
    pv_deg = float(c.get('pv_degradation', 0.0))

    # --- KPI ter-SCOPE ("Financial Analysis"): dipakai HANYA utk LCOE & KPI
    # 'capex'/'opex_year1' yang ditampilkan/dikembalikan — TERPISAH dari
    # `cap`/`opex1` whole-system di atas, yang tetap dipakai apa adanya utk
    # cashflow/NPV/IRR/ROI/Payback/baseline di bawah (tak terpengaruh scope).
    cap_lcoe = capex_scoped(sizes['kwp'], sizes['kw_inv'], sizes['kwh_bess'],
                            sizes['kw_deg'], c, scope)
    opex_lcoe1 = annual_opex_scoped(
        cap_lcoe, kpi['diesel_fuel_l'], kpi['grid_import_kwh'], c, scope,
        export_kwh=kpi.get('grid_export_kwh', 0.0),
        grid_peak_kwh=kpi.get('grid_import_peak_kwh'),
        grid_offpeak_kwh=kpi.get('grid_import_offpeak_kwh'))
    energy_lcoe_base = lcoe_energy_scoped(kpi, scope)

    N = int(np.size(cap))
    flows = np.zeros((N, years + 1))
    flows[:, 0] = -np.asarray(cap).reshape(-1)
    lcoe_cost = np.asarray(cap_lcoe, float).reshape(-1).copy()
    lcoe_energy = np.zeros(N)
    for y in range(1, years + 1):
        esc = (1.0 + infl) ** (y - 1)
        deg_f = (1.0 - pv_deg) ** (y - 1)
        # penghematan = baseline - opex ; energi & fuel PV-linked menurun sesuai degradasi
        op_y = np.asarray(opex1).reshape(-1) * esc
        base_y = np.asarray(base1).reshape(-1) * esc
        save_y = base_y - op_y
        flows[:, y] = save_y
        op_y_lcoe = np.asarray(opex_lcoe1).reshape(-1) * esc
        lcoe_cost += op_y_lcoe / (1.0 + r) ** y
        lcoe_energy += np.asarray(energy_lcoe_base).reshape(-1) * deg_f / (1.0 + r) ** y

    npv = _npv(r, flows)
    ir = irr(flows)
    cum = np.cumsum(flows, axis=1)
    payback = np.full(N, np.nan)
    for i in range(N):
        pos = np.where(cum[i] >= 0)[0]
        if pos.size:
            y = pos[0]
            if y == 0:
                payback[i] = 0.0
            else:
                prev = cum[i, y - 1]
                payback[i] = (y - 1) + (-prev) / max(flows[i, y], 1e-9)
    roi = (flows[:, 1:].sum(axis=1) - (-flows[:, 0])) / np.maximum(-flows[:, 0], 1e-9)
    lcoe = lcoe_cost / np.maximum(lcoe_energy, 1e-9)

    def _sq(x):
        x = np.asarray(x)
        return float(x.reshape(-1)[0]) if x.size == 1 else x
    return snap_dict({
        # 'capex'/'opex_year1' ter-SCOPE ("Financial Analysis") — utk scope
        # baku 'PV-BESS-DEG', cap_lcoe==cap & opex_lcoe1==opex1 persis
        # (bit-identik). 'baseline_cost_year1'/'savings_year1'/'npv'/'irr'/
        # 'roi'/'payback_years'/'cashflow' SELALU whole-system (cap/opex1
        # penuh), tak terpengaruh scope — lihat docstring di atas.
        'capex': _sq(cap_lcoe), 'opex_year1': _sq(opex_lcoe1),
        'baseline_cost_year1': _sq(base1), 'savings_year1': _sq(base1 - opex1),
        'lcoe': _sq(lcoe), 'npv': _sq(npv), 'irr': _sq(ir),
        'roi': _sq(roi), 'payback_years': _sq(payback),
        'cashflow': flows if N > 1 else flows[0],
    })
