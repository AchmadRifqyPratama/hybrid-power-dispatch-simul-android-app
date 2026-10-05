"""Grafik laporan (v139) — gaya teknis seragam untuk PDF & DOCX.

Prinsip: satu sumbu-Y per grafik (tanpa dual-axis; besaran berbeda → panel
terpisah), garis tipis, grid samar, legenda selalu ada untuk ≥ 2 seri, teks
berwarna tinta (bukan warna seri), warna seri mengikuti palet tervalidasi
`common.C`. Semua fungsi hanya MEMBACA hasil simulasi (tanpa menghitung ulang
dispatch) dan mengembalikan matplotlib Figure (atau None bila data tak ada).
"""
from __future__ import annotations

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from .common import C, L, months, DARK, GREY, RULE, INK

RC = {
    'font.size': 8, 'axes.titlesize': 8.5, 'axes.labelsize': 8,
    'xtick.labelsize': 7, 'ytick.labelsize': 7, 'legend.fontsize': 7,
    'axes.edgecolor': RULE, 'axes.labelcolor': INK, 'xtick.color': GREY,
    'ytick.color': GREY, 'axes.spines.top': False, 'axes.spines.right': False,
    'axes.grid': True, 'grid.color': '#E5E9E6', 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'text.color': INK,
    'figure.facecolor': 'white', 'axes.facecolor': 'white',
}
_MN = FuncFormatter(lambda v, _p: f'{v / 1e6:,.0f}')


def _fig(w, h, **kw):
    with plt.rc_context(RC):
        return plt.subplots(figsize=(w, h), **kw)


def _series(series, key, n=None):
    if series is None or key not in series:
        return None
    a = np.asarray(series[key], float)
    a = a.reshape(len(a), -1)[:, 0]
    return a[:n] if n else a


def steps_per_hour(dt_h):
    try:
        return max(1, int(round(1.0 / float(dt_h))))
    except Exception:
        return 1


# ---------------------------------------------------------------- beban & PV --
def fig_daily_profile(series, dt_h=1.0):
    """Profil harian rata-rata (jam 0–23): beban, PV, grid, diesel (kW)."""
    load = _series(series, 'load')
    if load is None or len(load) < 24:
        return None
    sph = steps_per_hour(dt_h)
    idx = (np.arange(len(load)) // sph) % 24

    def hourly(a):
        return np.array([a[idx == h].mean() if np.any(idx == h) else 0.0
                         for h in range(24)])
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7.2, 2.7))
        x = np.arange(24)
        ax.plot(x, hourly(load), color=C['load'], lw=1.6, ls='--',
                label=L('Beban', 'Load'))
        for key, col, lab in (('pv', C['pv'], L('PV (potensi)', 'PV (available)')),
                              ('grid', C['grid'], 'Grid'),
                              ('deg', C['deg'], 'Diesel')):
            a = _series(series, key)
            if a is not None and np.nanmax(np.abs(a)) > 1e-6:
                ax.plot(x, hourly(a), color=col, lw=1.4, label=lab)
        ax.set_xlim(0, 23)
        ax.set_xticks(range(0, 24, 2))
        ax.set_xlabel(L('Jam dalam sehari', 'Hour of day'))
        ax.set_ylabel(L('Daya rata-rata (kW)', 'Average power (kW)'))
        ax.set_ylim(bottom=0)
        ax.legend(loc='upper left', ncol=4)
        fig.tight_layout()
    return fig


