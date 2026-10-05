"""Impor gambar arsitektur (JPG/PNG/PDF) → rancangan terstruktur (arch_design).

Pengenalan otomatis 3 lapis (semua lokal, tanpa layanan daring):
  1. TEKS  — PDF: lapisan teks dibaca dengan `pypdf` (bila terpasang).
             JPG/PNG: OCR Tesseract lewat `pytesseract` (opsional; butuh
             aplikasi Tesseract-OCR terpasang). Tanpa keduanya → hanya
             underlay untuk ditelusuri manual di editor.
  2. KOMPONEN — blok teks diklasifikasi dengan kamus kata kunci EN/ID
             (PV, inverter, PCS, BESS, genset, PLN/grid, trafo, ATS, meter,
             rel/busbar/LVMDP, beban, EMS, CB); rating (kWp/kW/kWh/kVA/kV)
             diambil dari teks yang sama.
  3. SAMBUNGAN — dari PIKSEL gambar (numpy): rel AC = garis horizontal panjang;
             sambungan = jalur gelap lurus/siku antar kotak komponen tanpa
             melewati kotak lain (toleransi garis putus-putus & simbol CB).
             Bila tak ada bukti garis, sambungan DISARANKAN dari tata letak
             kolom (ditandai 'suggested' agar ditinjau pengguna).

Hasil: rancangan `arch_design` + laporan pengenalan. Pengguna meninjau/
mengoreksi di editor, lalu `arch_design.figure()` menggambar ulang secara
profesional untuk laporan. Modul murni (tanpa Qt).
"""
from __future__ import annotations

import base64
import io
import os
import re

import numpy as np

from .arch_design import default_edge_kind

# ----------------------------------------------------------------- kamus ----
# (jenis, [pola regex]) — URUTAN = prioritas (yang spesifik lebih dulu)
_RULES = [
    ('dcdc', [r'dc\s*[/-]\s*dc', r'\bmppt\b', r'charge\s+controller', r'\bscc\b']),
    ('pcs', [r'\bpcs\b', r'battery\s+inverter', r'inverter\s+bat', r'bi-?directional',
             r'power\s+conversion', r'\bbdi\b']),
    ('pv_inverter', [r'inverter', r'\binv\b']),
    ('ems', [r'\bems\b', r'controller', r'\bppc\b', r'\bscada\b', r'\bplc\b',
             r'energy\s+management', r'pengendali', r'data\s*logger', r'datalogger']),
    ('ats', [r'\bats\b', r'transfer\s+switch', r'\bcos\b', r'change\s*-?\s*over']),
    ('server', [r'server', r'cloud', r'monitoring', r'\bportal\b', r'\bweb\s*app',
                r'\bnms\b', r'dashboard']),
    ('eth_hub', [r'\bhub\b', r'ethernet', r'network\s+switch', r'\blan\s+switch',
                 r'\bswitch\s+hub', r'\brouter\b', r'\bmodem\b', r'\bgateway\b']),
    ('transformer', [r'transformer', r'\btrafo\b', r'\bxfmr\b', r'\btr\d*\b',
                     r'step\s*-?\s*up', r'step\s*-?\s*down']),
    ('pcc', [r'\bpcc\b', r'kwh\s*meter', r'\bmeter\b', r'\bexim\b', r'ekspor.?impor',
             r'common\s+coupling']),
    ('bess', [r'\bbess\b', r'batter', r'\bbaterai\b', r'\bbatt\b', r'\blfp\b',
              r'storage', r'\bess\b']),
    ('genset', [r'genset', r'diesel', r'generator', r'\bdeg\b', r'\bdg\b', r'\bedg\b',
                r'g-?set']),
    ('grid', [r'\bgrid\b', r'\bpln\b', r'utility', r'jaringan', r'\bmains\b',
              r'utilitas']),
    ('pv_array', [r'\bpv\b', r'solar', r'surya', r'\bmodul', r'module', r'\barray\b',
                  r'\bplts\b', r'photovoltaic']),
    ('dc_bus', [r'dc\s*bus', r'busbar\s*dc', r'rel\s*dc', r'combiner']),
    ('ac_bus', [r'\bbus\b', r'busbar', r'\brel\b', r'\blvmdp\b', r'\bmdp\b', r'\bsdp\b',
                r'switchboard', r'panel\s+utama', r'\blv\s*panel', r'main\s+panel',
                r'\blvsb\b', r'\bmsb\b', r'\bac\s*bus']),
    ('load', [r'\bload', r'\bbeban\b', r'consumer', r'konsumen', r'building',
              r'gedung', r'\bpabrik\b', r'facility']),
    ('breaker', [r'\bcb\b', r'\bmccb\b', r'\bacb\b', r'\bmcb\b', r'breaker', r'\bvcb\b',
                 r'\bfuse\b', r'pemutus']),
]
_RATING = re.compile(
    r'((?:\d+\s*[x×]\s*)?\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?)\s*'
    r'(kwp|mwp|kwh|mwh|kva|mva|kw|mw|kv|v)\b', re.I)
_UNIT = {'kwp': 'kWp', 'mwp': 'MWp', 'kwh': 'kWh', 'mwh': 'MWh', 'kva': 'kVA',
         'mva': 'MVA', 'kw': 'kW', 'mw': 'MW', 'kv': 'kV', 'v': 'V'}


# aturan prioritas tinggi (gambar teknik/CAD: tag & singkatan baku) — dicek
# SEBELUM _RULES agar mis. "LV SWG … FOR PV" = rel (switchgear), bukan array PV,
# dan "DIESEL GENSET xx kVA" = genset, bukan trafo.
_PRE_RULES = [
    ('ac_bus', [r'\bswg', r'switch\s*gear', r'\bswgr\b', r'\b[lm]vsg\b', r'\brmu\b',
                r'tapping\s*point', r'\blv-tp\b',
                # saluran udara (OHL) = ruas penghantar → simpul rel lewat-tengah
                r'\bohl', r'over\s*head\s*line',
                r'\bmvmdp\b', r'\blvmdp\b', r'\bjoint\s+busbar']),
    ('ems', [r'pv\s*logger', r'control\s*(cab|panel|box)', r'logger', r'smart\s*module', r'\bhmi\b', r'\brtu\b',
             r'controller', r'\bcontrol[il1]', r'\bems']),
    ('server', [r'\bnvr\b', r'scada', r'cloud', r'serv[il1]ce?', r'\bserver']),
    ('eth_hub', [r'antenna', r'satellite', r'\bvsat\b', r'starlink', r'\brouter\b',
                 r'adapt[oe]r', r'media\s*conver', r'\bfo-eth\b',
                 r'switch\s*hub', r'\beth\b.*switch', r'\bmodem\b']),
    ('sensor', [r'pyrano', r'irradian', r'\bcctv', r'camera', r'weather\s+station',
                r'anemomet', r'\bsensor', r'met\s*station', r'thermomet']),
    ('ats', [r'sync\.?\s*box', r'synchro', r'\blv-?syn\b']),
    # kotak baterai (BATBOX) = pengumpul DC rak-rak baterai → rel DC (sambungan
    # rak–BATBOX–inverter tetap DC; BESS–BESS langsung dianggap komunikasi)
    ('dc_bus', [r'\bbat\s*box', r'\bbatbox', r'battery\s*box']),
    # kartu gabungan "BATT. xxx kWh, PCS yyy kW" = BESS terintegrasi
    ('bess', [r'\bbatt\b.*\bpcs\b']),
    ('pcs', [r'max\.?\s*chg', r'chg\s*/\s*d[cl]g', r'\bpcs\b', r'\bpcs-?\d']),
    ('pv_inverter', [r'type\s*string', r'string\s+inv', r'\binv-?\s?\d', r'inverter',
                     r'pe\s*string', r'\bhybinv']),
    ('bess', [r'\bbess\b', r'\bbess-?\d', r'\bbatt\b', r'battery']),
    # STG / turbin = sumber jaringan (grid) pada gambar pengguna
    ('grid', [r'turbine', r'\bstg\b', r'\bpln\b', r'\butility\b']),
    ('genset', [r'diesel', r'genset', r'\bdeg-?\s?\d', r'alternator', r'\bg-?set']),
    ('transformer', [r'trans\s*former', r'\btrafo', r'\bdy[nx]', r'\bonan\b',
                     r'isolation\s*tra', r'\btraf\b', r'\btx-[a-z]',
                     r'\bonaf\b']),
    ('breaker', [r'\blbs\b', r'\bvcb\b', r'\b\w*coming\b', r'\boutgoing\b',
                 r'\bacb\b', r'\bmccb\b', r'disconnector']),
    ('load', [r'load\b', r'\bbeban\b']),
]
# koreksi salah-baca OCR yang umum pada huruf CAD (SHX)
_OCR_FIX = [
    (r'¥', 'V'), (r'\|', 'I'), (r'\bL[YVv]-', 'LV-'), (r'\bM[YVv]-', 'MV-'),
    (r'\bSW[G6C]\b', 'SWG'), (r'\bSWG\.', 'SWG '), (r'\bV[O0]B\b', 'VCB'),
    (r'\bV[CO0]B\.', 'VCB '), (r'(?i)\bi?nc?[o0]m+[il1]?n?g\b', 'INCOMING'),
    (r'(?i)\bJRANSFORMER', 'TRANSFORMER'), (r'(?i)TRANSFORMER(?=\d)', 'TRANSFORMER '),
    (r'(?i)\bSERVKE\b', 'SERVICE'), (r'(?i)CONTROLLOAD', 'CONTROL LOAD'),
    (r'\bINY-', 'INV-'), (r'(?i)\bSHART', 'SMART'), (r'(?i)\bLUHPED\b', 'LUMPED'),
    (r'(?i)MOOULE', 'MODULE'), (r'(?i)\bOHL(?=\d)', 'OHL '),
    (r'(?i)\bTRAF\s*[O0]\.\s*(?=\d{2,}\s*[KM]VA\b)', 'TRAFO. '), (r'\bNV-(\d)', r'INV-\1'), (r'(?i)\bYPE ?STRING', 'TYPE STRING'),
    (r'(?i)(\d)\s*K\s*V\b', r'\1kV'), (r'(?i)\b[@O]\.(\d)', r'0.\1'),
    (r'(?i)MONTORING', 'MONITORING'), (r'(?i)SCADA(?=[A-Z])', 'SCADA '),
    (r'(?i)(DEG-?\d)(?=CONTROL)', r'\1 '),
]


# kosakata gambar kelistrikan — memisah kata yang menempel hasil OCR
# ("LVSWG.0.4KVFORPV" → "LV SWG. 0.4KV FOR PV")
_VOCAB = set('''pv array total lv mv hv swg for cloud service server system cctv camera
sensor irradiance pyranometer satellite internet antenna router starlink scada monitoring
montoring switch hub eth transformer lbs vcb incoming outgoing control controller cabinet
panel batt bess genset diesel load lumped aux logger sync box type string max chg dcg dlg
kw kva kwh kwp mva kv manually op turbine alt stg deg hmi ems nvr bef int dist pcs inv pre
fabricated substation main grid pln meter inverter battery unit room house station power
pvbs bs cb dc ac and to of from the with rack module solar string container industrial
media converter isolation traf panel tapping point new ohl weather set eth adaptor smart
datalogger logger plc sungrow huawei batbox overhead line lumped reyee trafo'''.split())


def _seg_word(w):
    s = w.lower()
    n = len(s)
    best = [None] * (n + 1)
    best[0] = []
    for i in range(n):
        if best[i] is None:
            continue
        for j in range(i + 2, min(n, i + 14) + 1):
            if s[i:j] in _VOCAB and (best[j] is None or len(best[j]) > len(best[i]) + 1):
                best[j] = best[i] + [w[i:j]]
    return ' '.join(best[n]) if best[n] and len(best[n]) > 1 else w


def _split_glued(t):
    t = re.sub(r'(?<=[A-Za-z])0(?=[A-Za-z])', 'O', t)          # F0R → FOR
    t = re.sub(r'(?<=[A-Za-z]{4})(?=\d)', ' ', t)               # TOTAL591 → TOTAL 591
    t = re.sub(r'(?<=\d)(?=[A-Za-z]{4,})', ' ', t)              # 1CONTROL → 1 CONTROL
    t = re.sub(r'(?<=[A-Za-z]\.)(?=\d+(?:\.\d+)?\s*[kK][vV])', ' ', t)  # SWG.0.4KV

    def fix(m):
        w = m.group(0)
        return _seg_word(w) if len(w) >= 5 else w
    return re.sub(r'[A-Za-z]+', fix, t)


def norm_text(t):
    """Bersihkan teks OCR (spasi, salah-baca huruf CAD yang umum)."""
    t = ' '.join(str(t).split())
    t = _split_glued(t)
    for a, b in _OCR_FIX:
        t = re.sub(a, b, t)
    return ' '.join(t.split())


def classify(text, pre=True):
    t = ' ' + str(text).lower().replace('\n', ' ') + ' '
    for typ, pats in (_PRE_RULES if pre else []) + _RULES:
        for p in pats:
            if re.search(p, t):
                return typ
    return None


def rating_of(text):
    out = []
    for m in _RATING.finditer(str(text)):
        num = re.sub(r'\s*[x×]\s*', ' × ', m.group(1))
        num = re.sub(r'\s*/\s*', '/', num)
        out.append(f"{num} {_UNIT[m.group(2).lower()]}")
    return ', '.join(out[:2])


