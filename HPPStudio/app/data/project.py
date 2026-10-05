"""Berkas proyek HPP Studio (ekstensi ``.hpps``).

Satu berkas memuat seluruh pekerjaan: identitas proyek, seluruh parameter,
profil data 8760 jam, DAN hasil yang sudah dihitung — simulasi (Dashboard &
Results), hasil optimasi, serta simulasi multi-year — sehingga membuka
kembali berkas langsung menampilkan semuanya tanpa menghitung ulang.

Format: JSON UTF-8 yang dipadatkan gzip — ringkas (±150 KB untuk setahun
penuh), mudah diperiksa, dan tidak menambah dependensi apa pun.

    {
      "app": "HPP Studio", "format": 1, "saved_at": "...",
      "config": { ... seluruh parameter ... },
      "profiles": {"n": 8760, "start": "2025-01-01T00:00:00",
                   "load": [...], "pv": [...], "grid": [...]}
    }
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime

from ..config.i18n import tr

import numpy as np

EXT = '.hpps'
APP_TAG = 'HPP Studio'
FORMAT_VERSION = 1
FILE_FILTER = 'HPP Studio Project (*.hpps)'


class ProjectError(Exception):
    pass


def _round(arr, dec=6):
    return [float(x) for x in np.round(np.asarray(arr, float), dec)]


def _encode(obj, dec: int = 6):
    """Ubah struktur hasil (dict/ndarray) menjadi JSON-friendly."""
    if isinstance(obj, np.ndarray):
        if obj.dtype.kind == 'f':
            return {'__nd__': np.round(obj, dec).tolist(), 'k': 'f'}
        if obj.dtype.kind == 'b':
            return {'__nd__': obj.tolist(), 'k': 'b'}
        if obj.dtype.kind in 'iu':
            return {'__nd__': obj.tolist(), 'k': 'i'}
        return {'__nd__': [str(x) for x in obj.tolist()], 'k': 's'}
    if isinstance(obj, (np.floating, np.integer, np.bool_)):
        return obj.item()
    if isinstance(obj, dict):
        return {str(k): _encode(v, dec) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_encode(v, dec) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return None            # tipe lain (mis. dataclass) tidak disimpan


def _decode(obj):
    if isinstance(obj, dict):
        if '__nd__' in obj:
            kind = obj.get('k', 'f')
            dt = {'f': float, 'b': bool, 'i': np.int64, 's': object}[kind]
            return np.asarray(obj['__nd__'], dtype=dt)
        return {k: _decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    return obj


def save_project(path: str, cfg: dict, load=None, pv=None, grid=None,
                 datetimes=None, results=None,
                 pv_excel=None, pv_pvgis=None) -> str:
    """Tulis berkas proyek. Kembalikan path akhir (ekstensi dilengkapi)."""
    if not path.lower().endswith(EXT):
        path += EXT
    doc = {
        'app': APP_TAG,
        'format': FORMAT_VERSION,
        'saved_at': datetime.now().isoformat(timespec='seconds'),
        'config': {k: (v.item() if isinstance(v, np.generic) else v)
                   for k, v in dict(cfg).items()},
    }
    if load is not None and pv is not None:
        n = int(len(np.asarray(load).reshape(-1)))
        start = None
        freq_s = 3600                      # detik per langkah (default per jam)
        if datetimes is not None and len(datetimes):
            try:
                start = str(np.asarray(datetimes).reshape(-1)[0])
            except Exception:
                start = None
            try:                            # pertahankan resolusi sub-jam
                d = np.asarray(datetimes)
                if d.size >= 2:
                    freq_s = int(round(float(
                        (np.datetime64(d[1]) - np.datetime64(d[0]))
                        / np.timedelta64(1, 's'))) or 3600)
            except Exception:
                freq_s = 3600
        doc['profiles'] = {
            'n': n, 'start': start, 'freq_s': freq_s,
            'load': _round(load),
            'pv': _round(pv),
            'grid': _round(grid if grid is not None else np.ones(n), 0),
        }
        # Dua sumber PV opsional (Excel / PVGIS) agar pilihan tetap ada
        # setelah proyek dibuka kembali.
        for _k, _v in (('pv_excel', pv_excel), ('pv_pvgis', pv_pvgis)):
            if _v is not None and len(np.asarray(_v).reshape(-1)) == n:
                doc['profiles'][_k] = _round(_v)
    if results:
        doc['results'] = {k: _encode(v) for k, v in results.items()
                          if v is not None}
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.',
                exist_ok=True)
    raw = json.dumps(doc, ensure_ascii=False).encode('utf-8')
    with gzip.open(path, 'wb', compresslevel=6) as f:
        f.write(raw)
    return path


def load_project(path: str) -> dict:
    """Baca berkas proyek → {config, profiles|None, saved_at}."""
    if not os.path.exists(path):
        raise ProjectError(tr('Berkas tidak ditemukan:') + f' {path}')
    try:
        with gzip.open(path, 'rb') as f:
            doc = json.loads(f.read().decode('utf-8'))
    except (OSError, ValueError):
        # jaga-jaga bila tersimpan tanpa kompresi
        try:
            with open(path, 'r', encoding='utf-8') as f:
                doc = json.load(f)
        except Exception as e:
            raise ProjectError(tr('Berkas rusak atau bukan proyek HPP Studio')
                               + f' ({e}).')
    if doc.get('app') != APP_TAG:
        raise ProjectError(tr('Berkas ini bukan proyek HPP Studio.'))
    if int(doc.get('format', 0)) > FORMAT_VERSION:
        raise ProjectError(tr('Berkas dibuat oleh versi HPP Studio yang lebih '
                              'baru. Perbarui aplikasi terlebih dahulu.'))

    prof = doc.get('profiles')
    profiles = None
    if prof:
        n = int(prof.get('n') or len(prof.get('load', [])))
        load = np.asarray(prof.get('load', []), float)
        pv = np.asarray(prof.get('pv', []), float)
        grid = np.asarray(prof.get('grid', np.ones(n)), float)
        if len(load) != n or len(pv) != n:
            raise ProjectError(tr('Data profil dalam berkas tidak konsisten.'))
        dts = None
        if prof.get('start'):
            try:
                import pandas as pd
                from ..config.intervals import (detect_interval_label,
                                                 interval_seconds)
                # Interval DIDETEKSI dari jumlah baris (tepercaya walau freq_s
                # lama salah, mis. .hpps yg disimpan saat datetimes keliru per
                # jam); fallback ke freq_s tersimpan.
                lab = detect_interval_label(n, None)
                fs = (interval_seconds(lab) if lab
                      else int(prof.get('freq_s', 3600) or 3600))
                dts = pd.date_range(prof['start'], periods=n, freq=f'{fs}s')
            except Exception:
                dts = None
        profiles = dict(load=load, pv=pv, grid=grid, datetimes=dts)
        for _k in ('pv_excel', 'pv_pvgis'):
            if prof.get(_k) is not None:
                _a = np.asarray(prof[_k], float)
                if len(_a) == n:
                    profiles[_k] = _a
    results = {k: _decode(v)
               for k, v in (doc.get('results') or {}).items()}
    return dict(config=dict(doc.get('config') or {}),
                profiles=profiles, results=results,
                saved_at=doc.get('saved_at', ''))


def default_name(cfg: dict) -> str:
    """Nama berkas usulan berdasarkan identitas proyek."""
    from .exporter import _slug
    parts = [_slug(cfg.get('project_name', 'Project')),
             _slug(cfg.get('site_name') or cfg.get('location') or '')]
    return '_'.join(p for p in parts if p and p != 'NA') + EXT
