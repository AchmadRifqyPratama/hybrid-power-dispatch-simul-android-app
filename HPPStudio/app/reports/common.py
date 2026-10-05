"""Komponen bersama untuk laporan Studi Kelayakan (PDF & DOCX).

Berisi: pemilihan bahasa, format angka, palet warna grafik, konfigurasi font
persamaan, pembuat grafik (matplotlib → PNG), render persamaan (mathtext), dan
helper finansial/konfigurasi. Modul ini TIDAK bergantung pada reportlab maupun
python-docx sehingga bisa dipakai kedua pembuat laporan.

PENTING: modul ini TIDAK menjalankan/mengubah mesin dispatch — hanya MEMBACA
hasil simulasi. Sensitivitas hanya menghitung ulang lapisan finansial.
"""
from __future__ import annotations
import io
import os
import sys

import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

from ..config.i18n import get_language
from ..engine.finance import financial_kpis

# --------------------------------------------------------------- palet warna --
# Hex string (dipakai grafik; dikonversi ke tipe warna masing-masing report).
# Palet seri grafik laporan (v139): makna warna tetap sama dengan aplikasi
# (PV hijau, Grid biru, BESS oranye, Diesel merah, SOC ungu, curtailment
# kuning-tua) namun tiap langkah divalidasi agar terbedakan di cetak & bagi
# pembaca buta warna (lightness band, CVD ΔE ≥ 20, kontras ≥ 3:1).
C = dict(grid='#2563EB', deg='#991B1B', pv='#16A34A', bess='#EA580C',
         load='#4B5563', soc='#7C3AED', exc='#B7791F', uns='#9CA3AF')
GREEN = '#16A34A'          # aksen brand
DARK = '#0F3D2E'           # hijau tua brand (judul, header tabel)
LIGHT = '#F2F6F3'          # zebra tabel / latar kartu
GREY = '#5B6570'           # teks sekunder
RULE = '#D5DDD8'           # garis tabel
INK = '#1B2128'            # teks utama
AMBER = '#B45309'
WHITE = '#FFFFFF'
# Status (hanya utk makna baik/perhatian/buruk; selalu disertai ikon+label)
OK = '#15803D'
WARN = '#B45309'
BAD = '#B91C1C'
INFO = '#1D4ED8'


# --------------------------------------------------------------- bilingual ----
def L(id_text: str, en_text: str) -> str:
    """Pilih teks sesuai bahasa aktif aplikasi."""
    return en_text if get_language() == 'EN' else id_text


def months():
    return (['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
             'Oct', 'Nov', 'Dec'] if get_language() == 'EN'
            else ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu',
                  'Sep', 'Okt', 'Nov', 'Des'])


