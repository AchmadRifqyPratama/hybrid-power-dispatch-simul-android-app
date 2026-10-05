"""Design system HPP Studio — token warna + Qt Style Sheet (dark / light).

Arah visual: alat rekayasa teknis (engineering workstation) — permukaan
netral slate/graphite, tipografi rapat 12 px, dan hijau Akartha dipakai
HANYA sebagai aksen (aksi utama, seleksi, fokus). Warna seri grafik
(SERIES_COLORS) sengaja TIDAK diubah agar legenda tetap dikenali pengguna.

API publik yang dipakai modul lain tetap sama:
  ACCENT, DARK, LIGHT, SERIES_COLORS, CURRENT_FG, CURRENT_BG, CURRENT_DARK,
  style_plot_legend(), apply_titlebar_theme(), apply_theme()
Tambahan: TOKENS, tok(name) — baca token warna tema aktif dari halaman.
"""
from __future__ import annotations
import os
import sys

ACCENT = '#16A34A'          # hijau brand Akartha (isi tombol utama / seleksi)


def _asset_url(name: str) -> str:
    """Path aset -> URL untuk QSS (pakai '/', aman lintas-OS & PyInstaller)."""
    base = getattr(sys, '_MEIPASS', None)
    cand = []
    if base:
        cand.append(os.path.join(base, 'assets', name))
    here = os.path.dirname(os.path.abspath(__file__))
    cand.append(os.path.abspath(os.path.join(here, '..', '..', 'assets', name)))
    path = next((p for p in cand if os.path.exists(p)), cand[-1])
    return path.replace('\\', '/')


_ARROW_UP = _asset_url('spin_up.png')
_ARROW_DN = _asset_url('spin_down.png')

# ---------------------------------------------------------------- tokens
# bg      : kanvas halaman          chrome : sidebar / header / statusbar
# card    : panel (group, tab)      input  : kolom isian
# border  : garis panel             strong : garis tegas (header tabel, fokus)
# hover   : latar hover             sel    : latar seleksi (aksen transparan)
# fg      : teks utama              muted  : teks sekunder / label / satuan
# accent  : isi tombol utama        acc_fg : teks aksen (terbaca di latar)
# acc_h   : hover tombol utama      warn/err/ok : status semantik
TOKENS = {
    'dark': dict(
        bg='#111418', chrome='#0B0D10', card='#171B20', input='#0E1114',
        border='#262C33', strong='#39414B', hover='#1F252C',
        sel='rgba(22,163,74,56)', fg='#E3E7EB', muted='#8A94A0', faint='#5E6873',
        accent=ACCENT, acc_h='#15803D', acc_fg='#3CC476',
        ok='#3CC476', warn='#E0A93B', err='#E5484D',
        plot_bg='#15191E', plot_axis='#3A424C', plot_text='#9AA4AF',
        cursor_bg='rgba(16,19,23,238)'),
    'light': dict(
        bg='#F2F4F6', chrome='#FFFFFF', card='#FFFFFF', input='#FFFFFF',
        border='#D9DEE3', strong='#B7C0C9', hover='#EDF0F3',
        sel='rgba(22,163,74,34)', fg='#1B2128', muted='#5B6570', faint='#8B95A0',
        accent=ACCENT, acc_h='#15803D', acc_fg='#15803D',
        ok='#15803D', warn='#B7791F', err='#D93036',
        plot_bg='#FFFFFF', plot_axis='#B7C0C9', plot_text='#4B5560',
        cursor_bg='rgba(255,255,255,245)'),
}

