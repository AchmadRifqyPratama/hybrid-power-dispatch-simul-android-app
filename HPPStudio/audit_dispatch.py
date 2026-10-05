"""Audit ekshaustif strategi dispatch — menguji SEMUA kombinasi skenario.

Kombinasi yang diuji (perkalian penuh) — empat kelompok:
  A. Mode tunggal (13.824):
     Load Supply Priority (3) x BESS Charging Priority (2) x Strict (2)
     x Allow Grid Charging (2) x Allow DEG Charging (2)
     x DEG Interlock with Grid (2) x DEG Interlock with PV-BESS (2)
     x Grid Interlock with PV-BESS (2) x Any grid connection (2) x export (2)
     x 9 varian sistem
  B. Mode komposit bawaan engine (576): Auto by Grid Status &
     'Grid -> PV -> BESS -> DEG (auto-interlock)' x charging/strict/export
     x 9 varian sistem  (DEG boleh paralel grid).
  C. Mode split — Load Priority Follows Grid Status (5.184): skenario
     status-1 x status-0 (3x3) x charging/strict/interlock-PVBESS/export
     x 9 varian sistem.
  D. Mode DEG-split — DEG Options Follow Grid Status (1.728): DEG Interlock
     with PV-BESS & Allow DEG Charging dipilih terpisah utk grid tersedia (on)
     vs padam (off): il_on x il_off x dc_on x dc_off (2^4) x Load Priority (3)
     x charging (2) x strict (2) x 9 varian sistem. Invarian interlock &
     charging dinilai PER JAM sesuai status grid.
Total: 21.312 kombinasi.

Setiap jam pada setiap kombinasi diperiksa terhadap belasan invarian fisis
(neraca energi, batas daya, aturan interlock, batas SOC, dsb).

Jalankan:  python audit_dispatch.py            (semua: A+B+C+D)
           python audit_dispatch.py new        (hanya B+C+D — mode baru)
           python audit_dispatch.py 0 8        (bagian 1 dari 8, semua)
"""
from __future__ import annotations

import dataclasses
import itertools
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from app.config.parameters import defaults, to_system_params      # noqa: E402
from app.engine.dispatch import simulate                          # noqa: E402

TOL = 1e-6


# ----------------------------------------------------------------- profil uji
def make_profile(n_days: int = 6):
    """Profil sintetis yang sengaja memuat kasus ekstrem."""
    h = n_days * 24
    t = np.arange(h)
    hour = t % 24
    day = t // 24

    # beban: berganti-ganti rendah / sedang / sangat tinggi
    base = np.array([60, 120, 260, 90, 300, 55, 150, 220, 80, 180], float)
    load = base[day % len(base)] * (0.75 + 0.35 * (hour >= 8) * (hour <= 20))
    load[hour == 3] = 5.0            # beban sangat rendah
    peak = hour == 19
    load[peak] = base[day[peak] % len(base)] * 1.4   # puncak malam

    # PV: nol malam, tinggi siang; beberapa hari mendung
    pv = np.zeros(h)
    sun = (hour >= 6) & (hour <= 18)
    pv[sun] = np.sin((hour[sun] - 6) / 12 * np.pi) ** 1.2
    pv *= np.where((day % 4) == 3, 0.15, 1.0)        # hari mendung
    pv *= 220.0                                       # kW pada 1 kWp basis

    # status grid: beberapa blok padam, termasuk saat beban puncak
    grid = np.ones(h)
    grid[26:33] = 0.0
    grid[95:99] = 0.0
    grid[110:130] = 0.0
    grid[peak] = np.where(day[peak] % 5 == 0, 0.0, 1.0)
    return load, pv, grid


