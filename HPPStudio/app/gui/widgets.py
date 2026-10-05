"""Widget reusable: kartu KPI, form parameter otomatis dari skema, pie chart."""
from __future__ import annotations

from ..config.i18n import tr
from PySide6.QtCore import Qt, Signal, QLocale, QRectF
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QStandardItem,
                           QBrush)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QFormLayout,
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QGridLayout,
    QSizePolicy, QPushButton, QFileDialog, QMessageBox)

from ..config.parameters import Param, MODE_PRIORITY


class KPICard(QWidget):
    """Tile KPI ringkas: label (atas, kecil) + nilai + satuan (sebaris).

    API tidak berubah: KPICard(label, value, unit) & set_value(text)."""
    def __init__(self, label: str, value: str = '-', unit: str = ''):
        super().__init__()
        self.setObjectName('KPICard')
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 7)
        lay.setSpacing(1)
        self.l = QLabel(tr(label), self)
        self.l.setObjectName('KPITileLabel'); self.l.setWordWrap(True)
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self.v = QLabel(value, self); self.v.setObjectName('KPIValue')
        self.v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.v, 0, Qt.AlignBottom)
        # Induk (self) diberikan SAAT dibuat, dan visibilitas diatur SETELAH
        # masuk layout: setVisible(True) pada widget tanpa induk membuatnya
        # tampil sebagai JENDELA top-level sesaat ("potongan jendela" v132/133).
        self.u = QLabel(tr(unit) if unit else '', self)
        self.u.setObjectName('KPIUnit')
        row.addWidget(self.u, 0, Qt.AlignBottom)
        if not unit:
            self.u.hide()
        row.addStretch(1)
        lay.addWidget(self.l); lay.addLayout(row)
        self.setToolTip(tr(label) + (f' ({tr(unit)})' if unit else ''))

    def set_value(self, text: str):
        try:
            self.v.setText(text)
        except RuntimeError:      # widget sudah dihapus (mis. ganti bahasa)
            pass