_BASE = """
* {{ font-family: 'Segoe UI', 'Inter', 'Noto Sans', sans-serif;
     font-size: 12px; }}
QWidget {{ background: transparent; color: {fg}; }}
QMainWindow, QDialog, QStackedWidget, QMessageBox, QFileDialog,
QProgressDialog, QInputDialog {{ background: {bg}; }}
QComboBoxPrivateContainer {{ background: {card}; border: none; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled {{ color: {faint}; }}

/* ============================ Sidebar =============================== */
#Sidebar {{ background: {chrome}; border-right: 1px solid {border}; }}
#Sidebar QPushButton {{
    text-align: left; padding: 6px 10px; border: none; border-radius: 4px;
    margin: 0px 8px; color: {muted}; background: transparent;
    font-size: 12px; font-weight: 500; min-height: 18px;
}}
#Sidebar QPushButton:hover {{ background: {hover}; color: {fg}; }}
#Sidebar QPushButton:checked {{
    background: {sel}; color: {fg}; font-weight: 600;
}}
#NavSection {{ color: {faint}; font-size: 10px; font-weight: 700;
    letter-spacing: 1px; padding: 10px 18px 3px 18px; }}
#Sidebar QPushButton#FootBtn {{
    padding: 3px 8px; margin: 0px; text-align: center; border-radius: 4px;
    color: {muted}; border: 1px solid {border}; min-height: 16px;
    font-size: 11px; font-weight: 600;
}}
#Sidebar QPushButton#FootBtn:hover {{ background: {hover}; color: {fg}; }}
#SideSep {{ background: {border}; max-height: 1px; min-height: 1px; }}
#AppTitle {{ font-size: 14px; font-weight: 700; color: {fg}; }}
#Logo {{ font-size: 14px; font-weight: 700; color: {fg}; padding: 0px; }}
#LogoSub {{ color: {faint}; font-size: 10px; padding: 0px; }}
#Credit {{ color: {faint}; font-size: 9.5px; padding: 0px 2px; }}

/* ============================ Statusbar ============================= */
QStatusBar {{ background: {chrome}; border-top: 1px solid {border};
    color: {muted}; min-height: 22px; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {muted}; font-size: 11px; padding: 0px 8px; }}
#StatusDotOk {{ color: {ok}; }}
#StatusDotIdle {{ color: {faint}; }}
#StatusDotWarn {{ color: {warn}; }}
#StatusSep {{ color: {border}; padding: 0px; }}

/* ============================ Page header =========================== */
#PageTitle {{ font-size: 16px; font-weight: 600; color: {fg};
    padding: 0px; }}
#PageSub {{ color: {muted}; font-size: 11.5px; }}

/* ============================ Panels ================================ */
QGroupBox {{
    border: 1px solid {border}; border-radius: 6px; margin-top: 14px;
    padding: 10px 8px 8px 8px; background: {card}; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
    left: 2px; top: 0px; padding: 0px 4px 2px 4px; color: {muted};
    font-size: 11px; font-weight: 700; background: transparent; }}
#ParamHeading {{ color: {acc_fg}; font-size: 11px; }}
QFrame#HSep {{ background: {border}; max-height: 1px; border: none; }}

/* ============================ Inputs ================================ */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QDateEdit, QTimeEdit,
QPlainTextEdit, QTextEdit {{
    background: {input}; border: 1px solid {border}; border-radius: 4px;
    padding: 2px 6px; min-height: 18px; color: {fg};
    selection-background-color: {accent}; selection-color: white;
}}
QLineEdit:hover, QDoubleSpinBox:hover, QSpinBox:hover, QComboBox:hover {{
    border-color: {strong}; }}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {accent}; }}
QLineEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled,
QComboBox:disabled {{ color: {faint}; background: transparent;
    border-color: {border}; }}
QLineEdit[readOnly="true"] {{ background: transparent; }}
QComboBox {{ padding-right: 20px; }}
QComboBox::drop-down {{ subcontrol-origin: padding;
    subcontrol-position: center right; width: 18px; border: none; }}
QComboBox::down-arrow {{ image: url("{arrow_dn}"); width: 10px; height: 7px; }}
QComboBox QAbstractItemView {{ background: {card}; border: 1px solid {strong};
    selection-background-color: {sel}; selection-color: {fg};
    outline: none; padding: 2px; }}
QComboBox QAbstractItemView::item {{ min-height: 20px; padding: 0px 6px; }}
/* Spinbox: tombol naik/turun ditumpuk rapi, ramping */
QSpinBox, QDoubleSpinBox {{ padding-right: 18px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 16px; border: none; border-left: 1px solid {border};
    border-top-right-radius: 4px; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 16px; border: none; border-left: 1px solid {border};
    border-bottom-right-radius: 4px; background: transparent; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {hover}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{arrow_up}"); width: 9px; height: 6px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{arrow_dn}"); width: 9px; height: 6px; }}

/* ============================ Buttons =============================== */
/* Primer (default) = isi aksen. Sekunder (flat="true") = netral bergaris.
   Mode (mode="true") = tombol toggle / segmented. */
QPushButton {{
    background: {accent}; color: white; border: 1px solid {accent};
    border-radius: 4px; padding: 3px 12px; min-height: 18px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {acc_h}; border-color: {acc_h}; }}
QPushButton:pressed {{ background: {acc_h}; }}
QPushButton:focus {{ outline: none; }}
QPushButton:disabled {{ background: {hover}; color: {faint};
    border: 1px solid {border}; }}
QPushButton[flat="true"] {{ background: transparent; color: {fg};
    border: 1px solid {strong}; font-weight: 500; }}
QPushButton[flat="true"]:hover {{ background: {hover};
    border-color: {muted}; }}
QPushButton[flat="true"]:pressed, QPushButton[flat="true"]:checked {{
    background: {sel}; border-color: {accent}; }}
QPushButton[flat="true"]:disabled {{ background: transparent; color: {faint};
    border: 1px solid {border}; }}
QPushButton[mode="true"] {{ background: transparent; color: {muted};
    border: 1px solid {strong}; font-weight: 600; }}
QPushButton[mode="true"]:hover {{ background: {hover}; color: {fg}; }}
QPushButton[mode="true"]:checked {{ background: {sel}; color: {fg};
    border: 1px solid {accent}; }}
QPushButton[mode="true"]:disabled {{ background: transparent; color: {faint};
    border: 1px solid {border}; }}
QToolButton {{ background: transparent; border: 1px solid transparent;
    border-radius: 4px; padding: 2px 4px; color: {fg}; }}
QToolButton:hover {{ background: {hover}; border-color: {border}; }}
QToolButton:checked {{ background: {sel}; border-color: {accent}; }}
QToolButton::menu-indicator {{ image: none; }}

/* ============================ Check / radio ========================= */
QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border-radius: 3px;
    border: 1px solid {faint}; background: {input}; }}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent};
    image: url("{check}"); }}
QCheckBox::indicator:disabled {{ border-color: {strong};
    background: {hover}; }}
QCheckBox::indicator:checked:disabled {{ background: {faint};
    border-color: {faint}; }}
QRadioButton::indicator {{ width: 12px; height: 12px; border-radius: 7px;
    border: 1px solid {faint}; background: {input}; }}
QRadioButton::indicator:hover {{ border-color: {accent}; }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5,
    cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 white, stop:0.35 white,
    stop:0.45 {accent}, stop:1 {accent}); border-color: {accent}; }}
QRadioButton::indicator:checked:disabled {{ background: {faint};
    border-color: {faint}; }}
QRadioButton::indicator:unchecked:disabled {{ border-color: {strong};
    background: {hover}; }}

/* ============================ Tables ================================ */
QTableWidget, QTableView, QTreeView, QListView {{
    background: {card}; border: 1px solid {border}; border-radius: 4px;
    gridline-color: {border}; alternate-background-color: {hover};
    selection-background-color: {sel}; selection-color: {fg};
    outline: none;
}}
QTableView::item {{ padding: 0px 6px; }}
QTableView::item:selected {{ background: {sel}; color: {fg}; }}
QHeaderView {{ background: {chrome}; border: none; }}
QHeaderView::section {{ background: {chrome}; color: {muted}; border: none;
    border-right: 1px solid {border}; border-bottom: 1px solid {strong};
    padding: 4px 6px; font-weight: 600; font-size: 11px; }}
QHeaderView::section:vertical {{ border-right: 1px solid {strong};
    border-bottom: 1px solid {border}; padding: 0px 6px; }}
QHeaderView::section:hover {{ color: {fg}; }}
QTableCornerButton::section {{ background: {chrome}; border: none;
    border-right: 1px solid {border}; border-bottom: 1px solid {strong}; }}

/* ============================ Tabs ================================== */
QTabWidget::pane {{ border: 1px solid {border}; border-radius: 0px 6px 6px 6px;
    background: {card}; top: -1px; }}
QTabWidget::tab-bar {{ left: 0px; }}
#DashTabCard {{ background: {card}; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{ padding: 5px 14px; background: transparent; color: {muted};
    border: 1px solid transparent; border-bottom: 2px solid transparent;
    margin-right: 1px; font-weight: 500; }}
QTabBar::tab:hover {{ color: {fg}; }}
QTabBar::tab:selected {{ color: {fg}; background: {card};
    border: 1px solid {border}; border-bottom: 2px solid {accent};
    border-top-left-radius: 4px; border-top-right-radius: 4px;
    font-weight: 600; }}

/* ============================ Scroll / split ======================== */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px;
    margin: 0px; }}
QScrollBar::handle:vertical {{ background: {strong}; border-radius: 3px;
    min-height: 28px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {strong}; border-radius: 3px;
    min-width: 28px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px;
    border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: {border}; }}
QSplitter::handle:hover {{ background: {accent}; }}

/* ============================ Misc ================================== */
QProgressBar {{ border: 1px solid {border}; border-radius: 3px;
    text-align: center; background: {input}; max-height: 14px;
    font-size: 10.5px; color: {fg}; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}
QToolTip {{ background: {card}; color: {fg}; border: 1px solid {strong};
    border-radius: 4px; padding: 4px 6px; font-size: 11.5px; }}
QMenu {{ background: {card}; border: 1px solid {strong}; padding: 4px; }}
QMenu::item {{ padding: 4px 18px 4px 10px; border-radius: 3px; }}
QMenu::item:selected {{ background: {sel}; color: {fg}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 6px; }}
QMessageBox QLabel {{ font-size: 12px; }}
QMessageBox QPushButton {{ min-width: 72px; }}

/* ============================ KPI tiles ============================= */
#KPICard {{ background: {card}; border: 1px solid {border};
    border-radius: 6px; }}
QGroupBox #KPICard {{ background: {input}; }}
#KPITileLabel {{ color: {muted}; font-size: 10.5px; font-weight: 600; }}
#KPIValue {{ font-size: 18px; font-weight: 600; color: {fg}; }}
#KPIUnit {{ color: {muted}; font-size: 11px; padding-bottom: 2px; }}
/* KPILabel tetap dipakai sebagai label satuan / teks kecil sekunder */
#KPILabel {{ color: {muted}; font-size: 11px; }}

/* ============================ Login ================================= */
#LoginDialog {{ background: {bg}; }}
#LoginError {{ color: {err}; font-size: 11.5px; font-weight: 600; }}
"""


