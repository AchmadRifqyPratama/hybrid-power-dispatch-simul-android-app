"""Halaman Multi-Year — simulasi project-lifetime (data aktif) + batch
multi-site. Dipisahkan dari halaman Results agar fokus & rapi.

Perhitungan (run_lifetime) TIDAK berubah — hanya lokasi UI-nya yang dipindah.
"""
from __future__ import annotations
import os
import numpy as np

import threading

from ...config.i18n import tr
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QFileDialog, QMessageBox, QGroupBox, QGridLayout,
    QTableWidgetItem, QComboBox, QProgressBar, QCheckBox,
    QLineEdit, QApplication, QRadioButton, QButtonGroup)
import pyqtgraph as pg
from ..bgproc import ProcWorker

from ..theme import SERIES_COLORS
from ..widgets import KPICard, kpi_grid
from ..plotutil import (no_wheel_zoom, CursorReadout, fit_table_columns,
                        CopyTableWidget)
from ...data.exporter import (export_multi_year, export_filename,
                              export_batch_multi_year)
from ...data.importer import (read_profile_file, read_site_coords,
                              ImportError_)
from ...data.pvgis import batch_pvgis_pv
from ...engine.multiyear import (run_lifetime, year_hourly_series,
                                 year_series_datetimes)


class _MultiYearWorker(ProcWorker):   # proses latar (lihat gui/bgproc.py)
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(int)               # persen 0..100

    def __init__(self, state):
        super().__init__()
        self.state = state

    def run(self):
        try:
            st = self.state

            def _cb(done, total):
                self.progress.emit(int(done * 100 / max(total, 1)))

            self.finished_ok.emit(run_lifetime(
                st.load, st.pv_norm, st.grid_status, dict(st.cfg),
                deg_status=st.deg_status, datetimes=st.datetimes,
                progress=_cb))
        except Exception as e:  # pragma: no cover
            self.failed.emit(str(e))


class _MultiYearBatchWorker(ProcWorker):   # proses latar (lihat gui/bgproc.py)
    """Jalankan simulasi multi-year untuk beberapa berkas data (multi-site)
    secara berurutan, memakai parameter (cfg) yang SAMA. Nama site diambil dari
    nama berkas. Tahan-banting: satu berkas gagal dicatat & dilewati.

    PENTING: worker ini TIDAK membaca Excel. Berkas dibaca lebih dulu di THREAD
    UTAMA (pandas/openpyxl/lxml tidak aman dipanggil dari thread lain di Windows
    — memicu 'access violation'). Worker hanya menjalankan run_lifetime() atas
    profil yang sudah dimuat — jalur perhitungan sama persis dengan Run
    Multi-Year (numerik tidak berubah)."""
    progress = Signal(int, int, str)      # indeks, total, nama site
    finished_ok = Signal()                # hasil disimpan di self._result_rows
    failed = Signal(str)

    def __init__(self, loaded, cfg, overrides=None, fallback_pv=None,
                 read_errors=None, base_mode='params', base_custom=None):
        super().__init__()
        # loaded: [{'site','path','load','pv','grid','deg'}] — sudah dibaca di GUI.
        self.loaded = list(loaded)
        self.cfg = dict(cfg)
        # overrides: path -> {'pv_kwp','pv_inv_kw','bess_kwh','pcs_kw'} bila
        # site memakai sizing khusus; selain itu memakai cfg (halaman Parameters).
        self.overrides = dict(overrides or {})
        self.fallback_pv = fallback_pv
        # base_mode: sumber pv_base_annual (Base Profile Plant Size):
        #   'params' -> nilai halaman Parameters (cfg)
        #   'pv'     -> sama dengan PV (kWp) tiap site
        #   'custom' -> nilai tetap (base_custom) untuk semua site
        self.base_mode = base_mode
        self.base_custom = base_custom
        self.cancel_flag = threading.Event()
        self.errors = list(read_errors or [])   # galat baca dari thread utama
        self._result_rows = []            # hasil (dibaca thread GUI saat selesai)

    def run(self):
        rows = []
        try:
            for i, item in enumerate(self.loaded):
                if self.cancel_flag.is_set():
                    break
                site = item['site']
                path = item.get('path', site)
                self.progress.emit(i, len(self.loaded), site)
                try:
                    load, pv = item.get('load'), item.get('pv')
                    if load is None:
                        raise ImportError_(
                            tr('{site}: kolom Load tidak ditemukan.'
                               ).format(site=site))
                    n = len(load)
                    if pv is None:
                        if (self.fallback_pv is None
                                or len(self.fallback_pv) != n):
                            raise ImportError_(
                                tr('{site}: kolom PV ENetAC tidak ada dan '
                                   'tidak ada profil PV yang dapat dipakai.'
                                   ).format(site=site))
                        pv = self.fallback_pv
                    gs = item.get('grid')
                    if gs is None:
                        gs = (np.ones(n) if self.cfg.get('grid_enabled', True)
                              else np.zeros(n))
                    deg = item.get('deg')         # DEG Status per-site (opsional)
                    cfg_site = dict(self.cfg)     # semua param dari Parameters
                    ov = self.overrides.get(path)
                    if ov:                         # sizing khusus per site
                        cfg_site['pv_kwp'] = float(ov['pv_kwp'])
                        cfg_site['pv_inv_kw'] = float(ov['pv_inv_kw'])
                        cfg_site['bess_kwh'] = float(ov['bess_kwh'])
                        cfg_site['max_charge_kw'] = float(ov['pcs_kw'])
                        cfg_site['max_discharge_kw'] = float(ov['pcs_kw'])
                        if ov.get('self_cons_kw') is not None:
                            cfg_site['bess_self_cons_kw'] = float(ov['self_cons_kw'])
                    # Base Profile Plant Size (pv_base_annual) sesuai toggle
                    if self.base_mode == 'pv':
                        b = float(cfg_site.get('pv_kwp', 0.0))
                        if b > 0:            # 'pv' -> profil PV dipakai apa adanya
                            cfg_site['pv_base_annual'] = b
                    elif self.base_mode == 'custom' and self.base_custom:
                        cfg_site['pv_base_annual'] = float(self.base_custom)
                    # 'params' -> biarkan cfg_site['pv_base_annual'] (Parameters)
                    # Bila PV berasal dari PVGIS (koordinat per-site), profilnya
                    # mewakili `pv_base_annual` kWp tertentu -> pakai nilai itu
                    # agar penskalaan benar (mengalahkan toggle di atas).
                    if item.get('pv_base_annual'):
                        cfg_site['pv_base_annual'] = float(item['pv_base_annual'])
                    res = run_lifetime(load, pv, gs, cfg_site,
                                       deg_status=deg,
                                       datetimes=item.get('datetimes'))
                    sizing = {'pv_kwp': float(cfg_site['pv_kwp']),
                              'kw_inv': float(cfg_site['pv_inv_kw']),
                              'bess_kwh': float(cfg_site['bess_kwh']),
                              'pcs_kw': float(cfg_site['max_charge_kw']),
                              'self_cons_kw': float(
                                  cfg_site.get('bess_self_cons_kw', 0.0) or 0.0)}
                    rows.append({'site': site, 'path': path, 'res': res,
                                 'sizing': sizing, 'custom': bool(ov)})
                except Exception as e:     # satu site gagal -> catat, lanjut
                    self.errors.append((site, str(e)))
            # Simpan hasil di worker (dibaca thread GUI) — TIDAK dikirim lewat
            # sinyal agar array numpy tak perlu di-marshal antar-thread (sumber
            # crash/force-close pada build .exe Windows / PySide6).
            self._result_rows = rows
            self.finished_ok.emit()
        except Exception as e:                      # pragma: no cover
            self._result_rows = []
            self.failed.emit(str(e))


class MultiYearPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        t = QLabel(tr('Multi-Year')); t.setObjectName('PageTitle')
        head.addWidget(t); head.addStretch(1)
        lay.addLayout(head)
        sub = QLabel(tr('Simulasi seluruh umur proyek (lifetime) untuk data '
                        'aktif, serta batch multi-site.'))
        sub.setObjectName('PageSub'); sub.setWordWrap(True)
        lay.addWidget(sub)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); iv = QVBoxLayout(inner)

        # ---------------- Multi-Year (Lifetime) ----------------
        my_box = QGroupBox(tr('Simulasi Multi-Year (Project Lifetime)'))
        myl = QVBoxLayout(my_box)
        row = QHBoxLayout()
        self.btn_my = QPushButton(tr('▶  Run Multi-Year'))
        self.btn_my.clicked.connect(self._run_multi)
        self.lbl_my = QLabel(
            tr('Simulasikan seluruh lifetime dengan degradasi PV & BESS '
               'per tahun serta eskalasi harga (inflasi) dan discount '
               'rate.'))
        self.lbl_my.setObjectName('PageSub'); self.lbl_my.setWordWrap(True)
        self.btn_my_export = QPushButton(tr('Export Multi-Year…'))
        self.btn_my_export.setEnabled(False)
        self.btn_my_export.clicked.connect(self._export_multi)
        self.btn_my_clear = QPushButton(tr('Bersihkan Multi-Year'))
        self.btn_my_clear.setProperty('flat', True)
        self.btn_my_clear.setCursor(Qt.PointingHandCursor)
        self.btn_my_clear.clicked.connect(self._clear_multi)
        row.addWidget(self.btn_my); row.addWidget(self.btn_my_export)
        row.addWidget(self.btn_my_clear)
        row.addStretch(1)
        myl.addLayout(row)
        myl.addWidget(self.lbl_my)

        self.my_cards = {k: KPICard(lbl, '-', unit) for k, lbl, unit in [
            ('lcoe', tr('LCOE Lifetime'), 'Rp/kWh'), ('npv', tr('NPV'), tr('Rp')),
            ('irr', tr('IRR'), '%'),
            ('payback_years', tr('Payback'), tr('tahun'))]}
        myl.addWidget(kpi_grid(list(self.my_cards.values()), cols=4))

        prow = QHBoxLayout()
        prow.addWidget(QLabel(tr('Grafik per tahun:')))
        self.my_metric = QComboBox()
        self._MY_METRICS = [
            ('renewable_fraction', tr('Renewable Fraction (%)'), 100.0),
            ('annual_pv_generation_kwh', tr('PV Generation (kWh)'), 1.0),
            ('diesel_fuel_l', tr('Diesel Fuel (L)'), 1.0),
            ('grid_import_kwh', tr('Grid Import (kWh)'), 1.0),
            ('pv_excess_kwh', tr('Unused/Curtailment (kWh)'), 1.0),
            ('unserved_kwh', tr('Unserved (kWh)'), 1.0),
            ('_soh', tr('BESS SOH (%)'), 100.0),
            ('_savings', tr('Savings (Rp)'), 1.0),
            ('_cum', tr('Cashflow Kumulatif (Rp)'), 1.0)]
        self.my_metric.addItems([m[1] for m in self._MY_METRICS])
        self.my_metric.currentIndexChanged.connect(self._plot_multi)
        prow.addWidget(self.my_metric); prow.addStretch(1)
        myl.addLayout(prow)
        self.my_plot = pg.PlotWidget(); self.my_plot.setMinimumHeight(230)
        no_wheel_zoom(self.my_plot)
        self.lbl_my_cur = QLabel(''); self.lbl_my_cur.setObjectName('PageSub')
        self.my_plot.showGrid(y=True, alpha=0.2)
        self.my_plot.setLabel('bottom', tr('Tahun ke-'))
        myl.addWidget(self.lbl_my_cur)
        myl.addWidget(self.my_plot)
        self._cur_my = CursorReadout(self.my_plot, self.lbl_my_cur,
                                     self._my_at)

        self.my_table = CopyTableWidget()
        self.my_table.setMinimumHeight(240)
        self.my_table.setToolTip(tr(
            'Seret untuk memblok sel, lalu Ctrl+C untuk menyalin ke Excel.'))
        myl.addWidget(self.my_table)
        iv.addWidget(my_box)

        # ---------- Batch Multi-Site (Multi-Year) ----------
        self._build_batch_ui(iv)

        iv.addStretch(1)

        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        state.results_cleared.connect(self._on_cleared)
        if getattr(state, 'multi_result', None):   # pulihkan multi-year
            try:
                self._apply_multi(state.multi_result)
            except Exception:
                state.multi_result = None

    # ---------------- Multi-Year ----------------
    def _run_multi(self):
        # cegah start ganda (worker lama ter-orphan -> abort/force close)
        if getattr(self, '_myw', None) is not None and self._myw.isRunning():
            return
        if getattr(self, 'mybw', None) is not None and self.mybw.isRunning():
            QMessageBox.information(
                self, tr('Sedang berjalan'),
                tr('Tunggu batch multi-site yang sedang berjalan selesai.'))
            return
        if not self.state.data_ready():
            QMessageBox.information(self, tr('Data belum ada'),
                                    tr('Import Load Profile & PV ENetAC dahulu.'))
            return
        self.btn_my.setEnabled(False)
        self.lbl_my.setText(tr('Menjalankan simulasi seluruh lifetime … {p}%')
                            .format(p=0))
        self._myw = _MultiYearWorker(self.state)
        self._register_worker(self._myw)
        self._myw.finished_ok.connect(self._multi_done)
        self._myw.failed.connect(self._multi_fail)
        self._myw.progress.connect(self._multi_progress)
        self._myw.start()

    def _multi_progress(self, pct):
        self.lbl_my.setText(
            tr('Menjalankan simulasi seluruh lifetime … {p}%').format(p=int(pct)))

    def _multi_fail(self, msg):
        self.btn_my.setEnabled(True)
        self.lbl_my.setText(tr('Multi-year gagal.'))
        QMessageBox.critical(self, tr('Error'), msg)

    def _multi_done(self, res):
        self.btn_my.setEnabled(True)
        self.state.multi_result = res
        self._apply_multi(res)

    def _apply_multi(self, res):
        """Isi ringkasan, grafik, dan tabel multi-year (dipakai juga saat
        halaman dibangun ulang)."""
        self.btn_my_export.setEnabled(True)
        c = self.state.cfg
        f = res['finance']
        from ...config.parameters import soh_curve_active
        if soh_curve_active(c):
            self.lbl_my.setText(
                tr('Selesai — {n} tahun tersimulasi (degradasi PV {pv}%/th, '
                   'BESS mengikuti kurva SOH impor, inflasi {infl}%, '
                   'discount {disc}%).').format(
                    n=len(res['years']),
                    pv=f'{c["pv_degradation"]*100:.2f}',
                    infl=f'{c["inflation"]*100:.1f}',
                    disc=f'{c["discount_rate"]*100:.1f}'))
        else:
            self.lbl_my.setText(
                tr('Selesai — {n} tahun tersimulasi (degradasi PV {pv}%/th, '
                   'BESS {bess}%/th, inflasi {infl}%, discount {disc}%).').format(
                    n=len(res['years']),
                    pv=f'{c["pv_degradation"]*100:.2f}',
                    bess=f'{c["bess_degradation"]*100:.2f}',
                    infl=f'{c["inflation"]*100:.1f}',
                    disc=f'{c["discount_rate"]*100:.1f}'))
        self.my_cards['lcoe'].set_value(f'{f["lcoe"]:,.0f}')
        self.my_cards['npv'].set_value(f'{f["npv"]:,.0f}')
        self.my_cards['irr'].set_value(f'{f["irr"]*100:,.1f}')
        self.my_cards['payback_years'].set_value(f'{f["payback_years"]:,.1f}')
        self._plot_multi()
        self._fill_multi_table(res)

    def _my_series(self, res, key, scale):
        if key == '_soh':
            return np.asarray(res.get('bess_soh',
                                      np.ones(len(res['years'])))) * scale
        if key == '_savings':
            return np.asarray(res['finance']['savings_y'], float)
        if key == '_cum':
            return np.asarray(res['finance']['cum_cashflow'], float)
        return np.asarray(res['kpi'][key], float) * scale

    def _on_cleared(self, kind):
        if kind in ('multiyear', 'all'):
            self.clear_multi_view()
        if kind == 'all':
            self._clear_myb()

    def clear_multi_view(self):
        """Kosongkan kartu, grafik, dan tabel multi-year."""
        for c in self.my_cards.values():
            c.set_value('-')
        try:
            self.my_plot.clear()
        except Exception:
            pass
        self.my_table.clearContents()
        self.my_table.setRowCount(0)
        self._my_vals = None
        if hasattr(self, 'lbl_my_cur'):
            self.lbl_my_cur.setText('')
        self.btn_my_export.setEnabled(False)
        self.lbl_my.setText(tr(
            'Simulasikan seluruh lifetime dengan degradasi PV & BESS per '
            'tahun serta eskalasi harga (inflasi) dan discount rate.'))

    def _clear_multi(self):
        # Tetap berfungsi walau state sudah kosong tetapi tampilan masih
        # berisi (mis. hasil dihapus dari halaman lain) — sebelumnya tombol
        # diam saja pada kondisi ini.
        has_view = (getattr(self, '_my_vals', None) is not None
                    or self.my_table.rowCount() > 0)
        if not getattr(self.state, 'multi_result', None) and not has_view:
            return
        if QMessageBox.question(
                self, tr('Bersihkan Multi-Year'),
                tr('Hapus hasil simulasi multi-year?')) != QMessageBox.Yes:
            return
        self.state.multi_result = None
        self.clear_multi_view()
        self.state.results_cleared.emit('multiyear')

    def _my_at(self, x):
        v = getattr(self, '_my_vals', None)
        if v is None or not len(v):
            return ''
        i = int(round(x)) - 1
        if i < 0 or i >= len(v):
            return ''
        return (tr('Tahun') + f' {i + 1}  —  '
                f'{v[i]:,.2f} {self._my_unit}')

    def _plot_multi(self):
        res = getattr(self.state, 'multi_result', None)
        if not res:
            return
        key, label, scale = self._MY_METRICS[self.my_metric.currentIndex()]
        v = self._my_series(res, key, scale)
        x = np.asarray(res['years'], float)
        self.my_plot.clear()
        if key == '_cum':
            self.my_plot.addItem(pg.BarGraphItem(
                x=x, height=v, width=0.7,
                brushes=[SERIES_COLORS['deg'] if h < 0 else
                         SERIES_COLORS['pv'] for h in v]))
            self.my_plot.addLine(y=0, pen=pg.mkPen('#9CA3AF', width=1))
        else:
            self.my_plot.addItem(pg.BarGraphItem(x=x, height=v, width=0.7,
                                                 brush=SERIES_COLORS['pv'],
                                                 pen=None))
        self.my_plot.setLabel('left', label)
        self._my_vals = list(np.asarray(v, float))
        self._my_unit = label

    @staticmethod
    def _year_table_cols(res, cfg=None):
        """Definisi kolom tabel per-tahun (dipakai bersama oleh tabel Multi-Year
        dan tabel per-tahun batch multi-site). Tiap kolom: (nama, unit, nilai,
        desimal)."""
        k, f = res['kpi'], res['finance']
        yrs = len(res['years'])
        # BESS autonomous (jam): energi BESS terpakai / rata-rata beban.
        # Energi terpakai memakai konvensi app: bess_kwh × (soc_max − soc_min)
        # (lihat engine/kpi.py). Dihitung di UI — tidak mengubah mesin hitung.
        cfg = cfg or {}
        soc_win = max(float(cfg.get('soc_max', 0.95))
                      - float(cfg.get('soc_min', 0.1)), 0.0)
        usable = np.asarray(res['bess_kwh_eff'], float) * soc_win
        avg_load_kw = np.asarray(k['annual_load_kwh'], float) / 8760.0
        with np.errstate(divide='ignore', invalid='ignore'):
            autonomy_h = np.where(avg_load_kw > 0, usable / avg_load_kw, 0.0)
        return [(tr('Tahun'), '', res['years'], 0),
                (tr('PV Efektif'), 'kWp', res['pv_kwp_eff'], 1),
                (tr('BESS SOH'), '%', np.asarray(res.get(
                    'bess_soh', np.ones(yrs))) * 100, 1),
                (tr('BESS Efektif'), 'kWh', res['bess_kwh_eff'], 1),
                (tr('BESS autonomous'), tr('jam'), autonomy_h, 2),
                (tr('Battery Discharge'), 'kWh',
                 k['annual_battery_discharge_kwh'], 0),
                (tr('Battery Throughput'), 'kWh', k['battery_throughput_kwh'], 0),
                (tr('PV Gen'), 'kWh', k['annual_pv_generation_kwh'], 2),
                (tr('PV Pen'), 'kWh', k['annual_pv_inverter_out_kwh'], 2),
                (tr('RF'), '%', k['renewable_fraction'] * 100, 2),
                (tr('DEG Fuel'), tr('L/tahun'), k['diesel_fuel_l'], 2),
                (tr('DEG - total'), 'kWh', k['diesel_energy_kwh'], 2),
                (tr('DEG - runtime'), tr('jam'), k['diesel_runtime_h'], 2),
                (tr('Grid Imp'), 'kWh', k['grid_import_kwh'], 0),
                (tr('Unused'), 'kWh', k['pv_excess_kwh'], 0),
                (tr('PV Curtailment'), '%', k['pv_excess_ratio'] * 100, 2),
                (tr('Unserved'), 'kWh', k['unserved_kwh'], 1),
                (tr('OPEX'), 'Rp', f['opex_y'], 0),
                (tr('Savings'), 'Rp', f['savings_y'], 0),
                (tr('Kumulatif'), 'Rp', f['cum_cashflow'], 0)]

    @staticmethod
    def _fill_year_table(t, res, cfg=None):
        """Isi sebuah tabel per-tahun dari hasil run_lifetime `res`.
        Menyimpan nilai mentah (tanpa pemisah ribuan) di UserRole agar tersalin
        bersih ke Excel; kolom dirapatkan sesuai isi (fill=False); header
        di-wrap ke baris kedua (nama di atas, unit di bawah)."""
        cols = MultiYearPage._year_table_cols(res, cfg)
        t.setColumnCount(len(cols))
        t.setRowCount(len(res['years']))
        t.setHorizontalHeaderLabels(
            [(f'{n}\n({u})' if u else n) for (n, u, _a, _d) in cols])
        # header wrap otomatis bila teks tetap tak muat
        hh = t.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignCenter | Qt.TextWordWrap)
        for j, (_n, _u, arr, dec) in enumerate(cols):
            a = np.asarray(arr, float).reshape(-1)
            for i in range(len(a)):
                cell = QTableWidgetItem(f'{a[i]:,.{dec}f}')
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                cell.setData(Qt.UserRole, f'{a[i]:.{dec}f}')   # mentah utk Excel
                t.setItem(i, j, cell)
        fit_table_columns(t, min_w=60, max_w=200, fill=False)

    def _fill_multi_table(self, res):
        self._fill_year_table(self.my_table, res, self.state.cfg)

    def _export_multi(self):
        res = getattr(self.state, 'multi_result', None)
        if not res:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Simpan Multi-Year'),
            export_filename(self.state.cfg, tr('hasil_multi_year')),
            'Excel (*.xlsx)')
        if not path:
            return
        ans = QMessageBox.question(
            self, tr('Tabel per jam'),
            tr('Sertakan tabel per jam untuk setiap tahun? (satu sheet per '
               'tahun, proses lebih lama dan file jauh lebih besar)'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        hourly = None
        if ans == QMessageBox.Yes:
            st = self.state
            import pandas as pd
            # Deret per-tahun kini memakai basis 'sim_interval' yang SAMA dgn
            # Dashboard (lihat multiyear._my_prepare): panjang & resolusi deret
            # = jendela interval. Timestamp dibangun dari year_series_datetimes
            # sesuai panjang deret AKTUAL (bukan asumsi per-jam).
            start = f'{int(st.cfg.get("simulation_year", 2025))}-01-01'
            hourly = {}
            for y in res['years']:
                ser = year_hourly_series(
                    st.load, st.pv_norm, st.grid_status, dict(st.cfg), int(y),
                    deg_status=st.deg_status, datetimes=st.datetimes)
                # panjang deret dari salah satu kunci series
                _len = len(next(iter(ser.values()))) if ser else 0
                _dts = year_series_datetimes(dict(st.cfg), _len, start=start)
                hourly[int(y)] = (_dts, ser)
        try:
            export_multi_year(path, res, cfg=dict(self.state.cfg),
                              hourly=hourly)
            QMessageBox.information(
                self, tr('Sukses'), tr('Tersimpan:\n{path}').format(path=path))
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))

    # ============ Batch Multi-Site (Multi-Year) ============================ #
    def _build_batch_ui(self, iv):
        # ---- toggle enable (menampilkan/menyembunyikan seluruh section) ----
        self.chk_myb = QCheckBox(
            tr('Aktifkan Batch Multi-Site (Multi-Year)'))
        self.chk_myb.setToolTip(tr(
            'Tampilkan/sembunyikan bagian batch multi-site multi-year.'))
        self.chk_myb.toggled.connect(self._toggle_myb_section)
        iv.addWidget(self.chk_myb)

        box = QGroupBox(
            tr('Batch Multi-Site — Multi-Year (beberapa berkas data)'))
        self.myb_box = box
        bl = QVBoxLayout(box)
        _desc = QLabel(tr(
            'Jalankan simulasi multi-year untuk beberapa berkas data sekaligus. '
            'Nama site diambil dari nama berkas. Semua parameter mengikuti '
            'halaman Parameters (termasuk finance); PV/INV/BESS/PCS dapat '
            'dikhususkan per site di bawah. Berkas tanpa kolom PV ENetAC '
            'memakai profil PV aktif sebagai cadangan.'))
        _desc.setWordWrap(True)
        bl.addWidget(_desc)
        brow = QHBoxLayout()
        self.btn_myb_pick = QPushButton(tr('Pilih Berkas Data…'))
        self.btn_myb_pick.setProperty('flat', True)
        self.btn_myb_pick.setCursor(Qt.PointingHandCursor)
        self.btn_myb_pick.clicked.connect(self._pick_myb)
        self.btn_myb_run = QPushButton(tr('▶  Jalankan Batch Multi-Year'))
        self.btn_myb_run.setProperty('flat', True)
        self.btn_myb_run.setCursor(Qt.PointingHandCursor)
        self.btn_myb_run.setEnabled(False)
        self.btn_myb_run.clicked.connect(self._run_myb)
        self.btn_myb_cancel = QPushButton(tr('Batalkan Batch'))
        self.btn_myb_cancel.setProperty('flat', True)
        self.btn_myb_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_myb_cancel.setEnabled(False)
        self.btn_myb_cancel.clicked.connect(self._cancel_myb)
        self.btn_myb_export = QPushButton(tr('Export Batch…'))
        self.btn_myb_export.setProperty('flat', True)
        self.btn_myb_export.setCursor(Qt.PointingHandCursor)
        self.btn_myb_export.setEnabled(False)
        self.btn_myb_export.clicked.connect(self._export_myb)
        self.btn_myb_clear = QPushButton(tr('Bersihkan Batch'))
        self.btn_myb_clear.setProperty('flat', True)
        self.btn_myb_clear.setCursor(Qt.PointingHandCursor)
        self.btn_myb_clear.clicked.connect(self._clear_myb)
        for b in (self.btn_myb_pick, self.btn_myb_run, self.btn_myb_cancel,
                  self.btn_myb_export, self.btn_myb_clear):
            brow.addWidget(b)
        brow.addStretch(1)
        bl.addLayout(brow)

        # ---- Sumber koordinat PV tiap site (pilihan pengguna) ----
        crow = QHBoxLayout()
        crow.addWidget(QLabel(tr('Koordinat PV:')))
        self.myb_grp_coord = QButtonGroup(self)
        self.myb_rb_coord_home = QRadioButton(tr('Ikuti halaman Home'))
        self.myb_rb_coord_site = QRadioButton(
            tr('Per site dari Excel (unduh PVGIS)'))
        self.myb_rb_coord_home.setToolTip(tr(
            'Semua site memakai PV ENetAC dari berkas datanya '
            '(seperti biasa).'))
        self.myb_rb_coord_site.setToolTip(tr(
            'Tiap site memakai koordinat sendiri dari berkas Excel. PV '
            'diunduh dari PVGIS memakai tilt/azimuth, mounting, loss, dan '
            'year dari jendela Select Project Location.'))
        self.myb_grp_coord.addButton(self.myb_rb_coord_home)
        self.myb_grp_coord.addButton(self.myb_rb_coord_site)
        for rb in (self.myb_rb_coord_home, self.myb_rb_coord_site):
            rb.setCursor(Qt.PointingHandCursor)
            rb.toggled.connect(self._on_myb_coord_mode)
        crow.addWidget(self.myb_rb_coord_home)
        crow.addWidget(self.myb_rb_coord_site)
        self.btn_myb_coord_file = QPushButton(tr('Pilih Excel Koordinat…'))
        self.btn_myb_coord_file.setProperty('flat', True)
        self.btn_myb_coord_file.setCursor(Qt.PointingHandCursor)
        self.btn_myb_coord_file.clicked.connect(self._pick_myb_coords)
        self.btn_myb_coord_tmpl = QPushButton(tr('Template…'))
        self.btn_myb_coord_tmpl.setProperty('flat', True)
        self.btn_myb_coord_tmpl.setCursor(Qt.PointingHandCursor)
        self.btn_myb_coord_tmpl.setToolTip(tr(
            'Unduh templat Excel koordinat (kolom Site, Latitude, '
            'Longitude).'))
        self.btn_myb_coord_tmpl.clicked.connect(self._myb_coords_template)
        crow.addWidget(self.btn_myb_coord_file)
        crow.addWidget(self.btn_myb_coord_tmpl)
        crow.addStretch(1)
        bl.addLayout(crow)
        self.lbl_myb_coord = QLabel('')
        self.lbl_myb_coord.setObjectName('PageSub')
        self.lbl_myb_coord.setWordWrap(True)
        bl.addWidget(self.lbl_myb_coord)
        # pulihkan pilihan koordinat
        self._myb_coords = []
        cmode = str(self.state.cfg.get('myb_coord_mode', 'home') or 'home')
        (self.myb_rb_coord_site if cmode == 'persite'
         else self.myb_rb_coord_home).setChecked(True)
        cpath = self.state.cfg.get('myb_coords_path')
        if cpath and os.path.exists(cpath):
            try:
                self._myb_coords = read_site_coords(cpath)
            except Exception:
                self._myb_coords = []
        self._sync_myb_coord_ui()

        # ---- sizing per site (PV / INV / BESS / PCS) ----
        self.sp_box = QGroupBox(tr('Sizing per Site (PV / INV / BESS / PCS / Self Cons.)'))
        spv = QVBoxLayout(self.sp_box)
        _sp_hint = QLabel(tr(
            'Centang "Custom" pada sebuah site untuk memakai sizing khusus; '
            'bila tidak, site memakai nilai halaman Parameters. Anda juga dapat '
            'mengisi via Excel: kolom params (PV/INV/BESS/PCS/SELF CONS) × '
            'Unit × satu kolom per site (nama kolom = nama berkas data).'))
        _sp_hint.setWordWrap(True)
        spv.addWidget(_sp_hint)
        _sprow = QHBoxLayout()
        self.btn_sp_template = QPushButton(tr('Unduh Template Excel'))
        self.btn_sp_template.setProperty('flat', True)
        self.btn_sp_template.setCursor(Qt.PointingHandCursor)
        self.btn_sp_template.setToolTip(tr(
            'Simpan template Excel berisi kolom untuk tiap site (memakai nama '
            'berkas data) yang dapat Anda isi lalu impor kembali.'))
        self.btn_sp_template.clicked.connect(self._template_site_sizing)
        self.btn_sp_import = QPushButton(tr('Impor Sizing dari Excel…'))
        self.btn_sp_import.setProperty('flat', True)
        self.btn_sp_import.setCursor(Qt.PointingHandCursor)
        self.btn_sp_import.clicked.connect(self._import_site_sizing)
        _sprow.addWidget(self.btn_sp_template)
        _sprow.addWidget(self.btn_sp_import)
        _sprow.addStretch(1)
        spv.addLayout(_sprow)
        # grid dibungkus agar kolom rapat ke kiri (tidak melebar penuh layar)
        self.sp_grid = QGridLayout()
        self.sp_grid.setHorizontalSpacing(10)
        self.sp_grid.setVerticalSpacing(4)
        _spwrap = QHBoxLayout()
        _spwrap.addLayout(self.sp_grid)
        _spwrap.addStretch(1)            # dorong kolom ke kiri
        spv.addLayout(_spwrap)
        self.site_rows = []
        bl.addWidget(self.sp_box)
        self.sp_box.setVisible(False)     # muncul setelah berkas dipilih

        # ---- Base Profile Plant (kWp) — sumber pv_base_annual utk batch -------
        self.bpp_box = QGroupBox(tr('Base Profile Plant (kWp)'))
        bpv = QVBoxLayout(self.bpp_box)
        _bpp_hint = QLabel(tr(
            'Menentukan Base Profile Plant Size yang dipakai saat menskala '
            'profil PV tiap site: q = profil × (PV kWp ÷ Base).'))
        _bpp_hint.setWordWrap(True)
        bpv.addWidget(_bpp_hint)
        # Tiga mode SALING-EKSKLUSIF (interlock) — radio button dalam satu grup:
        # memilih satu otomatis mematikan yang lain.
        self.bpp_group = QButtonGroup(self)
        self.bpp_group.setExclusive(True)
        self.rb_bpp_follow = QRadioButton(tr(
            'Ikuti halaman Parameters ({v:,.2f} kWp)').format(
                v=float(self.state.cfg.get('pv_base_annual', 0.0))))
        self.rb_bpp_same = QRadioButton(tr('Sama dengan PV (kWp) tiap site'))
        self.rb_bpp_other = QRadioButton(tr('Nilai lain (kWp):'))
        for rb in (self.rb_bpp_follow, self.rb_bpp_same, self.rb_bpp_other):
            self.bpp_group.addButton(rb)
        bpv.addWidget(self.rb_bpp_follow)
        bpv.addWidget(self.rb_bpp_same)
        _crow = QHBoxLayout()
        _crow.addWidget(self.rb_bpp_other)
        self.ed_bpp_custom = QLineEdit()
        self.ed_bpp_custom.setFixedWidth(120)
        _crow.addWidget(self.ed_bpp_custom)
        _crow.addStretch(1)
        bpv.addLayout(_crow)
        bl.addWidget(self.bpp_box)
        # pulihkan mode (default: 'pv' -> Sama dengan PV kWp tiap site)
        mode = getattr(self.state, 'myb_base_mode', 'pv') or 'pv'
        {'params': self.rb_bpp_follow, 'pv': self.rb_bpp_same,
         'custom': self.rb_bpp_other}.get(mode, self.rb_bpp_same).setChecked(True)
        _bc = getattr(self.state, 'myb_base_custom', None)
        if _bc is None:
            _bc = self.state.cfg.get('pv_base_annual', 0.0)
        self.ed_bpp_custom.setText('{:g}'.format(float(_bc)))
        self.bpp_group.buttonToggled.connect(self._on_bpp_mode)
        self._sync_bpp_enabled()

        arow = QHBoxLayout()
        arow.addWidget(QLabel(tr('Site:')))
        self.myb_combo = QComboBox()
        self.myb_combo.setMinimumWidth(220)
        arow.addWidget(self.myb_combo)
        self.btn_myb_apply = QPushButton(tr('Terapkan Data Site Terpilih'))
        self.btn_myb_apply.setCursor(Qt.PointingHandCursor)
        self.btn_myb_apply.setEnabled(False)
        self.btn_myb_apply.setToolTip(tr(
            'Salin sizing PV/INV/BESS/PCS (charge & discharge) site ini ke '
            'halaman Parameters, dan muat profil Load/PV/Grid-nya sebagai data '
            'aktif di halaman Data (untuk drill-down Run Multi-Year / grafik '
            'per tahun).'))
        self.btn_myb_apply.clicked.connect(self._apply_myb_site)
        arow.addWidget(self.btn_myb_apply)
        arow.addStretch(1)
        bl.addLayout(arow)

        self.myb_bar = QProgressBar()
        self.myb_bar.setValue(0)
        bl.addWidget(self.myb_bar)
        self.lbl_myb = QLabel(tr('Belum ada berkas dipilih.'))
        self.lbl_myb.setObjectName('PageSub')
        self.lbl_myb.setWordWrap(True)
        bl.addWidget(self.lbl_myb)

        # Ringkasan headline site terpilih (untuk tombol Terapkan di atas)
        self.lbl_myb_sel = QLabel('')
        self.lbl_myb_sel.setObjectName('PageSub')
        self.lbl_myb_sel.setWordWrap(True)
        bl.addWidget(self.lbl_myb_sel)

        # Pilih DATA (parameter) yang ditampilkan pada tabel.
        drow = QHBoxLayout()
        drow.addWidget(QLabel(tr('Data:')))
        self.myb_metric_combo = QComboBox()
        self.myb_metric_combo.setMinimumWidth(260)
        self.myb_metric_combo.currentIndexChanged.connect(self._fill_myb_pivot)
        drow.addWidget(self.myb_metric_combo)
        drow.addStretch(1)
        bl.addLayout(drow)

        # Tabel per-DATA: kolom = seluruh site tersimulasi, baris = Tahun 1..akhir
        # (mengikuti project lifetime). Data ditentukan oleh dropdown "Data:".
        self.myb_year_table = CopyTableWidget()
        self.myb_year_table.setMinimumHeight(240)
        self.myb_year_table.setToolTip(tr(
            'Seret judul kolom untuk menggeser urutan site. Seret sel lalu '
            'Ctrl+C untuk menyalin ke Excel.'))
        # kolom site dapat digeser-geser (kolom Year tetap paling kiri)
        _hh = self.myb_year_table.horizontalHeader()
        _hh.setSectionsMovable(True)
        _hh.sectionMoved.connect(self._on_myb_section_moved)
        # urutan kolom tersimpan lintas ganti-metrik & rebuild bahasa
        self._myb_col_order = list(getattr(self.state, 'myb_col_order', []) or [])
        bl.addWidget(self.myb_year_table)
        # dropdown site -> perbarui ringkasan headline (untuk tombol Terapkan)
        self.myb_combo.currentIndexChanged.connect(self._on_myb_site_changed)
        iv.addWidget(box)
        box.setVisible(False)          # tersembunyi sampai toggle diaktifkan

        # pulihkan state batch (lintas rebuild bahasa)
        self.myb_paths = list(getattr(self.state, 'my_batch_paths', []) or [])
        self.myb_rows = list(getattr(self.state, 'my_batch_rows', []) or [])
        if self.myb_paths or self.myb_rows:
            self.chk_myb.setChecked(True)          # -> tampilkan section
        if self.myb_paths:
            self._rebuild_site_params()
            self.btn_myb_run.setEnabled(True)
            names = ', '.join(os.path.splitext(os.path.basename(p))[0]
                              for p in self.myb_paths)
            self.lbl_myb.setText(
                tr('{n} berkas dipilih:').format(n=len(self.myb_paths))
                + f' {names}')
        if self.myb_rows:
            try:
                self._fill_myb(self.myb_rows)
            except Exception:
                self.myb_rows = []

    def _toggle_myb_section(self, on):
        self.myb_box.setVisible(bool(on))

    # ---- koordinat PV per site (unduh PVGIS) --------------------------------
    def _myb_coord_persite(self) -> bool:
        return bool(getattr(self, 'myb_rb_coord_site', None)
                    and self.myb_rb_coord_site.isChecked())

    def _on_myb_coord_mode(self, checked=False):
        # tanggapi hanya toggled(True) agar cfg ditulis sekali per aksi.
        if not checked:
            return
        self.state.cfg['myb_coord_mode'] = (
            'persite' if self._myb_coord_persite() else 'home')
        self.state.db.save_project(self.state.cfg)
        self._sync_myb_coord_ui()

    def _sync_myb_coord_ui(self):
        on = self._myb_coord_persite()
        for w in (self.btn_myb_coord_file, self.btn_myb_coord_tmpl):
            w.setEnabled(on)
        if not on:
            self.lbl_myb_coord.setText(tr(
                'PV ENetAC diambil dari tiap berkas data (halaman Data).'))
            return
        if self._myb_coords:
            names = ', '.join(c[0] for c in self._myb_coords[:8])
            more = '' if len(self._myb_coords) <= 8 else ' …'
            self.lbl_myb_coord.setText(
                tr('{n} koordinat dimuat:').format(n=len(self._myb_coords))
                + f' {names}{more}')
        else:
            self.lbl_myb_coord.setText(tr(
                'Pilih berkas Excel koordinat (kolom Site, Latitude, '
                'Longitude).'))

    def _pick_myb_coords(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr('Pilih Excel Koordinat'), '',
            'Data (*.xlsx *.xls *.csv);;' + tr('Semua berkas (*)'))
        if not path:
            return
        try:
            coords = read_site_coords(path)
        except Exception as e:
            QMessageBox.critical(self, tr('Error'), str(e))
            return
        self._myb_coords = coords
        self.state.cfg['myb_coords_path'] = path
        self.state.db.save_project(self.state.cfg)
        self._sync_myb_coord_ui()

    def _myb_coords_template(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Simpan Template Koordinat'), 'site_coordinates.xlsx',
            'Excel (*.xlsx)')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Coordinates'
            ws.append([tr('Site'), tr('Latitude'), tr('Longitude')])
            for r in (('Site A', -8.409518, 115.188919),
                      ('Site B', -6.914744, 107.609810)):
                ws.append(list(r))
            for col, w in (('A', 22), ('B', 14), ('C', 14)):
                ws.column_dimensions[col].width = w
            wb.save(path)
        except Exception as e:
            QMessageBox.critical(self, tr('Error'), str(e))
            return
        QMessageBox.information(
            self, tr('Template'),
            tr('Template koordinat disimpan:') + f'\n{path}')

    def _rebuild_site_params(self):
        """Bangun baris input sizing per site sesuai berkas yang dipilih."""
        while self.sp_grid.count():
            it = self.sp_grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
        self.site_rows = []
        cfg = self.state.cfg
        d_pv = float(cfg.get('pv_kwp', 0.0))
        d_inv = float(cfg.get('pv_inv_kw', 0.0))
        d_bess = float(cfg.get('bess_kwh', 0.0))
        d_pcs = float(cfg.get('max_charge_kw', 0.0))
        d_sc = float(cfg.get('bess_self_cons_kw', 0.0) or 0.0)
        # lebar kolom tetap agar grid rapat & tidak melebar penuh layar
        COL_W = {0: 70, 1: 170, 2: 96, 3: 96, 4: 96, 5: 96, 6: 120}
        for c, w in COL_W.items():
            self.sp_grid.setColumnMinimumWidth(c, w)
            self.sp_grid.setColumnStretch(c, 0)
        self.sp_grid.setColumnStretch(7, 1)      # kolom kosong menyerap sisa
        heads = [tr('Custom'), tr('Site'), tr('PV (kWp)'), tr('INV (kW)'),
                 tr('BESS (kWh)'), tr('PCS (kW)'), tr('Self Cons. (kWh/h)')]
        for c, h in enumerate(heads):
            lab = QLabel(h)
            lab.setObjectName('PageSub')
            self.sp_grid.addWidget(lab, 0, c,
                                   Qt.AlignLeft | Qt.AlignVCenter)
        if not self.myb_paths:
            self.sp_box.setVisible(False)
            return
        for r, path in enumerate(self.myb_paths, start=1):
            site = os.path.splitext(os.path.basename(path))[0]
            chk = QCheckBox()
            chk.setToolTip(tr('Pakai sizing khusus untuk site ini.'))
            name = QLabel(site)
            name.setToolTip(path)
            pv = QLineEdit(f'{d_pv:g}')
            inv = QLineEdit(f'{d_inv:g}')
            bess = QLineEdit(f'{d_bess:g}')
            pcs = QLineEdit(f'{d_pcs:g}')
            sc = QLineEdit(f'{d_sc:g}')
            sc.setToolTip(tr('Self consumption BESS (kWh per jam) untuk site '
                             'ini — sama dengan parameter Battery → Self '
                             'Consumption.'))
            edits = (pv, inv, bess, pcs, sc)
            for e in edits:
                e.setFixedWidth(90)
                e.setEnabled(False)
            chk.toggled.connect(
                lambda on, es=edits: [e.setEnabled(bool(on)) for e in es])
            self.sp_grid.addWidget(chk, r, 0, Qt.AlignLeft | Qt.AlignVCenter)
            self.sp_grid.addWidget(name, r, 1)
            self.sp_grid.addWidget(pv, r, 2)
            self.sp_grid.addWidget(inv, r, 3)
            self.sp_grid.addWidget(bess, r, 4)
            self.sp_grid.addWidget(pcs, r, 5)
            self.sp_grid.addWidget(sc, r, 6)
            self.site_rows.append({'path': path, 'site': site, 'chk': chk,
                                   'pv': pv, 'inv': inv, 'bess': bess,
                                   'pcs': pcs, 'sc': sc})
        # pulihkan sizing tersimpan (dari .hpps) bila path cocok
        saved = {s.get('path'): s
                 for s in (getattr(self.state, 'my_batch_sizing', []) or [])}
        for row in self.site_rows:
            s = saved.get(row['path'])
            if not s:
                continue
            for key, edit in (('pv', row['pv']), ('inv', row['inv']),
                              ('bess', row['bess']), ('pcs', row['pcs']),
                              ('sc', row['sc'])):
                val = s.get(key)
                if val not in (None, ''):
                    edit.setText(str(val))
            if s.get('custom'):
                row['chk'].setChecked(True)      # aktifkan & buka field
        self.sp_box.setVisible(True)

    def _site_overrides(self):
        """Kumpulkan sizing khusus per site dari baris yang dicentang Custom.
        Kembalikan (overrides|None, error_str|None)."""
        ov = {}
        for r in self.site_rows:
            if not r['chk'].isChecked():
                continue
            try:
                d = {'pv_kwp': float(r['pv'].text()),
                     'pv_inv_kw': float(r['inv'].text()),
                     'bess_kwh': float(r['bess'].text()),
                     'pcs_kw': float(r['pcs'].text()),
                     'self_cons_kw': float(
                         str(r['sc'].text()).strip().replace(',', '.') or 0.0)}
            except (ValueError, TypeError):
                return None, r['site']
            if min(d.values()) < 0:
                return None, r['site']
            ov[r['path']] = d
        return ov, None

    # ---- sizing per site via Excel (format: params × Unit × kolom per site) --
    def _template_site_sizing(self):
        if not self.site_rows:
            QMessageBox.information(
                self, tr('Belum ada berkas'),
                tr('Pilih berkas data dulu agar kolom site terbentuk.'))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Simpan Template Sizing per Site'),
            'template_sizing_per_site.xlsx', 'Excel (*.xlsx)')
        if not path:
            return
        try:
            import pandas as pd
            cfg = self.state.cfg
            defaults = [float(cfg.get('pv_kwp', 0.0)),
                        float(cfg.get('pv_inv_kw', 0.0)),
                        float(cfg.get('bess_kwh', 0.0)),
                        float(cfg.get('max_charge_kw', 0.0)),
                        float(cfg.get('bess_self_cons_kw', 0.0) or 0.0)]
            data = {'params': ['PV', 'INV', 'BESS', 'PCS', 'SELF CONS'],
                    'Unit': ['kWp', 'kW', 'kWh', 'kW', 'kWh/h']}
            for r in self.site_rows:          # satu kolom per site (nama berkas)
                data[r['site']] = list(defaults)
            pd.DataFrame(data).to_excel(path, index=False)
            QMessageBox.information(
                self, tr('Template disimpan'),
                tr('Template tersimpan (nilai awal = halaman Parameters, silakan '
                   'sunting lalu impor):') + f'\n{path}')
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))

    def _import_site_sizing(self):
        if not self.site_rows:
            QMessageBox.information(
                self, tr('Belum ada berkas'),
                tr('Pilih berkas data dulu sebelum mengimpor sizing.'))
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr('Impor Sizing per Site'), '',
            'Excel (*.xlsx *.xls);;CSV (*.csv);;' + tr('Semua berkas (*)'))
        if not path:
            return
        try:
            import pandas as pd
            df = (pd.read_csv(path) if path.lower().endswith('.csv')
                  else pd.read_excel(path))
            cols = list(df.columns)
            if not cols:
                raise ValueError(tr('Berkas kosong.'))
            pcol = next((c for c in cols
                         if str(c).strip().lower() in
                         ('params', 'param', 'parameter')), cols[0])
            skip = {str(pcol).strip().lower(), 'unit', 'satuan'}
            site_cols = [c for c in cols if str(c).strip().lower() not in skip]
            # peta label param -> indeks baris
            labelmap = {}
            for idx, val in df[pcol].items():
                key = str(val).strip().upper()
                if key == 'INVERTER':
                    key = 'INV'
                if key.replace('_', ' ').replace('-', ' ') in (
                        'SELF CONS', 'SELF CONS.', 'SELF CONSUMPTION', 'SC',
                        'SELFCONS', 'SELF CONSUMPTION (KWH)'):
                    key = 'SC'          # baris opsional (berkas lama tanpa baris ini tetap sah)
                if key in ('PV', 'INV', 'BESS', 'PCS', 'SC'):
                    labelmap[key] = idx
            need = {'PV', 'INV', 'BESS', 'PCS'}
            if not need.issubset(labelmap):
                raise ValueError(tr(
                    'Kolom params wajib memuat baris PV, INV, BESS, PCS.'))
            row_by_site = {r['site'].strip().lower(): r for r in self.site_rows}
            applied, unmatched = [], []
            for sc in site_cols:
                sname = str(sc).strip()
                r = row_by_site.get(sname.lower())
                if r is None:
                    unmatched.append(sname)
                    continue
                fields = {'PV': r['pv'], 'INV': r['inv'],
                          'BESS': r['bess'], 'PCS': r['pcs'], 'SC': r['sc']}
                any_num = False
                for key, edit in fields.items():
                    if key not in labelmap:
                        continue
                    v = df.at[labelmap[key], sc]
                    try:
                        fv = float(v)
                    except (ValueError, TypeError):
                        continue
                    if fv != fv:              # NaN
                        continue
                    edit.setText(f'{fv:g}')
                    any_num = True
                if any_num:
                    r['chk'].setChecked(True)   # aktifkan sizing custom site ini
                    applied.append(r['site'])
            msg = tr('{n} site diterapkan dari Excel.').format(n=len(applied))
            if unmatched:
                msg += '\n\n' + tr(
                    'Kolom tanpa berkas data yang cocok (dilewati): ') \
                    + ', '.join(unmatched)
            QMessageBox.information(self, tr('Impor selesai'), msg)
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal impor'), str(e))

    def _pick_myb(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr('Pilih Berkas Data'), '',
            'Data (*.xlsx *.xls *.csv);;' + tr('Semua berkas (*)'))
        if not paths:
            return
        self.myb_paths = list(paths)
        self.state.my_batch_paths = list(paths)
        self._rebuild_site_params()
        names = ', '.join(os.path.splitext(os.path.basename(p))[0]
                          for p in paths)
        self.lbl_myb.setText(
            tr('{n} berkas dipilih:').format(n=len(paths)) + f' {names}')
        self.btn_myb_run.setEnabled(True)

    def _run_myb(self):
        # Cegah start ganda: bila worker batch (atau multi-year tunggal) masih
        # berjalan/berkas sedang dibaca, jangan mulai lagi. Menimpa self.mybw
        # saat thread lama masih hidup -> QThread di-GC saat running ->
        # 'Destroyed while running' -> Fatal Python error: Aborted (force close).
        if getattr(self, '_myb_reading', False):
            return
        if getattr(self, 'mybw', None) is not None and self.mybw.isRunning():
            return
        if getattr(self, '_myw', None) is not None and self._myw.isRunning():
            QMessageBox.information(
                self, tr('Sedang berjalan'),
                tr('Tunggu simulasi multi-year yang sedang berjalan selesai.'))
            return
        if not self.myb_paths:
            return
        overrides, bad = self._site_overrides()
        if bad is not None:
            QMessageBox.warning(
                self, tr('Nilai tidak valid'),
                tr('Sizing custom site "{s}" tidak valid.').format(s=bad))
            return
        base_mode, base_custom, base_err = self._base_pv_settings()
        if base_err:
            QMessageBox.warning(self, tr('Nilai tidak valid'), base_err)
            return

        # --- BACA SEMUA BERKAS DI THREAD UTAMA --------------------------------
        # pandas/openpyxl/lxml tidak aman dipanggil dari QThread di Windows
        # (memicu 'Windows fatal exception: access violation'). Maka berkas
        # dibaca di sini (thread GUI); worker hanya menghitung.
        self._myb_set_running(True)
        self._myb_reading = True
        loaded, read_errors = [], []
        try:
            n = len(self.myb_paths)
            self.myb_bar.setMaximum(n)
            self.myb_bar.setValue(0)
            for i, path in enumerate(self.myb_paths):
                if getattr(self, '_myb_cancel_read', False):
                    break
                site = os.path.splitext(os.path.basename(path))[0]
                self.lbl_myb.setText(
                    tr('Membaca berkas {i}/{n}: {site} …').format(
                        i=i + 1, n=n, site=site))
                self.myb_bar.setValue(i)
                QApplication.processEvents()
                try:
                    d = read_profile_file(path)
                    loaded.append({'site': site, 'path': path,
                                   'load': d.get('load'), 'pv': d.get('pv'),
                                   'grid': d.get('grid'), 'deg': d.get('deg'),
                                   'datetimes': d.get('datetimes')})
                except Exception as e:
                    read_errors.append((site, str(e)))
        finally:
            self._myb_reading = False
            self._myb_cancel_read = False

        if not loaded:
            self._myb_set_running(False)
            self._fill_myb([], read_errors)     # tampilkan galat baca / kosong
            return

        # --- Koordinat per-site: unduh PV dari PVGIS (thread utama) -----------
        if self._myb_coord_persite():
            if not self._myb_coords:
                self._myb_set_running(False)
                QMessageBox.warning(
                    self, tr('Koordinat PV'),
                    tr('Pilih berkas Excel koordinat lebih dulu, atau ganti '
                       'ke "Ikuti halaman Home".'))
                return
            self.lbl_myb.setText(tr('Mengunduh PV dari PVGIS per site …'))
            self.myb_bar.setMaximum(len(loaded))
            self.myb_bar.setValue(0)

            def _pvprog(i, total, site):
                self.myb_bar.setValue(i)
                self.lbl_myb.setText(
                    tr('Unduh PVGIS {i}/{n}: {site} …').format(
                        i=i + 1, n=total, site=site))
                QApplication.processEvents()

            try:
                loaded, pv_errors = batch_pvgis_pv(
                    loaded, self._myb_coords, dict(self.state.cfg),
                    progress=_pvprog)
            except Exception as e:
                self._myb_set_running(False)
                QMessageBox.critical(self, tr('Error'), str(e))
                return
            read_errors.extend(pv_errors)

        # --- WORKER hanya MENGHITUNG (tanpa baca Excel) -----------------------
        self.mybw = _MultiYearBatchWorker(
            loaded, dict(self.state.cfg), overrides=overrides,
            fallback_pv=self.state.pv_norm, read_errors=read_errors,
            base_mode=base_mode, base_custom=base_custom)
        self._register_worker(self.mybw)
        self.mybw.progress.connect(self._myb_progress)
        self.mybw.finished_ok.connect(self._myb_done)
        self.mybw.failed.connect(self._myb_fail)
        self.mybw.finished.connect(lambda: self._myb_set_running(False))
        self.myb_bar.setMaximum(len(loaded))
        self.myb_bar.setValue(0)
        self.mybw.start()

    def _myb_fail(self, m):
        self._myb_set_running(False)
        QMessageBox.critical(self, tr('Error'), m)

    # ---- Base Profile Plant (kWp) — 3 mode saling-eksklusif -------------------
    def _on_bpp_mode(self, *args):
        """Simpan mode terpilih & aktif/nonaktifkan kolom 'Nilai lain'."""
        if self.rb_bpp_follow.isChecked():
            self.state.myb_base_mode = 'params'
        elif self.rb_bpp_other.isChecked():
            self.state.myb_base_mode = 'custom'
        else:
            self.state.myb_base_mode = 'pv'
        self._sync_bpp_enabled()

    def _sync_bpp_enabled(self):
        # kolom nilai hanya aktif saat mode 'Nilai lain' dipilih
        self.ed_bpp_custom.setEnabled(self.rb_bpp_other.isChecked())

    def _base_pv_settings(self):
        """(mode, custom, error) untuk pv_base_annual batch.
        mode: 'params' | 'pv' | 'custom'."""
        if self.rb_bpp_follow.isChecked():
            return 'params', None, None
        if self.rb_bpp_other.isChecked():
            try:
                v = float(str(self.ed_bpp_custom.text()).replace(',', '.'))
            except (ValueError, TypeError):
                return None, None, tr('Nilai Base Profile Plant tidak valid.')
            if v <= 0:
                return None, None, tr('Nilai Base Profile Plant harus > 0.')
            self.state.myb_base_custom = v
            return 'custom', v, None
        return 'pv', None, None          # default: sama dengan PV kWp

    def _base_note(self):
        if self.rb_bpp_follow.isChecked():
            return tr('Base = Parameters')
        if self.rb_bpp_other.isChecked():
            return tr('Base = {v} kWp').format(v=self.ed_bpp_custom.text())
        return tr('Base = PV kWp')

    def sync_to_state(self):
        """Salin INPUT batch (sizing per-site & Base Profile Plant) ke state
        agar ikut tersimpan ke berkas .hpps. Dipanggil sebelum Save/Save As."""
        snap = []
        for r in getattr(self, 'site_rows', []):
            snap.append({'path': r['path'], 'site': r['site'],
                         'custom': bool(r['chk'].isChecked()),
                         'pv': r['pv'].text(), 'inv': r['inv'].text(),
                         'bess': r['bess'].text(), 'pcs': r['pcs'].text(),
                         'sc': r['sc'].text()})
        if snap:                         # jangan hapus bila grid belum dibangun
            self.state.my_batch_sizing = snap
        if hasattr(self, 'rb_bpp_follow'):
            self.state.myb_base_mode = (
                'params' if self.rb_bpp_follow.isChecked()
                else 'custom' if self.rb_bpp_other.isChecked() else 'pv')
            try:
                self.state.myb_base_custom = float(
                    str(self.ed_bpp_custom.text()).replace(',', '.'))
            except (ValueError, TypeError):
                pass

    def _myb_set_running(self, running: bool):
        """Kunci tombol yang mengubah keadaan selama batch berjalan — mencegah
        pengguna memicu start ganda / mengganti berkas di tengah proses."""
        self.btn_myb_run.setEnabled(not running)
        self.btn_myb_cancel.setEnabled(running)
        for name in ('btn_myb_pick', 'btn_myb_clear',
                     'btn_sp_template', 'btn_sp_import'):
            b = getattr(self, name, None)
            if b is not None:
                b.setEnabled(not running)
        for r in getattr(self, 'site_rows', []):
            r['chk'].setEnabled(not running)
        for rb in (getattr(self, 'rb_bpp_follow', None),
                   getattr(self, 'rb_bpp_same', None),
                   getattr(self, 'rb_bpp_other', None)):
            if rb is not None:
                rb.setEnabled(not running)
        if running:
            self.ed_bpp_custom.setEnabled(False)
        else:
            self._sync_bpp_enabled()

    def _cancel_myb(self):
        self._myb_cancel_read = True     # hentikan fase baca (thread utama)
        w = getattr(self, 'mybw', None)
        if w is not None:
            w.cancel_flag.set()
        self.btn_myb_cancel.setEnabled(False)
        self.lbl_myb.setText(tr('Membatalkan batch …'))

    def _myb_progress(self, i, total, site):
        self.myb_bar.setMaximum(total)
        self.myb_bar.setValue(i)
        self.lbl_myb.setText(
            tr('Menjalankan {i}/{n}: {site} …').format(i=i + 1, n=total,
                                                       site=site))

    def _myb_done(self):
        try:
            rows = list(getattr(getattr(self, 'mybw', None),
                                '_result_rows', []) or [])
            self._fill_myb(rows)
        except Exception as e:                      # pragma: no cover
            QMessageBox.critical(self, tr('Error'), str(e))

    def _myb_caption(self, item):
        """Baris ringkasan headline untuk site terpilih (untuk tombol Terapkan):
        sizing + LCOE/NPV/IRR/Payback/ROI/CAPEX lifetime."""
        res = item['res']
        f = res['finance']
        sz = item.get('sizing', {})
        return (
            tr('Site: {s}  ·  PV {pv:,.1f} kWp · INV {inv:,.1f} kW · '
               'BESS {bess:,.1f} kWh · PCS {pcs:,.1f} kW  ·  Lifetime {yr} th')
            .format(s=item['site'],
                    pv=sz.get('pv_kwp', 0.0), inv=sz.get('kw_inv', 0.0),
                    bess=sz.get('bess_kwh', 0.0), pcs=sz.get('pcs_kw', 0.0),
                    yr=len(res['years']))
            + (tr('  ·  Self Cons. {sc:,.2f} kWh/h').format(
                sc=float(sz.get('self_cons_kw', 0.0) or 0.0))
               if float(sz.get('self_cons_kw', 0.0) or 0.0) > 0 else '')
            + '\n'
            + tr('LCOE {lcoe:,.0f} Rp/kWh · NPV {npv:,.0f} Rp · IRR {irr:,.1f}% '
                 '· Payback {pb:,.1f} th · ROI {roi:,.1f}% · CAPEX {cap:,.0f} Rp')
            .format(lcoe=float(f['lcoe']), npv=float(f['npv']),
                    irr=float(f['irr']) * 100, pb=float(f['payback_years']),
                    roi=float(f['roi']) * 100, cap=float(f['capex'])))

    def _on_myb_site_changed(self, idx):
        """Perbarui ringkasan headline site terpilih (untuk tombol Terapkan)."""
        rows = getattr(self, 'myb_rows', []) or []
        self.lbl_myb_sel.setText(
            self._myb_caption(rows[idx]) if 0 <= idx < len(rows) else '')

    def _myb_metric_list(self):
        """Daftar metrik (nama, unit, desimal) = kolom tabel per-tahun tanpa
        'Tahun'. Dipakai untuk mengisi dropdown 'Data:' dan tabel pivot."""
        rows = getattr(self, 'myb_rows', []) or []
        if not rows:
            return []
        cols = self._year_table_cols(rows[0]['res'], self.state.cfg)
        return [(n, u, d) for (n, u, _a, d) in cols[1:]]      # buang 'Tahun'

    def _fill_myb_pivot(self, *args):
        """Tabel per-DATA: kolom = seluruh site, baris = Tahun 1..akhir, isi =
        metrik terpilih pada dropdown 'Data:'. Nilai mentah disimpan di UserRole
        agar tersalin bersih ke Excel."""
        rows = getattr(self, 'myb_rows', []) or []
        t = self.myb_year_table
        t.clearContents()
        if not rows:
            t.setRowCount(0)
            t.setColumnCount(0)
            return
        metrics = self._myb_metric_list()
        if not metrics:
            return
        m = self.myb_metric_combo.currentIndex()
        if not (0 <= m < len(metrics)):
            m = 0
        _name, unit, dec = metrics[m]
        cfg = self.state.cfg
        site_names = [r['site'] for r in rows]        # tanpa '*'
        # array metrik terpilih untuk tiap site (kolom m+1 pada _year_table_cols)
        site_arrays = [np.asarray(self._year_table_cols(r['res'], cfg)[m + 1][2],
                                  float).reshape(-1) for r in rows]
        yrs = max((len(r['res']['years']) for r in rows), default=0)
        t.setColumnCount(1 + len(site_names))
        t.setRowCount(yrs)
        u = f'\n({unit})' if unit else ''
        t.setHorizontalHeaderLabels(
            [tr('Tahun')] + [f'{s}{u}' for s in site_names])
        hh = t.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignCenter | Qt.TextWordWrap)
        for i in range(yrs):
            c0 = QTableWidgetItem(str(i + 1))
            c0.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            c0.setData(Qt.UserRole, str(i + 1))
            t.setItem(i, 0, c0)
            for js, arr in enumerate(site_arrays):
                v = float(arr[i]) if i < len(arr) else float('nan')
                cell = QTableWidgetItem(f'{v:,.{dec}f}')
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                cell.setData(Qt.UserRole, f'{v:.{dec}f}')
                t.setItem(i, js + 1, cell)
        fit_table_columns(t, min_w=60, max_w=200, fill=False)
        # setColumnCount mengatur ulang urutan ke logis -> terapkan lagi urutan
        # kolom pilihan pengguna (site tetap urut, Year di kiri).
        self._apply_myb_col_order()

    def _apply_myb_col_order(self):
        """Susun kolom site sesuai urutan simpan (self._myb_col_order); Year
        selalu di visual 0. Dipanggil tiap tabel diisi ulang."""
        order = getattr(self, '_myb_col_order', None)
        rows = getattr(self, 'myb_rows', []) or []
        t = self.myb_year_table
        if not order or t.columnCount() <= 1:
            return
        name_to_logical = {r['site']: j + 1 for j, r in enumerate(rows)}
        hh = t.horizontalHeader()
        self._myb_reorder_guard = True
        try:
            if hh.visualIndex(0) != 0:            # Year -> paling kiri
                hh.moveSection(hh.visualIndex(0), 0)
            target = 1
            for site in order:
                lc = name_to_logical.get(site)
                if lc is None:
                    continue
                cur = hh.visualIndex(lc)
                if cur != target:
                    hh.moveSection(cur, target)
                target += 1
        finally:
            self._myb_reorder_guard = False

    def _on_myb_section_moved(self, *args):
        """Pengguna menggeser kolom -> simpan urutan baru & jaga Year di kiri."""
        if getattr(self, '_myb_reorder_guard', False):
            return
        t = self.myb_year_table
        hh = t.horizontalHeader()
        if hh.visualIndex(0) != 0:               # Year selalu paling kiri
            self._myb_reorder_guard = True
            try:
                hh.moveSection(hh.visualIndex(0), 0)
            finally:
                self._myb_reorder_guard = False
        rows = getattr(self, 'myb_rows', []) or []
        site_by_logical = {j + 1: r['site'] for j, r in enumerate(rows)}
        order = [site_by_logical[hh.logicalIndex(v)]
                 for v in range(t.columnCount())
                 if hh.logicalIndex(v) in site_by_logical]
        self._myb_col_order = order
        self.state.myb_col_order = list(order)   # bertahan lintas metrik/rebuild

    def _fill_myb(self, rows, errors=None):
        self.myb_rows = rows
        self.state.my_batch_rows = rows
        self.myb_bar.setValue(self.myb_bar.maximum())
        errs = (errors if errors is not None
                else getattr(getattr(self, 'mybw', None), 'errors', []) or [])
        if not rows:
            for combo in (self.myb_combo, self.myb_metric_combo):
                combo.blockSignals(True)
                combo.clear()
                combo.blockSignals(False)
            self.myb_year_table.clearContents()
            self.myb_year_table.setRowCount(0)
            self.myb_year_table.setColumnCount(0)
            self.lbl_myb_sel.setText('')
            self.btn_myb_export.setEnabled(False)
            self.btn_myb_apply.setEnabled(False)
            if errs:
                detail = '\n'.join(f'• {s}: {m}' for s, m in errs)
                self.lbl_myb.setText(tr('Semua site gagal.'))
                QMessageBox.warning(self, tr('Batch selesai dengan galat'),
                                    tr('Semua site gagal.') + '\n\n' + detail)
            else:
                self.lbl_myb.setText(tr('Batch dibatalkan.'))
            return
        self.btn_myb_export.setEnabled(True)
        self.btn_myb_apply.setEnabled(True)
        # urutan kolom: pertahankan bila set site sama, selain itu default
        sites_now = [r['site'] for r in rows]
        saved = getattr(self.state, 'myb_col_order', None)
        if saved and set(saved) == set(sites_now):
            self._myb_col_order = [s for s in saved if s in sites_now]
        else:
            self._myb_col_order = list(sites_now)
            self.state.myb_col_order = list(sites_now)
        # dropdown site (untuk tombol Terapkan) — tanpa '*'
        self.myb_combo.blockSignals(True)
        self.myb_combo.clear()
        self.myb_combo.addItems([r['site'] for r in rows])
        self.myb_combo.blockSignals(False)
        # dropdown data/metrik (untuk tabel pivot)
        metrics = self._myb_metric_list()
        prev = self.myb_metric_combo.currentIndex()
        self.myb_metric_combo.blockSignals(True)
        self.myb_metric_combo.clear()
        self.myb_metric_combo.addItems(
            [f'{n} ({u})' if u else n for (n, u, _d) in metrics])
        if 0 <= prev < len(metrics):
            self.myb_metric_combo.setCurrentIndex(prev)
        self.myb_metric_combo.blockSignals(False)
        note = (' · ' + tr('{n} site gagal (dilewati)').format(n=len(errs))
                if errs else '')
        self.lbl_myb.setText(
            tr('Selesai — {n} site tersimulasi.').format(n=len(rows))
            + '  ·  ' + self._base_note() + note
            + '  ·  ' + tr('pilih Data pada dropdown; kolom = site, baris = '
                           'tahun.'))
        self.myb_combo.setCurrentIndex(0)
        self._on_myb_site_changed(0)     # ringkasan headline
        self._fill_myb_pivot()           # tabel pivot
        if errs:
            detail = '\n'.join(f'• {s}: {m}' for s, m in errs)
            QMessageBox.warning(
                self, tr('Sebagian site gagal'),
                tr('{n} site dilewati karena galat:').format(n=len(errs))
                + '\n\n' + detail)

    def _register_worker(self, w):
        """Simpan referensi worker agar TIDAK di-GC selama masih berjalan.
        Menimpa self.mybw/self._myw saja tidak cukup: bila referensi lama hilang
        saat thread masih hidup, QThread di-destroy -> Fatal error: Aborted."""
        lst = getattr(self, '_live_workers', None)
        if lst is None:
            lst = self._live_workers = []
        # buang yang sudah selesai agar daftar tak menumpuk
        self._live_workers = [x for x in lst
                              if x is not None and x.isRunning()]
        self._live_workers.append(w)

    def _all_workers(self):
        ws = list(getattr(self, '_live_workers', []) or [])
        for w in (getattr(self, '_myw', None), getattr(self, 'mybw', None)):
            if w is not None and w not in ws:
                ws.append(w)
        return ws

    def is_busy(self) -> bool:
        return any(w is not None and w.isRunning()
                   for w in self._all_workers())

    def stop_workers(self):
        """Hentikan SEMUA worker (multi-year tunggal & batch, termasuk yang
        sempat ter-orphan) sebelum halaman/aplikasi ditutup — mencegah
        'QThread destroyed while running' (force close)."""
        ws = self._all_workers()
        for w in ws:                       # minta berhenti dulu (kooperatif)
            if w is None or not w.isRunning():
                continue
            try:
                if hasattr(w, 'cancel_flag'):
                    w.cancel_flag.set()
            except Exception:
                pass
        for w in ws:                       # lalu tunggu; paksa bila membandel
            if w is None or not w.isRunning():
                continue
            try:
                if not w.wait(8000):
                    w.terminate()          # upaya terakhir: cegah abort()
                    w.wait(2000)
            except Exception:
                pass

    def _site_coords(self, site):
        """Koordinat (lat, lon) site dari berkas koordinat yang dimuat, cocok
        via NAMA (case-insensitive). None bila tak ditemukan."""
        key = str(site).strip().lower()
        for nm, la, lo in (getattr(self, '_myb_coords', None) or []):
            if str(nm).strip().lower() == key:
                return float(la), float(lo)
        return None

    def _apply_myb_site(self):
        """Terapkan site terpilih ke seluruh aplikasi:
        (1) salin sizing PV/INV/BESS/PCS (charge & discharge max) -> halaman
            Parameters (cfg), dan
        (2) muat profil Load/PV/Grid berkasnya -> halaman Data (data aktif).
        Berkas dibaca & divalidasi lebih dulu agar tak ada penerapan separuh."""
        i = self.myb_combo.currentIndex()
        if not self.myb_rows or not (0 <= i < len(self.myb_rows)):
            return
        item = self.myb_rows[i]
        try:
            # --- baca & validasi profil dulu; bila gagal, jangan ubah apa pun --
            d = read_profile_file(item['path'])
            load, pv, gs = d.get('load'), d.get('pv'), d.get('grid')
            if load is None:
                raise ImportError_(tr('kolom Load tidak ditemukan.'))
            n = len(load)
            if pv is None:
                pv = self.state.pv_norm
            if gs is None:
                gs = (np.ones(n) if self.state.cfg.get('grid_enabled', True)
                      else np.zeros(n))

            # --- (1) salin sizing site -> halaman Parameters ------------------
            sz = item.get('sizing', {}) or {}
            cfg_upd = {}
            for src, dst in (('pv_kwp', 'pv_kwp'),
                             ('kw_inv', 'pv_inv_kw'),
                             ('bess_kwh', 'bess_kwh')):
                if sz.get(src) is not None:
                    cfg_upd[dst] = float(sz[src])
            if sz.get('pcs_kw') is not None:      # PCS = charge & discharge max
                cfg_upd['max_charge_kw'] = float(sz['pcs_kw'])
                cfg_upd['max_discharge_kw'] = float(sz['pcs_kw'])
            if sz.get('self_cons_kw') is not None:   # self consumption BESS
                cfg_upd['bess_self_cons_kw'] = float(sz['self_cons_kw'])
            # Base Profile Plant Size sesuai toggle (agar Run Multi-Year setelah
            # Apply mereproduksi angka batch untuk site ini).
            base_mode, base_custom, base_err = self._base_pv_settings()
            if not base_err:
                if base_mode == 'pv' and cfg_upd.get('pv_kwp', 0.0) > 0:
                    cfg_upd['pv_base_annual'] = float(cfg_upd['pv_kwp'])
                elif base_mode == 'custom' and base_custom:
                    cfg_upd['pv_base_annual'] = float(base_custom)
                # 'params' -> biarkan pv_base_annual halaman Parameters
            # Site Name & koordinat -> halaman Home (koordinat bila berkas
            # koordinat dimuat & namanya cocok).
            cfg_upd['site_name'] = item['site']
            co = self._site_coords(item['site'])
            if co is not None:
                cfg_upd['latitude'] = round(co[0], 6)
                cfg_upd['longitude'] = round(co[1], 6)
            if cfg_upd:
                # update_cfg -> config_changed -> halaman Parameters refresh
                self.state.update_cfg(cfg_upd)

            # --- (2) muat profil site -> halaman Data (data aktif) ------------
            # profiles_changed -> halaman Data/Home/Dashboard refresh
            self.state.set_profiles(d.get('datetimes'), load, pv, gs)

            home_line = (tr('• Site Name & koordinat disalin ke halaman Home.')
                         if co is not None
                         else tr('• Site Name disalin ke halaman Home.'))
            QMessageBox.information(
                self, tr('Site diterapkan'),
                tr('Site "{s}" diterapkan:\n'
                   '• Sizing PV/INV/BESS/PCS (charge & discharge) disalin ke '
                   'halaman Parameters.\n'
                   '• Profil Load/PV/Grid dimuat sebagai data aktif di halaman '
                   'Data.\n{home}\n\nJalankan Run Multi-Year untuk rincian per '
                   'tahun.').format(s=item['site'], home=home_line))
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))

    def _export_myb(self):
        if not self.myb_rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Simpan Batch Multi-Year'),
            export_filename(self.state.cfg, 'batch_multi_year'),
            'Excel (*.xlsx);;CSV (*.csv)')
        if not path:
            return
        try:
            export_batch_multi_year(path, self.myb_rows,
                                    cfg=dict(self.state.cfg))
            QMessageBox.information(
                self, tr('Sukses'), tr('Tersimpan:\n{path}').format(path=path))
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))

    def _clear_myb(self):
        if not (self.myb_rows or self.myb_paths):
            return
        self.myb_paths = []
        self.myb_rows = []
        self.state.my_batch_paths = []
        self.state.my_batch_rows = []
        self._myb_col_order = []
        self.state.myb_col_order = []
        for combo in (self.myb_combo, self.myb_metric_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.blockSignals(False)
        self.myb_year_table.clearContents()
        self.myb_year_table.setRowCount(0)
        self.myb_year_table.setColumnCount(0)
        self.lbl_myb_sel.setText('')
        self._rebuild_site_params()          # kosongkan grid sizing per site
        self.btn_myb_run.setEnabled(False)
        self.btn_myb_export.setEnabled(False)
        self.btn_myb_apply.setEnabled(False)
        self.myb_bar.setValue(0)
        self.lbl_myb.setText(tr('Belum ada berkas dipilih.'))
