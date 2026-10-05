"""Pembuat laporan simulasi — HTML mandiri (chart SVG inline, siap cetak/PDF).

Tidak membutuhkan Microsoft Excel maupun koneksi internet.
"""
from __future__ import annotations
import base64
import io
from datetime import datetime

from ..config.i18n import tr
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
try:  # dipakai savefig(format='svg'); import eksplisit agar terdeteksi
    from matplotlib.backends import backend_svg  # noqa: F401
    _HAS_SVG = True
except Exception:  # pragma: no cover
    _HAS_SVG = False

MONTHS_ID = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
             'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def months():
    from ..config.i18n import get_language
    return MONTHS_EN if get_language() == 'EN' else MONTHS_ID
C = dict(grid='#2563EB', deg='#DC2626', pv='#16A34A', bess='#F97316',
         load='#6B7280', soc='#7C3AED', exc='#EAB308')


def _fig_to_html(fig) -> str:
    buf = io.BytesIO()
    if _HAS_SVG:
        fig.savefig(buf, format='svg', bbox_inches='tight')
        plt.close(fig)
        svg = buf.getvalue().decode('utf-8')
        return svg[svg.find('<svg'):]
    fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return f'<img src="data:image/png;base64,{b64}" style="max-width:100%">'


def _ts_chart(series, dts, start=0, hours=168):
    sl = slice(start, start + hours)
    x = np.arange(hours)
    fig, ax1 = plt.subplots(figsize=(9.5, 3.4), dpi=100)
    def g(k):
        a = np.asarray(series[k]); return a.reshape(len(a), -1)[:, 0][sl]
    ax1.plot(x, g('grid'), color=C['grid'], lw=1.1, label=tr('Grid'))
    ax1.plot(x, g('deg'), color=C['deg'], lw=1.1, label=tr('Diesel'))
    ax1.plot(x, g('pv_inv_out'), color=C['pv'], lw=1.1, label='PV INV')
    ax1.plot(x, g('bess_net'), color=C['bess'], lw=1.1, label='BESS')
    ax1.plot(x, g('load'), color=C['load'], lw=1.3, ls='--', label='Load')
    ax2 = ax1.twinx()
    ax2.plot(x, 100 * g('soc'), color=C['soc'], lw=1.0, alpha=0.8, label='SOC')
    ax2.set_ylabel('SOC (%)'); ax2.set_ylim(0, 100)
    ax1.set_ylabel('kW'); ax1.set_xlabel('Jam (minggu pertama)')
    ax1.legend(loc='upper left', ncol=5, fontsize=7, frameon=False)
    ax1.grid(alpha=0.25)
    return _fig_to_html(fig)


def _pie_energy(kpi):
    vals = [kpi['pvbs_supply_ratio'], kpi['grid_supply_ratio'],
            max(0.0, 1 - kpi['pvbs_supply_ratio'] - kpi['grid_supply_ratio']
                - kpi['unserved_kwh'] / max(kpi['annual_load_kwh'], 1e-9)),
            kpi['unserved_kwh'] / max(kpi['annual_load_kwh'], 1e-9)]
    labels = ['PV + BESS', tr('Grid'), tr('Diesel'), tr('Unserved')]
    colors = [C['pv'], C['grid'], C['deg'], '#9CA3AF']
    vals = np.maximum(np.asarray(vals, float), 0)
    keep = vals > 1e-4
    fig, ax = plt.subplots(figsize=(3.4, 3.0), dpi=100)
    ax.pie(vals[keep], labels=np.asarray(labels)[keep].tolist(),
           colors=np.asarray(colors)[keep].tolist(),
           autopct='%1.1f%%', textprops={'fontsize': 8})
    ax.set_title(tr('Energy Mix'), fontsize=10)
    return _fig_to_html(fig)