# ----------------------------------------------------------------- varian
SYSTEMS = {
    'lengkap': dict(pv_kwp=1.0, pv_inv_kw=200.0, bess_kwh=600.0, grid_kw=150.0,
                    max_charge_kw=300.0, max_discharge_kw=300.0,
                    deg_count='2', deg1_kw=200.0, deg2_kw=200.0),
    'grid-kecil': dict(pv_kwp=1.0, pv_inv_kw=200.0, bess_kwh=600.0,
                       grid_kw=60.0, max_charge_kw=300.0,
                       max_discharge_kw=300.0,
                       deg_count='1', deg1_kw=400.0),
    'tanpa-PV': dict(pv_kwp=0.0, pv_inv_kw=0.0, bess_kwh=600.0, grid_kw=150.0,
                     max_charge_kw=300.0, max_discharge_kw=300.0,
                     deg_count='1', deg1_kw=400.0),
    'tanpa-BESS': dict(pv_kwp=1.0, pv_inv_kw=200.0, bess_kwh=0.0,
                       grid_kw=150.0, max_charge_kw=0.0, max_discharge_kw=0.0,
                       deg_count='1', deg1_kw=400.0),
    'tanpa-DEG': dict(pv_kwp=1.0, pv_inv_kw=200.0, bess_kwh=600.0,
                      grid_kw=150.0, max_charge_kw=300.0,
                      max_discharge_kw=300.0, deg_count='0'),
    'PCS-kecil': dict(pv_kwp=1.0, pv_inv_kw=200.0, bess_kwh=600.0,
                      grid_kw=150.0, max_charge_kw=40.0,
                      max_discharge_kw=40.0,
                      deg_count='1', deg1_kw=400.0),
    'INV-kecil': dict(pv_kwp=1.0, pv_inv_kw=45.0, bess_kwh=600.0,
                      grid_kw=150.0, max_charge_kw=300.0,
                      max_discharge_kw=300.0,
                      deg_count='3', deg1_kw=100.0, deg2_kw=150.0,
                      deg3_kw=200.0),
    'hanya-DEG': dict(pv_kwp=0.0, pv_inv_kw=0.0, bess_kwh=0.0,
                      grid_kw=0.0, max_charge_kw=0.0,
                      max_discharge_kw=0.0,
                      deg_count='2', deg1_kw=300.0, deg2_kw=300.0),
    'DEG-kecil': dict(pv_kwp=1.0, pv_inv_kw=200.0, bess_kwh=300.0,
                      grid_kw=100.0, max_charge_kw=150.0,
                      max_discharge_kw=150.0,
                      deg_count='1', deg1_kw=50.0),
}

LOAD_PRIOS = ['PV -> Grid -> BESS -> DEG', 'Grid -> PV -> BESS -> DEG',
              'PV -> BESS -> Grid -> DEG']
# Mode komposit bawaan engine (bergantung status grid; tak lagi di dropdown,
# tetap didukung engine untuk kompatibilitas berkas lama).
LOAD_PRIOS_COMPOSITE = ['Auto by Grid Status',
                        'Grid -> PV -> BESS -> DEG (auto-interlock)']
CHG_PRIOS = ['PV -> Grid', 'Grid -> PV']

# nilai tetap yang berlaku untuk semua kombinasi audit
_COMMON = dict(grid_max_loading=0.9, grid_min_loading=0.05,
               deg_min_loading=0.3, deg_max_loading=0.9,
               charge_from_grid_below_soc=0.6, soc_init=0.35,
               pv_base_annual=1.0)


