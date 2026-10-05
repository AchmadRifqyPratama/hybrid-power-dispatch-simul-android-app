"""Utilitas bersama untuk seluruh grafik pyqtgraph.

* ``no_wheel_zoom``  — mematikan zoom via scroll mouse (sering tak sengaja
  terpicu saat menggulir halaman).
* ``CursorReadout``  — menampilkan nilai seri pada posisi kursor.
* ``fit_table_columns`` — melebarkan kolom tabel agar memenuhi lebar yang
  tersedia di layar, tanpa memaksa scroll horizontal bila muat.
"""
from __future__ import annotations

import os
import sys

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QHeaderView, QTableWidget, QApplication,
                               QAbstractItemView)


# --------------------------------------------------------------- grafik
def no_wheel_zoom(plot) -> None:
    """Matikan zoom roda mouse pada sebuah PlotWidget/ViewBox."""
    try:
        vb = plot.getViewBox() if hasattr(plot, 'getViewBox') else plot
    except Exception:
        return
    if vb is None:
        return

    def _ignore(ev, axis=None):
        try:
            ev.ignore()
        except Exception:
            pass

    vb.wheelEvent = _ignore


class CursorReadout:
    """Tampilkan nilai seri di posisi kursor pada sebuah plot.

    ``formatter(x)`` mengembalikan teks yang ditampilkan pada ``label``;
    kembalikan string kosong bila tidak ada data pada posisi tersebut.
    """

    def __init__(self, plot, label, formatter, vline: bool = True):
        self.plot, self.label, self.fmt = plot, label, formatter
        self.line = None
        if vline:
            self.line = pg.InfiniteLine(angle=90, movable=False,
                                        pen=pg.mkPen((150, 150, 150, 110),
                                                     width=1))
            self.line.setZValue(-10)
            plot.addItem(self.line, ignoreBounds=True)
            self.line.hide()
        self._proxy = pg.SignalProxy(plot.scene().sigMouseMoved,
                                     rateLimit=45, slot=self._moved)

    def _moved(self, evt):
        pos = evt[0]
        try:
            inside = self.plot.sceneBoundingRect().contains(pos)
        except Exception:
            inside = False
        if not inside:
            if self.line is not None:
                self.line.hide()
            return
        x = self.plot.getViewBox().mapSceneToView(pos).x()
        try:
            text = self.fmt(float(x))
        except Exception:
            text = ''
        if self.line is not None:
            if text:
                self.line.setPos(x)
                self.line.show()
            else:
                self.line.hide()
        if self.label is not None:
            self.label.setText(text)


# --------------------------------------------------------------- tabel
def fit_table_columns(table, min_w: int = 84, pad: int = 18,
                      max_w: int = 320, fill: bool = True) -> None:
    """Lebarkan kolom mengikuti isi.

    ``fill=True``  : bila total kolom lebih sempit dari area tampil, sisa ruang
                     dibagi proporsional sehingga tabel memenuhi lebar.
    ``fill=False`` : kolom dirapatkan sesuai isi saja (tanpa diregangkan) —
                     tidak ada ruang kosong berlebih di dalam sel.
    Bila total kolom lebih lebar dari area tampil, kolom dibatasi ``max_w`` dan
    scroll horizontal tetap tersedia.
    """
    n = table.columnCount()
    if n <= 0:
        return
    table.resizeColumnsToContents()
    widths = [min(max(table.columnWidth(c) + pad, min_w), max_w)
              for c in range(n)]
    total = sum(widths)
    avail = table.viewport().width()
    if fill and avail > 0 and total > 0 and avail > total:
        extra = avail - total
        for c in range(n):
            widths[c] += int(extra * widths[c] / total)
        # sisa pembulatan diberikan ke kolom terakhir
        widths[-1] += avail - sum(widths)
    for c, w in enumerate(widths):
        table.setColumnWidth(c, max(w, min_w))
    hh = table.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.Interactive)


class CopyTableWidget(QTableWidget):
    """QTableWidget dengan seleksi blok (drag) + salin ke clipboard (Ctrl+C)
    dalam format TSV, siap ditempel ke sel Excel/Sheets.

    Nilai mentah (tanpa pemisah ribuan) disimpan di ``Qt.UserRole`` bila ada,
    sehingga tersalin sebagai angka yang bersih untuk Excel; jika tidak ada,
    teks yang tampil yang disalin.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setCornerButtonEnabled(True)   # klik pojok = pilih semua

    def keyPressEvent(self, ev):
        if ev.matches(QKeySequence.Copy):
            self.copy_selection()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _cell_text(self, row, col):
        it = self.item(row, col)
        if it is None:
            return ''
        raw = it.data(Qt.UserRole)
        if raw is not None and str(raw) != '':
            return str(raw)
        return it.text()

    def copy_selection(self):
        ranges = self.selectedRanges()
        if not ranges:
            return
        rows = sorted({r for rng in ranges
                       for r in range(rng.topRow(), rng.bottomRow() + 1)
                       if not self.isRowHidden(r)})
        cols_logical = {c for rng in ranges
                        for c in range(rng.leftColumn(), rng.rightColumn() + 1)
                        if not self.isColumnHidden(c)}
        # Salin mengikuti urutan TAMPILAN kolom (visual), sehingga bila kolom
        # digeser-geser, hasil salin ke Excel tetap sesuai yang terlihat.
        hh = self.horizontalHeader()
        cols = sorted(cols_logical, key=lambda c: hh.visualIndex(c))
        lines = ['\t'.join(self._cell_text(r, c) for c in cols) for r in rows]
        QApplication.clipboard().setText('\n'.join(lines))


# --------------------------------------------------------------- aset
def asset_path(name: str) -> str:
    """Lokasi berkas di folder assets, baik saat dijalankan dari sumber
    maupun dari hasil bundel PyInstaller."""
    base = getattr(sys, '_MEIPASS', None)
    if base:
        p = os.path.join(base, 'assets', name)
        if os.path.exists(p):
            return p
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, '..', '..'))
    return os.path.join(root, 'assets', name)
