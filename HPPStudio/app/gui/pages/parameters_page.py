"""Halaman Parameters — seluruh grup parameter, otomatis dari SCHEMA."""
from __future__ import annotations

from ...config.i18n import tr
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QScrollArea, QPushButton, QGridLayout,
                               QMessageBox)

from ...config.parameters import (SCHEMA, defaults, VISIBILITY,
                                  load_priority_choices,
                                  load_priority_base_choices,
                                  load_priority_off_choices,
                                  load_priority_offgrid_choices,
                                  load_priority_label,
                                  load_priority_off_label,
                                  load_priority_help)
from ..widgets import ParamGroupBox


class ParametersPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        t = QLabel(tr('Parameters')); t.setObjectName('PageTitle')
        head.addWidget(t); head.addStretch(1)
        self.btn_reset = QPushButton('Reset Default')
        self.btn_reset.setProperty('flat', True)
        self.btn_reset.clicked.connect(self._reset)
        head.addWidget(self.btn_reset)
        lay.addLayout(head)
        sub = QLabel(tr('Semua nilai tersimpan otomatis. Arahkan kursor ke '
                        'label untuk melihat tooltip.'))
        sub.setObjectName('PageSub')
        lay.addWidget(sub)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); grid = QGridLayout(inner)
        grid.setSpacing(8)
        self.groups: list[ParamGroupBox] = []
        # 'Optimization Constraints' dipindahkan ke halaman Optimization
        # (di sebelah kiri kartu Objective & Kontrol).
        page_groups = [(n, p) for n, p in SCHEMA.items()
                       if n != 'Optimization Constraints']
        for i, (name, params) in enumerate(page_groups):
            g = ParamGroupBox(name, params)
            g.set_values(state.cfg)
            g.changed.connect(self._on_change)
            grid.addWidget(g, i // 2, i % 2)
            self.groups.append(g)
        grid.setRowStretch(grid.rowCount(), 1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        state.config_changed.connect(self.refresh_from_state)
        self._field('deg_interlock')
        self._wire_exclusive()
        self._sync_priority_choices()
        self._apply_visibility()

    def _apply_visibility(self):
        v = self._values()
        for g in self.groups:
            g.apply_visibility(v, VISIBILITY)

    def _label(self, key):
        for g in self.groups:
            if key in getattr(g, 'labels', {}):
                return g.labels[key]
        return None

    def _field(self, key):
        for g in self.groups:
            if key in g.fields:
                return g.fields[key]
        return None

    def _wire_exclusive(self):
        """Aturan saling-kunci antar opsi:
        * DEG interlock aktif  -> DEG charging dimatikan.
        * Grid interlock aktif -> grid charging dimatikan (bus terpisah).
        """
        fg, fgc = self._field('grid_interlock'), \
            self._field('grid_charge_enabled')
        if fg is not None and fgc is not None:
            def sync_grid():
                if bool(fg.value()) and bool(fgc.value()):
                    fgc.set_value(False)
                    self.state.cfg['grid_charge_enabled'] = False
                fgc.setEnabled(not bool(fg.value()))
            fg.changed.connect(sync_grid)
            sync_grid()
        # DEG interlock -> DEG charging dimatikan. Berlaku untuk setelan
        # tunggal maupun setelan per status grid (saat DEG Options Follow Grid
        # Status aktif): interlock status-1 mengunci charging status-1, dst.
        for ikey, ckey in (('deg_interlock', 'deg_charge_enabled'),
                           ('deg_interlock_on', 'deg_charge_on'),
                           ('deg_interlock_off', 'deg_charge_off')):
            fi, fc = self._field(ikey), self._field(ckey)
            if fi is None or fc is None:
                continue

            def make_sync(fi=fi, fc=fc):
                def sync():
                    locked = bool(fi.value())
                    if locked and bool(fc.value()):
                        fc.set_value(False)
                    fc.setEnabled(not locked)
                return sync
            s = make_sync()
            fi.changed.connect(s)
            s()
        # Smoothing <-> Firming, Operating Reserve <-> Backup: saling eksklusif
        # (mengaktifkan salah satu otomatis menonaktifkan pasangannya, dua
        # arah) -- BESS hanya boleh menjalankan salah satu peran dari tiap
        # pasangan pada saat bersamaan. Maks 5 mode aktif sekaligus (bukan 7)
        # -> dropdown Priority (parameters.py) memakai skala 1-5.
        # Diselesaikan TERPUSAT di _on_change()/refresh_from_state() (lihat
        # _resync_exclusive) -- BUKAN lewat sepasang sinyal 'changed' per
        # checkbox yang saling terhubung: pendekatan itu (versi sebelumnya)
        # bergantung pada URUTAN slot Qt yang menerima sinyal 'changed' yang
        # SAMA (forward ke ParamGroupBox.changed vs sinkronisasi sendiri),
        # yang TAK terjamin berjalan sebelum _on_change() sudah lebih dulu
        # menyimpan kedua flag True ke state.cfg -- akibatnya centang kedua
        # (mis. Firming saat Smoothing sudah aktif) kadang butuh DUA klik
        # sebelum benar2 saling mengunci (bug yang dilaporkan pengguna).
        self._exclusive_pairs = [('m_pv_smooth', 'm_firming'),
                                 ('m_reserve', 'm_backup')]
        self._resync_exclusive()

    def _resync_exclusive(self, prefer=None):
        """Pastikan tiap pasangan mode saling-eksklusif (_exclusive_pairs)
        hanya SATU yang aktif. `prefer`: set kunci yang BARU SAJA diaktifkan
        pengguna pada perubahan ini (dipertahankan; pasangannya yang
        dilepas). Tanpa `prefer` (mis. saat konstruksi awal atau memuat
        proyek lama yang mungkin menyimpan kedua flag True), anggota
        PERTAMA pada pasangan yang dipertahankan secara default.
        `self.state.cfg` ikut ditulis langsung (bukan hanya widget) karena
        ParamField.set_value menahan sinyal 'changed' (blockSignals)."""
        prefer = prefer or ()
        for a, b in getattr(self, '_exclusive_pairs', []):
            fa, fb = self._field(a), self._field(b)
            if fa is None or fb is None:
                continue
            if bool(fa.value()) and bool(fb.value()):
                drop = a if b in prefer else b
                fdrop = fb if drop == b else fa
                fdrop.set_value(False)
                self.state.cfg[drop] = False

    def _values(self) -> dict:
        v = {}
        for g in self.groups:
            v.update(g.values())
        return v

    def _sync_priority_choices(self):
        """Perbarui pilihan & tooltip untuk Load Supply Priority (tunggal)
        maupun kedua skenario per status grid (saat split aktif). Label tiap
        rantai menyesuaikan opsi DEG Interlock with Grid."""
        cfg = dict(self.state.cfg)
        cfg.update(self._values())
        # Selektor tunggal & 'Grid Available (1)' menampilkan rantai DASAR
        # penuh. Mode komposit 'Auto by Grid Status' & '(auto-interlock)'
        # dihapus dari dropdown (diwakili sakelar 'Load Priority Follows Grid
        # Status'). Selektor 'Grid Unavailable (0)' diringkas ke strategi
        # grid-padam yang benar-benar berbeda: saat grid memasok 0 kW, posisi
        # 'Grid' dalam rantai tak berpengaruh sehingga opsi kembar dilebur.
        # Tanpa grid, selektor Load Supply Priority memakai strategi grid-padam
        # (urutan PV/BESS/DEG) — posisi 'Grid' dalam rantai tak berpengaruh.
        grid_on = bool(cfg.get('grid_enabled', True))
        if grid_on:
            lp_choice_fn, lp_label_fn = (load_priority_base_choices,
                                         load_priority_label)
        else:
            lp_choice_fn, lp_label_fn = (load_priority_offgrid_choices,
                                         load_priority_off_label)
        specs = (('load_priority', lp_choice_fn, lp_label_fn),
                 ('load_priority_on', load_priority_base_choices,
                  load_priority_label),
                 ('load_priority_off', load_priority_off_choices,
                  load_priority_off_label))
        for key, choice_fn, label_fn in specs:
            f = self._field(key)
            if f is None:
                continue
            f.set_choices(choice_fn(cfg),
                          keep=label_fn(cfg.get(key, ''), cfg))
            base = tr(f.p.tooltip or f.p.label)
            detail = ('' if key == 'load_priority_off'
                      else tr(load_priority_help(cfg.get(key, ''), cfg)))
            txt = f'{detail}\n\n{base}' if detail else base
            f.w.setToolTip(txt)
            lbl = self._label(key)
            if lbl is not None:
                lbl.setToolTip(txt)

    def _on_change(self):
        v = self._values()
        # Pasangan mode saling-eksklusif: deteksi kunci yang BARU SAJA
        # beralih False -> True pada perubahan checkbox ini (dibandingkan
        # thd state.cfg SEBELUM disimpan) -- itulah yang baru saja dicentang
        # pengguna, jadi itu yang dipertahankan; pasangannya otomatis
        # dilepas. Dilakukan SEBELUM state.update_cfg(v) agar penyimpanan
        # tak pernah sempat memuat kedua flag True sekaligus.
        just_on = {k for pair in getattr(self, '_exclusive_pairs', ())
                  for k in pair
                  if v.get(k) and not bool(self.state.cfg.get(k))}
        self._resync_exclusive(prefer=just_on)
        v = self._values()          # baca ulang -- resync bisa saja mengubah widget
        self._sync_priority_choices()
        # validasi ringan lintas-parameter
        warn = []
        if v['soc_min'] >= v['soc_max']:
            warn.append(tr('SOC Minimum harus < SOC Maksimum.'))
        if warn:
            self.setToolTip(' '.join(warn))
        self._apply_visibility()
        self.state.update_cfg(v)

    def _reset(self):
        if QMessageBox.question(self, 'Reset',
                                tr('Kembalikan semua parameter ke default?')) \
                != QMessageBox.Yes:
            return
        d = defaults()
        for g in self.groups:
            g.set_values(d)
        self._apply_visibility()
        self.state.update_cfg(d)

    def refresh_from_state(self):
        for g in self.groups:
            g.set_values(self.state.cfg)
        self._resync_exclusive()
        self._sync_priority_choices()
        self._apply_visibility()
