"""Audit DEG-selalu-nyala (deg_always=True).

Dua bagian:
  (I)  INERT saat grid selalu tersedia: deg_always=True HARUS byte-identik
       dengan deg_always=False (fitur tak berpengaruh) -> lintas kombinasi.
  (II) AKTIF saat grid padam / tanpa grid: jalankan kombinasi audit dgn
       deg_always=True & deg_min_loading>0 pada profil ber-outage, periksa:
        * invarian fisis KERAS (neraca energi, PCS, SOC, rincian charge, dst)
          via audit_dispatch.check — kecuali aturan opsional yg memang
          DI-OVERRIDE must-run (interlock DEG–PV/BESS & larangan DEG-charge);
        * perilaku must-run pada jam grid padam:
            - minimal 1 genset menyala saat ada beban / ruang isi BESS;
            - DEG melayani beban (deg_load ≥ min(beban, floor_terkecil));
            - DEG mengisi BESS hanya bila SOC awal < SOC maks;
            - BESS tidak discharge selama DEG belum mencapai floor.
Jalankan:  python _t_deg_always_audit.py [step]
"""
import dataclasses
import sys
import numpy as np

import audit_dispatch as A
from app.config.parameters import defaults, to_system_params
from app.engine.dispatch import simulate

TOL = 1e-6
LMIN = 0.30                       # minimum loading utk membuat floor > 0

# pesan check() yg SENGAJA di-override oleh must-run (bukan pelanggaran fisis)
_OVERRIDE = (
    'DEG & PV-BESS memasok bersamaan',
    'DEG & PV-BESS bersamaan (split)',
    'DEG mengisi BESS padahal dilarang',
    'DEG charge saat dilarang (split)',
    'DEG & grid memasok bersamaan',
)

def _mk_sp(cfg, deg_always):
    cfg = dict(cfg)
    cfg['deg_always'] = deg_always
    cfg['deg_min_loading'] = LMIN
    sp = to_system_params(cfg)
    sp = dataclasses.replace(sp, pv_kwp=cfg['pv_kwp'])
    return cfg, sp

def part_I(combos, load, pvp):
    """grid selalu UP -> deg_always tak berpengaruh (byte-identik)."""
    gstat = np.ones(len(load))
    worst = 0.0; nbad = 0; tested = 0
    for sysname, overrides, ctag in combos:
        cfg = defaults(); cfg.update(A.SYSTEMS[sysname])
        cfg.update(A._COMMON); cfg.update(overrides)
        if cfg.get('grid_kw', 0) <= 0:
            cfg['grid_kw'] = 500.0          # pastikan grid ADA (agar 'up' berarti)
        cfg['grid_enabled'] = True
        _, sp0 = _mk_sp(cfg, False)
        _, sp1 = _mk_sp(cfg, True)
        r0 = simulate(load, pvp, gstat, sp0, record=True)
        r1 = simulate(load, pvp, gstat, sp1, record=True)
        tested += 1
        for k in r0['series']:
            d = float(np.max(np.abs(np.asarray(r1['series'][k], float) -
                                    np.asarray(r0['series'][k], float))))
            worst = max(worst, d)
            if d > 1e-9:
                nbad += 1
                print(f'  INERT DIFF {k}={d:g} [{sysname} {ctag}]')
    print(f'(I) INERT grid-up: {tested:,} kombinasi | worst {worst:g} | '
          f'beda {nbad}  -> {"OK" if nbad==0 else "GAGAL"}')
    return nbad == 0

