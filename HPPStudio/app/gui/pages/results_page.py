"""Halaman Results — KPI teknis & finansial + cash flow (simulasi tahun-1).

Simulasi Multi-Year (project lifetime) & batch multi-site kini berada di
halaman terpisah 'Multi-Year' (app/gui/pages/multi_year_page.py).
"""
from __future__ import annotations
import numpy as np

from ...config.i18n import tr
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QFileDialog, QMessageBox, QGroupBox, QGridLayout,
    QDialog, QCheckBox, QDialogButtonBox)
import pyqtgraph as pg

from ..theme import SERIES_COLORS
from ..widgets import KPICard
from ..plotutil import no_wheel_zoom, CursorReadout
from ...data.exporter import export_simulation, export_filename
# pdf_report diimpor malas di dalam _report() agar reportlab tidak menjadi
# syarat mutlak start-up aplikasi (bila belum terpasang, hanya fitur PDF ini
# yang nonaktif — sisanya tetap jalan).


TECH_ROWS = [
    ('annual_load_kwh', 'Annual Load', 'kWh', 0),
    ('annual_pv_generation_kwh', 'Annual PV Generation', 'kWh', 0),
    ('annual_pv_inverter_out_kwh', 'PV Inverter Output', 'kWh', 0),
    ('annual_battery_charge_kwh', 'Battery Charge', 'kWh', 0),
    ('pv_charge_kwh', 'BESS Charge from PV', 'kWh', 0),
    ('grid_charge_kwh', 'BESS Charge from Grid', 'kWh', 0),
    ('deg_charge_kwh', 'BESS Charge from DEG', 'kWh', 0),
    ('annual_battery_discharge_kwh', 'Battery Discharge', 'kWh', 0),
    ('battery_throughput_kwh', 'Battery Throughput', 'kWh', 0),
    ('battery_cycles', 'Battery Cycles', 'siklus', 1),
    ('bess_self_consumption_kwh', 'BESS Self Consumption', 'kWh', 0),
    ('renewable_fraction', 'Renewable Fraction', '%', 1),
    ('pv_excess_kwh', 'Curtailment', 'kWh', 0),
    ('pv_excess_ratio', 'PV Curtailment', '%', 1),
    ('diesel_runtime_h', 'Diesel Runtime', 'jam', 0),
    ('diesel_energy_kwh', 'Diesel Energy', 'kWh', 0),
    ('diesel_fuel_l', 'Diesel Fuel', 'L', 0),
    ('diesel_avg_loading', 'Diesel Avg Loading', '%', 1),
    ('soc_min', 'SOC Min', '%', 1),
    ('soc_max', 'SOC Max', '%', 1),
    ('grid_import_kwh', 'Grid Import', 'kWh', 0),
    ('grid_export_kwh', 'Grid Export', 'kWh', 0),
    ('unserved_kwh', 'Unserved Energy', 'kWh', 0),
]
FIN_ROWS = [
    ('capex', 'CAPEX', 'Rp', 0),
    ('opex_year1', 'OPEX Tahun-1', 'Rp', 0),
    ('baseline_cost_year1', 'Baseline Cost Th-1', 'Rp', 0),
    ('savings_year1', 'Penghematan Th-1', 'Rp', 0),
    ('lcoe', 'LCOE', 'Rp/kWh', 0),
    ('npv', 'NPV', 'Rp', 0),
    ('irr', 'IRR', '%', 1),
    ('roi', 'ROI', '%', 1),
    ('payback_years', 'Payback', 'tahun', 1),
]
PCT_KEYS = {'renewable_fraction', 'pv_excess_ratio',
            'diesel_avg_loading', 'soc_min',
            'soc_max', 'irr', 'roi'}


class ResultsPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        t = QLabel(tr('Results')); t.setObjectName('PageTitle')
        head.addWidget(t); head.addStretch(1)
        self.btn_xlsx = QPushButton(tr('Export Excel'))
        self.btn_xlsx.clicked.connect(self._export_xlsx)
        self.btn_rep = QPushButton(tr('Generate Feasibility Study'))
        self.btn_rep.setToolTip(tr(
            'Susun laporan studi kelayakan profesional (PDF atau Word/DOCX; '
            'teknis + finansial + sensitivitas; bagian Multi-Year disertakan '
            'bila sudah dijalankan).'))
        self.btn_rep.clicked.connect(self._report)
        self.btn_arch = QPushButton(tr('Design Architecture…'))
        self.btn_arch.setProperty('flat', True)
        self.btn_arch.setToolTip(tr(
            'Rancang arsitektur sistem dari nol atau impor gambar (PNG/JPG/PDF); '
            'sistem menggambar ulang secara profesional untuk laporan studi '
            'kelayakan.'))
        self.btn_arch.clicked.connect(self._design_arch)
        self.btn_clear = QPushButton(tr('Bersihkan Hasil'))
        self.btn_clear.setProperty('flat', True)
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setToolTip(tr(
            'Hapus hasil simulasi beserta seluruh grafiknya.'))
        self.btn_clear.clicked.connect(self._clear_results)
        head.addWidget(self.btn_xlsx); head.addWidget(self.btn_arch)
        head.addWidget(self.btn_rep)
        head.addWidget(self.btn_clear)
        lay.addLayout(head)
        self.lbl = QLabel(tr('Belum ada hasil — jalankan simulasi di Dashboard.'))
        self.lbl.setObjectName('PageSub')
        lay.addWidget(self.lbl)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); iv = QVBoxLayout(inner)

        self.tech_box = QGroupBox(tr('KPI Teknis'))
        self.tech_grid = QGridLayout(self.tech_box)
        self.tech_grid.setSpacing(6)
        self.tech_cards = {}
        for i, (key, label, unit, _d) in enumerate(TECH_ROWS):
            c = KPICard(tr(label), '-', tr(unit))
            self.tech_cards[key] = c
            self.tech_grid.addWidget(c, i // 6, i % 6)
        iv.addWidget(self.tech_box)

        self.fin_box = QGroupBox(tr('KPI Finansial'))
        self.fin_grid = QGridLayout(self.fin_box)
        self.fin_grid.setSpacing(6)
        self.fin_cards = {}
        for i, (key, label, unit, _d) in enumerate(FIN_ROWS):
            c = KPICard(tr(label), '-', tr(unit))
            self.fin_cards[key] = c
            self.fin_grid.addWidget(c, i // 6, i % 6)
        iv.addWidget(self.fin_box)

        cf_box = QGroupBox(tr('Cash Flow Kumulatif (savings vs baseline)'))
        cfl = QVBoxLayout(cf_box)
        self.cf_plot = pg.PlotWidget()
        no_wheel_zoom(self.cf_plot)
        self.cf_plot.showGrid(x=True, y=True, alpha=0.2)
        self.cf_plot.setLabel('bottom', tr('Tahun'))
        self.cf_plot.setLabel('left', tr('Rp'))
        self.cf_plot.setMinimumHeight(260)
        self.lbl_cf = QLabel(''); self.lbl_cf.setObjectName('PageSub')
        cfl.addWidget(self.lbl_cf)
        cfl.addWidget(self.cf_plot)
        self._cur_cf = CursorReadout(self.cf_plot, self.lbl_cf,
                                     self._cf_at)
        iv.addWidget(cf_box)

        iv.addStretch(1)

        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        state.simulation_done.connect(self._update)
        state.results_cleared.connect(self._on_cleared)
        if state.last_result:
            try:
                self._update(state.last_result)
            except Exception:
                pass

    # ----------------------------------------------------------
    def _update(self, res: dict):
        self.lbl.setText(tr('Hasil simulasi terbaru.'))
        k = res['kpi']
        for key, _l, _u, dec in TECH_ROWS:
            v = k.get(key)
            if v is None:
                continue
            v = float(np.asarray(v).reshape(-1)[0])
            if key in PCT_KEYS:
                v *= 100.0
            self.tech_cards[key].set_value(f'{v:,.{dec}f}')
        fin = res.get('finance')
        self.fin_box.setVisible(fin is not None)
        if fin:
            for key, _l, _u, dec in FIN_ROWS:
                v = fin.get(key)
                if v is None:
                    continue
                v = float(np.asarray(v).reshape(-1)[0])
                if key in PCT_KEYS:
                    v *= 100.0
                self.fin_cards[key].set_value(f'{v:,.{dec}f}')
            self.cf_plot.clear()
            flows = np.asarray(fin['cashflow'], float).reshape(-1)
            cum = np.cumsum(flows)
            x = np.arange(len(flows))
            self._cf_vals = list(cum)
            self.cf_plot.addItem(pg.BarGraphItem(
                x=x, height=cum, width=0.7,
                brushes=[SERIES_COLORS['deg'] if v < 0 else
                         SERIES_COLORS['pv'] for v in cum]))
            self.cf_plot.addLine(y=0, pen=pg.mkPen('#9CA3AF', width=1))

    # ----------------------------------------------------------
    def _need_result(self):
        if not self.state.last_result:
            QMessageBox.information(self, tr('Belum ada hasil'),
                                    tr('Jalankan simulasi terlebih dahulu.'))
            return None
        return self.state.last_result

    def _export_xlsx(self):
        res = self._need_result()
        if not res:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Simpan Excel'),
            export_filename(self.state.cfg, tr('hasil_simulasi')),
            'Excel (*.xlsx)')
        if not path:
            return
        try:
            export_simulation(path, res, self.state.datetimes,
                              cfg=dict(self.state.cfg))
            QMessageBox.information(
                self, tr('Sukses'), tr('Tersimpan:\n{path}').format(path=path))
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))

    def _design_arch(self):
        """Buka editor arsitektur sistem (gaya draw.io + impor gambar)."""
        try:
            from ..arch_editor import ArchEditorDialog
        except ImportError as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))
            return
        dlg = ArchEditorDialog(self.state, self)
        dlg.exec()

    def _ask_report_aspects(self):
        """Dialog checkbox: pilih aspek (Teknis / Finansial) yang ditampilkan.
        Kembalikan (inc_tech, inc_fin) atau None bila dibatalkan."""
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('Aspek Laporan'))
        lay = QVBoxLayout(dlg)
        lbl = QLabel(tr('Pilih aspek yang ingin ditampilkan pada laporan '
                        'studi kelayakan:'))
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        chk_t = QCheckBox(tr('Aspek Teknis')); chk_t.setChecked(True)
        chk_f = QCheckBox(tr('Aspek Finansial')); chk_f.setChecked(True)
        lay.addWidget(chk_t)
        lay.addWidget(chk_f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        lay.addWidget(bb)
        ok_btn = bb.button(QDialogButtonBox.Ok)

        def _sync():
            ok_btn.setEnabled(chk_t.isChecked() or chk_f.isChecked())
        chk_t.toggled.connect(_sync)
        chk_f.toggled.connect(_sync)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.Accepted:
            return None
        return bool(chk_t.isChecked()), bool(chk_f.isChecked())

    def _report(self):
        res = self._need_result()
        if not res:
            return
        aspects = self._ask_report_aspects()
        if aspects is None:
            return
        inc_tech, inc_fin = aspects
        path, selected = QFileDialog.getSaveFileName(
            self, tr('Simpan Studi Kelayakan'),
            export_filename(self.state.cfg, tr('studi_kelayakan'), ext='pdf'),
            'PDF (*.pdf);;Word Document (*.docx)')
        if not path:
            return
        low = path.lower()
        if low.endswith('.docx'):
            fmt = 'docx'
        elif low.endswith('.pdf'):
            fmt = 'pdf'
        else:                       # tak ada ekstensi -> ikuti filter dipilih
            fmt = 'docx' if 'docx' in (selected or '').lower() else 'pdf'
            path += '.docx' if fmt == 'docx' else '.pdf'
        multi = getattr(self.state, 'multi_result', None)
        try:
            if fmt == 'docx':
                from ...reports.docx_report import build_feasibility_docx as _build
            else:
                from ...reports.pdf_report import build_feasibility_pdf as _build
            _build(path, dict(self.state.cfg), res,
                   datetimes=self.state.datetimes, multi_result=multi,
                   include_technical=inc_tech, include_financial=inc_fin)
            extra = ('' if multi else
                     '\n\n' + tr('Catatan: jalankan Multi-Year untuk '
                                 'menyertakan proyeksi lifetime terperinci.'))
            QMessageBox.information(
                self, tr('Sukses'),
                tr('Laporan tersimpan:') + f'\n{path}' + extra)
        except ImportError:
            QMessageBox.critical(
                self, tr('Modul laporan belum terpasang'),
                tr('Pustaka pembuat laporan (reportlab untuk PDF / python-docx '
                   'untuk Word) belum terpasang di environment ini. Jalankan '
                   'install_deps.bat (atau run_dev.bat) untuk memasangnya, lalu '
                   'buka aplikasi kembali.'))
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))

    def _clear_results(self):
        if not self.state.last_result:
            return
        if QMessageBox.question(
                self, tr('Bersihkan Hasil'),
                tr('Hapus hasil simulasi beserta seluruh grafiknya?')) \
                != QMessageBox.Yes:
            return
        self.state.last_result = None
        self.clear_view()
        self.state.results_cleared.emit('simulation')

    def _on_cleared(self, kind):
        if kind in ('simulation', 'all'):
            self.clear_view()

    def clear_view(self):
        """Kosongkan KPI & grafik cash flow hasil simulasi."""
        for d in (self.tech_cards, self.fin_cards):
            for c in d.values():
                c.set_value('-')
        try:
            self.cf_plot.clear()
        except Exception:
            pass
        self._cf_vals = None
        if hasattr(self, 'lbl_cf'):
            self.lbl_cf.setText('')
        self.lbl.setText(
            tr('Belum ada hasil — jalankan simulasi di Dashboard.'))

    def _cf_at(self, x):
        v = getattr(self, '_cf_vals', None)
        if v is None or not len(v):
            return ''
        i = int(round(x))
        if i < 0 or i >= len(v):
            return ''
        return (tr('Tahun') + f' {i}  —  Rp {v[i]:,.0f}')
