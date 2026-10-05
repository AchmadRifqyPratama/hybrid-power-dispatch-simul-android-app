"""AppState — state bersama antar halaman (config, profil data, hasil)."""
from __future__ import annotations
import os
import numpy as np
from PySide6.QtCore import QObject, Signal

from ..config.parameters import defaults, load_config, save_config
from ..data.database import ProjectDB

APPDIR = os.path.join(os.path.expanduser('~'), '.hpp_studio')
CFG_PATH = os.path.join(APPDIR, 'config.json')
DB_PATH = os.path.join(APPDIR, 'project.db')


class AppState(QObject):
    profiles_changed = Signal()
    config_changed = Signal()
    simulation_done = Signal(dict)
    optimization_done = Signal(dict)
    results_cleared = Signal(str)      # 'simulation' | 'multiyear' | ...

    def __init__(self):
        super().__init__()
        os.makedirs(APPDIR, exist_ok=True)
        self.cfg: dict = load_config(CFG_PATH)
        self.db = ProjectDB(DB_PATH)
        saved = self.db.load_project()
        if saved:
            base = defaults(); base.update({k: v for k, v in saved.items()
                                            if not k.startswith('_')})
            self.cfg = base
            self.created = saved.get('_created', '')
        else:
            self.created = ''
        self.datetimes = None
        self.load = None
        self.pv_norm = None
        self.grid_status = None
        # DEG Status per-jam (opsional, import Excel): None = tak diimpor
        # (dispatch mengabaikannya sepenuhnya -- byte-identik lama). Kode
        # numerik lihat app.data.importer (DEG_STATUS_OFF/ON/AUTO).
        self.deg_status = None
        # Dua sumber PV ENetAC yang dapat dipilih di halaman Data:
        #   pv_excel : profil PV dari file input Excel
        #   pv_pvgis : profil PV hasil unduhan PVGIS
        # pv_norm = yang sedang aktif (dipilih lewat cfg['pv_source']).
        self.pv_excel = None
        self.pv_pvgis = None
        self.last_result: dict | None = None
        self.last_opt: dict | None = None
        self.multi_result: dict | None = None
        self.batch_rows: list = []        # hasil Batch Multi-Site (Optimization)
        self.my_batch_rows: list = []     # hasil Batch Multi-Site (Multi-Year)
        self.my_batch_paths: list = []
        self.myb_col_order: list = []     # urutan kolom site pd tabel pivot
        self.my_batch_sizing: list = []   # input sizing per-site (disimpan .hpps)
        self.myb_base_mode: str = 'pv'    # mode Base Profile Plant
        self.myb_base_custom = None       # nilai Base 'Nilai lain'
        self.project_path: str | None = None   # berkas .hpps aktif
        # Mode Case Analysis (Dashboard) — bertahan lintas ganti bahasa
        # (UI dibangun ulang, tetapi objek state berumur panjang).
        self.case_mode: bool = False
        self.case_enabled: dict = {}      # nomor case -> tampil/tidak
        self._restore_profiles()

    def _restore_profiles(self):
        dts, load = self.db.load_profile('load')
        _, pv = self.db.load_profile('pv')
        _, grid = self.db.load_profile('grid')
        _, deg = self.db.load_profile('deg_status')
        if load is not None and pv is not None and len(load) == len(pv):
            import pandas as pd
            self.load, self.pv_norm = load, pv
            self.grid_status = grid if grid is not None and len(grid) == len(load) \
                else np.ones(len(load))
            self.deg_status = deg if deg is not None and len(deg) == len(load) \
                else None
            self.datetimes = pd.DatetimeIndex(dts) if dts else \
                pd.date_range('2025-01-01', periods=len(load), freq='h')
        # Dua sumber PV (bila pernah disimpan) — untuk pilihan di halaman Data.
        _, pvx = self.db.load_profile('pv_excel')
        _, pvg = self.db.load_profile('pv_pvgis')
        self.pv_excel = pvx if pvx is not None else None
        self.pv_pvgis = pvg if pvg is not None else None

    def data_ready(self) -> bool:
        return self.load is not None and self.pv_norm is not None

    def set_profiles(self, datetimes, load=None, pv=None, grid=None, deg=None):
        import pandas as pd
        n = len(load if load is not None else
                pv if pv is not None else grid if grid is not None else deg)
        # SELALU pakai timestamp baru bila tersedia (jangan pertahankan datetimes
        # lama walau panjangnya sama — kalau tidak, re-import data resolusi beda
        # dgn jumlah baris sama akan salah dideteksi intervalnya). Tanpa
        # timestamp, jaga yang lama bila cocok, selain itu default per jam.
        if datetimes is not None:
            self.datetimes = pd.DatetimeIndex(datetimes)
        elif self.datetimes is None or len(self.datetimes) != n:
            self.datetimes = pd.date_range('2025-01-01', periods=n, freq='h')
        if load is not None:
            self.load = np.asarray(load, float)
            self.db.save_profile('load', self.datetimes, self.load)
        if pv is not None:
            self.pv_norm = np.asarray(pv, float)
            self.db.save_profile('pv', self.datetimes, self.pv_norm)
        if grid is not None:
            self.grid_status = np.asarray(grid, float)
            self.db.save_profile('grid', self.datetimes, self.grid_status)
        if self.grid_status is None and self.load is not None:
            self.grid_status = np.ones(len(self.load))
        if deg is not None:
            self.deg_status = np.asarray(deg, float)
            self.db.save_profile('deg_status', self.datetimes, self.deg_status)
        elif load is not None or pv is not None or grid is not None:
            # Re-import Load/PV/Grid tanpa kolom DEG Status baru -> DEG Status
            # LAMA (bila ada & panjangnya masih cocok) tetap dipertahankan;
            # kalau tak cocok lagi (mis. jumlah baris berubah), dianggap tak
            # ada lagi (None -> dispatch mengabaikannya, aman/byte-identik).
            if self.deg_status is not None and len(self.deg_status) != n:
                self.deg_status = None
                self.db.delete_profile('deg_status')
        self.profiles_changed.emit()

    # ----------------------------- sumber PV ENetAC -----------------------
    def set_pv_excel(self, pv):
        """Simpan profil PV dari file input Excel (untuk opsi di halaman Data)."""
        self.pv_excel = np.asarray(pv, float) if pv is not None else None
        if self.pv_excel is not None:
            self.db.save_profile('pv_excel', self.datetimes, self.pv_excel)
        else:
            self.db.delete_profile('pv_excel')

    def set_pv_pvgis(self, pv):
        """Simpan profil PV hasil unduhan PVGIS (untuk opsi di halaman Data)."""
        self.pv_pvgis = np.asarray(pv, float) if pv is not None else None
        if self.pv_pvgis is not None:
            self.db.save_profile('pv_pvgis', self.datetimes, self.pv_pvgis)
        else:
            self.db.delete_profile('pv_pvgis')

    def pv_source(self) -> str:
        return 'pvgis' if self.cfg.get('pv_source') == 'pvgis' else 'excel'

    def remember_pv_source(self, src: str):
        """Catat pilihan sumber PV ke config (tanpa mengubah profil aktif)."""
        self.cfg['pv_source'] = 'pvgis' if src == 'pvgis' else 'excel'
        save_config(CFG_PATH, self.cfg)
        self.db.save_project(self.cfg)

    @staticmethod
    def _align_weekday(arr, from_year, to_year):
        """Geser deret per-jam agar hari-dalam-minggu selaras dengan tahun
        tujuan: mis. Senin pekan-1 tahun A dipetakan ke Senin pekan-1 tahun B.
        Memakai pergeseran melingkar sebesar selisih hari-dalam-minggu 1 Jan
        (dipilih minimal, −3..3 hari) sehingga REVERSIBEL."""
        import pandas as pd
        a = np.asarray(arr, float)
        try:
            fy, ty = int(from_year), int(to_year)
        except (TypeError, ValueError):
            return a
        if fy == ty or a.size == 0:
            return a
        try:
            wf = pd.Timestamp(f'{fy}-01-01').weekday()
            wt = pd.Timestamp(f'{ty}-01-01').weekday()
        except Exception:
            return a
        delta = (wt - wf) % 7
        if delta > 3:
            delta -= 7                     # |pergeseran| minimal (−3..3 hari)
        return np.roll(a, -delta * 24)

    def _year_of(self):
        try:
            return int(self.datetimes[0].year)
        except Exception:
            return None

    def use_pv_source(self, src: str) -> bool:
        """Aktifkan sumber PV (excel|pvgis). Bila tahun data berubah, Load &
        Grid digeser (selaras hari-dalam-minggu) ke tahun target dan tahun
        simulasi ikut menyesuaikan. Kembalikan False bila sumber belum ada."""
        import pandas as pd
        want = 'pvgis' if src == 'pvgis' else 'excel'
        pv = self.pv_pvgis if want == 'pvgis' else self.pv_excel
        if pv is None:
            return False
        pv = np.asarray(pv, float)
        n = int(pv.shape[0])
        if want == 'pvgis':
            target = int(self.cfg.get('pvgis_year') or self._year_of() or 2025)
        else:
            target = int(self.cfg.get('excel_year')
                         or self.cfg.get('simulation_year') or 2025)
        cur = self._year_of()
        load, grid = self.load, self.grid_status
        if (load is not None and len(load) == n and cur and cur != target):
            load = self._align_weekday(load, cur, target)
        if (grid is not None and len(grid) == n and cur and cur != target):
            grid = self._align_weekday(grid, cur, target)
        dts = pd.date_range(f'{target}-01-01', periods=n, freq='h')
        # PENTING: perbarui cfg SEBELUM set_profiles(). set_profiles memancarkan
        # profiles_changed yang memicu _sync_pv_source di halaman Data; bila
        # cfg['pv_source'] belum diperbarui, radio akan disetel balik ke sumber
        # lama sehingga tampak butuh dua klik.
        self.cfg['pv_source'] = want
        self.cfg['simulation_year'] = target
        save_config(CFG_PATH, self.cfg)
        self.db.save_project(self.cfg)
        self.datetimes = None
        self.set_profiles(dts, load=load, pv=pv, grid=grid)
        self.config_changed.emit()
        return True

    def apply_pv_source(self, src: str) -> bool:      # kompatibilitas nama lama
        return self.use_pv_source(src)

    def save_config(self):
        try:
            from ..config.parameters import save_config
            save_config(CFG_PATH, self.cfg)
        except Exception:
            pass

    def update_cfg(self, values: dict):
        self.cfg.update(values)
        save_config(CFG_PATH, self.cfg)
        self.db.save_project(self.cfg)
        self.config_changed.emit()
