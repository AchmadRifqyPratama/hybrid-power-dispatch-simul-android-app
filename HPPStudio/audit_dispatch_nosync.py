"""Audit EKSHAUSTIF mode DEG TIDAK SINKRON (deg_sync=False).

Menjalankan SEMUA kombinasi audit standar (audit_dispatch.build_combos) namun
dengan deg_sync=False, lalu memeriksa:
  * seluruh invarian fisis umum (audit_dispatch.check) — KECUALI aturan
    'unserved padahal genset masih sanggup' yang memakai kapasitas GABUNGAN
    (tak berlaku saat genset tak boleh paralel); diganti versi no-sync.
  * invarian khusus no-sync:
      - paling banyak SATU genset menyala per jam;
      - tiap genset ≤ kapasitas·max_loading;
      - smallest-first: unit kecil yang sanggup tak boleh dilewati;
      - unserved hanya boleh saat genset TERBESAR tunggal sudah pada max.

Jalankan:  python audit_dispatch_nosync.py [part npart]
"""
from __future__ import annotations
import dataclasses
import sys
import time

import numpy as np

import audit_dispatch as A
from app.config.parameters import defaults, to_system_params
from app.engine.dispatch import simulate

TOL = 1e-6


def nosync_checks(sp, series, load):
    n = len(load)
    def c(k):
        return np.asarray(series[k], float).reshape(n, -1)[:, 0]
    d = [c('deg1'), c('deg2'), c('deg3')]
    deg = c('deg')
    uns = c('unserved')
    caps = [float(x) for x in sp.deg_kw]
    lmax = float(sp.deg_max_loading[0])
    bad = []
    on = [d[i] > TOL for i in range(3)]
    oncount = on[0].astype(int) + on[1].astype(int) + on[2].astype(int)
    if np.any(oncount > 1):
        bad.append('nosync: >1 genset menyala @jam %d' % int(np.argmax(oncount > 1)))
    for i in range(3):
        if caps[i] > 0 and np.any(d[i] - caps[i] * lmax > 1e-4):
            bad.append('nosync: unit%d > max-loading' % i)
    for i in range(3):
        for j in range(3):
            if caps[j] > 0 and caps[j] < caps[i]:
                if np.any(on[i] & (caps[j] * lmax >= d[i] + 1e-4)):
                    bad.append('nosync: unit kecil %d dilewati utk %d' % (j, i))
    # kapabilitas no-sync: unserved hanya saat genset TERBESAR pada max loading
    largest = max(caps) if caps else 0.0
    if largest > 0:
        sisa = largest * lmax - deg
        if np.any((uns > 1e-4) & (sisa > 1e-4)):
            bad.append('nosync: unserved padahal genset terbesar belum penuh '
                       '@jam %d' % int(np.argmax((uns > 1e-4) & (sisa > 1e-4))))
    return bad


def main():
    load, pvp, gstat = A.make_profile()
    combos = A.build_combos(['single', 'composite', 'split', 'deg-split'])
    args = sys.argv[1:]
    if len(args) == 2:
        part, npart = int(args[0]), int(args[1])
        combos = combos[part::npart]
        tag = f'bagian {part + 1}/{npart}'
    else:
        tag = 'penuh'
    print(f'Audit NO-SYNC ({tag}): {len(combos):,} kombinasi', flush=True)
    t0 = time.time()
    gagal, diuji = [], 0
    for sysname, overrides, ctag in combos:
        cfg = defaults()
        cfg.update(A.SYSTEMS[sysname]); cfg.update(A._COMMON); cfg.update(overrides)
        cfg['deg_sync'] = False                      # <-- mode tidak sinkron
        sp = to_system_params(cfg)
        sp = dataclasses.replace(sp, pv_kwp=cfg['pv_kwp'])
        res = simulate(load, pvp, gstat, sp, record=True)
        diuji += 1
        if diuji % 2000 == 0:
            print(f'  … {diuji:,}/{len(combos):,} ({time.time()-t0:.0f}s, '
                  f'{len(gagal)} gagal)', flush=True)
        ilock_h = dchg_h = None
        if overrides.get('deg_options_split'):
            gon = gstat > 0
            ilon, iloff = bool(overrides['deg_interlock_on']), \
                bool(overrides['deg_interlock_off'])
            dcon = bool(overrides['deg_charge_on']) and not ilon
            dcoff = bool(overrides['deg_charge_off']) and not iloff
            ilock_h = np.where(gon, ilon, iloff)
            dchg_h = np.where(gon, dcon, dcoff)
        bad = A.check(cfg, sp, res['series'], load, gstat, ilock_h, dchg_h)
        # buang aturan kapasitas-gabungan (tak berlaku no-sync); ganti versi no-sync
        bad = [b for b in bad
               if not b.startswith('unserved padahal genset masih sanggup')]
        bad += nosync_checks(sp, res['series'], load)
        if bad:
            gagal.append(((sysname, ctag), bad))
    dt = time.time() - t0
    print(f'{diuji:,} simulasi no-sync dalam {dt:.1f}s '
          f'({diuji/max(dt,1e-9):.0f}/detik)', flush=True)
    if not gagal:
        print('HASIL NO-SYNC: TIDAK ADA PELANGGARAN INVARIAN ✔')
        return 0
    print(f'HASIL NO-SYNC: {len(gagal)} kombinasi bermasalah')
    for (s, tg), b in gagal[:15]:
        print(f'  [{s}] {tg}')
        for x in b[:4]:
            print(f'      - {x}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