def build_combos(kinds):
    """Bangun daftar (sysname, overrides, tag) untuk kelompok yang diminta."""
    F, T = False, True
    out = []
    if 'single' in kinds:
        for (lp, cp, st, gc, dc, dgi, il, gil, gon, ex, sysname) in \
                itertools.product(LOAD_PRIOS, CHG_PRIOS, [F, T], [F, T],
                                  [F, T], [F, T], [F, T], [T, F], [F, T],
                                  [F, T], SYSTEMS.keys()):
            out.append((sysname, dict(
                load_priority=lp, charge_priority=cp,
                strict_charge_priority=st, grid_charge_enabled=gc,
                deg_charge_enabled=dc, deg_grid_interlock=dgi,
                deg_interlock=il, grid_interlock=gil, grid_enabled=gon,
                allow_export=ex), f'single | {lp}'))
    if 'composite' in kinds:
        # Mode komposit mengelola interlock sendiri per status grid, jadi
        # flag interlock global dinetralkan (DEG boleh paralel grid).
        for (lp, cp, st, gc, dc, ex, sysname) in itertools.product(
                LOAD_PRIOS_COMPOSITE, CHG_PRIOS, [F, T], [F, T], [F, T],
                [F, T], SYSTEMS.keys()):
            out.append((sysname, dict(
                load_priority=lp, charge_priority=cp,
                strict_charge_priority=st, grid_charge_enabled=gc,
                deg_charge_enabled=dc, deg_grid_interlock=F,
                deg_interlock=F, grid_interlock=F, grid_enabled=T,
                allow_export=ex), f'composite | {lp}'))
    if 'split' in kinds:
        for (on_, off_, cp, st, gc, dc, il, ex, sysname) in \
                itertools.product(LOAD_PRIOS, LOAD_PRIOS, CHG_PRIOS,
                                  [F, T], [F, T], [F, T], [F, T], [F, T],
                                  SYSTEMS.keys()):
            out.append((sysname, dict(
                load_priority_split=True, load_priority_on=on_,
                load_priority_off=off_, charge_priority=cp,
                strict_charge_priority=st, grid_charge_enabled=gc,
                deg_charge_enabled=dc, deg_grid_interlock=F,
                deg_interlock=il, grid_interlock=F, grid_enabled=T,
                allow_export=ex), f'split | {on_} / {off_}'))
    if 'deg-split' in kinds:
        # Opsi DEG per status grid: interlock PV-BESS & DEG charging dipilih
        # terpisah utk grid tersedia (on) vs padam (off). Load priority tetap
        # tunggal (lp), agar isolasi pada dimensi DEG.
        for (lp, ilon, iloff, dcon, dcoff, cp, st, sysname) in \
                itertools.product(LOAD_PRIOS, [F, T], [F, T], [F, T], [F, T],
                                  CHG_PRIOS, [F, T], SYSTEMS.keys()):
            out.append((sysname, dict(
                load_priority=lp, deg_options_split=True,
                deg_interlock_on=ilon, deg_interlock_off=iloff,
                deg_charge_on=dcon, deg_charge_off=dcoff,
                charge_priority=cp, strict_charge_priority=st,
                grid_charge_enabled=T, deg_grid_interlock=F,
                grid_interlock=F, grid_enabled=T, allow_export=F),
                f'deg-split | on(il={int(ilon)},dc={int(dcon)}) '
                f'off(il={int(iloff)},dc={int(dcoff)})'))
    return out