class ParamField(QWidget):
    """Satu baris input parameter: widget sesuai dtype + satuan + tooltip.
    Persentase (unit mengandung '%') ditampilkan 0-100, disimpan 0-1."""
    changed = Signal()

    def __init__(self, p: Param):
        super().__init__()
        self.p = p
        self.is_pct = '%' in p.unit and p.dtype == 'float'
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        if p.dtype == 'bool':
            self.w = QCheckBox()
            self.w.setChecked(bool(p.default))
            self.w.stateChanged.connect(self.changed)
        elif p.dtype == 'choice':
            self.w = QComboBox(); self.w.addItems([str(c) for c in p.choices])
            self.w.setCurrentText(str(p.default))
            self.w.currentTextChanged.connect(self.changed)
        elif p.dtype == 'int':
            self.w = QSpinBox()
            self.w.setRange(int(p.minimum or 0), int(p.maximum or 10**9))
            self.w.setKeyboardTracking(False)
            self.w.setValue(int(p.default))
            self.w.valueChanged.connect(self.changed)
        elif p.dtype == 'text':
            self.w = QLineEdit(str(p.default))
            self.w.textChanged.connect(self.changed)
        elif p.dtype == 'soh_curve':
            # tabel [tahun, SOH] dari berkas Excel/CSV (2 kolom)
            self._curve = []
            self.w = QLabel()
            self.w.setObjectName('KPILabel')
            self.w.setWordWrap(True)
            self._btn_imp = QPushButton(tr('Impor Excel…'))
            self._btn_imp.clicked.connect(self._import_curve)
            self._btn_clr = QPushButton(tr('Hapus'))
            self._btn_clr.clicked.connect(self._clear_curve)
            self._show_curve()
        else:
            self.w = QDoubleSpinBox()
            lo = p.minimum if p.minimum is not None else -1e15
            hi = p.maximum if p.maximum is not None else 1e15
            scale = 100.0 if self.is_pct else 1.0
            dec = 2 if self.is_pct else p.decimals
            self.w.setRange(lo * scale, hi * scale)
            self.w.setDecimals(dec)
            self.w.setSingleStep(10.0 ** (-dec))
            self.w.setValue(float(p.default) * scale)
            self.w.setGroupSeparatorShown(True)
            # locale seragam: pemisah desimal titik, ribuan koma —
            # tanpa ini, locale sistem (id_ID) menganggap '.' sebagai
            # pemisah ribuan sehingga desimal sulit diketik
            self.w.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))
            # jangan emit tiap ketukan: mencegah nilai ditulis ulang
            # (mis. '0.5' terpotong jadi '0') saat masih mengetik
            self.w.setKeyboardTracking(False)
            self.w.valueChanged.connect(self.changed)
        self.w.setToolTip(tr(p.tooltip or p.label))
        lay.addWidget(self.w, 1)
        lay.setSpacing(6)
        if p.dtype == 'soh_curve':
            lay.addWidget(self._btn_imp)
            lay.addWidget(self._btn_clr)
        if p.unit:
            u = QLabel(tr(p.unit)); u.setObjectName('KPILabel')
            u.setMinimumWidth(34)
            lay.addWidget(u)

    # --- kurva SOH (dtype 'soh_curve') ---
    def _show_curve(self):
        c = self._curve
        if not c:
            self.w.setText(tr('Belum ada berkas — impor Excel/CSV 2 kolom '
                              '(tahun, SOH)'))
            self._btn_clr.setEnabled(False)
            return
        self._btn_clr.setEnabled(True)
        self.w.setText(tr('{n} titik · tahun {a:g}–{b:g} · SOH {s0:.1f}% → '
                          '{s1:.1f}%').format(
            n=len(c), a=c[0][0], b=c[-1][0], s0=c[0][1] * 100, s1=c[-1][1] * 100))
        self.w.setToolTip(tr(self.p.tooltip) + '\n\n' + '\n'.join(
            f'{y:g}: {v * 100:.1f}%' for y, v in c))

    def _clear_curve(self):
        self._curve = []
        self._show_curve()
        self.changed.emit()

    def _import_curve(self):
        from ..config.parameters import parse_soh_curve
        path, _ = QFileDialog.getOpenFileName(
            self, tr('Pilih berkas kurva SOH BESS'), '',
            tr('Excel / CSV') + ' (*.xlsx *.xlsm *.xls *.csv *.txt)')
        if not path:
            return
        try:
            import pandas as pd
            if path.lower().endswith(('.csv', '.txt')):
                df = pd.read_csv(path, header=None, sep=None, engine='python')
            else:
                df = pd.read_excel(path, header=None)
            rows = df.iloc[:, :2].values.tolist() if df.shape[1] >= 2 else []
            curve = parse_soh_curve(rows)
        except Exception as e:                       # pragma: no cover (GUI)
            QMessageBox.warning(self, tr('Kurva SOH'),
                                tr('Berkas tidak dapat dibaca: {e}').format(e=e))
            return
        if len(curve) < 2:
            QMessageBox.warning(self, tr('Kurva SOH'), tr(
                'Tidak ditemukan data SOH. Berkas harus berisi 2 kolom: kolom '
                'pertama tahun, kolom kedua SOH pada tahun tersebut.'))
            return
        self._curve = curve
        self._show_curve()
        self.changed.emit()

    def value(self):
        p = self.p
        if p.dtype == 'soh_curve':
            return [list(r) for r in self._curve]
        if p.dtype == 'bool':
            return bool(self.w.isChecked())
        if p.dtype == 'choice':
            return self.w.currentText()
        if p.dtype == 'int':
            return int(self.w.value())
        if p.dtype == 'text':
            return self.w.text()
        v = float(self.w.value())
        return v / 100.0 if self.is_pct else v

    def set_choices(self, choices, keep=None):
        """Perbarui isi dropdown (dipakai bila pilihan bergantung
        pada parameter lain). Tidak memicu sinyal changed."""
        if self.p.dtype != 'choice':
            return
        cur = keep if keep is not None else self.w.currentText()
        items = [str(c) for c in choices]
        if items == [self.w.itemText(i)
                     for i in range(self.w.count())]:
            if cur and cur != self.w.currentText():
                self.w.blockSignals(True)
                self.w.setCurrentText(cur)
                self.w.blockSignals(False)
            return
        self.w.blockSignals(True)
        self.w.clear()
        self.w.addItems(items)
        if cur in items:
            self.w.setCurrentText(cur)
        self.w.blockSignals(False)

    def set_grouped_choices(self, groups, keep=None):
        """Isi dropdown dengan baris JUDUL kelompok (tidak dapat dipilih) di
        atas tiap kelompok. `groups` = [(judul, [label, ...]), ...].
        Dipakai untuk mengelompokkan Load Supply Priority per status grid."""
        if self.p.dtype != 'choice':
            return
        cur = keep if keep is not None else self.w.currentText()
        selectable = [lbl for _h, items in groups for lbl in items]
        target = cur if cur in selectable else (
            selectable[0] if selectable else '')
        # deret baris yang diinginkan (judul + item) untuk deteksi perubahan
        desired = []
        for header, items in groups:
            if header:
                desired.append(str(header))
            desired.extend(str(x) for x in items)
        current = [self.w.itemText(i) for i in range(self.w.count())]
        if desired == current:                    # struktur sama -> cukup pilih
            if target and target != self.w.currentText():
                self.w.blockSignals(True)
                self.w.setCurrentText(target)
                self.w.blockSignals(False)
            return
        self.w.blockSignals(True)
        self.w.clear()
        model = self.w.model()
        for header, items in groups:
            if header:
                hi = QStandardItem(str(header))
                hi.setFlags(Qt.NoItemFlags)              # judul: non-selectable
                f = hi.font(); f.setBold(True); hi.setFont(f)
                hi.setForeground(QBrush(QColor('#8A94A0')))
                model.appendRow(hi)
            for lbl in items:
                model.appendRow(QStandardItem(str(lbl)))
        idx = self.w.findText(target)
        if idx >= 0:
            self.w.setCurrentIndex(idx)
        self.w.blockSignals(False)

    def set_value(self, v):
        p = self.p
        if p.dtype == 'soh_curve':
            from ..config.parameters import parse_soh_curve
            try:
                self._curve = parse_soh_curve(v or [])
            except Exception:
                self._curve = []
            self._show_curve()
            return
        self.w.blockSignals(True)
        if p.dtype == 'bool':
            self.w.setChecked(bool(v))
        elif p.dtype == 'choice':
            self.w.setCurrentText(str(v))
        elif p.dtype == 'int':
            self.w.setValue(int(v))
        elif p.dtype == 'text':
            self.w.setText(str(v))
        else:
            self.w.setValue(float(v) * (100.0 if self.is_pct else 1.0))
        self.w.blockSignals(False)


