"""Arsitektur sistem rancangan PENGGUNA → diagram profesional untuk laporan.

Alur:
  1. Pengguna menggambar arsitektur bebas di editor (app/gui/arch_editor.py),
     disimpan sebagai `cfg['arch_design']` (JSON):
        {'version': 1, 'use_in_report': bool,
         'nodes': [{'id', 'type', 'label', 'rating', 'x', 'y', 'w'?}, ...],
         'edges': [{'id', 'src', 'dst', 'kind', 'pts'?}, ...]}
     kind: ac | dc (daya) · rs485 | tcpip | fo | can | wired | wireless (komunikasi);
     'ctrl' lama dibaca sebagai 'wired'. Bentuk rect/polygon = grup visual.
  2. `analyze()` MEMBACA TOPOLOGI (siapa tersambung ke siapa), bukan posisi:
     rel AC utama, feeder per sumber/beban, sambungan kendali EMS, rating dari
     Parameters, dan catatan konsistensi terhadap konfigurasi simulasi.
  3. `figure()` MENGGAMBAR ULANG secara profesional (gaya SLD, simbol standar,
     tata letak otomatis): feeder sumber di atas rel, beban di bawah, EMS
     dengan jalur kendali. Posisi gambar pengguna hanya dipakai untuk URUTAN
     kiri→kanan feeder.

Modul murni (tanpa Qt) — dipakai editor (pratinjau) dan laporan (PDF/DOCX).
Tidak menyentuh engine maupun hasil simulasi.
"""
from __future__ import annotations

import re
from collections import deque

import numpy as np

from . import common as K
from .common import L

_n = K.fmt_n

# ------------------------------------------------------------ jenis komponen
# key: (label EN, label ID, famili warna, bentuk, peran)
#   bentuk: box | bus | breaker | xfmr | text
#   peran : source | conv | prot | bus | load | ctrl | note | other
TYPES = {
    'pv_array':    ('PV Array', 'Array PV', 'pv', 'box', 'source'),
    'pv_inverter': ('PV Inverter', 'Inverter PV', 'pv', 'box', 'conv'),
    'dcdc':        ('DC/DC Converter', 'Konverter DC/DC', 'pv', 'box', 'conv'),
    'bess':        ('Battery (BESS)', 'Baterai (BESS)', 'bess', 'box', 'source'),
    'pcs':         ('PCS', 'PCS', 'bess', 'box', 'conv'),
    'genset':      ('Diesel Genset', 'Genset Diesel', 'deg', 'box', 'source'),
    'grid':        ('Utility Grid', 'Grid Utilitas', 'grid', 'box', 'source'),
    'pcc':         ('PCC / Meter', 'PCC / Meter', 'grid', 'box', 'prot'),
    'transformer': ('Transformer', 'Trafo', 'neutral', 'xfmr', 'conv'),
    'breaker':     ('Circuit Breaker', 'Pemutus (CB)', 'neutral', 'breaker', 'prot'),
    'ats':         ('ATS', 'ATS', 'neutral', 'box', 'prot'),
    'ac_bus':      ('AC Bus', 'Rel AC', 'bus', 'bus', 'bus'),
    'dc_bus':      ('DC Bus', 'Rel DC', 'bus', 'bus', 'bus'),
    'load':        ('Load', 'Beban', 'load', 'box', 'load'),
    'ems':         ('EMS / Controller', 'EMS / Pengendali', 'ctrl', 'box', 'comm'),
    'eth_hub':     ('Ethernet Hub', 'Ethernet Hub', 'comm', 'box', 'comm'),
    'server':      ('Server / Cloud Monitoring', 'Server / Cloud Monitoring', 'comm',
                    'box', 'comm'),
    'sensor':      ('Sensor / Camera', 'Sensor / Kamera', 'comm', 'box', 'comm'),
    'text':        ('Note', 'Catatan', 'note', 'text', 'note'),
    'rect':        ('Rectangle', 'Persegi', 'note', 'rect', 'note'),
    'polygon':     ('Polygon', 'Poligon', 'note', 'polygon', 'note'),
}
# kelompok palet editor (urutan tampil)
PALETTE = [
    (('Pembangkit', 'Generation'), ['pv_array', 'pv_inverter', 'dcdc', 'genset']),
    (('Penyimpanan', 'Storage'), ['bess', 'pcs']),
    (('Grid & Proteksi', 'Grid & Protection'),
     ['grid', 'pcc', 'transformer', 'breaker', 'ats']),
    (('Rel & Beban', 'Bus & Load'), ['ac_bus', 'dc_bus', 'load']),
    (('Kendali & Komunikasi', 'Control & Communication'), ['ems', 'eth_hub', 'server', 'sensor']),
    (('Anotasi & Bentuk', 'Annotation & Shapes'), ['text', 'rect', 'polygon']),
]
COMM_DEVICES = {'ems', 'eth_hub', 'server', 'sensor'}
SHAPES = {'rect', 'polygon'}
NON_TOPO = {'text'} | SHAPES
POWER_KINDS = ('ac', 'dc')
COMM_KINDS = ('rs485', 'tcpip', 'fo', 'can', 'wired', 'wireless')
EDGE_KINDS = POWER_KINDS + COMM_KINDS
# perangkat sejenis yang disambung langsung = jaringan komunikasi (RS485
# daisy-chain antar inverter/meter/PCS, ring antar BESS) — bukan jalur daya
_CHAIN_TYPES = {'pv_inverter', 'pcs', 'pcc', 'bess', 'dcdc', 'genset'}
_DC_SIDE = {'pv_array', 'bess', 'dc_bus', 'dcdc'}
# gaya kabel komunikasi di laporan: (warna, linestyle, label EN, label ID)
COMM_STYLE = {
    'rs485': ('#7C3AED', (0, (5, 1.6, 1, 1.6)), 'RS485', 'RS485'),
    'tcpip': ('#0E7490', '-', 'TCP/IP (Ethernet)', 'TCP/IP (Ethernet)'),
    'fo': ('#15803D', (0, (6, 1.5)), 'Fibre optic (FO)', 'Serat optik (FO)'),
    'can': ('#0891B2', (0, (3, 1.2, 3, 3.2)), 'CAN bus', 'CAN bus'),
    'wired': ('#6B7280', (0, (1.2, 1.4)), 'Wired control', 'Kabel kendali'),
    'wireless': ('#B45309', (0, (2.6, 2.0)), 'Wireless', 'Nirkabel'),
}


def kind_label(k):
    if k in COMM_STYLE:
        st = COMM_STYLE[k]
        return L(st[3], st[2])
    return {'ac': L('Daya AC', 'AC power'), 'dc': L('Daya DC', 'DC power')}.get(k, k)


def type_label(t):
    e = TYPES.get(t)
    return L(e[1], e[0]) if e else str(t)


def family_color(fam):
    C = K.C
    return {'pv': C['pv'], 'bess': C['bess'], 'deg': C['deg'], 'grid': C['grid'],
            'load': C['load'], 'ctrl': K.DARK, 'bus': K.DARK, 'comm': '#334155',
            'neutral': '#4B5563', 'note': K.GREY}.get(fam, '#4B5563')


def default_edge_kind(t1, t2):
    """Jenis sambungan bawaan dari jenis ujung-ujungnya."""
    if t1 in COMM_DEVICES or t2 in COMM_DEVICES:
        if 'eth_hub' in (t1, t2) or 'server' in (t1, t2):
            return 'tcpip'
        return 'rs485'
    if t1 == t2 and t1 in _CHAIN_TYPES:
        return 'rs485'
    conv = {'pv_inverter', 'pcs', 'dcdc'}
    a, b = t1 in _DC_SIDE, t2 in _DC_SIDE
    if (a and b) or (a and t2 in conv) or (b and t1 in conv):
        return 'dc'
    return 'ac'


def effective_kind(kind, t1, t2):
    """Jenis efektif sebuah sambungan (termasuk migrasi rancangan lama):
    'ctrl' lama → 'wired'; sambungan 'daya' ke perangkat komunikasi atau
    antar perangkat sejenis (inverter–inverter, meter–meter, BESS–BESS) →
    komunikasi (RS485)."""
    if kind == 'ctrl':
        return 'wired'
    if kind not in EDGE_KINDS:
        return default_edge_kind(t1, t2)
    if kind in POWER_KINDS and (t1 in COMM_DEVICES or t2 in COMM_DEVICES
                                or (t1 == t2 and t1 in _CHAIN_TYPES)):
        return default_edge_kind(t1, t2)
    return kind


def empty_design():
    return {'version': 1, 'use_in_report': True, 'nodes': [], 'edges': []}


def has_original(design):
    o = (design or {}).get('original') if isinstance(design, dict) else None
    return isinstance(o, dict) and bool(o.get('b64'))


def report_mode(design):
    """Gambar arsitektur di laporan: 'original' (gambar asli pengguna),
    'redrawn' (topologi digambar ulang) atau None (pakai diagram otomatis)."""
    if not isinstance(design, dict) or not design.get('use_in_report', False):
        return None
    if design.get('report_figure') == 'original' and has_original(design):
        return 'original'
    return 'redrawn' if is_usable(design) else None


def original_bytes(design):
    import base64
    try:
        return base64.b64decode(design['original']['b64'])
    except Exception:
        return None


def original_figure(design):
    """Figure: gambar asli (jendela utama) + legenda warna garis yang rapi."""
    raw = original_bytes(design) if has_original(design) else None
    if not raw:
        return None
    import io
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert('RGB')
    w, h = im.size
    o = design['original']
    cols = [c for c in (o.get('colours') or []) if len(c) >= 2]
    try:
        from .arch_import import COLOUR_HEX
    except Exception:                          # pragma: no cover
        COLOUR_HEX = {}
    handles = []
    for cname, kind in cols:
        col = COLOUR_HEX.get(cname, '#555555')
        if kind == 'existing':
            handles.append(Line2D([], [], color=col, lw=1.2, ls=(0, (4, 2)),
                                  label=L('Fasilitas eksisting (garis tepi)',
                                          'Existing facility (outline)')))
        else:
            ls = {'black_dot': (0, (1, 2)), 'black_dash': (0, (4, 2)),
                  'black': (0, (1, 2))}.get(cname, '-')
            handles.append(Line2D([], [], color=col, lw=1.8, ls=ls, label=kind_label(kind)))
    fw = 7.2
    ih = fw * h / float(w)
    lh = 0.0
    if handles:
        ncol = len(handles) if len(handles) <= 5 else (len(handles) + 1) // 2
        lh = 0.22 * ((len(handles) + ncol - 1) // ncol) + 0.12
    fig = plt.figure(figsize=(fw, ih + lh))
    ax = fig.add_axes([0, lh / (ih + lh), 1, ih / (ih + lh)])
    ax.imshow(np.asarray(im), interpolation='lanczos')
    ax.set_axis_off()
    for sp in ax.spines.values():
        sp.set_visible(False)
    if handles:
        fig.legend(handles=handles, loc='lower center', ncol=ncol,
                   frameon=False, fontsize=6.8, handlelength=2.6,
                   bbox_to_anchor=(0.5, 0.0), columnspacing=1.6)
    return fig


def is_usable(design):
    """True bila rancangan boleh dipakai laporan (aktif & ada komponen daya)."""
    if not isinstance(design, dict) or not design.get('use_in_report', False):
        return False
    return any(n.get('type') in TYPES and n.get('type') not in NON_TOPO
               and n.get('type') not in COMM_DEVICES
               for n in design.get('nodes', []))


def _in_shape(n, x, y):
    """Titik (x, y) di dalam bentuk rect/polygon (koordinat editor)?"""
    if n.get('type') == 'rect':
        cx, cy = _f(n.get('x')), _f(n.get('y'))
        w, h = _f(n.get('w'), 200.0), _f(n.get('h'), 120.0)
        return abs(x - cx) <= w / 2 and abs(y - cy) <= h / 2
    pts = [(_f(p[0]) + _f(n.get('x')), _f(p[1]) + _f(n.get('y')))
           for p in (n.get('pts') or []) if len(p) >= 2]
    if len(pts) < 3:
        return False
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]; xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------- data konfigurasi
def _f(v, d=0.0):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def _cfg_info(cfg):
    try:
        n = int(str(cfg.get('deg_count', '1')))
    except ValueError:
        n = 1
    caps = [_f(cfg.get(f'deg{i}_kw')) for i in (1, 2, 3)][:n]
    caps = [c for c in caps if c > 0]
    return dict(
        kwp=_f(cfg.get('pv_kwp')), inv=_f(cfg.get('pv_inv_kw')),
        kwh=_f(cfg.get('bess_kwh')), chg=_f(cfg.get('max_charge_kw')),
        dis=_f(cfg.get('max_discharge_kw')),
        grid=bool(cfg.get('grid_enabled', True)) and _f(cfg.get('grid_kw')) > 0,
        grid_kw=_f(cfg.get('grid_kw')), caps=caps,
        export=bool(cfg.get('allow_export', False)),
        adv=str(cfg.get('bess_mode', 'Standard')).lower().startswith('adv'),
        ilock=bool(cfg.get('deg_grid_interlock', True)))


