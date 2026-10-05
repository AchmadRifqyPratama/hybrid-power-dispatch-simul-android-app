"""OCR ringan TERBAWA di HPP Studio (tanpa aplikasi/paket OCR terpisah).

Model PP-OCRv4 (deteksi + pengenalan teks, format ONNX) disertakan di
``app/ocr/models``; inferensi memakai ``onnxruntime`` saja (+ numpy, Pillow).
Pra/pascaproses (DB text detection + CTC decoding) ditulis ulang di sini tanpa
OpenCV/pyclipper/shapely, dioptimalkan untuk teks HORIZONTAL gambar teknik.

Antarmuka meniru RapidOCR:  ``eng(img, use_cls=False) -> ([box4, teks, skor], t)``.

Lisensi model: Apache-2.0 (PaddleOCR / RapidOCR) — lihat models/NOTICE.txt.
"""
from __future__ import annotations

import math
import os
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(_HERE, 'models')
DET_MODEL = os.path.join(MODEL_DIR, 'ch_PP-OCRv4_det_infer.onnx')
REC_MODEL = os.path.join(MODEL_DIR, 'ch_PP-OCRv4_rec_infer.onnx')

_LAST_ERROR = ''


def last_error():
    """Pesan kegagalan terakhir saat memuat mesin OCR ('' bila tak ada)."""
    return _LAST_ERROR


def available():
    return load() is not None


_ENGINE = None


def load():
    """MiniOCR siap pakai, atau None (onnxruntime tak terpasang / model hilang)."""
    global _ENGINE, _LAST_ERROR
    if _ENGINE is None:
        try:
            _ENGINE = MiniOCR()
            _LAST_ERROR = ''
        except Exception as e:                      # pragma: no cover
            _ENGINE = False
            _LAST_ERROR = f'{type(e).__name__}: {e}'
    return _ENGINE or None


def _resize(a, w, h):
    from PIL import Image
    return np.asarray(Image.fromarray(a).resize((int(w), int(h)), Image.BILINEAR))


def _label_runs(mask):
    """Komponen terhubung (8-arah) berbasis run per baris + union-find.

    Kembalikan list bbox (x0, y0, x1, y1) + indeks run → dipakai utk skor."""
    H, W = mask.shape
    runs = []                                        # (y, x0, x1)
    row_idx = []
    m8 = mask.astype(np.int8)
    for y in range(H):
        r = m8[y]
        if not r.any():
            row_idx.append((len(runs), len(runs)))
            continue
        d = np.diff(np.concatenate(([0], r, [0])))
        st = np.flatnonzero(d == 1); en = np.flatnonzero(d == -1) - 1
        a = len(runs)
        runs.extend(zip([y] * len(st), st.tolist(), en.tolist()))
        row_idx.append((a, len(runs)))
    n = len(runs)
    par = list(range(n))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i
    for y in range(1, H):
        a0, a1 = row_idx[y - 1]
        b0, b1 = row_idx[y]
        i, j = a0, b0
        while i < a1 and j < b1:
            _, pa, pb = runs[i]
            _, qa, qb = runs[j]
            if pa <= qb + 1 and qa <= pb + 1:        # bersinggungan (8-arah)
                ri, rj = find(i), find(j)
                if ri != rj:
                    par[ri] = rj
            if pb < qb:
                i += 1
            else:
                j += 1
    comps = {}
    for k, (y, a, b) in enumerate(runs):
        r = find(k)
        c = comps.get(r)
        if c is None:
            comps[r] = [a, y, b, y, b - a + 1]
        else:
            c[0] = min(c[0], a); c[1] = min(c[1], y)
            c[2] = max(c[2], b); c[3] = max(c[3], y); c[4] += b - a + 1
    return list(comps.values())