class ParamGroupBox(QGroupBox):
    """Group parameter otomatis dari SCHEMA[group].

    Dua penataan khusus:
      * dtype 'heading'  -> baris JUDUL sub-bagian (full-width, tanpa input).
      * mode BESS (MODE_PRIORITY) -> dropdown prioritasnya dirender SEBARIS
        dengan checkbox mode (bukan baris terpisah).
    """
    changed = Signal()

    def __init__(self, title: str, params: list[Param]):
        super().__init__(tr(title))
        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(4)
        form.setContentsMargins(6, 6, 6, 4)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self._form = form
        self.fields: dict[str, ParamField] = {}
        self.labels: dict[str, QLabel] = {}
        self.headings: dict[str, QLabel] = {}
        self._rowfield: dict[str, QWidget] = {}   # widget dipakai sbg 'field' baris
        self._inline_prio: set[str] = set()        # prioritas yang tampil sebaris

        pmap = {p.key: p for p in params}
        for p in params:
            if p.dtype == 'heading':
                h = QLabel(tr(p.label)); h.setObjectName('ParamHeading')
                h.setStyleSheet('font-weight:700; padding:6px 0 1px 0;')
                if p.tooltip:
                    h.setToolTip(tr(p.tooltip))
                form.addRow(h)
                self.headings[p.key] = h
                continue
            if p.key in self._inline_prio:
                continue                            # sudah dirender sebaris mode
            if p.key in MODE_PRIORITY:
                self._add_mode_row(form, p, pmap)
                continue
            f = ParamField(p)
            f.changed.connect(self.changed)
            lbl = QLabel(tr(p.label))
            lbl.setToolTip(tr(p.tooltip or p.label))
            form.addRow(lbl, f)
            self.fields[p.key] = f
            self.labels[p.key] = lbl
            self._rowfield[p.key] = f

    def _add_mode_row(self, form, p, pmap):
        """Baris komposit: [checkbox mode] ......... Priority [dropdown].

        Prioritas RATA KANAN (stretch di antara checkbox & Priority) sehingga
        kolom input (dropdown hitam) rapi di tepi kanan."""
        mode_f = ParamField(p)
        mode_f.changed.connect(self.changed)
        mode_f.setFixedWidth(30)                    # cukup untuk kotak centang
        self.fields[p.key] = mode_f
        cont = QWidget()
        hl = QHBoxLayout(cont)
        hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(8)
        hl.addWidget(mode_f, 0)
        hl.addStretch(1)                            # dorong Priority ke kanan
        pk = MODE_PRIORITY.get(p.key)
        pp = pmap.get(pk) if pk else None
        if pp is not None:
            plbl = QLabel(tr('Priority')); plbl.setObjectName('KPILabel')
            prio_f = ParamField(pp)
            prio_f.changed.connect(self.changed)
            prio_f.setMaximumWidth(90)
            hl.addWidget(plbl, 0); hl.addWidget(prio_f, 0)
            self.fields[pk] = prio_f
            self.labels[pk] = plbl
            self._inline_prio.add(pk)
        lbl = QLabel(tr(p.label))
        lbl.setToolTip(tr(p.tooltip or p.label))
        form.addRow(lbl, cont)
        self.labels[p.key] = lbl
        self._rowfield[p.key] = cont

    def values(self) -> dict:
        return {k: f.value() for k, f in self.fields.items()}

    def set_values(self, cfg: dict):
        for k, f in self.fields.items():
            if k in cfg and not f.w.hasFocus():   # jangan ganggu input aktif
                f.set_value(cfg[k])

    def apply_visibility(self, cfg: dict, rules: dict):
        """Tampilkan hanya parameter yang relevan dengan konfigurasi."""
        for k, f in self.fields.items():
            rule = rules.get(k)
            vis = True if rule is None else bool(rule(cfg))
            if k in self._inline_prio:            # widget dalam baris komposit
                f.setVisible(vis)
                lbl = self.labels.get(k)
                if lbl is not None:
                    lbl.setVisible(vis)
                continue
            rw = self._rowfield.get(k, f)
            try:
                self._form.setRowVisible(rw, vis)
            except Exception:
                rw.setVisible(vis)
                if k in self.labels:
                    self.labels[k].setVisible(vis)
        for k, h in self.headings.items():        # judul sub-bagian
            rule = rules.get(k)
            vis = True if rule is None else bool(rule(cfg))
            try:
                self._form.setRowVisible(h, vis)
            except Exception:
                h.setVisible(vis)