def monthly_supply(series, start, dt_h=1.0):
    """Energi pasokan KE BEBAN per bulan (kWh) dari deret per-langkah.
    Kembalikan dict {labels, pvbs, grid, deg, uns, load} atau None."""
    load = _series(series, 'load')
    if load is None:
        return None
    try:
        import pandas as pd
        idx = pd.date_range(start, periods=len(load),
                            freq=pd.Timedelta(hours=float(dt_h)))
        mon = idx.month.values
    except Exception:
        return None
    dt = float(dt_h)

    def agg(a):
        if a is None:
            return np.zeros(12)
        return np.array([a[mon == m].sum() * dt for m in range(1, 13)])
    pvbs = _series(series, 'pvbs_load')
    gl = _series(series, 'grid_load')
    deg = _series(series, 'deg')
    chg_deg = _series(series, 'chg_deg')
    if deg is not None and chg_deg is not None:
        deg = np.maximum(deg - chg_deg, 0.0)
    uns = _series(series, 'unserved')
    present = [m for m in range(1, 13) if np.any(mon == m)]
    out = dict(pvbs=agg(pvbs), grid=agg(gl), deg=agg(deg), uns=agg(uns),
               load=agg(load), months=present)
    return out


def fig_monthly_supply(ms):
    """Batang bertumpuk: pasokan ke beban per sumber per bulan (MWh)."""
    if not ms:
        return None
    mlab = months()
    keep = [m - 1 for m in ms['months']]
    if not keep:
        return None
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7.2, 2.8))
        x = np.arange(len(keep))
        bottom = np.zeros(len(keep))
        for key, col, lab in (('pvbs', C['pv'], 'PV + BESS'),
                              ('grid', C['grid'], 'Grid'),
                              ('deg', C['deg'], 'Diesel'),
                              ('uns', C['uns'], L('Tak terlayani', 'Unserved'))):
            v = ms[key][keep] / 1000.0
            if np.nanmax(v) <= 1e-9:
                continue
            ax.bar(x, v, bottom=bottom, color=col, width=0.72, label=lab,
                   edgecolor='white', linewidth=0.8)
            bottom += v
        ax.set_xticks(x)
        ax.set_xticklabels([mlab[k] for k in keep])
        ax.set_ylabel(L('Energi ke beban (MWh)', 'Energy to load (MWh)'))
        ax.legend(loc='upper left', ncol=4, bbox_to_anchor=(0, 1.16))
        ax.grid(axis='x', visible=False)
        fig.tight_layout()
    return fig


def fig_supply_mix(parts):
    """Satu batang 100% horizontal: porsi pasokan beban per sumber.
    parts = [(label, kWh, color)]."""
    tot = sum(max(0.0, v) for _l, v, _c in parts)
    if tot <= 0:
        return None
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7.2, 1.25))
        left = 0.0
        for lab, v, col in parts:
            f = max(0.0, v) / tot
            if f <= 1e-4:
                continue
            ax.barh([0], [f], left=left, color=col, height=0.55,
                    edgecolor='white', linewidth=1.5, label=f'{lab}  {f*100:.1f}%')
            if f >= 0.07:
                ax.text(left + f / 2, 0, f'{f*100:.1f}%', ha='center',
                        va='center', color='white', fontsize=8,
                        fontweight='bold')
            left += f
        ax.set_xlim(0, 1)
        ax.set_yticks([])
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f'{v*100:.0f}%'))
        ax.grid(False)
        for sp in ('left',):
            ax.spines[sp].set_visible(False)
        ax.legend(loc='upper center', ncol=4, bbox_to_anchor=(0.5, -0.45))
        fig.tight_layout()
    return fig


