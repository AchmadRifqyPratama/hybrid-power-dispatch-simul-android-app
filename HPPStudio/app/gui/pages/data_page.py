"""Halaman Data — import Load Profile, PV ENetAC, Grid Status dari Excel/CSV."""
from __future__ import annotations
import numpy as np

from ...config.i18n import tr
from ..plotutil import no_wheel_zoom
from PySide6.QtCore import Qt, QLocale
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QFileDialog, QMessageBox,
                               QGroupBox, QFormLayout, QGridLayout,
                               QDoubleSpinBox, QButtonGroup, QScrollArea,
                               QSizePolicy, QRadioButton)
import pyqtgraph as pg

from ...data.importer import (read_profile_file, ImportError_,
                              deg_status_to_label, DEG_STATUS_AUTO)
from ..theme import SERIES_COLORS


class DataPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget(); scroll.setWidget(page)
        outer.addWidget(scroll)
        lay = QVBoxLayout(page)
        t = QLabel(tr('Input Data')); t.setObjectName('PageTitle')
        s = QLabel(tr('Format: kolom "Datetime" + "Load (kW)" / "PV ENetAC (kW)" '
                   '/ "Grid Status" / "DEG Status" (0/1/A). Per jam (8760/8784 '
                   'baris) atau resolusi tinggi dgn timestamp konsisten hingga '
                   '1 tahun (mis. 525.600 baris = 1 menit setahun). Interval '
                   'terdeteksi dari timestamp.'))
        s.setObjectName('PageSub')
        s.setWordWrap(True)              # bungkus → tak memaksa lebar halaman
        lay.addWidget(t); lay.addWidget(s)

        self.manual_box = None          # dibuat di bawah
        btns = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        specs = [(tr('Import Excel/CSV…'), self._import_file),
                 (tr('Buat Template Excel…'), self._template),
                 (tr('Input Load Manual (24 jam)…'), self._show_manual)]
        self.mode_btns = []
        for i, (text, slot) in enumerate(specs):
            b = QPushButton(text)
            b.setProperty('mode', True)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c, s=slot: s())
            self.mode_group.addButton(b, i)
            self.mode_btns.append(b)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.manual_box = self._build_manual()
        if self.manual_box is not None:
            self.manual_box.setVisible(False)
        lay.addWidget(self.manual_box)

        info = QGroupBox(tr('Status Data'))
        f = QFormLayout(info)
        self._style_form(f)
        self.lbl_load = QLabel(tr('belum diimpor'))
        self.lbl_pv = QLabel(tr('belum diimpor'))
        self.lbl_grid = QLabel(tr('default: selalu tersedia'))
        self.lbl_deg = QLabel(tr('default: Auto (mengikuti dispatch normal)'))
        for _lb in (self.lbl_load, self.lbl_pv, self.lbl_grid, self.lbl_deg):
            _lb.setWordWrap(True)            # bungkus baris → tak ada h-scroll
            _lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        f.addRow(tr('Load Profile'), self.lbl_load)
        f.addRow(tr('PV ENetAC'), self.lbl_pv)
        f.addRow(tr('Grid Status'), self.lbl_grid)
        f.addRow(tr('DEG Status'), self.lbl_deg)

        # --- Sumber PV ENetAC: Input Excel vs PVGIS ---
        self._syncing_pvsrc = False
        pvsrc = QGroupBox(tr('PV ENetAC Source'))
        pv_f = QFormLayout(pvsrc)
        self._style_form(pv_f)
        # Baris 1 — sumber aktif (dua radio)
        self.pvsrc_group = QButtonGroup(self)
        self.rb_excel = QRadioButton(tr('From Excel input'))
        self.rb_pvgis = QRadioButton(tr('From PVGIS'))
        self.pvsrc_group.addButton(self.rb_excel, 0)
        self.pvsrc_group.addButton(self.rb_pvgis, 1)
        self.rb_excel.toggled.connect(self._on_pv_source_changed)
        self.rb_pvgis.toggled.connect(self._on_pv_source_changed)
        rb_row = QWidget()
        rbl = QHBoxLayout(rb_row)
        rbl.setContentsMargins(0, 0, 0, 0); rbl.setSpacing(18)
        rbl.addWidget(self.rb_excel)
        rbl.addWidget(self.rb_pvgis)
        rbl.addStretch(1)
        # Tombol unduh di sisi KANAN kartu (sebaris dengan pilihan sumber)
        self.btn_dl_input = QPushButton(tr('Download modified input Excel…'))
        self.btn_dl_input.setProperty('flat', True)
        self.btn_dl_input.setCursor(Qt.PointingHandCursor)
        self.btn_dl_input.setToolTip(tr(
            'Save an input Excel (Datetime, Load, active PV ENetAC, Grid '
            'Status) — e.g. with the PV column replaced by PVGIS data.'))
        self.btn_dl_input.clicked.connect(self._download_input_excel)
        rbl.addWidget(self.btn_dl_input, 0, Qt.AlignRight)
        pv_f.addRow(tr('Active source'), rb_row)
        # Baris 2 — ketersediaan tiap sumber (titik status berwarna)
        self.lbl_pvsrc = QLabel('')
        self.lbl_pvsrc.setTextFormat(Qt.RichText)
        self.lbl_pvsrc.setWordWrap(True)
        pv_f.addRow(tr('Availability'), self.lbl_pvsrc)

        # Dua kartu sebaris dengan LEBAR SAMA & TINGGI SAMA; isi rata atas,
        # pola label–nilai seragam di kedua kartu.
        cards = QHBoxLayout()
        cards.setSpacing(8)
        cards.addWidget(info, 1)
        cards.addWidget(pvsrc, 1)
        lay.addLayout(cards)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget(
            title=tr('Pratinjau Profil (7 hari pertama · rata-rata per jam)'))
        no_wheel_zoom(self.plot)
        self.plot.setBackground(None)
        self.plot.addLegend(offset=(10, 10))
        self.plot.setLabel('left', 'kW')
        lay.addWidget(self.plot, 1)
        state.profiles_changed.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _style_form(f):
        """Pola form seragam utk kartu Status Data & PV ENetAC Source."""
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(7)
        f.setContentsMargins(8, 8, 8, 6)

    # ------------------------------------------------------------------
    def _import_file(self):
        if self.manual_box is not None:
            self.manual_box.setVisible(False)
        path, _ = QFileDialog.getOpenFileName(
            self, tr('Pilih file profil'), '',
            'Data (*.xlsx *.xlsm *.xls *.csv)')
        if not path:
            return
        # Indikator progres (file besar mis. 525.600 baris butuh beberapa detik).
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QCoreApplication
        dlg = QProgressDialog(tr('Membaca file…'), tr('Batal'), 0, 100, self)
        dlg.setWindowTitle(tr('Impor Data'))
        dlg.setMinimumDuration(0); dlg.setAutoClose(False); dlg.setAutoReset(False)

        def _step(pct, msg):
            dlg.setValue(int(pct)); dlg.setLabelText(tr(msg))
            QCoreApplication.processEvents()

        _step(5, 'Membaca file…')
        try:
            d = read_profile_file(path)
        except ImportError_ as e:
            dlg.close()
            QMessageBox.warning(self, tr('Import gagal'), str(e))
            return
        if dlg.wasCanceled():
            dlg.close(); return
        _step(70, 'Memuat & memvalidasi profil…')
        self.state.set_profiles(d.get('datetimes'), d.get('load'),
                                d.get('pv'), d.get('grid'), d.get('deg'))
        _step(90, 'Menyiapkan tampilan…')
        # Tahun acuan Load/Grid = tahun kolom Datetime pada Excel.
        try:
            self.state.cfg['excel_year'] = int(d['datetimes'][0].year)
        except Exception:
            pass
        if d.get('pv') is not None:
            # Simpan sebagai sumber "Excel" dan jadikan aktif.
            self.state.set_pv_excel(d['pv'])
            self.state.use_pv_source('excel')
        else:
            self.state.remember_pv_source('excel')
        _step(100, 'Selesai')
        dlg.close()
        got = [k for k in ('load', 'pv', 'grid', 'deg') if k in d]
        QMessageBox.information(
            self, tr('Import berhasil'),
            tr('Kolom terbaca: {cols}').format(cols=", ".join(got)))

    def _template(self):
        if self.manual_box is not None:
            self.manual_box.setVisible(False)
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Simpan template'), 'input_template.xlsx', 'Excel (*.xlsx)')
        if not path:
            return
        import pandas as pd
        dts = pd.date_range('2025-01-01', periods=8760, freq='h')
        pd.DataFrame({'Datetime': dts, 'Load (kW)': 0.0,
                      'PV ENetAC (kW)': 0.0, tr('Grid Status'): 1,
                      tr('DEG Status'): 'A'}) \
            .to_excel(path, index=False)
        QMessageBox.information(
            self, tr('Template'),
            tr('Template tersimpan di\n{path}').format(path=path))

    # ------------------------------------------------------------------
    def _build_manual(self):
        box = QGroupBox(tr('Input Load Manual — pola 24 jam (diulang tiap hari)'))
        v = QVBoxLayout(box)
        head = QHBoxLayout()
        head.addStretch(1)
        b_close = QPushButton(tr('✕  Tutup'))
        b_close.setProperty('flat', True)
        b_close.setCursor(Qt.PointingHandCursor)
        b_close.setToolTip(tr('Tutup panel input manual'))
        b_close.clicked.connect(self._close_manual)
        head.addWidget(b_close)
        v.addLayout(head)
        desc = QLabel(
            tr('Isi beban tiap jam (kW). Pola ini disalin ke seluruh hari dalam '
            'setahun. PV ENetAC memakai profil default bawaan; Grid Status '
            'mengikuti parameter Grid (1 penuh bila ada grid, 0 penuh bila '
            'off-grid).'))
        desc.setWordWrap(True)
        v.addWidget(desc)
        grid = QGridLayout()
        self.hour_spins = []
        for h in range(24):
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 1e6); sp.setDecimals(3)
            sp.setSingleStep(0.1); sp.setValue(0.0)
            sp.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))
            sp.setKeyboardTracking(False)
            sp.setMinimumWidth(64)
            sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            lb = QLabel(f'{h:02d}:00')
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lb.setMinimumWidth(46)
            r, c = h % 6, h // 6
            grid.addWidget(lb, r, c * 2)
            grid.addWidget(sp, r, c * 2 + 1)
            self.hour_spins.append(sp)
        grid.setHorizontalSpacing(8)
        for c in range(4):                 # kolom spin melar seimbang
            grid.setColumnStretch(c * 2, 0)
            grid.setColumnStretch(c * 2 + 1, 1)
        v.addLayout(grid)
        row = QHBoxLayout()
        b_fill = QPushButton(tr('Isi dari Profil Saat Ini'))
        b_fill.setProperty('flat', True)
        b_fill.setCursor(Qt.PointingHandCursor)
        b_fill.clicked.connect(self._fill_from_current)
        b_flat = QPushButton(tr('Isi Rata…'))
        b_flat.setProperty('flat', True)
        b_flat.setCursor(Qt.PointingHandCursor)
        b_flat.clicked.connect(self._fill_flat)
        b_apply = QPushButton(tr('▶  Terapkan ke Setahun'))
        b_apply.setProperty('flat', True)
        b_apply.setCursor(Qt.PointingHandCursor)
        b_apply.clicked.connect(self._apply_manual)
        row.addWidget(b_fill); row.addWidget(b_flat)
        row.addStretch(1)
        row.addWidget(b_apply)
        row.addStretch(1)
        v.addLayout(row)
        self.lbl_manual = QLabel('')
        self.lbl_manual.setObjectName('PageSub')
        self.lbl_manual.setWordWrap(True)
        v.addWidget(self.lbl_manual)
        return box

    def _close_manual(self):
        if self.manual_box is not None:
            self.manual_box.setVisible(False)
        self.mode_group.setExclusive(False)
        for b in self.mode_btns:
            b.setChecked(False)
        self.mode_group.setExclusive(True)

    def _show_manual(self):
        if self.manual_box is None:
            return
        # klik ulang pada tombol mode = tutup panel
        if self.manual_box.isVisible():
            self._close_manual()
        else:
            self.manual_box.setVisible(True)

    def _fill_from_current(self):
        st = self.state
        if st.load is None:
            QMessageBox.information(self, tr('Belum ada data'),
                                    tr('Impor profil dahulu, atau isi manual.'))
            return
        n = len(st.load)
        prof = np.asarray(st.load, float)[:n // 24 * 24].reshape(-1, 24)
        avg = prof.mean(axis=0)
        for h, sp in enumerate(self.hour_spins):
            sp.setValue(float(avg[h]))
        self.lbl_manual.setText(tr('Terisi rata-rata profil saat ini.'))

    def _fill_flat(self):
        vals = [sp.value() for sp in self.hour_spins]
        base = max(vals) if max(vals) > 0 else 0.0
        for sp in self.hour_spins:
            sp.setValue(base)
        self.lbl_manual.setText(tr('Terisi rata sebesar nilai tertinggi.'))

    def _default_pv(self, n: int):
        """Profil PV ENetAC default dari assets/sample_input.xlsx."""
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.abspath(os.path.join(here, '..', '..', '..'))
        path = os.path.join(root, 'assets', 'sample_input.xlsx')
        if not os.path.exists(path):
            return None
        try:
            d = read_profile_file(path)
        except ImportError_:
            return None
        pv = d.get('pv')
        if pv is None:
            return None
        pv = np.asarray(pv, float)
        if len(pv) >= n:
            return pv[:n]
        return np.resize(pv, n)

    def _apply_manual(self):
        vals = np.array([sp.value() for sp in self.hour_spins], float)
        if vals.sum() <= 0:
            QMessageBox.warning(self, tr('Data kosong'),
                                tr('Isi setidaknya satu jam dengan nilai > 0.'))
            return
        year = int(self.state.cfg.get('simulation_year', 2025) or 2025)
        leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
        days = 366 if leap else 365
        load = np.tile(vals, days)
        n = len(load)
        pv = self.state.pv_norm
        src = tr('profil PV yang sudah dimuat')
        if pv is None or len(pv) != n:
            pv = self._default_pv(n)
            src = tr('profil PV default bawaan')
        if pv is None:
            QMessageBox.warning(
                self, tr('PV tidak tersedia'),
                tr('Profil PV default tidak ditemukan '
                   '(assets/sample_input.xlsx). Impor profil PV '
                   'terlebih dahulu.'))
            return
        on = bool(self.state.cfg.get('grid_enabled', True))
        grid = np.ones(n) if on else np.zeros(n)
        try:
            import pandas as pd
            dts = pd.date_range(f'{year}-01-01', periods=n, freq='h')
        except Exception:
            dts = None
        self.state.set_profiles(dts, load, pv, grid)
        gs = tr('1 (tersedia)') if on else tr('0 (off-grid)')
        self.lbl_manual.setText(
            tr('{n} jam dibuat dari pola 24 jam · {src} · Grid Status {g} '
               'penuh.').format(n=f'{n:,}', src=src, g=gs))
        QMessageBox.information(
            self, tr('Data dibuat'),
            tr('Load {e} kWh/tahun dari pola 24 jam (diulang {d} hari).')
            .format(e=f'{load.sum():,.0f}', d=days)
            + f'\nPV ENetAC: {src}.\n' + tr('Grid Status:') + ' '
            + (tr('selalu tersedia') if on else tr('off-grid penuh')) + '.')

    # ------------------------------------------------------------------
    # -------------------------- sumber PV ENetAC --------------------------
    def _on_pv_source_changed(self, checked):
        if not checked or self._syncing_pvsrc:
            return
        src = 'pvgis' if self.rb_pvgis.isChecked() else 'excel'
        if self.state.pv_source() == src:
            return
        if not self.state.apply_pv_source(src):
            self._sync_pv_source()          # sumber belum ada → kembalikan
            return
        # profil aktif berubah → profiles_changed memicu refresh()

    def _sync_pv_source(self):
        st = self.state
        has_x = st.pv_excel is not None
        has_g = st.pv_pvgis is not None
        src = st.pv_source()
        if src == 'pvgis' and not has_g and has_x:
            src = 'excel'
        elif src == 'excel' and not has_x and has_g:
            src = 'pvgis'
        self._syncing_pvsrc = True
        self.rb_excel.setEnabled(has_x)
        self.rb_pvgis.setEnabled(has_g)
        self.rb_excel.setChecked(src == 'excel' and has_x)
        self.rb_pvgis.setChecked(src == 'pvgis' and has_g)
        self._syncing_pvsrc = False
        self.btn_dl_input.setEnabled(
            st.load is not None and st.pv_norm is not None)
        from .. import theme as _thm

        def _item(name, ok):
            col = _thm.tok('ok') if ok else _thm.tok('faint')
            txt = tr('available') if ok else tr('not loaded')
            return (f'<span style="color:{col}">&#9679;</span>&nbsp;{name}: '
                    f'<span style="color:{_thm.tok("muted")}">{txt}</span>')
        self.lbl_pvsrc.setText(_item('Excel', has_x) + '&nbsp;&nbsp;&nbsp;&nbsp;'
                               + _item('PVGIS', has_g))

    def _download_input_excel(self):
        st = self.state
        if st.load is None or st.pv_norm is None:
            QMessageBox.information(
                self, tr('Belum ada data'),
                tr('Load and PV ENetAC profiles are required first.'))
            return
        import os
        import pandas as pd
        base = (self.state.cfg.get('site_name')
                or self.state.cfg.get('project_name') or 'input')
        suffix = 'PVGIS' if st.pv_source() == 'pvgis' else 'Excel'
        default = f'input_{base}_{suffix}.xlsx'.replace(' ', '_')
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Download Input Excel'), default, 'Excel (*.xlsx)')
        if not path:
            return
        try:
            n = len(st.load)
            if st.datetimes is not None and len(st.datetimes) == n:
                dts = pd.DatetimeIndex(st.datetimes)
            else:
                dts = pd.date_range('2025-01-01', periods=n, freq='h')
            grid = (st.grid_status if st.grid_status is not None
                    and len(st.grid_status) == n else np.ones(n))
            deg = (st.deg_status if st.deg_status is not None
                   and len(st.deg_status) == n else np.full(n, DEG_STATUS_AUTO))
            df = pd.DataFrame({
                'Datetime': dts,
                'Load (kW)': np.asarray(st.load, float),
                'PV ENetAC (kW)': np.asarray(st.pv_norm, float),
                'Grid Status': np.asarray(grid, float).round().astype(int),
                'DEG Status': [deg_status_to_label(c) for c in np.asarray(deg, float)],
            })
            df.to_excel(path, index=False)
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))
            return
        QMessageBox.information(
            self, tr('Sukses'),
            tr('Input Excel saved:') + f'\n{os.path.basename(path)}')

    def refresh(self):
        st = self.state
        self._sync_pv_source()
        # Interval NATIVE data (dari timestamp / jumlah baris). Energi = daya ×
        # dt; jumlah baris BUKAN jam. Data per-jam -> dt=1 (tampilan lama utuh).
        from ...config import intervals as ivals
        n = len(st.load) if st.load is not None else 0
        iv = ivals.detect_interval_label(n, st.datetimes) or '1 hour'
        dt = ivals.interval_dt_h(iv)
        if st.load is not None:
            self.lbl_load.setText(
                tr('{n} baris · total {e} kWh · puncak {p} kW').format(
                    n=f'{len(st.load):,}',
                    e=f'{st.load.sum() * dt:,.0f}', p=f'{st.load.max():,.1f}'))
        if st.pv_norm is not None:
            self.lbl_pv.setText(
                tr('{n} baris · profil basis {e} (skala kWp/basis)'
                   ).format(n=f'{len(st.pv_norm):,}',
                            e=f'{st.pv_norm.sum() * dt:,.0f}'))
        if st.grid_status is not None:
            off_h = float((st.grid_status == 0).sum()) * dt
            oh = f'{off_h:,.0f}' if abs(off_h - round(off_h)) < 0.05 \
                else f'{off_h:,.1f}'
            self.lbl_grid.setText(tr('{n} jam padam / tahun').format(n=oh))
        if st.deg_status is not None:
            off_h = float((st.deg_status == 0.0).sum()) * dt
            on_h = float((st.deg_status == 1.0).sum()) * dt
            auto_h = float((st.deg_status == DEG_STATUS_AUTO).sum()) * dt
            self.lbl_deg.setText(
                tr('{off} jam DEG dipaksa OFF · {on} jam dipaksa ON · '
                   '{auto} jam Auto').format(
                    off=f'{off_h:,.0f}', on=f'{on_h:,.0f}',
                    auto=f'{auto_h:,.0f}'))
        else:
            self.lbl_deg.setText(tr('default: Auto (mengikuti dispatch normal)'))
        self.plot.clear()
        # Pratinjau: ratakan ke basis PER JAM lalu tampilkan hingga 7 hari
        # pertama (pola harian jelas) — bukan 720 langkah mentah (utk data 1
        # menit hanya 12 menit & tak terbaca).
        if st.load is not None:
            lh = ivals.to_hourly(st.load, iv)
            m = int(min(len(lh), 168))
            xh = np.arange(m)
            self.plot.plot(xh, np.asarray(lh[:m], float),
                           pen=pg.mkPen(SERIES_COLORS['load'], width=1.4),
                           name=tr('Load'))
            if st.pv_norm is not None:
                ph = ivals.to_hourly(st.pv_norm, iv)
                scale = self.state.cfg.get('pv_kwp', 1) / \
                    max(self.state.cfg.get('pv_base_annual', 1), 1e-9)
                self.plot.plot(xh, np.asarray(ph[:m], float) * scale,
                               pen=pg.mkPen(SERIES_COLORS['pv'], width=1.2),
                               name=tr('PV ENetAC'))
        self.plot.setLabel('bottom', tr('Jam pertama (pratinjau · rata-rata per jam)'))
