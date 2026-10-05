"""Cek versi build & uji cepat strategi dispatch — tanpa GUI.

Jalankan:  python cek_dispatch.py
Berguna untuk memastikan salinan yang Anda jalankan sudah memuat perbaikan
terbaru, dan untuk melihat langsung perilaku dispatch pada tiap skenario.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BUILD = '2026-07-31b · audit ekshaustif 13.824 kombinasi'


def _fitur():
    """Deteksi keberadaan perbaikan penting pada berkas engine."""
    src = open(os.path.join(HERE, 'app', 'engine', 'dispatch.py'),
               encoding='utf-8').read()
    return [
        ('Grid interlock: kapasitas genset ikut dihitung',
         'firm_cap = firm_cap + deg_cap_max' in src),
        ('Interlock DEG tidak mematikan pasokan grid',
         'AD = np.where(excl & (~grid_off), ad_g, AD)' in src),
        ('Rantai PV → Grid → DEG → BESS',
         'rantai PV → Grid → DEG → BESS' in src),
        ('Rantai Grid → DEG → PV → BESS',
         'DEG paralel grid   : Grid → DEG → PV → BESS' in src),
        ('Opsi DEG Interlock with Grid', 'deg_grid_interlock' in src),
        ('Opsi Grid Interlock with PV-BESS', 'grid_interlock' in src),
        ('Transfer switch saat grid tak sanggup',
         'grid_off = grid_off | transfer' in src),
        ('Transfer sadar Grid-Interlock (bus tak dijumlahkan)',
         'other_cap = np.maximum(grid_cap_t, pv_cap + d_cap)' in src),
        ('Batas maximum loading grid dihormati',
         'np.minimum(gmax * Hg, rem)' in src),
        ('DEG dinilai sebelum BESS pada rantai PV→Grid→DEG→BESS',
         'need_deg = (((pv_cap + grid_cap) < ae - 1e-9)' in src),
        ('Kapabilitas PV dibatasi inverter', 'pv_cap = np.minimum(q, pinv)'
         in src),
        ('Kapabilitas BESS dibatasi PCS',
         'd_cap = np.minimum(d_pot, max_dhg)' in src),
        ('Pasokan grid tak melebihi beban', 'def _grid_serve(rem):' in src),
    ]


def main():
    print(f'HPP Studio — cek dispatch (build {BUILD})')
    print(f'Folder: {HERE}\n')
    ok = True
    for nama, ada in _fitur():
        print(f'  {"OK " if ada else "!! "} {nama}')
        ok = ok and ada
    if not ok:
        print('\n[!] Salinan ini BELUM memuat perbaikan terbaru — ekstrak ulang '
              'berkas ZIP terbaru ke folder yang benar-benar Anda jalankan.')
        return
    print('\nSemua perbaikan terpasang. Menjalankan uji perilaku …\n')

    import dataclasses
    from app.config.parameters import defaults, to_system_params
    from app.engine.dispatch import simulate

    # profil sintetis: beban 150 kW (melebihi kapasitas grid 100 kW), PV siang
    n = 48
    load = np.full(n, 150.0)
    pvp = np.zeros(n)
    for d in range(2):
        for h in range(6, 18):
            pvp[d * 24 + h] = 60.0 * np.sin((h - 6) / 12 * np.pi)
    grid = np.ones(n)
    grid[30:34] = 0.0          # padam 4 jam

    cfg = defaults()
    cfg.update(load_priority='Grid -> DEG -> PV -> BESS',
               deg_grid_interlock=False, grid_interlock=True,
               deg_interlock=True, deg_count='1', deg1_kw=250.0,
               pv_base_annual=1.0)
    sp = dataclasses.replace(
        to_system_params(cfg), pv_kwp=1.0, pv_inv_kw=100.0, bess_kwh=400.0,
        grid_kw=100.0, max_charge_kw=200.0, max_discharge_kw=200.0)
    s = simulate(load, pvp, grid, sp, record=True)['series']

    def col(k):
        return np.asarray(s[k]).reshape(-1)

    print(' jam status   load    grid     DEG    BESS   SOC%')
    for i in list(range(4)) + [12, 13] + list(range(29, 35)):
        print('  %3d    %d   %6.1f  %6.1f  %6.1f  %6.1f  %5.1f'
              % (i, col('grid_status')[i], col('load')[i],
                 col('grid_load')[i], col('deg')[i], col('dhg')[i],
                 col('soc')[i] * 100))

    on = col('grid_status') > 0
    diam = int((on & (col('load') > 100.0)
                & (col('grid_load') <= 1e-9)).sum())
    bantu = int((on & (col('deg') > 1e-9)).sum())
    print(f'\n  Jam grid ON & beban > kapasitas: {int((on).sum())}')
    print(f'  Grid diam padahal tersedia      : {diam}   (harus 0)')
    print(f'  Jam genset membantu grid        : {bantu}   (harus > 0)')
    print('\nHASIL: ' + ('BENAR — grid memasok penuh, genset menutup sisanya.'
                         if diam == 0 and bantu > 0 else
                         'MASIH SALAH — kirimkan keluaran ini.'))

    # --- uji kedua: interlock penuh (grid & DEG saling kunci) ---
    cfg2 = defaults()
    cfg2.update(load_priority='Grid -> PV -> BESS -> DEG',
                deg_grid_interlock=True, grid_interlock=True,
                deg_interlock=True, deg_count='1', deg1_kw=400.0,
                pv_base_annual=1.0, soc_init=0.16, soc_min=0.10)
    sp2 = dataclasses.replace(
        to_system_params(cfg2), pv_kwp=1.0, pv_inv_kw=100.0, bess_kwh=2892.0,
        grid_kw=80.0, max_charge_kw=1296.0, max_discharge_kw=1296.0)
    load2 = np.full(6, 225.5)
    s2 = simulate(load2, np.zeros(6), np.ones(6), sp2, record=True)['series']

    def c2(k):
        return np.asarray(s2[k]).reshape(-1)

    print('\n[uji 2] Interlock penuh — beban 225,5 kW, grid 80 kW, PV 0, '
          'SOC rendah')
    print(' jam    load    grid      DEG   BESS  unserved')
    for i in range(4):
        print('  %2d  %6.1f  %6.1f  %7.1f  %5.1f  %8.2f'
              % (i, c2('load')[i], c2('grid_load')[i], c2('deg')[i],
                 c2('dhg')[i], c2('unserved')[i]))
    uns = float(c2('unserved').sum())
    print('  Unserved total: %.2f kWh (harus 0) -> %s'
          % (uns, 'BENAR' if uns < 1e-6 else 'MASIH SALAH'))


if __name__ == '__main__':
    main()
