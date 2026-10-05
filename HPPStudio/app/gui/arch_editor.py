"""Editor Arsitektur Sistem (gaya draw.io) — dibuka dari halaman Results.

Pengguna dapat:
  * menggambar arsitektur dari nol: seret/klik komponen dari palet, sambungkan
    (mode Connect: tarik dari satu komponen ke komponen lain; jenis kabel dipilih
    di toolbar: Auto / AC / DC / RS485 / TCP/IP / Wired / Wireless), ubah label &
    rating di panel properti, undo/redo, hapus;
  * langsung di kanvas: ubah panjang rel (tarik ujung rel), belokkan rute kabel
    (tarik kabel terpilih → titik belok; klik-ganda titik belok utk menghapus),
    gambar bentuk sendiri (Rectangle: tarik sudut utk ubah ukuran; Polygon:
    klik titik-titik, klik-ganda/Enter utk selesai, tarik verteks utk ubah);
  * mengimpor gambar arsitektur (PNG/JPG/PDF): sistem MENGENALI komponen &
    sambungan (lapisan teks PDF / OCR + analisis garis, lihat
    reports/arch_import.py) di proses latar, lalu menaruh hasilnya di atas
    gambar asli yang dipudarkan (underlay) untuk ditinjau/dikoreksi;
  * melihat PRATINJAU LAPORAN: sistem membaca topologi & menggambar ulang
    secara profesional (reports/arch_design.py) beserta catatan konsistensi
    terhadap konfigurasi simulasi.

Rancangan disimpan di cfg['arch_design'] (ikut tersimpan di berkas .hpps).
Tidak ada perhitungan/engine yang disentuh.
"""
from __future__ import annotations

import base64
import copy
import json
import math

import numpy as np
from PySide6.QtCore import (Qt, QPointF, QRectF, Signal, QTimer, QMimeData, QSize,
                            QObject, QEvent)
from PySide6.QtGui import (QPainter, QPen, QBrush, QColor, QFont, QPainterPath,
                           QPixmap, QImage, QDrag, QKeySequence, QShortcut,
                           QPainterPathStroker, QFontMetrics, QPolygonF)
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QGraphicsScene, QGraphicsView, QGraphicsObject,
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsItem, QSplitter, QWidget,
    QTabWidget, QScrollArea, QFormLayout, QLineEdit, QComboBox, QSpinBox,
    QCheckBox, QSlider, QFileDialog, QMessageBox, QGroupBox, QInputDialog,
    QProgressDialog, QAbstractItemView, QSizePolicy, QRadioButton, QButtonGroup,
    QFrame, QApplication, QLayout)

from ..config.i18n import tr
from .theme import tok
from .bgproc import ProcWorker

GRID = 10
MIME = 'application/x-hpp-arch-type'
# (kind, label EN) — urutan combo jenis kabel
CABLE_KINDS = [('ac', 'AC power'), ('dc', 'DC power'), ('rs485', 'RS485'),
               ('tcpip', 'TCP/IP (Ethernet)'), ('fo', 'Fibre optic (FO)'),
               ('can', 'CAN bus'), ('wired', 'Wired control'),
               ('wireless', 'Wireless')]


def _AD():
    from ..reports import arch_design
    return arch_design


def _lab(t):
    e = _AD().TYPES.get(t)
    return tr(e[0]) if e else t


def _mix(c1, c2, k):
    a, b = QColor(c1), QColor(c2)
    return QColor(int(a.red() * (1 - k) + b.red() * k),
                  int(a.green() * (1 - k) + b.green() * k),
                  int(a.blue() * (1 - k) + b.blue() * k))


def _dark():
    return QColor(tok('card')).lightness() < 110


def cable_pen(kind, auto=None, width_scale=1.0):
    """QPen utk jenis kabel (tema-aware)."""
    dk = _dark()
    if auto == 'suggested':
        col = QColor(tok('warn'))
    elif kind in ('ac', 'dc'):
        col = QColor(tok('fg'))
    elif kind == 'rs485':
        col = QColor('#A78BFA' if dk else '#7C3AED')
    elif kind == 'tcpip':
        col = QColor('#22D3EE' if dk else '#0E7490')
    elif kind == 'wireless':
        col = QColor('#F59E0B' if dk else '#B45309')
    elif kind == 'fo':
        col = QColor('#4ADE80' if dk else '#15803D')
    elif kind == 'can':
        col = QColor('#67E8F9' if dk else '#0891B2')
    else:
        col = QColor(tok('muted'))
    w = (1.6 if kind in ('ac', 'dc') else 1.4) * width_scale
    pen = QPen(col, w)
    if kind == 'dc':
        pen.setStyle(Qt.DashLine)
    elif kind == 'rs485':
        pen.setStyle(Qt.DashDotLine)
    elif kind == 'wired':
        pen.setStyle(Qt.DotLine)
    elif kind == 'wireless':
        pen.setDashPattern([3.0, 3.0])
    elif kind == 'fo':
        pen.setDashPattern([6.0, 1.5])
    elif kind == 'can':
        pen.setDashPattern([3.0, 1.2, 3.0, 3.2])
    return pen


def _draw_fit(p, rect, text, px0, bold=True, px_min=7):
    """Tulis teks rata tengah di dalam rect: dibungkus per kata, ukuran huruf
    diperkecil seperlunya; kata yang tetap terlalu panjang dipenggal ke baris
    berikutnya — teks tidak pernah keluar dari kartu."""
    words = str(text).split() or ['']
    flags = Qt.AlignCenter | Qt.TextWordWrap
    f = QFont('Segoe UI'); f.setBold(bold)
    px = max(px_min, int(px0))
    while True:
        f.setPixelSize(px)
        fm = QFontMetrics(f)
        longest = max(fm.horizontalAdvance(w) for w in words)
        br = fm.boundingRect(rect.toRect(), int(flags), text)
        if (longest <= rect.width() and br.height() <= rect.height()) or px <= px_min:
            break
        if longest > rect.width() and px <= max(px_min, int(px0 * 0.7)):
            # lebih baik memenggal kata daripada huruf terlalu kecil
            flags = Qt.AlignCenter | Qt.TextWrapAnywhere
            br = fm.boundingRect(rect.toRect(), int(flags), text)
            if br.height() <= rect.height():
                break
        px -= 1
    p.setFont(f)
    p.drawText(rect, flags, text)


def _snap(v):
    return round(v / GRID) * GRID