def _check_url() -> str:
    """Tanda centang putih untuk checkbox (dibuat sekali, disimpan di temp)."""
    try:
        import tempfile
        path = os.path.join(tempfile.gettempdir(), 'hpps_check_v1.svg')
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                f.write('<svg xmlns="http://www.w3.org/2000/svg" width="12" '
                        'height="12" viewBox="0 0 12 12"><path d="M2.5 6.2 '
                        'L5 8.6 L9.6 3.6" fill="none" stroke="white" '
                        'stroke-width="1.8" stroke-linecap="round" '
                        'stroke-linejoin="round"/></svg>')
        return path.replace('\\', '/')
    except Exception:
        return ''


def _build(mode: str) -> str:
    t = TOKENS[mode]
    return _BASE.format(arrow_up=_ARROW_UP, arrow_dn=_ARROW_DN,
                        check=_check_url(), **t)


DARK = _build('dark')
LIGHT = _build('light')

# Warna seri grafik — TIDAK diubah (konsisten dgn laporan & kebiasaan pengguna)
SERIES_COLORS = dict(grid='#2563EB', deg='#DC2626', pv='#84CC16',
                     bess='#F97316', load='#6B7280', soc='#7C3AED',
                     exc='#EAB308')


CURRENT_FG = TOKENS['dark']['fg']
CURRENT_BG = TOKENS['dark']['plot_bg']
CURRENT_DARK = True          # tema aktif (dipakai tooltip kursor Dashboard)