# ----------------------------------------------------------------- invarian
def check(cfg, sp, series, load, grid_status, ilock_h=None, dchg_h=None):
    """Kembalikan daftar pelanggaran invarian (kosong = sehat).

    ilock_h / dchg_h : mask boolean per jam (T,) untuk mode DEG-split, di mana
    'DEG Interlock with PV-BESS' & 'Allow DEG Charging' berbeda menurut status
    grid. Bila None, dipakai flag skalar sp (perilaku mode non-split)."""
    bad = []
    n = len(load)

    def c(k):
        return np.asarray(series[k], float).reshape(n, -1)[:, 0]

    ld, gl, pvbs = c('load'), c('grid_load'), c('pvbs_load')
    deg, cdeg, uns = c('deg'), c('chg_deg'), c('unserved')
    chg, dhg, soc = c('chg'), c('dhg'), c('soc')
    cpv, cgr = c('chg_pv'), c('chg_grid')
    pvg, pvo, exc = c('pv'), c('pv_inv_out'), c('pv_excess')
    imp, exp_ = c('grid'), c('grid_export')
    cap0, cap1 = c('cap_start'), c('cap_end')
    deg_load = deg - cdeg
    gcap = sp.grid_kw * sp.grid_max_loading
    on = (grid_status > 0) & (sp.grid_kw > 0)

    def add(name, mask):
        if np.any(mask):
            i = int(np.argmax(mask))
            bad.append(f'{name} @jam {i}')

    # 1. neraca daya tiap jam
    add('neraca beban', np.abs(pvbs + gl + deg_load + uns - ld) > 1e-5)
    add('unserved negatif', uns < -TOL)
    add('over-serve', pvbs + gl + deg_load - ld > 1e-5)

    # 2. batas grid
    add('grid > max loading', gl - gcap > 1e-5)
    add('grid saat padam/off', (~on) & (imp > TOL))
    add('impor != beban + charge', np.abs(imp - (gl + cgr)) > 1e-5)

    # 3. batas BESS
    add('charge & discharge bersamaan', (chg > TOL) & (dhg > TOL))
    add('charge > PCS', chg - sp.max_charge_kw > 1e-5)
    add('discharge > PCS', dhg - sp.max_discharge_kw > 1e-5)
    add('rincian charge != total', np.abs(cpv + cgr + cdeg - chg) > 1e-5)
    if sp.bess_kwh > 0:
        add('SOC < minimum', soc < sp.soc_min - 1e-6)
        add('SOC > maksimum', soc > sp.soc_max + 1e-6)
        rte = np.sqrt(sp.rte)
        exp_cap = np.clip(cap0 + chg * rte - dhg / rte,
                          sp.soc_min * sp.bess_kwh, sp.soc_max * sp.bess_kwh)
        add('SOC tidak kontinu', np.abs(cap1 - exp_cap) > 1e-4)
        add('kapasitas awal != akhir sebelumnya',
            np.abs(cap0[1:] - cap1[:-1]) > 1e-4)
    else:
        add('BESS aktif padahal 0 kWh', (chg > TOL) | (dhg > TOL))

    # 4. batas PV / inverter
    add('inverter melebihi kapasitas', pvo - sp.pv_inv_kw > 1e-5)
    add('output PV > EArray', pvo - pvg > 1e-5)
    add('unused energy negatif', exc < -TOL)
    add('unused != EArray - output', np.abs(pvg - pvo - exc) > 1e-5)
    add('charge PV > EArray', cpv - pvg > 1e-5)
    pv_load = np.maximum(pvbs - dhg, 0.0)
    add('PV ke beban > kapasitas inverter',
        pv_load - sp.pv_inv_kw > 1e-5)
    add('PV ke beban > output inverter', pv_load - pvo > 1e-5)

    # 5. batas genset
    add('DEG aktif padahal tak ada', (deg > TOL) if sp.deg_kw[0] +
        sp.deg_kw[1] + sp.deg_kw[2] <= 0 else np.zeros(n, bool))
    add('porsi DEG ke beban negatif', deg_load < -TOL)

    # 6. aturan opsi
    if not cfg.get('grid_enabled', True):
        add('grid memasok padahal tanpa sambungan', imp > TOL)
    if not sp.grid_charge_enabled:
        add('grid mengisi BESS padahal dilarang', cgr > TOL)
    if dchg_h is not None:                 # DEG-split: izin charging per jam
        add('DEG charge saat dilarang (split)', (~dchg_h) & (cdeg > TOL))
    elif not sp.deg_charge_enabled:
        add('DEG mengisi BESS padahal dilarang', cdeg > TOL)
    if sp.grid_interlock:
        add('grid & PV-BESS memasok bersamaan', (gl > TOL) & (pvbs > TOL))
        add('grid mengisi BESS saat interlock', cgr > TOL)
    if sp.deg_grid_interlock:
        add('DEG & grid memasok bersamaan', (deg_load > TOL) & (gl > TOL))
    if ilock_h is not None:                 # DEG-split: interlock PV-BESS per jam
        add('DEG & PV-BESS bersamaan (split)',
            ilock_h & (deg_load > TOL) & (pvbs > TOL))
    elif sp.deg_interlock:
        add('DEG & PV-BESS memasok bersamaan', (deg_load > TOL) & (pvbs > TOL))
    if sp.strict_charge_priority:
        add('dua sumber charge bersamaan (strict)', (cpv > TOL) & (cgr > TOL))
    if not sp.allow_export:
        add('ekspor padahal dilarang', exp_ > TOL)

    # 7. tidak boleh ada beban tak terlayani bila sumber masih sanggup
    #    (dinilai konservatif: hanya saat genset tersedia & belum penuh)
    deg_cap = (sp.deg_kw[0] + sp.deg_kw[1] + sp.deg_kw[2]) * sp.deg_max_loading[0]
    if deg_cap > 0:
        sisa_deg = deg_cap - deg
        add('unserved padahal genset masih sanggup',
            (uns > 1e-4) & (sisa_deg > 1e-4))
    return bad