def fig_week_profile(series, dt_h=1.0, days=7):
    """Dua panel berbagi sumbu waktu: daya per sumber (kW) & SOC BESS (%)."""
    load = _series(series, 'load')
    if load is None:
        return None
    sph = steps_per_hour(dt_h)
    n = min(len(load), days * 24 * sph)
    t = np.arange(n) / float(sph) / 24.0          # hari
    with plt.rc_context(RC):
        fig, (a1, a2) = plt.subplots(
            2, 1, figsize=(7.2, 3.6), sharex=True,
            gridspec_kw={'height_ratios': [2.3, 1.0], 'hspace': 0.12})
        a1.plot(t, load[:n], color=C['load'], lw=1.3, ls='--',
                label=L('Beban', 'Load'))
        for key, col, lab in (('pv_inv_out', C['pv'], 'PV'),
                              ('grid', C['grid'], 'Grid'),
                              ('deg', C['deg'], 'Diesel'),
                              ('bess_net', C['bess'],
                               L('BESS (+ discharge / − charge)',
                                 'BESS (+ discharge / − charge)'))):
            a = _series(series, key, n)
            if a is not None and np.nanmax(np.abs(a)) > 1e-6:
                a1.plot(t, a, color=col, lw=1.0, label=lab)
        a1.axhline(0, color=RULE, lw=0.8)
        a1.set_ylabel('kW')
        a1.legend(loc='upper left', ncol=5, bbox_to_anchor=(0, 1.2))
        soc = _series(series, 'soc', n)
        if soc is not None:
            a2.plot(t, soc * 100.0, color=C['soc'], lw=1.1)
            a2.fill_between(t, soc * 100.0, color=C['soc'], alpha=0.08)
        a2.set_ylim(0, 100)
        a2.set_ylabel('SOC (%)')
        a2.set_xlabel(L('Hari ke-', 'Day'))
        a2.set_xlim(0, t[-1] if n else 1)
        fig.subplots_adjust(left=0.08, right=0.99, top=0.88, bottom=0.12)
    return fig


def fig_heat(series, key, cmap, dt_h=1.0, label=''):
    """Peta panas jam × hari; None bila deret kosong / seluruhnya nol."""
    a = _series(series, key)
    if a is None:
        return None
    sph = steps_per_hour(dt_h)
    if sph > 1:                                   # rata-rata per jam
        nh = len(a) // sph
        a = a[:nh * sph].reshape(nh, sph).mean(axis=1)
    days = len(a) // 24
    if days < 2 or float(np.nanmax(np.abs(a))) <= 1e-9:
        return None
    m = a[:days * 24].reshape(days, 24).T
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7.2, 1.9))
        im = ax.imshow(m, aspect='auto', origin='lower', cmap=cmap,
                       extent=[1, days, 0, 24], interpolation='nearest')
        ax.set_xlabel(L('Hari ke-', 'Day of period'))
        ax.set_ylabel(L('Jam', 'Hour'))
        ax.set_yticks([0, 6, 12, 18, 24])
        ax.grid(False)
        cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
        cb.ax.tick_params(labelsize=6.5)
        if label:
            cb.set_label(label, fontsize=7)
        fig.tight_layout()
    return fig


# ------------------------------------------------------------------ finansial --
def fig_capex(items):
    """Batang horizontal CAPEX per komponen (Rp juta), terurut, satu warna."""
    items = [(lab, v) for lab, v in items if v and v > 0]
    if not items:
        return None
    items.sort(key=lambda t: t[1])
    tot = sum(v for _l, v in items)
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7.2, 0.42 * len(items) + 0.6))
        y = np.arange(len(items))
        vals = [v for _l, v in items]
        ax.barh(y, vals, color=DARK, height=0.6)
        ax.set_yticks(y)
        ax.set_yticklabels([lab for lab, _v in items])
        ax.xaxis.set_major_formatter(_MN)
        ax.set_xlabel(L('Rp juta', 'Rp million'))
        ax.grid(axis='y', visible=False)
        xmax = max(vals)
        for yi, v in zip(y, vals):
            ax.text(v + xmax * 0.01, yi, f'{v/1e6:,.1f}  ({v/tot*100:.1f}%)',
                    va='center', fontsize=7, color=INK)
        ax.set_xlim(0, xmax * 1.28)
        fig.tight_layout()
    return fig