def auto_rating(t, idx, count, cfg, load_stats=None):
    """Rating bawaan komponen dari Parameters (teks), '' bila tak ada."""
    ci = _cfg_info(cfg)
    if t == 'pv_array' and ci['kwp'] > 0:
        return (f"{_n(ci['kwp'], 1)} kWp" if count <= 1
                else f"Σ {_n(ci['kwp'], 1)} kWp")
    if t == 'pv_inverter' and ci['inv'] > 0:
        return (f"{_n(ci['inv'], 1)} kW AC" if count <= 1
                else f"Σ {_n(ci['inv'], 1)} kW AC")
    if t == 'bess' and ci['kwh'] > 0:
        return f"{_n(ci['kwh'], 0)} kWh" if count <= 1 else f"Σ {_n(ci['kwh'], 0)} kWh"
    if t == 'pcs' and (ci['chg'] > 0 or ci['dis'] > 0):
        return f"{_n(ci['chg'], 0)}/{_n(ci['dis'], 0)} kW"
    if t == 'genset' and ci['caps']:
        caps = ci['caps']
        if count == 1 and len(caps) > 1:
            return f"{len(caps)} × (" + ' + '.join(_n(c, 0) for c in caps) + ') kW'
        if idx < len(caps):
            return f"{_n(caps[idx], 0)} kW"
        return ''
    if t == 'grid' and ci['grid']:
        return f"{_n(ci['grid_kw'], 1)} kW"
    if t == 'pcc' and ci['grid']:
        return L('ekspor-impor', 'import-export') if ci['export'] else L('impor saja', 'import only')
    if t == 'load' and load_stats and count <= 1:
        pk, e = load_stats.get('peak_kw'), load_stats.get('energy_kwh')
        parts = []
        if pk and pk == pk:
            parts.append(L('puncak', 'peak') + f" {_n(pk, 1)} kW")
        if e and e == e:
            parts.append(f"{_n(e / 1000.0, 1)} MWh/" + L('thn', 'yr'))
        return ' · '.join(parts)
    if t == 'ems':
        return 'Advanced EMS' if ci['adv'] else L('Dispatch standar', 'Standard dispatch')
    if t == 'server':
        return L('pemantauan', 'monitoring')
    return ''


# ------------------------------------------------------------- analisis ----
def analyze(design, cfg, load_stats=None):
    """Baca topologi rancangan → struktur siap-gambar + catatan konsistensi.

    Kembalikan dict: ok, issues [(tingkat, teks)], main, tree (children),
    feeders_up, feeders_down, nodes {id: node+label/rating}, kind {(a,b): k},
    comm [{a, b, kind}], commdev, groups [{label, members}], summary."""
    issues = []
    all_raw = [dict(n) for n in (design or {}).get('nodes', []) if n.get('type') in TYPES]
    shapes = [n for n in all_raw if n['type'] in SHAPES]
    nodes_raw = [n for n in all_raw if n['type'] not in NON_TOPO]
    nodes = {str(n['id']): n for n in nodes_raw}
    out = dict(ok=False, issues=issues, nodes=nodes, main=None, tree={},
               feeders_up=[], feeders_down=[], kind={}, comm=[], commdev=[],
               groups=[], comm_summary=[], summary=[], virtual_bus=False)
    if not nodes:
        issues.append(('warn', L('Rancangan kosong.', 'The design is empty.')))
        return out

    # --- label & rating per jenis (urut posisi x pengguna) ---
    by_type = {}
    for n in sorted(nodes.values(), key=lambda n: (_f(n.get('x')), _f(n.get('y')))):
        by_type.setdefault(n['type'], []).append(n)
    for t, lst in by_type.items():
        for i, n in enumerate(lst):
            base = type_label(t)
            if t == 'genset':
                base = f"{L('Genset', 'Genset')} DEG-{i + 1}" if len(lst) > 1 else \
                    L('Genset diesel', 'Diesel genset')
            elif len(lst) > 1 and t not in ('breaker',):
                base = f"{base} {i + 1}"
            n['_label'] = (str(n.get('label') or '').strip() or base)
            r = str(n.get('rating') or '').strip()
            n['_rating'] = r or auto_rating(t, i, len(lst), cfg, load_stats)
            n['_order'] = i

    # --- graf daya & komunikasi ---
    adj = {k: [] for k in nodes}
    edges = []
    comm_seen = set()
    for e in (design or {}).get('edges', []):
        a, b = str(e.get('src')), str(e.get('dst'))
        if a not in nodes or b not in nodes or a == b:
            continue
        k = effective_kind(e.get('kind'), nodes[a]['type'], nodes[b]['type'])
        if k in COMM_KINDS:
            key = (frozenset((a, b)), k)
            if key not in comm_seen:
                comm_seen.add(key)
                out['comm'].append(dict(a=a, b=b, kind=k))
            continue
        if b in adj[a]:
            continue
        adj[a].append(b); adj[b].append(a)
        out['kind'][(a, b)] = out['kind'][(b, a)] = k
        edges.append((a, b))

    power_ids = [k for k, n in nodes.items() if n['type'] not in COMM_DEVICES]
    if not power_ids:
        issues.append(('warn', L('Belum ada komponen daya pada rancangan.',
                                 'The design has no power components yet.')))
        return out
    buses = [k for k in power_ids if nodes[k]['type'] == 'ac_bus']
    if buses:
        main = max(buses, key=lambda k: (len(adj[k]), -_f(nodes[k].get('y'))))
    else:
        # tak ada rel AC: sisipkan rel virtual di titik pertemuan beban
        main = '__bus__'
        nodes[main] = dict(id=main, type='ac_bus', _label=L('Rel AC', 'AC bus'),
                           _rating='', x=0, y=0)
        adj[main] = []
        loads = [k for k in power_ids if nodes[k]['type'] == 'load']
        hub_nb = set()
        if loads:
            for ld in loads:
                for nb in list(adj[ld]):
                    hub_nb.add(nb)
                    adj[ld].remove(nb); adj[nb].remove(ld)
                adj[main].append(ld); adj[ld].append(main)
                out['kind'][(main, ld)] = out['kind'][(ld, main)] = 'ac'
            for nb in hub_nb:
                if nb not in loads:
                    adj[main].append(nb); adj[nb].append(main)
                    out['kind'][(main, nb)] = out['kind'][(nb, main)] = 'ac'
        else:
            hub = max(power_ids, key=lambda k: len(adj[k]))
            adj[main].append(hub); adj[hub].append(main)
            out['kind'][(main, hub)] = out['kind'][(hub, main)] = 'ac'
        out['virtual_bus'] = True
        issues.append(('info', L('Tidak ada rel AC pada gambar — rel AC utama disisipkan '
                                 'otomatis di titik pertemuan sumber dan beban.',
                                 'No AC bus in the drawing — a main AC bus was inserted '
                                 'automatically where sources and loads meet.')))
    out['main'] = main

    # --- pohon BFS dari rel utama (urutan anak mengikuti x pengguna) ---
    tree = {main: []}
    seen = {main}
    dq = deque([main])
    loops = 0
    while dq:
        u = dq.popleft()
        for v in sorted(adj[u], key=lambda k: _f(nodes[k].get('x'))):
            if v in seen:
                if v not in tree.get(u, []) and u not in tree.get(v, []):
                    loops += 1
                continue
            seen.add(v)
            tree.setdefault(u, []).append(v)
            tree[v] = []
            dq.append(v)
    loops //= 2
    drawing = isinstance(design, dict) and design.get('layout') == 'drawing'
    if loops and drawing:
        issues.append(('info', L(f'{loops} sambungan DAYA membentuk loop (tetap digambar sesuai '
                                 'gambar; mohon pastikan skema operasinya).',
                                 f'{loops} POWER connection(s) form a loop (drawn as in the '
                                 'drawing; please confirm the operating scheme).')))
    elif loops:
        issues.append(('warn', L(f'{loops} sambungan DAYA membentuk loop dan tidak digambar '
                                 '(sistem daya radial diasumsikan; loop pada jaringan '
                                 'komunikasi diizinkan).',
                                 f'{loops} POWER connection(s) form a loop and are not drawn '
                                 '(a radial power system is assumed; loops in the '
                                 'communication network are allowed).')))
    out['tree'] = tree
    lost = [k for k in power_ids if k not in seen]
    for k in lost:
        if drawing:
            issues.append(('info', L(f"'{nodes[k]['_label']}' belum tersambung ke sistem daya "
                                     "(tetap digambar sesuai posisinya).",
                                     f"'{nodes[k]['_label']}' is not connected to the power "
                                     "system (still drawn at its position).")))
            continue
        issues.append(('warn', L(f"'{nodes[k]['_label']}' tidak tersambung ke sistem daya "
                                 "dan dihilangkan dari diagram.",
                                 f"'{nodes[k]['_label']}' is not connected to the power "
                                 "system and is omitted from the diagram.")))
    # --- jaringan komunikasi (loop/daisy-chain/ring DIIZINKAN) ---
    commdev = [k for k, n in nodes.items() if n['type'] in COMM_DEVICES]
    ok_nodes = set(seen) | set(commdev)
    out['comm'] = [c for c in out['comm'] if c['a'] in ok_nodes and c['b'] in ok_nodes]
    out['commdev'] = sorted(commdev, key=lambda k: _f(nodes[k].get('x')))
    linked = {c['a'] for c in out['comm']} | {c['b'] for c in out['comm']}
    for k in commdev:
        if k not in linked:
            issues.append(('info', L(f"'{nodes[k]['_label']}' belum tersambung ke jaringan "
                                     "komunikasi.",
                                     f"'{nodes[k]['_label']}' is not connected to the "
                                     "communication network.")))
    for kd in COMM_KINDS:
        es = [c for c in out['comm'] if c['kind'] == kd]
        if not es:
            continue
        g = {}
        for c in es:
            g.setdefault(c['a'], set()).add(c['b']); g.setdefault(c['b'], set()).add(c['a'])
        done = set()
        for st in sorted(g, key=lambda k: _f(nodes[k].get('x'))):
            if st in done:
                continue
            comp, stack = [], [st]
            while stack:
                u = stack.pop()
                if u in done:
                    continue
                done.add(u); comp.append(u)
                stack += [v for v in g[u] if v not in done]
            ne = sum(len(g[u]) for u in comp) // 2
            deg = [len(g[u]) for u in comp]
            if kd in ('tcpip', 'fo', 'wireless') and len(comp) > 2:
                topo = (L('bintang (hub)', 'star (hub)')
                        if any(nodes[u]['type'] == 'eth_hub' for u in comp)
                        else L('jaringan', 'network'))
            elif len(comp) > 2 and ne == len(comp) and all(d == 2 for d in deg):
                topo = L('ring', 'ring')
            elif len(comp) > 2 and ne == len(comp) - 1 and max(deg) <= 2:
                topo = L('serial / daisy-chain', 'serial / daisy-chain')
            elif len(comp) > 2 and ne == len(comp) - 1:
                topo = L('bintang', 'star')
            elif len(comp) == 2:
                topo = L('titik-ke-titik', 'point-to-point')
            else:
                topo = L('mesh', 'mesh')
            # urutan label mengikuti rantai bila daisy-chain
            order = comp
            ends = [u for u in comp if len(g[u]) == 1]
            if ends and max(deg) <= 2:
                order, prev, cur = [], None, ends[0]
                while cur is not None and cur not in order:
                    order.append(cur)
                    nxt = [v for v in g[cur] if v != prev and v not in order]
                    prev, cur = cur, (nxt[0] if nxt else None)
            labs = ' – '.join(nodes[u]['_label'] for u in order)
            out['comm_summary'].append(f"{kind_label(kd)} — {topo}: {labs}")

    # --- grup dari bentuk (rect/polygon) pengguna ---
    for shp in shapes:
        mem = [k for k, n in nodes.items() if k in ok_nodes
               and _in_shape(shp, _f(n.get('x')), _f(n.get('y')))]
        if mem:
            out['groups'].append(dict(label=str(shp.get('label') or '').strip(),
                                      members=mem))

    # --- feeder atas (sumber) / bawah (beban) ---
    def sub(u):
        acc = [u]
        for v in tree.get(u, []):
            acc += sub(v)
        return acc
    for r in tree[main]:
        members = sub(r)
        roles = {TYPES[nodes[m]['type']][4] for m in members}
        (out['feeders_down'] if ('load' in roles and 'source' not in roles)
         else out['feeders_up']).append(r)

    # --- pemeriksaan konsistensi terhadap konfigurasi simulasi ---
    ci = _cfg_info(cfg)
    cnt = {t: len([m for m in seen if nodes[m]['type'] == t]) for t in TYPES}

    def chk(present_cfg, t, what_id, what_en):
        if present_cfg and cnt.get(t, 0) == 0:
            issues.append(('warn', L(f'{what_id} ada di konfigurasi simulasi tetapi tidak '
                                     'digambar.',
                                     f'{what_en} is in the simulation configuration but '
                                     'not drawn.')))
        if not present_cfg and cnt.get(t, 0) > 0:
            issues.append(('warn', L(f'{what_id} digambar tetapi tidak ada di konfigurasi '
                                     'simulasi (kapasitas 0 / nonaktif).',
                                     f'{what_en} is drawn but not in the simulation '
                                     'configuration (zero capacity / disabled).')))
    chk(ci['kwp'] > 0, 'pv_array', 'Array PV', 'PV array')
    chk(ci['kwh'] > 0, 'bess', 'BESS', 'BESS')
    chk(bool(ci['caps']), 'genset', 'Genset diesel', 'Diesel genset')
    chk(ci['grid'], 'grid', 'Grid', 'Grid')
    if ci['caps'] and cnt['genset'] > 1 and cnt['genset'] != len(ci['caps']):
        issues.append(('warn', L(f"Jumlah genset digambar ({cnt['genset']}) berbeda dengan "
                                 f"konfigurasi ({len(ci['caps'])} unit).",
                                 f"Number of gensets drawn ({cnt['genset']}) differs from "
                                 f"the configuration ({len(ci['caps'])} units).")))
    for t, what_id, what_en in (('pv_array', 'array PV', 'PV arrays'),
                                ('pv_inverter', 'inverter PV', 'PV inverters'),
                                ('bess', 'unit BESS', 'BESS units')):
        if cnt[t] > 1:
            issues.append(('info', L(f'Simulasi memodelkan {what_id} sebagai satu kapasitas '
                                     f'agregat; {cnt[t]} unit pada gambar diberi rating total (Σ).',
                                     f'The simulation models {what_en} as one aggregated '
                                     f'capacity; the {cnt[t]} units drawn carry the total '
                                     'rating (Σ).')))
    # rating yang ditulis pengguna vs parameter simulasi
    def _num(txt, units):
        import re as _re
        for m in _re.finditer(r'(\d+(?:[.,]\d+)?)\s*(kWp|kWh|kW|MWp|MWh|MW)\b', str(txt)):
            v = float(m.group(1).replace(',', '.'))
            u = m.group(2)
            if u.startswith('M'):
                v *= 1000.0; u = 'k' + u[1:]
            if u in units:
                return v
        return None
    ref = {'pv_array': (ci['kwp'], ('kWp',)), 'pv_inverter': (ci['inv'], ('kW',)),
           'bess': (ci['kwh'], ('kWh',)), 'pcs': (max(ci['chg'], ci['dis']), ('kW',))}
    for k in seen:
        n = nodes[k]
        if n['type'] in ref and str(n.get('rating') or '').strip():
            cfgv, units = ref[n['type']]
            v = _num(n['rating'], units)
            if v is not None and cfgv > 0 and cnt[n['type']] == 1 and \
                    abs(v - cfgv) > 0.02 * cfgv:
                issues.append(('warn', L(f"Rating '{n['_label']}' pada gambar ({n['rating']}) "
                                         f"berbeda dengan parameter simulasi ({_n(cfgv, 1)} "
                                         f"{units[0]}).",
                                         f"Rating of '{n['_label']}' in the drawing "
                                         f"({n['rating']}) differs from the simulation "
                                         f"parameter ({_n(cfgv, 1)} {units[0]}).")))
    n_sug = len([e for e in (design or {}).get('edges', []) if e.get('auto') == 'suggested'])
    if n_sug:
        issues.append(('info', L(f'{n_sug} sambungan disimpulkan dari tata letak gambar '
                                 '(tanpa garis terdeteksi) dan belum dikonfirmasi.',
                                 f'{n_sug} connection(s) were inferred from the drawing '
                                 'layout (no line detected) and are not yet confirmed.')))
    if cnt['load'] == 0:
        issues.append(('warn', L('Beban belum digambar.', 'No load is drawn.')))

    # sumber DC harus melalui konverter sebelum rel AC
    parent = {v: u for u, vs in tree.items() for v in vs}

    def path_up(u):
        p = []
        while u in parent:
            u = parent[u]
            p.append(u)
        return p
    for k in seen:
        t = nodes[k]['type']
        if t in ('pv_array', 'bess'):
            # BESS terintegrasi (kartu "BATT. … kWh, PCS … kW" / all-in-one) sudah ber-PCS
            if t == 'bess' and re.search(r'(?i)\bpcs\b|all[\s-]*in[\s-]*one|integrat',
                                         str(nodes[k].get('desc') or '')):
                continue
            conv = {'pv_inverter', 'pcs'} if t == 'pv_array' else {'pcs', 'pv_inverter'}
            if not any(nodes[u]['type'] in conv for u in path_up(k)):
                issues.append(('warn', L(f"'{nodes[k]['_label']}' tersambung ke sisi AC tanpa "
                                         "inverter/PCS.",
                                         f"'{nodes[k]['_label']}' connects to the AC side "
                                         "without an inverter/PCS.")))
    if ci['grid'] and ci['caps'] and ci['ilock'] and cnt['ats'] == 0 \
            and cnt['grid'] and cnt['genset']:
        issues.append(('info', L('Parameter memakai interlock DEG–Grid (transfer switch); '
                                 'pertimbangkan menggambar ATS di antara grid dan genset.',
                                 'Parameters use a DEG–Grid interlock (transfer switch); '
                                 'consider drawing an ATS between grid and genset.')))

    # --- ringkasan feeder (teks) ---
    def chain_txt(u, up):
        seq = []
        while True:
            if nodes[u]['type'] != 'breaker':
                seq.append(nodes[u]['_label'])
            kids = tree.get(u, [])
            if len(kids) != 1:
                if len(kids) > 1:
                    br = '; '.join(chain_txt(k, up) for k in kids)
                    seq.append('{' + br + '}')
                break
            u = kids[0]
        return ' → '.join(reversed(seq) if up else seq)
    for r in out['feeders_up']:
        out['summary'].append(chain_txt(r, True) + ' → ' + L('rel AC', 'AC bus'))
    for r in out['feeders_down']:
        out['summary'].append(L('Rel AC', 'AC bus') + ' → ' + chain_txt(r, False))
    out['summary'] += out['comm_summary']
    out['ok'] = bool(out['feeders_up'] or out['feeders_down'])
    return out


