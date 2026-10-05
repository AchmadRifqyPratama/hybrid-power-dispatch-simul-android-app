"""Isi laporan (v139) — model blok yang TIDAK bergantung format.

Satu sumber isi untuk dua keluaran: `pdf_report.py` (reportlab) dan
`docx_report.py` (python-docx) hanya me-render daftar blok yang dihasilkan
`build_report()`. Dengan begitu PDF & Word selalu identik isi & urutannya.

Struktur laporan (bagian tampil sesuai aspek yang dipilih pengguna):
  Sampul · Kendali Dokumen · Daftar Isi
  1  Ringkasan Eksekutif (KPI, kriteria investasi & verdict, temuan kunci)
  2  Deskripsi Proyek & Dasar Desain
  3  Kajian Beban & Sumber Daya            [teknis]
  4  Hasil Simulasi Energi (Dispatch)     [teknis]
  5  Dampak Lingkungan                    [teknis]
  6  Analisis Finansial                   [finansial]
  7  Analisis Sensitivitas                [finansial]
  8  Kajian Risiko & Mitigasi
  9  Kesimpulan & Rekomendasi
  Lampiran A Metodologi · B Singkatan · C Batasan & Disclaimer

PENTING: modul ini TIDAK menjalankan/mengubah mesin dispatch maupun rumus
finansial. Seluruh angka dibaca dari hasil simulasi; indikator turunan
(mis. specific yield, discounted payback, rincian OPEX) hanya dihitung ulang
dari angka yang sama untuk penyajian. Rincian OPEX/baseline memanggil helper
engine yang SAMA (`engine.finance`) sehingga totalnya konsisten.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from . import common as K
from . import charts as CH
from . import methodology as M
from .common import L

_n = K.fmt_n
_rp = K.fmt_rp
_pct = K.fmt_pct
_ms = K.fmt_money_short
_mn = K.fmt_mn

# Faktor emisi indikatif (dapat ditimpa lewat cfg bila tersedia)
EF_DIESEL_KG_PER_L = 2.68          # tipikal solar (IPCC, pembakaran)
EF_GRID_DEFAULT = 0.85             # kgCO2/kWh — asumsi rata-rata grid; GANTI
                                   # dgn faktor emisi grid setempat yg berlaku


def _f(x, default=0.0):
    try:
        v = float(x)
        return default if v != v else v
    except (TypeError, ValueError):
        return default


def _arr(d, k):
    try:
        return np.asarray(d.get(k, []), float).reshape(-1)
    except Exception:
        return np.zeros(0)


def _png(fig, dpi=170):
    """Figure → bytes PNG (None aman)."""
    if fig is None:
        return None
    try:
        return K.fig_to_png(fig, dpi=dpi).getvalue()
    except Exception:
        return None


# ============================================================ builder blok ====
class _Doc:
    """Pengumpul blok + penomoran bab/gambar/tabel."""

    def __init__(self):
        self.blocks = []
        self.h1 = 0
        self.h2 = 0
        self.fig = 0
        self.tab = 0
        self.appendix = None

    def add(self, **b):
        self.blocks.append(b)
        return b

    def section(self, text, appendix_letter=None, pagebreak=True):
        if pagebreak:
            self.add(t='pagebreak')
        if appendix_letter:
            self.appendix = appendix_letter
            self.h2 = 0
            num = f'{L("Lampiran", "Appendix")} {appendix_letter}'
        else:
            self.h1 += 1
            self.h2 = 0
            num = str(self.h1)
        self.add(t='h1', num=num, text=text)

    def sub(self, text):
        self.h2 += 1
        base = self.appendix if self.appendix else str(self.h1)
        self.add(t='h2', num=f'{base}.{self.h2}', text=text)

    def p(self, text, keep=False):
        self.add(t='p', text=text, keep=keep)

    def note(self, text, keep=False):
        self.add(t='note', text=text, keep=keep)

    def bullets(self, items):
        items = [i for i in items if i]
        if items:
            self.add(t='bullets', items=items)

    def table(self, header, rows, align=None, widths=None, caption=None,
              total=False, tones=None, group_rows=None, font=None):
        cap = None
        if caption:
            self.tab += 1
            cap = f'{L("Tabel", "Table")} {self.tab}. {caption}'
        self.add(t='table', header=header, rows=rows,
                 align=align or ['l'] + ['r'] * (len(header) - 1),
                 widths=widths, caption=cap, total=total, tones=tones or {},
                 group_rows=set(group_rows or []), font=font)
        return self.tab

    def figure(self, fig, caption, width=1.0, dpi=170):
        png = _png(fig, dpi)
        if png is None:
            return None
        self.fig += 1
        self.add(t='figure', png=png, width=width,
                 caption=f'{L("Gambar", "Figure")} {self.fig}. {caption}')
        return self.fig

    def kpis(self, items, cols=4):
        self.add(t='kpis', items=items, cols=cols)

    def callout(self, tone, title, text=''):
        self.add(t='callout', tone=tone, title=title, text=text)


# ======================================================= analisis turunan ====
def _analysis(cfg, result, multi):
    """Hitung seluruh angka turunan yang dipakai laporan (sekali)."""
    kpi = result.get('kpi', {}) or {}
    fin = result.get('finance') or {}
    series = result.get('series')
    p = result.get('params')
    sz = K.sizes_from(result, cfg)
    A = dict(kpi=kpi, fin=fin, series=series, sizes=sz, params=p)
    dt = _f(getattr(p, 'interval_h', None), 1.0) or 1.0
    A['dt'] = dt
    A['interval'] = str(result.get('sim_interval') or cfg.get('sim_interval')
                        or '1 hour')
    win_h = _f(result.get('window_h'), 0.0)
    if win_h <= 0 and series is not None and 'load' in series:
        win_h = len(np.asarray(series['load'])) * dt
    A['window_h'] = win_h or 8760.0
    A['annualized'] = A['window_h'] < 8700
    A['start_h'] = _f(result.get('window_start_h'), 0.0)

    # --- komponen ---
    n_deg, kw_deg, caps = K.deg_info(cfg)
    A.update(n_deg=n_deg if kw_deg > 0 else 0, kw_deg=kw_deg, deg_caps=caps)
    A['grid_on'] = bool(cfg.get('grid_enabled', True))
    A['has_pv'] = sz['kwp'] > 0
    A['has_bess'] = sz['kwh_bess'] > 0
    A['has_deg'] = kw_deg > 0
    pcs = _f(cfg.get('max_discharge_kw', cfg.get('max_charge_kw', 0.0)))
    A['pcs'] = pcs
    smin, smax = _f(cfg.get('soc_min'), 0.1), _f(cfg.get('soc_max'), 0.95)
    A['usable_kwh'] = sz['kwh_bess'] * max(0.0, smax - smin)
    A['dcac'] = sz['kwp'] / sz['kw_inv'] if sz['kw_inv'] > 0 else float('nan')
    A['duration_h'] = A['usable_kwh'] / pcs if pcs > 0 else float('nan')
    A['c_rate'] = pcs / sz['kwh_bess'] if sz['kwh_bess'] > 0 else float('nan')

    # --- beban & sumber daya ---
    load_kwh = _f(kpi.get('annual_load_kwh'))
    A['load_kwh'] = load_kwh
    peak = float('nan')
    lmin = float('nan')
    if series is not None and 'load' in series:
        la = np.asarray(series['load'], float).reshape(len(series['load']), -1)[:, 0]
        if la.size:
            peak, lmin = float(np.max(la)), float(np.min(la))
    A['peak_kw'], A['min_kw'] = peak, lmin
    A['avg_kw'] = load_kwh / 8760.0
    A['load_factor'] = A['avg_kw'] / peak if peak and peak == peak and peak > 0 else float('nan')
    pv_gen = _f(kpi.get('annual_pv_generation_kwh'))
    A['pv_gen'] = pv_gen
    A['spec_yield'] = pv_gen / sz['kwp'] if sz['kwp'] > 0 else float('nan')
    A['pv_cf'] = pv_gen / (sz['kwp'] * 8760.0) if sz['kwp'] > 0 else float('nan')
    A['pv_pen'] = sz['kwp'] / peak if peak and peak == peak and peak > 0 else float('nan')
    out_h = _f(kpi.get('outage_hours'))
    A['outage_h'] = out_h
    A['grid_avail'] = (1.0 - out_h / 8760.0) if A['grid_on'] else 0.0

    # --- pasokan ke beban ---
    uns = _f(kpi.get('unserved_kwh'))
    pvbs = _f(kpi.get('served_pvbs_kwh'))
    grid_s = _f(kpi.get('served_grid_kwh'))
    deg_s = max(0.0, load_kwh - uns - pvbs - grid_s)
    A.update(uns=uns, served_pvbs=pvbs, served_grid=grid_s, served_deg=deg_s)
    A['lpsp'] = uns / load_kwh if load_kwh > 0 else 0.0
    A['rf'] = _f(kpi.get('renewable_fraction'))

    # --- BESS / diesel ---
    chg = _f(kpi.get('annual_battery_charge_kwh'))
    dis = _f(kpi.get('annual_battery_discharge_kwh'))
    A.update(bess_chg=chg, bess_dis=dis)
    A['bess_eff'] = dis / chg if chg > 0 else float('nan')
    A['cycles'] = _f(kpi.get('battery_cycles'))
    fuel = _f(kpi.get('diesel_fuel_l'))
    deg_e = _f(kpi.get('diesel_energy_kwh'))
    A.update(fuel_l=fuel, deg_kwh=deg_e)
    A['sfc'] = fuel / deg_e if deg_e > 0 else float('nan')

    # --- emisi (indikatif) ---
    efg = _f(cfg.get('grid_emission_factor_kg_per_kwh'), EF_GRID_DEFAULT) or EF_GRID_DEFAULT
    A['ef_grid'] = efg
    try:
        from ..config.parameters import cost_config
        cc = cost_config(cfg)
    except Exception:
        cc = {}
    A['cc'] = cc
    try:
        from ..engine.finance import _fuel_rate_eff
        rate = float(_fuel_rate_eff(cc))
    except Exception:
        rate = K.fuel_rate(cfg)
    A['fuel_rate_eff'] = rate
    gi = _f(kpi.get('grid_import_kwh'))
    ge = _f(kpi.get('grid_export_kwh'))
    A.update(grid_imp=gi, grid_exp=ge)
    bmode = str(cc.get('baseline_mode', cfg.get('baseline_mode', 'diesel_only')))
    A['baseline_mode'] = bmode
    if bmode == 'diesel_only':
        b_grid, b_fuel = 0.0, load_kwh * rate
    else:
        b_grid = min(load_kwh, gi)
        b_fuel = (load_kwh - b_grid) * rate
    A['base_grid'], A['base_fuel'] = b_grid, b_fuel
    A['co2_base'] = (b_fuel * EF_DIESEL_KG_PER_L + b_grid * efg) / 1000.0
    A['co2_proj'] = (fuel * EF_DIESEL_KG_PER_L + max(0.0, gi) * efg) / 1000.0
    A['co2_avoid'] = A['co2_base'] - A['co2_proj']

    # --- finansial ---
    lifetime = bool(multi and multi.get('finance'))
    A['lifetime'] = lifetime
    head = (multi.get('finance') if lifetime else None) or fin
    A['head'] = head
    A['years'] = int(_f(cfg.get('project_lifetime_y'), 20))
    A['disc'] = _f(cfg.get('discount_rate'), 0.08)
    A['infl'] = _f(cfg.get('inflation'), 0.03)
    base1 = _f(fin.get('baseline_cost_year1'))
    sav1 = _f(fin.get('savings_year1'))
    A['base1'] = base1
    A['sav1'] = sav1
    A['opex1_full'] = base1 - sav1                 # OPEX seluruh sistem th-1
    A['base_unit'] = base1 / load_kwh if load_kwh > 0 else float('nan')
    A['scope'] = str(cc.get('finance_scope', 'PV-BESS-DEG') or 'PV-BESS-DEG')

    # CAPEX per komponen (seluruh sistem; sama dgn engine.finance.capex)
    ck = lambda k: _f(cc.get(k, cfg.get(k, 0.0)))
    A['capex_items'] = [
        (L('Modul PV', 'PV modules'), sz['kwp'], 'kWp', ck('pv_cost_per_kwp')),
        (L('Inverter PV', 'PV inverter'), sz['kw_inv'], 'kW', ck('inverter_cost_per_kw')),
        (L('Sistem baterai (BESS)', 'Battery system (BESS)'), sz['kwh_bess'], 'kWh', ck('bess_cost_per_kwh')),
        (L('Genset diesel', 'Diesel genset'), sz['kw_deg'], 'kW', ck('deg_cost_per_kw')),
        (L('EPC', 'EPC'), sz['kwp'], 'kWp', ck('epc_cost_per_kwp')),
        (L('Aksesoris', 'Accessories'), 1.0, L('lot', 'lot'), ck('accessories_cost')),
        (L('Logistik', 'Logistics'), 1.0, L('lot', 'lot'), ck('logistic_cost')),
    ]
    A['capex_full'] = sum(q * u for _l, q, _un, u in A['capex_items'])

    # Rincian OPEX tahun-1 (memanggil helper engine yang sama)
    try:
        from ..engine.finance import _grid_energy_cost
        om = _f(cc.get('om_fraction')) * A['capex_full']
        fuel_c = fuel * _f(cc.get('diesel_price_per_l'))
        grid_c = float(np.asarray(_grid_energy_cost(
            gi, cc, kpi.get('grid_import_peak_kwh'),
            kpi.get('grid_import_offpeak_kwh'))).reshape(-1)[0])
        exp_c = ge * _f(cc.get('export_tariff_per_kwh'))
        parts = [(L('O&M (fraksi CAPEX)', 'O&M (share of CAPEX)'), om),
                 (L('Bahan bakar diesel', 'Diesel fuel'), fuel_c),
                 (L('Energi impor grid', 'Grid energy import'), grid_c)]
        if exp_c:
            parts.append((L('Kredit ekspor grid', 'Grid export credit'), -exp_c))
        tot = sum(v for _l, v in parts)
        A['opex_parts'] = parts if abs(tot - A['opex1_full']) <= max(
            1.0, 1e-6 * abs(tot)) else None
    except Exception:
        A['opex_parts'] = None

    # Arus kas (lifetime bila ada; selain itu proyeksi tahun-1 aplikasi)
    r, infl = A['disc'], A['infl']
    if lifetime:
        mf = multi['finance']
        flows = _arr(mf, 'flows')
        yrs = np.arange(1, flows.size)
        base_y = _arr(mf, 'baseline_y')
        repl_y = _arr(mf, 'repl_y')
        save_y = _arr(mf, 'savings_y')
        opex_y = base_y - save_y - repl_y          # OPEX seluruh sistem
    else:
        flows = np.asarray(fin.get('cashflow', []), float).reshape(-1)
        yrs = np.arange(1, flows.size)
        esc = (1.0 + infl) ** (yrs - 1)
        base_y = base1 * esc
        opex_y = A['opex1_full'] * esc
        repl_y = np.zeros(yrs.size)
    disc_f = flows / (1.0 + r) ** np.arange(flows.size) if flows.size else flows
    A.update(flows=flows, cf_years=yrs, base_y=base_y, opex_y=opex_y,
             repl_y=repl_y, disc_flows=disc_f)
    A['cum'] = np.cumsum(flows) if flows.size else flows
    A['cum_disc'] = np.cumsum(disc_f) if flows.size else flows
    A['dpb'] = _payback(disc_f)                     # discounted payback
    A['npv_check'] = float(np.sum(disc_f)) if flows.size else float('nan')
    A['repl_count'] = int(np.sum(np.asarray(repl_y) > 0))
    A['repl_total'] = float(np.sum(repl_y))
    A['feasible'] = K.verdict(head, cfg) if head else False
    return A


def _payback(flows):
    """Tahun saat kumulatif ≥ 0 (interpolasi linier, pola sama dgn engine)."""
    f = np.asarray(flows, float).reshape(-1)
    if f.size < 2:
        return float('nan')
    cum = np.cumsum(f)
    pos = np.where(cum >= 0)[0]
    if not pos.size:
        return float('nan')
    y = int(pos[0])
    if y == 0:
        return 0.0
    return (y - 1) + (-cum[y - 1]) / max(f[y], 1e-9)


# ================================================================ laporan ======
def build_report(cfg, result, datetimes=None, multi_result=None,
                 include_technical=True, include_financial=True):
    """Kembalikan (meta, blocks) untuk dirender PDF/DOCX."""
    tech = bool(include_technical)
    finx = bool(include_financial)
    if not (tech or finx):
        tech = finx = True
    A = _analysis(cfg, result, multi_result)
    finx = finx and bool(A['head'])
    D = _Doc()
    now = datetime.now()
    proj = cfg.get('project_name') or L('Proyek Pembangkit Hibrida',
                                        'Hybrid Power Plant Project')
    comps = [c for c, on in (('PV', A['has_pv']), ('BESS', A['has_bess']),
                             ('Diesel', A['has_deg']), ('Grid', A['grid_on']))
             if on]
    if tech and finx:
        title = L('Studi Kelayakan Pembangkit Listrik Hibrida',
                  'Hybrid Power Plant Feasibility Study')
        code = 'FS'
    elif tech:
        title = L('Laporan Simulasi Dispatch Energi',
                  'Dispatch Energy Simulation Report')
        code = 'DS'
    else:
        title = L('Kajian Kelayakan Finansial', 'Financial Feasibility Assessment')
        code = 'FA'
    meta = dict(
        title=title, project=proj, subtitle=' + '.join(comps),
        client=cfg.get('customer') or '-', site=cfg.get('site_name') or '-',
        location=cfg.get('location') or '-',
        coords=K.coord_text(cfg.get('latitude'), cfg.get('longitude')),
        doc_no=f'AEB-{code}-{now:%Y%m%d-%H%M}', revision='A',
        date=now.strftime('%d %B %Y'),
        status=L('Draf awal — untuk diskusi', 'Preliminary — for discussion'),
        prepared='Engineering · Akartha Energy',
        aspects=[a for a, on in ((L('Teknis', 'Technical'), tech),
                                 (L('Finansial', 'Financial'), finx)) if on],
        header_right=title,
        footer=L('Akartha Energy · Rahasia', 'Akartha Energy · Confidential'),
        verdict=(A['feasible'] if finx else None),
    )

    # ---------------------------------------------------- kendali dokumen ---
    D.add(t='doc_control', rows=[
        (L('Judul dokumen', 'Document title'), title),
        (L('Proyek', 'Project'), proj),
        (L('Klien', 'Client'), meta['client']),
        (L('Nomor dokumen', 'Document no.'), meta['doc_no']),
        (L('Revisi', 'Revision'), f"{meta['revision']} — {meta['status']}"),
        (L('Tanggal', 'Date'), meta['date']),
        (L('Aspek yang dicakup', 'Aspects covered'), ', '.join(meta['aspects'])),
        (L('Disusun oleh', 'Prepared by'), meta['prepared']),
        (L('Diperiksa / disetujui', 'Checked / approved'),
         L('— (wajib ditinjau engineer sebelum diterbitkan)',
           '— (to be reviewed by an engineer before issue)')),
    ])
    D.add(t='toc')

    _exec_summary(D, A, cfg, proj, tech, finx)
    _project_description(D, A, cfg, datetimes, tech, finx)
    if tech:
        _load_resource(D, A, cfg, datetimes)
        _simulation_results(D, A, cfg, result, datetimes, multi_result)
        _environment(D, A, cfg, multi_result)
    if finx:
        _financial(D, A, cfg)
        _sensitivity(D, A, cfg)
    _risks(D, A, cfg, tech, finx)
    _conclusions(D, A, cfg, proj, tech, finx)
    _appendices(D, A, cfg, tech, finx)
    return meta, D.blocks


# ------------------------------------------------------------ 1 ringkasan ---
def _findings(A, cfg, tech, finx):
    out = []
    k = A['kpi']
    if tech:
        load = A['load_kwh'] or 1.0
        mix = [('PV + BESS', A['served_pvbs'] / load), ('Grid', A['served_grid'] / load),
               ('Diesel', A['served_deg'] / load)]
        mix_t = ', '.join(f'{n} {v*100:.1f}%' for n, v in mix if v > 5e-4)
        out.append(L(f"**Bauran pasokan:** beban tahunan {_n(A['load_kwh'])} kWh "
                     f"dipasok oleh {mix_t}; fraksi terbarukan {_pct(A['rf'])}.",
                     f"**Supply mix:** the {_n(A['load_kwh'])} kWh annual load is "
                     f"supplied by {mix_t}; renewable fraction {_pct(A['rf'])}."))
        cr = _f(k.get('pv_excess_ratio'))
        if A['has_pv']:
            if cr > 0.15:
                out.append(L(f"**Curtailment tinggi:** {_pct(cr)} energi PV tersedia "
                             f"tidak termanfaatkan ({_n(k.get('pv_excess_kwh'))} kWh/thn) — "
                             "kapasitas BESS/ekspor membatasi pemanfaatan PV.",
                             f"**High curtailment:** {_pct(cr)} of available PV energy "
                             f"is not utilised ({_n(k.get('pv_excess_kwh'))} kWh/yr) — "
                             "BESS/export capacity limits PV utilisation."))
            else:
                out.append(L(f"**Pemanfaatan PV baik:** curtailment {_pct(cr)}; "
                             f"specific yield {_n(A['spec_yield'])} kWh/kWp·thn.",
                             f"**Good PV utilisation:** curtailment {_pct(cr)}; "
                             f"specific yield {_n(A['spec_yield'])} kWh/kWp·yr."))
        if A['has_bess']:
            cy = A['cycles']
            if cy < 50:
                out.append(L(f"**BESS kurang termanfaatkan:** hanya {_n(cy,1)} siklus "
                             "ekivalen/thn — kapasitas mungkin berlebih untuk strategi "
                             "dispatch saat ini.",
                             f"**BESS under-utilised:** only {_n(cy,1)} equivalent full "
                             "cycles/yr — capacity may be oversized for the current "
                             "dispatch strategy."))
            elif cy > 400:
                out.append(L(f"**Siklus BESS tinggi:** {_n(cy,0)} siklus/thn — pastikan "
                             "sesuai batas garansi siklus pabrikan.",
                             f"**High BESS cycling:** {_n(cy,0)} cycles/yr — confirm "
                             "against the manufacturer's cycle warranty."))
            else:
                out.append(L(f"**BESS:** {_n(cy,1)} siklus ekivalen/thn, rentang SOC "
                             f"{_pct(k.get('soc_min'))}–{_pct(k.get('soc_max'))}.",
                             f"**BESS:** {_n(cy,1)} equivalent full cycles/yr, SOC range "
                             f"{_pct(k.get('soc_min'))}–{_pct(k.get('soc_max'))}."))
        if A['uns'] > 1e-6:
            out.append(L(f"**Keandalan:** {_n(A['uns'],1)} kWh/thn tak terlayani "
                         f"(LPSP {_pct(A['lpsp'],2)}) — tinjau kapasitas cadangan.",
                         f"**Reliability:** {_n(A['uns'],1)} kWh/yr unserved "
                         f"(LPSP {_pct(A['lpsp'],2)}) — review backup capacity."))
        else:
            out.append(L("**Keandalan:** seluruh beban terlayani (energi tak "
                         "terlayani 0 kWh).",
                         "**Reliability:** all load is served (0 kWh unserved)."))
        if A['has_deg'] and _f(k.get('diesel_runtime_h')) > 0:
            al = _f(k.get('diesel_avg_loading'))
            if al < 0.30:
                out.append(L(f"**Loading genset rendah:** rata-rata {_pct(al)} — risiko "
                             "wet-stacking & efisiensi bahan bakar buruk.",
                             f"**Low genset loading:** average {_pct(al)} — risk of "
                             "wet-stacking and poor fuel efficiency."))
    if finx:
        h = A['head']
        irr = _f(h.get('irr'), float('nan'))
        spread = (irr - A['disc']) if irr == irr else float('nan')
        out.append(L(f"**Investasi:** CAPEX {_ms(h.get('capex'))}, NPV "
                     f"{_ms(h.get('npv'))} pada discount rate {_pct(A['disc'])}, IRR "
                     f"{_pct(irr)}" + (f" ({spread*100:+.1f} poin di atas discount rate)"
                                       if spread == spread else '')
                     + f", payback {_n(h.get('payback_years'),1)} tahun.",
                     f"**Investment:** CAPEX {_ms(h.get('capex'))}, NPV "
                     f"{_ms(h.get('npv'))} at a {_pct(A['disc'])} discount rate, IRR "
                     f"{_pct(irr)}" + (f" ({spread*100:+.1f} pts above the discount rate)"
                                       if spread == spread else '')
                     + f", payback {_n(h.get('payback_years'),1)} years."))
        if A['base1'] > 0:
            out.append(L(f"**Penghematan:** biaya energi tahun-1 turun "
                         f"{_pct(A['sav1']/A['base1'])} dari {_ms(A['base1'])} "
                         f"(baseline) menjadi {_ms(A['opex1_full'])}.",
                         f"**Savings:** year-1 energy cost falls by "
                         f"{_pct(A['sav1']/A['base1'])} from {_ms(A['base1'])} "
                         f"(baseline) to {_ms(A['opex1_full'])}."))
        if A['repl_count']:
            out.append(L(f"**Penggantian BESS:** {A['repl_count']}× selama umur proyek "
                         f"({_ms(A['repl_total'])}, nominal) sudah termasuk dalam arus kas.",
                         f"**BESS replacement:** {A['repl_count']}× over the project "
                         f"life ({_ms(A['repl_total'])}, nominal), included in the cash flow."))
    return out


def _exec_summary(D, A, cfg, proj, tech, finx):
    D.section(L('Ringkasan Eksekutif', 'Executive Summary'))
    sz = A['sizes']
    cfg_parts = []
    if A['has_pv']:
        cfg_parts.append(f"PV {_n(sz['kwp'],1)} kWp / {_n(sz['kw_inv'],1)} kWac")
    if A['has_bess']:
        cfg_parts.append(f"BESS {_n(sz['kwh_bess'],0)} kWh / {_n(A['pcs'],0)} kW")
    if A['has_deg']:
        cfg_parts.append(L(f"{A['n_deg']}× genset diesel ({_n(A['kw_deg'],0)} kW)",
                           f"{A['n_deg']}× diesel genset ({_n(A['kw_deg'],0)} kW)"))
    cfg_parts.append(L(f"sambungan grid {_n(cfg.get('grid_kw'),0)} kW",
                       f"{_n(cfg.get('grid_kw'),0)} kW grid connection")
                     if A['grid_on'] else L('tanpa grid (off-grid)', 'no grid (off-grid)'))
    basis = L(f"simulasi dispatch berinterval {A['interval']} selama "
              f"{_n(A['window_h'])} jam", f"a {A['interval']}-interval dispatch "
              f"simulation over {_n(A['window_h'])} hours")
    if A['annualized']:
        basis += L(' (hasil dianualisasi ke 1 tahun)', ' (results annualised to one year)')
    scope = []
    if tech:
        scope.append(L('kinerja teknis & energi', 'technical and energy performance'))
    if finx:
        scope.append(L('kelayakan finansial', 'financial feasibility'))
    D.p(L(f"Dokumen ini menyajikan {' dan '.join(scope)} sistem pembangkit hibrida "
          f"**{proj}**. Konfigurasi yang dikaji: {'; '.join(cfg_parts)}. Hasil "
          f"diperoleh dari {basis}.",
          f"This document presents the {' and '.join(scope)} of the **{proj}** "
          f"hybrid power system. Configuration assessed: {'; '.join(cfg_parts)}. "
          f"Results are derived from {basis}."))
    h = A['head']
    tiles = []
    if tech:
        tiles += [
            (L('Fraksi terbarukan', 'Renewable fraction'), _pct(A['rf']),
             L('porsi beban dari PV + BESS', 'share of load from PV + BESS')),
            (L('Energi PV', 'PV energy'), f"{_n(A['pv_gen']/1000,1)} MWh",
             f"{_n(A['spec_yield'])} kWh/kWp·" + L('thn', 'yr')),
            (L('Curtailment PV', 'PV curtailment'), _pct(A['kpi'].get('pv_excess_ratio')),
             f"{_n(A['kpi'].get('pv_excess_kwh'))} kWh/" + L('thn', 'yr')),
            (L('CO₂ dihindari', 'CO₂ avoided'), f"{_n(A['co2_avoid'],1)} t/" + L('thn', 'yr'),
             L('indikatif, vs baseline', 'indicative, vs baseline')),
        ]
    if finx:
        tiles += [
            ('CAPEX', _ms(h.get('capex')), L('seluruh sistem', 'total system')
             if A['scope'] == 'PV-BESS-DEG' else f"scope {A['scope']}"),
            ('NPV', _ms(h.get('npv')), L(f"@ {_pct(A['disc'])} discount", f"@ {_pct(A['disc'])} discount")),
            ('IRR', _pct(h.get('irr')), L('proyek (nominal)', 'project (nominal)')),
            (L('Payback', 'Payback'), f"{_n(h.get('payback_years'),1)} " + L('thn', 'yr'),
             L(f"diskonto: {_n(A['dpb'],1)} thn", f"discounted: {_n(A['dpb'],1)} yr")),
        ]
    D.kpis(tiles, cols=4)

    if finx:
        D.sub(L('Kriteria Keputusan Investasi', 'Investment Decision Criteria'))
        rows, tones = _criteria_rows(A, cfg)
        D.table([L('Kriteria', 'Criterion'), L('Ambang', 'Threshold'),
                 L('Hasil', 'Result'), L('Status', 'Status')], rows,
                align=['l', 'l', 'r', 'c'], widths=[0.40, 0.22, 0.22, 0.16],
                tones=tones, caption=L('Kriteria kelayakan investasi',
                                       'Investment feasibility criteria'))
        if A['feasible']:
            D.callout('good', L('KESIMPULAN: LAYAK SECARA FINANSIAL',
                                'VERDICT: FINANCIALLY FEASIBLE'),
                      L('NPV positif dan IRR/payback memenuhi kriteria pada asumsi dasar.',
                        'Positive NPV and IRR/payback meet the criteria under base assumptions.'))
        else:
            D.callout('warn', L('KESIMPULAN: MARGINAL — TINJAU ASUMSI',
                                'VERDICT: MARGINAL — REVIEW ASSUMPTIONS'),
                      L('Satu atau lebih kriteria utama tidak terpenuhi pada asumsi dasar.',
                        'One or more key criteria are not met under base assumptions.'))
    D.sub(L('Temuan Kunci', 'Key Findings'))
    D.bullets(_findings(A, cfg, tech, finx))


def _criteria_rows(A, cfg):
    h = A['head']
    npv = _f(h.get('npv'), float('nan'))
    irr = _f(h.get('irr'), float('nan'))
    pb = _f(h.get('payback_years'), float('nan'))
    lcoe = _f(h.get('lcoe'), float('nan'))
    ok = L('✓ Terpenuhi', '✓ Met')
    no = L('✗ Tidak', '✗ Not met')
    rows, tones = [], {}

    def add(name, thr, val, passed, info=False):
        i = len(rows)
        rows.append([name, thr, val, ok if passed else
                     (L('! Perhatian', '! Note') if info else no)])
        tones[(i, 3)] = 'good' if passed else ('warn' if info else 'bad')
    add(L('Net Present Value (NPV)', 'Net Present Value (NPV)'), '> 0',
        _ms(npv), npv == npv and npv > 0)
    add(L('Internal Rate of Return (IRR)', 'Internal Rate of Return (IRR)'),
        f"≥ {_pct(A['disc'])} (discount)", _pct(irr),
        irr == irr and irr >= A['disc'])
    add(L('Periode balik modal', 'Payback period'),
        f"≤ {A['years']} " + L('thn (umur proyek)', 'yr (project life)'),
        f"{_n(pb,1)} " + L('thn', 'yr'), pb == pb and pb <= A['years'])
    if A['base_unit'] == A['base_unit'] and lcoe == lcoe:
        add(L('LCOE vs biaya energi baseline', 'LCOE vs baseline cost of energy'),
            f"≤ {_rp(A['base_unit'])}/kWh", f"{_rp(lcoe)}/kWh",
            lcoe <= A['base_unit'], info=True)
    return rows, tones


# ------------------------------------------------------------ 2 proyek -------
def _project_description(D, A, cfg, datetimes, tech, finx):
    D.section(L('Deskripsi Proyek & Dasar Desain', 'Project Description & Design Basis'))
    D.sub(L('Lokasi Proyek', 'Project Site'))
    loc = cfg.get('location') or '-'
    site = cfg.get('site_name') or '-'
    coord = K.coord_text(cfg.get('latitude'), cfg.get('longitude'))
    rows = [(L('Nama site', 'Site name'), site), (L('Lokasi', 'Location'), loc)]
    if coord != '-':
        rows.append((L('Koordinat', 'Coordinates'), coord))
    rows.append((L('Klien', 'Client'), cfg.get('customer') or '-'))
    D.table([L('Item', 'Item'), L('Keterangan', 'Description')],
            [list(r) for r in rows], align=['l', 'l'], widths=[0.3, 0.7])
    if K.has_coords(cfg):
        try:
            mfig = K.fig_location_map(cfg.get('latitude'), cfg.get('longitude'))
        except Exception:
            mfig = None
        if mfig is not None:
            D.figure(mfig, L(f'Peta lokasi proyek ({coord}). Sumber peta: '
                             '© OpenStreetMap contributors.',
                             f'Project location map ({coord}). Map data: '
                             '© OpenStreetMap contributors.'), width=0.7)

    D.sub(L('Konfigurasi Sistem', 'System Configuration'))
    sz = A['sizes']
    rows, groups = [], []

    def grp(name):
        groups.append(len(rows))
        rows.append([name, '', ''])
    if A['has_pv']:
        grp(L('Pembangkit PV', 'PV plant'))
        rows += [[L('Kapasitas PV (DC)', 'PV capacity (DC)'), f"{_n(sz['kwp'],1)}", 'kWp'],
                 [L('Kapasitas inverter (AC)', 'Inverter capacity (AC)'), f"{_n(sz['kw_inv'],1)}", 'kW'],
                 [L('Rasio DC/AC', 'DC/AC ratio'), _n(A['dcac'], 2), '-']]
    if A['has_bess']:
        grp(L('Sistem penyimpanan (BESS)', 'Battery storage (BESS)'))
        rows += [[L('Kapasitas nominal', 'Nominal capacity'), _n(sz['kwh_bess'], 1), 'kWh'],
                 [L('Kapasitas guna (jendela SOC)', 'Usable capacity (SOC window)'),
                  _n(A['usable_kwh'], 1), 'kWh'],
                 [L('Daya PCS (charge / discharge)', 'PCS power (charge / discharge)'),
                  f"{_n(cfg.get('max_charge_kw'),1)} / {_n(cfg.get('max_discharge_kw'),1)}", 'kW'],
                 [L('Durasi pada daya penuh', 'Duration at rated power'), _n(A['duration_h'], 2), L('jam', 'h')],
                 [L('C-rate', 'C-rate'), _n(A['c_rate'], 2), 'C'],
                 [L('Jendela SOC (min – maks)', 'SOC window (min – max)'),
                  f"{_pct(cfg.get('soc_min'),0)} – {_pct(cfg.get('soc_max'),0)}", '%'],
                 [L('Efisiensi round-trip', 'Round-trip efficiency'), _pct(cfg.get('rte'), 1), '%']]
        if _f(cfg.get('bess_self_cons_kw', 0.0)) > 0:
            _src = str(cfg.get('bess_sc_source', 'PV+BESS'))
            rows += [[L('Konsumsi sendiri (self consumption)', 'Self consumption'),
                      _n(_f(cfg.get('bess_self_cons_kw')), 2) + ' (' +
                      L('dipasok ', 'supplied by ') + _src + ')', 'kWh/h']]
    if A['has_deg']:
        grp(L('Genset diesel (DEG)', 'Diesel genset (DEG)'))
        caps = ' + '.join(_n(c, 0) for c in A['deg_caps'] if c > 0)
        rows += [[L('Jumlah & kapasitas unit', 'Units & rating'), f"{A['n_deg']}× ({caps})", 'kW'],
                 [L('Loading minimum per unit', 'Minimum loading per unit'),
                  _pct(cfg.get('deg_min_loading'), 0), '%'],
                 [L('Laju konsumsi bahan bakar', 'Fuel consumption rate'),
                  K.fuel_rate_disp(cfg).replace(' L/kWh', ''), 'L/kWh']]
    grp(L('Grid', 'Grid'))
    if A['grid_on']:
        rows += [[L('Kapasitas sambungan', 'Connection capacity'), _n(cfg.get('grid_kw'), 1), 'kW'],
                 [L('Ekspor ke grid', 'Export to grid'),
                  L('Ya', 'Yes') if cfg.get('allow_export') else L('Tidak', 'No'), '-']]
    else:
        rows += [[L('Status', 'Status'), L('Off-grid (tanpa grid)', 'Off-grid (no grid)'), '-']]
    D.table([L('Parameter', 'Parameter'), L('Nilai', 'Value'), L('Satuan', 'Unit')],
            rows, align=['l', 'r', 'l'], widths=[0.55, 0.28, 0.17],
            group_rows=groups, caption=L('Konfigurasi sistem yang dikaji',
                                         'Assessed system configuration'))

    p = A.get('params')
    D.sub(L('Arsitektur Sistem yang Diusulkan', 'Proposed System Architecture'))
    from . import arch_design as AD
    user_des = cfg.get('arch_design')
    ufig, UA = None, None
    mode = AD.report_mode(user_des)
    ofig = None
    if mode == 'original':
        try:
            ofig = AD.original_figure(user_des)
        except Exception:
            ofig = None
    if ofig is None and mode == 'original':
        mode = 'redrawn' if AD.is_usable(user_des) else None
    if mode == 'redrawn':
        try:
            ls = dict(peak_kw=A.get('peak_kw'), energy_kwh=A.get('load_kwh'))
            UA = AD.analyze(user_des, cfg, ls)
            ufig = AD.figure(user_des, cfg, ls, analysis=UA) \
                if (UA['ok'] or user_des.get('layout') == 'drawing') else None
        except Exception:
            ufig, UA = None, None
    if ofig is not None:
        o = user_des.get('original') or {}
        q = ''                                   # nama berkas sumber tidak dicantumkan
        if o.get('sheet') and o.get('legend_removed') and o.get('colours'):
            D.p(L(f"Arsitektur sistem di bawah ditampilkan dari gambar asli pengguna{q}. "
                  "Yang dimuat hanya diagram pada jendela utama lembar gambar — blok judul, "
                  "label grid, dan legenda gambar tidak disertakan; kode warna garis "
                  "dirangkum ulang pada legenda di bawah gambar.",
                  f"The system architecture below is shown from the user's original "
                  f"drawing{q}. Only the diagram in the sheet's main drawing area is "
                  "included — the title block, grid labels and drawing legend are left out; "
                  "the line colour code is restated in the legend below the figure."),
                keep=True)
        elif o.get('sheet'):
            D.p(L(f"Arsitektur sistem di bawah ditampilkan dari gambar asli pengguna{q}. "
                  "Yang dimuat hanya diagram pada jendela utama lembar gambar; blok judul "
                  "dan label grid tidak disertakan.",
                  f"The system architecture below is shown from the user's original "
                  f"drawing{q}. Only the diagram in the sheet's main drawing area is "
                  "included; the title block and grid labels are left out."), keep=True)
        else:
            D.p(L(f"Arsitektur sistem di bawah ditampilkan dari gambar asli pengguna{q} "
                  "tanpa digambar ulang.",
                  f"The system architecture below is shown from the user's original "
                  f"drawing{q} without redrawing."), keep=True)
        D.figure(ofig, L(f"Arsitektur sistem yang diusulkan — gambar asli pengguna{q}.",
                         f"Proposed system architecture — user's original drawing{q}."),
                 dpi=300)
    elif ufig is not None:
        src = (user_des.get('source') or {})
        origin = (L(" berdasarkan gambar arsitektur pengguna",
                    " based on the user's architecture drawing")
                  if src.get('kind') == 'import' else '')
        if user_des.get('layout') == 'drawing':
            D.p(L(f"Arsitektur di bawah mengikuti topologi rancangan pengguna{origin}. "
                  "Penempatan setiap blok dan rel dipertahankan sesuai gambar; sistem "
                  "menggambar ulang kartu komponen dengan gaya laporan dan merutekan ulang "
                  "seluruh kabel secara ortogonal tanpa saling berimpit. Rating diambil dari "
                  "rancangan atau, bila kosong, dari parameter simulasi.",
                  f"The architecture below follows the user-defined topology{origin}. The "
                  "placement of every block and bus is kept as in the drawing; the system "
                  "redraws the component cards in the report style and re-routes all cables "
                  "orthogonally without overlaps. Ratings come from the design or, where "
                  "blank, from the simulation parameters."), keep=True)
        else:
            D.p(L(f"Arsitektur di bawah mengikuti topologi rancangan pengguna{origin}. Sistem "
                  "membaca komponen dan sambungannya, lalu menggambar ulang dalam format "
                  "diagram satu garis standar laporan: feeder sumber di atas rel AC utama, "
                  "beban di bawahnya, dan EMS dengan jalur kendali. Rating diambil dari "
                  "rancangan atau, bila kosong, dari parameter simulasi.",
                  f"The architecture below follows the user-defined topology{origin}. The "
                  "system reads its components and connections and redraws them in the "
                  "report's standard single-line format: source feeders above the main AC "
                  "bus, loads below it, and the EMS with its control paths. Ratings come from "
                  "the design or, where blank, from the simulation parameters."), keep=True)
        drawn = user_des.get('layout') == 'drawing'
        D.figure(ufig, L('Arsitektur sistem yang diusulkan — topologi rancangan pengguna, '
                         'digambar ulang sesuai standar laporan'
                         + (' (penempatan blok sesuai gambar).' if user_des.get('layout') ==
                            'drawing' else '.'),
                         'Proposed system architecture — user-defined topology, redrawn to '
                         'the report standard'
                         + (' (block placement as in the drawing).' if user_des.get('layout') ==
                            'drawing' else '.')),
                 dpi=300 if drawn else 170)
        # ringkasan feeder & catatan tinjauan topologi hanya untuk editor (tidak
        # dimuat di laporan)
    else:
        D.p(L("Sistem diusulkan sebagai pembangkit hibrida **AC-coupled**: setiap sumber "
              "terhubung ke satu rel AC bersama melalui antarmuka daya dan pemutus masing-"
              "masing — array PV melalui inverter PV, baterai melalui PCS dua arah, genset "
              "melalui panel genset, dan grid melalui titik sambung (PCC) ber-kWh meter. EMS/"
              "pengendali pembangkit membaca kondisi tiap sumber dan menetapkan setpoint daya "
              "setiap langkah waktu sesuai strategi dispatch pada subbab berikutnya.",
              "The system is proposed as an **AC-coupled** hybrid plant: each source connects "
              "to one common AC bus through its own power interface and circuit breaker — the "
              "PV array via the PV inverter, the battery via a bidirectional PCS, the gensets "
              "via the genset panel, and the grid via a metered point of common coupling "
              "(PCC). The EMS / plant controller reads the state of every source and sets the "
              "power setpoints each time step according to the dispatch strategy in the next "
              "subsection."), keep=True)
        D.figure(CH.fig_architecture(M.arch_spec(A, cfg, p)),
                 L('Arsitektur sistem yang diusulkan (diagram blok, AC-coupled). Rating '
                   'sesuai konfigurasi yang dikaji.',
                   'Proposed system architecture (block diagram, AC-coupled). Ratings as per '
                   'the assessed configuration.'))
    D.table([L('Jalur aliran daya', 'Power-flow path'), L('Diizinkan', 'Permitted'),
             L('Kondisi', 'Condition')], M.power_path_rows(A, cfg, p),
            align=['l', 'c', 'l'], widths=[0.30, 0.14, 0.56], font=7.8,
            caption=L('Jalur aliran daya & interlock sesuai parameter dispatch',
                      'Power-flow paths & interlocks per dispatch parameters'))
    D.note(L("Diagram bersifat konseptual untuk tahap studi kelayakan; tegangan rel, "
             "proteksi, pembumian, dan skema komunikasi ditetapkan pada single-line "
             "diagram desain rinci.",
             "The diagram is conceptual for the feasibility stage; bus voltage, "
             "protection, earthing and communication scheme are defined in the "
             "detailed-design single-line diagram."))

    if tech:
        D.sub(L('Strategi Operasi (Dispatch)', 'Operating (Dispatch) Strategy'))
        D.p(L("Setiap langkah waktu, beban dipasok mengikuti rantai prioritas sumber "
              "yang dikonfigurasi, dibatasi kapasitas perangkat (inverter, PCS, genset, "
              "grid), jendela SOC BESS, dan interlock antar-bus. Pengaturan efektif yang "
              "dipakai mesin simulasi pada studi ini:",
              "At every time step, load is supplied following the configured source "
              "priority chain, bounded by device ratings (inverter, PCS, genset, grid), "
              "the BESS SOC window and inter-bus interlocks. Effective settings used by "
              "the simulation engine in this study:"), keep=True)
        D.table([L('Pengaturan', 'Setting'), L('Nilai', 'Value')],
                M.dispatch_rows(A, cfg, p), align=['l', 'l'], widths=[0.55, 0.45],
                caption=L('Parameter strategi dispatch', 'Dispatch strategy parameters'))
        M.advanced_section(D, A, cfg, p)

    D.sub(L('Data Masukan & Dasar Simulasi', 'Input Data & Simulation Basis'))
    rows = [[L('Resolusi simulasi', 'Simulation resolution'), A['interval']],
            [L('Durasi yang disimulasikan', 'Simulated period'),
             f"{_n(A['window_h'])} " + L('jam', 'hours')
             + (L(' (dianualisasi)', ' (annualised)') if A['annualized'] else '')]]
    try:
        if datetimes is not None and len(datetimes):
            import pandas as pd
            t0 = pd.Timestamp(datetimes[0]) + pd.Timedelta(hours=A['start_h'])
            t1 = t0 + pd.Timedelta(hours=A['window_h']) - pd.Timedelta(hours=A['dt'])
            rows.append([L('Periode data', 'Data period'),
                         f"{t0:%d %b %Y %H:%M} – {t1:%d %b %Y %H:%M}"])
    except Exception:
        pass
    rows += [[L('Profil beban', 'Load profile'),
              L('data beban dari pengguna', 'load data supplied by the user')],
             [L('Profil PV', 'PV profile'),
              L('ENetAC (PVsyst) / PVGIS sesuai pilihan', 'ENetAC (PVsyst) / PVGIS as selected')
              + f" — {L('basis', 'base')} {_n(cfg.get('pv_base_annual'),1)} kWp"],
             [L('Status grid', 'Grid status'),
              (f"{_n(A['outage_h'])} " + L('jam padam/thn', 'outage h/yr')) if A['grid_on']
              else L('off-grid', 'off-grid')]]
    D.table([L('Item', 'Item'), L('Keterangan', 'Description')], rows,
            align=['l', 'l'], widths=[0.35, 0.65])


# ---------------------------------------------------------- 3 beban & SD ----
def _load_resource(D, A, cfg, datetimes):
    D.section(L('Kajian Beban & Sumber Daya', 'Load & Resource Assessment'))
    D.p(L("Karakteristik beban dan potensi energi surya menentukan ukuran "
          "optimal PV dan BESS. Ringkasan statistik profil yang disimulasikan:",
          "Load characteristics and solar resource determine the appropriate PV "
          "and BESS sizing. Statistical summary of the simulated profiles:"))
    rows = [[L('Energi beban tahunan', 'Annual load energy'), _n(A['load_kwh']), 'kWh'],
            [L('Beban puncak', 'Peak demand'), _n(A['peak_kw'], 1), 'kW'],
            [L('Beban rata-rata', 'Average demand'), _n(A['avg_kw'], 1), 'kW'],
            [L('Beban minimum', 'Minimum demand'), _n(A['min_kw'], 1), 'kW'],
            [L('Faktor beban', 'Load factor'), _pct(A['load_factor']), '%']]
    if A['has_pv']:
        rows += [[L('Produksi PV tersedia (ENetAC)', 'Available PV energy (ENetAC)'), _n(A['pv_gen']), 'kWh/' + L('thn', 'yr')],
                 [L('Specific yield', 'Specific yield'), _n(A['spec_yield']), 'kWh/kWp·' + L('thn', 'yr')],
                 [L('Faktor kapasitas PV', 'PV capacity factor'), _pct(A['pv_cf']), '%'],
                 [L('Rasio PV terhadap beban puncak', 'PV-to-peak-load ratio'), _n(A['pv_pen'], 2), 'kWp/kW']]
    if A['grid_on']:
        rows += [[L('Jam padam grid', 'Grid outage hours'), _n(A['outage_h']), 'h/' + L('thn', 'yr')],
                 [L('Ketersediaan grid', 'Grid availability'), _pct(A['grid_avail'], 2), '%']]
    D.table([L('Indikator', 'Indicator'), L('Nilai', 'Value'), L('Satuan', 'Unit')],
            rows, align=['l', 'r', 'l'], widths=[0.55, 0.25, 0.20],
            caption=L('Statistik beban & sumber daya', 'Load & resource statistics'))
    D.figure(CH.fig_daily_profile(A['series'], A['dt']),
             L('Profil harian rata-rata beban dan pasokan (rata-rata per jam dalam '
               'sehari selama periode simulasi).',
               'Average daily profile of load and supply (mean for each hour of the '
               'day over the simulated period).'))


# ------------------------------------------------------------ 4 hasil -------
def _start_dt(A, datetimes):
    try:
        import pandas as pd
        if datetimes is not None and len(datetimes):
            return pd.Timestamp(datetimes[0]) + pd.Timedelta(hours=A['start_h'])
    except Exception:
        pass
    return datetime(2025, 1, 1) + timedelta(hours=A['start_h'])


def _simulation_results(D, A, cfg, result, datetimes, multi):
    k = A['kpi']
    D.section(L('Hasil Simulasi Energi', 'Energy Simulation Results'))
    D.sub(L('Neraca Energi Tahunan', 'Annual Energy Balance'))
    load = A['load_kwh'] or 1.0
    rows = [
        [L('Dipasok PV + BESS', 'Supplied by PV + BESS'), _n(A['served_pvbs']), _pct(A['served_pvbs'] / load)],
        [L('Dipasok grid', 'Supplied by grid'), _n(A['served_grid']), _pct(A['served_grid'] / load)],
        [L('Dipasok genset diesel', 'Supplied by diesel genset'), _n(A['served_deg']), _pct(A['served_deg'] / load)],
        [L('Tak terlayani', 'Unserved'), _n(A['uns'], 1), _pct(A['lpsp'], 2)],
        [L('Total beban', 'Total load'), _n(A['load_kwh']), '100.0%'],
    ]
    D.table([L('Pasokan ke beban', 'Supply to load'), 'kWh/' + L('thn', 'yr'), L('Porsi', 'Share')],
            rows, widths=[0.56, 0.24, 0.20], total=True,
            caption=L('Pasokan beban per sumber', 'Load supply by source'))
    D.figure(CH.fig_supply_mix([
        ('PV + BESS', A['served_pvbs'], K.C['pv']), ('Grid', A['served_grid'], K.C['grid']),
        ('Diesel', A['served_deg'], K.C['deg']),
        (L('Tak terlayani', 'Unserved'), A['uns'], K.C['uns'])]),
        L('Bauran pasokan beban tahunan.', 'Annual load supply mix.'))

    flows = [[L('Energi PV tersedia (ENetAC)', 'Available PV energy (ENetAC)'), _n(A['pv_gen'])],
             [L('Keluaran inverter PV', 'PV inverter output'), _n(k.get('annual_pv_inverter_out_kwh'))],
             [L('Curtailment / energi PV tak terpakai', 'Curtailment / unused PV energy'), _n(k.get('pv_excess_kwh'))]]
    if A['has_bess']:
        flows += [[L('Pengisian BESS — dari PV', 'BESS charging — from PV'), _n(k.get('pv_charge_kwh'))],
                  [L('Pengisian BESS — dari grid', 'BESS charging — from grid'), _n(k.get('grid_charge_kwh'))],
                  [L('Pengisian BESS — dari genset', 'BESS charging — from genset'), _n(k.get('deg_charge_kwh'))],
                  [L('Discharge BESS', 'BESS discharge'), _n(A['bess_dis'])],
                  [L('Rugi-rugi BESS (charge − discharge)', 'BESS losses (charge − discharge)'),
                   _n(A['bess_chg'] - A['bess_dis'])]]
    if A['grid_on']:
        flows += [[L('Impor grid (total)', 'Grid import (total)'), _n(A['grid_imp'])],
                  [L('Ekspor grid', 'Grid export'), _n(A['grid_exp'])]]
    if A['has_deg']:
        flows += [[L('Produksi genset diesel', 'Diesel genset generation'), _n(A['deg_kwh'])]]
    D.table([L('Aliran energi', 'Energy flow'), 'kWh/' + L('thn', 'yr')], flows,
            widths=[0.70, 0.30], caption=L('Aliran energi komponen', 'Component energy flows'))

    ms = CH.monthly_supply(A['series'], _start_dt(A, datetimes), A['dt'])
    if ms and len(ms.get('months', [])) >= 2:
        D.sub(L('Pasokan Energi Bulanan', 'Monthly Energy Supply'))
        D.figure(CH.fig_monthly_supply(ms),
                 L('Energi yang dipasok ke beban per sumber per bulan.',
                   'Energy supplied to the load by source for each month.'))

    D.sub(L('Profil Operasi', 'Operating Profile'))
    D.figure(CH.fig_week_profile(A['series'], A['dt']),
             L('Profil operasi 7 hari pertama: daya per sumber (atas) dan SOC BESS '
               '(bawah). BESS positif = discharge, negatif = charge.',
               'Operating profile, first 7 days: power by source (top) and BESS SOC '
               '(bottom). BESS positive = discharge, negative = charge.'))

    D.sub(L('Kinerja Komponen', 'Component Performance'))
    rows, groups = [], []

    def grp(name):
        groups.append(len(rows)); rows.append([name, '', ''])
    if A['has_pv']:
        grp('PV')
        rows += [[L('Specific yield', 'Specific yield'), _n(A['spec_yield']), 'kWh/kWp·' + L('thn', 'yr')],
                 [L('Faktor kapasitas', 'Capacity factor'), _pct(A['pv_cf']), '%'],
                 [L('Rasio curtailment', 'Curtailment ratio'), _pct(k.get('pv_excess_ratio')), '%']]
    if A['has_bess']:
        grp('BESS')
        rows += [[L('Throughput tahunan', 'Annual throughput'), _n(k.get('battery_throughput_kwh')), 'kWh'],
                 [L('Siklus penuh ekivalen', 'Equivalent full cycles'), _n(A['cycles'], 1), L('siklus/thn', 'cycles/yr')],
                 [L('Efisiensi efektif (discharge/charge)', 'Effective efficiency (discharge/charge)'), _pct(A['bess_eff']), '%'],
                 [L('SOC minimum / maksimum teramati', 'Observed SOC min / max'),
                  f"{_pct(k.get('soc_min'))} / {_pct(k.get('soc_max'))}", '%']]
    if A['has_deg']:
        grp(L('Genset diesel', 'Diesel genset'))
        rows += [[L('Jam operasi', 'Running hours'), _n(k.get('diesel_runtime_h')), 'h/' + L('thn', 'yr')],
                 [L('Konsumsi bahan bakar', 'Fuel consumption'), _n(A['fuel_l']), 'L/' + L('thn', 'yr')],
                 [L('Konsumsi spesifik (SFC)', 'Specific fuel consumption (SFC)'), _n(A['sfc'], 3), 'L/kWh'],
                 [L('Loading rata-rata', 'Average loading'), _pct(k.get('diesel_avg_loading')), '%']]
    if A['grid_on']:
        grp('Grid')
        rows += [[L('Porsi beban dari grid', 'Share of load from grid'), _pct(A['served_grid'] / load), '%'],
                 [L('Ketersediaan grid', 'Grid availability'), _pct(A['grid_avail'], 2), '%']]
    grp(L('Keandalan pasokan', 'Supply reliability'))
    rows += [[L('Energi tak terlayani', 'Unserved energy'), _n(A['uns'], 1), 'kWh/' + L('thn', 'yr')],
             [L('LPSP (loss of power supply probability)', 'LPSP (loss of power supply probability)'), _pct(A['lpsp'], 3), '%'],
             [L('Rasio pasokan', 'Supply ratio'), _pct(k.get('supply_ratio'), 2), '%']]
    D.table([L('Indikator', 'Indicator'), L('Nilai', 'Value'), L('Satuan', 'Unit')], rows,
            align=['l', 'r', 'l'], widths=[0.55, 0.25, 0.20], group_rows=groups,
            caption=L('Indikator kinerja komponen tahun-1', 'Year-1 component performance indicators'))

    M.advanced_results(D, A, cfg, A.get('params'))

    heats = [('soc', 'Purples', L('SOC BESS (fraksi)', 'BESS SOC (fraction)'), 'SOC'),
             ('deg', 'Reds', L('pembebanan genset (kW)', 'genset loading (kW)'), 'kW'),
             ('grid', 'Blues', L('impor grid (kW)', 'grid import (kW)'), 'kW'),
             ('pv_excess', 'YlOrBr', L('curtailment PV (kW)', 'PV curtailment (kW)'), 'kW')]
    figs = [(CH.fig_heat(A['series'], key, cm, A['dt'], unit), lab)
            for key, cm, lab, unit in heats]
    figs = [(f, lab) for f, lab in figs if f is not None]
    if figs:
        D.sub(L('Peta Panas Operasi', 'Operational Heatmaps'))
        D.note(L('Sumbu horizontal = hari dalam periode simulasi, sumbu vertikal = '
                 'jam dalam sehari. Deret yang seluruhnya nol tidak ditampilkan.',
                 'Horizontal axis = day of the simulated period, vertical axis = hour '
                 'of day. Series that are zero throughout are omitted.'), keep=True)
        for f, lab in figs:
            D.figure(f, L(f'Peta panas {lab}.', f'Heatmap of {lab}.'))

    ca = K.case_analysis(result, cfg)
    if ca:
        D.sub(L('Analisis Mode Operasi', 'Operating Mode Analysis'))
        total = ca['total_h'] or 1.0
        D.p(L("Setiap langkah waktu digolongkan ke salah satu dari 32 mode menurut status grid, "
              "ketersediaan PV, keadaan BESS, dan status genset. Tabel berikut "
              f"merangkum mode yang terjadi (sisa {_n(total - ca['marked_h'])} jam: "
              "BESS idle dengan energi cukup).",
              "Each time step is classified into one of 32 modes by grid status, PV "
              "availability, BESS state and genset status. The table summarises the "
              f"modes that occur (remaining {_n(total - ca['marked_h'])} h: BESS idle "
              "with sufficient energy)."), keep=True)
        crow = [[f'C{c}', K.case_desc(c), _n(h), _pct(h / total)] for c, h in ca['rows']]
        D.table([L('Mode', 'Mode'), L('Deskripsi', 'Description'), L('Jam', 'Hours'),
                 L('% periode', '% period')], crow, align=['c', 'l', 'r', 'r'],
                widths=[0.10, 0.58, 0.14, 0.18], font=7.5,
                caption=L('Durasi mode operasi', 'Operating mode durations'))
        D.figure(K.fig_case_hours(ca['rows']),
                 L('Durasi tiap mode operasi (jam per periode).',
                   'Duration of each operating mode (hours per period).'))

    if multi and multi.get('kpi') is not None:
        mk = multi['kpi']
        yrs = list(np.asarray(multi.get('years', []), int))
        if yrs:
            D.sub(L('Kinerja Teknis Jangka Panjang', 'Long-Term Technical Performance'))
            D.p(L("Proyeksi per tahun memperhitungkan degradasi PV, penurunan SOH BESS "
                  "dan penggantian BESS (★) sesuai batas umur/SOH.",
                  "The yearly projection accounts for PV degradation, BESS SOH decline "
                  "and BESS replacement (★) per the lifetime/SOH limits."), keep=True)
            soh = _arr(multi, 'bess_soh')
            rep = np.asarray(multi.get('bess_replaced', np.zeros(len(yrs))), bool).reshape(-1)
            pvg, rf = _arr(mk, 'annual_pv_generation_kwh'), _arr(mk, 'renewable_fraction')
            cyc, fuel, gi = _arr(mk, 'battery_cycles'), _arr(mk, 'diesel_fuel_l'), _arr(mk, 'grid_import_kwh')
            bk = _arr(multi, 'bess_kwh_eff')
            g = lambda a, i: a[i] if i < len(a) else float('nan')
            rows = []
            for i, y in enumerate(yrs):
                rows.append([f"{y}{' ★' if i < len(rep) and rep[i] else ''}",
                             _n(g(pvg, i) / 1000, 1), _pct(g(rf, i)), _pct(g(soh, i), 0),
                             _n(g(bk, i), 0), _n(g(cyc, i), 1), _n(g(fuel, i)),
                             _n(g(gi, i) / 1000, 1)])
            D.table([L('Thn', 'Yr'), 'PV (MWh)', 'RF', 'SOH', 'BESS (kWh)', 'EFC',
                     L('Solar (L)', 'Fuel (L)'), 'Grid (MWh)'], rows,
                    align=['c'] + ['r'] * 7,
                    widths=[0.08, 0.13, 0.11, 0.10, 0.14, 0.10, 0.17, 0.17], font=7.5,
                    caption=L('Proyeksi kinerja teknis per tahun', 'Yearly technical performance projection'))


# ---------------------------------------------------------- 5 lingkungan ----
def _environment(D, A, cfg, multi):
    D.section(L('Dampak Lingkungan', 'Environmental Impact'))
    D.p(L(f"Emisi CO₂ operasional dihitung dari konsumsi solar "
          f"({EF_DIESEL_KG_PER_L:.2f} kgCO₂/L) dan impor grid "
          f"({A['ef_grid']:.2f} kgCO₂/kWh), dibandingkan terhadap baseline "
          f"{_baseline_txt(A)}.",
          f"Operational CO₂ emissions are computed from diesel consumption "
          f"({EF_DIESEL_KG_PER_L:.2f} kgCO₂/L) and grid imports "
          f"({A['ef_grid']:.2f} kgCO₂/kWh), compared against the {_baseline_txt(A)} "
          f"baseline."))
    rows = [[L('Konsumsi solar', 'Diesel consumption'), _n(A['base_fuel']), _n(A['fuel_l']), 'L/' + L('thn', 'yr')],
            [L('Energi dari grid', 'Energy from grid'), _n(A['base_grid']), _n(A['grid_imp']), 'kWh/' + L('thn', 'yr')],
            [L('Emisi CO₂', 'CO₂ emissions'), _n(A['co2_base'], 1), _n(A['co2_proj'], 1), 't/' + L('thn', 'yr')]]
    D.table([L('Parameter', 'Parameter'), 'Baseline', L('Proyek', 'Project'), L('Satuan', 'Unit')],
            rows, align=['l', 'r', 'r', 'l'], widths=[0.40, 0.21, 0.21, 0.18],
            caption=L('Perbandingan emisi operasional', 'Operational emissions comparison'))
    red = A['co2_avoid'] / A['co2_base'] if A['co2_base'] > 0 else float('nan')
    tiles = [(L('CO₂ dihindari', 'CO₂ avoided'), f"{_n(A['co2_avoid'],1)} t/" + L('thn', 'yr'),
              L('vs baseline', 'vs baseline')),
             (L('Pengurangan emisi', 'Emission reduction'), _pct(red), L('vs baseline', 'vs baseline')),
             (L('Solar dihemat', 'Diesel saved'), f"{_n(A['base_fuel'] - A['fuel_l'])} L/" + L('thn', 'yr'), '')]
    if multi:
        tiles.append((L('CO₂ dihindari (umur proyek)', 'CO₂ avoided (project life)'),
                      f"{_n(A['co2_avoid'] * A['years'])} t",
                      L(f"≈ {A['years']} × nilai tahun-1", f"≈ {A['years']} × year-1 value")))
    D.kpis(tiles, cols=len(tiles))
    D.note(L("Faktor emisi grid adalah asumsi indikatif; gunakan faktor emisi resmi "
             "jaringan setempat untuk pelaporan karbon. Emisi siklus hidup peralatan "
             "tidak termasuk.",
             "The grid emission factor is an indicative assumption; use the official "
             "factor of the local grid for carbon reporting. Equipment life-cycle "
             "emissions are excluded."))


def _baseline_txt(A):
    return (L('diesel penuh (seluruh beban dari genset)', 'diesel-only (all load from gensets)')
            if A['baseline_mode'] == 'diesel_only'
            else L('grid + diesel eksisting', 'existing grid + diesel'))


# ---------------------------------------------------------- 6 finansial -----
def _financial(D, A, cfg):
    h = A['head']
    cc = A['cc']
    D.section(L('Analisis Finansial', 'Financial Analysis'))
    D.p(L(f"Kelayakan dinilai dengan metode arus kas terdiskonto (DCF) atas "
          f"penghematan biaya energi terhadap baseline {_baseline_txt(A)}. "
          + ("Indikator utama berasal dari model umur proyek terperinci (Multi-Year) "
             "yang memperhitungkan degradasi & penggantian BESS."
             if A['lifetime'] else
             "Indikator berasal dari proyeksi berbasis tahun-1 (jalankan Multi-Year "
             "untuk model umur proyek terperinci)."),
          f"Feasibility is assessed with the discounted cash flow (DCF) method on "
          f"energy-cost savings against the {_baseline_txt(A)} baseline. "
          + ("Headline indicators come from the detailed project-lifetime "
             "(Multi-Year) model, including degradation and BESS replacement."
             if A['lifetime'] else
             "Indicators come from a year-1-based projection (run Multi-Year for "
             "the detailed lifetime model).")))

    D.sub(L('Asumsi Finansial', 'Financial Assumptions'))
    rows = [[L('Umur proyek', 'Project lifetime'), f"{A['years']} " + L('tahun', 'years')],
            [L('Discount rate', 'Discount rate'), _pct(A['disc'])],
            [L('Inflasi / eskalasi harga energi', 'Inflation / energy price escalation'), _pct(A['infl'])],
            [L('Degradasi PV', 'PV degradation'), _pct(cfg.get('pv_degradation'), 2) + '/' + L('thn', 'yr')]]
    if A['has_bess']:
        from ..config.parameters import soh_curve_active, parse_soh_curve
        if soh_curve_active(cfg):
            _cv = parse_soh_curve(cfg.get('bess_soh_curve'))
            rows += [[L('Degradasi BESS', 'BESS degradation'),
                      L('Kurva SOH per tahun', 'Annual SOH curve') +
                      f" ({_cv[0][0]:g}–{_cv[-1][0]:g}: {_pct(_cv[0][1], 1)} → {_pct(_cv[-1][1], 1)})"]]
        else:
            rows += [[L('Degradasi BESS', 'BESS degradation'), _pct(cfg.get('bess_degradation'), 2) + '/' + L('thn', 'yr')]]
        rows += [
                 [L('Umur BESS / ambang SOH penggantian', 'BESS life / replacement SOH threshold'),
                  f"{_n(cfg.get('bess_lifetime_y'))} " + L('thn', 'yr') + f" / {_pct(cfg.get('bess_soh_threshold'),0)}"]]
    rows += [[L('Harga solar', 'Diesel price'), f"{_rp(cc.get('diesel_price_per_l'))}/L"],
             [L('Laju bahan bakar baseline', 'Baseline fuel rate'), f"{A['fuel_rate_eff']:.3f} L/kWh"]]
    if A['grid_on']:
        rows.append([L('Tarif grid', 'Grid tariff'), f"{_rp(cc.get('grid_tariff_per_kwh'))}/kWh"])
        tou = (_f(A['kpi'].get('grid_import_peak_kwh')) + _f(A['kpi'].get('grid_import_offpeak_kwh'))) > 0
        if tou and cc.get('tariff_offpeak_per_kwh') not in (None, ''):
            rows.append([L('Tarif luar-puncak', 'Off-peak tariff'), f"{_rp(cc.get('tariff_offpeak_per_kwh'))}/kWh"])
        if cfg.get('allow_export'):
            rows.append([L('Tarif ekspor', 'Export tariff'), f"{_rp(cc.get('export_tariff_per_kwh'))}/kWh"])
    rows += [[L('Biaya O&M', 'O&M cost'), _pct(cc.get('om_fraction'), 1) + ' CAPEX/' + L('thn', 'yr')],
             [L('Baseline pembanding', 'Comparison baseline'), _baseline_txt(A)],
             [L('Cakupan analisis (LCOE/CAPEX/OPEX)', 'Analysis scope (LCOE/CAPEX/OPEX)'), A['scope']]]
    D.table([L('Asumsi', 'Assumption'), L('Nilai', 'Value')], rows, align=['l', 'r'],
            widths=[0.58, 0.42], caption=L('Asumsi finansial dasar', 'Base financial assumptions'))

    D.sub(L('Belanja Modal (CAPEX)', 'Capital Expenditure (CAPEX)'))
    items = [(lab, q, un, u) for lab, q, un, u in A['capex_items'] if q * u > 0]
    tot = sum(q * u for _l, q, _u, u in items) or 1.0
    rows = [[lab, _n(q, 1) if un != L('lot', 'lot') else '1', un, _n(u), _mn(q * u), _pct(q * u / tot)]
            for lab, q, un, u in items]
    rows.append([L('Total CAPEX', 'Total CAPEX'), '', '', '', _mn(tot), '100.0%'])
    D.table([L('Komponen', 'Component'), L('Kuantitas', 'Quantity'), L('Satuan', 'Unit'),
             L('Harga satuan (Rp)', 'Unit cost (Rp)'), L('Biaya (Rp juta)', 'Cost (Rp million)'),
             L('Porsi', 'Share')], rows, align=['l', 'r', 'l', 'r', 'r', 'r'],
            widths=[0.26, 0.12, 0.09, 0.19, 0.19, 0.15], total=True,
            caption=L('Rincian CAPEX seluruh sistem', 'Total system CAPEX breakdown'))
    if A['sizes']['kwp'] > 0:
        D.note(L(f"CAPEX spesifik: {_rp(tot / A['sizes']['kwp'])}/kWp PV terpasang.",
                 f"Specific CAPEX: {_rp(tot / A['sizes']['kwp'])}/kWp of installed PV."))
    if A['scope'] != 'PV-BESS-DEG':
        D.note(L(f"Cakupan analisis '{A['scope']}': CAPEX/LCOE headline dibatasi pada "
                 f"komponen tersebut ({_rp(h.get('capex'))}); NPV/IRR/payback tetap "
                 "dihitung untuk seluruh sistem.",
                 f"Analysis scope '{A['scope']}': headline CAPEX/LCOE are limited to "
                 f"those components ({_rp(h.get('capex'))}); NPV/IRR/payback remain "
                 "whole-system."))
    D.figure(CH.fig_capex([(lab, q * u) for lab, q, _un, u in items]),
             L('Komposisi CAPEX per komponen.', 'CAPEX composition by component.'))

    D.sub(L('Biaya Operasi & Perbandingan Baseline', 'Operating Cost & Baseline Comparison'))
    rows = []
    if A['opex_parts']:
        rows += [[lab, _mn(v)] for lab, v in A['opex_parts']]
    rows += [[L('OPEX proyek tahun-1', 'Project OPEX, year 1'), _mn(A['opex1_full'])],
             [L('Biaya energi baseline tahun-1', 'Baseline energy cost, year 1'), _mn(A['base1'])],
             [L('Penghematan tahun-1', 'Savings, year 1'), _mn(A['sav1'])]]
    n_parts = len(A['opex_parts'] or [])
    D.table([L('Komponen biaya tahun-1', 'Year-1 cost item'), L('Rp juta', 'Rp million')],
            rows, widths=[0.68, 0.32], group_rows=[],
            tones={(n_parts + 2, 1): 'good'} if A['sav1'] > 0 else {},
            caption=L('Biaya operasi tahun-1 vs baseline', 'Year-1 operating cost vs baseline'))
    D.p(L(f"Biaya energi baseline setara **{_rp(A['base_unit'])}/kWh**, sedangkan LCOE "
          f"proyek **{_rp(h.get('lcoe'))}/kWh**" + (f" dan tarif grid {_rp(cc.get('grid_tariff_per_kwh'))}/kWh."
                                                 if A['grid_on'] else '.'),
          f"The baseline cost of energy is equivalent to **{_rp(A['base_unit'])}/kWh**, "
          f"versus a project LCOE of **{_rp(h.get('lcoe'))}/kWh**"
          + (f" and a grid tariff of {_rp(cc.get('grid_tariff_per_kwh'))}/kWh."
             if A['grid_on'] else '.')))
    if len(A['cf_years']):
        D.figure(CH.fig_cost_compare(A['cf_years'], A['base_y'], A['opex_y'], A['repl_y']),
                 L('Biaya energi tahunan: baseline vs proyek (nominal, tereskalasi inflasi).',
                   'Annual energy cost: baseline vs project (nominal, inflation-escalated).'))

    D.sub(L('Arus Kas Proyek', 'Project Cash Flow'))
    D.figure(CH.fig_cashflow(A['flows'], _f(h.get('payback_years'), float('nan'))),
             L('Arus kas bersih tahunan dan kumulatif (tahun 0 = CAPEX).',
               'Annual and cumulative net cash flow (year 0 = CAPEX).'))
    rows = []
    for y in range(len(A['flows'])):
        if y == 0:
            rows.append(['0', '-', '-', '-', _mn(A['flows'][0]), _mn(A['disc_flows'][0]),
                         _mn(A['cum'][0])])
            continue
        i = y - 1
        g = lambda a: a[i] if i < len(a) else float('nan')
        rows.append([str(y), _mn(g(A['base_y'])), _mn(g(A['opex_y'])), _mn(g(A['repl_y']))
                     if g(A['repl_y']) else '-', _mn(A['flows'][y]), _mn(A['disc_flows'][y]),
                     _mn(A['cum'][y])])
    rows.append([L('Total', 'Total'), _mn(np.sum(A['base_y'])), _mn(np.sum(A['opex_y'])),
                 _mn(np.sum(A['repl_y'])), _mn(np.sum(A['flows'])),
                 _mn(np.sum(A['disc_flows'])), ''])
    D.table([L('Thn', 'Yr'), L('Biaya baseline', 'Baseline cost'), L('OPEX proyek', 'Project OPEX'),
             L('Ganti BESS', 'BESS repl.'), L('Arus kas bersih', 'Net cash flow'),
             L('Terdiskonto', 'Discounted'), L('Kumulatif', 'Cumulative')], rows,
            align=['c'] + ['r'] * 6, widths=[0.07, 0.155, 0.155, 0.13, 0.165, 0.16, 0.165],
            total=True, font=7.3,
            caption=L('Arus kas proyek (Rp juta, nominal)', 'Project cash flow (Rp million, nominal)'))

    D.sub(L('Indikator Finansial', 'Financial Indicators'))
    suf = ' (lifetime)' if A['lifetime'] else ''
    rows = [['CAPEX', _rp(h.get('capex'))],
            ['NPV' + suf, _rp(h.get('npv'))],
            ['IRR' + suf, _pct(h.get('irr'))],
            ['ROI' + suf, _pct(h.get('roi'))],
            [L('Payback sederhana', 'Simple payback') + suf, f"{_n(h.get('payback_years'),1)} " + L('tahun', 'years')],
            [L('Payback terdiskonto', 'Discounted payback'), f"{_n(A['dpb'],1)} " + L('tahun', 'years')],
            ['LCOE' + suf, f"{_rp(h.get('lcoe'))}/kWh"],
            [L('Biaya energi baseline', 'Baseline cost of energy'), f"{_rp(A['base_unit'])}/kWh"]]
    D.table([L('Indikator', 'Indicator'), L('Nilai', 'Value')], rows, align=['l', 'r'],
            widths=[0.58, 0.42], caption=L('Ringkasan indikator finansial', 'Financial indicator summary'))


# ---------------------------------------------------------- 7 sensitivitas --
def _sensitivity(D, A, cfg):
    try:
        scen = K.sensitivity(A['kpi'], cfg, A['sizes'])
    except Exception:
        return
    if not scen:
        return
    D.section(L('Analisis Sensitivitas', 'Sensitivity Analysis'), pagebreak=False)
    D.p(L("Sensitivitas diuji terhadap discount rate (±2 poin), harga solar (±15%) dan "
          "CAPEX (±10%). Hanya lapisan finansial yang dihitung ulang (hasil energi "
          "tetap) menggunakan proyeksi berbasis tahun-1, sehingga perubahan dinyatakan "
          "relatif terhadap kasus dasar proyeksi yang sama.",
          "Sensitivity is tested for the discount rate (±2 pts), diesel price (±15%) and "
          "CAPEX (±10%). Only the financial layer is recomputed (energy results fixed) "
          "using the year-1-based projection, so changes are expressed relative to the "
          "base case of that same projection."))
    base = scen[0][1]
    bnpv = _f(base.get('npv'), float('nan'))

    def dn(f):
        v = _f(f.get('npv'), float('nan'))
        return (v - bnpv) / abs(bnpv) if bnpv == bnpv and bnpv != 0 and v == v else float('nan')
    rows = []
    for name, f, is_b in scen:
        rows.append([f'**{name}**' if is_b else name, _mn(f.get('npv')),
                     '—' if is_b else f"{dn(f)*100:+.1f}%", _pct(f.get('irr')),
                     _n(f.get('payback_years'), 1), _n(f.get('lcoe'))])
    D.table([L('Skenario', 'Scenario'), L('NPV (Rp juta)', 'NPV (Rp million)'), 'Δ NPV',
             'IRR', L('Payback (thn)', 'Payback (yr)'), 'LCOE (Rp/kWh)'], rows,
            align=['l', 'r', 'r', 'r', 'r', 'r'], widths=[0.28, 0.17, 0.12, 0.12, 0.14, 0.17],
            caption=L('Hasil analisis sensitivitas', 'Sensitivity analysis results'))
    pairs = [(L('Discount rate ±2 poin', 'Discount rate ±2 pts'), 1, 2, '−2', '+2'),
             (L('Harga solar ±15%', 'Diesel price ±15%'), 3, 4, '−15%', '+15%'),
             ('CAPEX ±10%', 5, 6, '−10%', '+10%')]
    trows = []
    for lab, a, b, la, lb in pairs:
        if b < len(scen):
            trows.append((lab, _f(scen[a][1].get('npv'), float('nan')),
                          _f(scen[b][1].get('npv'), float('nan')), la, lb))
    D.figure(CH.fig_tornado(bnpv, trows),
             L('Diagram tornado: perubahan NPV terhadap kasus dasar untuk tiap variabel.',
               'Tornado diagram: NPV change vs base case for each variable.'))
    neg = [name for name, f, _b in scen if _f(f.get('npv'), 1.0) <= 0]
    if trows:
        big = max(trows, key=lambda r: abs(r[2] - r[1]))[0]
        D.p(L(f"Variabel paling berpengaruh: **{big}**. " + (
            "NPV tetap positif pada seluruh skenario yang diuji." if not neg else
            f"NPV menjadi negatif pada: {', '.join(neg)}."),
            f"Most influential variable: **{big}**. " + (
            "NPV remains positive in all tested scenarios." if not neg else
            f"NPV turns negative for: {', '.join(neg)}.")))


# ---------------------------------------------------------- 8 risiko --------
def _risks(D, A, cfg, tech, finx):
    D.section(L('Kajian Risiko & Mitigasi', 'Risk Assessment & Mitigation'))
    k = A['kpi']
    R = []
    R.append((L('Kualitas data beban & iradiasi', 'Load & irradiance data quality'),
              L('Ukuran sistem & penghematan menyimpang dari kenyataan',
                'Sizing and savings deviate from reality'),
              L('Validasi dengan data terukur ≥ 12 bulan; gunakan data P50/P90',
                'Validate against ≥ 12 months of measured data; use P50/P90 data')))
    if A['has_bess']:
        R.append((L('Degradasi & penggantian BESS', 'BESS degradation & replacement'),
                  L('Kapasitas turun; biaya penggantian di tengah umur proyek',
                    'Capacity fade; mid-life replacement cost'),
                  L('Jaminan kinerja & siklus dari pabrikan; strategi SOC konservatif',
                    'Manufacturer performance & cycle warranty; conservative SOC strategy')))
    if tech and A['has_pv'] and _f(k.get('pv_excess_ratio')) > 0.15:
        R.append((L('Curtailment PV tinggi', 'High PV curtailment'),
                  L('Energi terbarukan terbuang; nilai investasi PV berkurang',
                    'Renewable energy wasted; lower PV investment value'),
                  L('Tinjau rasio PV/BESS, strategi dispatch, atau izin ekspor',
                    'Review PV/BESS ratio, dispatch strategy, or export permission')))
    if tech and A['has_deg'] and _f(k.get('diesel_runtime_h')) > 0 and _f(k.get('diesel_avg_loading')) < 0.3:
        R.append((L('Loading genset rendah', 'Low genset loading'),
                  L('Wet-stacking, efisiensi bahan bakar rendah, perawatan meningkat',
                    'Wet-stacking, low fuel efficiency, higher maintenance'),
                  L('Atur loading minimum genset; manfaatkan pengisian BESS dari genset',
                    'Set minimum genset loading; allow BESS charging from genset')))
    if A['grid_on']:
        R.append((L('Keandalan & regulasi grid', 'Grid reliability & regulation'),
                  L('Padam lebih sering; perubahan tarif atau aturan interkoneksi',
                    'More frequent outages; tariff or interconnection rule changes'),
                  L('Kajian interkoneksi & proteksi; skenario tarif dalam sensitivitas',
                    'Interconnection & protection study; tariff scenarios in sensitivity')))
    if finx:
        R.append((L('Kenaikan harga peralatan / EPC', 'Equipment / EPC price escalation'),
                  L('CAPEX lebih tinggi, NPV & IRR turun', 'Higher CAPEX, lower NPV & IRR'),
                  L('Penawaran vendor yang mengikat; kontingensi 5–10%',
                    'Binding vendor quotations; 5–10% contingency')))
        R.append((L('Volatilitas harga bahan bakar', 'Fuel price volatility'),
                  L('Nilai penghematan berubah', 'Savings value changes'),
                  L('Lihat analisis sensitivitas; pertimbangkan kontrak pasokan',
                    'See sensitivity analysis; consider supply contracts')))
        R.append((L('Pembiayaan & suku bunga', 'Financing & interest rates'),
                  L('Discount rate/WACC lebih tinggi menurunkan NPV',
                    'Higher discount rate/WACC lowers NPV'),
                  L('Kaji skema pembiayaan hijau & insentif', 'Assess green financing schemes & incentives')))
    R.append((L('Perizinan & lahan', 'Permitting & land'),
              L('Keterlambatan jadwal proyek', 'Project schedule delay'),
              L('Identifikasi izin sejak awal; survei lokasi', 'Identify permits early; site survey')))
    D.table([L('Risiko', 'Risk'), L('Dampak', 'Impact'), L('Mitigasi', 'Mitigation')],
            [list(r) for r in R], align=['l', 'l', 'l'], widths=[0.27, 0.33, 0.40], font=8,
            caption=L('Daftar risiko utama & mitigasi', 'Key risk register & mitigation'))


# ---------------------------------------------------------- 9 kesimpulan ----
def _conclusions(D, A, cfg, proj, tech, finx):
    D.section(L('Kesimpulan & Rekomendasi', 'Conclusions & Recommendations'), pagebreak=False)
    D.sub(L('Kesimpulan', 'Conclusions'))
    k = A['kpi']
    items = []
    if tech:
        items.append(L(f"Secara teknis, konfigurasi mencapai fraksi terbarukan {_pct(A['rf'])} "
                       f"dengan energi tak terlayani {_n(A['uns'],1)} kWh/thn dan curtailment "
                       f"{_pct(k.get('pv_excess_ratio'))}.",
                       f"Technically, the configuration achieves a {_pct(A['rf'])} renewable "
                       f"fraction with {_n(A['uns'],1)} kWh/yr unserved energy and "
                       f"{_pct(k.get('pv_excess_ratio'))} curtailment."))
        if A['co2_avoid'] > 0:
            items.append(L(f"Emisi CO₂ operasional berkurang sekitar {_n(A['co2_avoid'],1)} t/thn "
                           "dibanding baseline (indikatif).",
                           f"Operational CO₂ emissions fall by about {_n(A['co2_avoid'],1)} t/yr "
                           "versus the baseline (indicative)."))
    if finx:
        h = A['head']
        if A['feasible']:
            items.append(L(f"Secara finansial proyek **layak**: NPV {_ms(h.get('npv'))}, IRR "
                           f"{_pct(h.get('irr'))} (> discount rate {_pct(A['disc'])}), payback "
                           f"{_n(h.get('payback_years'),1)} tahun dari umur {A['years']} tahun.",
                           f"Financially the project is **feasible**: NPV {_ms(h.get('npv'))}, IRR "
                           f"{_pct(h.get('irr'))} (> {_pct(A['disc'])} discount rate), payback "
                           f"{_n(h.get('payback_years'),1)} years of a {A['years']}-year life."))
        else:
            items.append(L(f"Secara finansial kelayakan **marginal** (NPV {_ms(h.get('npv'))}, "
                           f"payback {_n(h.get('payback_years'),1)} thn) pada asumsi saat ini.",
                           f"Financially, feasibility is **marginal** (NPV {_ms(h.get('npv'))}, "
                           f"payback {_n(h.get('payback_years'),1)} yr) under current assumptions."))
    D.bullets(items)
    D.sub(L('Rekomendasi & Langkah Berikutnya', 'Recommendations & Next Steps'))
    rec = [L("Verifikasi profil beban dan iradiasi dengan data terukur (min. 12 bulan).",
             "Verify load and irradiance profiles against measured data (min. 12 months).")]
    if tech and (_f(k.get('pv_excess_ratio')) > 0.15 or (A['has_bess'] and A['cycles'] < 50)):
        rec.append(L("Jalankan optimasi ukuran (halaman Optimization) untuk menyeimbangkan "
                     "rasio PV/BESS dan menurunkan curtailment.",
                     "Run sizing optimisation (Optimization page) to rebalance the PV/BESS "
                     "ratio and reduce curtailment."))
    if finx:
        rec.append(L("Konfirmasi harga peralatan & EPC melalui penawaran vendor dan tambahkan "
                     "kontingensi.", "Confirm equipment & EPC prices with vendor quotations "
                     "and add contingency."))
        rec.append(L("Kaji skema pembiayaan, pajak, dan insentif energi terbarukan yang berlaku.",
                     "Assess financing, taxation and applicable renewable-energy incentives."))
    if A['grid_on']:
        rec.append(L("Lakukan kajian interkoneksi grid (load flow, hubung singkat, proteksi).",
                     "Carry out a grid interconnection study (load flow, short circuit, protection)."))
    rec.append(L("Lanjutkan ke desain rinci (tata letak, single-line diagram, spesifikasi "
                 "teknis) dan survei lokasi.",
                 "Proceed to detailed design (layout, single-line diagram, technical "
                 "specifications) and a site survey."))
    D.add(t='numbered', items=rec)


# ---------------------------------------------------------- lampiran --------
def _appendices(D, A, cfg, tech, finx):
    M.methodology(D, A, cfg, A.get('params'), tech, finx)
    if tech:
        D.sub(L('Indikator Turunan pada Laporan', 'Derived Indicators in this Report'))
        D.bullets([
            L('Specific yield = energi PV tersedia / kWp; faktor kapasitas = energi PV / (kWp × 8.760 jam).',
              'Specific yield = available PV energy / kWp; capacity factor = PV energy / (kWp × 8,760 h).'),
            L('LPSP = energi tak terlayani / energi beban; faktor beban = beban rata-rata / beban puncak.',
              'LPSP = unserved energy / load energy; load factor = average demand / peak demand.'),
            L('Efisiensi efektif BESS = discharge / charge tahunan (termasuk perubahan SOC awal–akhir).',
              'Effective BESS efficiency = annual discharge / charge (includes start–end SOC change).'),
            L(f'Emisi CO₂ = solar × {EF_DIESEL_KG_PER_L:.2f} kg/L + impor grid × faktor emisi grid.',
              f'CO₂ emissions = diesel × {EF_DIESEL_KG_PER_L:.2f} kg/L + grid import × grid emission factor.'),
        ])
    if finx:
        if not tech:
            D.sub(L('Indikator Turunan pada Laporan', 'Derived Indicators in this Report'))
        D.bullets([
            L('Payback terdiskonto = tahun saat arus kas kumulatif terdiskonto ≥ 0 (interpolasi linier).',
              'Discounted payback = year in which cumulative discounted cash flow ≥ 0 (linear interpolation).'),
            L('Biaya energi baseline = biaya baseline tahun-1 / energi beban tahunan.',
              'Baseline cost of energy = year-1 baseline cost / annual load energy.'),
        ])

    D.section(L('Daftar Singkatan', 'Abbreviations'), appendix_letter='B', pagebreak=False)
    ab = [('BESS', L('Sistem penyimpanan energi baterai', 'Battery energy storage system')),
          ('CAPEX / OPEX', L('Belanja modal / biaya operasi', 'Capital / operating expenditure')),
          ('DCF', L('Arus kas terdiskonto', 'Discounted cash flow')),
          ('DEG', L('Genset diesel', 'Diesel engine generator')),
          ('EFC', L('Siklus penuh ekivalen', 'Equivalent full cycle')),
          ('EPC', 'Engineering, procurement & construction'),
          ('IRR', 'Internal rate of return'),
          ('LCOE', 'Levelised cost of energy'),
          ('LPSP', 'Loss of power supply probability'),
          ('NPV', 'Net present value'),
          ('O&M', L('Operasi & pemeliharaan', 'Operation & maintenance')),
          ('PCS', 'Power conversion system'),
          ('PV', 'Photovoltaic'),
          ('RF', L('Fraksi energi terbarukan', 'Renewable fraction')),
          ('ROI', 'Return on investment'),
          ('SFC', 'Specific fuel consumption'),
          ('SOC / SOH', 'State of charge / state of health')]
    D.table([L('Singkatan', 'Abbreviation'), L('Arti', 'Meaning')], [list(r) for r in ab],
            align=['l', 'l'], widths=[0.25, 0.75], font=8)

    D.section(L('Batasan & Disclaimer', 'Limitations & Disclaimer'), appendix_letter='C',
              pagebreak=False)
    D.bullets([
        L('Laporan disusun dari data & asumsi pengguna; angka '
          'bersifat indikatif untuk kajian awal (pre-feasibility).',
          'This report is prepared from user data and '
          'assumptions; figures are indicative for a preliminary (pre-feasibility) study.'),
        L('Model energi berbasis neraca energi per langkah waktu; tidak mencakup aliran '
          'daya, kualitas daya, stabilitas, maupun proteksi.',
          'The energy model is a per-time-step energy balance; it does not cover load '
          'flow, power quality, stability or protection.'),
        L('Analisis finansial bersifat nominal sebelum pajak dan tanpa struktur '
          'pembiayaan (ekuitas/pinjaman).',
          'The financial analysis is nominal, pre-tax, and excludes the financing '
          'structure (equity/debt).'),
        L('Bukan nasihat investasi; keputusan harus didasarkan pada desain rinci dan '
          'uji tuntas (due diligence).',
          'Not investment advice; decisions should rely on detailed design and due '
          'diligence.'),
    ])
