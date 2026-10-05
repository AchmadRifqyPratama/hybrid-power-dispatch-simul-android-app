"""MainWindow — sidebar navigasi + stacked pages + toggle dark/light."""
from __future__ import annotations
import os
import warnings

from ..config.i18n import tr, set_language, get_language
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QIcon, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QPushButton, QLabel, QButtonGroup, QApplication, QFrame, QStatusBar)

from .theme import apply_theme, apply_titlebar_theme, ACCENT, tok
from .plotutil import asset_path
from .icons import nav_icon, simple_icon
from .state import AppState
from .pages.home_page import HomePage
from .pages.parameters_page import ParametersPage
from .pages.data_page import DataPage
from .pages.dashboard_page import DashboardPage
from .pages.optimization_page import OptimizationPage
from .pages.results_page import ResultsPage
from .pages.multi_year_page import MultiYearPage

# (label, page-class) — ikon diambil dari icons.py berdasarkan label.
NAV = [
    ('Home', HomePage),
    ('Parameters', ParametersPage),
    ('Data', DataPage),
    ('Dashboard', DashboardPage),
    ('Optimization', OptimizationPage),
    ('Results', ResultsPage),
    ('Multi-Year', MultiYearPage),
]

# Pengelompokan VISUAL sidebar (urutan alur kerja). Indeks halaman/stack
# TETAP mengikuti NAV di atas — hanya posisi tombol yang dikelompokkan.
NAV_SECTIONS = [
    ('PROJECT', ('Home', 'Parameters', 'Data')),
    ('ANALYSIS', ('Dashboard', 'Optimization', 'Multi-Year')),
    ('REPORTING', ('Results',)),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('HPP Studio — Hybrid Power Plant Sizing & Simulation')
        _ic = QIcon(asset_path('logo.png'))
        if not _ic.isNull():
            self.setWindowIcon(_ic)
        self._fit_to_screen()
        self.state = AppState()
        self.dark = True
        set_language(self.state.cfg.get('language', 'ID'))
        self._build_ui()
        apply_theme(QApplication.instance(), dark=True)
        QShortcut(QKeySequence.Save, self,
                  activated=lambda: self._project('save'))
        QShortcut(QKeySequence('Ctrl+Shift+S'), self,
                  activated=lambda: self._project('save_as'))
        QShortcut(QKeySequence.Open, self,
                  activated=lambda: self._project('open'))
        # Ctrl+1 … Ctrl+7 : pindah halaman cepat
        for i in range(len(NAV)):
            QShortcut(QKeySequence(f'Ctrl+{i + 1}'), self,
                      activated=lambda i=i: self._goto(i))
        # results_cleared TIDAK diputus oleh _rebuild -> sambung sekali di sini
        self.state.results_cleared.connect(
            lambda *_: QTimer.singleShot(0, self._refresh_status))
        # nama berkas proyek tak punya sinyal -> segarkan status berkala (murah)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(1500)

    BASE_TITLE = 'HPP Studio — Hybrid Power Plant Sizing & Simulation'

    def set_project_title(self, path):
        """Tampilkan nama berkas proyek aktif di judul jendela."""
        import os
        self.setWindowTitle(f'{os.path.basename(path)} — {self.BASE_TITLE}'
                            if path else self.BASE_TITLE)

    def _project(self, action: str):
        """Ctrl+S / Ctrl+Shift+S / Ctrl+O.

        Aksi dijalankan oleh halaman Home, tetapi halaman yang sedang dibuka
        TIDAK diubah — pengguna tetap berada di tempatnya bekerja.
        """
        if action in ('save', 'save_as'):
            # biarkan tiap halaman menyalin input-nya ke state sebelum disimpan
            for i in range(self.stack.count()):
                pg_ = self.stack.widget(i)
                sync = getattr(pg_, 'sync_to_state', None)
                if callable(sync):
                    try:
                        sync()
                    except Exception:
                        pass
        home = self.stack.widget(0)
        names = {'save': 'save_project', 'save_as': 'save_project_as',
                 'open': 'open_project'}
        fn = getattr(home, names.get(action, ''), None)
        if callable(fn):
            fn()

    def _fit_to_screen(self):
        """Ukuran & posisi awal mengikuti area kerja layar.

        Tanpa ini, pada laptop berlayar kecil Qt meminta geometri melebihi
        area kerja dan Windows menolaknya (peringatan
        QWindowsWindow::setGeometry di konsol).
        """
        scr = QApplication.primaryScreen()
        avail = scr.availableGeometry() if scr else None
        if avail is None:
            self.setMinimumSize(1000, 620)
            self.resize(1360, 860)
            return
        # minimum tidak boleh melampaui layar
        self.setMinimumSize(min(1000, max(640, avail.width() - 40)),
                            min(620, max(480, avail.height() - 40)))
        w = min(1360, max(800, avail.width() - 60))
        h = min(880, max(560, avail.height() - 60))
        self.resize(w, h)
        self.move(avail.left() + (avail.width() - w) // 2,
                  avail.top() + (avail.height() - h) // 2)

    def _goto(self, i: int):
        btn = self.group.button(i)
        if btn is not None:
            btn.setChecked(True)
            self.stack.setCurrentIndex(i)

    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        h = QHBoxLayout(root); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)

        # ---------- sidebar (ringkas, dikelompokkan per alur kerja) ----------
        side = QWidget(); side.setObjectName('Sidebar')
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setFixedWidth(184)
        sv = QVBoxLayout(side); sv.setContentsMargins(0, 12, 0, 10)
        sv.setSpacing(1)
        head = QHBoxLayout()
        head.setContentsMargins(14, 0, 10, 0)
        head.setSpacing(8)
        self.logo_mark = QLabel()
        self._set_logo_pixmap()
        head.addWidget(self.logo_mark, 0, Qt.AlignVCenter)
        tv = QVBoxLayout(); tv.setSpacing(0); tv.setContentsMargins(0, 0, 0, 0)
        logo = QLabel('HPP Studio'); logo.setObjectName('Logo')
        sub = QLabel('PV · BESS · Diesel · Grid'); sub.setObjectName('LogoSub')
        tv.addWidget(logo); tv.addWidget(sub)
        head.addLayout(tv, 1)
        sv.addLayout(head)
        sv.addSpacing(10)
        sv.addWidget(self._hsep())
        sv.addSpacing(2)

        self.stack = QStackedWidget()
        self.group = QButtonGroup(self); self.group.setExclusive(True)
        self._nav_buttons = []
        off, on = self._nav_colors()
        btn_by_label = {}
        for i, (label, cls) in enumerate(NAV):
            btn = QPushButton(' ' + tr(label))
            btn.setIcon(nav_icon(label, off, on))
            btn.setIconSize(QSize(16, 16))
            btn.setCheckable(True)
            btn.setObjectName('NavBtn')
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f'{tr(label)}  (Ctrl+{i + 1})')
            self.group.addButton(btn, i)
            page = cls(self.state)
            self._frame_page(page)
            self.stack.addWidget(page)
            self._nav_buttons.append((btn, label))
            btn_by_label[label] = btn
        placed = set()
        for title, labels in NAV_SECTIONS:
            sec = QLabel(tr(title)); sec.setObjectName('NavSection')
            sv.addWidget(sec)
            for lb in labels:
                if lb in btn_by_label:
                    sv.addWidget(btn_by_label[lb]); placed.add(lb)
        for lb, btn in btn_by_label.items():      # jaga-jaga: item tak terpetakan
            if lb not in placed:
                sv.addWidget(btn)
        self.group.idClicked.connect(self.stack.setCurrentIndex)
        self.group.button(0).setChecked(True)

        sv.addStretch(1)
        sv.addWidget(self._hsep())
        sv.addSpacing(8)
        # Bahasa (ID/EN) + tema (ikon) — dua tombol kecil sebaris
        ctl = QHBoxLayout(); ctl.setSpacing(6)
        ctl.setContentsMargins(14, 0, 14, 0)
        self.btn_lang = QPushButton()
        self.btn_lang.setObjectName('FootBtn')
        self.btn_lang.setCursor(Qt.PointingHandCursor)
        self.btn_lang.clicked.connect(self._toggle_language)
        ctl.addWidget(self.btn_lang, 1)
        self.btn_theme = QPushButton()
        self.btn_theme.setObjectName('FootBtn')
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.clicked.connect(self._toggle_theme)
        ctl.addWidget(self.btn_theme, 1)
        sv.addLayout(ctl)
        self._sync_lang_button()
        self._sync_theme_button()
        sv.addSpacing(10)
        # logo Akartha (mengikuti tema) di footer sidebar — ukuran ringkas
        self.brand_logo = QLabel()
        self.brand_logo.setObjectName('BrandLogo')
        self.brand_logo.setAlignment(Qt.AlignHCenter)
        self._set_brand_logo()
        sv.addWidget(self.brand_logo)
        sv.addSpacing(4)
        credit = QLabel(tr('Developed by')
                        + ' ARP · Engineering\nAkartha Energy · v1.0')
        credit.setObjectName('Credit')
        credit.setAlignment(Qt.AlignHCenter)
        credit.setWordWrap(True)
        sv.addWidget(credit)

        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self._build_statusbar()

    @staticmethod
    def _frame_page(page):
        """Margin tepi halaman seragam (12/10 px) — hanya untuk halaman yang
        memakai margin bawaan; halaman dgn margin eksplisit tak disentuh."""
        lay = page.layout()
        if lay is None:
            return
        m = lay.contentsMargins()
        if (m.left(), m.top(), m.right(), m.bottom()) == (8, 8, 8, 8):
            lay.setContentsMargins(12, 10, 12, 8)

    # ---------- status bar: ringkasan konteks kerja selalu terlihat ----------
    @staticmethod
    def _hsep():
        f = QFrame(); f.setObjectName('SideSep'); f.setFixedHeight(1)
        f.setAttribute(Qt.WA_StyledBackground, True)
        return f

    def _build_statusbar(self):
        sb = QStatusBar(); sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)

        def lab():
            l = QLabel(''); l.setTextFormat(Qt.RichText); return l
        self._sb_data, self._sb_sim, self._sb_file = lab(), lab(), lab()
        self._sb_cfg = lab()
        sb.addWidget(self._sb_data)
        sb.addWidget(self._sb_sim)
        sb.addWidget(self._sb_file, 1)
        sb.addPermanentWidget(self._sb_cfg)
        # sinyal ini diputus oleh _rebuild -> disambung ulang tiap build
        for sig in (self.state.profiles_changed, self.state.config_changed,
                    self.state.simulation_done):
            sig.connect(lambda *_: QTimer.singleShot(0, self._refresh_status))
        self._refresh_status()

    def _refresh_status(self):
        lab = getattr(self, '_sb_data', None)
        if lab is None:
            return
        try:
            st = self.state
            ok, idle = tok('ok'), tok('faint')
            dot = '<span style="color:%s">&#9679;</span>&nbsp;'
            if st.data_ready():
                n = len(st.load)
                self._sb_data.setText(dot % ok + tr('Data') + ': '
                                      + f'{n:,} ' + tr('rows'))
            else:
                self._sb_data.setText(dot % idle + tr('No data loaded'))
            if st.last_result:
                self._sb_sim.setText(dot % ok + tr('Simulation ready'))
            else:
                self._sb_sim.setText(dot % idle + tr('Not simulated'))
            path = st.project_path
            self._sb_file.setText(os.path.basename(path) if path
                                  else tr('Unsaved project'))
            self._sb_file.setToolTip(path or '')
            cfg = st.cfg
            self._sb_cfg.setText(
                f"{cfg.get('sim_interval', '1 hour')}  ·  "
                f"{cfg.get('simulation_year', '')}  ·  {get_language()}")
        except RuntimeError:
            pass                    # label lama sudah dihapus (ganti bahasa)
        except Exception:
            pass

    def _set_logo_pixmap(self):
        """Varian logo menyesuaikan tema agar tetap terbaca."""
        name = 'logo_dark.png' if getattr(self, 'dark', True) \
            else 'logo.png'
        pm = QPixmap(asset_path(name))
        if pm.isNull():
            pm = QPixmap(asset_path('logo.png'))
        if not pm.isNull():
            self.logo_mark.setPixmap(
                pm.scaled(26, 26, Qt.KeepAspectRatio,
                          Qt.SmoothTransformation))

    def _set_brand_logo(self):
        """Logo Akartha di footer sidebar — versi terang untuk light theme,
        versi pucat untuk dark theme."""
        if not hasattr(self, 'brand_logo'):
            return
        name = 'logo_akartha_dark.png' if getattr(self, 'dark', True) \
            else 'logo_akartha.png'
        pm = QPixmap(asset_path(name))
        if pm.isNull():
            pm = QPixmap(asset_path('logo_akartha.png'))
        if not pm.isNull():
            self.brand_logo.setPixmap(
                pm.scaledToWidth(112, Qt.SmoothTransformation))

    def closeEvent(self, ev):
        for i in range(self.stack.count()):
            pg_ = self.stack.widget(i)
            if getattr(pg_, 'stop_workers', None):
                pg_.stop_workers()
        super().closeEvent(ev)

    def _nav_colors(self):
        """(warna ikon nav biasa, warna ikon nav aktif) menurut tema."""
        fg = '#8A94A0' if getattr(self, 'dark', True) else '#5B6570'
        on = '#3CC476' if getattr(self, 'dark', True) else ACCENT
        return fg, on

    def _set_nav_icons(self):
        off, on = self._nav_colors()
        for btn, label in getattr(self, '_nav_buttons', []):
            btn.setIcon(nav_icon(label, off, on))

    def _sync_lang_button(self):
        # cukup "ID"/"EN" tanpa ikon
        self.btn_lang.setText(get_language())
        self.btn_lang.setIcon(QIcon())
        self.btn_lang.setToolTip(tr('Ganti bahasa (ID / EN)'))

    def _sync_theme_button(self):
        # Ikon menampilkan MODE SAAT INI: bulan saat gelap, matahari saat terang.
        fg, _ = self._nav_colors()
        name = 'moon' if getattr(self, 'dark', True) else 'sun'
        self.btn_theme.setText('')
        self.btn_theme.setIcon(simple_icon(name, fg))
        self.btn_theme.setIconSize(QSize(14, 14))
        self.btn_theme.setToolTip(tr('Dark Mode') if self.dark
                                  else tr('Light Mode'))

    def _toggle_language(self):
        new = 'EN' if get_language() == 'ID' else 'ID'
        set_language(new)
        self.state.cfg['language'] = new
        self.state.save_config()
        self._rebuild()

    def _rebuild(self):
        """Bangun ulang seluruh halaman & sidebar dengan bahasa baru.

        Dua hal penting:
        * Koneksi sinyal halaman lama diputus lebih dulu — tanpa ini sinyal
          AppState (berumur panjang) masih memanggil widget yang sudah
          dihapus dan memicu RuntimeError 'C++ object already deleted'.
        * Penggambaran dibekukan selama proses agar tidak berkedip.
        """
        app = QApplication.instance()
        if app is not None and app.activeModalWidget() is not None:
            # jangan bongkar UI saat dialog modal masih terbuka
            QTimer.singleShot(150, self._rebuild)
            return
        for i in range(self.stack.count()):
            pg_ = self.stack.widget(i)
            if getattr(pg_, 'is_busy', None) and pg_.is_busy():
                # tunggu simulasi/optimasi selesai dulu
                QTimer.singleShot(300, self._rebuild)
                return
        idx = self.stack.currentIndex()
        self._begin_transition()
        self.setUpdatesEnabled(False)
        try:
            with warnings.catch_warnings():
                # sinyal tanpa penerima memicu RuntimeWarning dari PySide
                warnings.simplefilter('ignore', RuntimeWarning)
                for sig in (self.state.profiles_changed,
                            self.state.config_changed,
                            self.state.simulation_done,
                            self.state.optimization_done):
                    try:
                        sig.disconnect()
                    except (RuntimeError, TypeError):
                        pass            # memang belum ada yang tersambung
            for i in range(self.stack.count()):
                pg_ = self.stack.widget(i)
                if getattr(pg_, 'stop_workers', None):
                    pg_.stop_workers()
            old = self.centralWidget()
            if old is not None:
                old.hide()
                # Lepas sebelum widget baru dipasang — dipindah ke wadah
                # tersembunyi (BUKAN setParent(None)): widget tanpa induk
                # menjadi jendela top-level tersendiri dan di Windows dapat
                # muncul sebagai "potongan jendela" kosong.
                old.setParent(self._graveyard())
            self._build_ui()
            self.stack.setCurrentIndex(idx)
            self.group.button(idx).setChecked(True)
            apply_theme(QApplication.instance(), dark=self.dark)
            if old is not None:
                old.deleteLater()
        finally:
            self.setUpdatesEnabled(True)
            self._end_transition()
            self._refresh_cursor()

    # ---------- transisi halus (tanpa kedip) saat UI dibangun ulang ----------
    def _graveyard(self):
        g = getattr(self, '_grave', None)
        if g is None:
            g = QWidget(self)
            g.setObjectName('Graveyard')
            g.hide()
            self._grave = g
        return g

    def _begin_transition(self):
        """Tutup jendela dengan 'foto' tampilan saat ini; UI di bawahnya
        dibangun ulang tanpa terlihat, lalu foto dipudarkan (_end_transition)."""
        self._end_transition(immediate=True)
        if not self.isVisible():
            return
        try:
            pm = self.grab()
        except Exception:
            return
        ov = QLabel(self)
        ov.setObjectName('TransitionOverlay')
        ov.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        ov.setPixmap(pm)
        ov.setGeometry(self.rect())
        ov.show(); ov.raise_(); ov.repaint()
        self._overlay = ov

    def _end_transition(self, immediate: bool = False):
        ov = getattr(self, '_overlay', None)
        if ov is None:
            return
        self._overlay = None
        try:
            ov.raise_()
            if immediate:
                ov.deleteLater()
                return
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            from PySide6.QtCore import QPropertyAnimation, QEasingCurve
            eff = QGraphicsOpacityEffect(ov)
            eff.setOpacity(1.0)
            ov.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b'opacity', ov)
            anim.setDuration(180)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(ov.deleteLater)
            # beri waktu layout/polish widget baru selesai di balik foto
            QTimer.singleShot(40, anim.start)
        except RuntimeError:
            pass

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        ov = getattr(self, '_overlay', None)
        if ov is not None:
            try:
                ov.setGeometry(self.rect())
            except RuntimeError:
                pass

    # ---------- kursor: selalu sesuai widget di bawah mouse ----------
    def showEvent(self, ev):
        super().showEvent(ev)
        if getattr(self, '_cursor_filter', None) is None \
                and self.windowHandle() is not None:
            from PySide6.QtCore import QObject, QEvent

            win = self

            class _CursorFix(QObject):
                def eventFilter(self, obj, e):
                    if e.type() == QEvent.MouseMove:
                        try:
                            if e.buttons() == Qt.NoButton:
                                win._refresh_cursor()
                        except Exception:
                            pass
                    return False

            self._cursor_filter = _CursorFix(self)
            self.windowHandle().installEventFilter(self._cursor_filter)
        QTimer.singleShot(0, lambda: apply_titlebar_theme(self, self.dark))

    def _refresh_cursor(self):
        """Setel kursor jendela = kursor efektif widget di bawah mouse.

        Qt hanya memperbarui kursor saat mouse BERPINDAH widget. Bila widget
        berkursor tangan disembunyikan/dihapus (bangun ulang UI, dialog modal,
        ganti tema) kursor tangan bisa tertinggal di area yang tidak dapat
        diklik. Dipanggil pada setiap gerakan mouse (murah: hanya menelusuri
        induk widget)."""
        try:
            if QApplication.overrideCursor() is not None:
                return
            wh = self.windowHandle()
            if wh is None:
                return
            from PySide6.QtGui import QCursor
            w = QApplication.widgetAt(QCursor.pos())
            if w is None or w.window() is not self:
                return
            shape = Qt.ArrowCursor
            while w is not None:
                if w.testAttribute(Qt.WA_SetCursor):
                    shape = w.cursor().shape()
                    break
                if w.isWindow():
                    break
                w = w.parentWidget()
            if shape == Qt.BitmapCursor:
                return                   # kursor khusus: biarkan Qt
            if wh.cursor().shape() != shape:
                wh.setCursor(shape)
        except RuntimeError:
            pass

    def _toggle_theme(self):
        self.dark = not self.dark
        self._begin_transition()
        self.setUpdatesEnabled(False)
        try:
            apply_theme(QApplication.instance(), dark=self.dark)
            apply_titlebar_theme(self, self.dark)
            self._set_logo_pixmap()
            self._set_brand_logo()
            self._set_nav_icons()          # ikon nav mengikuti warna tema
            self._sync_theme_button()
            self._refresh_status()
        finally:
            self.setUpdatesEnabled(True)
            self._end_transition()
            self._refresh_cursor()