# ------------------------------------------------------------ penggambaran --
_FAILED = []                                  # diagnosis rute gagal (uji)
_GAP = {'breaker': 0.95, 'xfmr': 1.45, 'bus': 1.15, 'box': 1.75}
_BOX_H = 0.95


def _shape(nodes, k):
    return TYPES[nodes[k]['type']][3]


def _wrap(txt, width=18):
    words = str(txt).split()
    lines, cur = [], ''
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) > width and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + ' ' + w).strip()
    if cur:
        lines.append(cur)
    return '\n'.join(lines[:2]) if lines else ''


def figure(design, cfg, load_stats=None, analysis=None):
    """Gambar ulang rancangan pengguna secara profesional. None bila tak layak.

    Tata letak: feeder sumber di atas rel AC utama, beban di bawah, perangkat
    komunikasi (EMS/hub/server) di baris paling bawah. Kabel komunikasi
    DIRUTEKAN agar tidak pernah berimpit (kolinear) dengan kabel daya, kotak,
    maupun kabel komunikasi lain: (a) lurus antar perangkat bersebelahan,
    (b) rute lokal di atas baris perangkat, (c) lane tersendiri di bawah
    sistem daya. Persilangan tegak lurus masih mungkin (lazim pada SLD)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Circle
    from .charts import RC, _tint
    if isinstance(design, dict) and design.get('layout') == 'drawing':
        return figure_drawing(design, cfg, load_stats, analysis)
    A = analysis or analyze(design, cfg, load_stats)
    if not A['ok']:
        return None
    nodes, tree, main = A['nodes'], A['tree'], A['main']

    # ------------------------------------------------ tata letak daya -------
    width = {}

    def wcalc(u):
        kids = tree.get(u, [])
        width[u] = max(1, sum(wcalc(v) for v in kids)) if kids else 1
        return width[u]
    for r in A['feeders_up'] + A['feeders_down']:
        wcalc(r)
    ncol = max(sum(width[r] for r in A['feeders_up']),
               sum(width[r] for r in A['feeders_down']), 2)
    COL = 2.9
    bw = COL * 0.86
    pos = {}

    def place(u, x0, y, sgn):
        kids = tree.get(u, [])
        pos[u] = (x0 + width[u] * COL / 2.0, y)
        cx = x0
        for v in kids:
            gap = _GAP[_shape(nodes, v)]
            if _shape(nodes, u) == 'breaker':
                gap = max(gap, 0.95)
            place(v, cx, y + sgn * gap, sgn)
            cx += width[v] * COL

    tot_up = sum(width[r] for r in A['feeders_up'])
    tot_dn = sum(width[r] for r in A['feeders_down'])
    x = (ncol - tot_up) * COL / 2.0
    for r in A['feeders_up']:
        place(r, x, _GAP[_shape(nodes, r)], +1)
        x += width[r] * COL
    x = (ncol - tot_dn) * COL / 2.0
    for r in A['feeders_down']:
        place(r, x, -_GAP[_shape(nodes, r)], -1)
        x += width[r] * COL

    def half_h(k):
        return {'box': _BOX_H / 2, 'breaker': 0.16, 'xfmr': 0.42,
                'bus': 0.0}[_shape(nodes, k)]

    xs = [p[0] for p in pos.values()] or [0.0, ncol * COL]
    ys = [p[1] for p in pos.values()] or [0.0]
    bus_l = min(min(xs) - COL * 0.45, 0.2)
    bus_r = max(max(xs) + COL * 0.45, ncol * COL - 0.2)

    # ------------------------------------------- geometri kabel daya --------
    def feeder_color(k):
        stack = [k]
        while stack:
            u = stack.pop(0)
            fam = TYPES[nodes[u]['type']][2]
            if fam in ('pv', 'bess', 'deg', 'grid', 'load'):
                return family_color(fam)
            stack += tree.get(u, [])
        return '#4B5563'
    plines = []                                  # (xs, ys, warna, jenis)
    pv_segs, ph_segs = [], []                    # (x, y0, y1) / (y, x0, x1)

    def add_pline(xs_, ys_, col, kind):
        plines.append((xs_, ys_, col, kind))
        for (xa, ya), (xb, yb) in zip(zip(xs_, ys_), list(zip(xs_, ys_))[1:]):
            if abs(xa - xb) < 1e-9:
                pv_segs.append((xa, min(ya, yb), max(ya, yb)))
            else:
                ph_segs.append((ya, min(xa, xb), max(xa, xb)))

    def link(p, c, col):
        xp, yp = pos[p]
        xc, yc = pos[c]
        sgn = 1 if yc > yp else -1
        k = A['kind'].get((p, c), 'ac')
        y0 = yp if _shape(nodes, p) == 'bus' else yp + sgn * half_h(p)
        y1 = yc - sgn * half_h(c)
        if abs(xc - xp) < 1e-6:
            add_pline([xp, xp], [y0, y1], col, k)
        else:
            ym = y0 + (y1 - y0) * 0.45 if _shape(nodes, p) != 'bus' else y0
            add_pline([xp, xp, xc, xc], [y0, ym, ym, y1], col, k)
    for r in A['feeders_up'] + A['feeders_down']:
        col = feeder_color(r)
        xr, yr = pos[r]
        sg = 1 if yr > 0 else -1
        add_pline([xr, xr], [0, yr - sg * half_h(r)], col, A['kind'].get((main, r), 'ac'))
        stack = [(r, col)]
        while stack:
            u, cu = stack.pop()
            for v in tree.get(u, []):
                fam = TYPES[nodes[v]['type']][2]
                if fam in ('pv', 'bess', 'deg', 'grid', 'load'):
                    cv = family_color(fam)
                elif any(TYPES[nodes[w]['type']][2] in ('pv', 'bess', 'deg', 'grid', 'load')
                         for w in tree.get(v, [])):
                    cv = feeder_color(v)
                else:
                    cv = cu
                link(u, v, cv)
                stack.append((v, cv))
    ph_segs.append((0.0, bus_l, bus_r))
    sec_bus = {}
    for k in pos:
        if _shape(nodes, k) == 'bus':
            kids = tree.get(k, [])
            xsk = [pos[v][0] for v in kids] + [pos[k][0]]
            sec_bus[k] = (min(xsk) - 0.5, max(xsk) + 0.5)
            ph_segs.append((pos[k][1], sec_bus[k][0], sec_bus[k][1]))

    # ----------------------------------------------------- kotak ------------
    def bbox(k):
        xk, yk = pos[k]
        sh = _shape(nodes, k)
        if sh == 'box':
            return (xk - bw / 2, yk - _BOX_H / 2, xk + bw / 2, yk + _BOX_H / 2)
        if sh == 'breaker':
            lab = str(nodes[k].get('label') or '')
            return (xk - 0.16, yk - 0.16, xk + (0.3 + 0.1 * len(lab) if lab else 0.16),
                    yk + 0.16)
        if sh == 'xfmr':
            txt = max(len(str(nodes[k]['_label'])), len(str(nodes[k]['_rating'] or '')))
            return (xk - 0.26, yk - 0.42, xk + 0.4 + 0.12 * txt, yk + 0.42)
        return None
    boxes = {}
    for k in pos:
        b_ = bbox(k)
        if b_:
            boxes[k] = b_

    # ------------------------------------------- router komunikasi ----------
    devs = list(A['commdev'])
    dev_set = set(devs)
    comm = list(A['comm'])
    cv_used, ch_used = [], []
    EPS = 0.06

    def seg_ok(xa, ya, xb, yb, own):
        if abs(xa - xb) < 1e-9:                          # vertikal
            lo, hi = min(ya, yb), max(ya, yb)
            for (px, p0, p1) in pv_segs + cv_used:
                if abs(px - xa) < EPS and p0 < hi - 1e-6 and p1 > lo + 1e-6:
                    return False
            for (py, p0, p1) in ph_segs:                  # ujung di atas garis daya
                if abs(py - lo) < 1e-3 or abs(py - hi) < 1e-3:
                    if p0 - 1e-6 <= xa <= p1 + 1e-6 and py not in (0.0,):
                        return False
            for k, (bx0, by0, bx1, by1) in boxes.items():
                if k in own:
                    continue
                if bx0 - 0.07 < xa < bx1 + 0.07 and by0 - 0.04 < hi and by1 + 0.04 > lo:
                    return False
        else:                                             # horizontal
            lo, hi = min(xa, xb), max(xa, xb)
            for (py, p0, p1) in ph_segs + ch_used:
                if abs(py - ya) < EPS and p0 < hi - 1e-6 and p1 > lo + 1e-6:
                    return False
            for (px, p0, p1) in pv_segs:                  # tak menempel di ujung
                if (abs(px - lo) < 1e-3 or abs(px - hi) < 1e-3) and p0 <= ya <= p1:
                    return False
            for k, (bx0, by0, bx1, by1) in boxes.items():
                if k in own:
                    continue
                if by0 - 0.04 < ya < by1 + 0.04 and bx0 - 0.04 < hi and bx1 + 0.04 > lo:
                    return False
        return True

    def path_ok(pts, own):
        return all(seg_ok(xa, ya, xb, yb, own)
                   for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]))

    def commit(pts):
        for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
            if abs(xa - xb) < 1e-9:
                cv_used.append((xa, min(ya, yb), max(ya, yb)))
            else:
                ch_used.append((ya, min(xa, xb), max(xa, xb)))

    routes = []                                   # (pts, kind, (xm, ym) penanda)
    side_n, top_n = {}, {}

    def side_y(k, j):
        yk = pos[k][1]
        hh = (boxes[k][3] - boxes[k][1]) / 2 if k in boxes else 0.1
        return yk + min(0.22, hh * 0.55) - 0.12 * j

    def route_direct(c):
        a_, b_ = sorted((c['a'], c['b']), key=lambda k: pos[k][0])
        if a_ not in boxes or b_ not in boxes:
            return None
        if abs(pos[a_][1] - pos[b_][1]) > 0.3:
            return None
        xa, xb = boxes[a_][2], boxes[b_][0]
        if xb <= xa:
            return None
        for j in range(4):
            y = side_y(a_, max(side_n.get(a_, 0), side_n.get(b_, 0)) + j)
            pts = [(xa, y), (xb, y)]
            if path_ok(pts, {a_, b_}):
                side_n[a_] = side_n.get(a_, 0) + 1; side_n[b_] = side_n.get(b_, 0) + 1
                return pts
        return None

    def route_over(c):
        a_, b_ = sorted((c['a'], c['b']), key=lambda k: pos[k][0])
        if a_ in dev_set or b_ in dev_set or a_ not in boxes or b_ not in boxes:
            return None
        ta, tb = boxes[a_][3], boxes[b_][3]
        x_lo, x_hi = pos[a_][0], pos[b_][0]
        top = max([ta, tb] + [bb[3] for k, bb in boxes.items()
                              if bb[2] > x_lo and bb[0] < x_hi and bb[1] > min(ta, tb) - 0.3])
        for i in range(6):
            yt = top + 0.22 + 0.13 * i
            for oa in (0.22, 0.4, 0.58):
                xa = boxes[a_][0] + oa + 0.18 * top_n.get(a_, 0)
                xb = boxes[b_][2] - oa - 0.18 * top_n.get(b_, 0)
                pts = [(xa, ta), (xa, yt), (xb, yt), (xb, tb)]
                if path_ok(pts, {a_, b_}):
                    top_n[a_] = top_n.get(a_, 0) + 1; top_n[b_] = top_n.get(b_, 0) + 1
                    return pts
        return None

    # ujung yang tak berposisi (mis. pemutus yang digambar sebagai simbol pada
    # feeder) tak dapat dirutekan → dilewati
    comm = [c for c in comm if all(k in boxes or k in dev_set for k in (c['a'], c['b']))]
    local = {}
    for idx, c in enumerate(comm):
        if c['a'] in dev_set or c['b'] in dev_set:
            continue
        pts = route_direct(c) or route_over(c)
        if pts:
            commit(pts)
            local[idx] = pts

    # perangkat komunikasi bersebelahan: sambung langsung di baris komunikasi
    def dev_adjacent(a_, b_):
        return abs(devs.index(a_) - devs.index(b_)) == 1
    direct_dev = [i for i, c in enumerate(comm) if c['a'] in dev_set and c['b'] in dev_set
                  and dev_adjacent(c['a'], c['b'])]
    laned = [i for i in range(len(comm)) if i not in local and i not in direct_dev]

    y_top = max([pos[k][1] + half_h(k) for k in pos] + [0.0]) + 0.4
    y_top = max([y_top] + [p[1] + 0.25 for pts in local.values() for p in pts])
    y_pow_low = min([pos[k][1] - half_h(k) for k in pos] + [0.0])
    lane_gap = 0.16
    y_lane0 = y_pow_low - 0.32
    if devs:
        y_comm = y_lane0 - 0.12 * max(len(laned) - 1, 0) - 0.5 - _BOX_H / 2
        pitch = max(bw + 0.6, 1.85)           # label 2 baris tidak saling tumpuk
        span_d = (len(devs) - 1) * pitch
        cx0 = (bus_l + bus_r) / 2 - span_d / 2
        for i, k in enumerate(devs):
            pos[k] = (cx0 + i * pitch, y_comm)
            boxes[k] = bbox(k)
        y_low = y_comm - _BOX_H / 2
    else:
        y_low = y_lane0 - lane_gap * max(len(laned) - 1, 0) - 0.15

    for i in direct_dev:
        c = comm[i]
        a_, b_ = sorted((c['a'], c['b']), key=lambda k: pos[k][0])
        for j in range(5):
            y = pos[a_][1] + (0.2, -0.2, 0.07, -0.07, 0.33)[j]
            pts = [(boxes[a_][2], y), (boxes[b_][0], y)]
            if path_ok(pts, {a_, b_}):
                break
        commit(pts)
        local[i] = pts

    # ---------- A*: jalur ortogonal di grid (hindari kotak & garis sejajar) ----
    import heapq
    import numpy as np
    GX = 0.1
    gx0 = min(bus_l - 2.0, min(bb[0] for bb in boxes.values()) - 0.8)
    gx1 = max(bus_r + 2.4, max(bb[2] for bb in boxes.values()) + 1.2)
    gy0 = y_low - 0.6
    gy1 = y_top + 0.6
    NI = int((gx1 - gx0) / GX) + 1
    NJ = int((gy1 - gy0) / GX) + 1

    def gi(x):
        return int(round((x - gx0) / GX))

    def gj(y):
        return int(round((y - gy0) / GX))
    cell_block = np.zeros((NI, NJ), bool)
    vblock = np.zeros((NI, NJ), bool)       # dilarang bergerak vertikal di sel ini
    hblock = np.zeros((NI, NJ), bool)       # dilarang bergerak horizontal
    near_v = np.zeros((NI, NJ), bool)       # bersebelahan dgn garis vertikal (biaya)
    near_h = np.zeros((NI, NJ), bool)

    def mark_box(bb, pad=0.07):
        i0, i1 = max(0, gi(bb[0] - pad)), min(NI - 1, gi(bb[2] + pad))
        j0, j1 = max(0, gj(bb[1] - pad)), min(NJ - 1, gj(bb[3] + pad))
        cell_block[i0:i1 + 1, j0:j1 + 1] = True

    def mark_v(x, y0, y1, clear=0):
        i = gi(x)
        j0, j1 = max(0, gj(y0) - 1), min(NJ - 1, gj(y1) + 1)
        for ii in range(i - clear, i + clear + 1):
            if 0 <= ii < NI:
                vblock[ii, j0:j1 + 1] = True
        for ii in (i - clear - 2, i - clear - 1, i + clear + 1, i + clear + 2):
            if 0 <= ii < NI:
                near_v[ii, j0:j1 + 1] = True

    def mark_h(y, x0, x1, clear=0):
        j = gj(y)
        i0, i1 = max(0, gi(x0) - 1), min(NI - 1, gi(x1) + 1)
        for jj in range(j - clear, j + clear + 1):
            if 0 <= jj < NJ:
                hblock[i0:i1 + 1, jj] = True
        for jj in (j - clear - 2, j - clear - 1, j + clear + 1, j + clear + 2):
            if 0 <= jj < NJ:
                near_h[i0:i1 + 1, jj] = True
    for k_, bb in boxes.items():
        mark_box(bb, pad=0.08)
    for (x_, a0, a1) in pv_segs:
        mark_v(x_, a0, a1, clear=1)             # jarak bebas dari kabel daya
    for (x_, a0, a1) in cv_used:
        mark_v(x_, a0, a1)
    for (y_, a0, a1) in ph_segs:
        mark_h(y_, a0, a1, clear=1)
    for (y_, a0, a1) in ch_used:
        mark_h(y_, a0, a1)
    # pita lane: horizontal murah di bawah sistem daya, mahal di atasnya
    band_hi = gj(y_pow_low - 0.2)
    h_extra = np.full(NJ, 2.2)
    h_extra[:max(0, band_hi) + 1] = 0.0

    def ports(k):
        """Titik port (x, y, arah keluar) di tepi perangkat."""
        xk, yk = pos[k]
        bb = boxes[k]
        out_ = []
        if k in dev_set:
            n_ = top_n.get(k, 0)
            for o in (0.3, 0.55, 0.8, 1.05, 1.3, 1.55, 1.8, 2.05):
                out_.append((bb[0] + o + 0.0 * n_, bb[3], (0, 1)))
            out_ += [(bb[0], yk + 0.2, (-1, 0)), (bb[2], yk + 0.2, (1, 0)),
                     (bb[0], yk - 0.2, (-1, 0)), (bb[2], yk - 0.2, (1, 0))]
        else:
            hh = (bb[3] - bb[1]) / 2
            for dy in ((0.22, 0.1, -0.02, -0.14) if hh > 0.3 else (0.0,)):
                out_.append((bb[2], yk + dy, (1, 0)))
                out_.append((bb[0], yk + dy, (-1, 0)))
        return out_

    def astar(ka, kb):
        """Cari jalur terbaik antar port ka → kb. Kembalikan polyline atau None."""
        starts = {}
        for (px, py, (dx, dy)) in ports(ka):
            i, j = gi(px) + 2 * dx, gj(py) + 2 * dy
            if 0 <= i < NI and 0 <= j < NJ and not cell_block[i, j]:
                starts[(i, j)] = (px, py, (dx, dy))
        goals = {}
        for (px, py, (dx, dy)) in ports(kb):
            i, j = gi(px) + 2 * dx, gj(py) + 2 * dy
            if 0 <= i < NI and 0 <= j < NJ and not cell_block[i, j]:
                goals[(i, j)] = (px, py, (dx, dy))
        if not starts or not goals:
            return None
        gl = list(goals)

        def h(i, j):
            return min(abs(i - a) + abs(j - b) for a, b in gl)
        BEND = 8.0
        pq, best, came = [], {}, {}
        for (i, j), (px, py, d) in starts.items():
            st = (i, j, d)
            best[st] = 0.0
            heapq.heappush(pq, (h(i, j), 0.0, st))
        found = None
        n_iter = 0
        while pq and n_iter < 400000:
            n_iter += 1
            f, g, st = heapq.heappop(pq)
            if g > best.get(st, 1e18) + 1e-9:
                continue
            i, j, d = st
            if (i, j) in goals:
                found = st
                break
            for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + nd[0], j + nd[1]
                if not (0 <= ni < NI and 0 <= nj < NJ) or cell_block[ni, nj]:
                    continue
                if nd[1] != 0 and (vblock[i, j] or vblock[ni, nj]):
                    continue
                if nd[0] != 0 and (hblock[i, j] or hblock[ni, nj]):
                    continue
                c = 1.0
                if nd != d:
                    c += BEND
                if nd[0] != 0:
                    c += h_extra[nj]
                if nd[1] != 0 and near_v[ni, nj]:
                    c += 2.5
                if nd[0] != 0 and near_h[ni, nj]:
                    c += 2.5
                ns = (ni, nj, nd)
                ng = g + c
                if ng < best.get(ns, 1e18) - 1e-9:
                    best[ns] = ng
                    came[ns] = st
                    heapq.heappush(pq, (ng + h(ni, nj), ng, ns))
        if found is None:
            return None
        cells = [found]
        while cells[-1] in came:
            cells.append(came[cells[-1]])
        cells.reverse()
        s0 = starts[(cells[0][0], cells[0][1])]
        g0 = goals[(cells[-1][0], cells[-1][1])]
        cpts = [(gx0 + i * GX, gy0 + j * GX) for (i, j, _d) in cells]
        pts = [(s0[0], s0[1])]
        # port → sel pertama: lurus menurut arah port, lalu siku
        c0 = cpts[0]
        if s0[2][0] != 0:
            pts.append((c0[0], s0[1]))
        else:
            pts.append((s0[0], c0[1]))
        pts.append(c0)
        pts += cpts[1:]
        cN = cpts[-1]
        if g0[2][0] != 0:
            pts.append((cN[0], g0[1]))
        else:
            pts.append((g0[0], cN[1]))
        pts.append((g0[0], g0[1]))
        # rapikan: buang titik kolinear
        dedup = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - dedup[-1][0]) > 1e-9 or abs(p[1] - dedup[-1][1]) > 1e-9:
                dedup.append(p)
        pts = dedup
        simp = [pts[0]]
        for p in pts[1:]:
            if len(simp) >= 2:
                (x1_, y1_), (x2_, y2_) = simp[-2], simp[-1]
                if (abs(x1_ - x2_) < 1e-9 and abs(x2_ - p[0]) < 1e-9) or \
                        (abs(y1_ - y2_) < 1e-9 and abs(y2_ - p[1]) < 1e-9):
                    simp[-1] = p
                    continue
            if abs(p[0] - simp[-1][0]) > 1e-9 and abs(p[1] - simp[-1][1]) > 1e-9:
                simp.append((simp[-1][0], p[1]))   # jaga ortogonal
            simp.append(p)
        return simp

    lane_pts = {}
    laned.sort(key=lambda i: (abs(pos[comm[i]['a']][0] - pos[comm[i]['b']][0])
                              + abs(pos[comm[i]['a']][1] - pos[comm[i]['b']][1])))
    for i in laned:
        c = comm[i]
        pts = astar(c['a'], c['b'])
        if pts is None:
            _FAILED.append((c['a'], c['b']))
            # cadangan: garis sederhana lewat bawah
            ba, bb_ = boxes[c['a']], boxes[c['b']]
            ya, yb = pos[c['a']][1], pos[c['b']][1]
            xa, xb = ba[2] + 0.15, bb_[2] + 0.22
            yl = y_low - 0.2
            pts = [(ba[2], ya), (xa, ya), (xa, yl), (xb, yl), (xb, yb), (bb_[2], yb)]
        commit(pts)
        for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
            if abs(xa - xb) < 1e-9:
                mark_v(xa, min(ya, yb), max(ya, yb))
            else:
                mark_h(ya, min(xa, xb), max(xa, xb))
        lane_pts[i] = pts
    route_by_idx = {}
    for i, pts in list(local.items()) + list(lane_pts.items()):
        routes.append((pts, comm[i]['kind']))
        route_by_idx[i] = pts

    # ------------------------------------------------------ ukuran kanvas ----
    y_bot = y_low - (0.95 if not comm else 1.45)
    x_l, x_r = bus_l - 2.2, bus_r + 0.6
    for k, (xk, _yk) in pos.items():
        if _shape(nodes, k) == 'xfmr':
            txt = max(len(str(nodes[k]['_label'])), len(str(nodes[k]['_rating'] or '')))
            x_r = max(x_r, xk + 0.45 + 0.13 * txt)
    for pts, _k in routes:
        x_r = max(x_r, max(p[0] for p in pts) + 0.2)
    for k in devs:                                # baris perangkat komunikasi
        if k in boxes:
            x_l = min(x_l, boxes[k][0] - 0.5)
            x_r = max(x_r, boxes[k][2] + 0.5)
    fw = 7.2
    fh = max(2.8, min(10.5, fw * (y_top - y_bot) / (x_r - x_l)))
    fs = 7.0 if ncol <= 6 else (6.3 if ncol <= 8 else 5.6)
    fs = max(4.2, min(fs, 7.0 * 16.0 / max(16.0, x_r - x_l)))   # diagram sangat lebar

    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(fw, fh))
        ax.set_xlim(x_l, x_r)
        ax.set_ylim(y_bot, y_top)
        ax.axis('off')
        dash = {'ac': '-', 'dc': (0, (4, 1.6))}

        def draw_node(k):
            xk, yk = pos[k]
            n = nodes[k]
            sh = _shape(nodes, k)
            col = family_color(TYPES[n['type']][2])
            if sh == 'box':
                ax.add_patch(FancyBboxPatch(
                    (xk - bw / 2, yk - _BOX_H / 2), bw, _BOX_H,
                    boxstyle='round,pad=0.02,rounding_size=0.12',
                    fc=_tint(col), ec=col, lw=1.1, zorder=4))
                # lebar bungkus = muatan kotak (diagram lebar → huruf per kotak sedikit)
                fit = bw * 72.0 * fw / max(1e-6, x_r - x_l) / (0.62 * fs)
                title = _wrap(n['_label'], max(9, min(20 if fs >= 7 else 17, int(fit))))
                two = '\n' in title
                rt = str(n['_rating'] or '')
                rlines = [rt]
                if len(rt) > 22 and ' · ' in rt:
                    rlines = rt.split(' · ', 1)
                elif len(rt) > 26:
                    rlines = [rt[:26], rt[26:52]]
                ty = yk + (0.12 if rt else 0) + (0.05 if two else 0) + \
                    (0.08 if len(rlines) > 1 else 0)
                ax.text(xk, ty, title, ha='center', va='center', fontsize=fs,
                        fontweight='bold', color=K.INK, zorder=5, linespacing=1.0)
                if rt:
                    y0r = yk - (0.22 if len(rlines) > 1 else 0.27)
                    for i, ln in enumerate(rlines[:2]):
                        ax.text(xk, y0r - i * 0.17, ln.strip(), ha='center', va='center',
                                fontsize=fs - (1.3 if len(rlines) > 1 else 0.9),
                                color=K.GREY, zorder=5)
            elif sh == 'breaker':
                ax.add_patch(plt.Rectangle((xk - 0.16, yk - 0.16), 0.32, 0.32,
                                           fc='white', ec=K.INK, lw=0.8, zorder=5))
                if n.get('label'):
                    ax.text(xk + 0.28, yk, n['label'], fontsize=fs - 1, color=K.GREY,
                            va='center', zorder=5)
            elif sh == 'xfmr':
                for dy in (0.14, -0.14):
                    ax.add_patch(Circle((xk, yk + dy), 0.24, fc='white',
                                        ec='#4B5563', lw=1.0, zorder=5))
                ax.text(xk + 0.36, yk + 0.08, n['_label'], fontsize=fs - 0.4,
                        fontweight='bold', color=K.INK, va='center', zorder=5)
                if n['_rating']:
                    ax.text(xk + 0.36, yk - 0.22, n['_rating'], fontsize=fs - 1,
                            color=K.GREY, va='center', zorder=5)

        # kabel daya
        for xs_, ys_, col, kind in plines:
            ax.plot(xs_, ys_, color=col, lw=1.1, ls=dash.get(kind, '-'), zorder=2)
            if kind == 'dc':
                xm = xs_[-1]
                ym = (ys_[-1] + ys_[-2]) / 2
                ax.text(xm + 0.12, ym, 'DC', fontsize=fs - 1.4, color=K.GREY,
                        va='center', zorder=3)
        # rel
        ax.plot([bus_l, bus_r], [0, 0], color=K.DARK, lw=3.2, solid_capstyle='butt',
                zorder=3)
        ax.text(bus_l - 0.15, 0, nodes[main]['_label'] +
                (f"\n{nodes[main]['_rating']}" if nodes[main].get('_rating') else ''),
                ha='right', va='center', fontsize=fs, color=K.DARK, fontweight='bold',
                zorder=5)
        for k, (lft, rgt) in sec_bus.items():
            yk = pos[k][1]
            col = K.DARK if nodes[k]['type'] == 'ac_bus' else '#7C2D12'
            ax.plot([lft, rgt], [yk, yk], color=col,
                    lw=2.4 if nodes[k]['type'] == 'ac_bus' else 2.0,
                    solid_capstyle='butt', zorder=3)
            ax.text(lft - 0.1, yk, nodes[k]['_label'], ha='right', va='center',
                    fontsize=fs - 0.8, color=col, fontweight='bold', zorder=5)
        for k in pos:
            if _shape(nodes, k) != 'bus':
                draw_node(k)
        # kabel komunikasi
        for pts, kind in routes:
            st = COMM_STYLE.get(kind, COMM_STYLE['wired'])
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=st[0], ls=st[1],
                    lw=0.95, zorder=1.6, solid_capstyle='butt')
            if kind == 'wireless':
                # penanda di segmen terpanjang
                best = max(zip(pts[:-1], pts[1:]),
                           key=lambda s_: abs(s_[0][0] - s_[1][0]) + abs(s_[0][1] - s_[1][1]))
                xm = (best[0][0] + best[1][0]) / 2; ym = (best[0][1] + best[1][1]) / 2
                ax.text(xm, ym, '((·))', ha='center', va='center', fontsize=fs - 1.2,
                        color=st[0], zorder=6,
                        bbox=dict(boxstyle='round,pad=0.08', fc='white', ec='none'))
        # grup bentuk pengguna
        for g in A['groups']:
            bb = [boxes[k] for k in g['members'] if k in boxes]
            if not bb:
                continue
            mem = set(g['members'])
            for i_, c in enumerate(comm):
                if c['a'] in mem and c['b'] in mem and i_ in route_by_idx:
                    for (px, py) in route_by_idx[i_]:
                        bb.append((px, py, px, py))
            gx0 = min(b_[0] for b_ in bb) - 0.22; gy0 = min(b_[1] for b_ in bb) - 0.2
            gx1 = max(b_[2] for b_ in bb) + 0.22
            gy1 = max(b_[3] for b_ in bb) + (0.42 if g['label'] else 0.2)
            ax.add_patch(FancyBboxPatch((gx0, gy0), gx1 - gx0, gy1 - gy0,
                                        boxstyle='round,pad=0.0,rounding_size=0.15',
                                        fc='none', ec='#6B7280', lw=0.8,
                                        ls=(0, (4, 2.5)), zorder=0.6))
            if g['label']:
                ax.text(gx0 + 0.1, gy1 - 0.05, g['label'], ha='left', va='top',
                        fontsize=fs - 1, style='italic', color='#4B5563', zorder=6)
        # legenda
        items = [('-', K.DARK, 1.2, L('Rel AC / daya AC', 'AC bus / AC power'))]
        if any(v == 'dc' for v in A['kind'].values()):
            items.append(((0, (4, 1.6)), K.GREY, 1.0, L('Daya DC', 'DC power')))
        for kd in COMM_KINDS:
            if any(c['kind'] == kd for c in comm):
                st = COMM_STYLE[kd]
                items.append((st[1], st[0], 0.95, L(st[3], st[2])))
        span = x_r - x_l
        ly = y_bot + (0.82 if comm else 0.35)
        x0 = x_l + 0.1
        for ls, col, lw_, lab in items:
            wdt = span * (0.07 + 0.0105 * len(lab))
            if x0 + wdt > x_r:
                x0 = x_l + 0.1; ly -= 0.36
            ax.plot([x0, x0 + span * 0.04], [ly, ly], color=col, lw=lw_, ls=ls)
            ax.text(x0 + span * 0.05, ly, lab, fontsize=6.2, color=K.GREY, va='center')
            x0 += wdt
        if any(_shape(nodes, k) == 'breaker' for k in pos):
            if x0 + span * 0.2 > x_r:
                x0 = x_l + 0.1; ly -= 0.36
            ax.add_patch(plt.Rectangle((x0, ly - 0.13), 0.26, 0.26, fc='white',
                                       ec=K.INK, lw=0.8))
            ax.text(x0 + 0.4, ly, L('Pemutus (CB)', 'Circuit breaker'), fontsize=6.2,
                    color=K.GREY, va='center')
        fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    return fig


# ================================================ tata letak SESUAI GAMBAR ===
def _clean_label(label, rating):
    """Label kartu: buang rating yang sudah tampil terpisah & kata sambung
    menggantung (mis. 'LV SWG 0.4kV FOR' → 'LV SWG 0.4kV')."""
    import re
    t = ' '.join(str(label or '').split())
    for r in re.split(r',\s*', str(rating or '')):
        r = r.strip()
        if r:
            num = re.escape(r.split()[0])
            t = re.sub(num + r'\s*' + re.escape(r.split()[-1]) + r'\b', '', t, flags=re.I) \
                if len(r.split()) > 1 else t
    t = re.sub(r'\b(for|to|of|and|&)\s*$', '', t.strip(' ,;:-'), flags=re.I)
    return ' '.join(t.split()).strip(' ,;:-')


_TW = {}


def _text_w(s, bold=True):
    """Lebar teks (pt) pada ukuran huruf 1 — diukur dari glyph (bukan perkiraan)."""
    key = (s, bold)
    if key not in _TW:
        try:
            from matplotlib.textpath import TextPath
            from matplotlib.font_manager import FontProperties
            ext = TextPath((0, 0), s, size=1.0,
                           prop=FontProperties(weight='bold' if bold else 'normal')).get_extents()
            _TW[key] = max(0.3 * len(s), float(ext.width) + 0.08)
        except Exception:                          # pragma: no cover
            _TW[key] = 0.68 * len(s)
    return _TW[key]


def _fit_text(txt, w_pt, h_pt, fs_max=6.2, fs_min=3.2, max_lines=4, bold=True):
    """Pilih bungkus & ukuran huruf agar teks MUAT di kotak (w_pt × h_pt).

    Kata dibungkus per spasi; kata yang tetap terlalu panjang dipenggal ke baris
    berikutnya (tanda '-'), sehingga teks tidak pernah melewati tepi kartu."""
    words = str(txt).split()
    if not words:
        return fs_max, ''
    total = len(' '.join(words))
    longest = max(len(w) for w in words)

    def best_of(mode):
        cs = []
        for width in range(1, max(longest, total) + 1):
            wrapped = _wrap_n(txt, width, max_lines, mode)
            if '…' in wrapped:
                continue
            lines = wrapped.split('\n')
            lw = max(_text_w(x, bold) for x in lines)
            fs = min(fs_max, w_pt / max(lw, 1e-6), h_pt / (1.22 * len(lines)))
            cs.append((fs, len(lines), wrapped))
        if not cs:
            return None
        if mode:
            # penggalan: sesedikit mungkin baris asalkan huruf ≥ batas minimum
            ok = [c for c in cs if c[0] >= fs_min]
            if ok:
                c = min(ok, key=lambda c: (c[1], -c[0]))
                return c[0], c[2]
        c = max(cs, key=lambda c: c[0])
        return c[0], c[2]
    # 1) utuh per kata  2) penggal di tanda '-' yang ada  3) penggal bebas
    best = best_of(None)
    for mode in ('hyphen', 'any'):
        if best is not None and (best[0] >= 0.72 * fs_max or best[0] >= fs_min):
            break
        alt = best_of(mode)
        if alt is not None and (best is None or alt[0] > best[0] * 1.15):
            best = alt
    if best is None:
        wrapped = _wrap_n(txt, max(4, longest), max_lines, 'any')
        lines = wrapped.split('\n')
        lw = max(_text_w(x, bold) for x in lines)
        best = (min(fs_max, w_pt / max(lw, 1e-6), h_pt / (1.22 * len(lines))), wrapped)
    return best


def _wrap_n(txt, width, max_lines, brk=None):
    """brk: None (utuh) | 'hyphen' (penggal di '-' yang ada) | 'any' (penggal bebas)."""
    import re as _re
    words = []
    for w in str(txt).split():
        if brk and len(w) > width and '-' in w[:-1]:
            parts = _re.findall(r'[^-]+-?|-', w)           # "MV-PVBS-2" → MV- PVBS- 2
            words.extend(parts[:-1]); w = parts[-1]
        if brk == 'any' and len(w) > width and width >= 3:
            while len(w) > width:
                words.append(w[:width - 1] + '-'); w = w[width - 1:]
        words.append(w)
    lines, cur = [], ''
    for w in words:
        glue = '' if cur.endswith('-') else ' '
        if len(cur) + len(w) + (len(glue) if cur else 0) > width and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + glue + w) if cur else w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:max(1, width - 1)] + '…'
    return '\n'.join(lines)


def _route_grid(boxes, x0, y0, nx, ny, cell):
    """Grid pemilik sel: indeks kotak (-1 kosong)."""
    own = np.full((ny, nx), -1, np.int32)
    for k, (bx0, by0, bx1, by1) in enumerate(boxes):
        i0 = max(0, int((bx0 - x0) / cell)); i1 = min(nx - 1, int((bx1 - x0) / cell))
        j0 = max(0, int((by0 - y0) / cell)); j1 = min(ny - 1, int((by1 - y0) / cell))
        own[j0:j1 + 1, i0:i1 + 1] = k
    return own


def _anchor(bx, pt):
    """Titik sambung pada tepi kotak bx menuju titik pt (sama dgn editor):
    tegak lurus bila pt berhadapan dengan sisi kotak, selain itu tengah sisi."""
    x0, y0, x1, y1 = bx
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    w, h = x1 - x0, y1 - y0
    px, py = pt
    if x0 + 2 <= px <= x1 - 2 and (py < y0 or py > y1):
        return (px, y0 if py < cy else y1), 'v'
    if y0 + 2 <= py <= y1 - 2 and (px < x0 or px > x1):
        return (x0 if px < cx else x1, py), 'h'
    dx, dy = px - cx, py - cy
    if abs(dy) * w >= abs(dx) * h:
        return (cx, cy + (h / 2 if dy > 0 else -h / 2)), 'v'
    return (cx + (w / 2 if dx > 0 else -w / 2), cy), 'h'


def edge_polyline(bxa, bxb, pts):
    """Polyline ortogonal a→b melewati titik belok (algoritme = editor)."""
    pts = [(_f(q[0]), _f(q[1])) for q in (pts or [])]
    ca = ((bxa[0] + bxa[2]) / 2.0, (bxa[1] + bxa[3]) / 2.0)
    cb = ((bxb[0] + bxb[2]) / 2.0, (bxb[1] + bxb[3]) / 2.0)
    if not pts:
        pa, oa = _anchor(bxa, cb)
        pb, ob = _anchor(bxb, ca)
        pl = [pa]
        if oa == 'v' and ob == 'v':
            if abs(pa[0] - pb[0]) >= 1:
                my = (pa[1] + pb[1]) / 2
                pl += [(pa[0], my), (pb[0], my)]
        elif oa == 'h' and ob == 'h':
            mx = (pa[0] + pb[0]) / 2
            pl += [(mx, pa[1]), (mx, pb[1])]
        elif oa == 'v':
            pl.append((pa[0], pb[1]))
        else:
            pl.append((pb[0], pa[1]))
        return pl + [pb]
    pa, oa = _anchor(bxa, pts[0])
    pb, ob = _anchor(bxb, pts[-1])
    seq = pts + [pb]
    pl, cur, d = [pa], pa, oa
    for idx, q in enumerate(seq):
        last = idx == len(seq) - 1
        if abs(cur[0] - q[0]) < 0.5 or abs(cur[1] - q[1]) < 0.5:
            pl.append(q)
        else:
            if last:
                corner = (q[0], cur[1]) if ob == 'v' else (cur[0], q[1])
            else:
                corner = (cur[0], q[1]) if d == 'v' else (q[0], cur[1])
            pl += [corner, q]
        cur = q
    return pl


def drawing_routes(design, cfg=None, reroute=False):
    """Rute kabel tata letak 'sesuai gambar' → {id_sambungan: [[x, y], …]} berupa
    TITIK BELOK (tanpa ujung) utk disimpan sbg 'pts' editor. reroute=True
    mengabaikan titik belok yang sudah ada (rapikan ulang semua rute)."""
    out = figure_drawing(design, cfg or {}, _routes_only=True, reroute=reroute)
    res = {}
    for eid, poly in (out or {}).items():
        mid = [[round(q[0], 1), round(q[1], 1)] for q in poly[1:-1]]
        if not mid and len(poly) == 2:          # lurus: satu titik tengah agar posisi
            mid = [[round((poly[0][0] + poly[1][0]) / 2, 1),       # sambung terkunci
                    round((poly[0][1] + poly[1][1]) / 2, 1)]]
        res[eid] = mid
    return res


def figure_drawing(design, cfg, load_stats=None, analysis=None, _routes_only=False,
                   reroute=False):
    """Gambar ulang dengan PENEMPATAN SESUAI GAMBAR PENGGUNA (posisi & ukuran
    kartu/rel dari editor = dari gambar impor). Kartu diberi gaya laporan
    (warna famili, label & rating rapi, huruf otomatis muat) dan SEMUA kabel
    dirutekan ulang secara ortogonal (A* grid): tidak menembus kotak, tidak
    berimpit dengan kabel lain (persilangan tegak lurus diizinkan); kabel daya
    dirutekan lebih dulu, lalu kabel komunikasi."""
    import heapq
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle, Polygon as MPoly
    from .charts import RC, _tint
    A = analysis or analyze(design, cfg, load_stats)
    anodes = A.get('nodes', {})
    raw = [n for n in (design or {}).get('nodes', []) if n.get('type') in TYPES]
    if not raw:
        return None
    byid = {str(n.get('id')): n for n in raw}

    def lab_of(n):
        a = anodes.get(str(n.get('id'))) or {}
        return a.get('_label') or n.get('label') or type_label(n['type'])

    def rat_of(n):
        if str(n.get('rating') or '').strip() or n['type'] in COMM_DEVICES:
            return str(n.get('rating') or '').strip()   # tanpa rating otomatis utk perangkat komunikasi
        a = anodes.get(str(n.get('id'))) or {}
        return str(a.get('_rating') or '')

    # --- ukuran kartu: dari impor (bw/bh) atau diperkirakan dari jarak antar kartu
    cards = [n for n in raw if n['type'] not in NON_TOPO and n['type'] not in ('ac_bus', 'dc_bus')]
    pts = [(_f(n.get('x')), _f(n.get('y'))) for n in cards]

    def pitch(axis):
        ds = []
        for i, p in enumerate(pts):
            best = None
            for j, q in enumerate(pts):
                if i == j or abs(p[1 - axis] - q[1 - axis]) > 25:
                    continue
                d = abs(p[axis] - q[axis])
                if d > 5 and (best is None or d < best):
                    best = d
            if best:
                ds.append(best)
        return float(np.median(ds)) if ds else 0.0
    px, py = pitch(0), pitch(1)
    base = min([v for v in (px, py) if v > 0] or [180.0])
    cw0 = 0.68 * (px or base)
    ch0 = 0.68 * (py or base)
    cw0, ch0 = max(60.0, min(cw0, 1.6 * ch0)), max(40.0, min(ch0, 1.2 * cw0))

    geo = {}                                           # id → (x0, y0, x1, y1)
    for n in raw:
        t = n['type']
        if t in NON_TOPO:
            continue
        x, y = _f(n.get('x')), _f(n.get('y'))
        if t in ('ac_bus', 'dc_bus'):
            w = _f(n.get('w'), 3 * cw0); h = _f(n.get('bh'), 0.0) or 0.62 * ch0
        else:
            w = _f(n.get('bw'), 0.0) or cw0; h = _f(n.get('bh'), 0.0) or ch0
        geo[str(n['id'])] = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    if not geo:
        return None
    ids = list(geo)
    boxes = [geo[k] for k in ids]
    kidx = {k: i for i, k in enumerate(ids)}

    # --- sambungan (jenis efektif) ---
    conns = []
    for e in (design or {}).get('edges', []):
        a, b = str(e.get('src')), str(e.get('dst'))
        if a not in geo or b not in geo or a == b:
            continue
        k = effective_kind(e.get('kind'), byid[a]['type'], byid[b]['type'])
        conns.append((a, b, k, str(e.get('id')), None if reroute else e.get('pts'),
                      e.get('ports') if isinstance(e.get('ports'), dict) else None))
    # daya dulu (pendek → panjang), lalu komunikasi
    def dist(c):
        (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = geo[c[0]], geo[c[1]]
        return abs((ax0 + ax1) - (bx0 + bx1)) + abs((ay0 + ay1) - (by0 + by1))
    conns.sort(key=lambda c: (c[2] in COMM_KINDS, dist(c)))

    # --- grid perutean ---
    cell = max(4.0, min(cw0, ch0) / 9.0)
    X0 = min(b[0] for b in boxes) - 6 * cell; Y0 = min(b[1] for b in boxes) - 6 * cell
    X1 = max(b[2] for b in boxes) + 6 * cell; Y1 = max(b[3] for b in boxes) + 6 * cell
    nx, ny = int((X1 - X0) / cell) + 1, int((Y1 - Y0) / cell) + 1
    own = _route_grid(boxes, X0, Y0, nx, ny, cell)
    near = np.zeros((ny, nx), bool)                    # sel bersebelahan kotak
    occ = own >= 0
    near[1:] |= occ[:-1]; near[:-1] |= occ[1:]; near[:, 1:] |= occ[:, :-1]; near[:, :-1] |= occ[:, 1:]
    near &= ~occ
    useH = np.zeros((ny, nx), np.int16); useV = np.zeros((ny, nx), np.int16)
    DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))          # kanan, bawah, kiri, atas

    _SIDE = {'top': 3, 'bottom': 1, 'left': 2, 'right': 0}

    def ports(k, is_goal, fixed=None):
        """Sel di luar tiap sisi kotak + arah keluar (atau masuk utk tujuan).
        fixed = [sisi, t] → hanya titik sambung asli dari gambar."""
        bx0, by0, bx1, by1 = boxes[k]
        i0 = int((bx0 - X0) / cell); i1 = int((bx1 - X0) / cell)
        j0 = int((by0 - Y0) / cell); j1 = int((by1 - Y0) / cell)
        if fixed and len(fixed) >= 2 and fixed[0] in _SIDE:
            d = _SIDE[fixed[0]]
            t = min(0.97, max(0.03, _f(fixed[1], 0.5)))
            if d in (1, 3):
                ic = int(round(i0 + t * (i1 - i0))); jc = j0 - 1 if d == 3 else j1 + 1
                cand = [(ic + o, jc) for o in (0, -1, 1)]
            else:
                jc = int(round(j0 + t * (j1 - j0))); ic = i0 - 1 if d == 2 else i1 + 1
                cand = [(ic, jc + o) for o in (0, -1, 1)]
            out = [(i, j, d, 0.6 * abs(o)) for (i, j), o in zip(cand, (0, 1, 1))
                   if 0 <= i < nx and 0 <= j < ny]
            if is_goal:
                out = [(i, j, (dd + 2) % 4, c) for i, j, dd, c in out]
            if out:
                return out
        ic, jc = (i0 + i1) / 2.0, (j0 + j1) / 2.0
        wbus = byid[ids[k]]['type'] in ('ac_bus', 'dc_bus')
        cw_ = 0.04 if wbus else 0.35
        out = []
        for i in range(i0 + 1, i1):
            for j, d in ((j0 - 1, 3), (j1 + 1, 1)):
                if 0 <= j < ny:
                    out.append((i, j, d, cw_ * abs(i - ic)))
        for j in range(j0 + 1, j1):
            for i, d in ((i0 - 1, 2), (i1 + 1, 0)):
                if 0 <= i < nx:
                    out.append((i, j, d, cw_ * abs(j - jc) + (0.6 if wbus else 0.0)))
        if is_goal:
            out = [(i, j, (d + 2) % 4, c) for i, j, d, c in out]   # arah MASUK
        return out

    def route(ka, kb, pa=None, pb=None):
        gb = boxes[kb]
        gi0 = (gb[0] - X0) / cell; gi1 = (gb[2] - X0) / cell
        gj0 = (gb[1] - Y0) / cell; gj1 = (gb[3] - Y0) / cell
        goals = {}
        for i, j, d, c in ports(kb, True, pb):
            if own[j, i] < 0:
                goals[(i, j)] = (d, c)
        if not goals:
            return None
        heap, best, prev = [], {}, {}
        for i, j, d, c in ports(ka, False, pa):
            if own[j, i] >= 0:
                continue
            st = (i, j, d)
            g = c + (useH[j, i] + useV[j, i]) * 20.0
            if g < best.get(st, 1e18):
                best[st] = g; prev[st] = None
                h = max(gi0 - i, 0, i - gi1) + max(gj0 - j, 0, j - gj1)
                heapq.heappush(heap, (g + h, g, st))
        done = None
        exp = 0
        while heap:
            f, g, st = heapq.heappop(heap)
            if g > best.get(st, 1e18):
                continue
            i, j, d = st
            if (i, j) in goals:
                gd, gc = goals[(i, j)]
                tot = g + gc + (4.0 if d != gd else 0.0)
                if done is None or tot < done[0]:
                    done = (tot, st)
                if f >= done[0]:
                    break
            exp += 1
            if exp > 60000:
                break
            for nd in (d, (d + 1) % 4, (d + 3) % 4):
                di, dj = DIRS[nd]
                ii, jj = i + di, j + dj
                if not (0 <= ii < nx and 0 <= jj < ny) or own[jj, ii] >= 0:
                    continue
                c = 1.0 + (4.0 if nd != d else 0.0)
                horiz = nd in (0, 2)
                c += (useH[jj, ii] if horiz else useV[jj, ii]) * 60.0     # berimpit
                c += (useV[jj, ii] if horiz else useH[jj, ii]) * 7.0      # bersilang
                # jaga jarak dari kabel sejajar (hindari garis berdempet)
                if horiz:
                    if (jj > 0 and useH[jj - 1, ii]) or (jj + 1 < ny and useH[jj + 1, ii]):
                        c += 1.5
                elif (ii > 0 and useV[jj, ii - 1]) or (ii + 1 < nx and useV[jj, ii + 1]):
                    c += 1.5
                if near[jj, ii]:
                    c += 1.5
                ns = (ii, jj, nd)
                ng = g + c
                if ng < best.get(ns, 1e18):
                    best[ns] = ng; prev[ns] = st
                    h = max(gi0 - ii, 0, ii - gi1) + max(gj0 - jj, 0, jj - gj1)
                    heapq.heappush(heap, (ng + h, ng, ns))
        if done is None:
            return None
        path, st = [], done[1]
        while st is not None:
            path.append(st); st = prev[st]
        path.reverse()
        return path

    def cxy(i, j):
        return X0 + (i + 0.5) * cell, Y0 + (j + 0.5) * cell

    def edge_pt(k, i, j, d_out):
        """Titik tepi kotak k tegak lurus dari sel port (i, j)."""
        x, y = cxy(i, j)
        bx0, by0, bx1, by1 = boxes[k]
        if d_out == 3:
            return x, by0
        if d_out == 1:
            return x, by1
        if d_out == 2:
            return bx0, y
        return bx1, y

    def mark(poly):
        for (xa, ya), (xb, yb) in zip(poly[:-1], poly[1:]):
            ia, ja = int((xa - X0) / cell), int((ya - Y0) / cell)
            ib, jb = int((xb - X0) / cell), int((yb - Y0) / cell)
            if ja == jb:
                for i in range(min(ia, ib), max(ia, ib) + 1):
                    if 0 <= i < nx and 0 <= ja < ny:
                        useH[ja, i] += 1
            elif ia == ib:
                for j in range(min(ja, jb), max(ja, jb) + 1):
                    if 0 <= ia < nx and 0 <= j < ny:
                        useV[j, ia] += 1

    routes = []
    # 1) rute yang sudah diedit pengguna (titik belok) dipakai apa adanya
    for a, b, kind, eid, epts, eports in conns:
        if epts:
            poly = edge_polyline(boxes[kidx[a]], boxes[kidx[b]], epts)
            mark(poly)
            routes.append((poly, kind, eid))
    # 2) sisanya dirutekan otomatis (titik sambung asli dari gambar bila ada)
    for a, b, kind, eid, epts, eports in conns:
        if epts:
            continue
        ka, kb = kidx[a], kidx[b]
        pp = eports or {}
        p = route(ka, kb, pp.get('src'), pp.get('dst'))
        if not p and pp:
            p = route(ka, kb)
        if not p:
            poly = edge_polyline(boxes[ka], boxes[kb], None)
            mark(poly)
            routes.append((poly, kind, eid))
            continue
        for (i, j, d), nxt in zip(p, p[1:] + [None]):
            dd = nxt[2] if nxt else d
            if dd in (0, 2):
                useH[j, i] += 1
            else:
                useV[j, i] += 1
        # arah keluar sel pertama = arah awal; arah masuk tujuan dari port terakhir
        i0, j0, d0 = p[0]
        il, jl, dl = p[-1]
        # sisi kotak asal: kebalikan dari arah port → cari sisi yang bersebelahan
        bxa = boxes[ka]
        ca = cxy(i0, j0)
        side_a = 3 if ca[1] < bxa[1] else 1 if ca[1] > bxa[3] else 2 if ca[0] < bxa[0] else 0
        bxb = boxes[kb]
        cb = cxy(il, jl)
        side_b = 3 if cb[1] < bxb[1] else 1 if cb[1] > bxb[3] else 2 if cb[0] < bxb[0] else 0
        poly = [edge_pt(ka, i0, j0, side_a)] + [cxy(i, j) for i, j, _d in p] + \
            [edge_pt(kb, il, jl, side_b)]
        simp = [poly[0]]
        for q in poly[1:]:
            if len(simp) >= 2 and ((abs(simp[-2][0] - simp[-1][0]) < 1e-6 and
                                    abs(simp[-1][0] - q[0]) < 1e-6) or
                                   (abs(simp[-2][1] - simp[-1][1]) < 1e-6 and
                                    abs(simp[-1][1] - q[1]) < 1e-6)):
                simp[-1] = q
            else:
                simp.append(q)
        routes.append((simp, kind, eid))
    if _routes_only:
        return {eid: poly for poly, _k, eid in routes}

    # --- gambar ---
    W_ = X1 - X0; H_ = Y1 - Y0
    fw = 7.2
    leg_h = 0.46
    fh = max(3.0, min(10.2, fw * H_ / W_ + leg_h))
    pt_per_u = fw * 72.0 / W_
    with plt.rc_context(RC):
        fig = plt.figure(figsize=(fw, fh))
        ax = fig.add_axes([0.005, leg_h / fh, 0.99, 1 - leg_h / fh - 0.005])
        ax.set_xlim(X0, X1); ax.set_ylim(Y1, Y0)       # sumbu y ke bawah (spt editor)
        ax.set_aspect('equal', adjustable='box')
        ax.axis('off')
        # grup (persegi/poligon) & catatan
        for n in raw:
            t = n['type']
            if t == 'rect':
                x, y = _f(n.get('x')), _f(n.get('y'))
                w, h = _f(n.get('w'), 200), _f(n.get('h'), 120)
                ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, fill=False,
                                       ec='#6B7280', lw=0.8, ls=(0, (5, 3)), zorder=1))
                if n.get('label'):
                    fs = max(3.4, min(6.0, 0.9 * 0.3 * ch0 * pt_per_u))
                    ax.text(x - w / 2, y - h / 2 - 0.3 * cell, n['label'],
                            ha='left', va='bottom', fontsize=fs, style='italic',
                            color='#4B5563', zorder=6)
            elif t == 'polygon':
                q = [(_f(p_[0]) + _f(n.get('x')), _f(p_[1]) + _f(n.get('y')))
                     for p_ in (n.get('pts') or [])]
                if len(q) >= 3:
                    ax.add_patch(MPoly(q, closed=True, fill=False, ec='#6B7280', lw=0.8,
                                       ls=(0, (5, 3)), zorder=1))
            elif t == 'text' and n.get('label'):
                ax.text(_f(n.get('x')), _f(n.get('y')), n['label'], ha='center',
                        va='center', fontsize=5.5, color=K.GREY, zorder=6)
        # kabel
        used_kinds = set()
        for poly, kind, _eid in routes:
            xs = [q[0] for q in poly]; ys = [q[1] for q in poly]
            if kind in COMM_STYLE:
                col, ls, _e, _i = COMM_STYLE[kind]
                ax.plot(xs, ys, color=col, lw=0.75, ls=ls, zorder=2,
                        solid_capstyle='butt', solid_joinstyle='miter')
            elif kind == 'dc':
                ax.plot(xs, ys, color=K.GREY, lw=0.95, ls=(0, (4, 1.6)), zorder=3)
            else:
                ax.plot(xs, ys, color=K.DARK, lw=1.05, zorder=3,
                        solid_capstyle='butt', solid_joinstyle='miter')
            used_kinds.add(kind)
        # ukuran huruf seragam: kuartil bawah dari ukuran muat tiap kartu
        fits = []
        for k in ids:
            n = byid[k]
            if n['type'] in ('ac_bus', 'dc_bus'):
                continue
            bx0, by0, bx1, by1 = geo[k]
            w, h = bx1 - bx0, by1 - by0
            rt = rat_of(n)
            rh = 0.24 * h if rt else 0.0
            fits.append(_fit_text(_clean_label(lab_of(n), rt) or type_label(n['type']),
                                  0.9 * w * pt_per_u, (0.86 * h - rh) * pt_per_u)[0])
        fs_card = float(np.percentile(fits, 25)) if fits else 6.0
        # kartu & rel
        for k in ids:
            n = byid[k]; t = n['type']
            bx0, by0, bx1, by1 = geo[k]
            w, h = bx1 - bx0, by1 - by0
            col = family_color(TYPES[t][2])
            rt = rat_of(n)
            title = _clean_label(lab_of(n), rt) or type_label(t)
            if t in ('ac_bus', 'dc_bus'):
                stb = n.get('status')
                ax.add_patch(FancyBboxPatch((bx0, by0), w, h,
                                            boxstyle=f'round,pad=0,rounding_size={0.12 * h:.2f}',
                                            fc='#FFFFFF' if stb != 'future' else '#F9FAFB',
                                            ec='#9CA3AF' if stb == 'future' else '#374151',
                                            lw=0.9, zorder=4,
                                            ls=(0, (5, 2.5)) if stb == 'existing' else
                                            (0, (3, 2)) if stb == 'future' else '-'))
                yb = by1 - 0.28 * h
                ax.plot([bx0 + 0.06 * min(w, 4 * h), bx1 - 0.06 * min(w, 4 * h)], [yb, yb],
                        color=K.DARK, lw=2.4, solid_capstyle='butt', zorder=5)
                txt = title + (f' · {rt}' if rt and rt.lower() not in title.lower() else '')
                fs, s = _fit_text(txt, (w - 0.2 * h) * pt_per_u, 0.56 * h * pt_per_u,
                                  fs_max=min(6.0, 1.15 * fs_card), max_lines=3)
                ax.text((bx0 + bx1) / 2, by0 + 0.30 * h, s, ha='center', va='center',
                        fontsize=fs, fontweight='bold', color=K.INK, zorder=6,
                        linespacing=1.0)
                continue
            stt = n.get('status')
            if stt == 'future':                        # rencana: abu-abu, garis putus
                ec_, fc_, ls_ = '#9CA3AF', '#F9FAFB', (0, (3, 2))
            else:
                ec_, fc_ = col, _tint(col)
                ls_ = (0, (5, 2.5)) if stt == 'existing' else '-'
            ax.add_patch(FancyBboxPatch((bx0, by0), w, h,
                                        boxstyle=f'round,pad=0,rounding_size={0.09 * min(w, h):.2f}',
                                        fc=fc_, ec=ec_, lw=0.9, ls=ls_, zorder=4))
            rh = 0.24 * h if rt else 0.0
            fs, s = _fit_text(title, 0.9 * w * pt_per_u, (0.86 * h - rh) * pt_per_u,
                              fs_max=fs_card)
            ax.text((bx0 + bx1) / 2, by0 + (0.07 * h + (0.86 * h - rh) / 2), s,
                    ha='center', va='center', fontsize=fs, fontweight='bold',
                    color=K.INK, zorder=6, linespacing=1.0)
            if rt:
                fr, sr = _fit_text(rt, 0.9 * w * pt_per_u, rh * pt_per_u, fs_max=min(5.2, fs),
                                   bold=False,
                                   fs_min=2.4, max_lines=1)
                ax.text((bx0 + bx1) / 2, by1 - 0.06 * h - rh / 2, sr, ha='center',
                        va='center', fontsize=fr, color=K.GREY, zorder=6)
        # legenda
        items = []
        if 'ac' in used_kinds or any(byid[k]['type'] == 'ac_bus' for k in ids):
            items.append(('-', K.DARK, 1.2, L('Rel AC / daya AC', 'AC bus / AC power')))
        if 'dc' in used_kinds:
            items.append(((0, (4, 1.6)), K.GREY, 1.0, L('Daya DC', 'DC power')))
        for kd in COMM_KINDS:
            if kd in used_kinds:
                st = COMM_STYLE[kd]
                items.append((st[1], st[0], 0.95, L(st[3], st[2])))
        sts = {byid[k].get('status') for k in ids}
        if 'existing' in sts:
            items.append(((0, (5, 2.5)), '#4B5563', 0.9,
                          L('Fasilitas eksisting (garis tepi putus)', 'Existing facility (dashed outline)')))
        if 'future' in sts:
            items.append(((0, (3, 2)), '#9CA3AF', 0.9, L('Rencana (abu-abu)', 'Future (grey)')))
        lax = fig.add_axes([0.01, 0.0, 0.98, leg_h / fh])
        lax.axis('off'); lax.set_xlim(0, 1); lax.set_ylim(0, 1)
        x, yl = 0.0, 0.72
        for ls, col, lw_, lab in items:
            wdt = 0.05 + 0.0078 * len(lab)
            if x + wdt > 1.0:
                x, yl = 0.0, 0.25
            lax.plot([x, x + 0.035], [yl, yl], color=col, lw=lw_, ls=ls)
            lax.text(x + 0.042, yl, lab, fontsize=6.0, color=K.GREY, va='center')
            x += wdt + 0.02
    return fig


def render_png(design, cfg, load_stats=None, dpi=130):
    """PNG bytes pratinjau (dipakai editor). None bila tak layak digambar."""
    fig = figure(design, cfg, load_stats)
    if fig is None:
        return None
    buf = K.fig_to_png(fig, dpi=dpi)
    return buf.getvalue()


# -------------------------------------------------- titik awal dari konfigurasi
def seed_from_config(cfg):
    """Rancangan awal (bisa diedit) yang mencerminkan konfigurasi simulasi."""
    ci = _cfg_info(cfg)
    nodes, edges = [], []
    nid = [0]

    def node(t, x, y, **kw):
        nid[0] += 1
        d = dict(id=f'n{nid[0]}', type=t, label='', rating='', x=float(x), y=float(y))
        d.update(kw)
        nodes.append(d)
        return d['id']

    def edge(a, b, kind=None):
        ta = next(n['type'] for n in nodes if n['id'] == a)
        tb = next(n['type'] for n in nodes if n['id'] == b)
        edges.append(dict(id=f'e{len(edges) + 1}', src=a, dst=b,
                          kind=kind or default_edge_kind(ta, tb)))
    cols = []
    if ci['kwp'] > 0:
        cols.append('pv')
    if ci['kwh'] > 0:
        cols.append('bess')
    deg_n = len(ci['caps'])
    use_ats = ci['grid'] and deg_n > 0 and ci['ilock']
    if deg_n and not use_ats:
        cols += ['deg'] * deg_n
    if ci['grid']:
        cols.append('grid_ats' if use_ats else 'grid')
    dx, x0 = 190.0, 0.0
    bus_w = max(2, len(cols) + (deg_n if use_ats else 0)) * dx
    bus = node('ac_bus', x0 + bus_w / 2 - dx / 2, 330.0, w=bus_w)
    ctrl = []
    x = x0
    for c in cols:
        if c == 'pv':
            a = node('pv_array', x, 0); b = node('pv_inverter', x, 110)
            cb = node('breaker', x, 240)
            edge(a, b); edge(b, cb); edge(cb, bus); ctrl.append(b)
            x += dx
        elif c == 'bess':
            a = node('bess', x, 0); b = node('pcs', x, 110); cb = node('breaker', x, 240)
            edge(a, b); edge(b, cb); edge(cb, bus); ctrl.append(b)
            x += dx
        elif c == 'deg':
            g = node('genset', x, 60); cb = node('breaker', x, 240)
            edge(g, cb); edge(cb, bus); ctrl.append(g)
            x += dx
        elif c in ('grid', 'grid_ats'):
            if c == 'grid_ats':
                gens = []
                for _i in range(deg_n):
                    gens.append(node('genset', x, 60)); x += dx
                gx = x
                gr = node('grid', gx, 0); pc = node('pcc', gx, 110)
                edge(gr, pc)
                ats = node('ats', (x - deg_n * dx + gx) / 2, 190)
                for g in gens:
                    edge(g, ats); ctrl.append(g)
                edge(pc, ats)
                cb = node('breaker', (x - deg_n * dx + gx) / 2, 260)
                edge(ats, cb); edge(cb, bus); ctrl.append(ats)
                x += dx
            else:
                gr = node('grid', x, 0); pc = node('pcc', x, 110)
                cb = node('breaker', x, 240)
                edge(gr, pc); edge(pc, cb); edge(cb, bus); ctrl.append(pc)
                x += dx
    cbl = node('breaker', x0 + bus_w * 0.25, 410)
    ld = node('load', x0 + bus_w * 0.25, 500)
    edge(bus, cbl); edge(cbl, ld)
    ems = node('ems', x0 + bus_w * 0.7, 500)
    for t in ctrl:
        edge(ems, t)                      # RS485 (bawaan EMS ↔ perangkat)
    return {'version': 1, 'use_in_report': True, 'nodes': nodes, 'edges': edges}
