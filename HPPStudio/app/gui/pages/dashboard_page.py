"""Halaman Dashboard — time series interaktif, energy mix, bulanan, heatmap."""
from __future__ import annotations
import colorsys
import numpy as np

from ...config.i18n import tr, get_language
from PySide6.QtCore import QThread, Signal, Qt, QRectF, QPoint, QEvent
from PySide6.QtGui import QColor, QBrush, QPicture, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget,
    QCheckBox, QComboBox, QMessageBox, QSpinBox, QToolButton, QMenu,
    QWidgetAction, QGridLayout, QInputDialog)
import pyqtgraph as pg
from ..bgproc import ProcWorker

from ..theme import SERIES_COLORS, style_plot_legend
from .. import theme as _thm            # baca CURRENT_DARK/FG/BG saat runtime
from ..plotutil import no_wheel_zoom, CursorReadout
from ..widgets import PieChart, KPICard, kpi_grid
from ...engine.simulation import SimulationEngine
from ...config.parameters import to_system_params, cost_config
from ...config import intervals as ivals

# ---------------------------------------------------------------- performa --
# Lebar garis kurva = 1 px (cosmetic, bilangan bulat). Lebar pecahan (mis. 1.3)
# memaksa Qt memakai 'stroker' antialias yang ~40x lebih lambat pada deret
# besar (43.200 titik interval 1 menit: 1,2 s -> 25 ms per gambar ulang).
CURVE_W = 1


def _lighten_curve(item):
    """(Panggil SETELAH item masuk ViewBox — bila sebelum, pyqtgraph gagal
    mencari view saat clipToView aktif.)
    Render ringan untuk satu kurva TANPA mengubah data: hanya titik dalam
    jendela tampil yang digambar (clipToView) & downsampling 'peak' (min/max
    per piksel -> puncak/lembah tetap persis terlihat). Kartu kursor tetap
    membaca data asli."""
    for fn, kw in (('setDownsampling', dict(auto=True, method='peak')),
                   ('setClipToView', None)):
        try:
            f = getattr(item, fn)
            f(**kw) if kw else f(True)
        except Exception:
            pass
    return item


def _lighten_plot(plot):
    """Terapkan clipToView + downsampling peak ke seluruh kurva (sekarang &
    yang ditambahkan kemudian) pada satu PlotWidget."""
    try:
        pi = plot.getPlotItem()
        pi.setDownsampling(auto=True, mode='peak')
        pi.setClipToView(True)
    except Exception:
        pass


def _style_card_once(card):
    """Stylesheet kartu kursor hanya disetel saat tema berubah (dulu disetel
    di SETIAP gerakan mouse -> polish ulang widget tiap event, patah-patah)."""
    key = (_thm.tok('cursor_bg'), _thm.tok('strong'))
    if getattr(card, '_qss_key', None) != key:
        card.setStyleSheet(
            '#CursorCard { background: %s; border: 1px solid %s;'
            'border-radius: 4px; padding: 5px 8px; }' % key)
        card._qss_key = key

MONTHS_ID = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
             'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
DAYS_ID = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min']
DAYS_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def months():
    """Singkatan nama bulan sesuai bahasa aktif."""
    return MONTHS_EN if get_language() == 'EN' else MONTHS_ID


def days():
    return DAYS_EN if get_language() == 'EN' else DAYS_ID


def _fmt_ts(t: float, with_day: bool = True) -> str:
    """Epoch detik (naive) -> 'Sen 13 Jan 2025 14:00'."""
    import numpy as _np
    import pandas as pd
    try:
        ts = pd.Timestamp(_np.datetime64(int(round(float(t))), 's'))
    except Exception:
        return ''
    d = f'{days()[ts.weekday()]} ' if with_day else ''
    return (f'{d}{ts.day} {months()[ts.month - 1]} {ts.year} '
            f'{ts.hour:02d}:{ts.minute:02d}')


def _fmt_dt(sec: float) -> str:
    """Selisih waktu ringkas bertanda: '+2 h 15 m', '−45 m', '+3 d 4 h'."""
    sign = '+' if sec >= 0 else '\u2212'
    m = int(round(abs(float(sec)) / 60.0))
    d, m = divmod(m, 1440)
    h, m = divmod(m, 60)
    if d:
        return f'{sign}{d} d {h} h'
    if h:
        return f'{sign}{h} h {m:02d} m'
    return f'{sign}{m} m'


def _fmt_ts_axis(t: float, step: float) -> str:
    """Label tick sumbu-X ringkas untuk langkah manual (N jam)."""
    import numpy as _np
    import pandas as pd
    try:
        ts = pd.Timestamp(_np.datetime64(int(round(float(t))), 's'))
    except Exception:
        return ''
    if step >= 24 * 3600:                       # langkah harian -> tanggal saja
        return f'{ts.day} {months()[ts.month - 1]}'
    return f'{ts.hour:02d}:{ts.minute:02d}'     # sub-harian -> jam saja (tanpa nomor hari)

# Lebar jendela default grafik Time Series ("Tampil (jam)"), dipakai baik saat
# widget dibangun MAUPUN direset tiap kali ada hasil simulasi baru (lihat
# _apply_result) — sebelumnya direset ke SELURUH durasi yang disimulasikan
# (mis. 8760 jam utk "Setahun penuh"), membuat grafik awal terlalu padat;
# kini SELALU 24 jam, pengguna tinggal perbesar via "Tampil (jam)" bila perlu.
TS_DEFAULT_WINDOW_H = 24

# (kunci series, label, warna, sumbu-kanan?)
TS_SERIES = [
    ('load',       'Load',        SERIES_COLORS['load'], False),
    ('pv_inv_out', 'PV Pen',      SERIES_COLORS['pv'],   False),
    ('deg',        'Diesel',      SERIES_COLORS['deg'],  False),
    ('grid',       'Grid Import', SERIES_COLORS['grid'], False),
    ('dhg',        'BESS Dischg', SERIES_COLORS['bess'], False),
    ('chg',        'BESS Charge', '#0EA5E9',             False),
    ('bess_net',   'BESS Balance', '#14B8A6',  False),
    ('pv_excess',  'Unused/Curtail',   SERIES_COLORS['exc'],  False),
    ('unserved',   'Unserved',    '#EC4899',             False),
    ('soc',        'SOC',         SERIES_COLORS['soc'],  True),
]


# --------------------------------------------------------------------------- #
#  Mode Case Analysis — 32 kasus (Grid status x PV x BESS x DEG)
# --------------------------------------------------------------------------- #
# Empat dimensi (mengikuti tabel):
#   Grid : status 1 / status 0
#   PV   : available / not available            (PV membangkit > 0)
#   BESS : charge / can not charge / discharge / can not discharge
#   DEG  : ON / OFF                             (genset menyala, deg > 0)
# Nomor case = (DEG OFF ? 16 : 0) + (Grid 0 ? 8 : 0) + (PV n/a ? 4 : 0) + idx
#   idx BESS: 1 charge, 2 can not charge, 3 discharge, 4 can not discharge
#   -> case 1..16 = DEG ON ; case 17..32 = DEG OFF.
#
# Aturan BESS (SELARAS rumus dispatch; hanya MEMBACA hasil simulasi + parameter
# sistem — tidak mengubah logika dispatch):
#   charge            : chg > 0
#   discharge         : dhg > 0
#   can not charge    : idle & SOC = maksimum (baterai penuh)
#   can not discharge : idle & energi terkirim efektif BESS < beban jam itu,
#                       memakai potensi discharge yang sama dgn engine
#                       (d_pot = (Z - SOC_min·E)/dt · √η_RT):
#                         (SOC_now - SOC_min) * kapasitas * √η_RT  <  load * dt
#                       -> BESS tak sanggup memikul beban sehingga (mis. karena
#                       PV-BESS interlock dgn Grid/DEG) beban diambil alih penuh
#                       oleh Grid/DEG. Contoh: kap 1629,36 kWh, batas bawah 10%,
#                       SOC 34,5% -> tersedia 399,19 kWh; terkirim efektif
#                       399,19·√0,913 = 381,43 kWh < load 495 kWh => can not
#                       discharge. Kasus SOC tepat di minimum tercakup (0 < load).
#   idle & energi cukup: TIDAK masuk case (tanpa blok warna)
_BESS_STATES = ['charge', 'can not charge', 'discharge', 'can not discharge']
_BESS_SHORT = ['charge', 'no charge', 'dischg', 'no dischg']


def _make_case_colors():
    """32 warna berbeda: hue tersebar (golden-angle) agar antar-case kontras;
    kelompok DEG OFF sengaja lebih redup sebagai isyarat visual."""
    cols = {}
    for c in range(1, 33):
        h = ((c - 1) * 0.6180339887) % 1.0
        deg_on = c <= 16
        s = 0.72 if deg_on else 0.50
        val = 0.96 if deg_on else 0.78
        r, g, b = colorsys.hsv_to_rgb(h, s, val)
        cols[c] = (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))
    return cols


CASE_COLORS = _make_case_colors()


def case_text(c: int) -> str:
    """Deskripsi lengkap (tooltip) untuk nomor case 1..32."""
    deg_on = c <= 16
    cc = c if deg_on else c - 16          # 1..16 di dalam kelompok DEG
    grid = 'Grid status 1' if cc <= 8 else 'Grid status 0'
    pv = 'PV available' if ((cc - 1) % 8) < 4 else 'PV not available'
    bess = _BESS_STATES[(cc - 1) % 4]
    deg = 'DEG ON' if deg_on else 'DEG OFF'
    return f'Case {c}:  {grid}  ·  {pv}  ·  BESS {bess}  ·  {deg}'


def case_short(c: int) -> str:
    """Label ringkas untuk daftar filter (DEG sudah jadi judul kolom)."""
    deg_on = c <= 16
    cc = c if deg_on else c - 16
    g = '1' if cc <= 8 else '0'
    pv = 'PV✓' if ((cc - 1) % 8) < 4 else 'PV✗'
    return f'C{c}  ·  G{g} {pv} · {_BESS_SHORT[(cc - 1) % 4]}'


def classify_cases(series: dict, soc_min: float, soc_max: float,
                   bess_kwh: float = 0.0, dt: float = 1.0,
                   rte: float = 1.0) -> np.ndarray:
    """Nomor case 1..32 tiap jam (0 = tanpa case). Murni dari deret terekam:
    grid_status, pv (EArray), chg, dhg, soc, deg, load. Tidak menyentuh logika
    simulasi. `bess_kwh`, `dt`, `rte` dipakai untuk uji 'can not discharge'
    memakai potensi discharge yang SAMA dengan engine
    (d_pot = (Z - SOC_min·E)/dt · √η_RT)."""
    n = int(np.asarray(series['load']).reshape(-1).shape[0])

    def col(k):
        return np.asarray(series.get(k, np.zeros(n)), float).reshape(n, -1)[:, 0]

    grid_on = col('grid_status') > 0.5
    pv_avail = col('pv') > 1e-6
    deg_on = col('deg') > 1e-6            # genset menyala jam itu
    chg, dhg, soc, load = col('chg'), col('dhg'), col('soc'), col('load')
    tol, eps = 1e-6, 1e-4
    # energi BESS yang benar-benar TERKIRIM (efektif) jam ini (kWh), selaras
    # rumus dispatch: d_pot = (Z - SOC_min·E)/dt · √η_RT  → energi = d_pot·dt
    srte = float(np.sqrt(max(float(rte), 0.0)))
    avail = (soc - soc_min) * float(bess_kwh) * srte
    need = load * float(dt)               # beban jam itu (kWh, dt jam)
    b = np.zeros(n, dtype=int)
    b[soc >= soc_max - eps] = 2           # penuh -> can not charge (prioritas rendah)
    if float(bess_kwh) > tol:
        # can not discharge: energi terkirim efektif tak cukup memikul beban jam
        # itu (mis. beban diambil alih Grid/DEG karena interlock). Menimpa
        # 'penuh' pada kasus langka penuh-namun-tak-cukup.
        b[avail < need - 1e-9] = 4
    b[dhg > tol] = 3                      # benar-benar discharge -> discharge
    b[chg > tol] = 1                      # benar-benar charge    -> charge
    base = (np.where(deg_on, 0, 16) + np.where(grid_on, 0, 8)
            + np.where(pv_avail, 0, 4))
    return np.where(b > 0, base + b, 0).astype(int)


def case_runs(cases: np.ndarray, x: np.ndarray, allowed=None):
    """Gabungkan jam berurutan dengan case sama -> [(x0, x1, (r,g,b)), ...].
    `allowed` (set/None): bila diberikan, hanya case di dalamnya yang dibuat."""
    n = len(cases)
    if n == 0:
        return []
    dt = float(x[1] - x[0]) if n > 1 else 3600.0
    runs, i = [], 0
    while i < n:
        c = int(cases[i])
        j = i
        while j + 1 < n and int(cases[j + 1]) == c:
            j += 1
        if c > 0 and (allowed is None or c in allowed):
            runs.append((float(x[i]), float(x[j]) + dt, CASE_COLORS[c]))
        i = j + 1
    return runs