def tok(name: str) -> str:
    """Token warna untuk tema AKTIF (mis. tok('muted'), tok('border'))."""
    return TOKENS['dark' if CURRENT_DARK else 'light'].get(name, '#888888')


def style_plot_legend(plot):
    """Samakan warna teks legend dengan tema aktif (item lama & baru)."""
    try:
        import pyqtgraph as pg  # noqa: F401
        leg = plot.getPlotItem().legend
        if leg is None:
            return
        try:
            leg.setLabelTextColor(CURRENT_FG)
        except Exception:
            pass
        for _sample, label in list(getattr(leg, 'items', [])):
            try:
                label.setText(label.text, color=CURRENT_FG)
            except Exception:
                pass
    except Exception:
        pass


def apply_titlebar_theme(window, dark: bool = True):
    """Warnai bilah judul jendela mengikuti tema (Windows 10 1809+/11).

    Bilah judul digambar oleh sistem operasi, bukan Qt, sehingga perlu
    memanggil DwmSetWindowAttribute. Di OS lain fungsi ini tidak melakukan
    apa pun.
    """
    if sys.platform != 'win32':
        return
    try:
        # JANGAN panggil winId() pada jendela yang belum punya handle native /
        # tersembunyi: winId() akan MEMBUAT jendela native baru dan, bersama
        # SWP_FRAMECHANGED, memunculkan "potongan jendela" kosong (bug v132).
        if window.windowHandle() is None or not window.isVisible():
            return
        import ctypes
        hwnd = int(window.winId())
        if not hwnd:
            return
        val = ctypes.c_int(1 if dark else 0)
        dwm = ctypes.windll.dwmapi
        for attr in (20, 19):          # 20 = build baru, 19 = build lama
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val),
                                      ctypes.sizeof(val))
        # paksa bingkai digambar ulang agar perubahan langsung terlihat
        SWP = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP)
    except Exception:
        pass