# --------------------------------------------------------- sumber teks -----
def ocr_available():
    try:
        import pytesseract
    except Exception:
        return False
    for cand in (r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                 r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'):
        if os.path.exists(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            break
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


_RAPID = None
_RAPID_ERR = ''


def _rapid():
    """Mesin OCR berbasis model PP-OCR (ONNX).

    Utama: OCR TERBAWA di aplikasi (``app/ocr`` — model disertakan, cukup
    ``onnxruntime``). Cadangan: paket pip ``rapidocr_onnxruntime`` bila ada.
    None bila keduanya tak tersedia (lihat ``ocr_error()``)."""
    global _RAPID, _RAPID_ERR
    if _RAPID is None:
        _RAPID = False
        try:
            try:
                from .. import ocr as _mini
            except Exception:                      # dipanggil sbg modul absolut
                from app import ocr as _mini
            eng = _mini.load()
            if eng is not None:
                _RAPID = eng
            else:
                _RAPID_ERR = _mini.last_error()
        except Exception as e:                     # pragma: no cover
            _RAPID_ERR = f'{type(e).__name__}: {e}'
        if not _RAPID:
            try:
                from rapidocr_onnxruntime import RapidOCR
                _RAPID = RapidOCR()
            except Exception:
                pass
    return _RAPID or None


def ocr_error():
    """Alasan OCR terbawa tidak dapat dimuat ('' bila siap)."""
    _rapid()
    return '' if _RAPID else (_RAPID_ERR or 'onnxruntime not available')


def ocr_engine():
    """'rapidocr' (OCR terbawa / RapidOCR — utama) | 'tesseract' | None."""
    if _rapid() is not None:
        return 'rapidocr'
    return 'tesseract' if ocr_available() else None


def _starts(L_, tile, ov):
    if L_ <= tile:
        return [0]
    out, x = [], 0
    while True:
        out.append(x)
        if x + tile >= L_:
            return out
        x = min(x + tile - ov, L_ - tile)


def rapid_words(img, tile=1400, ov=260, min_score=0.5):
    """OCR RapidOCR per ubin (gambar besar, huruf kecil) → [(teks, x0, y0, x1, y1)]."""
    eng = _rapid()
    if eng is None:
        return []
    a = np.asarray(img)
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, axis=2)
    a = a[..., :3].astype(np.uint8)
    H, W = a.shape[:2]
    found = []
    for y in _starts(H, tile, ov):
        for x in _starts(W, tile, ov):
            sub = np.ascontiguousarray(a[y:y + tile, x:x + tile])
            if sub.min() > 200:                        # ubin kosong
                continue
            try:
                out, _t = eng(sub, use_cls=False)
            except Exception:
                out = None
            for box, txt, sc in out or []:
                txt = str(txt or '').strip()
                if not txt or float(sc) < min_score:
                    continue
                xs = [p[0] for p in box]; ys = [p[1] for p in box]
                found.append((txt, x + min(xs), y + min(ys), x + max(xs), y + max(ys)))
    # buang duplikat dari tumpang-tindih ubin (simpan teks terpanjang)
    found.sort(key=lambda w: -len(w[0]))
    keep = []
    for w in found:
        ar = max(1.0, (w[3] - w[1]) * (w[4] - w[2]))
        dup = False
        for i_, k in enumerate(keep):
            ix = min(k[3], w[3]) - max(k[1], w[1]); iy = min(k[4], w[4]) - max(k[2], w[2])
            if ix > 0 and iy > 0 and ix * iy > 0.5 * min(ar, (k[3] - k[1]) * (k[4] - k[2])):
                dup = True
                # teks panjang terpotong tepi ubin: dua potongan saling melampaui →
                # gabungkan (buang bagian yang terbaca dua kali)
                hk = k[4] - k[2]; hw = w[4] - w[2]
                if iy > 0.6 * min(hk, hw) and ix < 0.85 * min(k[3] - k[1], w[3] - w[1]):
                    L, R = (k, w) if k[1] < w[1] else (w, k)
                    if R[3] > L[3] + 0.5 * min(hk, hw):
                        lt, rt = L[0], R[0]
                        # sejajarkan pada bentuk kanonik (tanpa spasi, 0→O): potongan
                        # yang sama bisa terbaca beda spasi/angka; huruf terakhir potongan
                        # kiri sering salah-baca (terpotong tepi ubin) → buang 0–2 huruf
                        li = [k_ for k_, c_ in enumerate(lt) if not c_.isspace()]
                        ri = [k_ for k_, c_ in enumerate(rt) if not c_.isspace()]
                        lc = ''.join(lt[k_] for k_ in li).upper().replace('0', 'O')
                        rc = ''.join(rt[k_] for k_ in ri).upper().replace('0', 'O')
                        txt = None
                        for trim in (0, 1, 2):
                            l2 = lc[:len(lc) - trim]
                            for n_ in range(min(len(l2), len(rc)), 0, -1):
                                p_ = rc.find(l2[-n_:])
                                if (p_ == 0 and (trim == 0 or n_ >= 3)) or (p_ > 0 and n_ >= 4):
                                    cl = li[len(l2) - 1] + 1 if l2 else 0
                                    cr = ri[p_ + n_ - 1] + 1
                                    txt = lt[:cl] + rt[cr:]
                                    break
                            if txt is not None:
                                break
                        if txt is None:
                            tail = lt.split(' ')[-1]
                            glue = '' if (len(tail) <= 2 and tail.isalpha()
                                          and rt[:1].isalpha()) else ' '
                            txt = (lt.rstrip() + glue + rt.lstrip()).strip()
                        keep[i_] = (txt, L[1], min(L[2], R[2]), R[3], max(L[4], R[4]))
                break
        if not dup:
            keep.append(w)
    return [(norm_text(t), a_, b_, c_, d_) for t, a_, b_, c_, d_ in keep]


def ocr_words(gray):
    """[(teks, x0, y0, x1, y1)] dari OCR (RapidOCR bila terpasang; selain itu
    Tesseract beberapa mode segmentasi, digabung); [] bila tak ada OCR."""
    if _rapid() is not None:
        g = np.asarray(gray)
        f = 2.0 if max(g.shape[:2]) < 2200 else 1.0      # huruf kecil → perbesar
        if f != 1.0:
            from PIL import Image
            g = np.asarray(Image.fromarray(g.astype(np.uint8)).resize(
                (int(g.shape[1] * f), int(g.shape[0] * f)), Image.LANCZOS))
        return [(t, a / f, b / f, c / f, d / f) for t, a, b, c, d in rapid_words(g)]
    if not ocr_available():
        return []
    import pytesseract
    from PIL import Image
    h, w = gray.shape
    scale = 2.0 if max(h, w) < 2200 else 1.0
    img = Image.fromarray(gray)
    if scale != 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    img = img.point(lambda v: 255 if v > 170 else 0)       # binarisasi
    found = []                                               # (conf, word)
    for psm in (11, 6, 3):
        try:
            d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT,
                                          config=f'--psm {psm}')
        except Exception:
            continue
        for i, txt in enumerate(d.get('text', [])):
            txt = (txt or '').strip().strip('|[]{}()_~`\'".,;:')
            try:
                conf = float(d['conf'][i])
            except (TypeError, ValueError):
                conf = -1
            if conf < 35 or not txt:
                continue
            if not ((re.fullmatch(r'\d+([.,]\d+)?', txt) and len(txt) >= 2)
                    or len(re.findall(r'[A-Za-z]', txt)) >= 2):
                continue                                     # buang sampah OCR
            x, y, ww, hh = (d[k][i] / scale for k in ('left', 'top', 'width', 'height'))
            wd = (txt, x, y, x + ww, y + hh)
            dup = False
            for k, (c0, w0) in enumerate(found):
                ix = min(w0[3], wd[3]) - max(w0[1], wd[1])
                iy = min(w0[4], wd[4]) - max(w0[2], wd[2])
                if ix > 0 and iy > 0 and ix * iy > 0.3 * min(
                        (w0[3] - w0[1]) * (w0[4] - w0[2]), ww * hh):
                    dup = True
                    if conf > c0:
                        found[k] = (conf, wd)
                    break
            if not dup:
                found.append((conf, wd))
    return [w for _c, w in found]


def pdf_words(path, page_index, W, H):
    """Kata + posisi (piksel gambar W×H) dari lapisan teks PDF via pypdf."""
    try:
        from pypdf import PdfReader
    except Exception:
        return []
    try:
        page = PdfReader(path).pages[page_index]
    except Exception:
        return []
    box = page.mediabox
    pw, ph = float(box.width), float(box.height)
    x_off, y_off = float(box.left), float(box.bottom)
    words = []

    def visit(text, cm, tm, font, size):
        text = (text or '').strip()
        if not text:
            return
        # posisi = tm · cm (matriks 3×3 afine PDF)
        a, b, c, d, e, f = tm
        A_, B_, C_, D_, E_, F_ = cm
        x = e * A_ + f * C_ + E_
        y = e * B_ + f * D_ + F_
        fs = abs(float(size or 10) * (d if d else 1.0) * (D_ if D_ else 1.0)) or 10.0
        for ln in text.splitlines():
            ln = ln.strip()
            if ln:
                x0 = (x - x_off) * W / pw
                y1 = H - (y - y_off) * H / ph
                h_px = fs * H / ph
                words.append((ln, x0, y1 - h_px, x0 + 0.55 * h_px * len(ln), y1))
            y -= fs * 1.2
    try:
        page.extract_text(visitor_text=visit)
    except Exception:
        return []
    return words


# --------------------------------------------------------- utilitas piksel --
def _binarize(gray):
    g = gray.astype(np.float32)
    # ambang Otsu sederhana
    hist, _ = np.histogram(g, bins=256, range=(0, 256))
    tot = g.size
    sum_all = np.dot(np.arange(256), hist)
    wb = sb = 0.0
    best, thr = -1.0, 128
    for i in range(256):
        wb += hist[i]
        if wb == 0:
            continue
        wf = tot - wb
        if wf == 0:
            break
        sb += i * hist[i]
        mb, mf = sb / wb, (sum_all - sb) / wf
        between = wb * wf * (mb - mf) ** 2
        if between > best:
            best, thr = between, i
    thr = min(thr, 200)
    return g < thr


def _group_phrases(words):
    """Gabung kata → blok teks (baris lalu tumpukan vertikal dalam satu kotak)."""
    items = [dict(t=t, x0=x0, y0=y0, x1=x1, y1=y1) for t, x0, y0, x1, y1 in words]
    items.sort(key=lambda d: d['x0'])
    lines = []
    for w in items:
        h = max(4.0, w['y1'] - w['y0'])
        cy = (w['y0'] + w['y1']) / 2
        for ln in lines:
            lh = max(4.0, ln['y1'] - ln['y0'])
            if abs(cy - (ln['y0'] + ln['y1']) / 2) < 0.6 * max(h, lh) and \
                    -0.5 * h < w['x0'] - ln['x1'] < 1.4 * max(h, lh):
                ln['t'] += ' ' + w['t']
                ln['x1'] = max(ln['x1'], w['x1']); ln['y0'] = min(ln['y0'], w['y0'])
                ln['y1'] = max(ln['y1'], w['y1'])
                break
        else:
            lines.append(dict(w))
    # tumpukan vertikal (judul + rating dalam satu kotak)
    blocks = []
    for ln in sorted(lines, key=lambda d: d['y0']):
        h = max(4.0, ln['y1'] - ln['y0'])
        cx = (ln['x0'] + ln['x1']) / 2
        for b in blocks:
            bcx = (b['x0'] + b['x1']) / 2
            if -0.45 * h <= ln['y0'] - b['y1'] < 1.1 * h and \
                    abs(cx - bcx) < 0.5 * max(b['x1'] - b['x0'], ln['x1'] - ln['x0']):
                b['t'] += '\n' + ln['t']
                b['x0'] = min(b['x0'], ln['x0']); b['x1'] = max(b['x1'], ln['x1'])
                b['y1'] = max(b['y1'], ln['y1'])
                break
        else:
            blocks.append(dict(ln))
    return blocks


def _enclosing_box(dark, blk, max_frac=0.18):
    """Perluas bbox teks ke kotak yang digambar di sekelilingnya (bila ada)."""
    H, W = dark.shape
    cx = int((blk['x0'] + blk['x1']) / 2)
    cy = int((blk['y0'] + blk['y1']) / 2)
    lim_x, lim_y = int(W * max_frac), int(H * max_frac)
    x0, x1 = int(blk['x0']), int(blk['x1'])
    y0, y1 = int(blk['y0']), int(blk['y1'])

    def scan(x, y, dx, dy, lim):
        for i in range(1, lim):
            xx, yy = x + dx * i, y + dy * i
            if not (0 <= xx < W and 0 <= yy < H):
                return None
            if dark[yy, xx]:
                return i
        return None
    le = scan(max(0, x0 - 2), cy, -1, 0, lim_x)
    ri = scan(min(W - 1, x1 + 2), cy, 1, 0, lim_x)
    up = scan(cx, max(0, y0 - 2), 0, -1, lim_y)
    dn = scan(cx, min(H - 1, y1 + 2), 0, 1, lim_y)
    if None not in (le, ri, up, dn):
        return (x0 - 2 - le, y0 - 2 - up, x1 + 2 + ri, y1 + 2 + dn)
    pad = 0.4 * max(6.0, blk['y1'] - blk['y0'])
    return (blk['x0'] - pad, blk['y0'] - pad, blk['x1'] + pad, blk['y1'] + pad)