# ============================================================ item node =====
class NodeItem(QGraphicsObject):
    moved = Signal()
    geometry_done = Signal()

    def __init__(self, nid, ntype, label='', rating='', w=None, h=None, pts=None):
        super().__init__()
        self.nid, self.ntype = nid, ntype
        self.label, self.rating = label or '', rating or ''
        self.auto_rating = ''
        sk = self.shape_kind()
        self.bus_w = float(w or 420.0)
        self.rw = float(w or 220.0)
        self.rh = float(h or 140.0)
        self.pts = [QPointF(float(p[0]), float(p[1])) for p in (pts or [])] or \
            [QPointF(-90, -50), QPointF(90, -50), QPointF(110, 40), QPointF(0, 70),
             QPointF(-110, 40)]
        self.edges = []
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(-1 if sk in ('rect', 'polygon') else 2)
        self._hover = False
        self._drag = None                   # ('bus', side) | ('rect',) | ('vtx', i)

    # -- geometri --------------------------------------------------------
    def shape_kind(self):
        return _AD().TYPES[self.ntype][3]

    def card_size(self):
        """Ukuran kartu asli dari gambar impor (bw, bh) bila ada."""
        ex = getattr(self, 'extra', None) or {}
        try:
            bw, bh = float(ex.get('bw') or 0), float(ex.get('bh') or 0)
        except (TypeError, ValueError):
            bw = bh = 0.0
        return bw, bh

    def is_card(self):
        return self.shape_kind() in ('box', 'breaker', 'xfmr') and self.card_size()[0] > 0

    def is_panel(self):
        return self.shape_kind() == 'bus' and self.card_size()[1] > 0

    def set_extra(self, ex):
        self.prepareGeometryChange()
        self.extra = dict(ex or {})
        self.update()

    def size(self):
        s = self.shape_kind()
        if self.is_card():
            return self.card_size()
        if s == 'bus':
            return self.bus_w, (self.card_size()[1] if self.is_panel() else 16.0)
        if s == 'breaker':
            return 22.0, 22.0
        if s == 'xfmr':
            return 34.0, 46.0
        if s == 'text':
            fm = QFontMetrics(QFont('Segoe UI', 9))
            return max(60.0, fm.horizontalAdvance(self.label or _lab('text')) + 12.0), 22.0
        if s == 'rect':
            return self.rw, self.rh
        if s == 'polygon':
            r = QPolygonF(self.pts).boundingRect()
            return r.width(), r.height()
        return 150.0, 54.0

    def boundingRect(self):
        if self.shape_kind() == 'polygon':
            return QPolygonF(self.pts).boundingRect().adjusted(-8, -22, 8, 8)
        w, h = self.size()
        extra = 18 if self.shape_kind() == 'rect' else 3
        return QRectF(-w / 2 - 6, -h / 2 - extra, w + 12, h + extra + 6)

    def body(self):
        if self.shape_kind() == 'polygon':
            return QPolygonF(self.pts).boundingRect()
        w, h = self.size()
        return QRectF(-w / 2, -h / 2, w, h)

    def shape(self):
        sk = self.shape_kind()
        if sk in ('rect', 'polygon'):
            path = QPainterPath()
            if sk == 'rect':
                path.addRect(self.body())
            else:
                path.addPolygon(QPolygonF(self.pts + [self.pts[0]]))
            st = QPainterPathStroker(); st.setWidth(10)
            out = st.createStroke(path)
            lr = self._label_rect()
            if lr is not None:
                out.addRect(lr)
            return out
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def _label_rect(self):
        if not self.label.strip():
            return None
        fm = QFontMetrics(QFont('Segoe UI', 8))
        w = fm.horizontalAdvance(self.label) + 10
        if self.shape_kind() == 'rect':
            r = self.body()
            return QRectF(r.left() + 4, r.top() - 17, w, 15)
        br = QPolygonF(self.pts).boundingRect()
        return QRectF(br.left(), br.top() - 17, w, 15)

    def title(self):
        return self.label.strip() or _lab(self.ntype)

    # -- gambar ----------------------------------------------------------
    def paint(self, p, _opt, _w=None):
        AD = _AD()
        fam = AD.TYPES[self.ntype][2]
        col = QColor(AD.family_color(fam))
        fg, card, muted = QColor(tok('fg')), QColor(tok('card')), QColor(tok('muted'))
        s = self.shape_kind()
        r = self.body()
        p.setRenderHint(QPainter.Antialiasing, True)
        sel = self.isSelected()
        acc = QColor(tok('accent'))
        ex = getattr(self, 'extra', None) or {}
        stt = ex.get('status')
        if self.is_panel():                 # panel switchgear (dari gambar impor)
            pp = QPen(muted if stt == 'future' else fg, 1.3)
            if stt in ('existing', 'future'):
                pp.setStyle(Qt.DashLine)
            p.setPen(pp); p.setBrush(card)
            p.drawRoundedRect(r, 6, 6)
            yb = r.bottom() - 0.28 * r.height()
            p.setPen(Qt.NoPen); p.setBrush(QColor('#7C2D12') if self.ntype == 'dc_bus' else fg)
            p.drawRect(QRectF(r.left() + 8, yb - 3.5, r.width() - 16, 7))
            p.setPen(fg)
            rt = self.rating.strip() or self.auto_rating
            _draw_fit(p, QRectF(r.left() + 4, r.top() + 3, r.width() - 8, yb - r.top() - 8),
                      self.title() + (f' · {rt}' if rt else ''),
                      int(max(10, min(30, r.height() * 0.16))))
            if sel or self._hover:
                p.setPen(QPen(acc, 1.2)); p.setBrush(card)
                for x in (r.left(), r.right()):
                    p.drawRect(QRectF(x - 4, -6, 8, 12))
            return
        if self.is_card():                  # kartu (ukuran asli gambar impor)
            if stt == 'future':
                pc, fill = muted, _mix(card, muted, 0.06)
            else:
                pc, fill = col, _mix(card, col, 0.16)
            pen = QPen(pc, 1.5)
            if stt in ('existing', 'future'):
                pen.setStyle(Qt.DashLine)
            p.setPen(pen); p.setBrush(fill)
            p.drawRoundedRect(r, 8, 8)
            rt = self.rating.strip() or (self.auto_rating if self.ntype not in
                                         _AD().COMM_DEVICES else '')
            # huruf sebanding ukuran kartu → tetap terbaca saat tampilan dipaskan
            px = int(max(10, min(34, min(r.width(), r.height()) * 0.13)))
            p.setPen(fg)
            rh = px * 1.5 if rt else 0
            _draw_fit(p, QRectF(r.left() + 6, r.top() + 4, r.width() - 12,
                                r.height() - 8 - rh), self.title(), px)
            if rt:
                f2 = QFont('Segoe UI'); f2.setPixelSize(int(px * 0.78))
                f2.setItalic(not self.rating.strip())
                p.setFont(f2); p.setPen(muted)
                p.drawText(QRectF(r.left() + 4, r.bottom() - rh - 4, r.width() - 8, rh),
                           Qt.AlignHCenter | Qt.AlignVCenter, rt)
            if sel or self._hover:
                pen = QPen(acc, 1.3, Qt.DashLine if not sel else Qt.SolidLine)
                p.setPen(pen); p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), 9, 9)
            return
        if s == 'bus':
            bar = QRectF(r.left(), -3.5, r.width(), 7)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#7C2D12') if self.ntype == 'dc_bus' else fg)
            p.drawRect(bar)
            f = QFont('Segoe UI', 8); f.setBold(True); p.setFont(f)
            p.setPen(fg)
            p.drawText(QRectF(r.left(), -20, r.width(), 14), Qt.AlignLeft | Qt.AlignVCenter,
                       self.title())
            if sel or self._hover:          # pegangan ubah panjang di kedua ujung
                p.setPen(QPen(acc, 1.2)); p.setBrush(card)
                for x in (r.left(), r.right()):
                    p.drawRect(QRectF(x - 4, -6, 8, 12))
        elif s == 'breaker':
            p.setPen(QPen(fg, 1.2)); p.setBrush(card)
            p.drawRect(r.adjusted(2, 2, -2, -2))
            p.drawLine(r.topLeft() + QPointF(5, 5), r.bottomRight() - QPointF(5, 5))
        elif s == 'xfmr':
            p.setPen(QPen(fg, 1.3)); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(0, -7), 13, 13)
            p.drawEllipse(QPointF(0, 7), 13, 13)
        elif s == 'text':
            f = QFont('Segoe UI', 9); f.setItalic(True); p.setFont(f)
            p.setPen(muted)
            p.drawText(r, Qt.AlignCenter, self.title())
        elif s in ('rect', 'polygon'):
            fill = QColor(tok('fg')); fill.setAlpha(10)
            p.setBrush(fill)
            pen = QPen(acc if sel else muted, 1.3, Qt.DashLine)
            p.setPen(pen)
            if s == 'rect':
                p.drawRoundedRect(r, 6, 6)
            else:
                p.drawPolygon(QPolygonF(self.pts))
            if self.label.strip():
                f = QFont('Segoe UI', 8); f.setItalic(True); p.setFont(f)
                p.setPen(muted)
                p.drawText(self._label_rect(), Qt.AlignLeft | Qt.AlignVCenter, self.label)
            if sel:
                p.setPen(QPen(acc, 1.2)); p.setBrush(card)
                if s == 'rect':
                    p.drawRect(QRectF(r.right() - 5, r.bottom() - 5, 10, 10))
                else:
                    for q in self.pts:
                        p.drawRect(QRectF(q.x() - 4, q.y() - 4, 8, 8))
            return
        else:
            fill = _mix(card, col, 0.16)
            p.setPen(QPen(col, 1.4)); p.setBrush(fill)
            p.drawRoundedRect(r, 6, 6)
            f = QFont('Segoe UI', 9); f.setBold(True); p.setFont(f)
            p.setPen(fg)
            rt = self.rating.strip() or self.auto_rating
            p.drawText(QRectF(r.left() + 4, r.top() + 5, r.width() - 8, 22 if rt else r.height() - 10),
                       Qt.AlignHCenter | (Qt.AlignTop if rt else Qt.AlignVCenter),
                       self.title())
            if rt:
                f2 = QFont('Segoe UI', 8); f2.setItalic(not self.rating.strip())
                p.setFont(f2); p.setPen(muted)
                p.drawText(QRectF(r.left() + 4, r.top() + 27, r.width() - 8, 20),
                           Qt.AlignHCenter | Qt.AlignTop, rt)
        if (sel or self._hover) and s != 'bus':
            pen = QPen(acc, 1.3, Qt.DashLine if not sel else Qt.SolidLine)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), 7, 7)

    # -- interaksi langsung (resize rel/persegi, verteks poligon) ---------
    def _hit(self, lp):
        s = self.shape_kind()
        r = self.body()
        if s == 'bus':
            for side, x in (('l', r.left()), ('r', r.right())):
                if abs(lp.x() - x) <= 8 and abs(lp.y()) <= 9:
                    return ('bus', side)
        elif s == 'rect' and self.isSelected():
            if abs(lp.x() - r.right()) <= 9 and abs(lp.y() - r.bottom()) <= 9:
                return ('rect',)
        elif s == 'polygon' and self.isSelected():
            for i, q in enumerate(self.pts):
                if abs(lp.x() - q.x()) <= 7 and abs(lp.y() - q.y()) <= 7:
                    return ('vtx', i)
        return None

    def hoverMoveEvent(self, e):
        h = self._hit(e.pos())
        if h and h[0] == 'bus':
            self.setCursor(Qt.SizeHorCursor)
        elif h and h[0] == 'rect':
            self.setCursor(Qt.SizeFDiagCursor)
        elif h and h[0] == 'vtx':
            self.setCursor(Qt.CrossCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(e)

    def mousePressEvent(self, e):
        h = self._hit(e.pos()) if e.button() == Qt.LeftButton else None
        if h is not None:
            self._drag = h
            self._drag_anchor = (self.scenePos(), self.body())
            if not self.isSelected():
                self.scene().clearSelection(); self.setSelected(True)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            super().mouseMoveEvent(e)
            return
        sp = e.scenePos()
        kind = self._drag[0]
        self.prepareGeometryChange()
        if kind == 'bus':
            p0, r0 = self._drag_anchor
            left = p0.x() + r0.left()
            right = p0.x() + r0.right()
            if self._drag[1] == 'l':
                left = min(_snap(sp.x()), right - 60)
            else:
                right = max(_snap(sp.x()), left + 60)
            self.bus_w = right - left
            self.setPos(QPointF((left + right) / 2, p0.y()))
        elif kind == 'rect':
            p0, r0 = self._drag_anchor
            left, top = p0.x() + r0.left(), p0.y() + r0.top()
            right = max(_snap(sp.x()), left + 40)
            bottom = max(_snap(sp.y()), top + 30)
            self.rw, self.rh = right - left, bottom - top
            self.setPos(QPointF((left + right) / 2, (top + bottom) / 2))
        elif kind == 'vtx':
            lp = self.mapFromScene(QPointF(_snap(sp.x()), _snap(sp.y())))
            self.pts[self._drag[1]] = lp
        for ed in self.edges:
            ed.refresh()
        self.update()
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.geometry_done.emit()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.shape_kind() == 'polygon' and self.isSelected():
            h = self._hit(e.pos())
            if h and h[0] == 'vtx' and len(self.pts) > 3:
                self.prepareGeometryChange()
                del self.pts[h[1]]
                self.update(); self.geometry_done.emit()
                return
            # sisipkan verteks pada sisi terdekat
            lp = e.pos()
            best, bi = 1e18, None
            for i in range(len(self.pts)):
                a, b = self.pts[i], self.pts[(i + 1) % len(self.pts)]
                d = _seg_dist(lp, a, b)
                if d < best:
                    best, bi = d, i
            if bi is not None and best < 10:
                self.prepareGeometryChange()
                self.pts.insert(bi + 1, QPointF(_snap(lp.x()), _snap(lp.y())))
                self.update(); self.geometry_done.emit()
                return
        super().mouseDoubleClickEvent(e)

    def hoverEnterEvent(self, e):
        self._hover = True; self.update(); super().hoverEnterEvent(e)

    def hoverLeaveEvent(self, e):
        self._hover = False; self.unsetCursor(); self.update(); super().hoverLeaveEvent(e)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            return QPointF(_snap(value.x()), _snap(value.y()))
        if change == QGraphicsItem.ItemPositionHasChanged:
            for e in self.edges:
                e.refresh()
            self.moved.emit()
        return super().itemChange(change, value)

    # titik sambung ke arah titik lain
    def anchor_toward(self, other: QPointF):
        c = self.scenePos()
        w, h = self.size()
        if self.shape_kind() == 'bus' and not self.is_panel():
            x = min(max(other.x(), c.x() - w / 2 + 6), c.x() + w / 2 - 6)
            return QPointF(x, c.y()), 'v'
        # berhadapan dengan sisi kotak → sambung tegak lurus di titik itu
        # (sama dengan arch_design._anchor, agar editor = gambar laporan)
        if c.x() - w / 2 + 2 <= other.x() <= c.x() + w / 2 - 2 and abs(other.y() - c.y()) > h / 2:
            return QPointF(other.x(), c.y() + (h / 2 if other.y() > c.y() else -h / 2)), 'v'
        if c.y() - h / 2 + 2 <= other.y() <= c.y() + h / 2 - 2 and abs(other.x() - c.x()) > w / 2:
            return QPointF(c.x() + (w / 2 if other.x() > c.x() else -w / 2), other.y()), 'h'
        dx, dy = other.x() - c.x(), other.y() - c.y()
        if abs(dy) * w >= abs(dx) * h:
            return QPointF(c.x(), c.y() + (h / 2 if dy > 0 else -h / 2)), 'v'
        return QPointF(c.x() + (w / 2 if dx > 0 else -w / 2), c.y()), 'h'


def _seg_dist(p, a, b):
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p.x() - ax) * dx + (p.y() - ay) * dy) / L2))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(p.x() - qx, p.y() - qy)