def _monthly_bars(monthly):
    fig, axes = plt.subplots(1, 3, figsize=(9.5, 2.6), dpi=100)
    for ax, (key, title, color) in zip(axes, [
            ('pv_inv_out', 'Energi PV Bulanan (kWh)', C['pv']),
            ('fuel_l', 'Fuel Diesel Bulanan (L)', C['deg']),
            ('pv_excess', 'Curtailment Bulanan (kWh)', C['exc'])]):
        ax.bar(months(), monthly[key], color=color)
        ax.set_title(title, fontsize=9)
        ax.tick_params(labelsize=7); ax.grid(axis='y', alpha=0.25)
    fig.tight_layout()
    return _fig_to_html(fig)


def _heatmap(series, key, title, cmap):
    a = np.asarray(series[key]); a = a.reshape(len(a), -1)[:, 0]
    days = len(a) // 24
    m = a[:days * 24].reshape(days, 24).T
    fig, ax = plt.subplots(figsize=(9.5, 2.2), dpi=100)
    im = ax.imshow(m, aspect='auto', origin='lower', cmap=cmap,
                   extent=[1, days, 0, 24])
    ax.set_title(title, fontsize=9); ax.set_xlabel('Hari'); ax.set_ylabel('Jam')
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    return _fig_to_html(fig)


def _fmt(v, dec=1):
    if isinstance(v, float):
        return f'{v:,.{dec}f}'
    return str(v)