# ---------------------------------------------------------------- style
_COMPACT = None


def _install_compact_style(app):
    """Gaya dasar Fusion + metrik tata letak rapat (margin 8, spasi 6).

    Fusion memberi render QSS yang konsisten di semua OS; ProxyStyle
    merapatkan margin/spasi DEFAULT seluruh layout tanpa mengubah kode
    halaman (layout yang menyetel margin sendiri tidak terpengaruh)."""
    global _COMPACT
    if _COMPACT is not None:
        return
    try:
        from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleFactory

        class _CompactStyle(QProxyStyle):
            _M = {
                QStyle.PM_LayoutLeftMargin: 8,
                QStyle.PM_LayoutRightMargin: 8,
                QStyle.PM_LayoutTopMargin: 8,
                QStyle.PM_LayoutBottomMargin: 8,
                QStyle.PM_LayoutHorizontalSpacing: 6,
                QStyle.PM_LayoutVerticalSpacing: 5,
                QStyle.PM_SmallIconSize: 14,
            }

            def pixelMetric(self, metric, option=None, widget=None):
                v = self._M.get(metric)
                if v is not None:
                    return v
                return super().pixelMetric(metric, option, widget)

            def styleHint(self, hint, option=None, widget=None,
                          returnData=None):
                # tooltip muncul lebih cepat & tanpa efek animasi combobox
                if hint == QStyle.SH_ToolTip_WakeUpDelay:
                    return 450
                if hint == QStyle.SH_ComboBox_Popup:
                    return 0
                return super().styleHint(hint, option, widget, returnData)

        base = QStyleFactory.create('Fusion')
        _COMPACT = _CompactStyle(base) if base is not None else None
        if _COMPACT is not None:
            app.setStyle(_COMPACT)
    except Exception:
        _COMPACT = False


def _apply_palette(app, t):
    """QPalette selaras token — untuk bagian yang tak dijangkau QSS
    (dialog sistem, item view bawaan, teks placeholder)."""
    try:
        from PySide6.QtGui import QPalette, QColor
        p = QPalette()
        C = QColor
        p.setColor(QPalette.Window, C(t['bg']))
        p.setColor(QPalette.WindowText, C(t['fg']))
        p.setColor(QPalette.Base, C(t['input']))
        p.setColor(QPalette.AlternateBase, C(t['hover']))
        p.setColor(QPalette.Text, C(t['fg']))
        p.setColor(QPalette.Button, C(t['card']))
        p.setColor(QPalette.ButtonText, C(t['fg']))
        p.setColor(QPalette.ToolTipBase, C(t['card']))
        p.setColor(QPalette.ToolTipText, C(t['fg']))
        p.setColor(QPalette.Highlight, C(t['accent']))
        p.setColor(QPalette.HighlightedText, C('#FFFFFF'))
        p.setColor(QPalette.PlaceholderText, C(t['faint']))
        p.setColor(QPalette.Link, C(t['acc_fg']))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            p.setColor(QPalette.Disabled, role, C(t['faint']))
        app.setPalette(p)
    except Exception:
        pass