class CaseOverlay(pg.GraphicsObject):
    """Blok warna vertikal (opacity 10%) per run case. Dilukis sekali via
    QPicture; dikecualikan dari auto-range sumbu (dataBounds None)."""

    def __init__(self):
        super().__init__()
        self._runs = []
        self._pic = None
        self.setZValue(-1000)

    def set_runs(self, runs):
        self._runs = runs
        self._pic = None
        self.prepareGeometryChange()
        self.update()

    def _build(self):
        self._pic = QPicture()
        qp = QPainter(self._pic)
        qp.setPen(pg.mkPen(None))
        Y = 1e9
        for x0, x1, (r, g, b) in self._runs:
            qp.setBrush(QBrush(QColor(r, g, b, 64)))    # 64/255 ~= 25% opacity
            qp.drawRect(QRectF(x0, -Y, x1 - x0, 2 * Y))
        qp.end()

    def paint(self, p, *args):
        if self._pic is None:
            self._build()
        self._pic.play(p)

    def boundingRect(self):
        if not self._runs:
            return QRectF()
        x0 = min(r[0] for r in self._runs)
        x1 = max(r[1] for r in self._runs)
        return QRectF(x0, -1e9, x1 - x0, 2e9)

    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        return [None, None]         # jangan pengaruhi auto-range


class _SimWorker(ProcWorker):   # proses latar (lihat gui/bgproc.py)
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(int)              # persen 0..100

    def __init__(self, state, start_h: int = 0, window_h=None):
        super().__init__()
        self.state = state
        self.start_h = int(start_h)
        self.window_h = None if window_h is None else int(window_h)

    def run(self):
        try:
            st = self.state
            lab = str(st.cfg.get('sim_interval', '1 hour'))
            # Bangun profil pada interval terpilih (resample per-jam / dijendela),
            # mulai dari titik waktu pilihan pengguna (start_h jam dari awal data)
            # sepanjang DURASI pilihan (window_h). None -> jendela penuh interval.
            L, P, G, dt_h, n, D = ivals.build_sim_arrays(
                st.load, st.pv_norm, st.grid_status, st.datetimes, lab,
                start_h=self.start_h, window_h=self.window_h,
                deg=st.deg_status)
            try:
                start_dt = ivals.window_start_datetime(st.datetimes, self.start_h)
                dts = ivals.make_datetimes(lab, n, start=start_dt)
            except Exception:
                dts = None
            eng = SimulationEngine(L, P, G, datetimes=dts, deg_status=D)

            def _cb(done, total):
                self.progress.emit(int(done * 100 / max(total, 1)))

            # Annualisasi dari jam yang BENAR-BENAR disimulasikan (n × dt) —
            # setahun penuh -> 1.0 (paritas Excel tetap).
            ann = ivals.annualization_factor_h(max(1e-9, n * dt_h))
            res = eng.run(to_system_params(st.cfg),
                          cost_cfg=cost_config(st.cfg), record=True,
                          annualize=ann, progress=_cb)
            res['sim_interval'] = lab
            res['window_start_h'] = self.start_h
            res['window_h'] = int(round(n * dt_h))
            # mode shaping PV yang aktif (utk label grafik Advanced EMS)
            _adv = str(st.cfg.get('bess_mode', 'Standard')) == 'Advanced'
            res['adv_pv_smooth'] = bool(_adv and st.cfg.get('m_pv_smooth', False))
            res['adv_firming'] = bool(_adv and st.cfg.get('m_firming', False))
            self.finished_ok.emit(res)
        except Exception as e:  # pragma: no cover
            self.failed.emit(str(e))


class DashboardPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self._worker = None
        pg.setConfigOptions(antialias=True)

        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        t = QLabel(tr('Dashboard')); t.setObjectName('PageTitle')
        head.addWidget(t); head.addStretch(1)
        # Titik MULAI jendela simulasi (untuk interval sub-tahun mis. 1 menit =
        # 1 bulan): pilih bulan & tanggal awal dari data yang diimpor.
        self.lbl_start = QLabel(tr('Mulai:'))
        head.addWidget(self.lbl_start)
        self.cmb_month = QComboBox()
        self.cmb_month.addItems(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])
        self.cmb_month.setToolTip(tr(
            'Bulan awal jendela simulasi (interval sub-tahun). Diabaikan untuk '
            'interval 1 jam / 30 menit yang mencakup setahun penuh.'))
        head.addWidget(self.cmb_month)
        self.spin_day = QSpinBox(); self.spin_day.setRange(1, 31)
        self.spin_day.setToolTip(tr('Tanggal awal jendela simulasi (1-31).'))
        head.addWidget(self.spin_day)
        # Durasi SIMULASI (preset) — jam yang BENAR-BENAR dihitung engine, dari
        # titik Mulai. Interval lebih halus membatasi durasi maksimum. Opsi
        # dibangun ulang mengikuti interval aktif (_refresh_dur_options).
        self.lbl_dur = QLabel(tr('Durasi simulasi:'))
        head.addWidget(self.lbl_dur)
        self.cmb_dur = QComboBox()
        self.cmb_dur.setToolTip(tr(
            'Durasi (jendela) yang BENAR-BENAR disimulasikan, dihitung dari '
            'titik Mulai. Interval lebih halus membatasi durasi maksimum '
            '(mis. 1 menit → maks 1 bulan; 1 detik → maks 1 hari). KPI '
            'kWh/tahun diekstrapolasi dari jendela ini.'))
        self._dur_labels_h: list = []          # [(label_id, jam)] utk interval aktif
        head.addWidget(self.cmb_dur)
        self._refresh_dur_options()
        # Pulihkan Start/Durasi (setelan jendela simulasi proyek bersama) & simpan
        # tiap kali diubah, agar Multi-Year/Optimization memakai jendela yang SAMA.
        self._restore_sim_window()
        self.cmb_month.currentIndexChanged.connect(
            lambda *_: self._persist_sim_window())
        self.spin_day.valueChanged.connect(
            lambda *_: self._persist_sim_window())
        self.cmb_dur.currentIndexChanged.connect(
            lambda *_: (None if getattr(self, '_dur_syncing', False)
                        else self._persist_sim_window()))
        self.btn_run = QPushButton(tr('▶  Run Simulation'))
        self.btn_run.clicked.connect(self._run)
        head.addWidget(self.btn_run)
        self.btn_clear = QPushButton(tr('Bersihkan Hasil'))
        self.btn_clear.setProperty('flat', True)
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setToolTip(tr(
            'Hapus hasil simulasi beserta seluruh grafiknya.'))
        self.btn_clear.clicked.connect(self._clear_results)
        head.addWidget(self.btn_clear)
        lay.addLayout(head)
        self.lbl_status = QLabel(tr('Import data lalu jalankan simulasi.'))
        self.lbl_status.setObjectName('PageSub')
        lay.addWidget(self.lbl_status)

        self.cards = {k: KPICard(lbl, '-', tr(unit)) for k, lbl, unit in [
            ('rf', tr('Renewable Fraction'), '%'),
            ('pv', 'PV Generation', 'kWh/th'),
            ('fuel', tr('Diesel Fuel'), 'L/th'),
            ('grid', tr('Grid Import'), 'kWh/th')]}
        lay.addWidget(kpi_grid(list(self.cards.values()), cols=4))

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_ts_tab(), tr('Time Series'))
        self._idx_adv = self.tabs.addTab(self._build_adv_tab(), tr('Advanced (EMS)'))
        self.tabs.addTab(self._build_mix_tab(), tr('Energy Mix'))
        self.tabs.addTab(self._build_month_tab(), tr('Bulanan'))
        self.tabs.addTab(self._build_heat_tab(), tr('Heatmap'))
        # Pemilih HARI utk tab Advanced (EMS): hanya relevan & tampil bila (a)
        # tab Advanced (EMS) aktif, DAN (b) jendela yang disimulasikan > 1 hari
        # (24 jam) -- lihat _build_adv_day_picker/_update_adv_day_visibility.
        # Diletakkan sbg corner widget shg tak memakan baris kontrol tiap tab.
        self.tabs.setCornerWidget(self._build_adv_day_picker(), Qt.TopRightCorner)
        self.tabs.currentChanged.connect(self._update_adv_day_visibility)
        self._update_adv_day_visibility()

        state.profiles_changed.connect(self._on_profiles)
        # interval simulasi (Parameters) berubah -> perbarui opsi Durasi simulasi
        state.config_changed.connect(self._refresh_dur_options)
        state.results_cleared.connect(self._on_cleared)
        self._on_profiles()
        if state.last_result:            # pulihkan hasil terakhir
            try:
                self._apply_result(state.last_result)
            except Exception:            # berkas lama/rusak: abaikan
                state.last_result = None
        # Pulihkan Mode Case Analysis (mode + filter case) agar tidak hilang
        # saat UI dibangun ulang, mis. ketika mengganti bahasa.
        self._case_enabled = dict(getattr(state, 'case_enabled', {}) or {})
        if getattr(state, 'case_mode', False):
            self.chk_case.setChecked(True)   # -> _toggle_case -> gambar overlay

    # ---------------- tab builders ----------------
    def _build_ts_tab(self) -> QWidget:
        w = QWidget(); w.setObjectName('DashTabCard')
        v = QVBoxLayout(w); v.setContentsMargins(8, 6, 8, 6)
        # Baris 1 — pemilih deret (checkbox), dibungkus agar tak tumpang tindih.
        row = QHBoxLayout(); row.setSpacing(10)
        self.checks: dict[str, QCheckBox] = {}
        for key, label, color, _r in TS_SERIES:
            cb = QCheckBox(tr(label))
            cb.setChecked(key in ('load', 'pv_inv_out', 'deg', 'grid', 'soc'))
            cb.setStyleSheet(f'color: {color}; font-weight: 600;')
            cb.toggled.connect(self._refresh_ts)
            self.checks[key] = cb
            row.addWidget(cb)
        row.addStretch(1)
        v.addLayout(row)

        # Baris 2 — Mode Case Analysis + filter case + lebar jendela.
        row2 = QHBoxLayout(); row2.setSpacing(8)
        self.chk_case = QCheckBox(tr('Mode Case Analysis'))
        self.chk_case.setStyleSheet('font-weight: 600;')
        self.chk_case.setToolTip(tr(
            'Tandai grafik dengan blok warna sesuai 16 case '
            '(Grid status × PV × BESS). Arahkan kursor ke blok untuk '
            'melihat keterangan case.'))
        self.chk_case.toggled.connect(self._toggle_case)
        row2.addWidget(self.chk_case)
        self.btn_cases = QToolButton()
        self.btn_cases.setText(tr('Pilih Case') + '  ▾')
        self.btn_cases.setPopupMode(QToolButton.InstantPopup)
        # panah dropdown cukup satu (yang menyatu di teks '▾'); sembunyikan
        # indikator-menu bawaan QToolButton agar tidak muncul dua panah.
        self.btn_cases.setStyleSheet(
            'QToolButton{padding:2px 8px;} '
            'QToolButton::menu-indicator{image:none; width:0;}')
        self.btn_cases.setToolTip(tr('Pilih case mana yang blok warnanya '
                                     'ditampilkan.'))
        self.btn_cases.setVisible(False)
        row2.addWidget(self.btn_cases)
        row2.addSpacing(12)
        # Petunjuk navigasi grafik (berubah jadi info pin saat pin aktif)
        self.lbl_hint = QLabel('')
        self.lbl_hint.setObjectName('PageSub')
        row2.addWidget(self.lbl_hint)
        row2.addStretch(1)
        # Interval TAMPILAN: agregasi hasil simulasi ke resolusi ini (rata-rata
        # daya/SOC). 'Match simulation' = apa adanya. Lebih halus dari interval
        # simulasi otomatis diabaikan (dibatasi ke resolusi simulasi).
        row2.addWidget(QLabel(tr('Interval tampilan:')))
        self.disp_interval = QComboBox()
        self.disp_interval.addItems([tr(x) for x in ivals.DISPLAY_ORDER])
        self.disp_interval.setToolTip(
            tr('Resolusi tampilan grafik (agregasi dari hasil simulasi).'))
        self._disp_labels = list(ivals.DISPLAY_ORDER)
        self.disp_interval.currentIndexChanged.connect(self._refresh_ts)
        row2.addWidget(self.disp_interval)
        row2.addSpacing(10)
        row2.addWidget(QLabel(tr('Tampil (jam):')))
        self.win_hours = QSpinBox()
        self.win_hours.setRange(1, 8784)
        self.win_hours.setValue(TS_DEFAULT_WINDOW_H)
        self.win_hours.setFixedWidth(96)
        self.win_hours.setToolTip(
            tr('Lebar jendela tampilan time series '
               '(jumlah jam/data yang ditampilkan)'))
        self.win_hours.valueChanged.connect(self._apply_window)
        row2.addWidget(self.win_hours)
        # Zoom: seret-kiri (drag) membentuk kotak zoom; klik-kanan → "Reset view".
        v.addLayout(row2)

        # Langkah/tick sumbu diatur lewat KLIK-KANAN pada masing-masing sumbu
        # (kiri kW, kanan %, bawah jam) — tidak memakai baris kontrol agar tidak
        # memakan ruang grafik. Nilai 0 = otomatis. Lihat _on_axis_rclick.
        self._axis_step = {'yl': 0.0, 'yr': 0.0, 'x': 0.0}

        info = QHBoxLayout()
        self.lbl_cursor = QLabel(''); self.lbl_cursor.setObjectName('PageSub')
        self.lbl_cursor.setWordWrap(True)   # teks panjang turun ke bawah
        self.lbl_range = QLabel(''); self.lbl_range.setObjectName('PageSub')
        info.addWidget(self.lbl_cursor, 1)
        info.addWidget(self.lbl_range, 0, Qt.AlignTop | Qt.AlignRight)
        v.addLayout(info)

        self.plot = pg.PlotWidget(
            axisItems={'bottom': pg.DateAxisItem(utcOffset=0)})
        no_wheel_zoom(self.plot)
        _lighten_plot(self.plot)
        self.plot.showGrid(x=True, y=True, alpha=0.1)   # opacity grid default 10%
        self.plot.setLabel('left', tr('Daya (kW)'))
        self.plot.setLabel('bottom', tr('Waktu'))
        # tanpa legend di dalam grafik — checkbox seri di atas sudah jadi legend
        # Rentang-Y dikelola manual (lihat _apply_default_yranges) agar sumbu
        # kiri/kanan tidak saling menyilang; jadi auto-range Y dimatikan.
        self.plot.getPlotItem().vb.enableAutoRange(x=False, y=False)
        # sumbu kanan untuk SOC
        self.right_vb = pg.ViewBox()
        no_wheel_zoom(self.right_vb)
        pi = self.plot.getPlotItem()
        pi.showAxis('right')
        pi.scene().addItem(self.right_vb)
        pi.getAxis('right').linkToView(self.right_vb)
        self.right_vb.setXLink(pi.vb)
        pi.getAxis('right').setLabel('SOC (%)')
        pi.vb.sigResized.connect(self._sync_right_vb)
        self._install_right_y_menu()     # menu klik-kanan: Y axis (kiri) & (kanan)
        # Zoom: seret-kiri kotak; klik-kanan → Reset view (kembali ke jendela).
        self._setup_box_zoom(self.plot, lambda: self._reset_view(self.plot,
                                                                 sync_region=True))
        v.addWidget(self.plot, 3)

        self.overview = pg.PlotWidget(
            axisItems={'bottom': pg.DateAxisItem(utcOffset=0)})
        no_wheel_zoom(self.overview)
        _lighten_plot(self.overview)
        self.overview.setMaximumHeight(90)
        self.overview.hideAxis('left'); self.overview.showGrid(x=True, alpha=0.15)
        self.region = pg.LinearRegionItem([0, 168])
        self.region.sigRegionChanged.connect(
            lambda: self.plot.setXRange(*self.region.getRegion(), padding=0))
        self.plot.sigXRangeChanged.connect(
            lambda _, rng: self.region.setRegion(rng))
        self.plot.sigXRangeChanged.connect(self._update_range_label)
        self.overview.addItem(self.region)
        v.addWidget(self.overview, 1)
        self._x = None
        self._s_last = None
        # Snapshot tampilan TEPAT SEBELUM drag-zoom kotak (dipakai "Reset view"
        # utk mengembalikan rentang-X & Window(jam) persis spt sebelum di-zoom).
        self._ts_prezoom = None          # (lo, hi, win_hours) atau None
        self._restore_range = None       # (lo, hi) yg diminta dipulihkan _refresh_ts
        self._cases = None
        self._case_mode = False
        self._case_enabled = {}          # nomor case -> bool (tampil/tidak)
        self.case_overlay = CaseOverlay()
        # --- Kartu titik-data melayang (mengikuti kursor) — gaya gambar acuan:
        # header waktu + tiap seri dengan titik warna & nilai. Menyesuaikan tema.
        self._point_box = QLabel(self.plot.viewport())
        self._point_box.setObjectName('CursorCard')
        self._point_box.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._point_box.setTextFormat(Qt.RichText)
        self._point_box.hide()
        # crosshair vertikal + penanda lingkaran per seri di posisi kursor
        self._cursor_vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen((150, 150, 150, 170), width=1))
        self._cursor_vline.setZValue(50)
        self._cursor_vline.hide()
        self._cursor_dots = pg.ScatterPlotItem(size=11)     # seri sumbu kiri
        self._cursor_dots.setZValue(60)
        self._cursor_dots_r = pg.ScatterPlotItem(size=11)   # SOC (sumbu kanan)
        self._cursor_dots_r.setZValue(60)
        self._proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved,
                                     rateLimit=60, slot=self._on_mouse_move)
        # Klik-kanan pada sumbu -> atur langkah/tick sumbu itu (kiri/kanan/bawah).
        self.plot.scene().sigMouseClicked.connect(self._on_axis_rclick)
        # Klik-kiri = pin pembanding; klik-ganda = lepas pin + reset tampilan.
        self.plot.scene().sigMouseClicked.connect(self._on_plot_click)
        self._pin_x = None
        self._pin_line = None
        from PySide6.QtGui import QShortcut, QKeySequence
        _esc = QShortcut(QKeySequence(Qt.Key_Escape), self.plot)
        _esc.setContext(Qt.WidgetWithChildrenShortcut)
        _esc.activated.connect(lambda: self._set_pin(None))
        self.plot.setFocusPolicy(Qt.ClickFocus)
        self._update_pin_hint()
        # kursor keluar dari widget grafik -> sembunyikan kartu (sigMouseMoved
        # tidak lagi terpicu setelah kursor keluar, jadi perlu event Leave).
        self.plot.viewport().installEventFilter(self)
        return w

    def _on_axis_rclick(self, ev):
        """Klik-kanan pada area sumbu -> dialog isian langkah/tick sumbu itu.
        Wilayah sumbu ditentukan relatif kotak data (ViewBox): di kiri = sumbu
        Y-kiri (kW), di kanan = Y-kanan (%), di bawah = X (jam). Klik di dalam
        area data dibiarkan (menu bawaan grafik tetap muncul)."""
        try:
            if ev.button() != Qt.RightButton:
                return
            sp = ev.scenePos()
        except Exception:
            return
        vbr = self.plot.getPlotItem().vb.sceneBoundingRect()
        x, y = sp.x(), sp.y()
        if x < vbr.left():
            spec = ('yl', tr('Langkah tick sumbu Y-kiri (kW)'), 100000.0)
        elif x > vbr.right():
            spec = ('yr', tr('Langkah tick sumbu Y-kanan (%)'), 100.0)
        elif y > vbr.bottom():
            spec = ('x', tr('Langkah tick sumbu X (jam)'), 8784.0)
        else:
            return                       # di dalam area data -> bukan klik sumbu
        try:
            ev.accept()
        except Exception:
            pass
        self._prompt_axis_step(*spec)

    def _prompt_axis_step(self, which, title, maxv):
        """Minta nilai langkah tick untuk sumbu terpilih (0 = otomatis)."""
        cur = float(self._axis_step.get(which, 0.0))
        val, ok = QInputDialog.getDouble(
            self, tr('Langkah Sumbu'),
            f"{title}  —  {tr('0 = otomatis')}",
            cur, 0.0, float(maxv), 2)
        if ok:
            self._axis_step[which] = float(val)
            self._apply_axis_steps()

    def _install_right_y_menu(self):
        """Sisipkan submenu 'Y axis (right)' pada menu klik-kanan grafik agar
        sumbu-Y KANAN (SOC) juga bisa diatur (Manual/Auto/Invert/dll.), bukan
        hanya sumbu-Y kiri. Memakai ViewBoxMenu bawaan right_vb yang sudah
        terikat ke view kanan. Judul dibiarkan bahasa Inggris agar seragam
        dengan menu bawaan pyqtgraph (View All, X axis, Mouse Mode, ...)."""
        try:
            main_menu = self.plot.getPlotItem().vb.menu
            r_menu = self.right_vb.menu

            def _y_action(menu):
                for a in menu.actions():
                    sub = a.menu()
                    if sub is not None and (a.text() or '').strip().lower()\
                            .startswith('y'):
                        return a
                return None

            my = _y_action(main_menu)
            ry = _y_action(r_menu)
            if my is None or ry is None:
                return
            my.menu().setTitle('Y axis (left)')
            ry.menu().setTitle('Y axis (right)')
            acts = main_menu.actions()
            idx = acts.index(my)
            before = acts[idx + 1] if idx + 1 < len(acts) else None
            if before is not None:
                main_menu.insertMenu(before, ry.menu())
            else:
                main_menu.addMenu(ry.menu())
        except Exception:
            pass

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel:
            try:
                if obj is self.plot.viewport():
                    x = self._x
                    b = ((float(x[0]), float(x[-1]), float(x[1] - x[0]))
                         if x is not None and len(x) > 1 else None)
                    if self._wheel_nav(self.plot, ev, b):
                        ev.accept()
                        return True
                elif (hasattr(self, 'adv_power')
                      and obj in (self.adv_power.viewport(),
                                  self.adv_ramp.viewport())):
                    x = getattr(self, '_adv_x', None)
                    b = ((float(x[0]), float(x[-1]), float(x[1] - x[0]))
                         if x is not None and len(x) > 1 else None)
                    _pl = (self.adv_ramp if obj is self.adv_ramp.viewport()
                           else self.adv_power)
                    if self._wheel_nav(_pl, ev, b):
                        ev.accept()
                        return True
            except Exception:
                pass
        if ev.type() == QEvent.Leave:
            if obj is getattr(self.plot, 'viewport', lambda: None)():
                self._hide_cursor_extras()
            elif (hasattr(self, 'adv_power')
                  and obj is self.adv_power.viewport()):
                self._hide_adv_cursor()
        elif ev.type() == QEvent.MouseButtonPress:
            # Rekam tampilan TEPAT SEBELUM drag-zoom kotak dimulai (klik-kiri di
            # area grafik Time Series) -> "Reset view" mengembalikan persis ke
            # sini (rentang-X + Window jam), bukan sekadar jendela default.
            try:
                if (obj is self.plot.viewport() and ev.button() == Qt.LeftButton
                        and self._x is not None and len(self._x) >= 2):
                    lo, hi = self.plot.getPlotItem().vb.viewRange()[0]
                    self._ts_prezoom = (float(lo), float(hi),
                                        int(self.win_hours.value()))
            except Exception:
                pass
        return super().eventFilter(obj, ev)

    def _toggle_case(self, on):
        self._case_mode = bool(on)
        self.state.case_mode = self._case_mode      # bertahan lintas bahasa
        self.btn_cases.setVisible(self._case_mode)
        if not self._case_mode:
            self.lbl_cursor.setText('')     # teks case tampil di baris atas
        # Hanya perbarui blok warna case — JANGAN gambar ulang seluruh grafik,
        # agar setelan sumbu (X maupun Y kiri/kanan) tidak ter-reset.
        self._apply_case_overlay()

    def _apply_case_overlay(self):
        """Tambah/hapus blok warna case TANPA menyentuh rentang sumbu.
        Dipakai saat mengaktif/menonaktifkan Mode Case Analysis sehingga
        setelan zoom/rentang X & Y (kiri/kanan) tetap seperti apa adanya."""
        try:
            self.plot.removeItem(self.case_overlay)
        except Exception:
            pass
        if not self._case_mode or self._s_last is None or self._x is None:
            self._cases = None
            return
        self._cases = self._compute_cases(self._s_last)
        if self._cases is None:
            return
        present = self._present_cases()
        self._rebuild_cases_menu(present)
        allowed = {c for c in present if self._case_enabled.get(c, True)}
        self.case_overlay.set_runs(case_runs(self._cases, self._x, allowed))
        self.plot.addItem(self.case_overlay)     # zValue -1000 -> di belakang

    def _apply_axis_steps(self):
        """Terapkan langkah/tick manual untuk sumbu Y-kiri (kW), Y-kanan (%),
        dan X (jam) dari nilai yang diisi via klik-kanan. 0 = otomatis."""
        pi = self.plot.getPlotItem()
        # --- sumbu Y kiri (daya, kW) ---
        try:
            s = float(self._axis_step.get('yl', 0.0))
            axL = pi.getAxis('left')
            axL.setTickSpacing(major=s, minor=s) if s > 0 else axL.setTickSpacing()
        except Exception:
            pass
        # --- sumbu Y kanan (SOC, %) ---
        try:
            s = float(self._axis_step.get('yr', 0.0))
            axR = pi.getAxis('right')
            axR.setTickSpacing(major=s, minor=s) if s > 0 else axR.setTickSpacing()
        except Exception:
            pass
        # --- sumbu X (waktu, jam) ---
        self._apply_xstep()

    def _apply_xstep(self):
        """Tick sumbu-X manual tiap N jam. DateAxisItem menimpa tickValues,
        jadi tick dihitung sendiri untuk rentang yang sedang tampil dan
        diperbarui setiap kali rentang X berubah (pan/zoom)."""
        import math
        ax = self.plot.getPlotItem().getAxis('bottom')
        try:
            h = float(self._axis_step.get('x', 0.0))
        except Exception:
            h = 0.0
        if h <= 0:
            ax.setTicks(None)                       # kembali otomatis
            return
        lo, hi = self.plot.getPlotItem().vb.viewRange()[0]
        if not (hi > lo):
            return
        step = h * 3600.0
        start = math.ceil(lo / step) * step
        ticks, t, guard = [], start, 0
        while t <= hi and guard < 500:
            ticks.append((t, _fmt_ts_axis(t, step)))
            t += step
            guard += 1
        ax.setTicks([ticks, []])

    def _apply_default_yranges(self, left_vals):
        """Rentang-Y tampilan awal agar kurva sumbu KIRI (daya) & KANAN (SOC)
        tidak saling menyilang:
          * sumbu KANAN (SOC 0–100%) didorong ke ATAS  -> batas BAWAH diturunkan
          * sumbu KIRI  (daya)       didorong ke BAWAH -> batas ATAS  dinaikkan
        """
        # SOC tampil? (checkbox). Bila SOC DISEMBUNYIKAN, sumbu KIRI auto-match
        # (fit ketat ke deret daya, penuh bingkai). Bila SOC tampil, pakai
        # tata-letak terbagi: SOC (kanan) di paruh atas, daya (kiri) di paruh bawah.
        soc_on = True
        try:
            soc_on = self.checks['soc'].isChecked()
        except Exception:
            pass
        self.right_vb.setYRange(-105.0, 105.0, padding=0)
        lvb = self.plot.getPlotItem().vb
        if left_vals:
            allv = np.concatenate([np.asarray(v, float).reshape(-1)
                                   for v in left_vals])
            allv = allv[np.isfinite(allv)]
        else:
            allv = np.empty(0)
        if allv.size:
            dmin = float(np.min(allv))
            dmax = float(np.max(allv))
            if dmax <= dmin:
                dmax = dmin + 1.0
            rng = dmax - dmin
            pad = 0.05 * rng
            if soc_on:
                # batas atas dinaikkan sebesar satu rentang penuh -> data paruh bawah
                lvb.setYRange(dmin - pad, dmax + rng + pad, padding=0)
            else:
                # SOC hidden: fit ketat ke daya (auto-match, penuh bingkai)
                lvb.setYRange(dmin - pad, dmax + pad, padding=0)
        else:
            lvb.setYRange(0.0, 100.0, padding=0)

    def _save_case_filter(self):
        self.state.case_enabled = dict(self._case_enabled)

    # ---- filter case (dropdown 2 kolom: DEG ON | DEG OFF) ----
    def _case_checkbox(self, c):
        self._case_enabled.setdefault(c, True)
        cb = QCheckBox(case_short(c))
        cb.setToolTip(case_text(c))
        r, g, b = CASE_COLORS[c]
        cb.setStyleSheet(f'QCheckBox{{color: rgb({r},{g},{b}); font-weight:600;'
                         f' padding:2px 10px;}}')
        cb.setChecked(self._case_enabled[c])
        cb.toggled.connect(lambda on_, cc=c: self._on_case_box(cc, on_))
        self._case_boxes[c] = cb
        return cb

    def _rebuild_cases_menu(self, present):
        """Menu centang 2 kolom: case 1–16 (DEG ON) di kiri, 17–32 (DEG OFF)
        di kanan — hanya case yang muncul pada hasil saat ini."""
        menu = QMenu(self.btn_cases)
        a_all = menu.addAction(tr('Tampilkan semua'))
        a_all.triggered.connect(lambda: self._set_all_cases(True))
        a_none = menu.addAction(tr('Sembunyikan semua'))
        a_none.triggered.connect(lambda: self._set_all_cases(False))
        menu.addSeparator()
        self._case_boxes = {}
        cont = QWidget()
        grid = QGridLayout(cont)
        grid.setContentsMargins(8, 4, 8, 6)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(1)
        left = [c for c in present if c <= 16]
        right = [c for c in present if c >= 17]

        def _hdr(text):
            lbl = QLabel(text)
            lbl.setStyleSheet('color:%s; font-weight:700; padding:2px 6px;'
                              % _thm.tok('muted'))
            return lbl
        grid.addWidget(_hdr('DEG ON  ·  Case 1–16'), 0, 0)
        grid.addWidget(_hdr('DEG OFF  ·  Case 17–32'), 0, 1)
        for row in range(max(len(left), len(right))):
            if row < len(left):
                grid.addWidget(self._case_checkbox(left[row]), row + 1, 0)
            if row < len(right):
                grid.addWidget(self._case_checkbox(right[row]), row + 1, 1)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(cont)
        menu.addAction(wa)
        self.btn_cases.setMenu(menu)
        self._update_cases_btn_text()

    def _on_case_box(self, c, on):
        self._case_enabled[c] = bool(on)
        self._save_case_filter()
        self._redraw_case_overlay()
        self._update_cases_btn_text()

    def _set_all_cases(self, on):
        for c in list(self._case_boxes):
            self._case_enabled[c] = on
            self._case_boxes[c].blockSignals(True)
            self._case_boxes[c].setChecked(on)
            self._case_boxes[c].blockSignals(False)
        self._save_case_filter()
        self._redraw_case_overlay()
        self._update_cases_btn_text()

    def _present_cases(self):
        if self._cases is None:
            return []
        return sorted({int(v) for v in self._cases if int(v) > 0})

    def _update_cases_btn_text(self):
        present = self._present_cases()
        on = sum(1 for c in present if self._case_enabled.get(c, True))
        self.btn_cases.setText(tr('Pilih Case') + f'  ({on}/{len(present)})  ▾')

    def _redraw_case_overlay(self):
        if not self._case_mode or self._cases is None or self._x is None:
            return
        allowed = {c for c in self._present_cases()
                   if self._case_enabled.get(c, True)}
        self.case_overlay.set_runs(case_runs(self._cases, self._x, allowed))

    def _compute_cases(self, s):
        if s is None or 'grid_status' not in s or 'soc' not in s:
            return None
        r = self.state.last_result
        p = r.get('params') if isinstance(r, dict) else None
        smin = getattr(p, 'soc_min', None)
        smax = getattr(p, 'soc_max', None)
        bess = getattr(p, 'bess_kwh', None)
        dt = getattr(p, 'interval_h', None)
        rte = getattr(p, 'rte', None)
        if smin is None:
            smin = float(self.state.cfg.get('soc_min', 0.1))
        if smax is None:
            smax = float(self.state.cfg.get('soc_max', 0.95))
        if bess is None:
            bess = float(self.state.cfg.get('bess_kwh', 0.0))
        if rte is None:
            rte = float(self.state.cfg.get('rte', 1.0))
        dt = float(dt) if dt else 1.0
        try:
            return classify_cases(s, float(smin), float(smax),
                                  float(bess), dt, float(rte))
        except Exception:
            return None

    def _update_range_label(self, *_):
        if self._x is None:
            return
        lo, hi = self.plot.getPlotItem().vb.viewRange()[0]
        self.lbl_range.setText(
            tr('Rentang tampil:') + f'  {_fmt_ts(lo)}  –  {_fmt_ts(hi)}')
        # Window (jam) mengikuti TOTAL jam yang benar-benar tampil, termasuk
        # bila lebar diubah lewat time-bar/zoom di grafik (bukan hanya input).
        wh = getattr(self, 'win_hours', None)
        if wh is not None:
            hrs = int(round((hi - lo) / 3600.0))
            hrs = max(wh.minimum(), min(hrs, wh.maximum()))
            if hrs != wh.value():
                wh.blockSignals(True)
                wh.setValue(hrs)
                wh.blockSignals(False)
        # Tick sumbu-X manual dihitung ulang mengikuti rentang baru.
        if float(getattr(self, '_axis_step', {}).get('x', 0.0)) > 0:
            self._apply_xstep()

    def _install_cursor_items(self):
        """(Re)pasang crosshair + penanda kursor setelah plot.clear()."""
        try:
            self.plot.addItem(self._cursor_vline, ignoreBounds=True)
            self.plot.addItem(self._cursor_dots, ignoreBounds=True)
            self.right_vb.addItem(self._cursor_dots_r, ignoreBounds=True)
        except Exception:
            pass
        self._cursor_vline.hide()
        self._cursor_dots.setData([])
        self._cursor_dots_r.setData([])
        self._cursor_key = None
        # pin pembanding ikut dipasang ulang (plot.clear() melepasnya); lepas
        # bila berada di luar data yang sekarang ditampilkan
        pin = getattr(self, '_pin_x', None)
        if pin is not None:
            x = self._x
            if x is None or not (float(x[0]) <= pin <= float(x[-1])):
                self._set_pin(None)
            else:
                self._set_pin(pin)

    def _hide_cursor_extras(self):
        self._cursor_key = None
        self._point_box.hide()
        self._cursor_vline.hide()
        self._cursor_dots.setData([])
        self._cursor_dots_r.setData([])
        # paksa cat-ulang penuh agar tidak ada sisa/ghost penanda kursor
        try:
            self.plot.viewport().update()
        except Exception:
            pass

    @staticmethod
    def _place_card(card, plot, scene_pos):
        """Letakkan kartu di kanan-bawah kursor; balik ke kiri/atas bila
        menabrak tepi area grafik."""
        vp = plot.mapFromScene(scene_pos)
        x, y = vp.x() + 16, vp.y() + 16
        vw, vh = plot.viewport().width(), plot.viewport().height()
        if x + card.width() > vw:
            x = vp.x() - card.width() - 16
        if y + card.height() > vh:
            y = vh - card.height() - 2
        card.move(QPoint(int(max(0, x)), int(max(0, y))))

    @staticmethod
    def _delta_html(d, unit):
        """Selisih terhadap pin: kecil & abu-abu, bertanda."""
        sign = '+' if d >= 0 else '\u2212'
        return ('&nbsp;<span style="color:%s;font-size:11px">(Δ %s%s%s)'
                '</span>' % (_thm.tok('muted'), sign,
                             format(abs(d), ',.1f'), unit))

    # ---------------- pin pembanding & navigasi roda ----------------
    def _set_pin(self, xval):
        """Pasang/lepas garis pembanding (pin). Kartu kursor lalu menampilkan
        Δt dan Δ nilai tiap seri relatif terhadap titik pin."""
        line = getattr(self, '_pin_line', None)
        if xval is None:
            self._pin_x = None
            if line is not None:
                line.hide()
        else:
            self._pin_x = float(xval)
            if line is None:
                line = pg.InfiniteLine(
                    angle=90, movable=False,
                    pen=pg.mkPen(_thm.tok('acc_fg'), width=1,
                                 style=Qt.DashLine),
                    label='PIN', labelOpts=dict(
                        position=0.97, color=_thm.tok('acc_fg'),
                        fill=None, movable=False))
                line.setZValue(55)
                self._pin_line = line
            line.setPen(pg.mkPen(_thm.tok('acc_fg'), width=1,
                                 style=Qt.DashLine))
            if line.scene() is None:
                self.plot.addItem(line, ignoreBounds=True)
            line.setPos(self._pin_x)
            line.show()
        self._cursor_key = None           # paksa kartu dihitung ulang
        self._update_pin_hint()

    def _update_pin_hint(self):
        lbl = getattr(self, 'lbl_hint', None)
        if lbl is None:
            return
        if getattr(self, '_pin_x', None) is not None:
            lbl.setText(tr('Pin:') + ' ' + _fmt_ts(self._pin_x)
                        + '  ·  ' + tr('Esc / klik-ganda: lepas'))
        else:
            lbl.setText(tr('Ctrl+scroll: zoom · Shift+scroll: geser · '
                           'klik: pin pembanding · klik-ganda: reset'))

    def _on_plot_click(self, ev):
        """Klik-kiri di area data = pasang pin di langkah data terdekat
        (klik di dekat pin yang ada = lepas). Klik-ganda = lepas pin + reset
        tampilan. Seret-kiri tetap zoom kotak (bukan 'klik')."""
        try:
            if ev.button() != Qt.LeftButton or self._x is None:
                return
            vb = self.plot.getPlotItem().vb
            sp = ev.scenePos()
            if not vb.sceneBoundingRect().contains(sp):
                return
            if ev.double():
                self._set_pin(None)
                self._reset_view(self.plot, sync_region=True)
                ev.accept()
                return
            t = vb.mapSceneToView(sp).x()
            i = int(np.clip(np.searchsorted(self._x, t, side='right') - 1,
                            0, len(self._x) - 1))
            xi = float(self._x[i])
            cur = getattr(self, '_pin_x', None)
            self._set_pin(None if (cur is not None and abs(cur - xi) < 1e-6)
                          else xi)
            self._on_mouse_move((sp,))
            ev.accept()
        except Exception:
            pass

    def _wheel_nav(self, plot, ev, bounds):
        """Ctrl+roda = zoom sumbu-X di posisi kursor; Shift+roda (atau
        geser horizontal touchpad) = geser jendela. Roda biasa tetap
        diabaikan agar grafik tidak ter-zoom tak sengaja saat menggulir."""
        mods = ev.modifiers()
        dy, dx = ev.angleDelta().y(), ev.angleDelta().x()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        if not (ctrl or shift or dx):
            # roda biasa: DIBLOK (tanpa zoom tak sengaja) — no_wheel_zoom pada
            # ViewBox tidak selalu efektif karena event diteruskan ke item lain
            return True
        if bounds is None:
            return True
        x0, x1, step = bounds
        vb = plot.getPlotItem().vb
        lo, hi = vb.viewRange()[0]
        span = max(hi - lo, step)
        if ctrl:
            steps = dy / 120.0
            f = 0.8 ** steps
            try:
                cx = vb.mapSceneToView(
                    plot.mapToScene(ev.position().toPoint())).x()
            except Exception:
                cx = 0.5 * (lo + hi)
            cx = min(max(cx, lo), hi)
            new_span = min(max(span * f, 4 * step), x1 - x0)
            lo = cx - (cx - lo) * new_span / span
            hi = lo + new_span
        else:
            d = (dy if shift else -dx) / 120.0
            lo -= d * 0.2 * span
            hi = lo + span
        if lo < x0:
            lo, hi = x0, x0 + (hi - lo)
        if hi > x1:
            lo, hi = max(x0, x1 - (hi - lo)), x1
        vb.setXRange(lo, hi, padding=0)
        return True

    def _cursor_card_html(self, ts_text, rows):
        """HTML kartu titik-data: header waktu + tiap seri (titik warna+nilai)."""
        fg = _thm.CURRENT_FG
        muted = _thm.tok('muted')
        body = ('<div style="font-size:12px;color:%s;margin-bottom:3px">%s</div>'
                % (muted, ts_text))
        for color, label, disp in rows:
            body += (
                '<div style="margin:1px 0">'
                '<span style="color:%s;font-size:14px">&#9679;</span>'
                '&nbsp;<span style="color:%s">%s:</span>'
                '&nbsp;<b style="color:%s">%s</b></div>'
                % (color, fg, label, fg, disp))
        return body

    def _on_mouse_move(self, evt):
        if self._x is None or self._s_last is None:
            return
        pos = evt[0]
        vb = self.plot.getPlotItem().vb
        # Hanya tampil bila kursor di dalam AREA PLOT (ViewBox), bukan di sumbu
        # atau tepi widget — kartu hilang saat kursor keluar area grafik.
        if not vb.sceneBoundingRect().contains(pos):
            self._hide_cursor_extras()
            return
        t = vb.mapSceneToView(pos).x()
        # Jam yang intervalnya [x[i], x[i+1]) memuat kursor; side='right'-1
        # agar tidak off-by-one (selaras dengan blok warna case).
        i = int(np.clip(np.searchsorted(self._x, t, side='right') - 1,
                        0, len(self._x) - 1))
        s = self._s_last
        n = len(s['load'])
        xi = float(self._x[i])
        active = tuple(k for k, _l, _c, _r in TS_SERIES
                       if k in s and self.checks[k].isChecked())
        pin_x = getattr(self, '_pin_x', None)
        # Kursor masih di langkah data yang SAMA -> cukup geser kartu (tanpa
        # hitung ulang, tanpa gambar ulang penanda). Membuat gerakan mulus.
        key_now = (i, active, pin_x, _thm.CURRENT_DARK)
        if key_now == getattr(self, '_cursor_key', None) \
                and self._point_box.isVisible():
            self._place_card(self._point_box, self.plot, pos)
            return
        self._cursor_key = key_now
        pin_i = None
        if pin_x is not None:
            pin_i = int(np.clip(np.searchsorted(self._x, pin_x, side='right')
                                - 1, 0, len(self._x) - 1))

        # --- kumpulkan seri aktif: baris kartu + penanda lingkaran ---
        rows = []
        left_spots, right_spots = [], []
        hollow = pg.mkBrush(_thm.CURRENT_BG)     # isi lingkaran = warna latar
        for key, label, color, right in TS_SERIES:
            if key not in active:
                continue
            arr = s[key]
            v = float(arr[i])
            if key == 'soc':
                disp = '%s%%' % format(v * 100.0, ',.1f')
                if pin_i is not None:
                    disp += self._delta_html((v - float(arr[pin_i])) * 100.0,
                                             ' pp')
                right_spots.append({'pos': (xi, v * 100.0), 'size': 11,
                                    'symbol': 'o', 'brush': hollow,
                                    'pen': pg.mkPen(color, width=2)})
            else:
                disp = '%s kW' % format(v, ',.1f')
                if pin_i is not None:
                    disp += self._delta_html(v - float(arr[pin_i]), '')
                left_spots.append({'pos': (xi, v), 'size': 11, 'symbol': 'o',
                                   'brush': hollow,
                                   'pen': pg.mkPen(color, width=2)})
            rows.append((color, tr(label), disp))

        # crosshair + penanda lingkaran di posisi kursor
        self._cursor_vline.setPos(xi)
        self._cursor_vline.show()
        self._cursor_dots.setData(left_spots)
        self._cursor_dots_r.setData(right_spots)
        # Cat-ulang penuh viewport: crosshair (InfiniteRentang) + penanda pada
        # sumbu-kanan (ViewBox terpisah) kadang meninggalkan sisa/ghost saat
        # kursor digeser cepat; update penuh menghapusnya.
        try:
            self.plot.viewport().update()
        except Exception:
            pass

        # --- kartu melayang (gaya gambar acuan), menyesuaikan tema ---
        if rows:
            _style_card_once(self._point_box)
            head = _fmt_ts(xi)
            if pin_i is not None:
                head += ('&nbsp;&nbsp;<span style="color:%s">Δt %s</span>'
                         % (_thm.tok('acc_fg'),
                            _fmt_dt(xi - float(self._x[pin_i]))))
            self._point_box.setText(self._cursor_card_html(head, rows))
            self._point_box.adjustSize()
            self._place_card(self._point_box, self.plot, pos)
            self._point_box.raise_()
            self._point_box.show()
        else:
            self._point_box.hide()

        # --- teks Case Analysis -> baris ATAS (menggantikan readout lama) ---
        c = int(self._cases[i]) if (self._case_mode and self._cases is not None
                                    and 0 <= i < len(self._cases)) else 0
        if c > 0 and self._case_enabled.get(c, True):
            self.lbl_cursor.setText('\U0001F3AF  ' + case_text(c))
        elif self._case_mode:
            self.lbl_cursor.setText('')

    def _apply_window(self):
        """Terapkan lebar jendela (jam) dari spinbox ke tampilan."""
        if self._x is None or len(self._x) < 2:
            return
        self._ts_prezoom = None          # perubahan Window disengaja → baseline baru
        x = self._x
        lo, _hi = self.region.getRegion()
        lo = min(max(float(lo), float(x[0])), float(x[-1]))
        hi = lo + self.win_hours.value() * 3600.0
        if hi > x[-1]:                    # geser mundur bila mentok kanan
            hi = float(x[-1])
            lo = max(float(x[0]), hi - self.win_hours.value() * 3600.0)
        self.region.setRegion([lo, hi])
        self.plot.setXRange(lo, hi, padding=0)
        self._sync_adv_window(lo, hi)

    # ---------------- durasi simulasi (header) & zoom grafik ----------------
    def _refresh_dur_options(self):
        """Bangun ulang opsi 'Durasi simulasi' sesuai interval aktif (durasi
        maksimum dibatasi window interval). Pertahankan pilihan JAM bila masih
        valid; jika tidak, default = window penuh interval (perilaku lama)."""
        if not hasattr(self, 'cmb_dur'):
            return
        lab = str(self.state.cfg.get('sim_interval', '1 hour'))
        opts = ivals.allowed_durations(lab)          # [(label_id, jam)]
        prev_h = None
        if getattr(self, '_dur_labels_h', None):
            i = self.cmb_dur.currentIndex()
            if 0 <= i < len(self._dur_labels_h):
                prev_h = self._dur_labels_h[i][1]
        self._dur_syncing = True
        self.cmb_dur.blockSignals(True)
        self.cmb_dur.clear()
        self.cmb_dur.addItems([tr(l) for l, _h in opts])
        self._dur_labels_h = opts
        hours = [h for _l, h in opts]
        tgt = prev_h if prev_h in hours else ivals.interval_window_h(lab)
        idx = next((k for k, (_l, h) in enumerate(opts) if h == tgt),
                   len(opts) - 1)
        self.cmb_dur.setCurrentIndex(max(0, idx))
        self.cmb_dur.blockSignals(False)
        self._dur_syncing = False

    def _selected_duration_h(self) -> int:
        """Durasi simulasi terpilih (JAM), atau window penuh interval bila tak
        ada pilihan valid."""
        lab = str(self.state.cfg.get('sim_interval', '1 hour'))
        i = self.cmb_dur.currentIndex() if hasattr(self, 'cmb_dur') else -1
        if getattr(self, '_dur_labels_h', None) and 0 <= i < len(self._dur_labels_h):
            return int(self._dur_labels_h[i][1])
        return int(ivals.interval_window_h(lab))

    def _persist_sim_window(self):
        """Simpan pilihan Start (bulan/tanggal) & Durasi ke cfg agar JENDELA
        SIMULASI menjadi setelan proyek bersama (dibaca Multi-Year/Optimization
        lewat ivals.resolve_sim_window). Ditulis langsung ke cfg + disimpan
        (TANPA memancarkan config_changed agar tak memicu rebuild opsi durasi
        yang bisa mengubah pilihan pengguna)."""
        if not (hasattr(self, 'cmb_month') and hasattr(self, 'spin_day')):
            return
        self.state.cfg['sim_start_month'] = int(self.cmb_month.currentIndex() + 1)
        self.state.cfg['sim_start_day'] = int(self.spin_day.value())
        self.state.cfg['sim_duration_h'] = int(self._selected_duration_h())
        try:
            self.state.save_config()
            self.state.db.save_project(self.state.cfg)
        except Exception:
            pass

    def _restore_sim_window(self):
        """Pulihkan kontrol Start/Durasi dari cfg (setelan proyek bersama)."""
        if not (hasattr(self, 'cmb_month') and hasattr(self, 'spin_day')):
            return
        m = int(self.state.cfg.get('sim_start_month', 1) or 1)
        d = int(self.state.cfg.get('sim_start_day', 1) or 1)
        self.cmb_month.blockSignals(True)
        self.cmb_month.setCurrentIndex(int(min(12, max(1, m)) - 1))
        self.cmb_month.blockSignals(False)
        self.spin_day.blockSignals(True)
        self.spin_day.setValue(int(min(31, max(1, d))))
        self.spin_day.blockSignals(False)
        dur = int(self.state.cfg.get('sim_duration_h', 0) or 0)
        if dur > 0 and getattr(self, '_dur_labels_h', None):
            idx = next((k for k, (_l, h) in enumerate(self._dur_labels_h)
                        if h == dur), None)
            if idx is not None:
                self.cmb_dur.blockSignals(True)
                self.cmb_dur.setCurrentIndex(idx)
                self.cmb_dur.blockSignals(False)

    def _sync_adv_window(self, lo=None, hi=None):
        """Samakan rentang-X tab Advanced (EMS) dengan jendela Time Series."""
        if not hasattr(self, 'adv_power'):
            return
        if lo is None or hi is None:
            try:
                lo, hi = self.region.getRegion()
            except Exception:
                return
        try:
            self.adv_power.setXRange(float(lo), float(hi), padding=0)
        except Exception:
            pass

    def _setup_box_zoom(self, plot, reset_fn):
        """Zoom-in = seret-KIRI membentuk kotak (RectMode). Reset = KLIK-KANAN →
        'Reset view' (kembali ke jendela 'Tampil (jam)' sebelum di-zoom)."""
        try:
            vb = plot.getPlotItem().vb
        except Exception:
            vb = plot.getViewBox()
        try:
            vb.setMouseMode(pg.ViewBox.RectMode)      # seret-kiri = kotak zoom
        except Exception:
            pass
        try:
            from PySide6.QtGui import QAction
            act = QAction(tr('Reset view'), plot)
            act.triggered.connect(lambda *_: reset_fn())
            menu = vb.menu
            acts = menu.actions()
            if acts:
                menu.insertAction(acts[0], act)
                menu.insertSeparator(acts[0])
            else:
                menu.addAction(act)
        except Exception:
            pass

    def _reset_view(self, plot, sync_region=False):
        """Kembalikan tampilan ke kondisi SEBELUM drag-zoom kotak.

        Time Series: pulihkan rentang-X + Window(jam) PERSIS spt tepat sebelum
        di-zoom (snapshot _ts_prezoom), termasuk Y dual-axis default. Bila tak
        ada snapshot (mis. belum pernah zoom), jatuh ke jendela 'Tampil (jam)'
        dari awal data (perilaku lama)."""
        x = getattr(self, '_x', None)
        if x is None or len(x) < 2:
            return
        if sync_region and plot is getattr(self, 'plot', None):
            pz = getattr(self, '_ts_prezoom', None)
            if pz is not None:
                lo, hi, wh = pz
                self._ts_prezoom = None
                try:                     # Window(jam) balik ke nilai pra-zoom
                    self.win_hours.blockSignals(True)
                    self.win_hours.setValue(int(max(self.win_hours.minimum(),
                                                    min(int(wh),
                                                        self.win_hours.maximum()))))
                    self.win_hours.blockSignals(False)
                except Exception:
                    pass
                self._restore_range = (float(lo), float(hi))
                self._force_window = False
                self._refresh_ts()       # pulihkan rentang persis + Y default
                self._sync_adv_window()
                return
            # Tak ada snapshot: jendela default 'Tampil (jam)' dari awal data.
            self._force_window = True
            self._refresh_ts()
            self._sync_adv_window()
            return
        lo = float(x[0])
        hi = min(float(x[-1]), lo + max(1, self.win_hours.value()) * 3600.0)
        try:
            vb = plot.getPlotItem().vb
            vb.setXRange(lo, hi, padding=0)
            vb.enableAutoRange(axis=vb.YAxis, enable=True)   # refit Y ke jendela
            vb.enableAutoRange(axis=vb.YAxis, enable=False)  # kunci lagi
        except Exception:
            pass

    # Deret grafik daya Advanced (EMS) dibangun dinamis di _refresh_adv menurut
    # mode shaping aktif (Smoothing/Firming): PV only vs smoothed/firmed &
    # DEG/Grid only vs smoothed/firmed, + BESS Balance & SOC.
    # Deret ramp (subplot bawah, hanya saat Smoothing) dibangun dinamis di
    # _refresh_adv: PV only / Plant Inj. (=PV+BESS) & DEG/Grid wPV / wPVBESS + Allowed.

    def _build_adv_tab(self) -> QWidget:
        """Tab EMS multi-mode: aliran daya + laju ramp PV (verifikasi PV
        Smoothing) — sumbu-X waktu & kartu kursor seperti tab Time Series."""
        w = QWidget(); w.setObjectName('DashTabCard')
        v = QVBoxLayout(w); v.setContentsMargins(8, 6, 8, 6)
        info = QLabel(tr('Grafik EMS multi-mode (mode Advanced): PV & suplai '
                         'DEG/Grid, sebelum vs sesudah shaping BESS (Smoothing / '
                         'Firming), + SOC. Zoom: seret-kiri kotak; klik-kanan → '
                         'Reset view. Jalankan Run dengan mode Advanced.'))
        info.setObjectName('PageSub'); info.setWordWrap(True); v.addWidget(info)
        self.adv_power = pg.PlotWidget(
            axisItems={'bottom': pg.DateAxisItem(utcOffset=0)})
        no_wheel_zoom(self.adv_power); self.adv_power.setBackground(None)
        _lighten_plot(self.adv_power)
        self.adv_power.setLabel('left', tr('Power'), units='kW')
        self._adv_legend = self.adv_power.addLegend(offset=(10, 10))
        self.adv_power.showGrid(x=True, y=True, alpha=0.15)
        # Y manual (agar zoom kotak menempel); reset via klik-kanan.
        self.adv_power.getPlotItem().vb.enableAutoRange(x=False, y=False)
        # sumbu kanan untuk SOC (%) — sama pola dgn Time Series
        self.adv_right_vb = pg.ViewBox()
        no_wheel_zoom(self.adv_right_vb)
        _api = self.adv_power.getPlotItem()
        _api.showAxis('right')
        _api.scene().addItem(self.adv_right_vb)
        _api.getAxis('right').linkToView(self.adv_right_vb)
        self.adv_right_vb.setXLink(_api.vb)
        _api.getAxis('right').setLabel('SOC (%)')
        self.adv_right_vb.setYRange(0, 100, padding=0)
        _api.vb.sigResized.connect(self._sync_adv_right_vb)
        # Zoom kotak (seret-kiri) + klik-kanan Reset view
        self._setup_box_zoom(self.adv_power, lambda: self._reset_view(self.adv_power))
        self.adv_ramp = pg.PlotWidget(
            axisItems={'bottom': pg.DateAxisItem(utcOffset=0)})
        no_wheel_zoom(self.adv_ramp); self.adv_ramp.setBackground(None)
        _lighten_plot(self.adv_ramp)
        self.adv_ramp.setLabel('left', tr('DEG/Grid Ramp'), units='kW')
        self.adv_ramp.addLegend(offset=(10, 10))
        self.adv_ramp.showGrid(x=True, y=True, alpha=0.15)
        self.adv_ramp.setXLink(self.adv_power)
        v.addWidget(self.adv_power, 2); v.addWidget(self.adv_ramp, 1)
        # --- kartu melayang + crosshair (sama seperti Time Series) ---
        from PySide6.QtWidgets import QLabel as _QL
        self._adv_card = _QL(self.adv_power)
        self._adv_card.setObjectName('CursorCard')
        self._adv_card.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._adv_card.setTextFormat(Qt.RichText); self._adv_card.hide()
        _cpen = pg.mkPen((150, 150, 150, 170), width=1)
        self._adv_vline = pg.InfiniteLine(angle=90, movable=False, pen=_cpen)
        self._adv_vline.setZValue(50); self._adv_vline.hide()
        self._adv_vline2 = pg.InfiniteLine(angle=90, movable=False, pen=_cpen)
        self._adv_vline2.setZValue(50); self._adv_vline2.hide()
        self._adv_dots = pg.ScatterPlotItem(size=11); self._adv_dots.setZValue(60)
        self._adv_dots2 = pg.ScatterPlotItem(size=11); self._adv_dots2.setZValue(60)
        self._adv_saved_view = None          # (xrange,yrange,socrange) utk pertahankan zoom
        self._adv_force_window = False        # run baru → fit ke jendela (bukan zoom lama)
        self._adv_proxy = pg.SignalProxy(self.adv_power.scene().sigMouseMoved,
                                         rateLimit=60, slot=self._on_adv_mouse)
        self.adv_power.viewport().installEventFilter(self)
        self.adv_ramp.viewport().installEventFilter(self)   # roda: zoom/geser
        self._adv_x = None; self._adv_series = None; self._adv_meta = []
        return w

    def _build_adv_day_picker(self) -> QWidget:
        """Corner widget tab (pojok kanan-atas baris tab): pemilih HARI untuk
        grafik Advanced (EMS) bila jendela yang disimulasikan > 1 hari (24
        jam) — memungkinkan pengguna melompat ke hari tertentu tanpa harus
        menggeser/zoom manual. Hanya tampak saat tab Advanced (EMS) aktif
        (lihat _update_adv_day_visibility)."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 8, 0); row.setSpacing(6)
        row.addWidget(QLabel(tr('Hari:')))
        self.adv_day_combo = QComboBox()
        self.adv_day_combo.setMinimumWidth(90)
        self.adv_day_combo.setToolTip(tr(
            'Pilih hari yang ditampilkan pada grafik Advanced (EMS) -- muncul '
            'hanya bila jendela yang disimulasikan lebih dari 1 hari (24 jam).'))
        self.adv_day_combo.currentIndexChanged.connect(self._on_adv_day_changed)
        row.addWidget(self.adv_day_combo)
        self._adv_day_box = box
        self._adv_total_days = 1
        box.setVisible(False)      # disembunyikan sampai ada hasil > 1 hari
        return box

    def _update_adv_day_visibility(self, *_a):
        """Tampilkan pemilih hari HANYA saat tab Advanced (EMS) aktif DAN
        jendela hasil terakhir > 1 hari; sembunyikan di tab lain / jendela
        1 hari (mis. Durasi '1 hari') agar tak memakan ruang tanpa guna."""
        box = getattr(self, '_adv_day_box', None)
        if box is None:
            return
        show = (self.tabs.currentIndex() == getattr(self, '_idx_adv', -1)
                and getattr(self, '_adv_total_days', 1) > 1)
        box.setVisible(show)

    def _refresh_adv_day_options(self, res=None):
        """Bangun ulang daftar 'Hari 1..N' menurut lebar jendela hasil
        terakhir (dari res['window_h'], fallback ke rentang self._x bila tak
        ada) — dipanggil tiap kali ada hasil baru (lihat _apply_result) /
        hasil dibersihkan (_on_cleared)."""
        win_h = 0
        r = res if res is not None else self.state.last_result
        if isinstance(r, dict):
            win_h = int(r.get('window_h') or 0)
        if win_h <= 0:
            x = getattr(self, '_x', None)
            if x is not None and len(x) > 1:
                win_h = int(round((float(x[-1]) - float(x[0])) / 3600.0)) + 1
        n_days = max(1, int(np.ceil(win_h / 24.0))) if win_h > 0 else 1
        self._adv_total_days = n_days
        combo = getattr(self, 'adv_day_combo', None)
        if combo is not None:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([tr('Hari {n}').format(n=i + 1)
                           for i in range(n_days)])
            if n_days:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._update_adv_day_visibility()

    def _on_adv_day_changed(self, idx: int):
        """Loncat ke hari ke-(idx+1) pada grafik Advanced (EMS): set rentang-X
        ke [awal jendela + idx*24 jam, .. +24 jam) lalu refit Y (trik
        enable/disable autoRange sekali, sama seperti saat run baru — lihat
        _refresh_adv)."""
        if idx < 0 or not hasattr(self, 'adv_power'):
            return
        x = getattr(self, '_adv_x', None)
        if x is None or len(x) < 2:
            return
        x0 = float(x[0]); x_end = float(x[-1])
        lo = x0 + idx * 86400.0
        hi = min(x_end, lo + 86400.0)
        if hi <= lo:            # hari di luar data (mis. sisa < 1 hari) → abaikan
            return
        try:
            vb = self.adv_power.getPlotItem().vb
            vb.setXRange(lo, hi, padding=0)
            vb.enableAutoRange(axis=vb.YAxis, enable=True)
            vb.enableAutoRange(axis=vb.YAxis, enable=False)
        except Exception:
            pass

    def _refresh_adv(self):
        if not hasattr(self, 'adv_power'):
            return
        # Tangkap SEBELUM clear: seri yg disembunyikan (legend) & rentang zoom,
        # agar dipertahankan saat run baru (req: pertahankan hide + zoom-in).
        _prev_hidden = set(); _prev_view = None
        _had_prev = bool(getattr(self, '_adv_meta', None))
        if _had_prev:
            for _m in self._adv_meta:
                _it = _m[4] if len(_m) > 4 else None
                try:
                    if _it is not None and not _it.isVisible():
                        _prev_hidden.add(_m[0])
                except Exception:
                    pass
            try:
                _vb0 = self.adv_power.getPlotItem().vb
                _sr = (list(self.adv_right_vb.viewRange()[1])
                       if hasattr(self, 'adv_right_vb') else None)
                _prev_view = (list(_vb0.viewRange()[0]),
                              list(_vb0.viewRange()[1]), _sr)
            except Exception:
                _prev_view = None
        self.adv_power.clear(); self.adv_ramp.clear()
        if hasattr(self, 'adv_right_vb'):
            self.adv_right_vb.clear()
        try:
            self._adv_legend.clear()
        except Exception:
            pass
        s = getattr(self, '_s_last', None); x = getattr(self, '_x', None)
        self._adv_x = x; self._adv_series = s; self._adv_meta = []
        if s is None or x is None or len(x) < 2:
            return
        nx = len(x)
        C = SERIES_COLORS

        def _col(c):
            return C.get(c, c)

        def _y(key):
            return np.asarray(s[key], float).reshape(nx, -1)[:, 0]

        r = self.state.last_result or {}
        smoothing = bool(r.get('adv_pv_smooth'))
        firming = bool(r.get('adv_firming'))
        shaped = smoothing or firming
        load_y = _y('load') if 'load' in s else np.zeros(nx)
        pvb = _y('pv') if 'pv' in s else np.zeros(nx)   # PV only ≡ PV EnetAC
        grid_y = _y('grid') if 'grid' in s else np.zeros(nx)
        deg_y = _y('deg') if 'deg' in s else np.zeros(nx)
        dg_wpv = np.maximum(0.0, load_y - pvb)       # DEG/Grid dgn PV saja (no BESS)
        dg_wpvbess = grid_y + deg_y                  # DEG/Grid dgn PV+BESS (aktual)
        # Plant Inj = injeksi PV+BESS. Pakai deret terekam (memperhitungkan curtail
        # saat baterai penuh pada shaping); fallback ke pv+dhg−chg bila tak tersedia.
        if 'plant_inj' in s:
            plant_inj = _y('plant_inj')
        else:
            plant_inj = (_y('pv') if 'pv' in s else np.zeros(nx)) \
                + (_y('dhg') if 'dhg' in s else np.zeros(nx)) \
                - (_y('chg') if 'chg' in s else np.zeros(nx))
        # Deret daya (sumbu kiri). "PV only" (mentah) vs "Plant Inj." (=PV+BESS
        # ter-shaping). Plant Inj. == PV wBESS untuk shaping, jadi tak digandakan.
        lines = [(load_y, 'Load', _col('load')),
                 (pvb, 'PV only', '#FCD34D')]
        lines.append((dg_wpv, 'DEG/Grid wPV', '#FCA5A5'))
        if shaped:
            lines.append((dg_wpvbess, 'DEG/Grid wPVBESS', '#EF4444'))
        lines.append((plant_inj, 'Plant Inj.', '#38BDF8'))   # = PV+BESS (PV wBESS)
        # MA Setpoint (Smoothing): target yg HARUS dicapai Plant Inj TANPA
        # kurtailmen/batasan real — bisa beda dari 'Plant Inj.' bila baterai/
        # kurtailmen membatasi. Hanya utk Smoothing (bukan Firming — target
        # Firming konstan, sudah tersirat dari nilai parameter).
        if smoothing and 'ma_setpoint' in s:
            lines.append((_y('ma_setpoint'), 'MA Setpoint', '#A78BFA'))
        lines.append((_y('bess_net') if 'bess_net' in s else np.zeros(nx),
                      'BESS Balance', '#14B8A6'))
        for y, label, color in lines:
            _it = self.adv_power.plot(x, y, pen=pg.mkPen(color, width=CURVE_W),
                                      name=tr(label))
            self._adv_meta.append((label, y, color, 'power', _it))
        # SOC (%) pada sumbu kanan + entri legend (grafik atas)
        if 'soc' in s:
            socy = _y('soc') * 100.0
            _soc_item = pg.PlotDataItem(x, socy,
                                        pen=pg.mkPen(_col('soc'), width=CURVE_W))
            self.adv_right_vb.addItem(_soc_item)
            _lighten_curve(_soc_item)        # setelah masuk ViewBox
            self.adv_right_vb.setYRange(0, 100, padding=0)
            self._sync_adv_right_vb()
            try:
                self._adv_legend.addItem(_soc_item, tr('SOC'))
            except Exception:
                pass
            self._adv_meta.append(('SOC', socy, _col('soc'), 'socr', _soc_item))
        # Subplot ramp tampil utk Smoothing MAUPUN Firming (deret sama). "Plant Inj
        # ramp" == ramp PV wBESS (identik). Allowed = ±batas ramp PV (Smoothing).
        self.adv_ramp.setVisible(shaped)
        if shaped:
            ramp_series = [
                ('pv_ramp_act', 'PV only ramp actual', '#FCD34D'),
                ('dg_ramp_act', 'DEG/Grid wPV Ramp', '#FCA5A5'),
                ('dg_ramp_smooth', 'DEG/Grid wPVBESS Ramp', '#EF4444'),
                ('plant_inj_ramp', 'Plant Inj ramp', '#38BDF8')]
            for key, label, cc in ramp_series:
                if key in s:
                    yy = _y(key)
                    _it = self.adv_ramp.plot(x, yy, pen=pg.mkPen(cc, width=CURVE_W),
                                             name=tr(label))
                    self._adv_meta.append((label, yy, cc, 'ramp', _it))
            up = float(r.get('ramp_up_step') or 0.0)
            dn = float(r.get('ramp_dn_step') or 0.0)
            allow_label = 'PV Ramp Allowed'   # setpoint = output PV ter-smoothed
            _al = '#9CA3AF'
            _first = True
            for lim in ((up if up > 0 else None), (-dn if dn > 0 else None)):
                if lim is None:
                    continue
                yy = np.full(nx, lim)
                _it = self.adv_ramp.plot(x, yy, pen=pg.mkPen(_al, width=1,
                                         style=Qt.DashLine),
                                         name=tr(allow_label) if _first else None)
                if _first:
                    self._adv_meta.append((allow_label, yy, _al, 'ramp', _it))
                _first = False
        style_plot_legend(self.adv_power); style_plot_legend(self.adv_ramp)
        try:                                 # pasang ulang crosshair+penanda stlh clear
            self.adv_power.addItem(self._adv_vline, ignoreBounds=True)
            self.adv_power.addItem(self._adv_dots, ignoreBounds=True)
            self.adv_ramp.addItem(self._adv_vline2, ignoreBounds=True)
            self.adv_ramp.addItem(self._adv_dots2, ignoreBounds=True)
        except Exception:
            pass
        self._adv_vline.hide(); self._adv_vline2.hide()
        self._adv_dots.setData([]); self._adv_dots2.setData([]); self._adv_card.hide()
        # Terapkan kembali seri yg DISEMBUNYIKAN sebelumnya (by label).
        if _prev_hidden:
            for _m in self._adv_meta:
                _it = _m[4] if len(_m) > 4 else None
                if _it is not None and _m[0] in _prev_hidden:
                    try:
                        _it.setVisible(False)
                    except Exception:
                        pass
        try:
            vb = self.adv_power.getPlotItem().vb
            # Run/rebuild baru (_adv_force_window) → SELALU fit ke jendela simulasi
            # baru + refit Y, karena basis waktu (epoch) bergeser sesuai
            # window_start_h; mempertahankan zoom lama akan membuat grafik kosong.
            # Hanya redraw non-run (tanpa flag) yang mempertahankan zoom pengguna.
            _force_win = getattr(self, '_adv_force_window', False)
            self._adv_force_window = False
            if _had_prev and _prev_view is not None and not _force_win:
                _xr, _yr, _sr = _prev_view          # redraw biasa → pertahankan zoom
                vb.setXRange(_xr[0], _xr[1], padding=0)
                vb.setYRange(_yr[0], _yr[1], padding=0)
                if _sr is not None and hasattr(self, 'adv_right_vb'):
                    self.adv_right_vb.setYRange(_sr[0], _sr[1], padding=0)
            else:                                   # run baru / pertama → jendela + refit Y
                lo, hi = self.region.getRegion()
                vb.setXRange(float(lo), float(hi), padding=0)
                vb.enableAutoRange(axis=vb.YAxis, enable=True)
                vb.enableAutoRange(axis=vb.YAxis, enable=False)
        except Exception:
            pass

    def _hide_adv_cursor(self):
        self._adv_cursor_key = None
        self._adv_card.hide(); self._adv_vline.hide(); self._adv_vline2.hide()
        self._adv_dots.setData([]); self._adv_dots2.setData([])
        try:
            self.adv_power.viewport().update()
            self.adv_ramp.viewport().update()
        except Exception:
            pass

    def _on_adv_mouse(self, evt):
        if self._adv_x is None or self._adv_series is None:
            return
        pos = evt[0]; vb = self.adv_power.getPlotItem().vb
        if not vb.sceneBoundingRect().contains(pos):
            self._hide_adv_cursor(); return
        t = vb.mapSceneToView(pos).x()
        x = self._adv_x; nx = len(x)
        i = int(np.clip(np.searchsorted(x, t, side='right') - 1, 0, nx - 1))
        xi = float(x[i])
        vis = tuple(bool(_m[4].isVisible()) if len(_m) > 4 and _m[4] is not None
                    else True for _m in self._adv_meta)
        key_now = (i, vis, _thm.CURRENT_DARK)
        if key_now == getattr(self, '_adv_cursor_key', None) \
                and self._adv_card.isVisible():
            self._place_card(self._adv_card, self.adv_power, pos)
            return
        self._adv_cursor_key = key_now
        rows = []; spots = []; spots2 = []; hollow = pg.mkBrush(_thm.CURRENT_BG)
        for _m in self._adv_meta:
            label, yarr, color, which = _m[0], _m[1], _m[2], _m[3]
            item = _m[4] if len(_m) > 4 else None
            if item is not None and not item.isVisible():   # seri di-hide → tak ada titik/baris
                continue
            v = float(np.asarray(yarr, float).reshape(-1)[i])
            if which == 'socr':                    # SOC pada sumbu kanan (%)
                rows.append((color, tr(label), '%s %%' % format(v, ',.1f')))
                continue
            rows.append((color, tr(label), '%s kW' % format(v, ',.1f')))
            _spot = {'pos': (xi, v), 'size': 11, 'symbol': 'o',
                     'brush': hollow, 'pen': pg.mkPen(color, width=2)}
            if which == 'power':
                spots.append(_spot)             # penanda grafik ATAS
            elif which == 'ramp':
                spots2.append(_spot)            # penanda grafik BAWAH (ramp)
        self._adv_vline.setPos(xi); self._adv_vline.show()
        self._adv_vline2.setPos(xi); self._adv_vline2.show()
        self._adv_dots.setData(spots)
        self._adv_dots2.setData(spots2)
        try:
            self.adv_power.viewport().update()
        except Exception:
            pass
        if rows:
            _style_card_once(self._adv_card)
            self._adv_card.setText(self._cursor_card_html(_fmt_ts(xi), rows))
            self._adv_card.adjustSize()
            self._place_card(self._adv_card, self.adv_power, pos)
            self._adv_card.raise_(); self._adv_card.show()
        else:
            self._adv_card.hide()

    def _sync_right_vb(self):
        pi = self.plot.getPlotItem()
        self.right_vb.setGeometry(pi.vb.sceneBoundingRect())

    def _sync_adv_right_vb(self):
        """Samakan geometri viewbox SOC (sumbu kanan) tab Advanced (EMS)."""
        if not hasattr(self, 'adv_right_vb'):
            return
        _api = self.adv_power.getPlotItem()
        self.adv_right_vb.setGeometry(_api.vb.sceneBoundingRect())

    def _build_mix_tab(self) -> QWidget:
        w = QWidget(); w.setObjectName('DashTabCard'); h = QHBoxLayout(w)
        self.pie = PieChart(tr('Energy Mix (porsi beban terlayani)'))
        h.addWidget(self.pie, 1)
        self.mix_cards = {k: KPICard(lbl, '-', 'kWh') for k, lbl in [
            ('pvbs', tr('PV + BESS → Load')), ('grid', tr('Grid → Load')),
            ('deg', tr('Diesel → Load')), ('uns', tr('Unserved'))]}
        h.addWidget(kpi_grid(list(self.mix_cards.values()), cols=1))
        return w

    def _build_month_tab(self) -> QWidget:
        w = QWidget(); w.setObjectName('DashTabCard'); v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('Metode:')))
        self.month_combo = QComboBox()
        self.month_combo.addItems([tr('Energi (kWh)'), tr('Fuel Diesel (L)'),
                                   tr('Curtailment / Excess (kWh)')])
        self.month_combo.currentIndexChanged.connect(self._refresh_month)
        row.addWidget(self.month_combo); row.addStretch(1)
        v.addLayout(row)
        self.lbl_month = QLabel(''); self.lbl_month.setObjectName('PageSub')
        row.addWidget(self.lbl_month)
        self.month_plot = pg.PlotWidget()
        no_wheel_zoom(self.month_plot)
        self.month_plot.showGrid(y=True, alpha=0.2)
        ax = self.month_plot.getAxis('bottom')
        ax.setTicks([[(i, m) for i, m in enumerate(months())]])
        v.addWidget(self.month_plot, 1)
        self._cur_month = CursorReadout(self.month_plot,
                                        self.lbl_month,
                                        self._month_at)
        return w

    def _month_at(self, x):
        vals = getattr(self, '_month_vals', None)
        if not vals:
            return ''
        i = int(round(x))
        if i < 0 or i >= len(vals):
            return ''
        return f'{months()[i]}  —  {vals[i]:,.1f} {self._month_unit}'

    def _build_heat_tab(self) -> QWidget:
        w = QWidget(); w.setObjectName('DashTabCard'); v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('Variabel:')))
        self.heat_combo = QComboBox()
        self.heat_combo.addItems(['SOC (%)', tr('Diesel (kW)'), tr('PV Excess (kW)')])
        self.heat_combo.currentIndexChanged.connect(self._refresh_heat)
        row.addWidget(self.heat_combo); row.addStretch(1)
        v.addLayout(row)
        self.lbl_heat = QLabel(''); self.lbl_heat.setObjectName('PageSub')
        row.addWidget(self.lbl_heat)
        self.heat_plot = pg.PlotWidget()
        no_wheel_zoom(self.heat_plot)
        self.heat_plot.setLabel('left', tr('Jam dalam hari'))
        self.heat_plot.setLabel('bottom', tr('Hari dalam tahun'))
        self.heat_img = pg.ImageItem()
        self.heat_plot.addItem(self.heat_img)
        self.heat_cbar = pg.ColorBarItem(colorMap=pg.colormap.get('viridis'))
        self.heat_cbar.setImageItem(self.heat_img,
                                    insert_in=self.heat_plot.getPlotItem())
        v.addWidget(self.heat_plot, 1)
        self._proxy_heat = pg.SignalProxy(
            self.heat_plot.scene().sigMouseMoved, rateLimit=40,
            slot=self._heat_moved)
        return w

    def _heat_moved(self, evt):
        img = getattr(self, '_heat_data', None)
        if img is None:
            return
        pos = evt[0]
        if not self.heat_plot.sceneBoundingRect().contains(pos):
            return
        pt = self.heat_plot.getViewBox().mapSceneToView(pos)
        d, h = int(pt.x()), int(pt.y())
        if 0 <= d < img.shape[0] and 0 <= h < img.shape[1]:
            self.lbl_heat.setText(
                tr('Hari') + f' {d + 1}, {h:02d}:00  —  '
                f'{img[d, h]:,.2f} {self._heat_unit}')
        else:
            self.lbl_heat.setText('')

    # ---------------- run ----------------
    def _on_profiles(self):
        ok = self.state.data_ready()
        self.btn_run.setEnabled(ok)
        if not ok:
            self.lbl_status.setText(
                tr('Belum ada data — buka halaman Data untuk mengimpor '
                   'Load Profile & PV ENetAC.'))

    def _run(self):
        if not self.state.data_ready():
            QMessageBox.warning(self, tr('Data belum ada'),
                                tr('Import Load Profile & PV ENetAC dahulu.'))
            return
        self.btn_run.setEnabled(False)
        # Status mengikuti interval simulasi yang dipilih (bukan selalu 8760 jam).
        lab = str(self.state.cfg.get('sim_interval', '1 hour'))
        nrow = len(self.state.load) if self.state.load is not None else 0
        # Persist pilihan Start/Durasi ke cfg -> JENDELA SIMULASI menjadi setelan
        # proyek BERSAMA (dibaca Multi-Year & Optimization lewat
        # ivals.resolve_sim_window) sehingga tahun-1 Multi-Year == Dashboard
        # apa pun setelan Start/Durasi (bukan hanya "Setahun penuh").
        self._persist_sim_window()
        # start_h/win_h dihitung dari SATU sumber rumus (resolve_sim_window) yang
        # SAMA persis dipakai Multi-Year -> jaminan konsistensi.
        start_h, win_h = ivals.resolve_sim_window(
            self.state.cfg, nrow, self.state.datetimes)
        nsteps = int(round(win_h * ivals.steps_per_hour(lab)))
        self._status_iv, self._status_n = lab, nsteps
        self.lbl_status.setText(
            tr('Menjalankan simulasi {iv} · {n} langkah … {p}%')
            .format(iv=lab, n=f'{nsteps:,}', p=0))
        self._worker = _SimWorker(self.state, start_h=start_h, window_h=win_h)
        self._worker.finished_ok.connect(self._done)
        self._worker.failed.connect(self._fail)
        self._worker.progress.connect(self._on_progress)
        self._worker.start()

    def _on_progress(self, pct):
        self.lbl_status.setText(
            tr('Menjalankan simulasi {iv} · {n} langkah … {p}%')
            .format(iv=getattr(self, '_status_iv', ''),
                    n=f'{getattr(self, "_status_n", 0):,}', p=int(pct)))

    def _fail(self, msg):
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(tr('Simulasi gagal.'))
        QMessageBox.critical(self, tr('Error'), msg)

    def _done(self, res):
        self.btn_run.setEnabled(True)
        self.state.last_result = res
        self.state.simulation_done.emit(res)
        self._apply_result(res)

    # ---------------- pekerja latar (proses) ----------------
    def is_busy(self) -> bool:
        w = getattr(self, '_worker', None)
        return w is not None and w.isRunning()

    def stop_workers(self):
        """Hentikan simulasi latar saat halaman dibongkar / aplikasi ditutup."""
        w = getattr(self, '_worker', None)
        if w is None or not w.isRunning():
            return
        try:
            w.blockSignals(True)
            w.terminate()
        except Exception:
            pass

    def _clear_results(self):
        """Hapus hasil simulasi & kosongkan seluruh grafik."""
        if not self.state.last_result:
            return
        if QMessageBox.question(
                self, tr('Bersihkan Hasil'),
                tr('Hapus hasil simulasi beserta seluruh grafiknya?')) \
                != QMessageBox.Yes:
            return
        self.state.last_result = None
        self.state.multi_result = None
        self.clear_view()
        self.state.results_cleared.emit('simulation')
        # hasil multi-year ikut dihapus dari state -> kosongkan juga tampilannya
        self.state.results_cleared.emit('multiyear')

    def _on_cleared(self, kind):
        if kind in ('simulation', 'all'):
            self.clear_view()

    def clear_view(self):
        """Kosongkan kartu KPI dan semua grafik pada halaman ini."""
        for c in self.cards.values():
            c.set_value('-')
        for c in getattr(self, 'mix_cards', {}).values():
            c.set_value('-')
        for pl in (self.plot, self.overview, self.month_plot,
                   getattr(self, 'adv_power', None),
                   getattr(self, 'adv_ramp', None)):
            try:
                if pl is not None:
                    pl.clear()
            except Exception:
                pass
        # Sumbu-Y KEDUA (SOC) berada di ViewBox terpisah -> plot.clear() tidak
        # menyentuhnya; bersihkan eksplisit (Time Series & Advanced).
        for vb in (getattr(self, 'right_vb', None),
                   getattr(self, 'adv_right_vb', None)):
            try:
                if vb is not None:
                    vb.clear()
            except Exception:
                pass
        try:
            self._adv_legend.clear()
        except Exception:
            pass
        # kursor/kartu titik-data tidak boleh menampilkan data lama
        self._s_last = None
        self._set_pin(None)
        for nm in ('_point_box', '_adv_card'):
            try:
                getattr(self, nm).hide()
            except Exception:
                pass
        try:
            self.overview.addItem(self.region)   # pemilih rentang tetap ada
        except Exception:
            pass
        try:
            self.pie.set_data([])
        except Exception:
            pass
        try:
            self.heat_img.clear()
        except Exception:
            pass
        self._month_vals, self._heat_data = None, None
        for lb in ('lbl_cursor', 'lbl_month', 'lbl_heat', 'lbl_range'):
            w = getattr(self, lb, None)
            if w is not None:
                w.setText('')
        self.lbl_status.setText(
            tr('Import data lalu jalankan simulasi.')
            if self.state.load is None else
            tr('Data siap — tekan Run Simulation.'))
        self._refresh_adv_day_options()   # hasil dibersihkan → sembunyikan pemilih hari

    def _apply_result(self, res):
        """Isi kartu KPI & grafik dari hasil simulasi (dipakai juga saat
        halaman dibangun ulang, mis. setelah ganti bahasa)."""
        # Run baru: SELALU mulai dari jendela tampil TS_DEFAULT_WINDOW_H (24 jam)
        # agar grafik awal tetap terbaca (bukan seluruh durasi simulasi yang bisa
        # sepadat 8760 jam utk "Setahun penuh") — pengguna tinggal perbesar lewat
        # "Tampil (jam)" bila ingin melihat rentang lebih panjang.
        self._force_window = True
        self._adv_force_window = True   # run/rebuild → grafik Advanced fit ke jendela baru
        self._ts_prezoom = None         # run baru → snapshot zoom lama tak berlaku
        self._pin_x = None              # run baru → pin lama tak berlaku
        try:
            self.win_hours.blockSignals(True)
            self.win_hours.setValue(
                max(1, min(TS_DEFAULT_WINDOW_H, self.win_hours.maximum())))
            self.win_hours.blockSignals(False)
        except Exception:
            pass
        k = res['kpi']
        self.lbl_status.setText(tr('Simulasi selesai. Lihat halaman '
                                   'Results untuk KPI lengkap & laporan.'))
        self.cards['rf'].set_value(f"{k['renewable_fraction']*100:,.1f}")
        self.cards['pv'].set_value(f"{k['annual_pv_generation_kwh']:,.0f}")
        self.cards['fuel'].set_value(f"{k['diesel_fuel_l']:,.0f}")
        self.cards['grid'].set_value(f"{k['grid_import_kwh']:,.0f}")
        self._refresh_all()
        self._refresh_adv_day_options(res)

    # ---------------- refreshers ----------------
    def _series(self):
        r = self.state.last_result
        return None if not r else r.get('series')

    def _refresh_all(self):
        self._refresh_ts(); self._refresh_adv(); self._refresh_mix()
        self._refresh_month(); self._refresh_heat()

    def _refresh_ts(self):
        s = self._series()
        if s is None:
            return
        self.plot.clear(); self.right_vb.clear(); self.overview.clear()
        self.overview.addItem(self.region)
        n_full = len(s['load'])
        # Interval simulasi hasil (spasi sumbu-X) + interval TAMPILAN (agregasi).
        r = self.state.last_result
        sim_lab = (r.get('sim_interval') if isinstance(r, dict) else None) or '1 hour'
        sim_sec = ivals.interval_seconds(sim_lab)
        disp_lab = 'Match simulation'
        if hasattr(self, 'disp_interval') and self.disp_interval.currentIndex() >= 0:
            disp_lab = self._disp_labels[self.disp_interval.currentIndex()]
        g = ivals.display_group_steps(sim_lab, disp_lab)
        # ratakan seluruh seri (mean daya/SOC) ke resolusi tampilan bila g>1
        if g > 1:
            s = {k: ivals.aggregate_series(
                    np.asarray(v, float).reshape(n_full, -1)[:, 0], g, 'mean')
                 for k, v in s.items()}
        else:
            s = {k: np.asarray(v, float).reshape(n_full, -1)[:, 0]
                 for k, v in s.items()}
        n = len(s['load'])
        step_sec = float(sim_sec * g)
        # basis epoch dari tanggal sumber (bila ada) agar tanggal tampil wajar
        base = 0.0
        dts0 = self.state.datetimes
        if dts0 is not None and len(dts0):
            try:
                import pandas as pd
                base = float(pd.Timestamp(dts0[0]).to_datetime64()
                             .astype('datetime64[s]').astype('int64'))
            except Exception:
                base = 0.0
        # Geser basis ke AWAL JENDELA simulasi (start_h jam dari awal data) agar
        # sumbu waktu, kartu kursor, & rentang tampil sesuai periode yang
        # BENAR-BENAR disimulasikan (bukan awal seluruh dataset).
        try:
            base += float((r or {}).get('window_start_h', 0) or 0) * 3600.0
        except Exception:
            pass
        x = base + np.arange(n, dtype=float) * step_sec
        prev_lo, prev_hi = self.region.getRegion()
        # Tangkap lebar jendela yang DIINGINKAN lebih dulu: memasang bounds/region
        # di bawah memicu sinyal rentang-X yang (lewat _update_range_label) bisa
        # menimpa win_hours sebelum dipakai — jadi baca nilainya sekarang.
        want_hours = int(self.win_hours.value())
        self._x = x
        self._s_last = s
        left_vals = []
        for key, label, color, right in TS_SERIES:
            if not self.checks[key].isChecked():
                continue
            y = np.asarray(s[key], float).reshape(n, -1)[:, 0]
            if key == 'soc':
                y = y * 100.0
            item = pg.PlotDataItem(x, y, pen=pg.mkPen(color, width=CURVE_W),
                                   name=tr(label))
            if right:
                self.right_vb.addItem(item)
                _lighten_curve(item)     # SETELAH masuk ViewBox (bug pyqtgraph)
            else:
                self.plot.addItem(item)
                left_vals.append(y)
        # Blok warna case (z-value -1000 -> di belakang) — via helper bersama.
        self._apply_case_overlay()
        # Rentang-Y default agar kurva sumbu kiri (daya) & kanan (SOC) tidak
        # saling menyilang pada tampilan awal.
        self._apply_default_yranges(left_vals)
        style_plot_legend(self.plot)
        self._sync_right_vb()
        load = np.asarray(s['load'], float).reshape(n, -1)[:, 0]
        self.overview.plot(x, load, pen=pg.mkPen(SERIES_COLORS['load'], width=1))
        self.region.setBounds([float(x[0]), float(x[-1])])
        span = float(x[-1] - x[0])
        restore = getattr(self, '_restore_range', None)
        if restore is not None:
            # "Reset view": pulihkan rentang-X PERSIS spt sebelum drag-zoom
            # (dibatasi ke rentang data yang tersedia).
            self._restore_range = None
            lo = max(float(x[0]), min(float(restore[0]), float(x[-1])))
            hi = max(lo + 1.0, min(float(restore[1]), float(x[-1])))
        else:
            zoomed = (prev_hi > prev_lo
                      and prev_lo >= float(x[0]) - 1.0
                      and prev_hi <= float(x[-1]) + 1.0
                      and (prev_hi - prev_lo) < 0.9 * span)
            if getattr(self, '_force_window', False):
                zoomed = False           # run baru → terapkan Window (hours)
                self._force_window = False
            if zoomed:                   # pertahankan jendela zoom user
                lo, hi = float(prev_lo), float(prev_hi)
            else:                        # default: sesuai setting Tampil (jam)
                # jendela dalam JAM data (bukan indeks langkah) -> benar sub-jam
                lo = float(x[0])
                hi = min(float(x[-1]), lo + max(1, want_hours) * 3600.0)
        self.region.setRegion([lo, hi])
        self.plot.setXRange(lo, hi, padding=0)
        self._install_cursor_items()     # pasang ulang crosshair+penanda kursor
        self._update_range_label()

    def _refresh_mix(self):
        r = self.state.last_result
        if not r:
            return
        k = r['kpi']
        load = k['annual_load_kwh']
        pvbs = k['pvbs_supply_ratio'] * load
        grid = k['grid_supply_ratio'] * load
        deg = k['diesel_energy_kwh']
        uns = k['unserved_kwh']
        self.pie.set_data([
            ('PV + BESS', pvbs, SERIES_COLORS['pv']),
            (tr('Grid'), grid, SERIES_COLORS['grid']),
            (tr('Diesel'), deg, SERIES_COLORS['deg']),
            (tr('Unserved'), uns, '#9CA3AF')])
        for key, val in (('pvbs', pvbs), ('grid', grid),
                         ('deg', deg), ('uns', uns)):
            self.mix_cards[key].set_value(f'{val:,.0f}')

    def _refresh_month(self):
        r = self.state.last_result
        if not r or not r.get('monthly'):
            return
        m = r['monthly']
        self.month_plot.clear()
        mode = self.month_combo.currentIndex()
        x = np.arange(12)
        if mode == 0:
            groups = [('pv_inv_out', tr('PV'), SERIES_COLORS['pv']),
                      ('grid', tr('Grid'), SERIES_COLORS['grid']),
                      ('deg', tr('Diesel'), SERIES_COLORS['deg']),
                      ('dhg', 'BESS', SERIES_COLORS['bess'])]
            wbar = 0.2
            self.month_plot.addLegend()
            for i, (key, label, color) in enumerate(groups):
                bar = pg.BarGraphItem(x=x + (i - 1.5) * wbar, height=m[key],
                                      width=wbar, brush=color, pen=None,
                                      name=label)
                self.month_plot.addItem(bar)
            self.month_plot.setLabel('left', tr('Energi (kWh)'))
            self._month_vals = list(np.asarray(m['pv_inv_out'], float)
                                    + np.asarray(m['grid'], float)
                                    + np.asarray(m['deg'], float)
                                    + np.asarray(m['dhg'], float))
            self._month_unit = tr('kWh total')
        elif mode == 1:
            self.month_plot.addItem(pg.BarGraphItem(
                x=x, height=m['fuel_l'], width=0.6,
                brush=SERIES_COLORS['deg'], pen=None))
            self.month_plot.setLabel('left', tr('Fuel (L)'))
            self._month_vals = list(np.asarray(m['fuel_l'], float))
            self._month_unit = 'L'
        else:
            self.month_plot.addItem(pg.BarGraphItem(
                x=x, height=m['pv_excess'], width=0.6,
                brush=SERIES_COLORS['exc'], pen=None))
            self.month_plot.setLabel('left', 'Excess (kWh)')
            self._month_vals = list(np.asarray(m['pv_excess'], float))
            self._month_unit = 'kWh'

    def _refresh_heat(self):
        s = self._series()
        if s is None:
            return
        key, cmap = [('soc', 'viridis'), ('deg', 'CET-L3'),
                     ('pv_excess', 'CET-L17')][self.heat_combo.currentIndex()]
        n = len(s['load'])
        y = np.asarray(s[key], float).reshape(n, -1)[:, 0]
        # Heatmap = jam-hari × hari. Agregasi ke PER JAM lebih dulu (mean daya)
        # agar tetap benar untuk interval sub-jam apa pun.
        r = self.state.last_result
        sim_lab = (r.get('sim_interval') if isinstance(r, dict) else None) or '1 hour'
        sph = ivals.steps_per_hour(sim_lab)
        if sph > 1:
            y = ivals.aggregate_series(y, sph, 'mean')
        n_h = len(y)
        days = n_h // 24
        if days < 1:
            self.heat_img.setImage(np.zeros((1, 24)), autoLevels=True)
            return
        y = y[:days * 24]
        if key == 'soc':
            y = y * 100.0
        img = y.reshape(days, 24)          # (hari, jam)
        self._heat_data = img
        self._heat_unit = ['%', 'kW', 'kW'][self.heat_combo.currentIndex()]
        self.heat_img.setImage(img, autoLevels=True)
        try:
            cm = pg.colormap.get(cmap)
        except Exception:
            cm = pg.colormap.get('viridis')
        self.heat_cbar.setColorMap(cm)
        self.heat_cbar.setLevels((float(img.min()), float(img.max())))
