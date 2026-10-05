"""Ikon navigasi profesional (garis monokrom) digambar via QPainter.

Tanpa berkas gambar / dependensi tambahan (aman untuk build .exe). Tiap ikon
digambar pada kanvas 24-unit lalu diskalakan; warna mengikuti tema (dua state:
Off = warna teks biasa, On = warna aksen saat item nav aktif)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath


def _stroke(p: QPainter, s: float, color: str, w: float = 1.9):
    pen = QPen(QColor(color))
    pen.setWidthF(w * s)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)


# ------- masing-masing ikon: gambar pada koordinat 24-unit (skala s) -------
def _home(p, s, col):
    _stroke(p, s, col)
    path = QPainterPath()
    path.moveTo(4 * s, 11.5 * s)
    path.lineTo(12 * s, 4.5 * s)
    path.lineTo(20 * s, 11.5 * s)
    p.drawPath(path)
    p.drawRoundedRect(QRectF(6.2 * s, 11 * s, 11.6 * s, 8.6 * s), 1.2 * s, 1.2 * s)
    p.drawRect(QRectF(10.3 * s, 14.8 * s, 3.4 * s, 4.8 * s))


def _params(p, s, col):
    # sliders: tiga garis horizontal dengan knob
    _stroke(p, s, col)
    ys = (7.0, 12.0, 17.0)
    knobx = (16.0, 9.5, 14.0)
    for y, kx in zip(ys, knobx):
        p.drawLine(QPointF(4 * s, y * s), QPointF(20 * s, y * s))
    _stroke(p, s, col, 1.9)
    for y, kx in zip(ys, knobx):
        r = 1.9 * s
        c = QColor(col)
        p.setBrush(c)
        p.drawEllipse(QPointF(kx * s, y * s), r, r)
    p.setBrush(Qt.NoBrush)


def _data(p, s, col):
    # basis data (silinder)
    _stroke(p, s, col)
    top = QRectF(4.5 * s, 4 * s, 15 * s, 4.6 * s)
    p.drawEllipse(top)
    p.drawLine(QPointF(4.5 * s, 6.3 * s), QPointF(4.5 * s, 17.7 * s))
    p.drawLine(QPointF(19.5 * s, 6.3 * s), QPointF(19.5 * s, 17.7 * s))
    # dua lengkung tengah + bawah
    p.drawArc(QRectF(4.5 * s, 9 * s, 15 * s, 4.6 * s), 180 * 16, 180 * 16)
    p.drawArc(QRectF(4.5 * s, 15.4 * s, 15 * s, 4.6 * s), 180 * 16, 180 * 16)


def _dashboard(p, s, col):
    # bar chart
    _stroke(p, s, col)
    p.drawLine(QPointF(4 * s, 20 * s), QPointF(20 * s, 20 * s))   # sumbu
    bars = ((6.5, 13), (11, 8.5), (15.5, 5))
    _stroke(p, s, col, 2.6)
    for x, y in bars:
        p.drawLine(QPointF(x * s, 20 * s), QPointF(x * s, y * s))


def _optimization(p, s, col):
    # target (goal) — lingkaran konsentris + titik pusat
    _stroke(p, s, col)
    p.drawEllipse(QPointF(12 * s, 12 * s), 8 * s, 8 * s)
    p.drawEllipse(QPointF(12 * s, 12 * s), 4.3 * s, 4.3 * s)
    c = QColor(col); p.setBrush(c)
    p.drawEllipse(QPointF(12 * s, 12 * s), 1.4 * s, 1.4 * s)
    p.setBrush(Qt.NoBrush)


def _results(p, s, col):
    # dokumen + baris teks + sudut terlipat
    _stroke(p, s, col)
    path = QPainterPath()
    path.moveTo(6 * s, 3.5 * s)
    path.lineTo(14 * s, 3.5 * s)
    path.lineTo(18 * s, 7.5 * s)
    path.lineTo(18 * s, 20.5 * s)
    path.lineTo(6 * s, 20.5 * s)
    path.closeSubpath()
    p.drawPath(path)
    p.drawPolyline([QPointF(14 * s, 3.5 * s), QPointF(14 * s, 7.5 * s),
                    QPointF(18 * s, 7.5 * s)])
    for y in (11.5, 14, 16.5):
        p.drawLine(QPointF(8.5 * s, y * s), QPointF(15.5 * s, y * s))


def _multiyear(p, s, col):
    # kalender / rentang tahun
    _stroke(p, s, col)
    p.drawRoundedRect(QRectF(4 * s, 5.5 * s, 16 * s, 14 * s), 1.6 * s, 1.6 * s)
    p.drawLine(QPointF(4 * s, 9.5 * s), QPointF(20 * s, 9.5 * s))
    p.drawLine(QPointF(8 * s, 3.5 * s), QPointF(8 * s, 7 * s))
    p.drawLine(QPointF(16 * s, 3.5 * s), QPointF(16 * s, 7 * s))
    c = QColor(col); p.setBrush(c)
    for (x, y) in ((8, 13), (12, 13), (16, 13), (8, 16.5), (12, 16.5)):
        p.drawEllipse(QPointF(x * s, y * s), 0.9 * s, 0.9 * s)
    p.setBrush(Qt.NoBrush)


def _sun(p, s, col):
    _stroke(p, s, col)
    p.drawEllipse(QPointF(12 * s, 12 * s), 4.2 * s, 4.2 * s)
    import math
    for k in range(8):
        a = math.radians(k * 45)
        dx, dy = math.cos(a), math.sin(a)
        p.drawLine(QPointF((12 + 6.6 * dx) * s, (12 + 6.6 * dy) * s),
                   QPointF((12 + 8.6 * dx) * s, (12 + 8.6 * dy) * s))


def _moon(p, s, col):
    _stroke(p, s, col)
    path = QPainterPath()
    path.moveTo(15.5 * s, 4.5 * s)
    path.arcTo(QRectF(4 * s, 4 * s, 16 * s, 16 * s), 60, 190)
    path.arcTo(QRectF(8.5 * s, 3.2 * s, 13 * s, 13 * s), 250, -190)
    path.closeSubpath()
    c = QColor(col); p.setBrush(c)
    p.setPen(Qt.NoPen)
    p.drawPath(path)


_DRAW = {
    'Home': _home, 'Parameters': _params, 'Data': _data,
    'Dashboard': _dashboard, 'Optimization': _optimization,
    'Results': _results, 'Multi-Year': _multiyear,
    'sun': _sun, 'moon': _moon,
}


def _pixmap(name: str, color: str, px: int = 44) -> QPixmap:
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = px / 24.0
    _DRAW[name](p, s, color)
    p.end()
    return pm


def nav_icon(name: str, off_color: str, on_color: str, px: int = 44) -> QIcon:
    """QIcon dua-state: Off (nav biasa) & On (nav aktif = warna aksen)."""
    ic = QIcon()
    off = _pixmap(name, off_color, px)
    on = _pixmap(name, on_color, px)
    ic.addPixmap(off, QIcon.Normal, QIcon.Off)
    ic.addPixmap(on, QIcon.Active, QIcon.Off)
    ic.addPixmap(on, QIcon.Normal, QIcon.On)
    ic.addPixmap(on, QIcon.Active, QIcon.On)
    return ic


def simple_icon(name: str, color: str, px: int = 44) -> QIcon:
    """QIcon satu warna (mis. tombol tema)."""
    return QIcon(_pixmap(name, color, px))
