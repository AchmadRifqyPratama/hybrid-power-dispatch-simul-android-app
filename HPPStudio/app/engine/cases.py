"""Mode Case Analysis — klasifikasi 32 kasus operasi per jam.

Empat dimensi: Grid status (1/0) × PV (tersedia/tidak) × BESS (charge / can not
charge / discharge / can not discharge) × DEG (ON/OFF).
  Nomor case = (DEG OFF ? 16 : 0) + (Grid 0 ? 8 : 0) + (PV n/a ? 4 : 0) + idx
  idx BESS: 1 charge, 2 can not charge, 3 discharge, 4 can not discharge
  → case 1..16 = DEG ON ; case 17..32 = DEG OFF.

Modul MURNI (tanpa GUI): hanya MEMBACA deret hasil simulasi + parameter sistem;
tidak mengubah logika dispatch. Dipakai bersama halaman Dashboard dan laporan
Studi Kelayakan agar klasifikasi identik.
"""
from __future__ import annotations
import colorsys

import numpy as np

_BESS_STATES = ['charge', 'can not charge', 'discharge', 'can not discharge']
_BESS_SHORT = ['charge', 'no charge', 'dischg', 'no dischg']


def _make_case_colors():
    """32 warna berbeda (hue golden-angle); kelompok DEG OFF lebih redup."""
    cols = {}
    for c in range(1, 33):
        h = ((c - 1) * 0.6180339887) % 1.0
        deg_on = c <= 16
        s = 0.72 if deg_on else 0.50
        val = 0.96 if deg_on else 0.78
        r, g, b = colorsys.hsv_to_rgb(h, s, val)
        cols[c] = (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))
    return cols


CASE_COLORS = _make_case_colors()


def case_hex(c: int) -> str:
    r, g, b = CASE_COLORS[c]
    return f'#{r:02X}{g:02X}{b:02X}'


def case_components(c: int):
    """(grid_status:int, pv_avail:bool, bess_state_index:int 0..3, deg_on:bool)."""
    deg_on = c <= 16
    cc = c if deg_on else c - 16
    grid = 1 if cc <= 8 else 0
    pv_avail = ((cc - 1) % 8) < 4
    bess_idx = (cc - 1) % 4
    return grid, pv_avail, bess_idx, deg_on


def case_text(c: int) -> str:
    """Deskripsi lengkap (Inggris) untuk nomor case 1..32."""
    grid, pv_avail, bess_idx, deg_on = case_components(c)
    grid_s = f'Grid status {grid}'
    pv = 'PV available' if pv_avail else 'PV not available'
    bess = _BESS_STATES[bess_idx]
    deg = 'DEG ON' if deg_on else 'DEG OFF'
    return f'Case {c}:  {grid_s}  ·  {pv}  ·  BESS {bess}  ·  {deg}'


def case_short(c: int) -> str:
    """Label ringkas untuk daftar filter (DEG jadi judul kolom)."""
    grid, pv_avail, bess_idx, _deg = case_components(c)
    pv = 'PV✓' if pv_avail else 'PV✗'
    return f'C{c}  ·  G{grid} {pv} · {_BESS_SHORT[bess_idx]}'


def classify_cases(series: dict, soc_min: float, soc_max: float,
                   bess_kwh: float = 0.0, dt: float = 1.0,
                   rte: float = 1.0) -> np.ndarray:
    """Nomor case 1..32 tiap jam (0 = tanpa case). Murni dari deret terekam:
    grid_status, pv (EArray), chg, dhg, soc, deg, load. Tidak menyentuh logika
    simulasi. `bess_kwh`, `dt`, `rte` dipakai untuk uji 'can not discharge'
    memakai potensi discharge yang SAMA dengan engine
    (d_pot = (Z - SOC_min·E)/dt · √η_RT)."""
    n = int(np.asarray(series['load']).reshape(-1).shape[0])

    def col(k):
        return np.asarray(series.get(k, np.zeros(n)), float).reshape(n, -1)[:, 0]

    grid_on = col('grid_status') > 0.5
    pv_avail = col('pv') > 1e-6
    deg_on = col('deg') > 1e-6
    chg, dhg, soc, load = col('chg'), col('dhg'), col('soc'), col('load')
    tol, eps = 1e-6, 1e-4
    srte = float(np.sqrt(max(float(rte), 0.0)))
    avail = (soc - soc_min) * float(bess_kwh) * srte
    need = load * float(dt)
    b = np.zeros(n, dtype=int)
    b[soc >= soc_max - eps] = 2           # penuh -> can not charge
    if float(bess_kwh) > tol:
        b[avail < need - 1e-9] = 4        # can not discharge
    b[dhg > tol] = 3                      # discharge
    b[chg > tol] = 1                      # charge
    base = (np.where(deg_on, 0, 16) + np.where(grid_on, 0, 8)
            + np.where(pv_avail, 0, 4))
    return np.where(b > 0, base + b, 0).astype(int)


def case_summary(series, soc_min, soc_max, bess_kwh=0.0, dt=1.0, rte=1.0):
    """Ringkasan durasi tiap case.

    Kembalikan (rows, marked_h, total_h):
      rows      : [(case_num, hours), ...] untuk case yang muncul (jam>0),
                  terurut jam menurun;
      marked_h  : total jam yang tergolong salah satu case;
      total_h   : total jam simulasi.
    """
    cases = classify_cases(series, soc_min, soc_max, bess_kwh, dt, rte)
    total_h = float(len(cases) * float(dt))
    rows = []
    for c in range(1, 33):
        cnt = int(np.count_nonzero(cases == c))
        if cnt:
            rows.append((c, cnt * float(dt)))
    rows.sort(key=lambda t: t[1], reverse=True)
    marked_h = float(sum(h for _c, h in rows))
    return rows, marked_h, total_h
