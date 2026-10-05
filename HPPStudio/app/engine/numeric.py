"""Utilitas numerik bersama.

Perhitungan berantai 8760 jam meninggalkan sisa pembulatan floating-point
(mis. 3.33e-07 kWh) yang secara fisik berarti nol. Modul ini menyediakan
pembersihan nilai tersebut agar hasil di GUI, laporan, dan file ekspor
tampil bersih.
"""
from __future__ import annotations
import numpy as np

ZERO_TOL = 1e-6      # di bawah ini dianggap nol


def snap_zero(x, tol: float = ZERO_TOL):
    """Kembalikan x dengan |x| < tol dijadikan 0 (skalar maupun array)."""
    if x is None:
        return x
    if isinstance(x, (bool, np.bool_)):
        return x
    arr = np.asarray(x)
    if arr.dtype.kind not in 'fc':          # non-numerik / integer: biarkan
        return x
    out = np.where(np.abs(arr) < tol, 0.0, arr)
    if np.isscalar(x) or arr.ndim == 0:
        return float(out)
    return out


def snap_dict(d: dict, tol: float = ZERO_TOL, skip: set | None = None) -> dict:
    """snap_zero untuk setiap nilai numerik dalam dict."""
    skip = skip or set()
    return {k: (v if k in skip else snap_zero(v, tol)) for k, v in d.items()}