# ------------------------------------------------------------------- angka -----
def fmt_n(v, dec=0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return '-'
    if f != f:                       # NaN
        return '-'
    return f'{f:,.{dec}f}'


def fmt_rp(v, dec=0):
    s = fmt_n(v, dec)
    return '-' if s == '-' else f'Rp {s}'


def fmt_money_short(v, dec=2):
    """Rupiah ringkas utk ringkasan: 'Rp 5.57 bn' / 'Rp 5,57 miliar'."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return '-'
    if f != f:
        return '-'
    a = abs(f)
    for lim, en, idn in ((1e12, 'tn', 'triliun'), (1e9, 'bn', 'miliar'),
                         (1e6, 'mn', 'juta')):
        if a >= lim:
            num = f'{f / lim:,.{dec}f}'
            return f'Rp {num} ' + (en if get_language() == 'EN' else idn)
    return fmt_rp(f)


def fmt_mn(v, dec=1):
    """Nilai rupiah dalam JUTA (utk tabel ber-kolom 'Rp juta')."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return '-'
    if f != f:
        return '-'
    return f'{f / 1e6:,.{dec}f}'


def fmt_pct(frac, dec=1):
    try:
        f = float(frac)
    except (TypeError, ValueError):
        return '-'
    if f != f:
        return '-'
    return f'{f * 100:,.{dec}f}%'


# ------------------------------------------------------------------- aset ------
def asset(name: str):
    """Path aset yang tahan-frozen (.exe PyInstaller) & dari sumber."""
    cands = []
    base = getattr(sys, '_MEIPASS', None)
    if base:
        cands.append(os.path.join(base, 'assets', name))
    here = os.path.dirname(os.path.abspath(__file__))
    cands.append(os.path.abspath(os.path.join(here, '..', '..', 'assets', name)))
    for p in cands:
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------- font persamaan -----
def _configure_math_font():
    """Font persamaan: utamakan Cambria Math (tersedia di Windows/Word); bila
    tidak ada, pakai STIX — font matematika serif yang mirip Cambria Math dan
    selalu tersedia bersama matplotlib (aman untuk build .exe)."""
    try:
        from matplotlib import font_manager as fm
        names = {f.name for f in fm.fontManager.ttflist}
        if 'Cambria Math' in names:
            matplotlib.rcParams['mathtext.fontset'] = 'custom'
            for k in ('rm', 'it', 'bf', 'sf', 'tt', 'cal'):
                matplotlib.rcParams['mathtext.' + k] = 'Cambria Math'
            return 'Cambria Math'
    except Exception:
        pass
    matplotlib.rcParams['mathtext.fontset'] = 'stix'
    return 'stix'


MATH_FONT = _configure_math_font()


def eq_png(latex, fs=11, dpi=200):
    """Render persamaan (mathtext) → (BytesIO PNG, lebar_pt, tinggi_pt).
    Ukuran fs≈font teks utama. Font: Cambria Math bila ada, selain itu STIX."""
    def _render(fontsize):
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0.0, 0.0, latex, fontsize=fontsize)
        b = io.BytesIO()
        fig.savefig(b, format='png', dpi=dpi, bbox_inches='tight',
                    pad_inches=0.03, facecolor='white', transparent=False)
        plt.close(fig)
        return b
    try:
        buf = _render(fs)
    except Exception:                       # font 'custom' bermasalah → STIX
        matplotlib.rcParams['mathtext.fontset'] = 'stix'
        buf = _render(fs)
    buf.seek(0)
    arr = mpimg.imread(buf)
    ih, iw = arr.shape[0], arr.shape[1]
    buf.seek(0)
    return buf, iw * 72.0 / dpi, ih * 72.0 / dpi


