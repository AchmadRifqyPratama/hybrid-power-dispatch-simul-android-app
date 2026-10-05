"""Halaman Optimization — sweep range PV/Inverter/BESS, objective & constraints."""
from __future__ import annotations
import threading
import numpy as np

from ...config.i18n import tr
from ..plotutil import fit_table_columns
from ..bgproc import ProcWorker
from PySide6.QtCore import QThread, Signal, Qt, QLocale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QFormLayout,
    QDoubleSpinBox, QSpinBox, QComboBox, QPushButton, QProgressBar,
    QTableWidget, QTableWidgetItem, QMessageBox, QFileDialog, QGridLayout,
    QHeaderView, QScrollArea, QCheckBox, QApplication,
    QRadioButton, QButtonGroup)

from ...engine.optimization import (OptimizationEngine, SweepRange,
                                    build_grid, build_grid_extra, OBJECTIVES,
                                    make_pool, safe_shutdown)
from ...config.parameters import cost_config, opt_base_params, SCHEMA, VISIBILITY
from ...config import intervals as ivals
from ..widgets import ParamGroupBox
import os
from ...data.exporter import (export_optimization, export_filename,
                              export_batch_optimization)
from ...data.importer import (read_profile_file, read_site_coords,
                              ImportError_)
from ...data.pvgis import batch_pvgis_pv


class _Worker(ProcWorker):   # proses latar (lihat gui/bgproc.py)
    progress = Signal(int, int)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, engine, grid, objective, constraints, tol=0.01,
                 auto=False, dcac=1.1):
        super().__init__()
        self.engine, self.grid = engine, grid
        self.objective, self.constraints = objective, constraints
        self.tol = tol
        self.auto = auto
        self.dcac = dcac
        self.cancel_flag = threading.Event()

    def run(self):
        try:
            if self.auto:
                res = self.engine.run_auto(
                    self.objective, self.constraints,
                    progress_cb=lambda d, t: self.progress.emit(d, t),
                    cancel_flag=self.cancel_flag, tol=self.tol,
                    dcac=self.dcac)
            else:
                res = self.engine.run(
                    self.grid, self.objective, self.constraints,
                    progress_cb=lambda d, t: self.progress.emit(d, t),
                    cancel_flag=self.cancel_flag, tol=self.tol)
            if res is not None:
                self.finished_ok.emit(res)
        except Exception as e:  # pragma: no cover
            self.failed.emit(str(e))


def _rng_box(title, lo, hi, st, unit, dec=1):
    box = QGroupBox(title)
    f = QFormLayout(box)
    mk = lambda v, mx: _spin(v, mx, dec)
    a, b, c = mk(lo, 1e7), mk(hi, 1e7), mk(st, 1e6)
    u = tr(unit)
    f.addRow(f'Start ({u})', a)
    f.addRow(f'Stop ({u})', b)
    f.addRow(f'Step ({u})', c)
    return box, a, b, c


def _spin(v, mx, dec=1):
    s = QDoubleSpinBox(); s.setRange(0, mx); s.setDecimals(dec)
    s.setSingleStep(10.0 ** (-dec))
    s.setValue(v); s.setGroupSeparatorShown(True)
    s.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))
    s.setKeyboardTracking(False)
    return s


class _BatchWorker(ProcWorker):   # proses latar (lihat gui/bgproc.py)
    """Menjalankan optimasi untuk beberapa berkas data secara berurutan."""
    progress = Signal(int, int, str)      # indeks, total, nama site
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, loaded, cfg, base, cost, grid, objective, constraints,
                 tol, auto, dcac, fallback_pv=None, read_errors=None,
                 win_h=None, start_h=0):
        super().__init__()
        # loaded: [{'site','path','load','pv','grid','deg'}] — sudah dibaca di
        # thread UTAMA. Worker TIDAK membaca Excel (pandas/openpyxl/lxml tidak
        # aman di thread lain di Windows -> 'access violation').
        self.loaded, self.cfg = list(loaded), cfg
        self.base, self.cost = base, cost
        self.grid, self.objective = grid, objective
        self.constraints = constraints
        self.tol, self.auto, self.dcac = tol, auto, dcac
        self.fallback_pv = fallback_pv
        self.win_h = win_h                       # durasi jendela per iterasi (jam)
        self.start_h = int(start_h or 0)         # titik mulai jendela (jam)
        self.cancel_flag = threading.Event()
        self.errors = list(read_errors or [])   # galat baca dari thread utama

    def run(self):
        rows = []
        # Satu process pool dipakai bersama untuk SELURUH berkas: membuat &
        # membongkar pool per berkas membuat aplikasi berhenti paksa pada
        # versi .exe. Namun bila pool ini mati di tengah jalan, JANGAN
        # biarkan seluruh batch ikut jatuh — buat ulang untuk site berikut
        # dan lewati site yang gagal (lihat pool_state di bawah).
        n_work = min(max(1, (os.cpu_count() or 2) - 1), 8)   # batasi memori
        pool = {'ex': None}

        def _open():
            if n_work > 1 and not self.cancel_flag.is_set():
                try:
                    pool['ex'] = make_pool(n_work)
                except Exception:
                    pool['ex'] = None      # gagal buat pool -> jalur serial

        def _close():
            ex, pool['ex'] = pool['ex'], None
            safe_shutdown(ex)

        _open()
        try:
            for i, item in enumerate(self.loaded):
                if self.cancel_flag.is_set():
                    break
                site = item['site']
                path = item.get('path', site)
                self.progress.emit(i, len(self.loaded), site)
                pstate = {'broken': False}
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
                    # DURASI simulasi: ambil jendela jam lalu anualisasi KPI
                    # (identik jalur single-site). Resolusi: mode Advanced
                    # memakai interval simulasi Dashboard (cfg['sim_interval'])
                    # agar "Firming Target Met (%)" dkk. tak dirata-ratakan ke
                    # per-jam (lihat komentar sejenis pada _Worker/_run());
                    # Standard TETAP '1 jam' (tak disentuh).
                    _adv = str(self.cfg.get('bess_mode', 'Standard')
                              ).strip().lower().startswith('adv')
                    sim_lab = str(self.cfg.get('sim_interval', '1 hour')) \
                        if _adv else '1 hour'
                    # 'DEG Status' per-site (kolom import Excel) diteruskan
                    # sama seperti jalur single-site -- lihat _t_deg_status.py.
                    L, P, G, dt_h, m, D = ivals.build_sim_arrays(
                        load, pv, gs, item.get('datetimes'), sim_lab,
                        start_h=self.start_h, window_h=self.win_h,
                        deg=item.get('deg'))
                    base_i = dict(self.base)
                    base_i['interval_h'] = dt_h
                    ann_i = ivals.annualization_factor_h(max(1e-9, m * dt_h))
                    base_i['annualize'] = ann_i
                    eng = OptimizationEngine(L, P, G, base_i, dict(self.cost),
                                             deg_status=D)
                    use_ex = pool['ex']
                    use_workers = n_work if use_ex is not None else 1
                    if self.auto:
                        res = eng.run_auto(self.objective, self.constraints,
                                           workers=use_workers, executor=use_ex,
                                           cancel_flag=self.cancel_flag,
                                           tol=self.tol, dcac=self.dcac,
                                           pool_state=pstate)
                    else:
                        res = eng.run(self.grid, self.objective,
                                      self.constraints,
                                      workers=use_workers, executor=use_ex,
                                      cancel_flag=self.cancel_flag,
                                      tol=self.tol, pool_state=pstate)
                    if res is None:
                        break              # dibatalkan pengguna
                    res['annual_load_kwh'] = np.full(
                        len(res['kwp']), float(np.sum(L)) * ann_i)
                    rows.append({'site': site, 'path': path, 'res': res})
                except Exception as e:      # satu site gagal -> catat, lanjut
                    self.errors.append((site, str(e)))
                finally:
                    if pstate.get('broken'):   # pool mati -> buat ulang
                        _close()
                        _open()
            self.finished_ok.emit(rows)
        except Exception as e:                      # pragma: no cover
            self.failed.emit(str(e))
        finally:
            _close()


