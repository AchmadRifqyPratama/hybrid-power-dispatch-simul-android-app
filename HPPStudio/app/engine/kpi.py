"""Kalkulasi KPI teknis dari akumulator hasil dispatch.

Semua fungsi menerima skalar ATAU array (N,) — sehingga dipakai baik untuk
run tunggal maupun sweep optimasi tanpa perubahan kode.
"""
from __future__ import annotations
import numpy as np

from .numeric import snap_dict

DIESEL_LHV_KWH_PER_L = 10.0     # nilai kalor solar ~10 kWh/liter


def technical_kpis(acc: dict, params: dict) -> dict:
    """params minimal: bess_kwh, soc_min, soc_max, deg_fuel_rate, deg_kw_total."""
    load = acc['load']
    # self consumption BESS yg dipasok DEG bukan beban terlayani
    served = (acc['served_pvbs'] + acc['served_grid'] + acc['deg_energy']
              - acc.get('selfcons_deg', 0.0))
    bess_kwh = np.asarray(params.get('bess_kwh', 0.0), float)
    usable = np.maximum(bess_kwh * (np.asarray(params.get('soc_max', 1.0))
                                    - np.asarray(params.get('soc_min', 0.0))), 1e-9)
    # Bahan bakar dihitung PER-DEG: Fuel (L) = laju (L/kWh) × energi DEG (kWh),
    # dijumlahkan atas ketiga unit. Memakai energi mentah akumulator (bukan KPI
    # yang sudah dibulatkan) sehingga jumlahnya persis sama dengan energi DEG
    # total. Kompatibel-mundur: bila hanya `deg_efficiency` diberikan, laju
    # diturunkan sebagai 1/(eff × 10) → hasil identik dengan model lama.
    rates = params.get('deg_fuel_rate')
    if rates is None:
        eff = max(float(np.max(np.asarray(
            params.get('deg_efficiency', 0.33)))), 1e-6)
        r = 1.0 / (eff * DIESEL_LHV_KWH_PER_L)
        rates = (r, r, r)
    rates = tuple(rates)
    r1 = np.asarray(rates[0], float)
    r2 = np.asarray(rates[1] if len(rates) > 1 else rates[0], float)
    r3 = np.asarray(rates[2] if len(rates) > 2 else rates[0], float)
    fuel_l = (acc.get('deg1_energy', 0.0) * r1
              + acc.get('deg2_energy', 0.0) * r2
              + acc.get('deg3_energy', 0.0) * r3)
    deg_hours = np.maximum(acc['deg_hours'], 1e-9)
    kpi = {
        'annual_load_kwh': load,
        'annual_pv_generation_kwh': acc['pv_gen'],
        'annual_pv_inverter_out_kwh': acc['pv_inv_out'],
        'annual_battery_charge_kwh': acc['chg'],
        'annual_battery_discharge_kwh': acc['dhg'],
        'battery_throughput_kwh': acc['chg'] + acc['dhg'],
        'battery_cycles': acc['dhg'] / usable,
        'renewable_fraction': np.where(load > 0, acc['served_pvbs'] / np.maximum(load, 1e-9), 0.0),
        'pv_excess_kwh': acc['pv_excess'],
        'pv_excess_ratio': np.where(acc['pv_gen'] > 0,
                                    acc['pv_excess'] / np.maximum(acc['pv_gen'], 1e-9), 0.0),
        'curtailment_kwh': acc['pv_excess'],   # dalam model ini identik dgn excess
        'diesel_runtime_h': acc['deg_hours'],
        'diesel_energy_kwh': acc['deg_energy'],
        'deg_charge_kwh': acc.get('chg_deg', 0.0),
        'grid_charge_kwh': acc.get('chg_grid', 0.0),
        'pv_charge_kwh': acc.get('chg_pv', 0.0),
        'outage_hours': acc.get('outage_hours_total', 0.0),
        'deg1_energy_kwh': acc.get('deg1_energy', 0.0),
        'deg2_energy_kwh': acc.get('deg2_energy', 0.0),
        'deg3_energy_kwh': acc.get('deg3_energy', 0.0),
        'diesel_fuel_l': fuel_l,
        'diesel_avg_loading': np.where(acc['deg_hours'] > 0,
                                       acc['deg_loading_sum'] / deg_hours, 0.0),
        'soc_min': acc['soc_min_seen'],
        'soc_max': acc['soc_max_seen'],
        'grid_import_kwh': acc['grid_import'],
        'grid_import_peak_kwh': acc.get('grid_import_peak', 0.0),
        'grid_import_offpeak_kwh': acc.get('grid_import_offpeak', 0.0),
        'grid_export_kwh': acc['grid_export'],
        'unserved_kwh': acc['unserved'],
        'supply_ratio': np.where(load > 0, served / np.maximum(load, 1e-9), 0.0),
        'pvbs_supply_ratio': np.where(load > 0, acc['served_pvbs'] / np.maximum(load, 1e-9), 0.0),
        'grid_supply_ratio': np.where(load > 0, acc['served_grid'] / np.maximum(load, 1e-9), 0.0),
        # Energi (kWh) MENTAH beban terlayani per-jalur — dipakai finance.py
        # (Parameters > Finance > "Financial Analysis") utk membatasi LCOE ke
        # komponen PV-BESS saja / DEG(+Grid) saja. Bukan KPI baru yg tampil
        # tersendiri di UI, semata sumber angka bagi finance.py.
        'served_pvbs_kwh': acc['served_pvbs'],
        # Self consumption BESS (aux) — energi terpasok & per sumber pemasok
        'bess_self_consumption_kwh': acc.get('selfcons', 0.0),
        'bess_self_cons_pvbs_kwh': (acc.get('selfcons_pv', 0.0)
                                    + acc.get('selfcons_bess', 0.0)),
        'bess_self_cons_grid_kwh': acc.get('selfcons_grid', 0.0),
        'bess_self_cons_deg_kwh': acc.get('selfcons_deg', 0.0),
        'bess_self_cons_unserved_kwh': acc.get('selfcons_uns', 0.0),
        'served_grid_kwh': acc.get('served_grid', 0.0),
        # Firming: "Firming Target Met (%)" = waktu Plant Inj BENAR-BENAR
        # mencapai target ÷ TOTAL waktu firming window, dari jendela simulasi
        # ini APA ADANYA (tak diekstrapolasi/dianualisasi — lihat
        # optimization.py _ENERGY_ACC/_STEP_ACC yg SENGAJA tak menyertakan
        # firm_time_ok/firm_time_window). 100% bila jendela firming tak
        # pernah aktif (mode lain/Standard, atau firm_time_window=0).
        'firm_time_ok_h': acc.get('firm_time_ok', 0.0),
        'firm_time_window_h': acc.get('firm_time_window', 0.0),
        'firm_met_pct': np.where(
            np.asarray(acc.get('firm_time_window', 0.0), float) > 1e-9,
            100.0 * np.asarray(acc.get('firm_time_ok', 0.0), float)
            / np.maximum(np.asarray(acc.get('firm_time_window', 0.0), float), 1e-9),
            100.0),
    }
    return snap_dict(kpi)

def monthly_aggregates(series: dict, datetimes, fuel_rate: float | None = None) -> dict:
    """Agregasi bulanan deret waktu run tunggal untuk bar chart & laporan.

    `fuel_rate` (L/kWh) memakai laju bahan bakar efektif; bila None dipakai
    nilai bawaan setara efisiensi 33% (kompatibel-mundur)."""
    import pandas as pd
    idx = pd.DatetimeIndex(datetimes)
    months = idx.month
    out = {}
    for key in ('load', 'pv_inv_out', 'grid', 'deg', 'dhg', 'pv_excess', 'unserved'):
        s = np.asarray(series[key]).reshape(len(idx), -1)[:, 0]
        out[key] = np.array([s[months == m].sum() for m in range(1, 13)])
    if fuel_rate is None:
        fuel_rate = 1.0 / (0.33 * DIESEL_LHV_KWH_PER_L)
    out['fuel_l'] = out['deg'] * float(fuel_rate)
    return snap_dict(out)