# ============================================================ item edge =====
class EdgeItem(QGraphicsPathItem):
    def __init__(self, eid, a: NodeItem, b: NodeItem, kind='ac', auto=None, pts=None):
        super().__init__()
        self.eid, self.a, self.b, self.kind, self.auto = eid, a, b, kind, auto
        self.pts = [QPointF(float(q[0]), float(q[1])) for q in (pts or [])]
        a.edges.append(self); b.edges.append(self)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self._drag_i = None
        self._moved = False
        self.refresh()

    def polyline(self):
        """Titik-titik rute (ortogonal) dari a ke b melewati titik belok."""
        if not self.pts:
            pa, oa = self.a.anchor_toward(self.b.scenePos())
            pb, ob = self.b.anchor_toward(self.a.scenePos())
            pl = [pa]
            if oa == 'v' and ob == 'v':
                if abs(pa.x() - pb.x()) >= 1:
                    my = (pa.y() + pb.y()) / 2
                    pl += [QPointF(pa.x(), my), QPointF(pb.x(), my)]
            elif oa == 'h' and ob == 'h':
                mx = (pa.x() + pb.x()) / 2
                pl += [QPointF(mx, pa.y()), QPointF(mx, pb.y())]
            elif oa == 'v':
                pl.append(QPointF(pa.x(), pb.y()))
            else:
                pl.append(QPointF(pb.x(), pa.y()))
            pl.append(pb)
            return pl
        pa, oa = self.a.anchor_toward(self.pts[0])
        pb, ob = self.b.anchor_toward(self.pts[-1])
        seq = self.pts + [pb]
        pl = [pa]
        cur, d = pa, oa
        for idx, q in enumerate(seq):
            last = idx == len(seq) - 1
            if abs(cur.x() - q.x()) < 0.5 or abs(cur.y() - q.y()) < 0.5:
                pl.append(q)
            else:
                if last:
                    corner = QPointF(q.x(), cur.y()) if ob == 'v' else QPointF(cur.x(), q.y())
                else:
                    corner = QPointF(cur.x(), q.y()) if d == 'v' else QPointF(q.x(), cur.y())
                pl += [corner, q]
            cur = q
        return pl

    def refresh(self):
        pl = self.polyline()
        path = QPainterPath(pl[0])
        for q in pl[1:]:
            path.lineTo(q)
        self.setPath(path)
        self.update()

    def shape(self):
        st = QPainterPathStroker(); st.setWidth(10)
        return st.createStroke(self.path())

    def boundingRect(self):
        return super().boundingRect().adjusted(-8, -8, 8, 8)

    def paint(self, p, _opt, _w=None):
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = cable_pen(self.kind, self.auto)
        if any(n.is_card() or n.is_panel() for n in (self.a, self.b)):
            # rancangan skala gambar impor (besar): tebal garis tetap dalam piksel
            pen.setCosmetic(True); pen.setWidthF(1.6 if self.kind in ('ac', 'dc') else 1.3)
        if self.isSelected():
            p.setPen(QPen(QColor(tok('accent')), pen.widthF() + 2.4, Qt.SolidLine))
            p.drawPath(self.path())
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.path())
        if self.kind == 'wireless':            # penanda nirkabel di tengah rute
            pl = self.polyline()
            seg = max(zip(pl[:-1], pl[1:]),
                      key=lambda s_: abs(s_[0].x() - s_[1].x()) + abs(s_[0].y() - s_[1].y()))
            m = (seg[0] + seg[1]) / 2
            p.setPen(QPen(pen.color(), 1.2))
            for r_ in (4, 7):
                p.drawArc(QRectF(m.x() - r_, m.y() - r_, 2 * r_, 2 * r_), 45 * 16, 90 * 16)
            p.setBrush(pen.color()); p.drawEllipse(m, 1.8, 1.8)
        if self.isSelected():                  # pegangan titik belok
            p.setPen(QPen(QColor(tok('accent')), 1.2)); p.setBrush(QColor(tok('card')))
            for q in self.pts:
                p.drawRect(QRectF(q.x() - 4, q.y() - 4, 8, 8))

    # -- belokkan rute langsung di kanvas --------------------------------
    def _near_pt(self, sp):
        for i, q in enumerate(self.pts):
            if abs(sp.x() - q.x()) <= 7 and abs(sp.y() - q.y()) <= 7:
                return i
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isSelected():
            sp = e.scenePos()
            i = self._near_pt(sp)
            if i is None:
                # titik belok baru baru disisipkan saat kabel BENAR-BENAR ditarik
                self._pending = sp
                self._drag_i = None
                e.accept()
                return
            self._drag_i = i
            self._moved = False
            self.refresh()
            e.accept()
            return
        super().mousePressEvent(e)

    def _insert_at(self, sp):
        if True:
            if True:
                pl = self.polyline()
                best, bi = 1e18, 0
                # indeks sisip = jumlah titik belok yang dilewati sebelum segmen itu
                wp_index = []
                k = 0
                for a_, b_ in zip(pl[:-1], pl[1:]):
                    wp_index.append(k)
                    if k < len(self.pts) and (abs(b_.x() - self.pts[k].x()) < 0.5
                                              and abs(b_.y() - self.pts[k].y()) < 0.5):
                        k += 1
                for si, (a_, b_) in enumerate(zip(pl[:-1], pl[1:])):
                    d = _seg_dist(sp, a_, b_)
                    if d < best:
                        best, bi = d, wp_index[si]
                self.pts.insert(bi, QPointF(_snap(sp.x()), _snap(sp.y())))
                return bi

    def mouseMoveEvent(self, e):
        pend = getattr(self, '_pending', None)
        if pend is not None and self._drag_i is None:
            if (e.scenePos() - pend).manhattanLength() > 4:
                self.prepareGeometryChange()
                self._drag_i = self._insert_at(pend)
                self._pending = None
            else:
                e.accept()
                return
        if self._drag_i is not None:
            sp = e.scenePos()
            self.prepareGeometryChange()
            self.pts[self._drag_i] = QPointF(_snap(sp.x()), _snap(sp.y()))
            self._moved = True
            self.refresh()
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if getattr(self, '_pending', None) is not None:
            self._pending = None
            e.accept()
            return
        if self._drag_i is not None:
            self._drag_i = None
            if self.scene() is not None:
                self.scene().modified.emit()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        i = self._near_pt(e.scenePos())
        if i is not None:
            self.prepareGeometryChange()
            del self.pts[i]
            self.refresh()
            if self.scene() is not None:
                self.scene().modified.emit()
            return
        super().mouseDoubleClickEvent(e)

    def hoverMoveEvent(self, e):
        if self.isSelected():
            self.setCursor(Qt.SizeAllCursor if self._near_pt(e.scenePos()) is not None
                           else Qt.PointingHandCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(e)

    def detach(self):
        for n in (self.a, self.b):
            if self in n.edges:
                n.edges.remove(self)


# ============================================================ scene/view ====
class ArchScene(QGraphicsScene):
    modified = Signal()

    def __init__(self):
        super().__init__()
        self.nodes, self.edges = {}, {}
        self.underlay = None
        self._under_data = None
        self._seq = 0
        self.setSceneRect(-400, -300, 2200, 1500)

    def _new_id(self, pre):
        while True:
            self._seq += 1
            k = f'{pre}{self._seq}'
            if k not in self.nodes and k not in self.edges:
                return k

    def add_node(self, ntype, pos, nid=None, label='', rating='', w=None, emit=True,
                 h=None, pts=None):
        n = NodeItem(nid or self._new_id('n'), ntype, label, rating, w, h, pts)
        n.setPos(QPointF(_snap(pos.x()), _snap(pos.y())))
        n.geometry_done.connect(self.modified.emit)
        self.addItem(n)
        self.nodes[n.nid] = n
        if emit:
            self.modified.emit()
        return n

    def add_edge(self, a, b, kind=None, eid=None, auto=None, emit=True, pts=None):
        AD = _AD()
        if a is b or a.shape_kind() in ('rect', 'polygon', 'text') or \
                b.shape_kind() in ('rect', 'polygon', 'text'):
            return None
        kind = AD.effective_kind(kind, a.ntype, b.ntype) if kind else \
            AD.default_edge_kind(a.ntype, b.ntype)
        for e in self.edges.values():
            if {e.a, e.b} == {a, b} and (
                    (e.kind in AD.POWER_KINDS and kind in AD.POWER_KINDS) or e.kind == kind):
                return None                  # 1 jalur daya + 1 per jenis komunikasi
        e = EdgeItem(eid or self._new_id('e'), a, b, kind, auto, pts)
        self.addItem(e)
        self.edges[e.eid] = e
        if emit:
            self.modified.emit()
        return e

    def delete_items(self, items):
        changed = False
        for it in items:
            if isinstance(it, EdgeItem) and it.eid in self.edges:
                it.detach(); self.removeItem(it); del self.edges[it.eid]; changed = True
        for it in items:
            if isinstance(it, NodeItem) and it.nid in self.nodes:
                for e in list(it.edges):
                    e.detach(); self.removeItem(e); self.edges.pop(e.eid, None)
                self.removeItem(it); del self.nodes[it.nid]; changed = True
        if changed:
            self.modified.emit()

    def clear_all(self, keep_underlay=False):
        for it in list(self.edges.values()) + list(self.nodes.values()):
            self.removeItem(it)
        self.nodes.clear(); self.edges.clear()
        if not keep_underlay:
            self.set_underlay(None)

    # -- underlay --------------------------------------------------------
    def set_underlay(self, data):
        if self.underlay is not None:
            self.removeItem(self.underlay)
            self.underlay = None
        self._under_data = copy.deepcopy(data) if data else None
        if not data:
            return
        try:
            raw = base64.b64decode(data['png_b64'])
            img = QImage()
            img.loadFromData(raw, 'PNG')
            if _dark():                           # tema gelap → balik warna
                img = img.convertToFormat(QImage.Format_RGB32)
                img.invertPixels()
            pm = QPixmap.fromImage(img)
            pm = pm.scaled(int(data['w']), int(data['h']), Qt.IgnoreAspectRatio,
                           Qt.SmoothTransformation)
        except Exception:
            self._under_data = None
            return
        it = QGraphicsPixmapItem(pm)
        it.setPos(float(data.get('x', 0)), float(data.get('y', 0)))
        it.setOpacity(float(data.get('opacity', 0.35)))
        it.setZValue(-10)
        it.setVisible(bool(data.get('visible', True)))
        it.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.addItem(it)
        self.underlay = it

    def set_underlay_opacity(self, v):
        if self.underlay is not None and self._under_data:
            self.underlay.setOpacity(v); self._under_data['opacity'] = v

    def set_underlay_visible(self, v):
        if self.underlay is not None and self._under_data:
            self.underlay.setVisible(v); self._under_data['visible'] = bool(v)

    # -- serialisasi -----------------------------------------------------
    def to_design(self, use_in_report=True, source=None):
        nodes = []
        for n in self.nodes.values():
            d = dict(id=n.nid, type=n.ntype, label=n.label, rating=n.rating,
                     x=round(n.scenePos().x(), 1), y=round(n.scenePos().y(), 1))
            sk = n.shape_kind()
            if sk == 'bus':
                d['w'] = round(n.bus_w, 1)
            elif sk == 'rect':
                d['w'] = round(n.rw, 1); d['h'] = round(n.rh, 1)
            elif sk == 'polygon':
                d['pts'] = [[round(q.x(), 1), round(q.y(), 1)] for q in n.pts]
            d.update(getattr(n, 'extra', None) or {})
            nodes.append(d)
        edges = []
        for e in self.edges.values():
            d = dict(id=e.eid, src=e.a.nid, dst=e.b.nid, kind=e.kind)
            if e.auto:
                d['auto'] = e.auto
            if e.pts:
                d['pts'] = [[round(q.x(), 1), round(q.y(), 1)] for q in e.pts]
            d.update(getattr(e, 'extra', None) or {})
            edges.append(d)
        des = {'version': 1, 'use_in_report': bool(use_in_report),
               'nodes': nodes, 'edges': edges}
        if source:
            des['source'] = source
        if self._under_data:
            des['underlay'] = copy.deepcopy(self._under_data)
        return des

    def load_design(self, des):
        self.clear_all()
        des = des or {}
        AD = _AD()
        TYPES = AD.TYPES
        for d in des.get('nodes', []):
            if d.get('type') not in TYPES:
                continue
            n = self.add_node(d['type'], QPointF(float(d.get('x', 0)), float(d.get('y', 0))),
                              nid=str(d.get('id')), label=d.get('label', ''),
                              rating=d.get('rating', ''), w=d.get('w'), emit=False,
                              h=d.get('h'), pts=d.get('pts'))
            # data impor (ukuran kartu asli, status eksisting/rencana) ikut tersimpan
            n.set_extra({k: d[k] for k in ('bw', 'bh', 'status', 'desc') if k in d})
        for d in des.get('edges', []):
            a, b = self.nodes.get(str(d.get('src'))), self.nodes.get(str(d.get('dst')))
            if a and b:
                # migrasi: 'ctrl' → wired; 'daya' antar perangkat sejenis → RS485
                k = AD.effective_kind(d.get('kind'), a.ntype, b.ntype)
                e_ = self.add_edge(a, b, k, eid=str(d.get('id')), auto=d.get('auto'),
                                   emit=False, pts=d.get('pts'))
                if e_ is not None and d.get('ports'):
                    e_.extra = {'ports': d['ports']}     # titik sambung asli gambar
        ids = [k for k in list(self.nodes) + list(self.edges)]
        nums = [int(''.join(c for c in k if c.isdigit()) or 0) for k in ids]
        self._seq = max(nums + [0])
        self.set_underlay(des.get('underlay'))
        self.grow_rect()

    def grow_rect(self):
        """Perluas area kanvas agar seluruh rancangan (mis. hasil impor lembar
        besar) dapat digulir & dipaskan."""
        r = QRectF(-400, -300, 2200, 1500)
        if self.nodes or self.underlay is not None:
            r = r.united(self.itemsBoundingRect().adjusted(-600, -600, 600, 600))
        self.setSceneRect(r)


class ArchView(QGraphicsView):
    connect_done = Signal()
    polygon_done = Signal(object)
    zoomed = Signal()

    def __init__(self, scene: ArchScene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing
                            | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setAcceptDrops(True)
        self.mode = 'select'
        self.cable_kind = None                  # None = otomatis
        self._tmp = None
        self._src = None
        self._pan = None
        self._poly = []                          # titik poligon yang sedang digambar
        self._poly_item = None
        self.setMinimumSize(420, 320)

    def drawBackground(self, p, rect):
        p.fillRect(rect, QColor(tok('card')))
        col = QColor(tok('border'))
        p.setPen(QPen(col, 1))
        step = GRID * 2
        left = int(rect.left()) - int(rect.left()) % step
        top = int(rect.top()) - int(rect.top()) % step
        pts = []
        y = top
        while y < rect.bottom():
            x = left
            while x < rect.right():
                pts.append(QPointF(x, y))
                x += step
            y += step
        if len(pts) < 60000:
            p.drawPoints(pts)

    def drawForeground(self, p, rect):
        """Legenda gaya kabel (tetap di pojok kiri-bawah viewport)."""
        p.save()
        p.resetTransform()
        vp = self.viewport().rect()
        items = [(k, tr(lbl)) for k, lbl in CABLE_KINDS]
        f = QFont('Segoe UI', 8); p.setFont(f)
        fm = QFontMetrics(f)
        w = sum(fm.horizontalAdvance(t) + 42 for _k, t in items) + 8
        h = 22
        r = QRectF(8, vp.height() - h - 8, w, h)
        bg = QColor(tok('card')); bg.setAlpha(225)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor(tok('border')), 1)); p.setBrush(bg)
        p.drawRoundedRect(r, 5, 5)
        x = r.left() + 8
        yc = r.center().y()
        for k, t in items:
            p.setPen(cable_pen(k))
            p.drawLine(QPointF(x, yc), QPointF(x + 26, yc))
            p.setPen(QColor(tok('muted')))
            p.drawText(QPointF(x + 31, yc + fm.ascent() / 2 - 1), t)
            x += fm.horizontalAdvance(t) + 42
        p.restore()

    def set_mode(self, m):
        if self.mode == 'polygon' and m != 'polygon':
            self._cancel_poly()
        self.mode = m
        self.setDragMode(QGraphicsView.RubberBandDrag if m == 'select'
                         else QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.CrossCursor if m in ('connect', 'polygon')
                                  else Qt.ArrowCursor)
        for n in self.scene().nodes.values():
            n.setFlag(QGraphicsItem.ItemIsMovable, m == 'select')

    def _node_at(self, pos):
        for it in self.items(pos):
            if isinstance(it, NodeItem) and it.shape_kind() not in ('rect', 'polygon', 'text'):
                return it
        return None

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.scale(f, f)
            self.zoomed.emit()
            e.accept()
            return
        super().wheelEvent(e)

    # -- poligon -----------------------------------------------------------
    def _cancel_poly(self):
        if self._poly_item is not None:
            self.scene().removeItem(self._poly_item)
        self._poly_item = None
        self._poly = []

    def _draw_poly_tmp(self, cursor=None):
        pts = list(self._poly) + ([cursor] if cursor is not None else [])
        if self._poly_item is None:
            self._poly_item = QGraphicsPathItem()
            self._poly_item.setPen(QPen(QColor(tok('accent')), 1.3, Qt.DashLine))
            self._poly_item.setZValue(6)
            self.scene().addItem(self._poly_item)
        path = QPainterPath()
        if pts:
            path.moveTo(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
        self._poly_item.setPath(path)

    def finish_polygon(self):
        pts = self._poly
        self._cancel_poly()
        if len(pts) >= 3:
            self.polygon_done.emit(pts)

    def keyPressEvent(self, e):
        if self.mode == 'polygon' and e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.finish_polygon()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._pan = e.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if self.mode == 'polygon' and e.button() == Qt.LeftButton:
            sp = self.mapToScene(e.position().toPoint())
            self._poly.append(QPointF(_snap(sp.x()), _snap(sp.y())))
            self._draw_poly_tmp()
            return
        if self.mode == 'connect' and e.button() == Qt.LeftButton:
            n = self._node_at(e.position().toPoint())
            if n is not None:
                self._src = n
                path = QGraphicsPathItem()
                path.setPen(QPen(QColor(tok('accent')), 1.4, Qt.DashLine))
                path.setZValue(5)
                self.scene().addItem(path)
                self._tmp = path
            return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.mode == 'polygon':
            self.finish_polygon()
            return
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        if self.mode == 'polygon' and self._poly:
            sp = self.mapToScene(e.position().toPoint())
            self._draw_poly_tmp(QPointF(_snap(sp.x()), _snap(sp.y())))
            return
        if self._tmp is not None and self._src is not None:
            p = QPainterPath(self._src.scenePos())
            p.lineTo(self.mapToScene(e.position().toPoint()))
            self._tmp.setPath(p)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan is not None and e.button() == Qt.MiddleButton:
            self._pan = None
            self.viewport().setCursor(Qt.CrossCursor if self.mode in ('connect', 'polygon')
                                      else Qt.ArrowCursor)
            return
        if self.mode == 'polygon':
            return
        if self._tmp is not None:
            self.scene().removeItem(self._tmp)
            self._tmp = None
            dst = self._node_at(e.position().toPoint())
            if dst is not None and self._src is not None and dst is not self._src:
                self.scene().add_edge(self._src, dst, self.cable_kind)
            self._src = None
            self.connect_done.emit()
            return
        super().mouseReleaseEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            t = bytes(e.mimeData().data(MIME)).decode('utf-8')
            self.scene().add_node(t, self.mapToScene(e.position().toPoint()))
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class _Palette(QListWidget):
    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setIconSize(QSize(14, 14))

    def startDrag(self, _actions):
        it = self.currentItem()
        if it is None or not it.data(Qt.UserRole):
            return
        md = QMimeData()
        md.setData(MIME, it.data(Qt.UserRole).encode('utf-8'))
        dr = QDrag(self)
        dr.setMimeData(md)
        dr.exec(Qt.CopyAction)


# ============================================================ flow layout ==
class _FlowLayout(QLayout):
    """Tata letak mengalir: widget berjajar lalu turun baris bila lebar tak cukup
    (toolbar tetap utuh di layar kecil / skala DPI besar)."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRectF(0, 0, w, 0).toRect(), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        sz = QSize(0, 0)
        for it in self._items:
            sz = sz.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return sz + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        sp = self.spacing()
        for it in self._items:
            hint = it.sizeHint()
            nx = x + hint.width() + sp
            if nx - sp > rect.right() + 1 and line_h > 0:
                x = rect.x(); y += line_h + sp
                nx = x + hint.width() + sp; line_h = 0
            if not test:
                it.setGeometry(QRectF(x, y, hint.width(), hint.height()).toRect())
            x = nx
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


# ======================================================= proses latar impor ==
class _ImportWorker(ProcWorker):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, img, words):
        super().__init__()
        self.img = img
        self.words = words

    def run(self):
        try:
            from ..reports.arch_import import recognize_any
        except Exception:                      # dipanggil sbg modul absolut
            from app.reports.arch_import import recognize_any
        try:
            # lembar CAD berbingkai → hanya jendela utama; selain itu jalur biasa
            rec = recognize_any(self.img, self.words or None)
            self.finished_ok.emit(rec)
        except Exception as e:                 # pragma: no cover
            self.failed.emit(str(e))


# ============================================================ dialog =======
class ArchEditorDialog(QDialog):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle(tr('Arsitektur Sistem'))
        # jendela dapat di-maximize / full screen; ukuran awal mengikuti layar
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint
                            | Qt.WindowCloseButtonHint)
        self._fit_to_screen()
        self.scene = ArchScene()
        self.view = ArchView(self.scene)
        self._undo, self._redo = [], []
        self._source = None
        self._worker = None
        self._busy = None
        self._restoring = False
        self._prev_full = {}           # pixmap pratinjau ukuran penuh (utk skala ulang)
        self._original = None          # gambar asli (jendela utama) utk laporan
        self._report_fig = 'redrawn'   # 'redrawn' | 'original'
        self._layout = 'sld'           # 'sld' (otomatis) | 'drawing' (sesuai gambar)
        self._build()
        des = (state.cfg or {}).get('arch_design')
        if isinstance(des, dict) and (des.get('nodes') or des.get('original')):
            self.scene.load_design(des)
            self._source = des.get('source')
            self.chk_use.setChecked(bool(des.get('use_in_report', True)))
            if _AD().has_original(des):
                self._original = des.get('original')
            self._report_fig = des.get('report_figure', 'redrawn')
            self._layout = des.get('layout', 'sld')
        self._sync_choice()
        self._refresh_auto_ratings()
        self._fig0 = (self._report_fig, bool(self._original), self._layout)
        self._push_undo(initial=True)
        self._sync_underlay_ui()
        self.scene.modified.connect(self._on_modified)
        self.scene.selectionChanged.connect(self._on_selection)
        self.view.connect_done.connect(self._after_interaction)
        self.view.polygon_done.connect(self._polygon_done)
        self._mw = _MoveWatcher(self)
        self.view.viewport().installEventFilter(self._mw)
        QTimer.singleShot(0, self, self._fit_safe)

    def _fit_to_screen(self):
        """Ukuran awal = 92 % area layar yang tersedia (maks 1600×1000); layar
        kecil (≤ 1366×768 logis) langsung dibuka maksimal."""
        scr = (self.parent().screen() if self.parent() is not None else None) or \
            QApplication.primaryScreen()
        if scr is None:
            self.resize(1200, 760)
            return
        ag = scr.availableGeometry()
        w = min(1600, int(ag.width() * 0.92)); h = min(1000, int(ag.height() * 0.92))
        self.resize(max(640, w), max(420, h))
        self.move(ag.left() + (ag.width() - self.width()) // 2,
                  ag.top() + (ag.height() - self.height()) // 2)
        self._start_max = ag.width() <= 1400 or ag.height() <= 800

    # ------------------------------------------------------------- UI --
    def _build(self):
        lay = QVBoxLayout(self)
        # toolbar
        tbw = QWidget()                     # toolbar ringkas SATU BARIS
        tbw.setObjectName('ArchToolbar')
        tb = QHBoxLayout(tbw); tb.setContentsMargins(0, 0, 0, 0); tb.setSpacing(4)
        self.b_sel = QPushButton(tr('Select')); self.b_con = QPushButton(tr('Connect'))
        for b in (self.b_sel, self.b_con):
            b.setProperty('mode', True); b.setCheckable(True)
        self.b_sel.setChecked(True)
        self.b_sel.setToolTip(tr('Pilih & pindahkan komponen (V)'))
        self.b_con.setToolTip(tr('Tarik dari satu komponen ke komponen lain untuk '
                                 'menyambungkan (C)'))
        self.b_sel.clicked.connect(lambda: self._set_mode('select'))
        self.b_con.clicked.connect(lambda: self._set_mode('connect'))
        self.b_del = QPushButton(tr('Delete')); self.b_del.setProperty('flat', True)
        self.b_undo = QPushButton('↶'); self.b_undo.setProperty('flat', True)
        self.b_redo = QPushButton('↷'); self.b_redo.setProperty('flat', True)
        self.b_undo.setToolTip(tr('Undo') + ' (Ctrl+Z)'); self.b_redo.setToolTip(tr('Redo') + ' (Ctrl+Y)')
        self.b_del.clicked.connect(self._delete)
        self.b_undo.clicked.connect(self._do_undo)
        self.b_redo.clicked.connect(self._do_redo)
        self.b_imp = QPushButton(tr('Impor…'))
        self.b_imp.setToolTip(tr('Import Image / PDF…'))
        self.b_imp.setToolTip(tr('Impor gambar arsitektur (PNG/JPG/PDF). Sistem mengenali '
                                 'komponen & sambungan, lalu Anda dapat meninjau dan '
                                 'mengoreksinya.'))
        self.b_imp.clicked.connect(self._import)
        self.b_seed = QPushButton(tr('Dari konfigurasi'))
        self.b_seed.setToolTip(tr('Start from Configuration'))
        self.b_seed.setProperty('flat', True)
        self.b_seed.setToolTip(tr('Buat rancangan awal dari konfigurasi sistem di '
                                  'Parameters (dapat diedit).'))
        self.b_seed.clicked.connect(self._seed)
        self.b_clear = QPushButton(tr('Clear')); self.b_clear.setProperty('flat', True)
        self.b_clear.clicked.connect(self._clear)
        self.b_fit = QPushButton(tr('Fit')); self.b_fit.setProperty('flat', True)
        self.b_fit.clicked.connect(self._fit)
        self.b_route = QPushButton(tr('Rapikan rute')); self.b_route.setProperty('flat', True)
        self.b_route.setToolTip(tr('Rutekan ulang semua kabel secara ortogonal (tidak menembus '
                                   'kotak & tidak saling berimpit) — sama dengan gambar laporan.'))
        self.b_route.clicked.connect(self._auto_route)
        for w in (self.b_sel, self.b_con):
            tb.addWidget(w)
        self.cb_cable = QComboBox()
        self.cb_cable.addItem(tr('Kabel: otomatis'), None)
        for k, t in CABLE_KINDS:
            self.cb_cable.addItem(tr(t), k)
        self.cb_cable.setToolTip(tr('Jenis kabel untuk sambungan baru pada mode Connect. '
                                    'Otomatis: daya AC/DC menurut komponen; RS485 untuk '
                                    'EMS dan antar perangkat sejenis; TCP/IP untuk '
                                    'Ethernet Hub / Server.'))
        self.cb_cable.currentIndexChanged.connect(
            lambda _i: setattr(self.view, 'cable_kind', self.cb_cable.currentData()))
        tb.addWidget(self.cb_cable)
        for w in (self.b_del, self.b_undo, self.b_redo):
            tb.addWidget(w)
        tb.addWidget(self.b_imp); tb.addWidget(self.b_seed); tb.addWidget(self.b_clear)
        tb.addWidget(self.b_route)
        self.chk_under = QCheckBox(tr('Gambar impor'))
        self.chk_under.setToolTip(tr('Show imported image'))
        self.chk_under.toggled.connect(self.scene.set_underlay_visible)
        self.sl_op = QSlider(Qt.Horizontal); self.sl_op.setRange(5, 90)
        self.sl_op.setFixedWidth(60)
        self.sl_op.setToolTip(tr('Transparansi gambar impor'))
        self.sl_op.valueChanged.connect(lambda v: self.scene.set_underlay_opacity(v / 100.0))
        self.b_rm_under = QPushButton('✕'); self.b_rm_under.setProperty('flat', True)
        self.b_rm_under.setToolTip(tr('Remove image'))
        self.b_rm_under.clicked.connect(self._remove_underlay)
        for w in (self.chk_under, self.sl_op, self.b_rm_under):
            tb.addWidget(w)
        tb.insertStretch(tb.indexOf(self.chk_under), 1)
        tb.addWidget(self.b_fit)
        # gaya ringkas (padding kecil) — hanya utk toolbar ini
        tbw.setStyleSheet('#ArchToolbar QPushButton { padding: 3px 9px; min-height: 22px; }'
                          '#ArchToolbar QComboBox { padding: 2px 6px; min-height: 22px; }')
        self.cb_cable.setMaximumWidth(150)
        self.cb_cable.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_cable.setMinimumContentsLength(10)
        # tetap satu baris: bila jendela lebih sempit dari toolbar, toolbar dapat
        # digeser horizontal (tidak memaksa jendela melebihi layar)
        tbs = QScrollArea(); tbs.setWidget(tbw); tbs.setWidgetResizable(True)
        tbs.setFrameShape(QFrame.NoFrame)
        tbs.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tbs.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        tbs.setFixedHeight(tbw.sizeHint().height() + 4)
        tbs.setStyleSheet('QScrollArea { background: transparent; }')
        tbs.viewport().setAutoFillBackground(False)
        tbw.setAutoFillBackground(False)
        lay.addWidget(tbs)

        split = QSplitter(Qt.Horizontal)
        # palet
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0)
        hl = QLabel(tr('Komponen')); hl.setObjectName('GroupTitle')
        lv.addWidget(hl)
        self.pal = _Palette()
        from ..config.i18n import get_language
        en = get_language() == 'EN'
        for (grp_id, grp_en), types in _AD().PALETTE:
            h = QListWidgetItem(grp_en if en else grp_id)
            h.setFlags(Qt.NoItemFlags)
            f = h.font(); f.setBold(True); h.setFont(f)
            self.pal.addItem(h)
            for t in types:
                it = QListWidgetItem('   ' + _lab(t))
                it.setData(Qt.UserRole, t)
                it.setToolTip(tr('Klik untuk menambah, atau seret ke kanvas'))
                self.pal.addItem(it)
        self.pal.itemClicked.connect(self._palette_click)
        lv.addWidget(self.pal)
        hint = QLabel(tr('Seret komponen ke kanvas. Mode Connect: tarik dari satu '
                         'komponen ke komponen lain. Ctrl+scroll = zoom, tombol '
                         'tengah = geser.'))
        hint.setWordWrap(True); hint.setObjectName('PageSub')
        lv.addWidget(hint)
        left.setMinimumWidth(140); left.setMaximumWidth(240)
        split.addWidget(left)

        # tab kanvas & pratinjau
        self.tabs = QTabWidget()
        self.tabs.addTab(self.view, tr('Desain'))
        prev = QWidget(); pv = QVBoxLayout(prev)
        top = QHBoxLayout()
        pt = QLabel(tr('Pilih gambar arsitektur yang dimuat di laporan — bandingkan kedua '
                       'pratinjau:'))
        pt.setObjectName('PageSub')
        top.addWidget(pt); top.addStretch(1)
        b_ref = QPushButton(tr('Refresh')); b_ref.setProperty('flat', True)
        b_ref.clicked.connect(self._refresh_preview)
        top.addWidget(b_ref)
        pv.addLayout(top)
        self.fig_group = QButtonGroup(self)
        cmp_ = QSplitter(Qt.Horizontal)
        self.prev_panes = {}
        for key, title, sub in (
                ('original', tr('Gambar asli'),
                 tr('Diagram jendela utama gambar impor, apa adanya (blok judul, label '
                    'grid & legenda gambar tidak dimuat; legenda warna dirangkum ulang).')),
                ('redrawn', tr('Topologi digambar ulang'),
                 tr('Komponen & sambungan hasil pembacaan, digambar ulang otomatis '
                    'dalam format diagram satu garis standar laporan.'))):
            fr = QFrame(); fr.setObjectName('Card')
            fl = QVBoxLayout(fr); fl.setContentsMargins(8, 8, 8, 8)
            rb = QRadioButton(title)
            f = rb.font(); f.setBold(True); rb.setFont(f)
            self.fig_group.addButton(rb)
            rb.toggled.connect(lambda on, k=key: on and self._choose_fig(k))
            fl.addWidget(rb)
            sl = QLabel(sub); sl.setWordWrap(True); sl.setObjectName('PageSub')
            fl.addWidget(sl)
            if key == 'redrawn':
                row = QHBoxLayout()
                row.addWidget(QLabel(tr('Tata letak:')))
                self.cb_layout = QComboBox()
                self.cb_layout.addItem(tr('Sesuai gambar (posisi blok dipertahankan)'),
                                       'drawing')
                self.cb_layout.addItem(tr('Diagram satu garis otomatis'), 'sld')
                self.cb_layout.currentIndexChanged.connect(self._layout_changed)
                row.addWidget(self.cb_layout, 1)
                fl.addLayout(row)
            sc = QScrollArea(); sc.setWidgetResizable(True)
            lbl = QLabel(); lbl.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            lbl.setWordWrap(True)
            lbl.setStyleSheet('background: #FFFFFF; color: #555555; padding: 6px;')
            sc.setWidget(lbl)
            fl.addWidget(sc, 1)
            cmp_.addWidget(fr)
            self.prev_panes[key] = (rb, lbl, fr)
        self.prev_lbl = self.prev_panes['redrawn'][1]       # kompatibel
        pv.addWidget(cmp_, 3)
        nl = QLabel(tr('Pembacaan topologi & catatan konsistensi')); nl.setObjectName('GroupTitle')
        pv.addWidget(nl)
        self.notes = QListWidget(); self.notes.setWordWrap(True)
        pv.addWidget(self.notes, 1)
        self.tabs.addTab(prev, tr('Pratinjau Laporan'))
        self.tabs.currentChanged.connect(lambda i: i == 1 and self._refresh_preview())
        split.addWidget(self.tabs)

        # properti
        right = QGroupBox(tr('Properti'))
        self.form = QFormLayout(right)
        self.p_type = QLabel('-')
        self.p_label = QLineEdit(); self.p_label.setPlaceholderText(tr('(otomatis)'))
        self.p_rating = QLineEdit()
        self.p_kind = QComboBox()
        for k, t in CABLE_KINDS:
            self.p_kind.addItem(tr(t), k)
        self.p_reset = QPushButton(tr('Reset route'))
        self.p_reset.setProperty('flat', True)
        self.p_accept = QPushButton(tr('Accept suggestion'))
        self.p_accept.setProperty('flat', True)
        self.form.addRow(tr('Jenis'), self.p_type)
        self.form.addRow(tr('Label'), self.p_label)
        self.form.addRow(tr('Rating'), self.p_rating)
        self.form.addRow(tr('Sambungan'), self.p_kind)
        self.form.addRow('', self.p_reset)
        self.form.addRow('', self.p_accept)
        self.p_info = QLabel(''); self.p_info.setWordWrap(True); self.p_info.setObjectName('PageSub')
        self.form.addRow(self.p_info)
        self.p_label.editingFinished.connect(self._apply_props)
        self.p_rating.editingFinished.connect(self._apply_props)
        self.p_reset.clicked.connect(self._reset_route)
        self.p_kind.activated.connect(lambda _i: self._apply_props())
        self.p_accept.clicked.connect(self._accept_suggestion)
        right.setMinimumWidth(190); right.setMaximumWidth(300)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)

        # bawah
        bot = QHBoxLayout()
        self.chk_use = QCheckBox(tr('Gunakan arsitektur ini pada laporan studi kelayakan'))
        self.chk_use.setChecked(True)
        bot.addWidget(self.chk_use)
        self.status = QLabel(''); self.status.setObjectName('PageSub')
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        bot.addWidget(self.status, 1)
        b_cancel = QPushButton(tr('Batal')); b_cancel.setProperty('flat', True)
        b_save = QPushButton(tr('Simpan'))
        b_cancel.clicked.connect(self.reject)
        b_save.clicked.connect(self._save)
        bot.addWidget(b_cancel); bot.addWidget(b_save)
        lay.addLayout(bot)

        for seq, fn in ((QKeySequence.Delete, self._delete),
                        (QKeySequence.Undo, self._do_undo),
                        (QKeySequence.Redo, self._do_redo),
                        (QKeySequence('Ctrl+Y'), self._do_redo),
                        (QKeySequence('V'), lambda: self._set_mode('select')),
                        (QKeySequence('C'), lambda: self._set_mode('connect')),
                        (QKeySequence('Escape'), lambda: self._set_mode('select')),
                        (QKeySequence.SelectAll, self._select_all)):
            sc_ = QShortcut(seq, self); sc_.activated.connect(fn)
        self._on_selection()

    # ---------------------------------------------------------- helper --
    def _load_stats(self):
        st = {}
        r = getattr(self.state, 'last_result', None)
        try:
            if r and r.get('kpi'):
                st['energy_kwh'] = float(r['kpi'].get('annual_load_kwh') or 0) or None
                s = r.get('series') or {}
                if 'load' in s:
                    a = np.asarray(s['load'], float)
                    st['peak_kw'] = float(np.max(a.reshape(len(a), -1)[:, 0]))
            elif getattr(self.state, 'load', None) is not None:
                a = np.asarray(self.state.load, float)
                st['peak_kw'] = float(a.max())
                if a.size in (8760, 8784):
                    st['energy_kwh'] = float(a.sum())
        except Exception:
            pass
        return st

    def _refresh_auto_ratings(self):
        AD = _AD()
        by = {}
        for n in sorted(self.scene.nodes.values(), key=lambda n: (n.scenePos().x(), n.scenePos().y())):
            by.setdefault(n.ntype, []).append(n)
        ls = self._load_stats()
        cfg = self.state.cfg or {}
        for t, lst in by.items():
            for i, n in enumerate(lst):
                try:
                    n.auto_rating = AD.auto_rating(t, i, len(lst), cfg, ls)
                except Exception:
                    n.auto_rating = ''
                n.update()

    def _design(self):
        d = self.scene.to_design(self.chk_use.isChecked(), self._source)
        if self._original:
            d['original'] = self._original
        d['report_figure'] = self._report_fig if self._original else 'redrawn'
        d['layout'] = self._layout
        return d

    def _set_mode(self, m):
        self.view.set_mode(m)
        self.b_sel.setChecked(m == 'select'); self.b_con.setChecked(m == 'connect')
        if m == 'polygon':
            self.status.setText(tr('Mode Polygon: klik titik-titik sudut; klik-ganda atau '
                                   'Enter untuk selesai, Esc untuk batal.'))
        else:
            self._update_status()

    def _polygon_done(self, pts):
        cx = sum(q.x() for q in pts) / len(pts)
        cy = sum(q.y() for q in pts) / len(pts)
        c = QPointF(_snap(cx), _snap(cy))
        rel = [[q.x() - c.x(), q.y() - c.y()] for q in pts]
        n = self.scene.add_node('polygon', c, pts=rel)
        self._set_mode('select')
        self.scene.clearSelection(); n.setSelected(True)

    def _reset_route(self):
        for it in self.scene.selectedItems():
            if isinstance(it, EdgeItem) and it.pts:
                it.prepareGeometryChange(); it.pts = []; it.refresh()
        self._on_modified(); self._on_selection()

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, '_fitted', False):
            self._fitted = True
            if getattr(self, '_start_max', False) and not self.isMaximized():
                QTimer.singleShot(0, self, self.showMaximized)
            QTimer.singleShot(0, self, self._fit_safe)   # paskan tampilan saat dibuka

    def _fit_safe(self):
        try:
            self._fit()
        except RuntimeError:                           # dialog sudah ditutup
            pass

    def _fit(self):
        self.scene.grow_rect()
        items = [i for i in self.scene.items() if i.isVisible()]
        if not items:
            self.view.resetTransform()
            self.view.centerOn(400, 250)
            return
        its = list(self.scene.nodes.values()) + list(self.scene.edges.values())
        if its:
            r = its[0].sceneBoundingRect()
            for it in its[1:]:
                r = r.united(it.sceneBoundingRect())
            r = r.adjusted(-60, -60, 60, 60)
        else:
            r = self.scene.itemsBoundingRect().adjusted(-60, -60, 60, 60)
        if self.scene.underlay is not None and self.scene.underlay.isVisible():
            r = r.united(self.scene.underlay.sceneBoundingRect())
        self.view.fitInView(r, Qt.KeepAspectRatio)
        if self.view.transform().m11() > 1.4:
            self.view.resetTransform(); self.view.scale(1.4, 1.4)
            self.view.centerOn(r.center())

    def _palette_click(self, it):
        t = it.data(Qt.UserRole)
        if not t:
            return
        if t == 'polygon':                  # gambar poligon dengan klik di kanvas
            self._set_mode('polygon')
            return
        c = self.view.mapToScene(self.view.viewport().rect().center())
        off = (len(self.scene.nodes) % 6) * 20
        n = self.scene.add_node(t, QPointF(c.x() + off, c.y() + off))
        self.scene.clearSelection(); n.setSelected(True)

    def _select_all(self):
        for it in list(self.scene.nodes.values()) + list(self.scene.edges.values()):
            it.setSelected(True)

    def _delete(self):
        if self.tabs.currentIndex() != 0:
            return
        if self.focusWidget() in (self.p_label, self.p_rating):
            return
        self.scene.delete_items(self.scene.selectedItems())

    # ------------------------------------------------------- undo/redo --
    def _snap(self):
        """Snapshot JSON rancangan; data gambar underlay diganti hash (hemat)."""
        d = self._design()
        d.pop('original', None); d.pop('report_figure', None)   # di luar undo
        d.pop('layout', None)
        u = d.get('underlay')
        if u:
            import hashlib
            h = hashlib.md5(u['png_b64'].encode('ascii')).hexdigest()
            self._under_store = getattr(self, '_under_store', {})
            self._under_store[h] = u['png_b64']
            d['underlay'] = dict(u, png_b64='#' + h)
        return json.dumps(d, sort_keys=True)

    def _push_undo(self, initial=False):
        s = self._snap()
        if self._undo and self._undo[-1] == s:
            return
        self._undo.append(s)
        if len(self._undo) > 80:
            self._undo.pop(0)
        if not initial:
            self._redo.clear()
        self._update_status()

    def _restore(self, s):
        self._restoring = True
        try:
            d = json.loads(s)
            u = d.get('underlay')
            if u and str(u.get('png_b64', '')).startswith('#'):
                u['png_b64'] = getattr(self, '_under_store', {}).get(u['png_b64'][1:], '')
                if not u['png_b64']:
                    d.pop('underlay', None)
            self.scene.load_design(d)
            self.chk_use.setChecked(bool(d.get('use_in_report', True)))
            self._source = d.get('source')
            self._set_mode(self.view.mode)
            self._refresh_auto_ratings()
            self._sync_underlay_ui()
        finally:
            self._restoring = False
        self._update_status()

    def _do_undo(self):
        if len(self._undo) > 1:
            self._redo.append(self._undo.pop())
            self._restore(self._undo[-1])

    def _do_redo(self):
        if self._redo:
            s = self._redo.pop()
            self._undo.append(s)
            self._restore(s)

    def _on_modified(self):
        if self._restoring:
            return
        self._refresh_auto_ratings()
        self._push_undo()

    def _after_interaction(self):
        self._push_undo()

    def _update_status(self):
        nn = len([n for n in self.scene.nodes.values() if n.ntype != 'text'])
        ne = len(self.scene.edges)
        ns = len([e for e in self.scene.edges.values() if e.auto == 'suggested'])
        txt = tr('{n} komponen · {e} sambungan').format(n=nn, e=ne)
        if ns:
            txt += ' · ' + tr('{s} saran (kuning) perlu ditinjau').format(s=ns)
        if self._original:
            txt += ' · ' + (tr('Laporan: gambar asli') if self._report_fig == 'original'
                            else tr('Laporan: topologi digambar ulang'))
        self.status.setText(txt)
        self.b_undo.setEnabled(len(self._undo) > 1)
        self.b_redo.setEnabled(bool(self._redo))

    # ------------------------------------------------------- properti --
    def _on_selection(self):
        try:
            sel = self.scene.selectedItems()
        except RuntimeError:                       # scene sudah dihapus (dialog ditutup)
            return
        node = sel[0] if len(sel) == 1 and isinstance(sel[0], NodeItem) else None
        edge = sel[0] if len(sel) == 1 and isinstance(sel[0], EdgeItem) else None
        for w in (self.p_label, self.p_rating, self.p_kind, self.p_accept, self.p_reset):
            w.setEnabled(False)
        self.p_accept.setVisible(False)
        self.p_reset.setVisible(False)
        self.p_info.setText('')
        if node is not None:
            self.p_type.setText(_lab(node.ntype))
            self.p_label.setEnabled(True); self.p_label.setText(node.label)
            self.p_label.setPlaceholderText(_lab(node.ntype))
            sk = node.shape_kind()
            self.p_rating.setEnabled(sk not in ('bus', 'breaker', 'text', 'rect', 'polygon'))
            self.p_rating.setText(node.rating)
            self.p_rating.setPlaceholderText(node.auto_rating or tr('(opsional)'))
            if sk == 'bus':
                self.p_info.setText(tr('Tarik ujung rel di kanvas untuk mengubah panjangnya.'))
            elif sk == 'rect':
                self.p_info.setText(tr('Tarik sudut kanan-bawah untuk mengubah ukuran. '
                                       'Komponen di dalam bentuk ditampilkan sebagai grup '
                                       'berlabel pada laporan.'))
            elif sk == 'polygon':
                self.p_info.setText(tr('Tarik verteks untuk mengubah bentuk; klik-ganda sisi '
                                       'untuk menambah verteks, klik-ganda verteks untuk '
                                       'menghapus. Komponen di dalamnya menjadi grup berlabel '
                                       'pada laporan.'))
            if node.auto_rating:
                self.p_info.setText(tr('Kosongkan rating untuk memakai nilai dari '
                                       'Parameters: {r}').format(r=node.auto_rating))
        elif edge is not None:
            self.p_type.setText(tr('Sambungan') + f': {edge.a.title()} — {edge.b.title()}')
            self.p_kind.setEnabled(True)
            self.p_kind.setCurrentIndex(max(0, self.p_kind.findData(edge.kind)))
            self.p_reset.setVisible(True); self.p_reset.setEnabled(bool(edge.pts))
            self.p_info.setText(tr('Tarik kabel untuk menambah titik belok; tarik titik '
                                   'belok untuk memindahkan, klik-ganda untuk menghapus.'))
            if edge.auto == 'suggested':
                self.p_accept.setVisible(True); self.p_accept.setEnabled(True)
                self.p_info.setText(tr('Sambungan ini disarankan dari tata letak (tanpa '
                                       'bukti garis di gambar). Terima atau hapus.'))
        else:
            self.p_type.setText(tr('{n} item dipilih').format(n=len(sel)) if sel else '-')
            self.p_label.clear(); self.p_rating.clear()

    def _apply_props(self):
        sel = self.scene.selectedItems()
        if len(sel) != 1:
            return
        it = sel[0]
        changed = False
        if isinstance(it, NodeItem):
            lab, rat = self.p_label.text().strip(), self.p_rating.text().strip()
            if lab != it.label or rat != it.rating:
                it.label, it.rating = lab, rat; changed = True
            it.prepareGeometryChange()
            it.update()
        elif isinstance(it, EdgeItem):
            k = self.p_kind.currentData()
            if k != it.kind:
                AD = _AD()
                # satu sambungan daya + satu komunikasi boleh pada pasangan yang sama
                dup = [e for e in self.scene.edges.values() if e is not it
                       and {e.a, e.b} == {it.a, it.b}
                       and (e.kind in AD.COMM_KINDS) == (k in AD.COMM_KINDS)]
                if not dup:
                    it.kind = k; it.update(); changed = True
        if changed:
            self._on_modified()

    def _accept_suggestion(self):
        for it in self.scene.selectedItems():
            if isinstance(it, EdgeItem) and it.auto == 'suggested':
                it.auto = 'accepted'; it.update()
        self._on_modified(); self._on_selection()

    # ---------------------------------------------------------- aksi ----
    def _seed(self):
        if self.scene.nodes and QMessageBox.question(
                self, tr('Arsitektur Sistem'),
                tr('Ganti rancangan saat ini dengan rancangan dari konfigurasi?')) \
                != QMessageBox.Yes:
            return
        d = _AD().seed_from_config(self.state.cfg or {})
        d['use_in_report'] = self.chk_use.isChecked()
        self._source = {'kind': 'config'}
        self.scene.load_design(d)
        self._set_mode('select')
        self._refresh_auto_ratings(); self._sync_underlay_ui()
        self._push_undo(); self._fit()

    def _clear(self):
        if not self.scene.nodes and self.scene.underlay is None:
            return
        if QMessageBox.question(self, tr('Arsitektur Sistem'),
                                tr('Hapus seluruh isi kanvas?')) != QMessageBox.Yes:
            return
        self.scene.clear_all(); self._source = None
        self._original = None; self._report_fig = 'redrawn'; self._sync_choice()
        self._sync_underlay_ui(); self._push_undo()

    def _remove_underlay(self):
        self.scene.set_underlay(None); self._sync_underlay_ui(); self._push_undo()

    def _sync_underlay_ui(self):
        has = self.scene.underlay is not None
        for w in (self.chk_under, self.sl_op, self.b_rm_under):
            w.setVisible(has)
        if has:
            d = self.scene._under_data or {}
            self.chk_under.blockSignals(True); self.sl_op.blockSignals(True)
            self.chk_under.setChecked(bool(d.get('visible', True)))
            self.sl_op.setValue(int(round(float(d.get('opacity', 0.35)) * 100)))
            self.chk_under.blockSignals(False); self.sl_op.blockSignals(False)

    # ------------------------------------------------------- impor ------
    def _import(self):
        path, _f = QFileDialog.getOpenFileName(
            self, tr('Impor Gambar Arsitektur'), '',
            tr('Gambar & PDF') + ' (*.png *.jpg *.jpeg *.bmp *.pdf);;'
            + tr('Semua berkas (*)'))
        if not path:
            return
        try:
            img, words, name = self._load_file(path)
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))
            return
        if img is None:
            return
        if not words:
            self._ensure_ocr()          # OCR terbawa butuh onnxruntime di environment
        self._pending = (img, name)
        self._busy = QProgressDialog(tr('Mengenali komponen & sambungan…'),
                                     tr('Batal'), 0, 0, self)
        self._busy.setWindowTitle(tr('Impor Gambar Arsitektur'))
        self._busy.setWindowModality(Qt.WindowModal)
        self._busy.setMinimumDuration(0)
        self._busy.canceled.connect(self._cancel_import)
        self._worker = _ImportWorker(img, words)
        self._worker.finished_ok.connect(self._import_done)
        self._worker.failed.connect(self._import_failed)
        self._worker.start()
        self._busy.show()

    def _ensure_ocr(self):
        """OCR terbawa (app/ocr) hanya perlu paket onnxruntime. Bila belum ada di
        environment yang menjalankan aplikasi, tawarkan pemasangan otomatis."""
        import sys
        from ..reports import arch_import as AI
        if AI.ocr_engine() is not None or getattr(sys, 'frozen', False):
            return True
        why = AI.ocr_error()
        if QMessageBox.question(
                self, tr('Impor Gambar Arsitektur'),
                tr('OCR terbawa HPP Studio memerlukan paket "onnxruntime" yang belum '
                   'terpasang pada Python yang menjalankan aplikasi ini:\n{py}\n\n'
                   'Pasang sekarang (± 15 MB, sekali saja)? Tanpa OCR, gambar tetap '
                   'diimpor tetapi teks komponen tidak terbaca.').format(py=sys.executable)
                + ('\n\n' + tr('Detail: {e}').format(e=why) if why else '')) \
                != QMessageBox.Yes:
            return False
        from PySide6.QtCore import QProcess
        dlg = QProgressDialog(tr('Memasang onnxruntime…'), None, 0, 0, self)
        dlg.setWindowTitle(tr('Impor Gambar Arsitektur'))
        dlg.setWindowModality(Qt.WindowModal); dlg.setMinimumDuration(0); dlg.show()
        pr = QProcess(self)
        pr.setProcessChannelMode(QProcess.MergedChannels)
        pr.start(sys.executable, ['-m', 'pip', 'install', 'onnxruntime>=1.16'])
        out = []
        while not pr.waitForFinished(150):
            out.append(bytes(pr.readAll()).decode('utf-8', 'replace'))
            QApplication.processEvents()
            if pr.state() == QProcess.NotRunning:
                break
        out.append(bytes(pr.readAll()).decode('utf-8', 'replace'))
        dlg.close()
        AI._RAPID = None                               # muat ulang mesin OCR
        try:
            from .. import ocr as _mini
            _mini._ENGINE = None
        except Exception:
            pass
        if pr.exitCode() == 0 and AI.ocr_engine() is not None:
            return True
        tail = '\n'.join(''.join(out).strip().splitlines()[-6:])
        QMessageBox.warning(self, tr('Impor Gambar Arsitektur'),
                            tr('Pemasangan onnxruntime gagal. Jalankan manual:\n'
                               '"{py}" -m pip install onnxruntime').format(py=sys.executable)
                            + ('\n\n' + tail if tail else ''))
        return False

    def _load_file(self, path):
        import os
        from ..reports import arch_import as AI
        name = os.path.basename(path)
        if path.lower().endswith('.pdf'):
            try:
                from PySide6.QtPdf import QPdfDocument
            except Exception:
                raise RuntimeError(tr('Modul QtPdf tidak tersedia pada instalasi '
                                      'PySide6 ini; ekspor PDF ke PNG lalu impor '
                                      'gambarnya.'))
            doc = QPdfDocument(self)
            doc.load(path)
            n = doc.pageCount()
            if n <= 0:
                raise RuntimeError(tr('PDF tidak dapat dibaca.'))
            page = 0
            if n > 1:
                # sarankan halaman yang paling banyak berisi garis berwarna/diagram
                # (halaman pertama gambar CAD sering hanya sampul)
                best, best_sc = 0, -1.0
                for i_ in range(min(n, 30)):
                    try:
                        ps = doc.pagePointSize(i_)
                        im_ = doc.render(i_, QSize(max(1, int(ps.width() * 40 / 72)),
                                                   max(1, int(ps.height() * 40 / 72))))
                        a_ = self._qimage_rgb(im_).astype(np.int16)
                        sat = (a_.max(2) - a_.min(2)) > 60
                        sc_ = float(sat.mean()) * 10.0 + float((a_.min(2) < 160).mean())
                    except Exception:
                        sc_ = 0.0
                    if sc_ > best_sc:
                        best, best_sc = i_, sc_
                v, ok = QInputDialog.getInt(
                    self, tr('Impor Gambar Arsitektur'),
                    tr('Halaman PDF yang berisi arsitektur (disarankan: {p}):').format(p=best + 1),
                    best + 1, 1, n)
                if not ok:
                    return None, None, name
                page = v - 1
            pt = doc.pagePointSize(page)
            # resolusi tinggi: lembar CAD (A3/A1) memuat huruf kecil & garis tipis
            dpi = 300.0
            W = int(pt.width() * dpi / 72.0); H = int(pt.height() * dpi / 72.0)
            scale = min(1.0, 4800.0 / max(W, H))
            W, H = int(W * scale), int(H * scale)
            img = doc.render(page, QSize(W, H))
            rgb = self._qimage_rgb(img)
            words = AI.pdf_words(path, page, rgb.shape[1], rgb.shape[0])
            doc.close()
            return rgb, words, name
        img = QImage(path)
        if img.isNull():
            raise RuntimeError(tr('Gambar tidak dapat dibaca.'))
        if max(img.width(), img.height()) > 4800:
            img = img.scaled(4800, 4800, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return self._qimage_rgb(img), None, name

    @staticmethod
    def _qimage_rgb(img: QImage):
        base = QImage(img.size(), QImage.Format_RGB32)
        base.fill(Qt.white)
        p = QPainter(base); p.drawImage(0, 0, img); p.end()
        c = base.convertToFormat(QImage.Format_RGB888)
        w, h, bpl = c.width(), c.height(), c.bytesPerLine()
        arr = np.frombuffer(c.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)
        return arr[:, :w * 3].reshape(h, w, 3).copy()

    @staticmethod
    def _qimage_gray(img: QImage):
        # latar transparan → putih
        base = QImage(img.size(), QImage.Format_RGB32)
        base.fill(Qt.white)
        p = QPainter(base); p.drawImage(0, 0, img); p.end()
        g = base.convertToFormat(QImage.Format_Grayscale8)
        w, h, bpl = g.width(), g.height(), g.bytesPerLine()
        ptr = g.constBits()
        arr = np.frombuffer(ptr, dtype=np.uint8, count=bpl * h).reshape(h, bpl)
        return arr[:, :w].copy()

    def _cancel_import(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.terminate()
        self._worker = None

    def _close_busy(self):
        if self._busy is not None:
            try:
                self._busy.canceled.disconnect()
            except Exception:
                pass
            self._busy.close(); self._busy = None

    def _import_failed(self, msg):
        self._close_busy()
        QMessageBox.critical(self, tr('Gagal'), msg)

    def _import_done(self, rec):
        from ..reports import arch_import as AI
        self._close_busy()
        self._worker = None
        img, name = self._pending
        if self.scene.nodes and QMessageBox.question(
                self, tr('Impor Gambar Arsitektur'),
                tr('Ganti rancangan saat ini dengan hasil impor?')) != QMessageBox.Yes:
            return
        fr = rec.get('frame')
        sub = img[fr[1]:fr[3], fr[0]:fr[2]] if fr else img
        cw = float(rec.get('canvas_w') or 1000.0)
        under = AI.make_underlay(AI.to_gray(sub), canvas_w=cw, name=name)
        des = AI.to_design(rec, canvas_w=cw, underlay=under, source_name=name)
        des['use_in_report'] = self.chk_use.isChecked()
        self._source = des.get('source')
        # gambar asli (jendela utama; legenda gambar diputihkan → legenda laporan)
        self._original = AI.make_original(img, name=name, frame=fr,
                                          legend_box=rec.get('legend_box'),
                                          colours=rec.get('colours'))
        self._report_fig = 'redrawn' if des['nodes'] else 'original'
        self._layout = des.get('layout', 'sld')
        self._sync_choice()
        if self._layout == 'drawing':
            # kanvas Design = hasil redrawn: rute kabel rapi disimpan sbg titik belok
            # (dapat ditinjau & diedit), gambar impor disembunyikan (bisa ditampilkan)
            try:
                rts = _AD().drawing_routes(des, self.state.cfg or {})
                for e in des['edges']:
                    if rts.get(e['id']):
                        e['pts'] = rts[e['id']]
            except Exception:                      # pragma: no cover
                pass
            if des.get('underlay'):
                des['underlay']['visible'] = False
        self.scene.load_design(des)
        self._set_mode('select')
        self._refresh_auto_ratings(); self._sync_underlay_ui()
        self._push_undo(); self._fit()
        r = rec.get('report', {})
        meth = {'pdf-text': tr('lapisan teks PDF'), 'ocr': tr('OCR'),
                'none': tr('tidak ada (teks tak terbaca)')}.get(r.get('method'), '-')
        if r.get('method') == 'ocr' and r.get('engine'):
            meth += ' · ' + {'rapidocr': 'RapidOCR', 'tesseract': 'Tesseract'}.get(
                r['engine'], str(r['engine']))
        msg = tr('Hasil pengenalan ({m}):\n• {n} komponen\n• {c} sambungan dari garis '
                 'gambar\n• {s} sambungan disarankan (kuning) — mohon ditinjau').format(
            m=meth, n=r.get('nodes', 0), c=r.get('confirmed', 0), s=r.get('suggested', 0))
        if r.get('sheet'):
            msg = tr('Lembar gambar teknik terdeteksi: hanya diagram pada JENDELA UTAMA yang '
                     'diambil (blok judul, label grid & legenda dikecualikan).') + '\n\n' + msg
            if r.get('edges'):
                msg += '\n' + tr('• jenis sambungan dibaca dari WARNA garis{lg}').format(
                    lg=tr(' (sesuai legenda gambar)') if r.get('legend') else '')
            if r.get('existing') or r.get('future'):
                msg += '\n' + tr('• {e} komponen eksisting (garis tepi biru), {f} rencana '
                                  '(abu-abu)').format(e=r.get('existing', 0),
                                                      f=r.get('future', 0))
        msg += '\n\n' + tr('Untuk laporan, pilih di tab Pratinjau Laporan: GAMBAR ASLI atau '
                           'TOPOLOGI DIGAMBAR ULANG (kedua pratinjau ditampilkan '
                           'berdampingan).')
        if r.get('method') == 'none':
            from ..reports import arch_import as AI
            if AI.ocr_engine() is None:
                import sys
                msg += '\n\n' + tr('Teks pada gambar tidak dapat dibaca: OCR terbawa HPP '
                                   'Studio memerlukan paket onnxruntime pada Python aplikasi '
                                   '({py}). Jalankan install_deps.bat / run_dev.bat terbaru, '
                                   'lalu impor ulang. Sementara itu gambar asli tetap dapat '
                                   'dipakai di laporan.').format(py=sys.executable)
                if AI.ocr_error():
                    msg += '\n' + tr('Detail: {e}').format(e=AI.ocr_error())
            else:
                msg += '\n\n' + tr('Teks pada gambar tidak terbaca (gambar tanpa teks atau '
                                   'resolusi terlalu rendah). Gambar ditaruh sebagai latar — '
                                   'gambar ulang komponen di atasnya; gambar asli tetap dapat '
                                   'dipakai di laporan.')

        QMessageBox.information(self, tr('Impor Gambar Arsitektur'), msg)

    # ------------------------------------------------------- pratinjau --
    def _refresh_preview(self):
        AD = _AD()
        des = self._design()
        des['use_in_report'] = True
        cfg = self.state.cfg or {}
        ls = self._load_stats()
        self.notes.clear()
        try:
            A = AD.analyze(des, cfg, ls)
            fig = AD.figure(des, cfg, ls, analysis=A) \
                if (A['ok'] or des.get('layout') == 'drawing') else None
        except Exception as e:                 # pragma: no cover
            A, fig = {'issues': [('warn', str(e))], 'summary': []}, None
        wmax = max(300, self.tabs.width() // 2 - 60)
        lbl = self.prev_panes['redrawn'][1]
        if fig is not None:
            self._prev_full['redrawn'] = self._fig_pixmap(fig, 10 ** 6, dpi=150)
        else:
            lbl.setPixmap(QPixmap()); self._prev_full.pop('redrawn', None)
            lbl.setText(tr('Belum dapat digambar — tambahkan komponen dan '
                           'sambungkan ke rel AC / beban.'))
        olbl = self.prev_panes['original'][1]
        ofig = None
        if self._original:
            try:
                ofig = AD.original_figure(des)
            except Exception:                  # pragma: no cover
                ofig = None
        if ofig is not None:
            self._prev_full['original'] = self._fig_pixmap(ofig, 10 ** 6, dpi=150)
        else:
            olbl.setPixmap(QPixmap()); self._prev_full.pop('original', None)
            olbl.setText(tr('Tidak ada gambar asli — impor gambar/PDF arsitektur untuk '
                            'dapat memilih opsi ini.'))
        self._sync_choice()
        self._apply_previews()
        for s in A.get('summary', []):
            it = QListWidgetItem('▸ ' + s)
            self.notes.addItem(it)
        for lvl, txt in A.get('issues', []):
            it = QListWidgetItem(('⚠ ' if lvl == 'warn' else 'ⓘ ') + txt)
            it.setForeground(QColor(tok('warn') if lvl == 'warn' else tok('muted')))
            self.notes.addItem(it)

    def _apply_previews(self):
        """Skala pratinjau mengikuti lebar panel (ikut berubah saat jendela diubah)."""
        for key, (_rb, lbl, _fr) in getattr(self, 'prev_panes', {}).items():
            pm = self._prev_full.get(key)
            if pm is None or pm.isNull():
                continue
            sc = lbl.parentWidget()
            wmax = max(200, (sc.width() if sc is not None else lbl.width()) - 24)
            lbl.setPixmap(pm.scaledToWidth(min(wmax, pm.width()), Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, '_prev_full', None):
            QTimer.singleShot(0, self, self._apply_previews)

    @staticmethod
    def _fig_pixmap(fig, wmax, dpi=120):
        from ..reports.common import fig_to_png
        png = fig_to_png(fig, dpi=dpi).getvalue()
        pm = QPixmap(); pm.loadFromData(png, 'PNG')
        if pm.width() > wmax:
            pm = pm.scaledToWidth(wmax, Qt.SmoothTransformation)
        return pm

    def _auto_route(self):
        """Rutekan ulang semua kabel (A* ortogonal) → titik belok di kanvas."""
        if not self.scene.edges:
            return
        des = self._design()
        try:
            rts = _AD().drawing_routes(des, self.state.cfg or {}, reroute=True)
        except Exception as e:                     # pragma: no cover
            QMessageBox.warning(self, tr('Arsitektur Sistem'), str(e))
            return
        for eid, it in self.scene.edges.items():
            if eid in rts:
                it.pts = [QPointF(float(q[0]), float(q[1])) for q in rts[eid]]
                it.refresh()
        self._push_undo()

    def _layout_changed(self, _i=None):
        v = self.cb_layout.currentData()
        if v and v != self._layout:
            self._layout = v
            self._refresh_preview()

    def _choose_fig(self, key):
        if key == 'original' and not self._original:
            return
        self._report_fig = key
        self._sync_choice()
        self._update_status()

    def _sync_choice(self):
        """Radio pilihan gambar laporan ↔ status (asli hanya bila ada impor)."""
        panes = getattr(self, 'prev_panes', None)
        if not panes:
            return
        has = bool(self._original)
        if not has:
            self._report_fig = 'redrawn'
        rb_o, _l, fr_o = panes['original']
        rb_r, _l2, fr_r = panes['redrawn']
        rb_o.setEnabled(has)
        for rb, key in ((rb_o, 'original'), (rb_r, 'redrawn')):
            rb.blockSignals(True); rb.setChecked(self._report_fig == key); rb.blockSignals(False)
        cb = getattr(self, 'cb_layout', None)
        if cb is not None:
            cb.blockSignals(True)
            cb.setCurrentIndex(max(0, cb.findData(self._layout)))
            cb.blockSignals(False)
        acc = tok('accent')
        for fr, key in ((fr_o, 'original'), (fr_r, 'redrawn')):
            fr.setStyleSheet(f'QFrame#Card {{ border: 2px solid {acc}; border-radius: 8px; }}'
                             if self._report_fig == key else
                             'QFrame#Card { border: 1px solid rgba(128,128,128,0.35); '
                             'border-radius: 8px; }')

    # ------------------------------------------------------------ simpan --
    def _save(self):
        des = self._design()
        cfg = self.state.cfg
        if not des['nodes'] and not des.get('underlay') and not des.get('original'):
            cfg.pop('arch_design', None)
        else:
            cfg['arch_design'] = des
        try:
            self.state.save_config()
            self.state.db.save_project(cfg)
        except Exception:
            pass
        self.accept()

    def reject(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.terminate()
        cur = self._snap()
        dirty = (len(self._undo) > 1 and cur != self._undo[0]) or \
            (self._report_fig, bool(self._original), self._layout) != self._fig0
        if dirty and QMessageBox.question(
                self, tr('Arsitektur Sistem'),
                tr('Tutup tanpa menyimpan perubahan?')) != QMessageBox.Yes:
            return
        super().reject()


class _MoveWatcher(QObject):
    """Pantau pelepasan mouse di viewport → catat undo setelah drag/rubberband."""

    def __init__(self, dlg):
        super().__init__(dlg)
        self.dlg = dlg

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseButtonRelease:
            QTimer.singleShot(0, self.dlg._push_undo)
        return False