# --------------------------------------------------------- grafik matplotlib ---
def fig_to_png(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf


# ------------------------------------------------------ lokasi / koordinat ----
def has_coords(cfg) -> bool:
    """True bila latitude/longitude sudah diatur (bukan 0,0 kosong)."""
    try:
        lat = float(cfg.get('latitude', 0.0) or 0.0)
        lon = float(cfg.get('longitude', 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    return abs(lat) > 1e-9 or abs(lon) > 1e-9


def coord_text(lat, lon) -> str:
    """Koordinat desimal + huruf hemisfer, mis. '8.647800° S, 115.138500° E'.
    Kembalikan '-' bila belum diatur."""
    try:
        lat = float(lat); lon = float(lon)
    except (TypeError, ValueError):
        return '-'
    if abs(lat) < 1e-9 and abs(lon) < 1e-9:
        return '-'
    ns = 'N' if lat >= 0 else 'S'
    ew = 'E' if lon >= 0 else 'W'
    return f'{abs(lat):.6f}° {ns}, {abs(lon):.6f}° {ew}'


def _osm_tile(x, y, z, timeout=5.0):
    """Ambil satu ubin OpenStreetMap sebagai PIL.Image RGB (lempar bila gagal)."""
    from urllib.request import Request, urlopen
    from PIL import Image
    url = f'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
    req = Request(url, headers={
        'User-Agent': 'HPPStudio/1.0 (Akartha Energi Baru)'})
    with urlopen(req, timeout=timeout) as r:
        data = r.read()
    return Image.open(io.BytesIO(data)).convert('RGB')


def fig_location_map(lat, lon, zoom=13, cw=680, ch=430):
    """Peta lokasi (OpenStreetMap) dengan penanda pada koordinat.

    Best-effort: kembalikan matplotlib fig, atau None bila koordinat kosong,
    PIL tak tersedia, atau jaringan gagal (laporan tetap memuat koordinat
    dalam bentuk teks). Ubin diunduh dari OSM saat laporan dibuat."""
    import math
    try:
        lat = float(lat); lon = float(lon)
    except (TypeError, ValueError):
        return None
    if abs(lat) < 1e-9 and abs(lon) < 1e-9:
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    z = int(zoom)
    n = 2 ** z
    xt = (lon + 180.0) / 360.0 * n
    lat_c = max(-85.05112878, min(85.05112878, lat))
    yt = (1.0 - math.asinh(math.tan(math.radians(lat_c))) / math.pi) / 2.0 * n
    x0 = int(math.floor(xt)); y0 = int(math.floor(yt))
    span = 1                                   # kisi 3×3 ubin
    side = 256 * (2 * span + 1)
    canvas = Image.new('RGB', (side, side), (233, 230, 220))
    try:
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                tx, ty = x0 + dx, y0 + dy
                if tx < 0 or ty < 0 or tx >= n or ty >= n:
                    continue
                canvas.paste(_osm_tile(tx, ty, z),
                             ((dx + span) * 256, (dy + span) * 256))
    except Exception:
        return None                            # offline / diblokir → lewati
    px = (xt - (x0 - span)) * 256
    py = (yt - (y0 - span)) * 256
    left = max(0, min(int(round(px - cw / 2)), canvas.width - cw))
    top = max(0, min(int(round(py - ch / 2)), canvas.height - ch))
    crop = canvas.crop((left, top, left + cw, top + ch))
    mx, my = px - left, py - top
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    ax.imshow(np.asarray(crop), extent=(0, cw, ch, 0))
    ax.plot([mx], [my], marker='o', markersize=15, markerfacecolor=C['deg'],
            markeredgecolor='white', markeredgewidth=2.0, zorder=5)
    ax.plot([mx], [my], marker='o', markersize=4, markerfacecolor='white',
            markeredgecolor='white', zorder=6)
    ax.set_xlim(0, cw); ax.set_ylim(ch, 0)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_edgecolor(RULE); sp.set_linewidth(0.8)
    ax.text(cw - 6, ch - 6, '© OpenStreetMap', fontsize=6.5, color='#333',
            ha='right', va='bottom',
            bbox=dict(boxstyle='round,pad=0.2', fc='white', ec='none',
                      alpha=0.75))
    fig.tight_layout(pad=0.3)
    return fig


def _sr(series, key, n=None):
    a = np.asarray(series[key])
    a = a.reshape(len(a), -1)[:, 0]
    return a[:n] if n else a


def fig_profile(series):
    """Profil operasi minggu pertama. Legend menggabungkan sumbu kW (kiri) &
    SOC (kanan) sehingga SOC ikut tampil di legend."""
    hours = min(168, len(_sr(series, 'load')))
    x = np.arange(hours)
    fig, ax1 = plt.subplots(figsize=(9.6, 3.2))
    ax1.plot(x, _sr(series, 'grid', hours), color=C['grid'], lw=1.1,
             label=L('Grid', 'Grid'))
    ax1.plot(x, _sr(series, 'deg', hours), color=C['deg'], lw=1.1,
             label=L('Diesel', 'Diesel'))
    ax1.plot(x, _sr(series, 'pv_inv_out', hours), color=C['pv'], lw=1.1,
             label='PV INV')
    ax1.plot(x, _sr(series, 'bess_net', hours), color=C['bess'], lw=1.1,
             label='BESS')
    ax1.plot(x, _sr(series, 'load', hours), color=C['load'], lw=1.3, ls='--',
             label='Load')
    ax2 = ax1.twinx()
    ax2.plot(x, 100 * _sr(series, 'soc', hours), color=C['soc'], lw=1.0,
             alpha=0.85, label='SOC')
    ax2.set_ylabel('SOC (%)')
    ax2.set_ylim(0, 100)
    ax1.set_ylabel('kW')
    ax1.set_xlabel(L('Jam (minggu pertama)', 'Hour (first week)'))
    # legend gabungan kedua sumbu (agar SOC ikut tampil)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc='upper left', ncol=6, fontsize=7,
               frameon=False)
    ax1.grid(alpha=0.25)
    return fig


def fig_pie(kpi):
    pvbs = float(kpi.get('pvbs_supply_ratio', 0.0))
    grid = float(kpi.get('grid_supply_ratio', 0.0))
    uns = float(kpi.get('unserved_kwh', 0.0)) / max(
        float(kpi.get('annual_load_kwh', 1.0)), 1e-9)
    diesel = max(0.0, 1 - pvbs - grid - uns)
    vals = np.array([pvbs, grid, diesel, uns], float)
    labels = ['PV + BESS', L('Grid', 'Grid'), L('Diesel', 'Diesel'),
              L('Tak-terlayani', 'Unserved')]
    cols = [C['pv'], C['grid'], C['deg'], '#9CA3AF']
    keep = vals > 1e-4
    fig, ax = plt.subplots(figsize=(4.2, 3.2))
    ax.pie(vals[keep], labels=np.asarray(labels)[keep].tolist(),
           colors=np.asarray(cols)[keep].tolist(),
           autopct='%1.1f%%', startangle=90, textprops={'fontsize': 8})
    return fig


def fig_monthly(monthly):
    fig, axes = plt.subplots(1, 3, figsize=(9.6, 2.6))
    spec = [('pv_inv_out', L('Energi PV Bulanan (kWh)', 'Monthly PV Energy (kWh)'),
             C['pv']),
            ('fuel_l', L('Fuel Diesel Bulanan (L)', 'Monthly Diesel Fuel (L)'),
             C['deg']),
            ('pv_excess', L('Curtailment Bulanan (kWh)',
                            'Monthly Curtailment (kWh)'), C['exc'])]
    for ax, (key, title, color) in zip(axes, spec):
        ax.bar(months(), np.asarray(monthly[key], float), color=color)
        ax.set_title(title, fontsize=8.5)
        ax.tick_params(labelsize=6.5, axis='x', rotation=90)
        ax.tick_params(labelsize=7, axis='y')
        ax.grid(axis='y', alpha=0.25)
    fig.tight_layout()
    return fig


def fig_heat(series, key, cmap):
    a = _sr(series, key)
    days = len(a) // 24
    if days < 1:
        return None
    m = a[:days * 24].reshape(days, 24).T
    fig, ax = plt.subplots(figsize=(9.6, 2.1))
    im = ax.imshow(m, aspect='auto', origin='lower', cmap=cmap,
                   extent=[1, days, 0, 24])
    ax.set_xlabel(L('Hari', 'Day'), fontsize=8)
    ax.set_ylabel(L('Jam', 'Hour'), fontsize=8)
    ax.tick_params(labelsize=7)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    return fig


def fig_cumcash(years, cum):
    x = np.asarray(years, float)
    v = np.asarray(cum, float)
    fig, ax = plt.subplots(figsize=(9.6, 3.0))
    ax.bar(x, v, width=0.7,
           color=[C['deg'] if h < 0 else C['pv'] for h in v])
    ax.axhline(0, color='#9CA3AF', lw=1)
    ax.set_xlabel(L('Tahun ke-', 'Year'))
    ax.set_ylabel(L('Kas Kumulatif (Rp)', 'Cumulative Cash (Rp)'))
    ax.grid(axis='y', alpha=0.25)
    return fig


# --------------------------------------------------------- case analysis ------
def case_analysis(result, cfg):
    """Ringkasan Mode Case Analysis dari hasil simulasi (identik dgn Dashboard).
    Kembalikan {rows:[(case,jam)], marked_h, total_h} atau None bila deret tak
    tersedia."""
    series = result.get('series')
    if series is None or 'grid_status' not in series or 'soc' not in series:
        return None
    try:
        from ..engine.cases import case_summary
        p = result.get('params')
        smin = float(getattr(p, 'soc_min', cfg.get('soc_min', 0.1)))
        smax = float(getattr(p, 'soc_max', cfg.get('soc_max', 0.95)))
        bess = float(getattr(p, 'bess_kwh', cfg.get('bess_kwh', 0.0)))
        rte = float(getattr(p, 'rte', cfg.get('rte', 1.0)))
        dt = float(getattr(p, 'interval_h', 1.0) or 1.0)
        rows, marked, total = case_summary(series, smin, smax, bess, dt, rte)
        return {'rows': rows, 'marked_h': marked, 'total_h': total} if rows else None
    except Exception:
        return None


def case_desc(c):
    """Deskripsi case bilingual singkat untuk tabel report."""
    from ..engine.cases import case_components
    grid, pv, bidx, deg = case_components(c)
    bess_id = ['charge', 'tak bisa charge', 'discharge', 'tak bisa discharge'][bidx]
    bess_en = ['charge', 'cannot charge', 'discharge', 'cannot discharge'][bidx]
    pvs = 'PV✓' if pv else 'PV✗'
    dg = 'ON' if deg else 'OFF'
    return L(f'Grid {grid} · {pvs} · BESS {bess_id} · DEG {dg}',
             f'Grid {grid} · {pvs} · BESS {bess_en} · DEG {dg}')


def fig_case_hours(rows):
    """Bar chart horizontal jam per case (warna sesuai kode warna Dashboard)."""
    from ..engine.cases import case_hex
    rows = list(rows)
    labels = [f'C{c}' for c, _h in rows]
    vals = [h for _c, h in rows]
    cols = [case_hex(c) for c, _h in rows]
    fig, ax = plt.subplots(figsize=(9.6, max(1.8, 0.34 * len(rows) + 0.7)))
    y = list(range(len(rows)))
    ax.barh(y, vals, color=cols)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel(L('Jam per tahun', 'Hours per year'))
    ax.grid(axis='x', alpha=0.25)
    for yi, v in zip(y, vals):
        ax.text(v, yi, f' {v:,.0f}', va='center', fontsize=6.5)
    fig.tight_layout()
    return fig


# --------------------------------------------------- helper finansial/konfig ---
def deg_info(cfg):
    try:
        n = int(str(cfg.get('deg_count', '1')))
    except (TypeError, ValueError):
        n = 1
    caps = [float(cfg.get('deg1_kw', 0.0) or 0.0),
            float(cfg.get('deg2_kw', 0.0) or 0.0),
            float(cfg.get('deg3_kw', 0.0) or 0.0)][:max(n, 1)]
    return n, sum(caps), caps


def fuel_rate(cfg):
    """Laju bahan bakar efektif (skalar), DIHITUNG ULANG dari laju per-DEG saat
    ini — tidak memakai nilai `deg_fuel_rate_eff` tersimpan yang bisa basi
    (sumber ketidaksesuaian dengan halaman Parameters)."""
    try:
        from ..config.parameters import deg_fuel_rate_eff
        return float(deg_fuel_rate_eff(cfg))
    except Exception:
        try:
            eff = float(cfg.get('deg_efficiency', 0.33)) or 0.33
        except (TypeError, ValueError):
            eff = 0.33
        return 1.0 / (eff * 10.0)


def fuel_rates(cfg):
    """Laju bahan bakar per-DEG (tuple) sesuai halaman Parameters."""
    try:
        from ..config.parameters import deg_fuel_rates
        return tuple(deg_fuel_rates(cfg))
    except Exception:
        return (fuel_rate(cfg),) * 3


def fuel_rate_disp(cfg):
    """Teks tampilan laju bahan bakar per-DEG (identik dgn halaman Parameters):
    satu nilai bila semua sama, selain itu 'r1 / r2 / r3'."""
    n, _tot, _caps = deg_info(cfg)
    rs = list(fuel_rates(cfg))[:max(n, 1)]
    uniq = {round(float(r), 3) for r in rs}
    if len(uniq) == 1:
        return f'{next(iter(uniq)):.3f} L/kWh'
    return ' / '.join(f'{float(r):.3f}' for r in rs) + ' L/kWh'


def load_priority_rows(cfg):
    """Baris (label, nilai) Load Supply Priority yang MENGHORMATI opsi
    'Load Priority Follows Grid Status' (split per status grid) — agar sesuai
    dengan halaman Parameters."""
    grid_on = bool(cfg.get('grid_enabled', True))
    split = bool(cfg.get('load_priority_split', False)) and grid_on
    if split:
        return [
            (L('Prioritas Beban — Grid Tersedia',
               'Load Priority — Grid Available'),
             str(cfg.get('load_priority_on', '-'))),
            (L('Prioritas Beban — Grid Padam',
               'Load Priority — Grid Unavailable'),
             str(cfg.get('load_priority_off', '-'))),
        ]
    return [(L('Prioritas Pasokan Beban', 'Load Supply Priority'),
             str(cfg.get('load_priority', '-')))]


def dispatch_option_rows(cfg):
    """Ringkas opsi dispatch penting agar report sesuai halaman Parameters."""
    grid_on = bool(cfg.get('grid_enabled', True))
    yn = lambda b: (L('Ya', 'Yes') if b else L('Tidak', 'No'))
    rows = [(L('Pengisian Grid→BESS', 'Grid→BESS Charging'),
             yn(bool(cfg.get('grid_charge_enabled', False)) and grid_on)),
            (L('Strict Charging Priority', 'Strict Charging Priority'),
             yn(bool(cfg.get('strict_charge_priority', False))))]
    return rows


def sizes_from(result, cfg):
    p = result.get('params')
    if p is not None:
        return dict(kwp=float(p.pv_kwp), kw_inv=float(p.pv_inv_kw),
                    kwh_bess=float(p.bess_kwh), kw_deg=float(sum(p.deg_kw)),
                    pv_deg=float(getattr(p, 'pv_degradation', cfg.get(
                        'pv_degradation', 0.0))))
    _, kw_deg, _ = deg_info(cfg)
    return dict(kwp=float(cfg.get('pv_kwp', 0.0)),
                kw_inv=float(cfg.get('pv_inv_kw', 0.0)),
                kwh_bess=float(cfg.get('bess_kwh', 0.0)), kw_deg=kw_deg,
                pv_deg=float(cfg.get('pv_degradation', 0.0)))


def sensitivity(kpi, cfg, sizes):
    """Hitung ulang HANYA lapisan finansial untuk beberapa skenario.
    Dispatch/energi TIDAK dihitung ulang. Memakai cost_config(cfg) yang SAMA
    dengan aplikasi agar 'kasus dasar' identik dengan angka headline."""
    from ..config.parameters import cost_config
    base_cfg = {**cost_config(cfg), 'pv_degradation': sizes['pv_deg']}
    sz = {'kwp': sizes['kwp'], 'kw_inv': sizes['kw_inv'],
          'kwh_bess': sizes['kwh_bess'], 'kw_deg': sizes['kw_deg']}

    def fin(overrides=None, capex_factor=1.0):
        c = dict(base_cfg)
        if overrides:
            c.update(overrides)
        if capex_factor != 1.0:
            for k in ('pv_cost_per_kwp', 'inverter_cost_per_kw',
                      'bess_cost_per_kwh', 'deg_cost_per_kw',
                      'epc_cost_per_kwp', 'accessories_cost', 'logistic_cost'):
                if k in c and c[k] not in (None, ''):
                    c[k] = float(c[k]) * capex_factor
        return financial_kpis(kpi, sz, c)

    disc = float(cfg.get('discount_rate', 0.1))
    fuel = float(cfg.get('diesel_price_per_l', 0.0))
    return [
        (L('Kasus Dasar (base case)', 'Base case'), fin(), True),
        (L('Discount rate −2 poin', 'Discount rate −2 pts'),
         fin({'discount_rate': disc - 0.02}), False),
        (L('Discount rate +2 poin', 'Discount rate +2 pts'),
         fin({'discount_rate': disc + 0.02}), False),
        (L('Harga fuel −15%', 'Fuel price −15%'),
         fin({'diesel_price_per_l': fuel * 0.85}), False),
        (L('Harga fuel +15%', 'Fuel price +15%'),
         fin({'diesel_price_per_l': fuel * 1.15}), False),
        (L('CAPEX −10%', 'CAPEX −10%'), fin(capex_factor=0.90), False),
        (L('CAPEX +10%', 'CAPEX +10%'), fin(capex_factor=1.10), False),
    ]


def verdict(fin, cfg):
    """True bila proyek layak finansial (NPV>0 dan IRR≥discount atau payback≤umur)."""
    npv = float(fin.get('npv', float('nan')))
    irr = fin.get('irr', float('nan'))
    pb = fin.get('payback_years', float('nan'))
    life = float(cfg.get('project_lifetime_y', 0) or 0)
    disc = float(cfg.get('discount_rate', 0.0))
    irr_ok = (irr == irr) and float(irr) >= disc
    pb_ok = (pb == pb) and float(pb) <= life
    return (npv == npv and npv > 0) and (irr_ok or pb_ok)