def fig_cost_compare(years, baseline, project, repl=None):
    """Biaya energi tahunan: baseline (tanpa PV+BESS) vs OPEX proyek (garis),
    penggantian BESS sebagai batang terpisah. Satu sumbu (Rp juta)."""
    x = np.asarray(years, float)
    if not len(x):
        return None
    base = np.asarray(baseline, float)
    proj = np.asarray(project, float)
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7.2, 2.6))
        rp = np.asarray(repl, float) if repl is not None else np.zeros_like(x)
        if np.any(rp > 0):
            ax.bar(x, rp, bottom=proj, color=C['bess'], width=0.55, alpha=0.85,
                   label=L('Penggantian BESS', 'BESS replacement'))
        ax.plot(x, base, color=C['deg'], lw=1.6, marker='o', ms=3,
                label=L('Baseline (tanpa PV + BESS)', 'Baseline (without PV + BESS)'))
        ax.plot(x, proj, color=C['pv'], lw=1.6, marker='o', ms=3,
                label=L('OPEX proyek', 'Project OPEX'))
        ax.fill_between(x, proj, base, where=base >= proj, color=C['pv'],
                        alpha=0.10, interpolate=True,
                        label=L('Penghematan operasi', 'Operating savings'))
        ax.yaxis.set_major_formatter(_MN)
        ax.set_ylabel(L('Rp juta / tahun', 'Rp million / year'))
        ax.set_xlabel(L('Tahun operasi', 'Operating year'))
        ax.set_xlim(x[0] - 0.6, x[-1] + 0.6)
        ax.set_ylim(bottom=0)
        ax.legend(loc='lower left', ncol=4, bbox_to_anchor=(0, 1.0))
        fig.tight_layout()
    return fig


def fig_cashflow(flows, payback=None):
    """Arus kas bersih tahunan (batang) + kumulatif (garis), tahun 0..Y."""
    f = np.asarray(flows, float).reshape(-1)
    if f.size < 2:
        return None
    x = np.arange(f.size)
    cum = np.cumsum(f)
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7.2, 2.9))
        ax.bar(x, f, color=[C['deg'] if v < 0 else C['pv'] for v in f],
               width=0.68, label=L('Arus kas bersih tahunan', 'Annual net cash flow'))
        ax.plot(x, cum, color=DARK, lw=1.6, marker='o', ms=2.8,
                label=L('Arus kas kumulatif', 'Cumulative cash flow'))
        ax.axhline(0, color=GREY, lw=0.8)
        if payback is not None and payback == payback and 0 < payback <= x[-1]:
            ax.axvline(payback, color=GREY, lw=0.9, ls=':')
            top = ax.get_ylim()[1]
            ax.text(payback + 0.25, top * 0.5,
                    f'{L("Payback", "Payback")} {payback:.1f} ' + L('thn', 'yr'),
                    fontsize=7, color=INK, va='center')
        ax.yaxis.set_major_formatter(_MN)
        ax.set_ylabel(L('Rp juta', 'Rp million'))
        ax.set_xlabel(L('Tahun', 'Year'))
        ax.set_xlim(-0.6, x[-1] + 0.6)
        ax.set_xticks(x if x[-1] <= 25 else np.arange(0, x[-1] + 1, 5))
        ax.legend(loc='lower left', ncol=2, bbox_to_anchor=(0, 1.0))
        fig.tight_layout()
    return fig


def fig_tornado(base, rows, title_unit=''):
    """Diagram tornado: dampak tiap variabel terhadap metrik (Δ dari kasus
    dasar). rows = [(label, value_low, value_high, low_lab, high_lab)]."""
    rows = [r for r in rows if r[1] == r[1] and r[2] == r[2]]
    if not rows or base != base:
        return None
    rows.sort(key=lambda r: abs(r[2] - r[1]))
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7.2, 0.55 * len(rows) + 0.8))
        y = np.arange(len(rows))
        for yi, (lab, lo, hi, llab, hlab) in zip(y, rows):
            for v, tag in ((lo, llab), (hi, hlab)):
                d = v - base
                ax.barh(yi, d, left=0, height=0.55,
                        color=C['pv'] if d >= 0 else C['deg'])
                ax.text(d, yi, f' {tag} ' if d >= 0 else f' {tag} ',
                        va='center', ha='left' if d >= 0 else 'right',
                        fontsize=6.8, color=INK)
        ax.axvline(0, color=INK, lw=0.9)
        ax.set_yticks(y)
        ax.set_yticklabels([r[0] for r in rows])
        ax.xaxis.set_major_formatter(_MN)
        ax.set_xlabel(title_unit or L('Δ NPV terhadap kasus dasar (Rp juta)',
                                      'Δ NPV vs base case (Rp million)'))
        ax.grid(axis='y', visible=False)
        lim = max(max(abs(r[1] - base), abs(r[2] - base)) for r in rows) * 1.45 or 1.0
        ax.set_xlim(-lim, lim)
        fig.tight_layout()
    return fig