def build_report(path: str, cfg: dict, result: dict, datetimes=None):
    kpi, fin = result['kpi'], result.get('finance')
    s = result['series']; monthly = result.get('monthly')
    rows_tech = [
        (tr('Annual Load'), f"{_fmt(kpi['annual_load_kwh'],0)} kWh"),
        (tr('Annual PV Generation'), f"{_fmt(kpi['annual_pv_generation_kwh'],0)} kWh"),
        (tr('PV Inverter Output'), f"{_fmt(kpi['annual_pv_inverter_out_kwh'],0)} kWh"),
        (tr('Unused Energy / Curtailment'),
         f"{_fmt(kpi['pv_excess_kwh'],0)} kWh ({kpi['pv_excess_ratio']*100:.1f}%)"),
        ('Battery Charge / Discharge',
         f"{_fmt(kpi['annual_battery_charge_kwh'],0)} / "
         f"{_fmt(kpi['annual_battery_discharge_kwh'],0)} kWh"),
        (tr('Battery Throughput'), f"{_fmt(kpi['battery_throughput_kwh'],0)} kWh"),
        (tr('Battery Cycles'), _fmt(kpi['battery_cycles'])),
        ('SOC Min / Max',
         f"{kpi['soc_min']*100:.1f}% / {kpi['soc_max']*100:.1f}%"),
        (tr('Renewable Fraction'), f"{kpi['renewable_fraction']*100:.1f}%"),
        ('Grid Import / Export',
         f"{_fmt(kpi['grid_import_kwh'],0)} / {_fmt(kpi['grid_export_kwh'],0)} kWh"),
        ('Diesel Energy / Runtime',
         f"{_fmt(kpi['diesel_energy_kwh'],0)} kWh / {_fmt(kpi['diesel_runtime_h'],0)} h"),
        (tr('Diesel Fuel'), f"{_fmt(kpi['diesel_fuel_l'],0)} L"),
        (tr('Diesel Avg Loading'), f"{kpi['diesel_avg_loading']*100:.1f}%"),
        (tr('Unserved Energy'), f"{_fmt(kpi['unserved_kwh'],1)} kWh"),
    ]
    rows_fin = []
    if fin:
        rows_fin = [
            (tr('CAPEX'), f"Rp {_fmt(fin['capex'],0)}"),
            ('OPEX (tahun-1)', f"Rp {_fmt(fin['opex_year1'],0)}"),
            ('Savings (tahun-1)', f"Rp {_fmt(fin['savings_year1'],0)}"),
            ('LCOE', f"Rp {_fmt(fin['lcoe'],0)}/kWh"),
            (tr('NPV'), f"Rp {_fmt(fin['npv'],0)}"),
            (tr('IRR'), ('-' if fin['irr'] != fin['irr'] else f"{fin['irr']*100:.1f}%")),
            (tr('ROI'), f"{fin['roi']*100:.1f}%"),
            (tr('Payback'), ('-' if fin['payback_years'] != fin['payback_years']
                         else f"{fin['payback_years']:.1f} tahun")),
        ]

    def table(rows):
        return ''.join(f'<tr><td>{k}</td><td class="v">{v}</td></tr>'
                       for k, v in rows)

    charts = [_ts_chart(s, datetimes), _pie_energy(kpi)]
    if monthly:
        charts.append(_monthly_bars(monthly))
    charts.append(_heatmap(s, 'soc', 'Heatmap BESS SOC (fraksi)', 'viridis'))
    charts.append(_heatmap(s, 'deg', 'Heatmap Diesel Loading (kW)', 'Reds'))
    charts.append(_heatmap(s, 'pv_excess', 'Heatmap Curtailment (kW)', 'YlOrBr'))

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{tr('Laporan Simulasi')} — {cfg.get('project_name','')}</title>
<style>
 body{{font-family:'Segoe UI',Arial,sans-serif;color:#1f2937;margin:32px auto;
      max-width:960px;}}
 h1{{color:#1F3864;border-bottom:3px solid #1F3864;padding-bottom:6px;}}
 h2{{color:#2F5597;margin-top:28px;}}
 table{{border-collapse:collapse;width:100%;font-size:13px;}}
 td{{padding:5px 10px;border-bottom:1px solid #e5e7eb;}}
 td.v{{text-align:right;font-weight:600;}}
 .meta{{color:#6b7280;font-size:12px;}}
 .cols{{display:flex;gap:24px;}} .cols>div{{flex:1;}}
 @media print{{ .chart svg{{max-width:100%;}} }}
</style></head><body>
<h1>{tr('Laporan Simulasi Hybrid Power Plant')}</h1>
<p class="meta">{tr('Project:')} <b>{cfg.get('project_name','-')}</b> &nbsp;|&nbsp;
Customer: {cfg.get('customer','-')} &nbsp;|&nbsp; Site: {cfg.get('site_name','-') or '-'} &nbsp;|&nbsp; {tr('Lokasi:')} {cfg.get('location','-')}
&nbsp;|&nbsp; {tr('Dibuat:')} {datetime.now():%d %b %Y %H:%M}</p>
<p class="meta">{tr('Konfigurasi:')} PV {cfg.get('pv_kwp')} kWp · Inverter
{cfg.get('pv_inv_kw')} kW · BESS {cfg.get('bess_kwh')} kWh · Grid
{cfg.get('grid_kw')} kW · DEG {cfg.get('deg1_kw')} kW</p>
<p class="meta">Load Supply Priority: <b>{cfg.get('load_priority','-')}</b> &nbsp;|&nbsp; BESS Charging Priority: {cfg.get('charge_priority','-')} &nbsp;|&nbsp; Grid→BESS: {tr('ya') if cfg.get('grid_charge_enabled') else tr('tidak')} &nbsp;|&nbsp; DEG→BESS: {tr('ya') if cfg.get('deg_charge_enabled') else tr('tidak')} &nbsp;|&nbsp; DEG interlock: {tr('ya') if cfg.get('deg_interlock') else tr('tidak')}</p>
<div class="cols"><div><h2>{tr('KPI Teknis')}</h2><table>{table(rows_tech)}</table></div>
<div><h2>{tr('KPI Finansial')}</h2><table>{table(rows_fin) or
 '<tr><td colspan=2>-</td></tr>'}</table></div></div>
<h2>{tr('Profil Operasi (minggu pertama)')}</h2><div class="chart">{charts[0]}</div>
<div class="cols"><div class="chart">{charts[1]}</div></div>
<h2>{tr('Agregat Bulanan')}</h2><div class="chart">{charts[2] if monthly else ''}</div>
<h2>{tr('Heatmap Operasi')}</h2>
<div class="chart">{charts[-3]}</div>
<div class="chart">{charts[-2]}</div>
<div class="chart">{charts[-1]}</div>
<p class="meta" style="font-size:10px">{tr('Dihasilkan oleh HPP Studio')} &nbsp;·&nbsp; {tr('Developed by')} ARP · Engineering, Akartha Energy</p>
</body></html>"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path