def _find_bus_lines(dark, masks, min_frac=0.32):
    """Garis horizontal panjang (kandidat rel): [(y, x0, x1)]."""
    H, W = dark.shape
    d = dark.copy()
    for (x0, y0, x1, y1) in masks:
        d[max(0, int(y0)):min(H, int(y1) + 1), max(0, int(x0)):min(W, int(x1) + 1)] = False
    rows = []
    for y in range(H):
        r = d[y]
        if r.sum() < W * min_frac:
            continue
        # run terpanjang (izinkan celah ≤ 3 px)
        idx = np.flatnonzero(r)
        gaps = np.diff(idx)
        best, s = (0, 0, 0), 0
        for i in range(1, len(idx) + 1):
            if i == len(idx) or gaps[i - 1] > 4:
                ln = idx[i - 1] - idx[s]
                if ln > best[0]:
                    best = (ln, idx[s], idx[i - 1])
                s = i
        if best[0] >= W * min_frac:
            rows.append((y, best[1], best[2]))
    # gabung baris berdekatan (garis tebal)
    lines = []
    for y, a, b in rows:
        if lines and y - lines[-1]['y1'] <= 2:
            L_ = lines[-1]
            L_['y1'] = y; L_['a'] = min(L_['a'], a); L_['b'] = max(L_['b'], b)
        else:
            lines.append(dict(y0=y, y1=y, a=a, b=b))
    return [((l['y0'] + l['y1']) / 2.0, l['a'], l['b'], l['y1'] - l['y0'] + 1)
            for l in lines]


def _dilate(dark, r=2):
    """Dilatasi biner sederhana (numpy) — menoleransi garis tipis/antialias."""
    d = dark.copy()
    for k in range(1, r + 1):
        d[k:, :] |= dark[:-k, :]; d[:-k, :] |= dark[k:, :]
    e = d.copy()
    for k in range(1, r + 1):
        e[:, k:] |= d[:, :-k]; e[:, :-k] |= d[:, k:]
    return e


def _seg_pts(xa, ya, xb, yb):
    n = int(max(abs(xb - xa), abs(yb - ya))) + 1
    return (np.linspace(xa, xb, n).round().astype(int),
            np.linspace(ya, yb, n).round().astype(int))


def _path_ok(dd, pts, blocks, max_gap):
    """Jalur poligon gelap pada citra terdilatasi `dd`? Celah terpanjang ≤
    max_gap; tidak boleh masuk ke region terlarang `blocks` (kotak lain / pita
    rel). Tervektorisasi."""
    H, W = dd.shape
    xs_all, ys_all = [], []
    for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
        xs, ys = _seg_pts(xa, ya, xb, yb)
        xs_all.append(xs); ys_all.append(ys)
    if not xs_all:
        return False
    xs = np.concatenate(xs_all); ys = np.concatenate(ys_all)
    if xs.size < 2 or xs.min() < 0 or ys.min() < 0 or xs.max() >= W or ys.max() >= H:
        return False
    for (bx0, by0, bx1, by1) in blocks:
        if np.any((xs > bx0) & (xs < bx1) & (ys > by0) & (ys < by1)):
            return False
    hit = dd[ys, xs]
    if hit.all():
        return True
    miss = ~hit
    # run terpanjang dari False
    idx = np.flatnonzero(np.diff(np.concatenate(([0], miss.astype(np.int8), [0]))))
    runs = idx[1::2] - idx[0::2]
    return runs.max() <= max_gap