class PieChart(QWidget):
    """Pie chart ringan via QPainter (tanpa dependensi tambahan)."""
    def __init__(self, title=''):
        super().__init__()
        self.title = title
        self.data: list[tuple[str, float, str]] = []
        self.setMinimumSize(260, 220)

    def set_data(self, items):
        self.data = [(l, max(0.0, float(v)), c) for l, v, c in items if v > 1e-6]
        self.update()

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        qp.setPen(QPen(self.palette().text().color()))
        f = QFont(); f.setBold(True)
        qp.setFont(f)
        qp.drawText(QRectF(0, 4, w, 20), Qt.AlignHCenter, self.title)
        total = sum(v for _, v, _ in self.data)
        if total <= 0:
            return
        d = min(w - 130, h - 40)
        rect = QRectF(12, 30, d, d)
        start = 90 * 16
        for label, v, color in self.data:
            span = -int(round(v / total * 360 * 16))
            qp.setBrush(QColor(color)); qp.setPen(Qt.NoPen)
            qp.drawPie(rect, start, span)
            start += span
        # legend
        qp.setFont(QFont('Segoe UI', 8))
        y = 40
        for label, v, color in self.data:
            qp.setBrush(QColor(color)); qp.setPen(Qt.NoPen)
            qp.drawRect(int(d) + 26, y, 11, 11)
            qp.setPen(QPen(self.palette().text().color()))
            qp.drawText(int(d) + 42, y + 10, f'{label} {v/total*100:.1f}%')
            y += 18


def kpi_grid(cards: list[KPICard], cols=4) -> QWidget:
    w = QWidget(); g = QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(8); g.setVerticalSpacing(8)
    for i, c in enumerate(cards):
        g.addWidget(c, i // cols, i % cols)
    # tile tidak ikut meregang vertikal: sisa ruang ke baris kosong terakhir
    for c in cards:
        c.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    g.setRowStretch((len(cards) + cols - 1) // cols, 1)
    return w