def style_plot(w, t=None):
    """Terapkan gaya teknis ke satu PlotWidget pyqtgraph: latar panel,
    sumbu tipis netral, teks sumbu abu-abu, font tick 8.5 pt."""
    import pyqtgraph as pg
    from PySide6.QtGui import QFont
    t = t or TOKENS['dark' if CURRENT_DARK else 'light']
    w.setBackground(t['plot_bg'])
    pi = w.getPlotItem()
    f = QFont(); f.setPointSizeF(8.5)
    for side in ('left', 'bottom', 'right', 'top'):
        try:
            ax = pi.getAxis(side)
            ax.setPen(pg.mkPen(t['plot_axis']))
            ax.setTextPen(pg.mkPen(t['plot_text']))
            ax.setStyle(tickFont=f)
        except Exception:
            pass
    try:                                        # judul plot (bila ada)
        tl = pi.titleLabel
        if tl is not None and tl.text:
            tl.setText(tl.text, color=t['plot_text'], size='9pt')
    except Exception:
        pass
    style_plot_legend(w)


class _WindowThemer:
    """Filter event tingkat aplikasi: setiap JENDELA yang tampil (dialog,
    message box, peta, dsb.) atau menerima perubahan tema sistem langsung
    diberi warna bilah judul sesuai tema aktif. Tanpa ini Windows/Qt dapat
    mengembalikan bilah judul ke terang (mis. saat tema sistem = light)."""
    _obj = None

    @classmethod
    def install(cls, app):
        if cls._obj is not None:
            return
        from PySide6.QtCore import QObject, QEvent, QTimer

        class _F(QObject):
            _TYPES = (QEvent.Show, QEvent.ThemeChange,
                      QEvent.WindowActivate)

            def eventFilter(self, obj, ev):
                try:
                    if ev.type() in self._TYPES and obj.isWidgetType() \
                            and obj.isWindow() \
                            and type(obj).__name__ != 'QFileDialog':
                        w = obj
                        QTimer.singleShot(
                            0, lambda w=w: _safe_titlebar(w))
                except Exception:
                    pass
                return False

        cls._obj = _F(app)
        app.installEventFilter(cls._obj)


def _safe_titlebar(w):
    try:
        apply_titlebar_theme(w, CURRENT_DARK)
    except RuntimeError:            # widget sudah dihapus
        pass


def _set_color_scheme(app, dark):
    """Qt >= 6.8: beri tahu Qt skema warna aplikasi agar Qt sendiri menggambar
    bilah judul gelap/terang (tidak lagi mengikuti tema sistem Windows)."""
    try:
        from PySide6.QtCore import Qt
        hints = app.styleHints()
        if not hasattr(hints, 'setColorScheme'):
            return
        want = Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light
        if hints.colorScheme() != want:
            hints.setColorScheme(want)
    except Exception:
        pass


def apply_theme(app, dark: bool = True):
    """Terapkan QSS ke QApplication + sinkronkan seluruh grafik pyqtgraph."""
    global CURRENT_FG, CURRENT_BG, CURRENT_DARK
    _install_compact_style(app)
    _WindowThemer.install(app)
    t = TOKENS['dark' if dark else 'light']
    CURRENT_FG, CURRENT_BG, CURRENT_DARK = t['fg'], t['plot_bg'], bool(dark)
    _set_color_scheme(app, dark)
    _apply_palette(app, t)
    qss = DARK if dark else LIGHT
    # setStyleSheet memoles ulang SELURUH widget (mahal & berkedip) -> hanya
    # bila QSS memang berubah; widget baru otomatis memakai QSS aplikasi.
    if app.styleSheet() != qss:
        app.setStyleSheet(qss)
    for w in app.topLevelWidgets():
        if w.isWindow() and w.isVisible():
            apply_titlebar_theme(w, dark)
    try:                            # ulangi sekali setelah event Qt diproses
        from PySide6.QtCore import QTimer
        QTimer.singleShot(150, lambda: [
            _safe_titlebar(w) for w in app.topLevelWidgets()
            if w.isWindow() and w.isVisible()])
    except Exception:
        pass
    try:
        import pyqtgraph as pg
        pg.setConfigOption('background', t['plot_bg'])
        pg.setConfigOption('foreground', t['plot_text'])
        # retema widget plot yang SUDAH dibuat (config di atas hanya
        # berlaku untuk widget baru)
        for w in app.allWidgets():
            try:
                if not isinstance(w, pg.PlotWidget):
                    continue
                style_plot(w, t)
            except Exception:
                continue   # satu widget bermasalah tidak boleh
                           # menggagalkan retema widget lainnya
    except Exception:
        pass