def _stubs(dd, x0, x1, y, lo=None):
    """Kolom (x) di rentang [x0,x1] pada baris y yang gelap → pusat tiap run
    (titik keluarnya garis dari sisi kotak)."""
    H, W = dd.shape
    if not (0 <= y < H):
        return []
    x0, x1 = max(0, int(x0)), min(W - 1, int(x1))
    if x1 <= x0:
        return []
    row = dd[y, x0:x1 + 1]
    idx = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
    out = []
    for a, b in zip(idx[0::2], idx[1::2]):
        if b - a <= max(12, 0.35 * (x1 - x0)):     # bukan garis tepi kotak
            out.append(x0 + (a + b - 1) // 2)
    return out


def _rows_cov(dd, y0, y1, xa, xb, thr=0.9):
    """Baris y di [y0,y1] yang segmen horizontalnya xa..xb hampir penuh gelap."""
    H, W = dd.shape
    y0, y1 = max(0, int(y0)), min(H - 1, int(y1))
    lo, hi = sorted((max(0, int(xa)), min(W - 1, int(xb))))
    if y1 <= y0 or hi <= lo:
        return []
    cov = dd[y0:y1 + 1, lo:hi + 1].mean(axis=1)
    ys = np.flatnonzero(cov >= thr) + y0
    # satu wakil per kelompok baris berurutan
    out, last = [], -10
    for y in ys:
        if y - last > 2:
            out.append(int(y))
        last = y
    return out


def _cols_cov(dd, x0, x1, ya, yb, thr=0.9):
    return _rows_cov(dd.T, x0, x1, ya, yb, thr)


def _clear_row(dd, x0, x1, y_start, step, lim=18):
    """Baris pertama di luar tepi kotak yang TIDAK memuat run panjang (garis
    tepi kotak berantialias/membulat) → tempat membaca stub garis keluar."""
    H, W = dd.shape
    x0, x1 = max(0, int(x0)), min(W - 1, int(x1))
    for k in range(3, lim):
        y = int(y_start + step * k)
        if not (0 <= y < H):
            return None
        row = dd[y, x0:x1 + 1]
        if not row.any():
            return y
        idx = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
        if (idx[1::2] - idx[0::2]).max() <= max(12, 0.35 * (x1 - x0)):
            return y
    return None


def _stubs_v(dd, y0, y1, x):
    H, W = dd.shape
    if not (0 <= x < W):
        return []
    y0, y1 = max(0, int(y0)), min(H - 1, int(y1))
    if y1 <= y0:
        return []
    col = dd[y0:y1 + 1, x]
    idx = np.flatnonzero(np.diff(np.concatenate(([0], col.astype(np.int8), [0]))))
    return [y0 + (a + b - 1) // 2 for a, b in zip(idx[0::2], idx[1::2])
            if b - a <= max(12, 0.35 * (y1 - y0))]


def _rectangles(dark):
    """Deteksi kotak tergambar (tepi atas/bawah + sisi kiri/kanan) → [(x0,y0,x1,y1)]."""
    H, W = dark.shape
    segs = []
    for y in range(H):
        row = dark[y]
        if not row.any():
            continue
        idx = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
        for a, b in zip(idx[0::2], idx[1::2]):
            if 25 <= b - a <= 0.4 * W:
                segs.append((y, a, b - 1))
    # gabung baris berurutan (garis tebal)
    lines = []
    for y, a, b in segs:
        for L_ in lines:
            if y - L_[1] <= 1 and abs(L_[2] - a) <= 3 and abs(L_[3] - b) <= 3:
                L_[1] = y
                break
        else:
            lines.append([y, y, a, b])
    rects = []
    for i, t in enumerate(lines):
        for bt in lines[i + 1:]:
            if abs(t[2] - bt[2]) > 4 or abs(t[3] - bt[3]) > 4:
                continue
            y0, y1 = t[0], bt[1]
            if not (14 <= y1 - y0 <= 0.3 * H):
                continue
            x0, x1 = min(t[2], bt[2]), max(t[3], bt[3])
            lc = dark[y0:y1 + 1, max(0, x0 - 1):x0 + 2].any(axis=1).mean()
            rc = dark[y0:y1 + 1, max(0, x1 - 1):x1 + 2].any(axis=1).mean()
            if lc > 0.85 and rc > 0.85:
                rects.append((x0, y0, x1, y1))
                break
    return rects


def _ocr_crop(gray, box):
    """OCR satu kotak (mode satu baris / blok). '' bila tak tersedia."""
    if not ocr_available():
        return ''
    import pytesseract
    from PIL import Image
    x0, y0, x1, y1 = (int(v) for v in box)
    crop = gray[y0 + 3:y1 - 2, x0 + 3:x1 - 2]
    if crop.size == 0:
        return ''
    img = Image.fromarray(crop)
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = img.point(lambda v: 255 if v > 170 else 0)
    txt = ''
    for psm in (7, 6):
        try:
            t = pytesseract.image_to_string(img, config=f'--psm {psm}').strip()
        except Exception:
            t = ''
        if len(re.findall(r'[A-Za-z]', t)) > len(re.findall(r'[A-Za-z]', txt)):
            txt = t
    return txt


# ------------------------------------------------------------ pengenalan ----
def recognize(gray, words=None, source='image'):
    """gray: ndarray uint8 (H, W). words: [(teks, x0,y0,x1,y1)] atau None (OCR).

    Kembalikan dict(nodes, edges, report) — koordinat node dalam PIKSEL gambar.
    """
    gray = np.asarray(gray)
    if gray.ndim == 3:
        gray = (gray[..., :3] @ np.array([0.299, 0.587, 0.114])).astype(np.uint8)
    H, W = gray.shape
    dark = _binarize(gray)
    method = 'pdf-text' if words else None
    if not words:
        words = ocr_words(gray)
        method = 'ocr' if words else 'none'
    rep = dict(method=method, words=len(words), messages=[])
    blocks = _group_phrases(words) if words else []
    nodes = []
    for b in blocks:
        typ = classify(b['t'])
        if typ is None:
            continue
        bb = _enclosing_box(dark, b)
        first = b['t'].split('\n')[0].strip()
        label = re.sub(_RATING, '', first).strip(' -:,()') or first
        label = re.sub(r'\s+\d+([.,]\d+)?$', '', label).strip() or label
        nodes.append(dict(type=typ, label=label[:40], rating=rating_of(b['t']),
                          box=bb, cx=(bb[0] + bb[2]) / 2, cy=(bb[1] + bb[3]) / 2,
                          text=b['t'], tbox=(b['x0'], b['y0'], b['x1'], b['y1'])))
    # kotak tergambar tanpa komponen terkenali → OCR khusus per kotak
    if method == 'ocr' or not words:
        for rb in _rectangles(dark):
            cx, cy = (rb[0] + rb[2]) / 2, (rb[1] + rb[3]) / 2
            if any(n['box'][0] - 3 <= cx <= n['box'][2] + 3 and
                   n['box'][1] - 3 <= cy <= n['box'][3] + 3 for n in nodes):
                continue
            txt = _ocr_crop(gray, rb)
            typ = classify(txt) if txt else None
            if typ:
                first = txt.split('\n')[0].strip()
                label = re.sub(_RATING, '', first).strip(' -:,()|') or first
                nodes.append(dict(type=typ, label=label[:40], rating=rating_of(txt),
                                  box=tuple(float(v) for v in rb), cx=cx, cy=cy,
                                  text=txt, tbox=(rb[0] + 3, rb[1] + 3, rb[2] - 3, rb[3] - 3)))
                rep['messages'].append(('info', 'box_ocr'))
    # gabung duplikat (jenis sama, kotak bertumpuk)
    merged = []
    for n in nodes:
        for m in merged:
            if m['type'] == n['type'] and not (n['box'][0] > m['box'][2] or
                                                n['box'][2] < m['box'][0] or
                                                n['box'][1] > m['box'][3] or
                                                n['box'][3] < m['box'][1]):
                m['rating'] = m['rating'] or n['rating']
                break
        else:
            merged.append(n)
    nodes = merged

    # --- rel AC dari piksel ---
    masks = [n['box'] for n in nodes if n['type'] not in ('ac_bus', 'dc_bus')] + \
        [(n['tbox'][0] - 2, n['tbox'][1] - 2, n['tbox'][2] + 2, n['tbox'][3] + 2)
         for n in nodes if 'tbox' in n]
    buses = _find_bus_lines(dark, masks) if nodes else []
    bus_nodes = [n for n in nodes if n['type'] == 'ac_bus']
    main_line = None
    if buses:
        main_line = max(buses, key=lambda b: (b[2] - b[1]) * (1 + 0.3 * b[3]))
        yb, a, b_, th = main_line
        if bus_nodes:
            bn = min(bus_nodes, key=lambda n: abs(n['cy'] - yb))
            bn.update(box=(a, yb - 2, b_, yb + 2), cx=(a + b_) / 2, cy=yb, line=True)
        else:
            nodes.append(dict(type='ac_bus', label='', rating='', box=(a, yb - 2, b_, yb + 2),
                              cx=(a + b_) / 2, cy=yb, text='', line=True))
        rep['messages'].append(('info', 'bus_line'))
    for n in nodes:
        if n['type'] == 'ac_bus' and not n.get('line'):
            # label rel tanpa garis terdeteksi → kotak label diperlakukan titik rel
            n['line'] = False

    # --- sambungan dari bukti piksel (mengikuti garis yang keluar dari kotak) ---
    edges = []
    tol = max(8, int(0.012 * max(H, W)))
    dd = _dilate(dark, 2)
    # hapus teks LABEL komponen agar tak dikira garis (teks lain dibiarkan —
    # 'kata' OCR palsu sering jatuh di atas garis/simbol CB)
    txt = np.zeros_like(dd)
    for n in nodes:
        if 'tbox' in n:
            x0, y0, x1, y1 = (int(v) for v in n['tbox'])
            dd[max(0, y0 - 1):max(0, y1) + 2, max(0, x0 - 1):max(0, x1) + 2] = False
            txt[max(0, y0 - 1):max(0, y1) + 2, max(0, x0 - 1):max(0, x1) + 2] = True
    # untuk MENELUSURI jalur, area teks yang dihapus dianggap 'tak diketahui'
    # (garis boleh melintasi label, mis. label rel di atas garis rel)
    ddp = dd | txt
    off = 5                                    # jarak baca stub di luar tepi kotak

    def add(i, j, how):
        key = tuple(sorted((i, j)))
        if key not in {tuple(sorted((e['i'], e['j']))) for e in edges}:
            edges.append(dict(i=i, j=j, how=how))
    boxes = [n['box'] for n in nodes]
    bus_bands = {k: (n['box'][0], n['cy'] - 4, n['box'][2], n['cy'] + 4)
                 for k, n in enumerate(nodes) if n.get('line')}

    def blocks_for(i, j):
        bl = [boxes[k] for k in range(len(nodes))
              if k not in (i, j) and not nodes[k].get('line')]
        bl += [bb for k, bb in bus_bands.items() if k not in (i, j)]
        return bl

    def vertical_link(A_, B_, bl):
        """A di atas B: stub bawah A → (lurus | siku) → stub atas B."""
        ax0, ay0, ax1, ay1 = A_['box']
        bx0, by0, bx1, by1 = B_['box']
        if ay1 > by0:
            return False
        ya_r = _clear_row(dd, ax0 + 2, ax1 - 2, ay1, +1)
        yb_r = _clear_row(dd, bx0 + 2, bx1 - 2, by0, -1)
        if ya_r is None or yb_r is None or ya_r >= yb_r:
            return False
        exits = _stubs(dd, ax0 + 2, ax1 - 2, ya_r)
        entries = _stubs(dd, bx0 + 2, bx1 - 2, yb_r)
        for xa in exits:
            for xb in entries:
                if abs(xa - xb) <= 3:
                    if _path_ok(ddp, [(xa, int(ay1) + 1), (xa, int(by0) - 1)], bl, tol):
                        return True
                    continue
                # cari baris horizontal penghubung
                for ym in _rows_cov(dd, ya_r, yb_r, xa, xb):
                    if _path_ok(ddp, [(xa, int(ay1) + 1), (xa, ym), (xb, ym),
                                     (xb, int(by0) - 1)], bl, tol):
                        return True
        return False

    def horizontal_link(A_, B_, bl):
        """A di kiri B: stub kanan A → stub kiri B (lurus atau siku)."""
        ax0, ay0, ax1, ay1 = A_['box']
        bx0, by0, bx1, by1 = B_['box']
        if ax1 > bx0:
            return False
        xa_r = _clear_row(dd.T, ay0 + 2, ay1 - 2, ax1, +1)
        xb_r = _clear_row(dd.T, by0 + 2, by1 - 2, bx0, -1)
        if xa_r is None or xb_r is None or xa_r >= xb_r:
            return False
        exits = _stubs_v(dd, ay0 + 2, ay1 - 2, xa_r)
        entries = _stubs_v(dd, by0 + 2, by1 - 2, xb_r)
        for ya in exits:
            for yb in entries:
                if abs(ya - yb) <= 3:
                    if _path_ok(ddp, [(int(ax1) + 1, ya), (int(bx0) - 1, ya)], bl, tol):
                        return True
                    continue
                for xm in _cols_cov(dd, xa_r, xb_r, ya, yb):
                    if _path_ok(ddp, [(int(ax1) + 1, ya), (xm, ya), (xm, yb),
                                     (int(bx0) - 1, yb)], bl, tol):
                        return True
        return False

    def bus_link(A_, B_, bl):
        """Kotak A ke garis rel B (vertikal dari stub A)."""
        ax0, ay0, ax1, ay1 = A_['box']
        yb = B_['cy']
        if not (B_['box'][0] - tol <= A_['cx'] <= B_['box'][2] + tol):
            return False
        if yb > ay1:
            yr = _clear_row(dd, ax0 + 2, ax1 - 2, ay1, +1); y_from = int(ay1) + 1
        elif yb < ay0:
            yr = _clear_row(dd, ax0 + 2, ax1 - 2, ay0, -1); y_from = int(ay0) - 1
        else:
            return False
        if yr is None:
            return False
        xs = _stubs(dd, ax0 + 2, ax1 - 2, yr)
        for xa in xs:
            if B_['box'][0] - 2 <= xa <= B_['box'][2] + 2 and \
                    _path_ok(ddp, [(xa, y_from), (xa, int(yb))], bl, tol):
                return True
        return False

    for i, a in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            bl = blocks_for(i, j)
            if a.get('line') and b.get('line'):
                continue
            if a.get('line') or b.get('line'):
                A_, B_ = (b, a) if a.get('line') else (a, b)
                ok = bus_link(A_, B_, bl)
            else:
                ok = (vertical_link(a, b, bl) or vertical_link(b, a, bl)
                      or horizontal_link(a, b, bl) or horizontal_link(b, a, bl))
            if ok:
                add(i, j, 'line')
    confirmed = len(edges)

    # --- saran dari tata letak bila bukti garis minim ---
    comps = [k for k, n in enumerate(nodes) if n['type'] not in ('ems',)]
    linked = {e['i'] for e in edges} | {e['j'] for e in edges}
    loose = [k for k in comps if k not in linked]
    if loose and len(comps) > 1:
        bus_k = next((k for k, n in enumerate(nodes) if n['type'] == 'ac_bus'), None)
        colw = max(20.0, 0.07 * W)
        for k in loose:
            n = nodes[k]
            if n['type'] == 'ac_bus':
                continue
            # tetangga terdekat pada kolom yang sama, ke arah rel
            yb = nodes[bus_k]['cy'] if bus_k is not None else H / 2.0
            toward = 1 if n['cy'] < yb else -1
            cand = [m for m in comps if m != k and abs(nodes[m]['cx'] - n['cx']) < colw
                    and (nodes[m]['cy'] - n['cy']) * toward > 0
                    and nodes[m]['type'] != 'ac_bus']
            if cand:
                m = min(cand, key=lambda m: abs(nodes[m]['cy'] - n['cy']))
                add(k, m, 'suggested')
            elif bus_k is not None:
                add(k, bus_k, 'suggested')
    # EMS: kendali ke konverter/genset/PCC/ATS bila tak ada garis terdeteksi
    for k, n in enumerate(nodes):
        if n['type'] != 'ems':
            continue
        if not any(k in (e['i'], e['j']) for e in edges):
            for m, o in enumerate(nodes):
                if o['type'] in ('pv_inverter', 'pcs', 'genset', 'pcc', 'ats'):
                    add(k, m, 'suggested')
    rep['nodes'] = len(nodes)
    rep['edges'] = len(edges)
    rep['confirmed'] = confirmed
    rep['suggested'] = len(edges) - confirmed
    return dict(nodes=nodes, edges=edges, report=rep, size=(W, H))


def to_design(rec, canvas_w=1000.0, underlay=None, source_name=''):
    """Hasil recognize() → rancangan arch_design (koordinat editor)."""
    W, H = rec['size']
    s = canvas_w / float(W or 1)
    nodes, edges = [], []
    for k, n in enumerate(rec['nodes']):
        d = dict(id=f'i{k + 1}', type=n['type'], label=n.get('label', ''),
                 rating=n.get('rating', ''), x=round(n['cx'] * s, 1),
                 y=round(n['cy'] * s, 1))
        if n['type'] in ('ac_bus', 'dc_bus'):
            d['w'] = round(max(120.0, (n['box'][2] - n['box'][0]) * s), 1)
            d['label'] = d['label'] if not n.get('line') else (d['label'] or '')
        elif n['type'] == 'rect':
            d['w'] = round((n['box'][2] - n['box'][0]) * s, 1)
            d['h'] = round((n['box'][3] - n['box'][1]) * s, 1)
        if rec['report'].get('sheet') and n['type'] != 'rect':
            # ukuran kartu asli (dipakai tata letak laporan 'sesuai gambar')
            if n['type'] not in ('ac_bus', 'dc_bus'):
                d['bw'] = round((n['box'][2] - n['box'][0]) * s, 1)
            d['bh'] = round((n['box'][3] - n['box'][1]) * s, 1)
        if n.get('status') in ('existing', 'future'):
            d['status'] = n['status']
        if n.get('desc') and n['desc'] != d['label']:
            d['desc'] = n['desc']
        nodes.append(d)
    for e in rec['edges']:
        a, b = nodes[e['i']], nodes[e['j']]
        # jenis dari warna garis (lembar CAD) atau bawaan menurut jenis ujung
        kind = e.get('kind') or default_edge_kind(a['type'], b['type'])
        d = dict(id=f'ie{len(edges) + 1}', src=a['id'], dst=b['id'], kind=kind,
                 auto=e['how'])
        if e.get('ports'):
            d['ports'] = {'src': e['ports'][:2], 'dst': e['ports'][2:]}
        edges.append(d)
    des = {'version': 1, 'use_in_report': True, 'nodes': nodes, 'edges': edges,
           'source': {'kind': 'import', 'name': source_name,
                      'method': rec['report'].get('method'),
                      'sheet': bool(rec['report'].get('sheet'))}}
    if rec['report'].get('sheet'):
        des['layout'] = 'drawing'          # laporan: penempatan kartu sesuai gambar
    if underlay:
        des['underlay'] = underlay
    return des


def make_underlay(gray, canvas_w=1000.0, name='', max_px=1400):
    """Simpan gambar asli (skala abu-abu, dikecilkan) utk underlay editor."""
    from PIL import Image
    img = Image.fromarray(np.asarray(gray).astype(np.uint8))
    w, h = img.size
    f = min(1.0, max_px / float(max(w, h)))
    if f < 1.0:
        img = img.resize((int(w * f), int(h * f)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    s = canvas_w / float(w)
    return dict(png_b64=base64.b64encode(buf.getvalue()).decode('ascii'),
                x=0.0, y=0.0, w=round(w * s, 1), h=round(h * s, 1),
                opacity=0.35, visible=True, name=name)


def load_image_gray(path):
    from PIL import Image
    img = Image.open(path)
    img = img.convert('L')
    return np.asarray(img)


# =================================================== lembar gambar CAD ======
# Lembar gambar teknik (AutoCAD/Revit/…): bingkai utama + blok judul + label
# grid + legenda. Hanya diagram di dalam JENDELA UTAMA yang diambil. Komponen
# = kartu kotak (sudut membulat, garis tepi hitam/abu-abu/biru putus-putus),
# teks dibaca per kotak; sambungan = garis BERWARNA (jenis dari legenda).
_WORK_LONG = 4000.0          # skala kerja (sisi panjang jendela utama, piksel)

# kelas warna → jenis sambungan bawaan (konvensi umum & legenda tipikal)
_COLOUR_KIND = {'red': 'ac', 'blue': 'dc', 'olive': 'ac', 'magenta': 'tcpip',
                'green': 'fo', 'cyan': 'can', 'orange': 'rs485', 'grey': 'wired',
                'black': 'wireless'}          # garis hitam PUTUS-PUTUS di luar kartu
_LEGEND_WORDS = [('dc', r'\bdc\s*power'), ('ac', r'\bac\s*power'),
                 ('tcpip', r'tcp|ethernet|\blan\b'), ('fo', r'\bf\.?o\b|fib(er|re)|optic'),
                 ('can', r'\bcan\b'), ('rs485', r'serial|rs-?\s?485|modbus\s*rtu'),
                 ('wireless', r'wireless|radio|wi-?fi'), ('wired', r'hard\s*wire|wired'),
                 ('ac', r'busbar'), ('existing', r'existing')]


def _rgb(a):
    a = np.asarray(a)
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, axis=2)
    return a[..., :3].astype(np.int16)


def _ink(rgb, lim=170):
    mn, mx = rgb.min(2), rgb.max(2)
    return (mn < lim) | ((mx - mn) > 70)


def _long_runs(mask, frac, gap=6):
    """Garis lurus panjang (≥ frac × panjang sumbu) per baris → [(pos, a, b)]."""
    out = []
    L_ = mask.shape[1]
    sums = mask.sum(1)
    for y in np.flatnonzero(sums >= L_ * frac):
        idx = np.flatnonzero(mask[y])
        br = np.flatnonzero(np.diff(idx) > gap)
        st = np.r_[idx[0], idx[br + 1]]; en = np.r_[idx[br], idx[-1]]
        k = int((en - st).argmax())
        if en[k] - st[k] >= L_ * frac:
            out.append((int(y), int(st[k]), int(en[k])))
    m = []
    for y, a, b in out:
        if m and y - m[-1][1] <= 3 and abs(a - m[-1][2]) < 25 and abs(b - m[-1][3]) < 25:
            m[-1][1] = y
        else:
            m.append([y, y, a, b])
    return [((q[0] + q[1]) / 2.0, q[2], q[3]) for q in m]


def find_main_frame(img):
    """Jendela utama lembar gambar → (x0, y0, x1, y1) piksel, atau None.

    Dicari dari garis bingkai panjang: persegi TERKECIL yang sisi-sisinya
    tergambar, luas ≥ 40 % halaman, lebar & tinggi ≥ 50 % (blok judul,
    kolom label grid, dan bingkai luar tersisih dengan sendirinya)."""
    rgb = _rgb(img)
    H, W = rgb.shape[:2]
    f = min(1.0, 2000.0 / max(H, W))            # deteksi cukup di ~2000 px
    if f < 1.0:
        step = int(round(1 / f))
        rgb = rgb[::step, ::step]
        f = 1.0 / step
    h, w = rgb.shape[:2]
    ink = _ink(rgb, 175)
    Hs = _long_runs(ink, 0.45)
    Vs = _long_runs(ink.T, 0.45)
    if len(Hs) < 2 or len(Vs) < 2:
        return None
    tol = max(6, int(0.01 * max(h, w)))
    best = None
    for i, (yt, ta, tb) in enumerate(Hs):
        for (yb, ba, bb) in Hs[i + 1:]:
            if yb - yt < 0.5 * h:
                continue
            for j, (xl, la, lb) in enumerate(Vs):
                for (xr, ra, rb) in Vs[j + 1:]:
                    if xr - xl < 0.5 * w:
                        continue
                    # sisi vertikal menutup rentang y, sisi horizontal rentang x
                    if not (la <= yt + tol and lb >= yb - tol and
                            ra <= yt + tol and rb >= yb - tol):
                        continue
                    if not (ta <= xl + tol and tb >= xr - tol and
                            ba <= xl + tol and bb >= xr - tol):
                        continue
                    area = (xr - xl) * (yb - yt)
                    if area < 0.4 * h * w:
                        continue
                    if best is None or area < best[0]:
                        best = (area, xl, yt, xr, yb)
    if best is None:
        return None
    _a, x0, y0, x1, y1 = best
    # lebih kecil dari halaman secara nyata (bukan sekadar tepi gambar)?
    if (x1 - x0) * (y1 - y0) > 0.985 * h * w:
        return None
    return tuple(int(round(v / f)) for v in (x0, y0, x1, y1))


def _hue_classes(rgb):
    """Kelas warna garis per piksel → dict nama → mask bool."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(2), rgb.min(2)
    s = mx - mn
    sat = s > 60
    d = np.where(s == 0, 1, s).astype(np.float32)
    h = np.zeros(r.shape, np.float32)
    m = (mx == r)
    h[m] = (60 * ((g[m] - b[m]) / d[m])) % 360
    m2 = (mx == g) & ~m
    h[m2] = 60 * ((b[m2] - r[m2]) / d[m2]) + 120
    m3 = ~m & ~m2
    h[m3] = 60 * ((r[m3] - g[m3]) / d[m3]) + 240
    cls = {
        'red': sat & ((h < 12) | (h >= 340)),
        'orange': sat & (h >= 12) & (h < 45),
        'olive': sat & (h >= 45) & (h < 75),
        'green': sat & (h >= 75) & (h < 160),
        'cyan': sat & (h >= 160) & (h < 200),
        'blue': sat & (h >= 200) & (h < 265),
        'magenta': sat & (h >= 265) & (h < 340),
        'grey': (s < 22) & (mn > 105) & (mn < 195),
        'black': (mx < 115) & (s < 40),   # termasuk titik kecil ber-antialias (garis titik-titik)
    }
    return cls


def _segments(mask, minlen=40, gap=20):
    """Segmen garis horizontal (toleransi putus-putus) → [(y, a, b)] tergabung."""
    out = []
    sums = mask.sum(1)
    for y in np.flatnonzero(sums >= minlen):
        idx = np.flatnonzero(mask[y])
        br = np.flatnonzero(np.diff(idx) > gap)
        st = np.r_[idx[0], idx[br + 1]]; en = np.r_[idx[br], idx[-1]]
        for a, b in zip(st, en):
            if b - a >= minlen:
                out.append((int(y), int(a), int(b)))
    last, merged = {}, []
    for y, a, b in out:
        k = (round(a / 5), round(b / 5))
        hit = None
        for kk in ((k[0] + i, k[1] + j) for i in (-1, 0, 1) for j in (-1, 0, 1)):
            if kk in last and y - last[kk][1] <= 2:
                hit = kk
                break
        if hit:
            last[hit][1] = y
        else:
            last[k] = [y, y, a, b]
            merged.append(last[k])
    return [((q[0] + q[1]) / 2.0, q[2], q[3]) for q in merged]


def _sheet_rects(ink):
    """Kotak bersudut (membulat / garis putus-putus) → [(x0, y0, x1, y1)]."""
    from collections import defaultdict
    Hs = _segments(ink)
    Vs = _segments(ink.T)
    vb = defaultdict(list)
    for x, c, d in Vs:
        vb[int(x) // 20].append((x, c, d))

    def find_v(xlo, xhi, ylo, yhi, near):
        # sisi kotak = garis vertikal TERDEKAT ke ujung tepi atas (bukan kabel
        # lurus yang kebetulan sejajar di dekat sisi kartu)
        best = None
        for bkt in range(int(xlo) // 20, int(xhi) // 20 + 1):
            for (x, c, d) in vb.get(bkt, []):
                if xlo <= x <= xhi and c <= ylo and d >= yhi:
                    if best is None or abs(x - near) < abs(best - near):
                        best = x
        return best
    hb = defaultdict(list)
    for sg in Hs:
        hb[(sg[1] // 10, sg[2] // 10)].append(sg)
    rects = set()
    for (ka, kb), lst in hb.items():
        cand = []
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                cand += hb.get((ka + i, kb + j), [])
        for (yt, a, b) in lst:
            for (yb, a2, b2) in cand:
                if yb - yt < 40 or abs(a - a2) > 10 or abs(b - b2) > 10:
                    continue
                r = min(60, 0.3 * (yb - yt))
                xl = find_v(a - 70, a + 4, yt + r + 4, yb - r - 4, a)
                if xl is None:
                    continue
                xr = find_v(b - 4, b + 70, yt + r + 4, yb - r - 4, b)
                if xr is None:
                    continue
                rects.add((int(xl), int(yt), int(xr), int(yb)))
    clean = []
    for rc in sorted(rects):
        if any(abs(rc[0] - q[0]) < 8 and abs(rc[1] - q[1]) < 8 and abs(rc[2] - q[2]) < 8
               and abs(rc[3] - q[3]) < 8 for q in clean):
            continue
        clean.append(rc)
    # buang kotak yang 'menjangkau' dua kotak bertumpuk (atas + bawah sama-sama
    # terdeteksi); baris teks lebar di dalam kartu TIDAK membelah kartu
    def same_sides(a, b):
        return abs(a[0] - b[0]) < 8 and abs(a[2] - b[2]) < 8

    def spans_two(rc):
        for q in clean:
            if q != rc and same_sides(q, rc) and abs(q[1] - rc[1]) < 8 and q[3] < rc[3] - 20:
                if any(q2 != rc and same_sides(q2, rc) and q2[1] >= q[3] + 10
                       and abs(q2[3] - rc[3]) < 8 for q2 in clean):
                    return True
        return False
    return [rc for rc in clean if not spans_two(rc)]


def _inside(a, b, t=3):
    return (a is not b and a != b and a[0] >= b[0] - t and a[1] >= b[1] - t
            and a[2] <= b[2] + t and a[3] <= b[3] + t)


def _ocr_img(img, psm):
    import pytesseract
    try:
        return pytesseract.image_to_string(img, config=f'--psm {psm}')
    except Exception:
        return ''


def _box_text(gray, rc, full=False):
    """OCR pita judul kotak (atau seluruh kotak) — huruf CAD, diperbesar 2×."""
    from PIL import Image
    x0, y0, x1, y1 = rc
    h = y1 - y0
    yb = y1 - 6 if full else y0 + min(120, int(0.4 * h))
    crop = gray[y0 + 4:yb, x0 + 8:x1 - 8]
    if crop.size == 0:
        return ''
    img = Image.fromarray(crop.astype(np.uint8))
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    img = img.point(lambda v: 255 if v > 175 else 0)
    return norm_text(_ocr_img(img, 6))


def _outline_colour(rgb, rc):
    x0, y0, x1, _y1 = rc
    if x1 - x0 < 90:
        return 'none'
    band = rgb[max(0, y0 - 2):y0 + 3, x0 + 40:x1 - 40].reshape(-1, 3)
    ink = band[band.min(1) < 200]
    if not len(ink):
        return 'none'
    m = ink.mean(0)
    if m[2] > m[0] + 60:
        return 'blue'
    return 'grey' if m.min() > 110 else 'black'


def _legend_map(gray, rgb, rc, cls, words=None):
    """Baca legenda: setiap baris teks ↔ warna garis contoh di kirinya.

    words: kata/baris (teks, x0, y0, x1, y1) koordinat kerja (RapidOCR/PDF);
    None → OCR Tesseract pada kotak legenda."""
    x0, y0, x1, y1 = rc
    if words is not None:
        lines = {}
        for i, (t, a, b, c, d) in enumerate(words):
            if x0 <= (a + c) / 2 <= x1 and y0 <= (b + d) / 2 <= y1:
                lines[i] = dict(t=[t], x0=a - x0, x1=c - x0, y0=b - y0, y1=d - y0)
        return _legend_colours(lines, rc, cls)
    import pytesseract
    from PIL import Image
    sub = gray[y0:y1, x0:x1]
    img = Image.fromarray(sub.astype(np.uint8))
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    img = img.point(lambda v: 255 if v > 175 else 0)
    try:
        d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT,
                                      config='--psm 6')
    except Exception:
        return {}
    lines = {}
    for i, t in enumerate(d.get('text', [])):
        t = (t or '').strip()
        if not t:
            continue
        key = (d['block_num'][i], d['par_num'][i], d['line_num'][i])
        L_ = lines.setdefault(key, dict(t=[], x0=1e9, x1=0, y0=1e9, y1=0))
        L_['t'].append(t)
        L_['x0'] = min(L_['x0'], d['left'][i] / 2.0)
        L_['x1'] = max(L_['x1'], (d['left'][i] + d['width'][i]) / 2.0)
        L_['y0'] = min(L_['y0'], d['top'][i] / 2.0)
        L_['y1'] = max(L_['y1'], (d['top'][i] + d['height'][i]) / 2.0)
    return _legend_colours(lines, rc, cls)


def _legend_colours(lines, rc, cls):
    x0, y0, x1, y1 = rc
    out = {}
    wl = x1 - x0
    for L_ in lines.values():
        txt = ' '.join(L_['t']).lower()
        cy0, cy1 = int(y0 + L_['y0'] - 4), int(y0 + L_['y1'] + 4)
        xa = int(x0 + max(8, L_['x0'] - 0.30 * wl)); xb = int(x0 + L_['x0'] - 4)
        # jangan ikutkan teks kolom legenda sebelah kiri (tepi kanan teks + jarak)
        for M_ in lines.values():
            if M_ is L_ or 'x1' not in M_ or M_['x1'] >= L_['x0']:
                continue
            if M_['y1'] > L_['y0'] and M_['y0'] < L_['y1']:
                xa = max(xa, int(x0 + M_['x1'] + 4))
        if xb <= xa:
            continue
        kind = next((k for k, pat in _LEGEND_WORDS if re.search(pat, txt)), None)
        if kind is None or kind == 'existing':
            continue
        cnt = {c: int(m[cy0:cy1, xa:xb].sum()) for c, m in cls.items()}
        blk = None
        if cnt.get('black', 0) > 15:
            dot, dash = _split_dots(cls['black'][cy0:cy1, xa:xb], None)
            blk = 'black_dot' if dot.sum() >= dash.sum() else 'black_dash'
        if kind == 'wireless':                      # garis hitam titik/putus-putus
            best = blk
        elif kind == 'wired':                       # garis abu-abu / hitam putus-putus
            best = 'grey' if cnt.get('grey', 0) > 30 and blk is None else blk
        else:                                       # warna kromatis terbanyak
            best, bn = None, 25
            for c, n in cnt.items():
                if c not in ('grey', 'black') and n > bn:
                    best, bn = c, n
        if best is not None and best not in out:
            out[best] = kind
    return out


def _components(mask):
    """Komponen terhubung-8 (BFS numpy-list, tanpa SciPy) → list array indeks."""
    H, W = mask.shape
    lab = np.full(mask.shape, -1, np.int32)
    comps = []
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if lab[y, x] >= 0:
            continue
        k = len(comps)
        lab[y, x] = k
        stack = [(y, x)]
        cells = []
        while stack:
            cy, cx = stack.pop()
            cells.append((cy, cx))
            for dy in (-1, 0, 1):
                ny = cy + dy
                if ny < 0 or ny >= H:
                    continue
                for dx in (-1, 0, 1):
                    nx = cx + dx
                    if 0 <= nx < W and mask[ny, nx] and lab[ny, nx] < 0:
                        lab[ny, nx] = k
                        stack.append((ny, nx))
        comps.append(cells)
    return comps


def _close_dashes(m, gap, aligned=False):
    """Tutup celah ≤ gap sel sepanjang baris & kolom (garis putus-putus).

    aligned=True: celah hanya ditutup bila potongan di KEDUA sisinya searah
    penutupan (ruas searah ≥ ruas melintang) — garis sejajar berdekatan dan
    belokan garis tetangga tidak ikut tersambung melintang."""
    out = m.copy()
    for arr, res in ((m, out), (m.T, out.T)):
        if aligned:
            along = _runs(arr)
            across = _runs(np.ascontiguousarray(arr.T)).T
        for r in range(arr.shape[0]):
            idx = np.flatnonzero(arr[r])
            if len(idx) < 2:
                continue
            d = np.diff(idx)
            for k in np.flatnonzero((d > 1) & (d <= gap + 1)):
                if aligned:
                    a_, b_ = idx[k], idx[k + 1]
                    if along[r, a_] < across[r, a_] or along[r, b_] < across[r, b_]:
                        continue
                res[r, idx[k]:idx[k + 1]] = True
    return out


def _runs(M):
    """Panjang ruas horizontal tiap piksel True (vektor numpy)."""
    H, W = M.shape
    p = np.zeros((H, W + 2), np.int8)
    p[:, 1:-1] = M
    d = np.diff(p, axis=1)
    sr, sc = np.nonzero(d == 1)
    er, ec = np.nonzero(d == -1)
    L = ec - sc
    out = np.zeros(H * W, np.int32)
    if len(L):
        st = sr * W + sc
        tot = int(L.sum())
        off = np.arange(tot) - np.repeat(np.cumsum(L) - L, L)
        out[np.repeat(st, L) + off] = np.repeat(L, L)
    return out.reshape(H, W)


def _dot_pixels(m):
    """Piksel garis TITIK-TITIK: ruas horizontal & vertikal sama-sama pendek
    (≤ ~1,5× tebal garis) — garis utuh/putus-putus & huruf punya ruas panjang."""
    if not m.any():
        return np.zeros_like(m, dtype=bool)
    h = _runs(m)
    v = _runs(m.T).T
    mn = np.minimum(h, v)[m]
    thick = float(np.median(mn)) if mn.size else 2.0
    dmax = max(4, int(round(1.5 * thick)))
    lng = m & ((h > dmax) | (v > dmax))
    # piksel pendek yang MENEMPEL ruas panjang (ujung bulat putus-putus, huruf)
    # bukan titik → buang tetangga ≤2 px dari ruas panjang
    g = lng.copy()
    for _ in range(2):
        g2 = g.copy()
        g2[1:] |= g[:-1]; g2[:-1] |= g[1:]; g2[:, 1:] |= g[:, :-1]; g2[:, :-1] |= g[:, 1:]
        g = g2
    return m & ~g


def _split_dots(md, dmax=None):
    """Pisahkan potongan garis hitam: TITIK (≤ dmax sel; None = relatif terhadap
    tebal garis) vs putus-putus/garis → (mask_titik, mask_garis)."""
    dot = np.zeros_like(md, dtype=bool)
    comps = _components(md)
    if dmax is None:
        th = [min(np.ptp([c[0] for c in cc]), np.ptp([c[1] for c in cc])) + 1
              for cc in comps if len(cc) > 2]
        dmax = max(2, int(round(2.4 * (float(np.median(th)) if th else 1.0))))
    for cc in comps:
        ys = [c[0] for c in cc]; xs = [c[1] for c in cc]
        if max(max(ys) - min(ys), max(xs) - min(xs)) + 1 <= dmax:
            dot[ys, xs] = True
    return dot, (md & ~dot)


def _mst(idx, pos):
    """Pohon rentang minimum (Prim) atas titik pusat → [(i, j)]."""
    idx = list(idx)
    if len(idx) < 2:
        return []
    done, out = {idx[0]}, []
    while len(done) < len(idx):
        best = None
        for a in done:
            for b in idx:
                if b in done:
                    continue
                dd = abs(pos[a][0] - pos[b][0]) + abs(pos[a][1] - pos[b][1])
                if best is None or dd < best[0]:
                    best = (dd, a, b)
        done.add(best[2])
        out.append((best[1], best[2]))
    return out


# merek pabrikan pada kartu (bukan bagian nama blok)
_BRANDS = r'SUNGROW|HUAWEI|CATL|TRINA|JINKO|LONGI|SMA|GROWATT|GOODWE|SOLIS|DEYE|BYD|' \
          r'PYLONTECH|SCHNEIDER|ABB|SIEMENS|VICTRON|TERAPOWER'


def _strip_brand(t):
    return ' '.join(re.sub(r'(?i)(?<![A-Za-z0-9-])(?:%s)(?![A-Za-z0-9-])' % _BRANDS,
                           ' ', t).split()) or t


def _vocab_hits(t):
    return sum(1 for w in re.findall(r'[A-Za-z]{2,}', t) if w.lower() in _VOCAB)


def _odd_words(t):
    """Teks kartu tampak salah-baca: ada kata huruf (>=4) di luar kosakata."""
    for w in re.findall(r'[A-Za-z]{4,}', t)[:4]:
        if w.lower() not in _VOCAB and not re.search(r'(?i)%s' % _BRANDS, w):
            return True
    return False


def recognize_sheet(img, words=None, frame=None):
    """Kenali lembar gambar CAD (hanya jendela utama).

    img: ndarray RGB/abu (H, W[, 3]); words: teks PDF [(t, x0, y0, x1, y1)]
    dalam piksel img (opsional); frame: (x0, y0, x1, y1) atau None (dideteksi).
    Kembalikan dict seperti recognize() + 'frame' (piksel img) — koordinat
    node relatif terhadap POJOK jendela utama, pada resolusi img. None bila
    tak ada bingkai (bukan lembar gambar)."""
    from PIL import Image
    rgb0 = _rgb(img)
    frame = frame or find_main_frame(rgb0)
    if frame is None:
        return None
    fx0, fy0, fx1, fy1 = frame
    pad = max(4, int(0.0015 * max(rgb0.shape[:2])))
    cx0, cy0, cx1, cy1 = fx0 + pad, fy0 + pad, fx1 - pad, fy1 - pad

    def _work(x0, y0, x1, y1, smax):
        crop_ = rgb0[y0:y1, x0:x1]
        hc, wc = crop_.shape[:2]
        s_ = max(0.5, min(smax, _WORK_LONG / float(max(hc, wc))))
        if abs(s_ - 1.0) > 0.05:
            im_ = Image.fromarray(crop_.astype(np.uint8)).resize(
                (int(wc * s_), int(hc * s_)), Image.LANCZOS if s_ < 1 else Image.BICUBIC)
            return np.asarray(im_).astype(np.int16), s_, hc, wc
        return crop_, 1.0, hc, wc
    rgb, s, Hc, Wc = _work(cx0, cy0, cx1, cy1, 2.0)
    s_base = s
    ink = _ink(rgb, 185)
    rects = [r for r in _sheet_rects(ink) if r[2] - r[0] >= 100 and r[3] - r[1] >= 70]
    # diagram KECIL di dalam jendela utama (mis. blok diagram tipikal di pojok
    # lembar) → potong ke area kartu & perbesar agar teks/garis terbaca
    small = [r for r in _sheet_rects(ink) if r[2] - r[0] >= 30 and r[3] - r[1] >= 22]
    if len(small) >= 4:
        # buang pencilan (mis. huruf judul besar yang membentuk 'kotak'): pakai
        # kotak yang pusatnya di dalam rentang persentil 4–96 %
        cxs = np.array([(r[0] + r[2]) / 2 for r in small])
        cys = np.array([(r[1] + r[3]) / 2 for r in small])
        qx0, qx1 = np.percentile(cxs, [4, 96]); qy0, qy1 = np.percentile(cys, [4, 96])
        core = [r for r, x_, y_ in zip(small, cxs, cys)
                if qx0 <= x_ <= qx1 and qy0 <= y_ <= qy1] or small
        bx0 = min(r[0] for r in core); by0 = min(r[1] for r in core)
        bx1 = max(r[2] for r in core); by1 = max(r[3] for r in core)
        # perluas lagi ke kotak yang BERDEKATAN dengan inti (baris terluar diagram)
        msz = float(np.median([max(r[2] - r[0], r[3] - r[1]) for r in small]))
        grew = True
        while grew:
            grew = False
            for r in small:
                if r[0] >= bx0 and r[1] >= by0 and r[2] <= bx1 and r[3] <= by1:
                    continue
                gx = max(0, bx0 - r[2], r[0] - bx1); gy = max(0, by0 - r[3], r[1] - by1)
                if max(gx, gy) <= 1.2 * msz:
                    bx0, by0 = min(bx0, r[0]), min(by0, r[1])
                    bx1, by1 = max(bx1, r[2]), max(by1, r[3]); grew = True
        H_, W_ = ink.shape
        if (bx1 - bx0) * (by1 - by0) < 0.45 * H_ * W_:
            mg = 0.06 * max(bx1 - bx0, by1 - by0)
            nx0 = int(cx0 + max(0, bx0 - mg) / s); ny0 = int(cy0 + max(0, by0 - mg) / s)
            nx1 = int(cx0 + min(W_, bx1 + mg) / s); ny1 = int(cy0 + min(H_, by1 + mg) / s)
            cx0, cy0, cx1, cy1 = nx0, ny0, nx1, ny1
            rgb, s, Hc, Wc = _work(cx0, cy0, cx1, cy1, 3.0)
            ink = _ink(rgb, 185)
            rects = [r for r in _sheet_rects(ink) if r[2] - r[0] >= 100 and r[3] - r[1] >= 70]
    gray = (rgb @ np.array([0.299, 0.587, 0.114])).astype(np.uint8)
    H, W = gray.shape
    cls = _hue_classes(rgb)
    # teks PDF → koordinat kerja; dipakai HANYA bila benar-benar memuat teks kartu
    # (gambar CAD sering hanya punya teks blok judul/logo → tetap pakai OCR)
    wk = []
    for t, a, b, c, d in (words or []):
        wx, wy = ((a + c) / 2 - cx0) * s, ((b + d) / 2 - cy0) * s
        if 0 <= wx <= W and 0 <= wy <= H:
            wk.append((t, (a - cx0) * s, (b - cy0) * s, (c - cx0) * s, (d - cy0) * s))
    if wk and rects:
        cov = sum(1 for r in rects if any(r[0] <= (w[1] + w[3]) / 2 <= r[2]
                                          and r[1] <= (w[2] + w[4]) / 2 <= r[3] for w in wk))
        if cov < 0.3 * len(rects):
            wk = []
    engine = None if wk else ocr_engine()
    rep = dict(method='pdf-text' if wk else ('ocr' if engine else 'none'),
               engine=engine, words=len(wk),
               messages=[('info', 'sheet_frame')], sheet=True)
    if not wk and engine == 'rapidocr':
        wk = rapid_words(rgb)                    # satu kali untuk seluruh area diagram
        rep['words'] = len(wk)
        if not wk:
            rep['method'] = 'none'
    use_ocr = not wk and engine == 'tesseract'

    def text_of(rc, full=False):
        if wk:
            ws = [w for w in wk if rc[0] <= (w[1] + w[3]) / 2 <= rc[2]
                  and rc[1] <= (w[2] + w[4]) / 2 <= rc[3]]
            ws.sort(key=lambda w: (round(w[2] / 12), w[1]))
            return norm_text(' '.join(w[0] for w in ws))
        return _box_text(gray, rc, full) if use_ocr else ''

    # --- struktur: kartu, wadah (grup), ikon di dalam kartu ---
    med = float(np.median([min(r[2] - r[0], r[3] - r[1]) for r in rects])) if rects else 200.0
    containers = [r for r in rects if r[2] - r[0] > 2.5 * med and r[3] - r[1] > 2.5 * med]
    # kotak 'palsu' = tepi kartu tetangga + kartu sebenarnya (mis. kotak putus-putus
    # membulat tepat di bawah kartu lain): kotak dalam yang hampir memenuhi
    # kotak luar → kotak dalam = kartu, kotak luar dibuang
    def _ar(q):
        return float(q[2] - q[0]) * (q[3] - q[1])
    def _shares_edge(q):
        # tepi atas/bawah q berimpit dengan tepi kotak LAIN yang tidak di dalam q
        for o in rects:
            if o is q or o in containers or _inside(o, q) or _inside(q, o):
                continue
            if min(o[2], q[2]) - max(o[0], q[0]) < 0.5 * (q[2] - q[0]):
                continue
            if abs(q[1] - o[3]) < 6 or abs(q[3] - o[1]) < 6:
                return True
        return False
    spurious = set()
    for r in rects:
        if r in containers:
            continue
        for q in rects:
            if q is r or q in containers or not _inside(r, q) or not _shares_edge(q):
                continue
            if _ar(r) >= 0.45 * _ar(q) and (r[2] - r[0]) >= 0.75 * (q[2] - q[0]) \
                    and min(r[2] - r[0], r[3] - r[1]) >= 0.6 * med:
                spurious.add(q)
    cards = []
    for r in rects:
        if r in containers or r in spurious:
            continue
        par = [q for q in rects if _inside(r, q) and q not in containers and q not in spurious]
        if par:
            continue                     # ikon/simbol di dalam kartu
        cards.append(r)
    # --- teks & jenis ---
    legend = None
    nodes = []
    queue = list(cards)
    promoted = set()
    while queue:
        r = queue.pop(0)
        t = text_of(r)
        low = t.lower()
        _lg = r'power|protocol|comm\.|cable|facility|busbar|legend|wireless|serial'
        if use_ocr and len(re.findall(_lg, low)) == 1:
            low = (t + ' ' + _box_text(gray, r, full=True)).lower()
        if len(re.findall(_lg, low)) >= 2:
            legend = r
            continue
        typ = classify(t) if t else None
        if typ is None:
            rep.setdefault('unread', []).append((tuple(int(v) for v in r), t[:40]))
        reread = typ is None or _odd_words(t)
        if typ is None and use_ocr:
            t2 = _box_text(gray, r, full=True)
            if classify(t2):
                t, typ = t2, classify(t2)
        elif reread and _rapid() is not None and rep['method'] != 'pdf-text':
            # baca ulang kotak ini sendiri, DIPERBESAR (huruf kecil pada lembar padat;
            # konteks ubin kadang mengacaukan deteksi)
            sub = rgb[max(0, r[1] - 4):r[3] + 5, max(0, r[0] - 4):r[2] + 5].astype(np.uint8)
            fz = max(1.0, min(3.0, 480.0 / max(1, sub.shape[1])))
            if fz > 1.05:
                sub = np.asarray(Image.fromarray(sub).resize(
                    (int(sub.shape[1] * fz), int(sub.shape[0] * fz)), Image.BICUBIC))
            sub = np.ascontiguousarray(sub)
            try:
                out, _t = _rapid()(sub, use_cls=False)
            except Exception:
                out = None
            out = sorted(out or [], key=lambda o: (round(o[0][0][1] / 12), o[0][0][0]))
            t2 = norm_text(' '.join(str(o[1]) for o in out if float(o[2]) >= 0.5))
            if classify(t2) and (typ is None or _vocab_hits(t2) > _vocab_hits(t)):
                t, typ = t2, classify(t2)
        if typ is None:
            # kotak tak terbaca yang MEMBUNGKUS kotak lain (mis. tepi kartu di atasnya
            # ikut tergabung) → periksa kotak-kotak di dalamnya sebagai kartu
            kids = [q for q in rects if _inside(q, r) and q not in containers
                    and q not in promoted and q not in cards
                    and q[2] - q[0] >= 0.6 * med and q[3] - q[1] >= 0.6 * med]
            kids = [q for q in kids if not any(_inside(q, o) for o in kids)]
            for q in kids:
                promoted.add(q)
                queue.append(q)
            continue
        nodes.append(dict(type=typ, text=t, box=tuple(float(v) for v in r),
                          status={'blue': 'existing', 'grey': 'future'}.get(
                              _outline_colour(rgb, r), 'proposed')))
    # kartu ganda (dua persegi terdeteksi utk satu kartu) → simpan yang terbesar
    nodes.sort(key=lambda n: -(n['box'][2] - n['box'][0]) * (n['box'][3] - n['box'][1]))
    kept = []
    for n in nodes:
        a = n['box']; ar = (a[2] - a[0]) * (a[3] - a[1])
        dup = False
        for m in kept:
            b = m['box']
            ix = min(a[2], b[2]) - max(a[0], b[0]); iy = min(a[3], b[3]) - max(a[1], b[1])
            if ix > 0 and iy > 0 and ix * iy > 0.5 * min(ar, (b[2] - b[0]) * (b[3] - b[1])):
                dup = True
                break
        if not dup:
            kept.append(n)
    nodes = kept
    # label = NAMA UTAMA (tag kartu, mis. BESS-01 / PCS-01 / INV-01 / LV-PV1);
    # teks lengkap disimpan di 'desc'
    _TAG = re.compile(r'^(?:[A-Z]{2,6}(?:-[A-Z0-9#]{1,6}){1,3}|[A-Z]{2,5}\d{1,3})$')
    _STOP = {'TYPE', 'TOTAL', 'MAX', 'BATT', 'BATT.', 'HUAWEI', 'TRINA', 'CATL', 'DYNX',
             'DYNX,', 'DYX', 'DYX,', 'ONAN', 'ONAN,', 'MANUALLY', 'OP', 'OP.', 'TERAPOWER'}

    def _words(t):
        body = re.sub(r"^[\W_]+", '', t)
        ws = [w for w in re.split(r'\s+', body) if len(re.findall(r'[A-Za-z0-9]', w)) >= 2]
        while len(ws) > 1 and len(ws[0]) <= 2 and not re.search(r'\d', ws[0]) \
                and ws[0].upper() not in ('LV', 'MV', 'HV', 'PV', 'AC', 'DC', 'CB'):
            ws.pop(0)                                   # sisa ikon/garis di pita judul
        return ws

    def _is_tag(w):
        w = w.strip(',.;:()')
        return bool(_TAG.match(w)) and bool(re.search(r'\d|-', w))

    for n in nodes:
        t = n['text']
        ws = _words(t)
        n['desc'] = _strip_brand(' '.join(ws))[:120]
        n['rating'] = rating_of(t)
        tag = next((w.strip(',.;:()') for w in ws[:4] if _is_tag(w)), None)
        if tag:
            n['label'] = tag
            continue
        m_ohl = re.search(r'(?i)\bOHL\b.*?(\d+(?:[.,]\d+)?\s*K?M)\b', t)
        if m_ohl:
            n['label'] = 'OHL ' + m_ohl.group(1).replace(' ', '').upper()
            continue
        name = []
        for w in ws:
            wu = w.upper()
            if w.startswith('(') and name:
                break
            if wu in _STOP or _RATING.fullmatch(w) or re.fullmatch(r'[\d.,/]+', w) \
                    or re.fullmatch(r'(?i)(?:%s)[.,]?' % _BRANDS, w):
                break
            if re.match(r'^\d', w) and name:
                break
            if wu.strip(',.') in ('MVA', 'KVA', 'KW', 'KWP', 'KWH', 'MW', 'MWH', 'KV', 'V'):
                break
            name.append(w.rstrip(','))
            if w.endswith(','):
                # kode singkat sesudah koma (mis. "TURBINE ALT, STG") → "(STG)"
                i_ = ws.index(w)
                nx = ws[i_ + 1].strip(',.;:()') if i_ + 1 < len(ws) else ''
                if re.fullmatch(r'[A-Z]{2,4}', nx) and nx not in _STOP and \
                        not _RATING.fullmatch(nx):
                    name.append(f'({nx})')
                break
            if len(name) >= 4:
                break
        n['label'] = ' '.join(name)[:40] or ' '.join(ws[:2])[:40]
    # nama kembar → pakai tag di mana pun dalam teks, lalu rating
    from collections import Counter
    cnt = Counter(n['label'] for n in nodes)
    for n in nodes:
        if cnt[n['label']] > 1 and not _is_tag(n['label']):
            tag = next((w.strip(',.;:()') for w in _words(n['text']) if _is_tag(w)), None)
            if tag:
                n['label'] = tag
    cnt = Counter(n['label'] for n in nodes)
    for n in nodes:
        if cnt[n['label']] > 1:
            ws = [w for w in _words(n['text']) if w.strip(',.;:()') != n['label']]
            extra = next((w.strip(',.;:()') for w in ws if w.upper().strip(',.') in
                          ('CONTROLLER', 'CONTROL', 'CABINET', 'PANEL', 'LOAD')), None)
            if extra and n['type'] in COMM_TYPES_FOR_LABEL and \
                    extra.upper() not in n['label'].upper().split():
                n['label'] = f"{n['label']} {extra}"
            elif not _is_tag(n['label']) and n['rating']:
                n['label'] = f"{n['label']} {n['rating'].split(',')[0]}"
    # jenis rel lebar (switchgear digambar memanjang) → tetap ac_bus
    # wadah → grup visual (rect) dengan label teks pita atasnya
    groups = []
    # wadah bertumpuk dengan sisi kiri/kanan sama (tepi kartu ikut membentuk
    # 'wadah' semu) → simpan yang terbesar saja
    cont = sorted(containers, key=lambda q: -_ar(q))
    cont_k = []
    for r in cont:
        if any(abs(r[0] - q[0]) < 10 and abs(r[2] - q[2]) < 10 and _inside(r, q, 10)
               for q in cont_k):
            continue
        cont_k.append(r)
    for r in cont_k:
        kids = [n for n in nodes if _inside(n['box'], r)]
        if len(kids) < 2:
            continue
        # keterangan wadah di BAWAH bingkai (mis. "PV-BESS EXISTING #1 (PROJECT …)")
        cap = (r[0], r[3] + 2, r[2], int(r[3] + 0.45 * med))
        free = not any(n['box'][0] < cap[2] and n['box'][2] > cap[0] and
                       n['box'][1] < cap[3] and n['box'][3] > cap[1] for n in nodes)
        tc = text_of(cap) if free else ''
        if len(re.findall(r'[A-Za-z]{2,}', tc)) >= 2:
            groups.append(dict(type='rect', label=tc[:48], rating='',
                               box=tuple(float(v) for v in r), text=tc))
            continue
        # judul wadah = teks di pita atas (di atas kartu anak teratas)
        top = min(n['box'][1] for n in kids)
        t = text_of((r[0], r[1], r[2], int(top) - 2)) if top - r[1] > 12 else ''
        t = t or text_of(r)
        lab = re.split(r'[(\[]', t)[0].strip(' -:,.;') or t[:30]
        groups.append(dict(type='rect', label=lab[:40], rating='',
                           box=tuple(float(v) for v in r), text=t))
    # --- peta warna → jenis dari legenda ---
    cmap = dict(_COLOUR_KIND)
    if legend is not None and (use_ocr or wk):
        try:
            cmap.update(_legend_map(gray, rgb, legend, cls, words=wk if wk else None))
            rep['messages'].append(('info', 'legend'))
        except Exception:
            pass
    # --- sambungan dari garis berwarna ---
    ds = 3
    Hd, Wd = H // ds, W // ds
    boxes = [n['box'] for n in nodes]
    owner = np.full((Hd, Wd), -1, np.int32)
    blank = np.zeros((Hd, Wd), bool)
    zf = max(1.0, s / max(1e-6, s_base))        # faktor perbesaran diagram kecil
    ring = int(round(5 * zf))
    for k, b in enumerate(boxes):
        x0, y0, x1, y1 = (int(v // ds) for v in b)
        owner[max(0, y0 - ring):y1 + ring + 1, max(0, x0 - ring):x1 + ring + 1] = k
    for k, b in enumerate(boxes):
        x0, y0, x1, y1 = (int(v // ds) for v in b)
        e = 0 if nodes[k]['status'] == 'proposed' else 1   # tepi berwarna: +1 sel
        blank[max(0, y0 - e):y1 + e + 1, max(0, x0 - e):x1 + e + 1] = True
    # garis tepi wadah bukan kabel — dihapus HANYA pada kelas warnanya sendiri,
    # agar kabel berwarna lain yang MENYEBERANGI tepi wadah tidak terputus
    bands = []                                    # (kelas, a0, a1, b0, b1, horizontal)
    for g in groups:
        oc = _outline_colour(rgb, tuple(int(v) for v in g['box']))
        oc = {'none': 'grey'}.get(oc, oc)
        x0, y0, x1, y1 = (int(v // ds) for v in g['box'])
        for (a0, a1, b0, b1, hz) in ((y0 - 2, y0 + 3, x0, x1, True),
                                     (y1 - 2, y1 + 3, x0, x1, True),
                                     (y0, y1, x0 - 2, x0 + 3, False),
                                     (y0, y1, x1 - 2, x1 + 3, False)):
            bands.append((oc, max(0, a0), a1, max(0, b0), b1, hz))
    # hitam: garis tepi kartu (setengah tebal di luar kotak) ikut dihapus
    blank_blk = blank.copy()
    for b in boxes:
        x0, y0, x1, y1 = (int(v // ds) for v in b)
        blank_blk[max(0, y0 - 2):y1 + 3, max(0, x0 - 2):x1 + 3] = True
    if legend is not None:
        x0, y0, x1, y1 = (int(v // ds) for v in legend)
        blank[max(0, y0 - 3):y1 + 4, max(0, x0 - 3):x1 + 4] = True
    pos = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]
    edges, seen = [], set()

    used = {}                                     # kelas warna → jenis (terpakai)

    def _port(k, pt):
        """Titik kontak garis → (sisi, posisi 0..1 sepanjang sisi) kotak k."""
        x0, y0, x1, y1 = boxes[k]
        px, py = pt
        d = {'top': y0 - py, 'bottom': py - y1, 'left': x0 - px, 'right': px - x1}
        side = max(d, key=d.get)
        if side in ('top', 'bottom'):
            t = (px - x0) / max(1e-6, x1 - x0)
        else:
            t = (py - y0) / max(1e-6, y1 - y0)
        return [side, round(float(min(0.97, max(0.03, t))), 3)]

    def add(i, j, kind):
        power = kind in ('ac', 'dc')
        # satu jalur daya per pasangan; komunikasi boleh lebih dari satu JENIS
        # (mis. RS485 + CAN dari EMS ke PCS yang sama)
        key = (min(i, j), max(i, j), True if power else kind)
        if i == j or key in seen:
            return
        seen.add(key)
        e = dict(i=i, j=j, how='line', kind=kind)
        # titik sambung ASLI pada gambar (kontak garis terdekat antar kedua kotak)
        ci, cj = cts.get(i) or [], cts.get(j) or []
        if ci and cj:
            pa, pb = min(((a, b) for a in ci for b in cj),
                         key=lambda ab: abs(ab[0][0] - ab[1][0]) + abs(ab[0][1] - ab[1][1]))
            e['ports'] = _port(i, pa) + _port(j, pb)
        edges.append(e)
        used.setdefault(cur[0], cmap.get(cur[0]) or (
            cmap.get('black') if cur[0].startswith('black') else kind))
    cur = [None]
    cts = {}
    comm_rank = {'eth_hub': 0, 'server': 1, 'ems': 2}
    # hitam lebih dulu: antialias-nya terbaca abu-abu. Garis hitam dipisah
    # menurut POLA: titik-titik (nirkabel) vs putus-putus (mis. hardwired)
    passes, black_zone = [], None
    for cname, m in sorted(cls.items(), key=lambda kv: kv[0] != 'black'):
        bl = blank_blk if cname == 'black' else blank
        md = m[:Hd * ds, :Wd * ds].reshape(Hd, ds, Wd, ds).any(axis=(1, 3))
        md &= ~bl
        if cname == 'black':
            black_zone = md.copy()
            black_zone[1:] |= md[:-1]; black_zone[:-1] |= md[1:]
            black_zone[:, 1:] |= md[:, :-1]; black_zone[:, :-1] |= md[:, 1:]
            dpx = _dot_pixels(m)                  # pada resolusi kerja (titik rapat)
            dot = dpx[:Hd * ds, :Wd * ds].reshape(Hd, ds, Wd, ds).any(axis=(1, 3)) & ~bl
            dash = (m & ~dpx)[:Hd * ds, :Wd * ds].reshape(Hd, ds, Wd, ds).any(axis=(1, 3)) & ~bl
            passes += [('black_dash', dash, bl), ('black_dot', dot, bl)]
        else:
            passes.append((cname, md, bl))
    # titik-titik sering berhenti satu jarak titik sebelum kartu → cincin lebih lebar
    ring_dot = ring + int(round(3 * zf))
    owner_dot = np.full((Hd, Wd), -1, np.int32)
    for k, b in enumerate(boxes):
        x0, y0, x1, y1 = (int(v // ds) for v in b)
        owner_dot[max(0, y0 - ring_dot):y1 + ring_dot + 1,
                  max(0, x0 - ring_dot):x1 + ring_dot + 1] = k
    for cname, md, bl in passes:
        kind = cmap.get(cname)
        if kind is None and cname.startswith('black'):
            kind = cmap.get('black')
        if kind is None or kind == 'existing':
            continue
        cur[0] = cname
        if cname == 'grey' and black_zone is not None:
            md = md & ~black_zone                 # tepi antialias garis hitam
        own_map, rg = (owner_dot, ring_dot) if cname == 'black_dot' else (owner, ring)
        # tepi wadah sewarna: hapus hanya ruas PANJANG searah tepi (garis tepi),
        # ruas pendek = kabel sewarna yang menyeberang → dipertahankan
        for oc, a0, a1, b0, b1, hz in bands:
            if oc != cname and not (oc == 'black' and cname == 'black_dash'):
                continue
            sub = md[a0:a1, b0:b1] if hz else md[a0:a1, b0:b1].T
            keep = np.zeros_like(sub)
            for r in range(sub.shape[0]):
                idx = np.flatnonzero(sub[r])
                if not len(idx):
                    continue
                br = np.flatnonzero(np.diff(idx) > 1)
                for st, en in zip(np.r_[idx[0], idx[br + 1]], np.r_[idx[br], idx[-1]]):
                    if en - st + 1 <= 4:
                        keep[r, st:en + 1] = True
            if hz:
                md[a0:a1, b0:b1] = keep
            else:
                md[a0:a1, b0:b1] = keep.T
        if not md.any():
            continue
        # tutup celah kecil (panah, titik sambung, antialias)
        dil = md.copy()
        dil[1:] |= md[:-1]; dil[:-1] |= md[1:]; dil[:, 1:] |= md[:, :-1]; dil[:, :-1] |= md[:, 1:]
        # garis putus-putus / titik-garis → utuh. Hitam selalu; warna lain hanya
        # bila kelas itu memang tergambar putus-putus (banyak potongan pendek yang
        # menyatu setelah celah ditutup) agar garis utuh tak tersambung keliru
        gap_c = int(max(3, min(14, round(0.11 * med / ds))))
        if cname == 'black_dot':
            # titik di sudut belokan sering hilang → lebarkan 1 sel lagi dulu
            d2 = dil.copy()
            d2[1:] |= dil[:-1]; d2[:-1] |= dil[1:]; d2[:, 1:] |= dil[:, :-1]; d2[:, :-1] |= dil[:, 1:]
            narrow = _close_dashes(dil, max(int(round(8 * zf)), gap_c)) & ~bl
            dil = _close_dashes(d2, max(int(round(8 * zf)), gap_c))
        elif cname == 'black_dash':
            dil = _close_dashes(dil, max(int(round(7 * zf)), gap_c))
        else:
            n0 = len(_components(dil))
            if n0 >= 3:
                cl_ = _close_dashes(dil, gap_c, aligned=True)
                if len(_components(cl_)) < 0.6 * n0:
                    dil = cl_
        if cname != 'black_dot':
            narrow = None
        dil &= ~bl
        for cells in _components(dil):
            if narrow is not None:
                # kontak dihitung pada mask SEMPIT (sebelum pelebaran tambahan)
                cells = [c_ for c_ in cells if narrow[c_[0], c_[1]]]
                if not cells:
                    continue
            # (kabel pendek antar kartu berdekatan ≈ 35 sel; teks tak menyentuh 2 kotak)
            if len(cells) < {'grey': 20, 'black_dash': 20, 'black_dot': 12}.get(cname, 10) * zf:
                continue
            arr = np.asarray(cells)
            ow = own_map[arr[:, 0], arr[:, 1]]
            own = []
            cts = {}                                # kotak → titik kontak (koord. kerja)
            for k in set(np.unique(ow).tolist()) - {-1}:
                # garis BERAKHIR di kotak (masuk tegak lurus), bukan lewat di sisinya
                sub = arr[ow == k]
                # satu kotak (mis. rel lebar) bisa disentuh di BEBERAPA titik oleh
                # komponen yang sama → uji tiap gugus kontak terpisah
                y0_, x0_ = sub[:, 0].min(), sub[:, 1].min()
                loc = np.zeros((np.ptp(sub[:, 0]) + 1, np.ptp(sub[:, 1]) + 1), bool)
                loc[sub[:, 0] - y0_, sub[:, 1] - x0_] = True
                clusters = [np.asarray(c_) + (y0_, x0_) for c_ in _components(loc)] \
                    if loc.size <= 40000 else [sub]
                bx0, by0, bx1, by1 = (v / ds for v in boxes[k])
                for cl in clusters:
                    my, mx = cl[:, 0].mean(), cl[:, 1].mean()
                    if max(np.ptp(cl[:, 0]), np.ptp(cl[:, 1])) > rg + 8 * zf:
                        # beberapa garis sejajar masuk ke SATU sisi (mis. LOAD + GRID,
                        # terhubung lewat teks/panah): tipis tegak lurus sisi & tak
                        # sepanjang sisi → tetap kontak
                        if my < by0 or my > by1:
                            perp, along, side_len = np.ptp(cl[:, 0]), np.ptp(cl[:, 1]), bx1 - bx0
                        elif mx < bx0 or mx > bx1:
                            perp, along, side_len = np.ptp(cl[:, 1]), np.ptp(cl[:, 0]), by1 - by0
                        else:
                            continue
                        if perp > rg + 2 or along > 0.5 * side_len:
                            continue
                    # titik masuk harus berhadapan dengan sisi kotak (bukan garis yang
                    # lewat di dekat sudut/sisi luar kotak)
                    if (bx0 + 1 <= mx <= bx1 - 1) or (by0 + 1 <= my <= by1 - 1):
                        if k not in own:
                            own.append(k)
                        cts.setdefault(k, []).append(((mx + 0.5) * ds, (my + 0.5) * ds))
            if len(own) < 2:
                continue
            own = sorted(own)
            if cname == 'grey':
                # garis abu-abu: kabel kendali (legenda) ATAU jalur daya fasilitas
                # rencana (masa depan) yang digambar abu-abu → pilih per pasangan
                fut = any(nodes[k]['status'] == 'future' for k in own)
                bus = [k for k in own if nodes[k]['type'] in ('ac_bus', 'dc_bus')]
                if fut and len(bus) == 1:
                    # jalur daya rencana ke satu rel → bintang dari rel
                    for k in own:
                        if k != bus[0]:
                            dk = default_edge_kind(nodes[bus[0]]['type'], nodes[k]['type'])
                            add(bus[0], k, dk if dk in ('ac', 'dc') else kind)
                    continue
                for a, b in _mst(own, pos):
                    ta, tb = nodes[a]['type'], nodes[b]['type']
                    dk = default_edge_kind(ta, tb)
                    add(a, b, dk if fut and dk in ('ac', 'dc') else kind)
                continue
            if kind in ('ac', 'dc'):
                bus = [k for k in own if nodes[k]['type'] in ('ac_bus', 'dc_bus')]
                if len(bus) == 1:
                    for k in own:
                        add(bus[0], k, kind)
                else:
                    for a, b in _mst(own, pos):
                        add(a, b, kind)
            else:
                hubs = sorted((k for k in own if nodes[k]['type'] in comm_rank),
                              key=lambda k: comm_rank[nodes[k]['type']])
                if hubs and len(own) > 2 and kind in ('tcpip', 'fo', 'wireless'):
                    for k in own:
                        add(hubs[0], k, kind)
                else:
                    for a, b in _mst(own, pos):
                        add(a, b, kind)
    # --- kembali ke koordinat jendela utama pada resolusi img ---
    inv = 1.0 / s
    out_nodes = []
    for n in nodes + groups:
        b = tuple(v * inv for v in n['box'])
        n2 = dict(n, box=b, cx=(b[0] + b[2]) / 2, cy=(b[1] + b[3]) / 2)
        if n2['type'] in ('ac_bus', 'dc_bus'):
            n2['line'] = (b[2] - b[0]) > 2.2 * (b[3] - b[1])
        out_nodes.append(n2)
    rep['nodes'] = len(nodes)
    rep['groups'] = len(groups)
    rep['edges'] = rep['confirmed'] = len(edges)
    rep['suggested'] = 0
    rep['existing'] = sum(1 for n in nodes if n.get('status') == 'existing')
    rep['future'] = sum(1 for n in nodes if n.get('status') == 'future')
    rep['legend'] = legend is not None
    cw = max(1000.0, min(4000.0, (Wc) * 130.0 / max(40.0, med * inv)))
    lg = None
    if legend is not None:
        lg = tuple(int(round(v * inv)) for v in legend)
    colours = [(c, used[c]) for c in _COLOUR_ORDER if c in used]
    if any(n.get('status') == 'existing' for n in nodes):
        colours.append(('blue_dash', 'existing'))
    return dict(nodes=out_nodes, edges=edges, report=rep, size=(Wc, Hc),
                frame=(cx0, cy0, cx1, cy1), canvas_w=round(cw, 0), cmap=cmap,
                legend_box=lg, colours=colours)


COMM_TYPES_FOR_LABEL = {'ems', 'server', 'eth_hub', 'sensor', 'load'}
_COLOUR_ORDER = ('red', 'blue', 'olive', 'magenta', 'green', 'cyan', 'orange', 'grey',
                 'black', 'black_dash', 'black_dot')
# warna contoh untuk legenda laporan (setara warna garis pada gambar)
COLOUR_HEX = {'red': '#E00000', 'blue': '#0000E0', 'olive': '#A3A300',
              'magenta': '#E000E0', 'green': '#008A00', 'cyan': '#00B8C8',
              'orange': '#F07800', 'grey': '#8C8C8C', 'blue_dash': '#0000E0',
              'black': '#111111', 'black_dash': '#111111', 'black_dot': '#111111'}


def make_original(img, name='', frame=None, legend_box=None, colours=None,
                  max_px=2600):
    """Simpan GAMBAR ASLI (jendela utama bila lembar CAD) untuk laporan.

    img: ndarray RGB/abu gambar penuh; frame: potongan jendela utama (piksel);
    legend_box: kotak legenda relatif potongan → diputihkan (legenda diganti
    legenda laporan yang rapi). Kembalikan dict {fmt, b64, w, h, name, ...}."""
    from PIL import Image
    a = np.asarray(img)
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, axis=2)
    a = a[..., :3].astype(np.uint8)
    if frame:
        x0, y0, x1, y1 = (int(v) for v in frame)
        a = a[y0:y1, x0:x1]
    a = a.copy()
    if legend_box:
        x0, y0, x1, y1 = (int(v) for v in legend_box)
        m = max(6, int(0.004 * max(a.shape[:2])))
        a[max(0, y0 - m):y1 + m, max(0, x0 - m):x1 + m] = 255
    im = Image.fromarray(a)
    w, h = im.size
    f = min(1.0, max_px / float(max(w, h)))
    if f < 1.0:
        im = im.resize((int(w * f), int(h * f)), Image.LANCZOS)
    best = None
    for fmt, kw in (('PNG', dict(optimize=True)), ('JPEG', dict(quality=90))):
        buf = io.BytesIO()
        try:
            # PNG berpalet (octree 256) mempertahankan warna garis murni CAD
            (im.quantize(256, method=Image.FASTOCTREE) if fmt == 'PNG' else im) \
                .save(buf, format=fmt, **kw)
        except Exception:                      # mis. Pillow tanpa JPEG
            continue
        if best is None or len(buf.getvalue()) < len(best[1]):
            best = (fmt, buf.getvalue())
    return dict(fmt=best[0].lower(), b64=base64.b64encode(best[1]).decode('ascii'),
                w=im.size[0], h=im.size[1], name=name, sheet=bool(frame),
                legend_removed=bool(legend_box),
                colours=[list(c) for c in (colours or [])])


def to_gray(img):
    a = np.asarray(img)
    if a.ndim == 3:
        a = (a[..., :3] @ np.array([0.299, 0.587, 0.114])).astype(np.uint8)
    return a


def load_image_rgb(path):
    from PIL import Image
    img = Image.open(path)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return np.asarray(img.convert('RGB'))


def recognize_any(img, words=None, max_plain=2600):
    """Lembar CAD (berbingkai) → recognize_sheet; selain itu recognize() biasa
    pada gambar abu-abu ≤ max_plain px (teks PDF diskalakan)."""
    rec = None
    try:
        rec = recognize_sheet(img, words)
    except Exception:
        rec = None
    if rec is not None:
        return rec
    gray = to_gray(img)
    H, W = gray.shape
    f = min(1.0, max_plain / float(max(H, W)))
    if f < 1.0:
        from PIL import Image
        gray = np.asarray(Image.fromarray(gray).resize((int(W * f), int(H * f)),
                                                       Image.LANCZOS))
        if words:
            words = [(t, a * f, b * f, c * f, d * f) for t, a, b, c, d in words]
    rec = recognize(gray, words or None)
    rec['scale'] = f
    return rec