# ------------------------------------------------------ arsitektur sistem ----
def _tint(hex_col, k=0.88):
    """Campur warna dengan putih (k = porsi putih) → isi kotak lembut."""
    h = hex_col.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (int(round(c + (255 - c) * k)) for c in (r, g, b))
    return f'#{r:02X}{g:02X}{b:02X}'


def fig_architecture(arch):
    """Diagram blok arsitektur sistem (AC-coupled) yang diusulkan.

    arch = dict(
      columns=[dict(key, color, top=(judul, rating), mid=(judul, rating),
                    link='DC'|'AC', flow='down'|'both'), ...],
      load=(judul, rating), ems=(judul, keterangan),
      ats=bool  (interlock DEG–Grid → gambar tautan ATS antara breaker),
      bus_label=str)
    Hanya MENGGAMBAR konfigurasi dari parameter; tak menghitung apa pun."""
    from matplotlib.patches import FancyBboxPatch
    cols = arch.get('columns') or []
    if not cols:
        return None
    n = len(cols)
    W, H = 100.0, 62.0
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7.2, 4.5))
        ax.set_xlim(0, W)
        ax.set_ylim(0, H - 4.0)
        ax.axis('off')
        left, right = 14.0, 96.0
        span = (right - left) / n
        xs = [left + span * (i + 0.5) for i in range(n)]
        bw = min(19.0, span * 0.84)
        bh = 7.6
        y_top, y_mid, y_bus = 51.5, 37.5, 25.0
        y_brk = 29.2

        def box(x, y, title, sub, col, lw=1.1):
            ax.add_patch(FancyBboxPatch(
                (x - bw / 2, y - bh / 2), bw, bh,
                boxstyle='round,pad=0.25,rounding_size=0.9',
                fc=_tint(col), ec=col, lw=lw))
            ax.text(x, y + 1.35, title, ha='center', va='center',
                    fontsize=7.2, fontweight='bold', color=INK)
            if sub:
                ax.text(x, y - 1.75, sub, ha='center', va='center',
                        fontsize=6.6, color=GREY)

        def arrow(x, y0, y1, col, both=False):
            ax.annotate('', xy=(x, y1), xytext=(x, y0),
                        arrowprops=dict(arrowstyle='<|-|>' if both else '-|>',
                                        color=col, lw=1.0,
                                        shrinkA=0, shrinkB=0,
                                        mutation_scale=7))

        # rel AC
        ax.plot([left - 3.5, right + 1.5], [y_bus, y_bus], color=DARK,
                lw=3.2, solid_capstyle='butt', zorder=3)
        ax.text(left - 4.2, y_bus, arch.get('bus_label', 'AC bus'),
                ha='right', va='center', fontsize=7, color=DARK,
                fontweight='bold')
        brk_x = {}
        for x, c in zip(xs, cols):
            col = c['color']
            box(x, y_top, *c['top'], col)
            box(x, y_mid, *c['mid'], col)
            # tautan perangkat → antarmuka (DC / AC)
            ax.plot([x, x], [y_top - bh / 2 - 0.3, y_mid + bh / 2 + 0.3],
                    color=col, lw=1.1, ls='-' if c.get('link') == 'AC' else (0, (4, 1.6)))
            ax.text(x + 0.9, (y_top + y_mid) / 2, c.get('link', 'DC'),
                    fontsize=6, color=GREY, va='center')
            # antarmuka → rel AC, dengan pemutus (breaker)
            top_y = y_mid - bh / 2 - 0.3
            ax.plot([x, x], [top_y, y_brk + 1.0], color=col, lw=1.1)
            ax.add_patch(plt.Rectangle((x - 1.0, y_brk - 1.0), 2.0, 2.0,
                                       fc='white', ec=INK, lw=0.8, zorder=4))
            ax.plot([x, x], [y_brk - 1.0, y_bus], color=col, lw=1.1)
            arrow(x + 2.6, top_y - 0.2, y_brk + 1.6, col,
                  both=(c.get('flow') == 'both'))
            brk_x[c['key']] = x
        # interlock DEG–Grid (ATS): tautan putus-putus antar breaker
        if arch.get('ats') and 'deg' in brk_x and 'grid' in brk_x:
            xa, xb = brk_x['deg'], brk_x['grid']
            yy = y_brk
            ax.plot([xa + 1.0, xb - 1.0], [yy, yy], color=C['deg'], lw=0.9,
                    ls=(0, (2.2, 1.6)), zorder=5)
            ax.text((xa + xb) / 2, yy + 1.2, 'ATS / interlock', ha='center',
                    va='bottom', fontsize=6.2, color=C['deg'])

        # beban & EMS di bawah rel
        y_low = 10.5
        xl = left + (right - left) * 0.30
        xe = left + (right - left) * 0.78
        ax.plot([xl, xl], [y_bus, y_low + bh / 2 + 0.3], color=C['load'], lw=1.1)
        arrow(xl + 2.6, y_bus - 0.8, y_low + bh / 2 + 1.0, C['load'])
        box(xl, y_low, *arch['load'], C['load'])
        bw_e = bw
        bw = max(bw, 24.0)
        box(xe, y_low, *arch['ems'], DARK, lw=1.3)
        bw = bw_e
        # jalur kendali EMS (titik-titik): EMS → sisi kanan → rel kendali di
        # bawah antarmuka → cabang ke tiap antarmuka (tak memotong tautan ATS)
        y_ctl = 32.2
        dots = dict(color=GREY, lw=0.7, ls=(0, (1.2, 1.4)))
        x_r = right + 1.2
        y_turn = y_low + bh / 2 + 3.2
        ax.plot([xe, xe], [y_low + bh / 2 + 0.3, y_turn], **dots)
        ax.plot([xe, x_r], [y_turn, y_turn], **dots)
        ax.plot([x_r, x_r], [y_turn, y_ctl], **dots)
        xmin = min(xs) - bw / 2 + 1.5
        ax.plot([xmin, x_r], [y_ctl, y_ctl], **dots)
        for x in xs:
            ax.plot([x - bw / 2 + 1.5, x - bw / 2 + 1.5],
                    [y_ctl, y_mid - bh / 2 - 0.3], **dots)
        # legenda kecil
        ly = 2.2
        items = [('-', DARK, L('Rel AC / aliran daya', 'AC bus / power flow')),
                 ((0, (4, 1.6)), GREY, L('Tautan DC', 'DC link')),
                 ((0, (1.2, 1.4)), GREY, L('Kendali & komunikasi EMS',
                                          'EMS control & communication'))]
        x0 = 2.0
        for ls, col, lab in items:
            ax.plot([x0, x0 + 4.5], [ly, ly], color=col, lw=1.0, ls=ls)
            ax.text(x0 + 5.3, ly, lab, fontsize=6.3, color=GREY, va='center')
            x0 += 6.0 + 1.25 * len(lab)
        ax.add_patch(plt.Rectangle((x0, ly - 0.8), 1.6, 1.6, fc='white',
                                   ec=INK, lw=0.8))
        ax.text(x0 + 2.4, ly, L('Pemutus (breaker)', 'Circuit breaker'),
                fontsize=6.3, color=GREY, va='center')
        fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    return fig
