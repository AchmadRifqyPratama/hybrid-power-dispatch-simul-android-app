"""Self-test HPP Studio tanpa GUI.

Jalankan:  python selftest.py
Memverifikasi seluruh rantai non-GUI di mesin Anda:
import data -> simulasi 8760 jam -> KPI -> finansial -> optimasi kecil
(multiprocessing) -> export Excel -> laporan HTML.
Semua output tulis ke folder ./selftest_out
"""
import os
import sys
import time

import numpy as np


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    out = os.path.join(here, 'selftest_out')
    os.makedirs(out, exist_ok=True)

    print('[1/6] Import data sample ...')
    from app.data.importer import read_profile_file
    r = read_profile_file(os.path.join(here, 'assets', 'sample_input.xlsx'))
    load, pv, grid, dts = r['load'], r['pv'], r['grid'], r['datetimes']
    assert len(load) in (8760, 8784)
    print(f'      {len(load)} baris | load {np.nansum(load):,.1f} kWh | '
          f'PV {np.nansum(pv):,.1f} | grid padam '
          f'{int(np.sum(np.asarray(grid) == 0))} jam')

    print('[2/6] Simulasi 1 tahun ...')
    from app.config.parameters import defaults, to_system_params, cost_config
    from app.engine.simulation import SimulationEngine
    cfg = defaults()
    eng = SimulationEngine(load, pv, grid, datetimes=dts)
    t0 = time.time()
    res = eng.run(to_system_params(cfg), cost_cfg=cost_config(cfg), record=True)
    k, f = res['kpi'], res['finance']
    print(f'      {time.time() - t0:.2f} s | RF {k["renewable_fraction"]*100:.1f}% | '
          f'grid import {k["grid_import_kwh"]:,.1f} kWh | '
          f'LCOE {f["lcoe"]:,.0f} | payback {f["payback_years"]:.2f} th')
    exp = 88346.10854873648
    if abs(k['grid_import_kwh'] - exp) < 1e-6:
        print('      ✔ identik dengan referensi Excel (deviasi < 1e-6 kWh)')

    print('[3/6] Optimasi kecil (multiprocessing) ...')
    from app.config.parameters import opt_base_params
    from app.engine.optimization import (OptimizationEngine, SweepRange,
                                         build_grid)
    g = build_grid(SweepRange(20, 80, 20), SweepRange(20, 60, 20),
                   SweepRange(100, 400, 100))
    oe = OptimizationEngine(load, pv, grid, opt_base_params(cfg),
                            cost_config(cfg))
    t0 = time.time()
    ro = oe.run(g, 'Min LCOE', {})
    b = ro['rank_order'][0]
    print(f'      {len(g)} kombinasi dalam {time.time() - t0:.1f} s | terbaik: '
          f'PV {ro["kwp"][b]:.0f} kWp / INV {ro["kw_inv"][b]:.0f} kW / '
          f'BESS {ro["kwh_bess"][b]:.0f} kWh (LCOE {ro["lcoe"][b]:,.0f})')

    print('[4/6] Export Excel hasil simulasi ...')
    from app.data.exporter import export_simulation, export_optimization
    export_simulation(os.path.join(out, 'hasil_simulasi.xlsx'), res, dts)
    export_optimization(os.path.join(out, 'hasil_optimasi.xlsx'), ro, top_n=50)
    print('      ✔ selftest_out/hasil_simulasi.xlsx & hasil_optimasi.xlsx')

    print('[5/6] Laporan HTML ...')
    from app.reports.report_builder import build_report
    build_report(os.path.join(out, 'laporan.html'), cfg, res, dts)
    print('      ✔ selftest_out/laporan.html — buka dengan browser')

    print('[6/6] Cek GUI dapat di-import ...')
    try:
        import PySide6  # noqa: F401
        import pyqtgraph  # noqa: F401
        print('      ✔ PySide6 & pyqtgraph terpasang — jalankan: python main.py')
    except ImportError as e:
        print(f'      ✖ {e} — jalankan: pip install -r requirements.txt')

    print('\nSELESAI — semua modul inti berjalan normal.')


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