class OptimizationPage(QWidget):
    COLS = [('kwp', 'PV\n(kWp)'), ('kw_inv', 'INV\n(kW)'),
            ('dc_ac_ratio', 'DC/AC'),
            ('kwh_bess', 'BESS\n(kWh)'),
            ('pcs_kw', 'PCS\n(kW)'),
            ('bess_autonomy_h', 'BESS Autonomy\n(jam)'),
            ('lcoe', 'LCOE\n(Rp/kWh)'),
            ('npv', 'NPV\n(Rp)'), ('capex', 'CAPEX\n(Rp)'),
            ('payback_years', 'Payback\n(th)'),
            ('renewable_fraction', 'RF\n(%)'),
            ('annual_pv_generation_kwh', 'PV Generation\n(kWh/th)'),
            ('diesel_energy_kwh', 'Diesel Energy\n(kWh/th)'),
            ('diesel_fuel_l', 'Diesel Fuel\n(L/th)'),
            ('pv_excess_ratio', 'Unused/Curtail\n(%)'),
            ('unserved_kwh', 'Unserved\n(kWh)')]
    COL_DEC = {'dc_ac_ratio': 2, 'bess_autonomy_h': 2, 'payback_years': 2,
               'kwh_bess': 0,     # kapasitas BESS selalu bulat kWh
               'pcs_kw': 2,
               'lcoe': 0, 'npv': 0, 'capex': 0,
               'annual_pv_generation_kwh': 0, 'diesel_energy_kwh': 0,
               'diesel_fuel_l': 0, 'unserved_kwh': 1}

    # --- Parameter mode Advanced yang DAPAT dioptimasi (di luar PV/INV/BESS) ---
    # ui_key -> dict(engine, apply, label, unit, dec, lo, hi, step, scale, disp)
    #   engine = kunci kolom grid utk OptimizationEngine
    #   apply  = kunci cfg saat "Terapkan Terbaik" (reserve_frac dalam %)
    #   scale  = faktor UI -> engine (SOC Fraction: % -> pecahan)
    #   disp   = kunci kolom hasil ('opt_...') utk tabel
    _EXTRA_PARAMS = {
        'window': dict(engine='smoothing_window', apply='smoothing_window',
                       label='MA Window', unit='langkah', dec=0,
                       lo=5, hi=60, step=5, scale=1.0,
                       disp='opt_smoothing_window'),
        'target': dict(engine='firming_kw', apply='firming_kw',
                       label='Target Power', unit='kW', dec=0,
                       lo=500, hi=4000, step=250, scale=1.0,
                       disp='opt_firming_kw'),
        'maxchg': dict(engine='max_charge_cap', apply='max_charge_kw',
                       label='Maximum Charge Power', unit='kW', dec=0,
                       lo=100, hi=2000, step=100, scale=1.0,
                       disp='opt_max_charge'),
        'maxdhg': dict(engine='max_discharge_cap', apply='max_discharge_kw',
                       label='Maximum Discharge Power', unit='kW', dec=0,
                       lo=100, hi=2000, step=100, scale=1.0,
                       disp='opt_max_discharge'),
        'rfrac': dict(engine='reserve_frac', apply='reserve_frac',
                      label='SOC Fraction', unit='%', dec=0,
                      lo=0, hi=50, step=10, scale=0.01,
                      disp='opt_reserve_frac'),
        'rkw': dict(engine='reserve_kw', apply='reserve_kw',
                    label='Reserve Power', unit='kW', dec=0,
                    lo=0, hi=1000, step=100, scale=1.0,
                    disp='opt_reserve_kw'),
    }
    # kolom tampilan tabel: disp -> (header, dec, display_scale)
    _EXTRA_DISP = {
        'opt_smoothing_window': ('MA Window\n(langkah)', 0, 1.0),
        'opt_firming_kw': ('Target Power\n(kW)', 0, 1.0),
        'opt_firm_met_pct': ('Firming Target Met\n(%)', 1, 1.0),
        'opt_max_charge': ('Max BESS Charge\n(kW)', 0, 1.0),
        'opt_max_discharge': ('Max BESS Discharge\n(kW)', 0, 1.0),
        'opt_reserve_frac': ('SOC Fraction\n(%)', 1, 100.0),
        'opt_reserve_kw': ('Reserve Power\n(kW)', 0, 1.0),
    }
    _EXTRA_DISP_ORDER = ['opt_smoothing_window', 'opt_firming_kw',
                         'opt_firm_met_pct',
                         'opt_max_charge', 'opt_max_discharge',
                         'opt_reserve_frac', 'opt_reserve_kw']

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.worker = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        # Kartu dibuat ringkas & dapat menyusut agar muat tanpa scrollbar
        # horizontal, meski pada penskalaan layar tinggi / jendela sempit.
        # 'AsNeeded' sebagai jaring pengaman: bila muat (kasus normal) scrollbar
        # TIDAK muncul; bila layar sangat sempit/DPI tinggi, konten tetap dapat
        # dijangkau (tidak terpotong) alih-alih terpangkas di kanan.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        page = QWidget(); scroll.setWidget(page)
        outer.addWidget(scroll)
        lay = QVBoxLayout(page)
        # Margin kiri = kanan agar seluruh konten (kartu, tombol, hingga tabel
        # hasil) rata; ruang kanan mengimbangi scrollbar vertikal.
        lay.setContentsMargins(12, 10, 12, 10)
        t = QLabel(tr('Optimization')); t.setObjectName('PageTitle')
        lay.addWidget(t)
        s = QLabel(tr('Grid search seluruh kombinasi — '
                      'tervektorisasi + multiprocessing di semua '
                      'core CPU.'))
        s.setObjectName('PageSub'); lay.addWidget(s)

        # Toggle untuk menyembunyikan/menampilkan blok konfigurasi (Range,
        # PCS/Constraints/Objective) agar tabel hasil dapat menampilkan lebih
        # banyak baris opsi. Ditempatkan SATU BARIS dengan 'Mode Sizing' — baris
        # ini SELALU terlihat sehingga konfigurasi dapat dibuka kembali.
        self.btn_cfg_toggle = QPushButton('')
        self.btn_cfg_toggle.setProperty('flat', True)
        self.btn_cfg_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_cfg_toggle.clicked.connect(self._toggle_cfg_section)

        # Baris KOMPAK SATU BARIS (selalu terlihat): toggle konfigurasi, mode
        # sizing, DC/AC (auto), titik MULAI (bulan/tanggal) & DURASI simulasi.
        # Label diringkas agar muat satu baris. Deskripsi Auto Optimizer yang
        # panjang dipindah ke tooltip mode (tidak lagi membungkus baris).
        # Grup ditempel RAPAT (addSpacing tetap, bukan stretch) supaya tidak
        # ada jarak kosong yang aneh di ANTARA grup. Lebar kotak isian dijaga
        # SEWAJARNYA (hanya DC/AC & tanggal yang perlu diperlebar eksplisit,
        # sesuai permintaan sebelumnya) — TIDAK dipatok berlebihan, agar
        # total baris tetap muat di lebar jendela normal & tidak terpotong
        # di kanan. Satu stretch TUNGGAL di ujung kanan menampung sisa ruang
        # tanpa memunculkan celah di tengah baris.
        mrow = QHBoxLayout()
        mrow.addWidget(self.btn_cfg_toggle)
        mrow.addSpacing(12)
        mrow.addWidget(QLabel(tr('Sizing:')))
        self.mode = QComboBox()
        self.mode.addItems([tr('Manual Range (Grid Search)'),
                            tr('Auto Optimizer (tanpa range)')])
        self.mode.setToolTip(tr(
            'Batas pencarian Auto Optimizer diturunkan otomatis dari profil '
            'beban & PV; grid disempitkan iteratif hingga konvergen. Kapasitas '
            'inverter diikat INV = PV / rasio DC/AC.'))
        self.mode.currentIndexChanged.connect(self._mode_changed)
        mrow.addWidget(self.mode)
        mrow.addSpacing(12)
        self.lbl_dcac = QLabel(tr('DC/AC:'))
        mrow.addWidget(self.lbl_dcac)
        self.auto_dcac = QDoubleSpinBox()
        self.auto_dcac.setRange(0.50, 3.00); self.auto_dcac.setDecimals(2)
        self.auto_dcac.setSingleStep(0.05); self.auto_dcac.setValue(1.10)
        self.auto_dcac.setMinimumWidth(92)      # cukup lebar utk nilai "1.10"
        self.auto_dcac.setLocale(QLocale(QLocale.English,
                                         QLocale.UnitedStates))
        self.auto_dcac.setKeyboardTracking(False)
        self.auto_dcac.setToolTip(
            tr('Rasio DC/AC yang dipakai Auto Optimizer: kapasitas '
               'inverter = PV \u00f7 rasio ini.'))
        self.auto_dcac.valueChanged.connect(self._mode_changed)
        mrow.addWidget(self.auto_dcac)
        mrow.addSpacing(12)
        # Titik MULAI jendela simulasi (bulan/tanggal) \u2014 berlaku bila durasi <
        # setahun (ada ruang geser); diabaikan untuk 'Setahun penuh'.
        self.lbl_start = QLabel(tr('Mulai:'))
        mrow.addWidget(self.lbl_start)
        self.cmb_month = QComboBox()
        self.cmb_month.addItems(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])
        self.cmb_month.setToolTip(tr('Bulan awal jendela simulasi tiap '
                                     'iterasi (durasi < setahun).'))
        mrow.addWidget(self.cmb_month)
        self.spin_day = QSpinBox(); self.spin_day.setRange(1, 31)
        self.spin_day.setValue(1)
        self.spin_day.setMinimumWidth(68)       # cukup lebar utk tanggal (1-31)
        self.spin_day.setToolTip(tr('Tanggal awal jendela simulasi (1-31).'))
        mrow.addWidget(self.spin_day)
        mrow.addSpacing(12)
        # Durasi SIMULASI per iterasi (jendela jam). Lebih pendek = lebih cepat;
        # KPI (LCOE, PV generation, dll.) diekstrapolasi ke SETAHUN. 'Setahun
        # penuh' = tanpa ekstrapolasi. Basis 1 jam; data sub-jam \u2192 per-jam.
        # Mode Firming: 'Firming Target Met (%)' TIDAK diekstrapolasi \u2014
        # selalu dihitung hanya dari jendela (Mulai+Durasi) yang benar-benar
        # disimulasikan di sini (menit tercapai \u00f7 total menit firming window).
        self.lbl_dur = QLabel(tr('Durasi:'))
        mrow.addWidget(self.lbl_dur)
        self._dur_opts = ivals.allowed_durations('1 hour')      # [(label, jam)]
        self.cmb_dur = QComboBox()
        self.cmb_dur.addItems([tr(l) for l, _h in self._dur_opts])
        self.cmb_dur.setCurrentIndex(len(self._dur_opts) - 1)   # default: setahun
        self.cmb_dur.setToolTip(tr(
            'Durasi (jendela) yang disimulasikan tiap iterasi, dari titik '
            'Mulai. Lebih pendek = lebih cepat; KPI (LCOE, PV generation, dll.) '
            'diekstrapolasi ke setahun. "Setahun penuh" = tanpa ekstrapolasi. '
            'Mode Firming: kolom "Firming Target Met (%)" TIDAK diekstrapolasi, '
            'selalu dihitung hanya dari jendela ini \u2014 pilih "Setahun penuh" '
            'agar mencerminkan seluruh tahun, bukan hanya sampel.'))
        mrow.addWidget(self.cmb_dur)
        mrow.addStretch(1)                      # sisa ruang di UJUNG saja
        lay.addLayout(mrow)                       # baris SELALU terlihat

        # Blok konfigurasi yang dapat disembunyikan: Range + kartu
        # PCS / Constraints / Objective.
        self.cfg_box = QWidget()
        cfgv = QVBoxLayout(self.cfg_box)
        cfgv.setContentsMargins(0, 0, 0, 0)
        cfgv.setSpacing(8)

        top = QGridLayout()
        b1, self.pv_lo, self.pv_hi, self.pv_st = _rng_box(
            tr('Range PV'), 500, 3000, 100, 'kWp', dec=2)
        b2, self.iv_lo, self.iv_hi, self.iv_st = _rng_box(
            tr('Range PV Inverter'), 400, 2500, 50, 'kW')
        for _w in (self.pv_lo, self.pv_hi, self.pv_st):
            _w.setSingleStep(0.01); _w.setMinimum(0.01 if _w is self.pv_st
                                                 else 0.0)
        b3, self.bs_lo, self.bs_hi, self.bs_st = _rng_box(
            tr('Range BESS'), 500, 5000, 100, 'kWh')
        top.addWidget(b1, 0, 0); top.addWidget(b2, 0, 1); top.addWidget(b3, 0, 2)
        for _c in range(3):
            top.setColumnStretch(_c, 1)
        self._range_boxes = (b1, b2, b3)
        cfgv.addLayout(top)

        # --- Kartu range parameter mode Advanced yang dioptimasi ---
        # Muncul hanya bila mode Advanced dgn sub-mode terkait aktif & mode
        # sizing = Manual Range. Range charge/discharge menggantikan kartu PCS
        # utk Smoothing/Firming (dayanya justru yang dioptimasi).
        self._adv_opt_box = QGroupBox(
            tr('Optimasi Variabel Mode Advanced'))
        self._adv_opt_grid = QGridLayout(self._adv_opt_box)
        self._adv_opt_grid.setHorizontalSpacing(8)
        self._adv_opt_grid.setVerticalSpacing(8)
        # Bangun SEMUA kotak range sekali; penempatan (hanya yang aktif, tanpa sel
        # kosong) dilakukan _sync_adv_opt_ui agar layout selalu rapat & kompak.
        self._adv_rng = {}
        for uk, meta in self._EXTRA_PARAMS.items():
            box, lo, hi, st = _rng_box(
                tr(meta['label']), meta['lo'], meta['hi'], meta['step'],
                meta['unit'], dec=meta['dec'])
            self._adv_rng[uk] = (box, lo, hi, st)
            box.setVisible(False)
            for _w in (lo, hi, st):
                _w.valueChanged.connect(self._update_count)
        cfgv.addWidget(self._adv_opt_box)

        # Baris kartu bawah: PCS BESS | Batasan Optimasi | Objective & Kontrol
        # (grid terpisah dari baris Range agar lebar kolom tidak saling
        # memaksa; kartu dibuat dapat menyusut agar rapi di layar sempit).
        bottom = QGridLayout()

        pbox = QGroupBox(tr('PCS BESS (Charge / Discharge)'))
        pf = QFormLayout(pbox)
        self.pcs_mode = QComboBox()
        self.pcs_mode.addItems([tr('Ikut C-rate dari Parameters'),
                                tr('C-rate tetap (1/jam)'),
                                tr('Daya PCS tetap (kW)')])
        self.pcs_mode.currentIndexChanged.connect(self._pcs_changed)
        pf.addRow(tr('Mode'), self.pcs_mode)
        self.pcs_val = QDoubleSpinBox()
        self.pcs_val.setDecimals(3); self.pcs_val.setRange(0.0, 1e7)
        self.pcs_val.setSingleStep(0.05); self.pcs_val.setValue(0.5)
        self.pcs_val.setGroupSeparatorShown(True)
        self.pcs_val.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))
        self.pcs_val.setKeyboardTracking(False)
        self._pcs_val_label = QLabel(tr('Nilai'))
        pf.addRow(self._pcs_val_label, self.pcs_val)
        self._pcs_form = pf
        self.pcs_info = QLabel('')
        self.pcs_info.setObjectName('PageSub')
        self.pcs_info.setWordWrap(True)
        pf.addRow(self.pcs_info)
        bottom.addWidget(pbox, 0, 0)
        pbox.setMinimumWidth(140)
        self._pcs_box = pbox

        # --- Optimization Constraints (dipindah dari halaman Parameters) ---
        # Dibangun dari SCHEMA agar label, satuan, tooltip, & validasi identik.
        self.cbox = ParamGroupBox('Optimization Constraints',
                                  SCHEMA['Optimization Constraints'])
        self.cbox.set_values(self.state.cfg)
        self.cbox.changed.connect(self._on_constraint_change)
        # Kompak & dapat menyusut: label boleh membungkus (wrap) ke beberapa
        # baris, field ringkas berlebar tetap — sehingga kartu tidak memaksa
        # lebar kolom membesar. DontWrapRows: label & input SELALU satu baris
        # (label kiri, input kanan); tanpa ini input bisa 'terlempar' ke baris
        # baru di bawah label pada kartu sempit — mis. Maximum LCOE.
        self.cbox._form.setLabelAlignment(Qt.AlignLeft)
        self.cbox._form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        # Kolom field MENGISI sisa lebar kartu (unit menempel dekat tepi kanan)
        # sehingga margin kanan ≈ margin kiri — tidak ada ruang kosong berlebih.
        self.cbox._form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for _lbl in self.cbox.labels.values():
            _lbl.setWordWrap(True)
        # Kotak isian berlebar MINIMUM (boleh melebar mengisi kolom); jangan
        # dipatok fixed agar tidak menyisakan ruang kosong di kanan.
        for _f in self.cbox.fields.values():
            _f.w.setMinimumWidth(72)
            _f.w.setMaximumWidth(16777215)      # lepas batas fixed bila ada
        self.cbox.setMinimumWidth(140)
        bottom.addWidget(self.cbox, 0, 1)
        self.state.config_changed.connect(self._refresh_constraints)

        obox = QGroupBox(tr('Objective Control'))
        # QGridLayout: kolom-0 = label prioritas (ringkas), kolom-1 = dropdown
        # (memanjang). Dropdown menempel tepat setelah nama prioritas \u2014 tanpa
        # ruang kosong. Baris panjang (toleransi/jumlah/tombol) merentang 2
        # kolom agar TIDAK melebarkan kolom label. Struktur ini sama untuk ID & EN.
        og = QGridLayout(obox)
        og.setHorizontalSpacing(10); og.setVerticalSpacing(9)
        og.setColumnStretch(1, 1)
        NONE = tr('\u2014 (tidak dipakai)')
        self._OBJ_NONE = NONE
        self.obj1 = QComboBox(); self.obj1.addItems(OBJECTIVES.keys())
        self.obj2 = QComboBox(); self.obj2.addItem(NONE)
        self.obj2.addItems(OBJECTIVES.keys())
        self.obj3 = QComboBox(); self.obj3.addItem(NONE)
        self.obj3.addItems(OBJECTIVES.keys())
        for _cb in (self.obj1, self.obj2, self.obj3):
            _cb.setMinimumWidth(84)
        for i, (lbl_txt, cb) in enumerate(((tr('Prioritas 1'), self.obj1),
                                           (tr('Prioritas 2'), self.obj2),
                                           (tr('Prioritas 3'), self.obj3))):
            og.addWidget(QLabel(lbl_txt), i, 0, Qt.AlignLeft | Qt.AlignVCenter)
            og.addWidget(cb, i, 1)
        self.tol_spin = QDoubleSpinBox()
        self.tol_spin.setRange(0.1, 20.0); self.tol_spin.setDecimals(1)
        self.tol_spin.setValue(1.0); self.tol_spin.setSuffix(' %')
        self.tol_spin.setSingleStep(0.1)
        self.tol_spin.setLocale(QLocale(QLocale.English,
                                        QLocale.UnitedStates))
        self.tol_spin.setKeyboardTracking(False)
        self.tol_spin.setToolTip(
            tr('Kandidat yang nilainya masih dalam pita toleransi ini '
               'terhadap yang terbaik pada suatu prioritas dianggap setara, '
               'lalu diurutkan oleh prioritas berikutnya.'))
        # Baris toleransi: label + kotak yang MELEBAR mengisi sisa lebar
        # (tepi kanannya sejajar dropdown prioritas di atasnya).
        tolrow = QHBoxLayout(); tolrow.setContentsMargins(0, 0, 0, 0)
        tolrow.setSpacing(10)
        _tl = QLabel(tr('Toleransi antar prioritas')); _tl.setWordWrap(True)
        tolrow.addWidget(_tl, 1); tolrow.addWidget(self.tol_spin, 0)
        og.addLayout(tolrow, 3, 0, 1, 2)
        # Baris jumlah kombinasi: beri jarak jelas antara label & nilai; nilai
        # boleh membungkus agar tidak terpotong.
        self.n_lbl = QLabel('-'); self.n_lbl.setWordWrap(True)
        cntrow = QHBoxLayout(); cntrow.setContentsMargins(0, 6, 0, 0)
        cntrow.setSpacing(12)
        cntrow.addWidget(QLabel(tr('Jumlah kombinasi')), 0)
        cntrow.addWidget(self.n_lbl, 1)
        og.addLayout(cntrow, 4, 0, 1, 2)
        self.btn = QPushButton(tr('Run Optimization'))
        self.btn.clicked.connect(self._run)
        self.btn_cancel = QPushButton('Cancel'); self.btn_cancel.setEnabled(False)
        self.btn_cancel.setProperty('flat', True)
        self.btn_cancel.clicked.connect(self._cancel)
        hb = QHBoxLayout(); hb.addWidget(self.btn); hb.addWidget(self.btn_cancel)
        og.addLayout(hb, 5, 0, 1, 2)
        obox.setMinimumWidth(150)
        bottom.addWidget(obox, 0, 2)
        for _c in range(3):
            bottom.setColumnStretch(_c, 1)
        cfgv.addLayout(bottom)
        lay.addWidget(self.cfg_box)
        for w in (self.pv_lo, self.pv_hi, self.pv_st, self.iv_lo, self.iv_hi,
                  self.iv_st, self.bs_lo, self.bs_hi, self.bs_st):
            w.valueChanged.connect(self._update_count)
        self._update_count()
        self._pcs_changed()
        # Sinkronkan tampilan mode Advanced (sembunyikan PCS utk Smoothing/
        # Firming, tampilkan kartu range param yg dioptimasi) & saat cfg berubah.
        self.state.config_changed.connect(self._sync_adv_opt_ui)
        self._sync_adv_opt_ui()
        # Persist SELURUH setelan Optimization (Sizing/DC-AC, PCS, Objective,
        # Toleransi, Range) ke cfg tiap kali berubah — agar TIDAK ter-reset saat
        # blok konfigurasi disembunyikan lalu ditampilkan lagi, atau saat
        # aplikasi dibuka ulang. (Constraints sudah persist via _on_constraint_change.)
        for _key, _kind, _w in self._opt_widget_map():
            if _kind == 'text':
                _w.currentTextChanged.connect(self._persist_opt)
            elif _kind == 'idx':
                _w.currentIndexChanged.connect(self._persist_opt)
            else:
                _w.valueChanged.connect(self._persist_opt)

        self.pbar = QProgressBar()
        lay.addWidget(self.pbar)

        hb2 = QHBoxLayout()
        self.lbl_best = QLabel(''); self.lbl_best.setWordWrap(True)
        hb2.addWidget(self.lbl_best, 1)
        self.btn_apply = QPushButton(tr('Terapkan Terbaik ke Parameters'))
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply_best)
        self.btn_clear = QPushButton(tr('Bersihkan Hasil'))
        self.btn_clear.setProperty('flat', True)
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setEnabled(False)
        self.btn_clear.clicked.connect(self._clear_results)
        self.btn_export = QPushButton(tr('Export Hasil…'))
        self.btn_export.setProperty('flat', True); self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export)
        hb2.addWidget(self.btn_apply); hb2.addWidget(self.btn_export)
        hb2.addWidget(self.btn_clear)
        lay.addLayout(hb2)

        _init_cols = self._visible_base_cols(None)   # tanpa DC/AC (empty state)
        self.table = QTableWidget(0, len(_init_cols))
        self.table.setHorizontalHeaderLabels(
            ['\n'.join(tr(part) for part in c[1].split('\n'))
             for c in _init_cols])
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setDefaultSectionSize(24)
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setDefaultAlignment(Qt.AlignCenter)
        hh.setMinimumSectionSize(84)
        hh.setHighlightSections(False)
        # jamin minimal ~12 baris terlihat tanpa menggeser panel atas
        self.table.setMinimumHeight(24 * 12 + 60)
        lay.addWidget(self.table, 1)

        # ---------------- Batch beberapa file data ----------------
        self.chk_batch = QCheckBox(
            tr('Aktifkan Batch Multi-Site (beberapa berkas data)'))
        self.chk_batch.setCursor(Qt.PointingHandCursor)
        self.chk_batch.setToolTip(tr(
            'Tampilkan bagian untuk menjalankan optimasi pada '
            'beberapa berkas data sekaligus.'))
        self.chk_batch.toggled.connect(self._toggle_batch)
        lay.addWidget(self.chk_batch)

        bbox = QGroupBox(tr('Batch Multi-Site (beberapa berkas data)'))
        bl = QVBoxLayout(bbox)
        bl.addWidget(QLabel(tr(
            'Jalankan optimasi untuk beberapa berkas data sekaligus memakai '
            'parameter & objective yang sama. Nama site diambil dari nama '
            'berkas.')))
        brow = QHBoxLayout()
        self.btn_pick = QPushButton(tr('Pilih Berkas Data…'))
        self.btn_pick.setProperty('flat', True)
        self.btn_pick.setCursor(Qt.PointingHandCursor)
        self.btn_pick.clicked.connect(self._pick_batch)
        self.btn_batch = QPushButton(tr('▶  Jalankan Batch'))
        self.btn_batch.setProperty('flat', True)
        self.btn_batch.setCursor(Qt.PointingHandCursor)
        self.btn_batch.setEnabled(False)
        self.btn_batch.clicked.connect(self._run_batch)
        self.btn_batch_cancel = QPushButton(tr('Batalkan Batch'))
        self.btn_batch_cancel.setProperty('flat', True)
        self.btn_batch_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_batch_cancel.setEnabled(False)
        self.btn_batch_cancel.setToolTip(tr(
            'Hentikan proses batch yang sedang berjalan.'))
        self.btn_batch_cancel.clicked.connect(self._cancel_batch)
        self.btn_batch_export = QPushButton(tr('Export Batch…'))
        self.btn_batch_export.setProperty('flat', True)
        self.btn_batch_export.setCursor(Qt.PointingHandCursor)
        self.btn_batch_export.setEnabled(False)
        self.btn_batch_export.clicked.connect(self._export_batch)
        brow.addWidget(self.btn_pick); brow.addWidget(self.btn_batch)
        brow.addWidget(self.btn_batch_cancel)
        self.btn_batch_clear = QPushButton(tr('Bersihkan Batch'))
        self.btn_batch_clear.setProperty('flat', True)
        self.btn_batch_clear.setCursor(Qt.PointingHandCursor)
        self.btn_batch_clear.setToolTip(tr(
            'Hapus daftar berkas dan seluruh hasil batch agar dapat '
            'memulai dengan berkas data baru.'))
        self.btn_batch_clear.clicked.connect(self._clear_batch)
        brow.addWidget(self.btn_batch_export)
        brow.addWidget(self.btn_batch_clear)
        brow.addStretch(1)
        bl.addLayout(brow)

        # ---- Sumber koordinat PV tiap site (pilihan pengguna) ----
        crow = QHBoxLayout()
        crow.addWidget(QLabel(tr('Koordinat PV:')))
        self.grp_coord = QButtonGroup(self)
        self.rb_coord_home = QRadioButton(tr('Ikuti halaman Home'))
        self.rb_coord_site = QRadioButton(
            tr('Per site dari Excel (unduh PVGIS)'))
        self.rb_coord_home.setToolTip(tr(
            'Semua site memakai PV ENetAC dari berkas datanya '
            '(seperti biasa).'))
        self.rb_coord_site.setToolTip(tr(
            'Tiap site memakai koordinat sendiri dari berkas Excel. PV '
            'diunduh dari PVGIS memakai tilt/azimuth, mounting, loss, dan '
            'year dari jendela Select Project Location; PV base mengikuti '
            'halaman Parameters.'))
        self.grp_coord.addButton(self.rb_coord_home)
        self.grp_coord.addButton(self.rb_coord_site)
        for rb in (self.rb_coord_home, self.rb_coord_site):
            rb.setCursor(Qt.PointingHandCursor)
            rb.toggled.connect(self._on_coord_mode)
        crow.addWidget(self.rb_coord_home)
        crow.addWidget(self.rb_coord_site)
        self.btn_coord_file = QPushButton(tr('Pilih Excel Koordinat…'))
        self.btn_coord_file.setProperty('flat', True)
        self.btn_coord_file.setCursor(Qt.PointingHandCursor)
        self.btn_coord_file.clicked.connect(self._pick_coords)
        self.btn_coord_tmpl = QPushButton(tr('Template…'))
        self.btn_coord_tmpl.setProperty('flat', True)
        self.btn_coord_tmpl.setCursor(Qt.PointingHandCursor)
        self.btn_coord_tmpl.setToolTip(tr(
            'Unduh templat Excel koordinat (kolom Site, Latitude, '
            'Longitude).'))
        self.btn_coord_tmpl.clicked.connect(self._coords_template)
        crow.addWidget(self.btn_coord_file)
        crow.addWidget(self.btn_coord_tmpl)
        crow.addStretch(1)
        bl.addLayout(crow)
        self.lbl_coord = QLabel('')
        self.lbl_coord.setObjectName('PageSub')
        self.lbl_coord.setWordWrap(True)
        bl.addWidget(self.lbl_coord)

        arow = QHBoxLayout()
        arow.addWidget(QLabel(tr('Site:')))
        self.site_combo = QComboBox()
        self.site_combo.setMinimumWidth(220)
        self.site_combo.setToolTip(tr(
            'Pilih site yang hasil terbaiknya akan diterapkan.'))
        arow.addWidget(self.site_combo)
        self.btn_apply_site = QPushButton(
            tr('Terapkan Site Terpilih ke Parameters'))
        self.btn_apply_site.setCursor(Qt.PointingHandCursor)
        self.btn_apply_site.setEnabled(False)
        self.btn_apply_site.setToolTip(tr(
            'Salin sizing terbaik site ini ke halaman Parameters '
            'sekaligus memuat berkas datanya sebagai profil aktif.'))
        self.btn_apply_site.clicked.connect(self._apply_site)
        arow.addWidget(self.btn_apply_site)
        arow.addStretch(1)
        bl.addLayout(arow)
        self.lbl_batch = QLabel(tr('Belum ada berkas dipilih.'))
        self.lbl_batch.setObjectName('PageSub')
        self.lbl_batch.setWordWrap(True)
        bl.addWidget(self.lbl_batch)

        self.BCOLS = [('site', tr('Site')), ('kwp', 'PV\n(kWp)'),
                      ('kw_inv', 'INV\n(kW)'), ('dc_ac_ratio', 'DC/AC'),
                      ('kwh_bess', 'BESS\n(kWh)'), ('pcs_kw', 'PCS\n(kW)'),
                      ('bess_autonomy_h', 'BESS Autonomy\n(jam)'),
                      ('lcoe', 'LCOE\n(Rp/kWh)'), ('npv', 'NPV\n(Rp)'),
                      ('capex', 'CAPEX\n(Rp)'),
                      ('payback_years', 'Payback\n(th)'),
                      ('renewable_fraction', 'RF\n(%)'),
                      ('annual_pv_generation_kwh', 'PV Generation\n(kWh/th)'),
                      ('diesel_energy_kwh', 'Diesel Energy\n(kWh/th)'),
                      ('diesel_fuel_l', 'Diesel Fuel\n(L/th)'),
                      ('pv_excess_ratio', 'Unused/Curtail\n(%)'),
                      ('unserved_kwh', 'Unserved\n(kWh)')]
        self.btable = QTableWidget(0, len(self.BCOLS))
        self.btable.setHorizontalHeaderLabels(
            ['\n'.join(tr(x) for x in c[1].split('\n')) for c in self.BCOLS])
        self.btable.setAlternatingRowColors(True)
        self.btable.setEditTriggers(QTableWidget.NoEditTriggers)
        self.btable.setSelectionBehavior(QTableWidget.SelectRows)
        self.btable.verticalHeader().setDefaultSectionSize(24)
        bh = self.btable.horizontalHeader()
        bh.setSectionResizeMode(QHeaderView.Interactive)
        bh.setDefaultAlignment(Qt.AlignCenter)
        bh.setMinimumSectionSize(84)
        # tepat 10 baris terlihat sebelum perlu di-scroll
        _bh = 24 * 10 + 64
        self.btable.setMinimumHeight(_bh)
        self.btable.setMaximumHeight(_bh)
        self.btable.itemSelectionChanged.connect(self._sync_site_combo)
        bl.addWidget(self.btable)
        lay.addWidget(bbox)
        self.batch_box = bbox
        bbox.setVisible(False)          # tersembunyi sampai diaktifkan
        self.batch_paths = list(getattr(state, 'batch_paths', []) or [])
        self.batch_rows = list(getattr(state, 'batch_rows', []) or [])
        # ---- pulihkan pilihan koordinat PV per site ----
        self._batch_coords = []
        cmode = str(state.cfg.get('batch_coord_mode', 'home') or 'home')
        (self.rb_coord_site if cmode == 'persite'
         else self.rb_coord_home).setChecked(True)
        cpath = state.cfg.get('batch_coords_path')
        if cpath and os.path.exists(cpath):
            try:
                self._batch_coords = read_site_coords(cpath)
            except Exception:
                self._batch_coords = []
        self._sync_coord_ui()
        if self.batch_rows:              # pulihkan tampilan batch
            self.chk_batch.setChecked(True)
            try:
                self._batch_done(self.batch_rows)
            except Exception:
                self.batch_rows = []
        if getattr(state, 'last_opt', None):    # pulihkan hasil terakhir
            try:
                self._apply_result(state.last_opt)
            except Exception:
                state.last_opt = None
        # pulihkan status lipat blok konfigurasi (tersimpan di cfg)
        self._cfg_collapsed = bool(state.cfg.get('opt_cfg_collapsed', False))
        self._apply_cfg_collapsed()

    # ------------------------------------------------------------------
    def _apply_cfg_collapsed(self):
        """Terapkan status lipat: sembunyikan/ tampilkan blok konfigurasi &
        perbarui teks tombol toggle. Saat DITAMPILKAN kembali, setelan dipulihkan
        dari cfg sehingga tidak ter-reset."""
        hidden = bool(getattr(self, '_cfg_collapsed', False))
        if not hidden:
            self._restore_opt()          # pulihkan setelan sebelum tampil
        self.cfg_box.setVisible(not hidden)
        self.btn_cfg_toggle.setText(
            tr('▸  Tampilkan Konfigurasi') if hidden
            else tr('▾  Sembunyikan Konfigurasi'))

    # -- persistensi setelan Optimization (Sizing/DC-AC, PCS, Objective, Range) --
    def _opt_widget_map(self):
        """(cfg_key, jenis, widget) untuk seluruh setelan yang harus persist."""
        return [
            ('opt_sizing_mode', 'idx', self.mode),
            ('opt_sim_duration', 'idx', self.cmb_dur),
            ('opt_start_month', 'idx', self.cmb_month),
            ('opt_start_day', 'val', self.spin_day),
            ('opt_auto_dcac', 'val', self.auto_dcac),
            ('opt_pcs_mode', 'idx', self.pcs_mode),
            ('opt_pcs_val', 'val', self.pcs_val),
            ('opt_obj1', 'text', self.obj1),
            ('opt_obj2', 'text', self.obj2),
            ('opt_obj3', 'text', self.obj3),
            ('opt_tol', 'val', self.tol_spin),
            ('opt_pv_lo', 'val', self.pv_lo), ('opt_pv_hi', 'val', self.pv_hi),
            ('opt_pv_st', 'val', self.pv_st),
            ('opt_iv_lo', 'val', self.iv_lo), ('opt_iv_hi', 'val', self.iv_hi),
            ('opt_iv_st', 'val', self.iv_st),
            ('opt_bs_lo', 'val', self.bs_lo), ('opt_bs_hi', 'val', self.bs_hi),
            ('opt_bs_st', 'val', self.bs_st),
        ] + [
            (f'opt_adv_{uk}_{part}', 'val', w)
            for uk, (box, lo, hi, st) in getattr(self, '_adv_rng', {}).items()
            for part, w in (('lo', lo), ('hi', hi), ('st', st))
        ]

    def _persist_opt(self):
        """Simpan nilai widget setelan Optimization ke cfg (tanpa memicu
        config_changed -> tidak ada loop refresh)."""
        try:
            c = self.state.cfg
            for key, kind, w in self._opt_widget_map():
                if kind == 'idx':
                    c[key] = int(w.currentIndex())
                elif kind == 'text':
                    c[key] = w.currentText()
                else:
                    c[key] = float(w.value())
            self.state.save_config()
        except Exception:
            pass

    def _restore_opt(self):
        """Pulihkan nilai widget setelan Optimization dari cfg (bila ada).
        blockSignals mencegah sinyal beruntun; tampilan disinkronkan setelahnya."""
        c = getattr(self.state, 'cfg', {}) or {}
        for key, kind, w in self._opt_widget_map():
            if key not in c:
                continue
            w.blockSignals(True)
            try:
                if kind == 'idx':
                    iv = int(c[key])
                    if 0 <= iv < w.count():
                        w.setCurrentIndex(iv)
                elif kind == 'text':
                    tv = str(c[key])
                    if w.findText(tv) >= 0:
                        w.setCurrentText(tv)
                else:
                    # QSpinBox butuh int, QDoubleSpinBox butuh float — pakai
                    # tipe nilai widget agar spin_day (int) tak menolak float.
                    w.setValue(type(w.value())(float(c[key])))
            except Exception:
                pass
            w.blockSignals(False)
        # sinkronkan tampilan sesuai mode & jumlah kombinasi terkini
        try:
            self._mode_changed(); self._pcs_changed(); self._update_count()
        except Exception:
            pass

    def _toggle_cfg_section(self):
        self._cfg_collapsed = not bool(getattr(self, '_cfg_collapsed', False))
        self._apply_cfg_collapsed()
        try:
            self.state.cfg['opt_cfg_collapsed'] = self._cfg_collapsed
            self.state.save_config()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _ranges(self):
        return (SweepRange(self.pv_lo.value(), self.pv_hi.value(), self.pv_st.value()),
                SweepRange(self.iv_lo.value(), self.iv_hi.value(), self.iv_st.value()),
                SweepRange(self.bs_lo.value(), self.bs_hi.value(), self.bs_st.value()))

    def _update_count(self):
        pv, iv, bs = self._ranges()
        n = len(pv.values()) * len(iv.values()) * len(bs.values())
        if self.mode.currentIndex() != 1:        # bukan Auto → ikut variabel ekstra
            for uk in self._active_extra_keys():
                n *= max(1, len(self._extra_values(uk)))
        self.n_lbl.setText(
            tr('{n} simulasi tahunan').format(n=f'{n:,}'))

    def _duration_hours(self):
        """Jam jendela simulasi terpilih (utk build_sim_arrays & anualisasi).
        'Setahun penuh' → 8760 (jendela penuh, tanpa ekstrapolasi). Berlaku
        SAMA utk semua sub-mode Advanced termasuk Firming — Durasi/Mulai
        sepenuhnya di tangan pengguna (lihat 'Firming Target Met (%)' pada
        _EXTRA_DISP: dihitung HANYA dari jendela yang benar-benar
        disimulasikan, bukan diekstrapolasi ke setahun)."""
        opts = getattr(self, '_dur_opts', None) or []
        i = self.cmb_dur.currentIndex() if hasattr(self, 'cmb_dur') else -1
        if 0 <= i < len(opts):
            return int(opts[i][1])
        return ivals.HOURS_YEAR

    def _start_h(self):
        """Jam MULAI jendela (dari awal data) menurut pilihan bulan/tanggal.
        build_sim_arrays membatasi otomatis agar jendela tetap di dalam data;
        untuk 'Setahun penuh' start efektif 0 (jendela penuh)."""
        if not hasattr(self, 'cmb_month'):
            return 0
        return int(ivals.month_day_to_hour(self.cmb_month.currentIndex() + 1,
                                           self.spin_day.value()))

    # -------- mode Advanced: deteksi & variabel yang dioptimasi --------
    def _adv_active(self) -> bool:
        """True bila mode BESS = Advanced (dari halaman Parameters/Dashboard)."""
        return str(self.state.cfg.get('bess_mode', 'Standard')
                   ).strip().lower().startswith('adv')

    def _pcs_hidden(self) -> bool:
        """PCS card disembunyikan utk Smoothing/Firming (dayanya dioptimasi)."""
        if not self._adv_active():
            return False
        c = self.state.cfg
        return bool(c.get('m_pv_smooth') or c.get('m_firming'))

    def _active_extra_keys(self):
        """ui_key variabel ekstra yang dioptimasi menurut sub-mode aktif.
        Urutan = urutan kolom grid (harus konsisten dgn engine).
        CATATAN: Target Power (Firming) TIDAK pernah dioptimasi/di-sweep —
        nilainya selalu diambil dari halaman Parameters ('firming_kw' pada
        base params); kolom hasil 'Target Power' tetap tampil (konstan,
        lihat _simulate_chunk mode-driven emission)."""
        if not self._adv_active():
            return []
        c = self.state.cfg
        sm = bool(c.get('m_pv_smooth')); fm = bool(c.get('m_firming'))
        rv = bool(c.get('m_reserve'))
        keys = []
        if sm:
            keys.append('window')
        if sm or fm:
            keys += ['maxchg', 'maxdhg']
        if rv:
            keys += ['rfrac', 'rkw']
        return keys

    def _extra_range(self, uk) -> SweepRange:
        box, lo, hi, st = self._adv_rng[uk]
        return SweepRange(lo.value(), hi.value(), st.value())

    def _extra_values(self, uk, scaled=False):
        vals = self._extra_range(uk).values()
        if scaled:
            vals = vals * float(self._EXTRA_PARAMS[uk]['scale'])
        return vals

    def _sync_adv_opt_ui(self):
        """Sembunyikan PCS card utk Smoothing/Firming; tampilkan kartu range
        variabel ekstra hanya bila Advanced + sub-mode aktif + mode Manual.
        Tata-letak DIRAPATKAN: hanya kotak aktif yang ditempatkan (tanpa sel
        kosong), mengisi lebar penuh dalam satu baris."""
        if not hasattr(self, '_adv_rng'):
            return
        if hasattr(self, '_pcs_box'):
            self._pcs_box.setVisible(not self._pcs_hidden())
        auto = self.mode.currentIndex() == 1
        active = self._active_extra_keys()
        show_card = bool(active) and not auto
        grid = self._adv_opt_grid
        # lepas semua kotak dari grid dulu, sembunyikan
        for uk, (box, *_rest) in self._adv_rng.items():
            grid.removeWidget(box)
            box.setVisible(False)
        # kolom lama: nol-kan stretch agar tak menyisakan ruang kosong
        for _c in range(max(1, grid.columnCount())):
            grid.setColumnStretch(_c, 0)
        if show_card:
            # satu baris, kolom = jumlah variabel aktif → mengisi lebar, tanpa gap
            for i, uk in enumerate(active):
                box = self._adv_rng[uk][0]
                grid.addWidget(box, 0, i)
                grid.setColumnStretch(i, 1)
                box.setVisible(True)
        if hasattr(self, '_adv_opt_box'):
            self._adv_opt_box.setVisible(show_card)
        self._update_count()

    def showEvent(self, e):
        # Saat halaman ditampilkan, mode mungkin baru diubah di Parameters →
        # segarkan tampilan variabel ekstra.
        try:
            self._sync_adv_opt_ui()
        except Exception:
            pass
        super().showEvent(e)

    def _on_constraint_change(self):
        """Simpan nilai kartu Optimization Constraints ke state.cfg."""
        self.state.update_cfg(self.cbox.values())

    def _refresh_constraints(self):
        """Sinkronkan kartu constraints bila cfg berubah (mis. muat proyek)."""
        box = getattr(self, 'cbox', None)
        if box is not None:
            box.set_values(self.state.cfg)

    def _constraints(self):
        c = self.state.cfg
        pick = lambda k: (c.get(k) or None) if (c.get(k) or 0) > 0 else None
        return dict(
            max_pv_excess_ratio=c.get('max_pv_excess_ratio')
                if c.get('max_pv_excess_ratio', 1.0) < 1.0 else None,
            min_renewable_fraction=pick('min_renewable_fraction'),
            max_lcoe=pick('max_lcoe'), max_capex=pick('max_capex'),
            max_diesel_fuel_l=pick('max_diesel_fuel_l'),
            target_pvbs_supply=pick('target_pvbs_supply'),
            target_diesel_reduction=pick('target_diesel_reduction'))

    def _run(self):
        if self.is_busy():          # cegah start ganda -> worker ter-orphan
            return
        st = self.state
        if not st.data_ready():
            QMessageBox.warning(self, tr('Data belum ada'),
                                tr('Import Load Profile dan PV ENetAC dahulu '
                                   'di halaman Data.'))
            return
        cfg = st.cfg
        base = opt_base_params(cfg)
        # PCS card hanya dipakai bila TIDAK disembunyikan (Smoothing/Firming
        # mengoptimasi daya PCS langsung → jangan override lewat _pcs_apply).
        if not self._pcs_hidden():
            base = self._pcs_apply(base)
        # DURASI simulasi per iterasi: ambil JENDELA jam (dari awal data) pada
        # basis 1 jam; KPI diekstrapolasi ke setahun (annualize). 'Setahun penuh'
        # → jendela penuh & annualize=1 (jalur lama, bit-identik).
        win_h = self._duration_hours()
        # Resolusi simulasi: mode Advanced memakai interval simulasi YANG SAMA
        # dgn Dashboard (cfg['sim_interval']) — SEBELUMNYA selalu dipaksa
        # '1 jam' di sini, sehingga bila data asli beresolusi lebih halus
        # (mis. 1 menit) nilainya dirata-ratakan ke per-jam SEBELUM disimulasi.
        # Ini menutupi kekurangan singkat (mis. BESS habis beberapa menit
        # menjelang firming window berakhir) sehingga "Firming Target Met (%)"
        # bisa melapor 100% meski "Terapkan Terbaik" di Dashboard (yang
        # memakai resolusi asli) menunjukkan target TAK tercapai. Mode
        # Standard TETAP '1 jam' apa adanya (tak disentuh, paritas
        # Excel/canon terjaga — lihat _t_canon_equiv.py).
        sim_lab = (str(cfg.get('sim_interval', '1 hour'))
                   if self._adv_active() else '1 hour')
        # 'DEG Status' per-jam (import Excel, halaman Data) diteruskan ke
        # Optimization sama seperti Dashboard/Run Simulation -- lihat
        # OptimizationEngine(deg_status=...) di bawah & _t_deg_status.py.
        L, P, G, dt_h, n, D = ivals.build_sim_arrays(
            st.load, st.pv_norm, st.grid_status, st.datetimes, sim_lab,
            start_h=self._start_h(), window_h=win_h, deg=st.deg_status)
        base['interval_h'] = dt_h
        base['annualize'] = ivals.annualization_factor_h(max(1e-9, n * dt_h))
        auto = self.mode.currentIndex() == 1
        extra_cols = None
        if auto:
            grid = None
        else:
            pv, iv, bs = self._ranges()
            grid = build_grid(pv, iv, bs)
            # mode Advanced: perluas grid dgn variabel ekstra yg dioptimasi
            active = self._active_extra_keys()
            if active:
                extras = [(self._EXTRA_PARAMS[uk]['engine'],
                           self._extra_values(uk, scaled=True)) for uk in active]
                extra_cols = [self._EXTRA_PARAMS[uk]['engine'] for uk in active]
                grid, _keys = build_grid_extra(grid, extras)
        engine = OptimizationEngine(L, P, G,
                                    base, cost_config(cfg), extra_cols=extra_cols,
                                    deg_status=D)
        self.worker = _Worker(engine, grid, self._objectives(),
                              self._constraints(),
                              tol=self.tol_spin.value() / 100.0, auto=auto,
                              dcac=float(self.auto_dcac.value()))
        self._register_worker(self.worker)
        # Progress bar berskala permil TETAP (0..1000) & MONOTON: konversi
        # (d,t) -> permil lalu hanya izinkan MAJU (tak pernah mundur, walau
        # mode Auto memberi (d,t) yang penyebutnya berubah antar-ronde). 100%
        # diset HANYA saat worker benar-benar selesai (_done/finished) sehingga
        # bar penuh = optimasi selesai (bukan sekadar satu ronde tuntas).
        self.pbar.setRange(0, 1000)
        self._pbar_permille = 0
        self.pbar.setValue(0)
        self.worker.progress.connect(self._opt_progress)
        self.worker.finished_ok.connect(self._done)
        self.worker.failed.connect(
            lambda m: QMessageBox.critical(self, tr('Error'), m))
        self.worker.finished.connect(lambda: (self.btn.setEnabled(True),
                                              self.btn_cancel.setEnabled(False)))
        self.btn.setEnabled(False); self.btn_cancel.setEnabled(True)
        self.worker.start()

    def _opt_progress(self, d, t):
        """Perbarui progress bar (permil 0..1000), MONOTON NAIK & <100% hingga
        benar-benar selesai (100% diset di sinyal finished)."""
        try:
            pm = int(1000 * float(d) / max(float(t), 1.0))
        except Exception:
            pm = self._pbar_permille
        pm = max(0, min(999, pm))            # sisakan 100% utk sinyal selesai
        if pm > self._pbar_permille:         # hanya maju
            self._pbar_permille = pm
            self.pbar.setValue(pm)

    # ------------------------------------------------------------------
    def _register_worker(self, w):
        """Simpan referensi worker agar tak di-GC selama berjalan (mencegah
        'QThread destroyed while running' -> Fatal error: Aborted / force close)."""
        lst = getattr(self, '_live_workers', None)
        if lst is None:
            lst = self._live_workers = []
        self._live_workers = [x for x in lst
                              if x is not None and x.isRunning()]
        self._live_workers.append(w)

    def _all_workers(self):
        ws = list(getattr(self, '_live_workers', []) or [])
        for name in ('worker', 'bworker'):
            w = getattr(self, name, None)
            if w is not None and w not in ws:
                ws.append(w)
        return ws

    def stop_workers(self):
        """Hentikan SEMUA pekerjaan latar (termasuk yang sempat ter-orphan)
        sebelum halaman dibongkar agar sinyal tidak dikirim ke widget yang sudah
        dihapus dan tidak terjadi abort()."""
        ws = self._all_workers()
        for w in ws:
            try:
                if hasattr(w, 'cancel_flag'):
                    w.cancel_flag.set()
                w.blockSignals(True)
            except Exception:
                pass
        for w in ws:
            try:
                if w.isRunning() and not w.wait(6000):
                    w.terminate()          # upaya terakhir: cegah abort()
                    w.wait(2000)
            except Exception:
                pass

    def is_busy(self) -> bool:
        for w in self._all_workers():
            try:
                if w is not None and w.isRunning():
                    return True
            except Exception:
                pass
        return False

    def _toggle_batch(self, on):
        self.batch_box.setVisible(bool(on))

    # ---- koordinat PV per site (unduh PVGIS) --------------------------------
    def _coord_persite(self) -> bool:
        return bool(getattr(self, 'rb_coord_site', None)
                    and self.rb_coord_site.isChecked())

    def _on_coord_mode(self, checked=False):
        # QButtonGroup mengirim toggled(False) utk tombol lama & toggled(True)
        # utk tombol baru; tanggapi hanya yang True agar cfg ditulis sekali.
        if not checked:
            return
        self.state.cfg['batch_coord_mode'] = (
            'persite' if self._coord_persite() else 'home')
        self.state.db.save_project(self.state.cfg)
        self._sync_coord_ui()

    def _sync_coord_ui(self):
        on = self._coord_persite()
        for w in (self.btn_coord_file, self.btn_coord_tmpl):
            w.setEnabled(on)
        if not on:
            self.lbl_coord.setText(tr(
                'PV ENetAC diambil dari tiap berkas data (halaman Data).'))
            return
        if self._batch_coords:
            names = ', '.join(c[0] for c in self._batch_coords[:8])
            more = '' if len(self._batch_coords) <= 8 else ' …'
            self.lbl_coord.setText(
                tr('{n} koordinat dimuat:').format(n=len(self._batch_coords))
                + f' {names}{more}')
        else:
            self.lbl_coord.setText(tr(
                'Pilih berkas Excel koordinat (kolom Site, Latitude, '
                'Longitude).'))

    def _pick_coords(self):
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
        self._batch_coords = coords
        self.state.cfg['batch_coords_path'] = path
        self.state.db.save_project(self.state.cfg)
        self._sync_coord_ui()

    def _coords_template(self):
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

    def _pick_batch(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr('Pilih Berkas Data'), '',
            'Data (*.xlsx *.xls *.csv);;' + tr('Semua berkas (*)'))
        if not paths:
            return
        self.batch_paths = list(paths)
        self.state.batch_paths = list(paths)
        names = ', '.join(os.path.splitext(os.path.basename(p))[0]
                          for p in paths)
        self.lbl_batch.setText(
            tr('{n} berkas dipilih:').format(n=len(paths)) + f' {names}')
        self.btn_batch.setEnabled(True)

    def _run_batch(self):
        if getattr(self, '_batch_reading', False):
            return
        if self.is_busy():          # cegah start ganda -> worker ter-orphan
            return
        if not self.batch_paths:
            return
        cfg = self.state.cfg
        base = opt_base_params(cfg)
        if not self._pcs_hidden():           # Smoothing/Firming → PCS dioptimasi
            base = self._pcs_apply(base)
        win_h = self._duration_hours()       # durasi per iterasi (anualisasi)
        start_h = self._start_h()            # titik mulai jendela (bulan/tanggal)
        auto = self.mode.currentIndex() == 1
        grid = None
        if not auto:
            pv, iv, bs = self._ranges()
            grid = build_grid(pv, iv, bs)

        # --- BACA SEMUA BERKAS DI THREAD UTAMA --------------------------------
        # pandas/openpyxl/lxml tidak aman dipanggil dari QThread di Windows
        # ('access violation'). Baca di sini; worker hanya mengoptimasi.
        self.btn_batch.setEnabled(False)
        self.btn_batch_cancel.setEnabled(True)
        self._batch_reading = True
        loaded, read_errors = [], []
        try:
            n = len(self.batch_paths)
            self.pbar.setMaximum(n)
            self.pbar.setValue(0)
            for i, path in enumerate(self.batch_paths):
                if getattr(self, '_batch_cancel_read', False):
                    break
                site = os.path.splitext(os.path.basename(path))[0]
                self.lbl_batch.setText(
                    tr('Membaca berkas {i}/{n}: {site} …').format(
                        i=i + 1, n=n, site=site))
                self.pbar.setValue(i)
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
            self._batch_reading = False
            self._batch_cancel_read = False

        if not loaded:
            self.btn_batch.setEnabled(True)
            self.btn_batch_cancel.setEnabled(False)
            self._fill_batch([], read_errors)
            return

        # --- Koordinat per-site: unduh PV dari PVGIS (thread utama) -----------
        if self._coord_persite():
            if not self._batch_coords:
                self.btn_batch.setEnabled(True)
                self.btn_batch_cancel.setEnabled(False)
                QMessageBox.warning(
                    self, tr('Koordinat PV'),
                    tr('Pilih berkas Excel koordinat lebih dulu, atau ganti '
                       'ke "Ikuti halaman Home".'))
                return
            self.lbl_batch.setText(tr('Mengunduh PV dari PVGIS per site …'))
            self.pbar.setMaximum(len(loaded))
            self.pbar.setValue(0)

            def _pvprog(i, total, site):
                self.pbar.setValue(i)
                self.lbl_batch.setText(
                    tr('Unduh PVGIS {i}/{n}: {site} …').format(
                        i=i + 1, n=total, site=site))
                QApplication.processEvents()

            try:
                loaded, pv_errors = batch_pvgis_pv(
                    loaded, self._batch_coords, dict(cfg), progress=_pvprog)
            except Exception as e:
                self.btn_batch.setEnabled(True)
                self.btn_batch_cancel.setEnabled(False)
                QMessageBox.critical(self, tr('Error'), str(e))
                return
            read_errors.extend(pv_errors)

        self.bworker = _BatchWorker(
            loaded, dict(cfg), base, cost_config(cfg), grid,
            self._objectives(), self._constraints(),
            self.tol_spin.value() / 100.0, auto,
            float(self.auto_dcac.value()), fallback_pv=self.state.pv_norm,
            read_errors=read_errors, win_h=win_h, start_h=start_h)
        self._register_worker(self.bworker)
        self.bworker.progress.connect(self._batch_progress)
        self.bworker.finished_ok.connect(self._batch_done)
        self.bworker.failed.connect(
            lambda m: (QMessageBox.critical(self, tr('Error'), m),
                       self.btn_batch.setEnabled(True)))
        self.bworker.finished.connect(
            lambda: (self.btn_batch.setEnabled(True),
                     self.btn_cancel.setEnabled(False),
                     self.btn_batch_cancel.setEnabled(False)))
        self.btn_batch.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_batch_cancel.setEnabled(True)
        self.pbar.setMaximum(len(loaded))
        self.pbar.setValue(0)
        self.bworker.start()

    def _cancel_batch(self):
        self._batch_cancel_read = True     # hentikan fase baca (thread utama)
        w = getattr(self, 'bworker', None)
        if w is not None and w.isRunning():
            w.cancel_flag.set()
        self.btn_batch_cancel.setEnabled(False)
        self.lbl_batch.setText(tr('Membatalkan batch …'))

    def _batch_progress(self, i, total, site):
        self.pbar.setMaximum(total)
        self.pbar.setValue(i)
        self.lbl_batch.setText(
            tr('Menjalankan {i}/{n}: {site} …').format(i=i + 1, n=total,
                                                       site=site))

    def _batch_done(self, rows):
        try:
            self._fill_batch(rows)
        except Exception as e:                      # pragma: no cover
            QMessageBox.critical(self, tr('Error'), str(e))

    def _fill_batch(self, rows, errors=None):
        self.batch_rows = rows
        self.state.batch_rows = rows
        self.pbar.setValue(self.pbar.maximum())
        errs = (errors if errors is not None
                else getattr(getattr(self, 'bworker', None), 'errors', []) or [])
        if not rows:
            if errs:
                detail = '\n'.join(f'• {s}: {m}' for s, m in errs)
                self.lbl_batch.setText(
                    tr('Semua site gagal dioptimasi.'))
                QMessageBox.warning(
                    self, tr('Batch selesai dengan galat'),
                    tr('Semua site gagal dioptimasi.') + '\n\n' + detail)
            else:
                self.lbl_batch.setText(tr('Batch dibatalkan.'))
            return
        self.btn_batch_export.setEnabled(True)
        self.btn_apply_site.setEnabled(True)
        self.site_combo.blockSignals(True)
        self.site_combo.clear()
        self.site_combo.addItems([r['site'] for r in rows])
        self.site_combo.blockSignals(False)
        note = (' · ' + tr('{n} site gagal (dilewati)').format(n=len(errs))
                if errs else '')
        self.lbl_batch.setText(
            tr('Selesai — {n} site dioptimasi.').format(n=len(rows)) + note)
        if errs:
            detail = '\n'.join(f'• {s}: {m}' for s, m in errs)
            QMessageBox.warning(
                self, tr('Sebagian site gagal'),
                tr('{n} site dilewati karena galat:').format(n=len(errs))
                + '\n\n' + detail)
        t = self.btable
        t.blockSignals(True)        # cegah sinyal seleksi saat diisi
        t.setRowCount(len(rows))
        for r, item in enumerate(rows):
            res = item['res']
            best = res['rank_order'][0]
            for c, (key, _lbl) in enumerate(self.BCOLS):
                if key == 'site':
                    cell = QTableWidgetItem(item['site'])
                    cell.setToolTip(item['path'])
                    t.setItem(r, c, cell)
                    continue
                if key not in res:
                    continue
                v = float(np.asarray(res[key]).reshape(-1)[best])
                if key in ('renewable_fraction', 'pv_excess_ratio'):
                    txt = f'{v * 100:,.1f}'
                else:
                    txt = f'{v:,.{self.COL_DEC.get(key, 2)}f}'
                cell = QTableWidgetItem(txt)
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, cell)
        t.blockSignals(False)
        fit_table_columns(t, min_w=92, max_w=220)

    def _clear_results(self):
        """Hapus hasil optimasi (site tunggal) & kosongkan tabelnya."""
        if self.is_busy():
            QMessageBox.information(
                self, tr('Sedang berjalan'),
                tr('Hentikan proses yang sedang berjalan terlebih dahulu.'))
            return
        if getattr(self, 'res', None) is None:
            return
        if QMessageBox.question(
                self, tr('Bersihkan Hasil'),
                tr('Hapus hasil optimasi?')) != QMessageBox.Yes:
            return
        self.res = None
        self.state.last_opt = None
        self.table.clearContents()
        self.table.setRowCount(0)
        # kembalikan kolom ke dasar tersaring (tanpa DC/AC; buang kolom
        # variabel Advanced bila ada)
        base = self._visible_base_cols(None)
        self.table.setColumnCount(len(base))
        self.table.setHorizontalHeaderLabels(
            ['\n'.join(tr(part) for part in c[1].split('\n'))
             for c in base])
        self.lbl_best.setText('')
        self.pbar.setValue(0)
        for b in (self.btn_apply, self.btn_export, self.btn_clear):
            b.setEnabled(False)

    def _clear_batch(self):
        """Kosongkan daftar berkas & seluruh hasil batch."""
        if self.is_busy():
            QMessageBox.information(
                self, tr('Sedang berjalan'),
                tr('Hentikan proses yang sedang berjalan terlebih dahulu.'))
            return
        if self.batch_rows or self.batch_paths:
            if QMessageBox.question(
                    self, tr('Bersihkan Batch'),
                    tr('Hapus daftar berkas dan seluruh hasil batch?')) \
                    != QMessageBox.Yes:
                return
        self.batch_paths, self.batch_rows = [], []
        self.state.batch_paths, self.state.batch_rows = [], []
        self.btable.blockSignals(True)
        self.btable.clearContents()
        self.btable.setRowCount(0)
        self.btable.blockSignals(False)
        self.site_combo.blockSignals(True)
        self.site_combo.clear()
        self.site_combo.blockSignals(False)
        self.btn_batch.setEnabled(False)
        self.btn_batch_export.setEnabled(False)
        self.btn_apply_site.setEnabled(False)
        self.pbar.setValue(0)
        self.lbl_batch.setText(tr('Belum ada berkas dipilih.'))

    def _sync_site_combo(self):
        rows = self.btable.selectionModel().selectedRows() \
            if self.btable.selectionModel() else []
        if rows and 0 <= rows[0].row() < self.site_combo.count():
            self.site_combo.setCurrentIndex(rows[0].row())

    def _site_coords(self, site):
        """Koordinat (lat, lon) site dari berkas koordinat yang dimuat, cocok
        via NAMA (case-insensitive). None bila tak ditemukan."""
        key = str(site).strip().lower()
        for nm, la, lo in (getattr(self, '_batch_coords', None) or []):
            if str(nm).strip().lower() == key:
                return float(la), float(lo)
        return None

    def _apply_site(self):
        """Terapkan sizing terbaik site terpilih + muat berkas datanya."""
        i = self.site_combo.currentIndex()
        if not self.batch_rows or not (0 <= i < len(self.batch_rows)):
            return
        item = self.batch_rows[i]
        res = item['res']
        best = res['rank_order'][0]
        bess = float(res['kwh_bess'][best])
        pcs = res.get('pcs_kw')
        if pcs is not None:
            pcs = float(np.asarray(pcs).reshape(-1)[best])
        else:
            cfg = self.state.cfg
            pcs = bess * cfg['max_charge_kw'] / max(cfg['bess_kwh'], 1e-9)

        # --- muat profil data site tersebut agar konsisten dengan sizing ---
        loaded, warn = False, ''
        path = item.get('path', '')
        if path and os.path.exists(path):
            try:
                d = read_profile_file(path)
                n = len(d['load']) if d.get('load') is not None else 0
                pv = d.get('pv')
                if pv is None:
                    pv = self.state.pv_norm
                gs = d.get('grid')
                if gs is None:
                    gs = (np.ones(n) if self.state.cfg.get('grid_enabled', True)
                          else np.zeros(n))
                self.state.set_profiles(d.get('datetimes'), d['load'], pv, gs)
                loaded = True
            except (ImportError_, Exception) as e:
                warn = str(e)
        elif path:
            warn = tr('Berkas data tidak ditemukan:') + f' {path}'

        # hasil simulasi lama tidak lagi relevan dengan data & sizing baru
        self.state.last_result = None
        self.state.multi_result = None
        upd = dict(
            site_name=item['site'],
            pv_kwp=float(res['kwp'][best]),
            pv_inv_kw=float(res['kw_inv'][best]),
            bess_kwh=bess, max_charge_kw=pcs, max_discharge_kw=pcs)
        co = self._site_coords(item['site'])          # koordinat site (bila ada)
        if co is not None:
            upd['latitude'] = round(co[0], 6)
            upd['longitude'] = round(co[1], 6)
        self.state.update_cfg(upd)
        msg = tr('Sizing terbaik site {site} disalin ke Parameters:').format(
            site=item['site'])
        msg += (f"\n  PV {res['kwp'][best]:,.2f} kWp · INV "
                f"{res['kw_inv'][best]:,.2f} kW · BESS {bess:,.0f} kWh · "
                f"PCS {pcs:,.2f} kW")
        if co is not None:
            msg += '\n' + tr('Site Name & koordinat ({la:.5f}, {lo:.5f}) '
                             'disalin ke halaman Home.').format(la=co[0],
                                                                lo=co[1])
        else:
            msg += '\n' + tr('Site Name disalin ke halaman Home.')
        msg += '\n' + (tr('Profil data site ini ikut dimuat.') if loaded
                       else tr('Profil data TIDAK dimuat.'))
        if warn:
            msg += f'\n{warn}'
        QMessageBox.information(self, tr('Diterapkan'), msg)

    def _export_batch(self):
        if not self.batch_rows:
            return
        cfg = dict(self.state.cfg)
        name = export_filename(
            cfg, tr('hasil_optimasi_batch'),
            include_caps=False).replace(
                '.xlsx', f'_{len(self.batch_rows)}site.xlsx')
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Export Batch'), name, 'Excel (*.xlsx);;CSV (*.csv)')
        if not path:
            return
        try:
            export_batch_optimization(path, self.batch_rows, cfg=cfg)
            QMessageBox.information(self, tr('Sukses'),
                                    tr('Tersimpan:') + f'\n{path}')
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))

    def _mode_changed(self):
        auto = self.mode.currentIndex() == 1
        for b in self._range_boxes:
            b.setVisible(not auto)
        self.auto_dcac.setVisible(auto)
        self.lbl_dcac.setVisible(auto)
        if auto:
            self.n_lbl.setText(tr('otomatis (iteratif)'))
        else:
            self._update_count()
        # tampilkan/sembunyikan kartu variabel ekstra sesuai mode sizing
        self._sync_adv_opt_ui()

    def _pcs_changed(self):
        m = self.pcs_mode.currentIndex()
        cfg = self.state.cfg
        crate = cfg['max_charge_kw'] / max(cfg['bess_kwh'], 1e-9)
        show = m > 0
        try:
            self._pcs_form.setRowVisible(self.pcs_val, show)
        except Exception:
            self.pcs_val.setVisible(show)
            self._pcs_val_label.setVisible(show)
        if m == 0:
            self.pcs_info.setText(
                tr('Daya charge/discharge tiap kandidat = kapasitas BESS '
                   '\u00d7 C-rate Parameters ({c} 1/jam), yaitu {p} kW pada '
                   '{e} kWh.').format(
                    c=f'{crate:.3f}', p=f'{cfg["max_charge_kw"]:,.1f}',
                    e=f'{cfg["bess_kwh"]:,.1f}'))
        elif m == 1:
            self.pcs_info.setText(tr('Daya PCS = kapasitas BESS \u00d7 C-rate '
                                     'ini (mis. 0,5 = 2 jam penuh).'))
        else:
            self.pcs_info.setText(tr('Daya PCS tetap (kW) untuk semua '
                                     'kandidat, tidak ikut membesar dengan '
                                     'kapasitas BESS.'))

    def _pcs_apply(self, base: dict) -> dict:
        m = self.pcs_mode.currentIndex()
        if m == 1:
            base['bess_c_rate'] = float(self.pcs_val.value())
        elif m == 2:
            kw = float(self.pcs_val.value())
            base['bess_c_rate'] = 1e9
            base['max_charge_cap'] = kw
            base['max_discharge_cap'] = kw
        return base

    def _objectives(self):
        objs = [self.obj1.currentText()]
        for cb in (self.obj2, self.obj3):
            t = cb.currentText()
            if t != self._OBJ_NONE and t not in objs:
                objs.append(t)
        return objs

    def _cancel(self):
        w = getattr(self, 'bworker', None)
        if w is not None and w.isRunning():
            w.cancel_flag.set()
        if self.worker:
            self.worker.cancel_flag.set()

    def _done(self, res):
        # Optimasi SELESAI (bukan dibatalkan) -> progress penuh 100%.
        try:
            self.pbar.setValue(self.pbar.maximum())
        except Exception:
            pass
        self.res = res
        self.state.last_opt = res
        try:
            self.state.db.save_opt(' > '.join(self._objectives()),
                                   {k: v for k, v in res.items()})
        except Exception:
            pass
        self._apply_result(res)

    def _visible_base_cols(self, res=None):
        """Kolom dasar tabel setelah penyaringan:
        * DC/AC SELALU dihapus (req pengguna).
        * PCS (kW) dihapus utk Smoothing/Firming (daya PCS diganti kolom
          Max BESS Charge & Max BESS Discharge yang dioptimasi terpisah)."""
        drop = {'dc_ac_ratio'}
        if res is not None and 'opt_max_charge' in res:
            drop.add('pcs_kw')
        return [c for c in self.COLS if c[0] not in drop]

    def _apply_result(self, res):
        """Isi tabel & ringkasan (dipakai juga saat halaman dibangun ulang,
        mis. setelah ganti bahasa)."""
        self.res = res
        # Kolom dinamis: dasar (tersaring) + kolom variabel mode Advanced yg
        # dioptimasi (hanya yang benar-benar ada pada hasil).
        extra_present = [k for k in self._EXTRA_DISP_ORDER if k in res]
        cols = self._visible_base_cols(res) + [(k, self._EXTRA_DISP[k][0])
                                               for k in extra_present]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(
            ['\n'.join(tr(part) for part in c[1].split('\n')) for c in cols])
        order = res['rank_order'][:200]
        self.table.setRowCount(len(order))
        for r, idx in enumerate(order):
            for c, (key, _) in enumerate(cols):
                v = float(res[key][idx])
                if key in ('renewable_fraction', 'pv_excess_ratio'):
                    txt = f'{v * 100:,.1f}'
                elif key in self._EXTRA_DISP:
                    _hdr, _dec, _sc = self._EXTRA_DISP[key]
                    txt = f'{v * _sc:,.{_dec}f}'
                else:
                    txt = f'{v:,.{self.COL_DEC.get(key, 2)}f}'
                it = QTableWidgetItem(txt)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if not res['feasible'][idx]:
                    it.setForeground(Qt.gray)
                self.table.setItem(r, c, it)
        fit_table_columns(self.table, min_w=92, max_w=200)
        best = res['rank_order'][0]
        feas = int(res['feasible'].sum())
        self.lbl_best.setText(
            tr('Terbaik:') + f' PV {res["kwp"][best]:,.0f} kWp · INV '
            f'{res["kw_inv"][best]:,.0f} kW · BESS {res["kwh_bess"][best]:,.0f} '
            f'kWh — feasible {feas:,}/{len(res["kwp"]):,}'
            + (' · ' + tr('Auto: {n} evaluasi dalam {r} ronde').format(
                n=f'{res["auto_evaluated"]:,}', r=res['auto_rounds'])
               if 'auto_evaluated' in res
               else ''))
        self.btn_apply.setEnabled(True); self.btn_export.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.state.optimization_done.emit(res)

    def _apply_best(self):
        best = self.res['rank_order'][0]
        bess = float(self.res['kwh_bess'][best])
        # daya PCS kandidat terbaik ikut diterapkan; bila kolom tak ada
        # (hasil lama), hitung ulang dari mode PCS yang dipilih
        pcs = self.res.get('pcs_kw')
        if pcs is not None:
            pcs = float(np.asarray(pcs).reshape(-1)[best])
        else:
            cfg = self.state.cfg
            crate = cfg['max_charge_kw'] / max(cfg['bess_kwh'], 1e-9)
            pcs = bess * crate
        upd = dict(
            pv_kwp=float(self.res['kwp'][best]),
            pv_inv_kw=float(self.res['kw_inv'][best]),
            bess_kwh=bess,
            max_charge_kw=pcs, max_discharge_kw=pcs)
        # Variabel mode Advanced yg dioptimasi → salin nilai kandidat terbaik
        # ke Parameters (reserve_frac disimpan dlm %; window sbg bilangan bulat).
        _amap = {'opt_smoothing_window': ('smoothing_window', 1.0),
                 'opt_firming_kw': ('firming_kw', 1.0),
                 'opt_max_charge': ('max_charge_kw', 1.0),
                 'opt_max_discharge': ('max_discharge_kw', 1.0),
                 'opt_reserve_frac': ('reserve_frac', 100.0),
                 'opt_reserve_kw': ('reserve_kw', 1.0)}
        for dk, (ck, sc) in _amap.items():
            if dk in self.res:
                val = float(np.asarray(self.res[dk]).reshape(-1)[best]) * sc
                upd[ck] = int(round(val)) if ck == 'smoothing_window' else val
        self.state.update_cfg(upd)
        QMessageBox.information(
            self, tr('Diterapkan'),
            tr('Sizing terbaik disalin ke halaman Parameters. Jalankan '
               'simulasi di Dashboard untuk detail.'))

    def _export(self):
        b = self.res['rank_order'][0]
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Export hasil optimasi'),
            export_filename(self.state.cfg, tr('hasil_optimasi'),
                            pv_kwp=float(self.res['kwp'][b]),
                            bess_kwh=float(self.res['kwh_bess'][b])),
            'Excel (*.xlsx);;CSV (*.csv)')
        if path:
            export_optimization(path, self.res, cfg=dict(self.state.cfg))