# ----------------------------------------------------------------- utama
def main():
    load, pvp, gstat = make_profile()
    print(f'Audit dispatch — profil uji {len(load)} jam '
          f'(beban {load.min():.0f}–{load.max():.0f} kW, '
          f'{int((gstat == 0).sum())} jam padam)\n')

    # argumen: 'new' = hanya mode baru (komposit + split + deg-split);
    #          [part npart] = partisi
    args = sys.argv[1:]
    kinds = ['single', 'composite', 'split', 'deg-split']
    if args and args[0] == 'new':
        kinds = ['composite', 'split', 'deg-split']
        args = args[1:]
    combos = build_combos(kinds)
    print(f'Kelompok diuji: {", ".join(kinds)}  |  total kombinasi: '
          f'{len(combos):,}\n')

    if len(args) == 2:
        part, npart = int(args[0]), int(args[1])
        combos = combos[part::npart]
        print(f'Menjalankan bagian {part + 1}/{npart}: '
              f'{len(combos):,} kombinasi\n', flush=True)
    t0 = time.time()
    gagal, diuji = [], 0
    for sysname, overrides, tag in combos:
        cfg = defaults()
        cfg.update(SYSTEMS[sysname])
        cfg.update(_COMMON)
        cfg.update(overrides)
        sp = to_system_params(cfg)
        sp = dataclasses.replace(sp, pv_kwp=cfg['pv_kwp'])
        res = simulate(load, pvp, gstat, sp, record=True)
        diuji += 1
        if diuji % 1000 == 0:
            print(f'  … {diuji:,}/{len(combos):,} '
                  f'({time.time() - t0:.0f} s, {len(gagal)} gagal)',
                  flush=True)
        # mode DEG-split: interlock & charging berbeda per status grid, jadi
        # bangun mask per jam (efektif, sudah termasuk aturan interlock->charge).
        ilock_h = dchg_h = None
        if overrides.get('deg_options_split'):
            gon = gstat > 0
            ilon, iloff = bool(overrides['deg_interlock_on']), \
                bool(overrides['deg_interlock_off'])
            dcon = bool(overrides['deg_charge_on']) and not ilon
            dcoff = bool(overrides['deg_charge_off']) and not iloff
            ilock_h = np.where(gon, ilon, iloff)
            dchg_h = np.where(gon, dcon, dcoff)
        bad = check(cfg, sp, res['series'], load, gstat, ilock_h, dchg_h)
        if bad:
            gagal.append(((sysname, tag), bad))

    dt = time.time() - t0
    print(f'{diuji:,} simulasi selesai dalam {dt:.1f} s '
          f'({diuji / max(dt, 1e-9):.0f} kombinasi/detik)\n')
    if not gagal:
        print('HASIL: TIDAK ADA PELANGGARAN INVARIAN ✔')
        return 0
    print(f'HASIL: {len(gagal)} kombinasi bermasalah\n')
    for (sysname, tag), bad in gagal[:15]:
        print(f'  [{sysname}] {tag}')
        for b in bad[:4]:
            print(f'      - {b}')
    if len(gagal) > 15:
        print(f'  … dan {len(gagal) - 15} lainnya')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