class MiniOCR:
    def __init__(self, threads=0):
        import onnxruntime as ort
        for p in (DET_MODEL, REC_MODEL):
            if not os.path.exists(p):
                raise FileNotFoundError(p)
        so = ort.SessionOptions()
        so.log_severity_level = 3
        if threads:
            so.intra_op_num_threads = threads
        prov = ['CPUExecutionProvider']
        self.det = ort.InferenceSession(DET_MODEL, sess_options=so, providers=prov)
        self.rec = ort.InferenceSession(REC_MODEL, sess_options=so, providers=prov)
        meta = self.rec.get_modelmeta().custom_metadata_map
        chars = meta.get('character', '').splitlines()
        if not chars:
            raise RuntimeError('rec model has no character list')
        self.chars = ['blank'] + chars + [' ']
        self.det_in = self.det.get_inputs()[0].name
        self.rec_in = self.rec.get_inputs()[0].name

    # ------------------------------------------------------------ deteksi --
    def detect(self, img, limit=736, max_side=2000, thresh=0.3, box_thresh=0.5,
               unclip=1.6):
        h, w = img.shape[:2]
        ratio = 1.0
        if min(h, w) < limit:
            ratio = limit / float(min(h, w))
        if max(h, w) * ratio > max_side:
            ratio = max_side / float(max(h, w))
        rh = max(32, int(round(h * ratio / 32) * 32))
        rw = max(32, int(round(w * ratio / 32) * 32))
        x = _resize(img, rw, rh).astype(np.float32)[..., ::-1]      # BGR
        x = (x / 255.0 - 0.5) / 0.5
        x = x.transpose(2, 0, 1)[None].astype(np.float32)
        pred = self.det.run(None, {self.det_in: x})[0][0, 0]
        bm = pred > thresh
        bm = bm | np.pad(bm, ((1, 0), (0, 0)))[:-1] | np.pad(bm, ((0, 0), (1, 0)))[:, :-1] \
            | np.pad(bm, ((1, 0), (1, 0)))[:-1, :-1]                 # dilasi 2×2
        sx, sy = w / float(rw), h / float(rh)
        boxes = []
        for x0, y0, x1, y1, _area in _label_runs(bm):
            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            if min(bw, bh) < 3:
                continue
            score = float(pred[y0:y1 + 1, x0:x1 + 1].mean())
            if score < box_thresh:
                continue
            dist = bw * bh * unclip / (2.0 * (bw + bh))
            X0, Y0 = x0 - dist, y0 - dist
            X1, Y1 = x1 + 1 + dist, y1 + 1 + dist
            if min(X1 - X0, Y1 - Y0) < 5:
                continue
            X0 = min(max(X0 * sx, 0), w - 1); X1 = min(max(X1 * sx, 0), w - 1)
            Y0 = min(max(Y0 * sy, 0), h - 1); Y1 = min(max(Y1 * sy, 0), h - 1)
            if X1 - X0 <= 3 or Y1 - Y0 <= 3:
                continue
            boxes.append((X0, Y0, X1, Y1))
        boxes.sort(key=lambda b: (round(b[1] / 10), b[0]))
        return boxes

    # --------------------------------------------------------- pengenalan --
    def recognize(self, crops, batch=6, H=48, W=320):
        out = [('', 0.0)] * len(crops)
        order = np.argsort([c.shape[1] / float(c.shape[0]) for c in crops])
        for b0 in range(0, len(crops), batch):
            idx = order[b0:b0 + batch]
            mr = max([W / float(H)] + [crops[i].shape[1] / float(crops[i].shape[0])
                                       for i in idx])
            iw = int(H * mr)
            arr = np.zeros((len(idx), 3, H, iw), np.float32)
            for k, i in enumerate(idx):
                c = crops[i]
                rw = min(iw, int(math.ceil(H * c.shape[1] / float(c.shape[0]))))
                r = _resize(c, max(1, rw), H).astype(np.float32)[..., ::-1]
                arr[k, :, :, :rw] = ((r / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)
            preds = self.rec.run(None, {self.rec_in: arr})[0]
            ids = preds.argmax(2); prob = preds.max(2)
            for k, i in enumerate(idx):
                seq, ps, last = [], [], -1
                for t, c in enumerate(ids[k]):
                    if c != last and c != 0:
                        seq.append(self.chars[c] if c < len(self.chars) else '')
                        ps.append(prob[k, t])
                    last = c
                out[i] = (''.join(seq), float(np.mean(ps)) if ps else 0.0)
        return out

    def __call__(self, img, use_cls=False, **_kw):
        t0 = time.perf_counter()
        a = np.asarray(img)
        if a.ndim == 2:
            a = np.repeat(a[..., None], 3, axis=2)
        a = np.ascontiguousarray(a[..., :3].astype(np.uint8))
        if min(a.shape[:2]) < 8:
            return None, 0.0
        boxes = self.detect(a)
        crops, keep = [], []
        for (x0, y0, x1, y1) in boxes:
            c = a[int(y0):int(math.ceil(y1)) + 1, int(x0):int(math.ceil(x1)) + 1]
            if c.shape[0] < 4 or c.shape[1] < 4:
                continue
            if c.shape[0] >= c.shape[1] * 1.5:               # teks vertikal → putar
                c = np.ascontiguousarray(np.rot90(c))
            crops.append(c); keep.append((x0, y0, x1, y1))
        res = self.recognize(crops) if crops else []
        out = []
        for (x0, y0, x1, y1), (txt, sc) in zip(keep, res):
            if not txt.strip():
                continue
            out.append([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], txt, sc])
        return (out or None), time.perf_counter() - t0