def part_II(combos, load, pvp, gstat):
    """grid ber-outage -> perilaku + fisika must-run."""
    caps_small = None
    gagal = []; tested = 0
    gna_h = (gstat <= 0)
    for sysname, overrides, ctag in combos:
        cfg = defaults(); cfg.update(A.SYSTEMS[sysname])
        cfg.update(A._COMMON); cfg.update(overrides)
        cfgT, spT = _mk_sp(cfg, True)
        res = simulate(load, pvp, gstat, spT, record=True)
        s = res['series']; tested += 1
        n = len(load)
        def c(k): return np.asarray(s[k], float).reshape(n, -1)[:, 0]
        deg, cdeg = c('deg'), c('chg_deg')
        deg_load = deg - cdeg
        dhg, cap0 = c('dhg'), c('cap_start')
        ld = c('load')
        caps = [float(x) for x in spT.deg_kw]
        pos = [x for x in caps if x > 0]
        floor_small = (min(pos) * LMIN) if pos else 0.0
        soc_max_e = spT.soc_max * spT.bess_kwh
        bad = []
        # --- fisika keras (buang aturan opsional yg di-override must-run) ---
        raw = A.check(cfgT, spT, s, load, gstat)
        raw = [b for b in raw if not b.startswith(_OVERRIDE)]
        bad += raw
        # --- perilaku must-run HANYA pada jam grid padam ---
        # DEG = sumber UTAMA: melayani beban lebih dulu (menggeser PV bila perlu),
        # surplus mengisi BESS dg PRIORITAS. Jadi ruang-isi DEG = min(PCS, headroom
        # SOC) penuh (bukan sisa setelah PV). Rumus engine: head_chg =
        # (soc_max_e - cap_start)/dt/sqrt(rte), dt=1 jam.
        off = gna_h
        # izin DEG mengisi BESS (mengikuti 'Allow DEG Charging', interlock
        # meniadakan; opsi displit -> izin saat grid padam). Menentukan apakah
        # DEG boleh 'mencari beban lain' (charge) saat beban < floor.
        if cfgT.get('deg_options_split'):
            deg_chg_ok = (bool(cfgT.get('deg_charge_off', False))
                          and not bool(cfgT.get('deg_interlock_off', True)))
        else:
            deg_chg_ok = (bool(cfgT.get('deg_charge_enabled', False))
                          and not bool(cfgT.get('deg_interlock', True)))
        if floor_small > 0 and pos:
            srte = np.sqrt(spT.rte)
            head_chg = np.maximum(0.0, (soc_max_e - cap0) / srte) if spT.bess_kwh > 0 \
                else np.zeros_like(cap0)
            deg_room = np.minimum(spT.max_charge_kw, head_chg)
            # (a) minimal 1 genset menyala saat ADA SINK: ada beban (DEG melayani
            #     dg prioritas) ATAU (ada ruang isi BESS DAN charging diizinkan).
            has_chg_sink = (deg_room > 1e-3) if deg_chg_ok else np.zeros(n, bool)
            need_on = off & ((ld > 1e-3) | has_chg_sink)
            if np.any(need_on & (deg <= TOL)):
                i = int(np.argmax(need_on & (deg <= TOL)))
                bad.append(f'must-run: DEG mati padahal ada sink @jam {i}')
            # (b) DEG melayani beban (prioritas atas PV) minimal min(beban, floor)
            want = np.minimum(ld, floor_small)
            short = off & (deg_load < want - 1e-3)
            if np.any(short):
                i = int(np.argmax(short))
                bad.append(f'must-run: deg_load< min(beban,floor) @jam {i} '
                           f'({deg_load[i]:.3f}<{want[i]:.3f})')
            # (c) charge DEG hanya bila SOC awal < maks
            badchg = off & (cdeg > 1e-4) & (cap0 >= soc_max_e - 1e-6)
            if np.any(badchg):
                i = int(np.argmax(badchg))
                bad.append(f'must-run: DEG isi BESS saat SOC=maks @jam {i}')
            # (d) tak ada discharge selama DEG belum capai floor terkecil
            #     (DEG harus melayani beban lebih dulu)
            baddis = off & (dhg > 1e-4) & (deg < floor_small - 1e-4)
            if np.any(baddis):
                i = int(np.argmax(baddis))
                bad.append(f'must-run: discharge saat DEG<floor @jam {i}')
            # (e) bila charging TIDAK diizinkan -> DEG tak boleh mengisi BESS &
            #     saat beban < floor DEG hanya sebesar beban (deg == deg_load).
            if not deg_chg_ok:
                if np.any(off & (cdeg > 1e-4)):
                    i = int(np.argmax(off & (cdeg > 1e-4)))
                    bad.append(f'must-run: DEG isi BESS padahal charging OFF @jam {i}')
                lowl = off & (ld < floor_small - 1e-3)
                if np.any(lowl & (deg > ld + 1e-3)):
                    i = int(np.argmax(lowl & (deg > ld + 1e-3)))
                    bad.append(f'must-run: DEG>beban saat charging OFF & beban<floor '
                               f'@jam {i} (deg={deg[i]:.3f}>load={ld[i]:.3f})')
        if bad:
            gagal.append(((sysname, ctag), bad))
    print(f'(II) AKTIF grid-off: {tested:,} kombinasi | '
          f'bermasalah {len(gagal)}  -> {"OK" if not gagal else "GAGAL"}')
    for (s_, tg), b in gagal[:12]:
        print(f'   [{s_}] {tg}')
        for x in b[:4]:
            print(f'       - {x}')
    return not gagal

def main():
    step = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    load, pvp, gstat = A.make_profile()
    combos = A.build_combos(['single', 'composite', 'split', 'deg-split'])[::step]
    print(f'Audit deg_always — {len(combos):,} kombinasi (step {step}), '
          f'{int((gstat==0).sum())} jam padam\n', flush=True)
    ok1 = part_I(combos, load, pvp)
    ok2 = part_II(combos, load, pvp, gstat)
    print('\nRINGKASAN:', 'SEMUA LULUS ✔' if (ok1 and ok2) else 'ADA MASALAH ✗')
    return 0 if (ok1 and ok2) else 1

if __name__ == '__main__':
    raise SystemExit(main())
