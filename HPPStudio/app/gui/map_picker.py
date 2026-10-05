"""Dialog pemilih lokasi proyek — peta Leaflet (OpenStreetMap) via Qt WebEngine.

Fitur:
  * Peta interaktif: geser, zoom, klik untuk menaruh pin, dan seret pin.
  * Cari via latitude/longitude (kolom angka).
  * Cari via nama tempat (geocoding Nominatim/OpenStreetMap).
  * Alamat perkiraan (reverse geocoding) untuk mengisi kolom Location.

Aset Leaflet dibundel lokal (assets/leaflet) sehingga kerangka peta tetap
tampil walau offline; ubin peta & pencarian nama tempat memerlukan internet.
Modul GUI MURNI — tidak menyentuh mesin simulasi/dispatch.
"""
from __future__ import annotations

import json
import os
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config.i18n import tr
from .plotutil import asset_path

from PySide6.QtCore import Qt, QUrl, QObject, Signal, Slot, QTimer, QLocale, QEvent
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QDoubleSpinBox, QLineEdit, QPushButton,
                               QFrame, QWidget, QCheckBox, QComboBox,
                               QFormLayout)

# Locale titik-desimal (bukan koma), agar koordinat dapat di-copy-paste.
_US_LOCALE = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)

# Identitas aplikasi untuk permintaan ke Nominatim (wajib per kebijakan OSM).
_UA = 'HPPStudio/1.0 (Akartha Energi Baru)'
_NOMINATIM = 'https://nominatim.openstreetmap.org'

# Pusat peta bawaan bila koordinat belum diatur (kira-kira tengah Indonesia).
_DEFAULT_LAT, _DEFAULT_LON, _DEFAULT_ZOOM = -2.5, 118.0, 5
_PICK_ZOOM = 13


def webengine_available() -> bool:
    """True bila Qt WebEngine + WebChannel dapat diimpor (peta tersedia)."""
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
        import PySide6.QtWebChannel        # noqa: F401
        import PySide6.QtWebEngineCore     # noqa: F401
        return True
    except Exception:
        return False


_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<link rel="stylesheet" href="leaflet.css"/>
<script src="leaflet.js"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
  html,body,#map{height:100%;margin:0;padding:0}
  #map{background:#dfe7df}
  .leaflet-container{font-family:"Segoe UI",system-ui,sans-serif}
</style>
</head>
<body>
<div id="map"></div>
<script>
  var ICON = L.icon({
    iconUrl: 'images/marker-icon.png',
    iconRetinaUrl: 'images/marker-icon-2x.png',
    shadowUrl: 'images/marker-shadow.png',
    iconSize: [25,41], iconAnchor: [12,41],
    popupAnchor: [1,-34], shadowSize: [41,41]
  });
  var map = L.map('map', {zoomControl:true}).setView([__LAT__, __LON__], __ZOOM__);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);
  var marker = L.marker([__LAT__, __LON__], {draggable:true, icon:ICON}).addTo(map);
  var bridge = null;

  function report(ll){ if(bridge){ bridge.picked(ll.lat, ll.lng); } }
  map.on('click', function(e){ marker.setLatLng(e.latlng); report(e.latlng); });
  marker.on('dragend', function(){ report(marker.getLatLng()); });

  new QWebChannel(qt.webChannelTransport, function(channel){
    bridge = channel.objects.bridge;
    bridge.move_to.connect(function(lat, lon, zoom){
      marker.setLatLng([lat, lon]);
      if(zoom && zoom > 0){ map.setView([lat, lon], zoom); }
      else { map.panTo([lat, lon]); }
    });
    bridge.ready();
  });
  // Ukuran peta kadang perlu di-refresh setelah kontainer tampil.
  setTimeout(function(){ map.invalidateSize(); }, 250);
</script>
</body>
</html>"""


class _Bridge(QObject):
    """Jembatan JS <-> Python (QWebChannel)."""
    move_to = Signal(float, float, int)      # Python -> JS: pindah peta & pin

    def __init__(self, on_pick, on_ready):
        super().__init__()
        self._on_pick = on_pick
        self._on_ready = on_ready

    @Slot(float, float)
    def picked(self, lat, lon):               # JS -> Python: klik/seret pin
        self._on_pick(float(lat), float(lon))

    @Slot()
    def ready(self):                          # JS -> Python: peta siap
        self._on_ready()


class LossCalculatorDialog(QDialog):
    """Kalkulator rugi sistem PV: isi tiap komponen -> total gabungan.

    Total memakai gabungan PERKALIAN (1 - Π(1-rugiᵢ)), lebih tepat daripada
    penjumlahan. Rugi suhu & iradiansi-rendah TIDAK termasuk (dimodelkan
    tersendiri oleh PVGIS)."""

    _FIELDS = [
        ('inverter', 'Inverter', 3.0),
        ('cabling_dc', 'DC cabling', 1.0),
        ('cabling_ac', 'AC cabling', 1.0),
        ('mismatch', 'Module mismatch', 2.0),
        ('soiling', 'Soiling / dust', 3.0),
        ('shading', 'Shading', 2.0),
        ('other', 'Availability / other', 2.0),
    ]
    # Saat koreksi tipe-PVSyst aktif, dua komponen ini dimodelkan eksplisit
    # oleh koreksi (inverter → η inverter; kabel DC → sebanding iradiansi),
    # jadi DIKELUARKAN dari total agar tidak dobel-hitung.
    _PVSYST_EXCL = ('inverter', 'cabling_dc')

    def __init__(self, components=None, pvsyst_on=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('System Loss Calculator'))
        self.setMinimumWidth(380)
        comp = dict(components or {})
        self._pvsyst_on = bool(pvsyst_on)
        lay = QVBoxLayout(self)
        lay.setSpacing(9)
        hint = QLabel(tr('Enter each loss component (%). Temperature and '
                         'low-irradiance losses are excluded — PVGIS models '
                         'them separately.'))
        hint.setWordWrap(True); hint.setObjectName('PageSub')
        lay.addWidget(hint)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.spins = {}
        for key, label, default in self._FIELDS:
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 100.0); sp.setDecimals(2); sp.setSuffix(' %')
            sp.setSingleStep(0.1); sp.setLocale(_US_LOCALE)
            sp.setValue(float(comp.get(key, default)))
            sp.valueChanged.connect(self._update_total)
            self.spins[key] = sp
            form.addRow(tr(label), sp)
            if self._pvsyst_on and key == 'inverter':
                sp.setEnabled(False)          # digantikan η inverter koreksi
                sp.setToolTip(tr('Handled by "Inverter η" in the PVSyst-like '
                                 'correction — not counted here.'))
        lay.addLayout(form)
        if self._pvsyst_on:
            fn = QLabel(tr(
                'PVSyst-like correction is on: Inverter uses "Inverter η" '
                '(this row is disabled) and DC cabling is scaled with '
                'irradiance. Both are excluded from the total below to avoid '
                'double-counting.'))
            fn.setWordWrap(True); fn.setObjectName('PageSub')
            lay.addWidget(fn)
        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setObjectName('HSep'); lay.addWidget(line)
        self.lbl_total = QLabel('')
        f = self.lbl_total.font()
        f.setBold(True)
        # Font aplikasi bisa memakai pixel-size (pointSize()==-1); jangan
        # memanggil setPointSize(0) yang memicu peringatan Qt.
        if f.pointSizeF() > 0:
            f.setPointSizeF(f.pointSizeF() + 1)
        elif f.pixelSize() > 0:
            f.setPixelSize(f.pixelSize() + 1)
        self.lbl_total.setFont(f)
        lay.addWidget(self.lbl_total)
        foot = QHBoxLayout(); foot.addStretch(1)
        b_cancel = QPushButton(tr('Cancel'))
        b_cancel.setCursor(Qt.PointingHandCursor)
        b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(tr('Use This Value'))
        b_ok.setCursor(Qt.PointingHandCursor); b_ok.setDefault(True)
        b_ok.clicked.connect(self.accept)
        foot.addWidget(b_cancel); foot.addWidget(b_ok)
        lay.addLayout(foot)
        self._update_total()

    def _combined(self) -> float:
        eff = 1.0
        for key, sp in self.spins.items():
            if self._pvsyst_on and key in self._PVSYST_EXCL:
                continue                      # ditangani koreksi tipe-PVSyst
            eff *= (1.0 - min(max(sp.value(), 0.0), 100.0) / 100.0)
        return (1.0 - eff) * 100.0

    def _update_total(self):
        self.lbl_total.setText(
            tr('Total system loss: {v:.2f}%').format(v=self._combined()))

    def result_total(self) -> float:
        return round(self._combined(), 2)

    def result_components(self) -> dict:
        return {k: float(sp.value()) for k, sp in self.spins.items()}


class MapPickerDialog(QDialog):
    """Pilih lokasi proyek pada peta; kembalikan (latitude, longitude)."""

    # Sinyal hasil kerja thread jaringan (aman lintas-thread: koneksi queued).
    _geo_ok = Signal(float, float, str)
    _geo_err = Signal(str)
    _rev_ok = Signal(str)

    def __init__(self, lat=0.0, lon=0.0, options=None, parent=None):
        super().__init__(parent)
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebChannel import QWebChannel

        self._opts = dict(options or {})     # setelan PVGIS tersimpan (persist)
        self.setWindowTitle(tr('Select Project Location'))
        self.setMinimumSize(740, 720)
        # Wujudkan jendela native lebih dulu agar bilah judul bisa diwarnai
        # gelap SEBELUM tampil, DAN agar QWebEngineView menempel ke jendela
        # native yang sudah ada — mengurangi pembuatan-ulang handle (penyebab
        # "kedip" + bilah judul kembali putih). Sisa kasus ditangani lewat
        # event WinIdChange di event() di bawah.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.winId()                       # realisasikan handle native sekarang
        self._theme_titlebar()             # warnai gelap sejak awal

        try:
            lat = float(lat); lon = float(lon)
        except (TypeError, ValueError):
            lat = lon = 0.0
        unset = abs(lat) < 1e-9 and abs(lon) < 1e-9
        self._lat = lat if not unset else _DEFAULT_LAT
        self._lon = lon if not unset else _DEFAULT_LON
        init_zoom = _PICK_ZOOM if not unset else _DEFAULT_ZOOM
        self._address = ''
        # komponen kalkulator rugi terakhir (dipulihkan dari setelan tersimpan)
        self._loss_components = self._opts.get('loss_components')

        root = QVBoxLayout(self)
        root.setSpacing(9)

        hint = QLabel(tr('Search coordinates or a place, or click the map / drag '
                         'the pin to set the project location.'))
        hint.setWordWrap(True)
        hint.setObjectName('PageSub')
        root.addWidget(hint)

        # --- Baris 1: latitude / longitude + Go ---
        row1 = QHBoxLayout(); row1.setSpacing(7)
        row1.addWidget(QLabel(tr('Latitude')))
        self.lat = QDoubleSpinBox()
        self.lat.setDecimals(6); self.lat.setRange(-90.0, 90.0)
        self.lat.setSingleStep(0.001); self.lat.setValue(self._lat)
        self.lat.setLocale(_US_LOCALE)          # titik desimal
        self.lat.setMinimumWidth(120)
        row1.addWidget(self.lat)
        row1.addWidget(QLabel(tr('Longitude')))
        self.lon = QDoubleSpinBox()
        self.lon.setDecimals(6); self.lon.setRange(-180.0, 180.0)
        self.lon.setSingleStep(0.001); self.lon.setValue(self._lon)
        self.lon.setLocale(_US_LOCALE)          # titik desimal
        self.lon.setMinimumWidth(120)
        row1.addWidget(self.lon)
        self.btn_go = QPushButton(tr('Go'))
        self.btn_go.setCursor(Qt.PointingHandCursor)
        self.btn_go.clicked.connect(self._go)
        row1.addWidget(self.btn_go)
        row1.addStretch(1)
        root.addLayout(row1)

        # --- Baris 2: pencarian nama tempat ---
        row2 = QHBoxLayout(); row2.setSpacing(7)
        self.place = QLineEdit()
        self.place.setPlaceholderText(tr('Search place (e.g. Denpasar, Bali)'))
        self.place.returnPressed.connect(self._search_place)
        row2.addWidget(self.place, 1)
        self.btn_place = QPushButton(tr('Search Place'))
        self.btn_place.setCursor(Qt.PointingHandCursor)
        self.btn_place.clicked.connect(self._search_place)
        row2.addWidget(self.btn_place)
        root.addLayout(row2)

        self.status = QLabel('')
        self.status.setObjectName('PageSub')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        # --- Peta ---
        self.view = QWebEngineView()
        try:
            st = self.view.settings()
            st.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                True)
            st.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
                True)
        except Exception:
            pass
        root.addWidget(self.view, 1)

        # readout koordinat + alamat perkiraan
        self.readout = QLabel(f'{self._lat:.6f}, {self._lon:.6f}')
        self.readout.setObjectName('PageSub')
        root.addWidget(self.readout)
        self.addr = QLabel('')
        self.addr.setObjectName('PageSub')
        self.addr.setWordWrap(True)
        root.addWidget(self.addr)

        # --- Opsi: unduh profil PV dari PVGIS untuk lokasi ini ---
        self.chk_pvgis = QCheckBox(
            tr('Download PV/irradiance data (PVGIS) for this location'))
        self.chk_pvgis.setToolTip(tr(
            'When enabled, pressing "Select Location" downloads the hourly PV '
            'profile from the PVGIS open API for these coordinates and uses it '
            'as the PV ENetAC profile. Requires internet; leave unchecked to '
            'keep the current profile.'))
        root.addWidget(self.chk_pvgis)

        # --- Opsi lanjut PVGIS (aktif hanya bila kotak unduh dicentang) ---
        self.pvgis_adv = QWidget()
        advv = QVBoxLayout(self.pvgis_adv)
        advv.setContentsMargins(24, 0, 0, 0); advv.setSpacing(6)
        # Baris A: orientasi
        rowa = QHBoxLayout(); rowa.setSpacing(8)
        self.chk_optimal = QCheckBox(tr('Optimal tilt/azimuth'))
        self.chk_optimal.setChecked(bool(self._opts.get('optimal', True)))
        self.chk_optimal.setToolTip(tr('Let PVGIS optimise both tilt and '
                                       'azimuth for this location.'))
        rowa.addWidget(self.chk_optimal)
        rowa.addWidget(QLabel(tr('Tilt')))
        self.spin_tilt = QDoubleSpinBox()
        self.spin_tilt.setRange(0.0, 90.0); self.spin_tilt.setDecimals(0)
        self.spin_tilt.setSuffix('°'); self.spin_tilt.setLocale(_US_LOCALE)
        self.spin_tilt.setValue(float(self._opts.get('tilt', round(abs(self._lat)))))
        self.spin_tilt.setToolTip(tr('Panel tilt from horizontal (0–90°).'))
        rowa.addWidget(self.spin_tilt)
        rowa.addWidget(QLabel(tr('Azimuth')))
        self.spin_az = QDoubleSpinBox()
        self.spin_az.setRange(-180.0, 180.0); self.spin_az.setDecimals(0)
        self.spin_az.setSuffix('°'); self.spin_az.setLocale(_US_LOCALE)
        self.spin_az.setValue(float(self._opts.get(
            'azimuth', 0.0 if self._lat >= 0 else 180.0)))
        self.spin_az.setToolTip(tr('PVGIS azimuth: 0=South, 90=West, '
                                   '−90=East, 180=North.'))
        rowa.addWidget(self.spin_az)
        rowa.addStretch(1)
        advv.addLayout(rowa)
        # Baris B: pemasangan, rugi, tahun
        rowb = QHBoxLayout(); rowb.setSpacing(8)
        rowb.addWidget(QLabel(tr('Mounting')))
        self.combo_mount = QComboBox()
        self.combo_mount.addItem(tr('Free-standing'), 'free')
        self.combo_mount.addItem(tr('Building-integrated'), 'building')
        self.combo_mount.setToolTip(tr(
            'Free-standing: rack-mounted, air flows behind the modules '
            '(cooler). Building-integrated: fixed to a building, less '
            'ventilation (warmer, slightly lower yield).'))
        _mi = self.combo_mount.findData(self._opts.get('mounting', 'free'))
        self.combo_mount.setCurrentIndex(_mi if _mi >= 0 else 0)
        rowb.addWidget(self.combo_mount)
        rowb.addWidget(QLabel(tr('Loss')))
        self.spin_loss = QDoubleSpinBox()
        self.spin_loss.setRange(0.0, 100.0); self.spin_loss.setDecimals(2)
        self.spin_loss.setSingleStep(0.1)
        self.spin_loss.setSuffix('%'); self.spin_loss.setLocale(_US_LOCALE)
        self.spin_loss.setValue(float(self._opts.get('loss', 14.0)))
        self.spin_loss.setToolTip(tr('Combined system losses excl. temperature '
                                     '& low-irradiance (cables, inverter, '
                                     'mismatch, soiling…). PVGIS default 14%.'))
        rowb.addWidget(self.spin_loss)
        self.btn_loss_calc = QPushButton(tr('Calc…'))
        self.btn_loss_calc.setCursor(Qt.PointingHandCursor)
        self.btn_loss_calc.setToolTip(tr('Open the system-loss calculator '
                                         '(fill components → total loss).'))
        self.btn_loss_calc.clicked.connect(self._open_loss_calc)
        rowb.addWidget(self.btn_loss_calc)
        rowb.addWidget(QLabel(tr('Year')))
        self.combo_year = QComboBox()
        self.combo_year.addItem(tr('Auto'))
        for _y in range(2020, 2004, -1):
            self.combo_year.addItem(str(_y))
        self.combo_year.setToolTip(tr('Radiation-data year. "Auto" matches the '
                                      'length of your existing data.'))
        _yi = self.combo_year.findText(str(self._opts.get('year') or ''))
        self.combo_year.setCurrentIndex(_yi if _yi > 0 else 0)   # 0 = Auto
        rowb.addWidget(self.combo_year)
        rowb.addStretch(1)
        advv.addLayout(rowb)

        # Baris C: koreksi tipe-PVSyst (clipping inverter + kabel DC ∝ iradiansi)
        rowc = QHBoxLayout(); rowc.setSpacing(8)
        self.chk_pvsyst = QCheckBox(tr('PVSyst-like correction'))
        self.chk_pvsyst.setChecked(bool(self._opts.get('pvsyst_match', False)))
        self.chk_pvsyst.setToolTip(tr(
            'Apply inverter clipping, inverter part-load efficiency, and '
            'irradiance-dependent DC cabling loss on top of the PVGIS profile '
            'so P/G(i) is closer to PVSyst E_Grid/GlobInc. Inverter and DC '
            'cabling are then removed from the flat PVGIS loss to avoid '
            'double-counting; DC cabling @STC is taken from the loss '
            'calculator.'))
        rowc.addWidget(self.chk_pvsyst)
        rowc.addWidget(QLabel(tr('DC/AC')))
        self.spin_dcac = QDoubleSpinBox()
        self.spin_dcac.setRange(1.0, 2.5); self.spin_dcac.setDecimals(2)
        self.spin_dcac.setSingleStep(0.05); self.spin_dcac.setLocale(_US_LOCALE)
        self.spin_dcac.setValue(float(self._opts.get('dcac', 1.2) or 1.2))
        self.spin_dcac.setToolTip(tr(
            'DC/AC ratio = array DC (kWp) ÷ inverter AC (kW). Output is '
            'clipped at Pnom AC = reference kWp ÷ DC/AC.'))
        rowc.addWidget(self.spin_dcac)
        rowc.addWidget(QLabel(tr('Inverter η')))
        self.spin_inv_eff = QDoubleSpinBox()
        self.spin_inv_eff.setRange(80.0, 100.0); self.spin_inv_eff.setDecimals(2)
        self.spin_inv_eff.setSingleStep(0.1); self.spin_inv_eff.setSuffix('%')
        self.spin_inv_eff.setLocale(_US_LOCALE)
        self.spin_inv_eff.setValue(float(self._opts.get('inv_eff', 98.0)
                                         or 98.0))
        self.spin_inv_eff.setToolTip(tr(
            'Inverter plateau efficiency (e.g. Euro/CEC %). Used with a small '
            'self-consumption term for the low-load roll-off.'))
        rowc.addWidget(self.spin_inv_eff)
        rowc.addStretch(1)
        advv.addLayout(rowc)

        # Baris D: modul bifacial (gain pantulan tanah sisi belakang)
        rowd = QHBoxLayout(); rowd.setSpacing(8)
        self.chk_bifacial = QCheckBox(tr('Bifacial module'))
        self.chk_bifacial.setChecked(bool(self._opts.get('bifacial', False)))
        self.chk_bifacial.setToolTip(tr(
            'Add rear-side (bifacial) gain from ground-reflected light on top '
            'of the PVGIS monofacial profile. Requires GHI (downloaded '
            'automatically). Gain per hour = bifaciality × albedo × GHI × '
            'rear-side factor ÷ front G(i).'))
        rowd.addWidget(self.chk_bifacial)
        rowd.addWidget(QLabel(tr('Albedo')))
        self.spin_albedo = QDoubleSpinBox()
        self.spin_albedo.setRange(0.0, 1.0); self.spin_albedo.setDecimals(2)
        self.spin_albedo.setSingleStep(0.05); self.spin_albedo.setLocale(
            _US_LOCALE)
        self.spin_albedo.setValue(float(self._opts.get('albedo', 0.20) or 0.20))
        self.spin_albedo.setToolTip(tr(
            'Ground reflectance: grass ~0.20, dry sand ~0.40, concrete ~0.30, '
            'white membrane ~0.60.'))
        rowd.addWidget(self.spin_albedo)
        rowd.addWidget(QLabel(tr('Bifaciality')))
        self.spin_bifac = QDoubleSpinBox()
        self.spin_bifac.setRange(50.0, 95.0); self.spin_bifac.setDecimals(2)
        self.spin_bifac.setSingleStep(0.1); self.spin_bifac.setSuffix('%')
        self.spin_bifac.setLocale(_US_LOCALE)
        self.spin_bifac.setValue(float(self._opts.get('bifaciality', 70.0)
                                       or 70.0))
        self.spin_bifac.setToolTip(tr(
            'Bifaciality factor from the module datasheet (rear ÷ front '
            'efficiency), typically 65–85%.'))
        rowd.addWidget(self.spin_bifac)
        rowd.addWidget(QLabel(tr('Rear factor')))
        self.spin_rear = QDoubleSpinBox()
        self.spin_rear.setRange(0.0, 100.0); self.spin_rear.setDecimals(2)
        self.spin_rear.setSingleStep(0.1); self.spin_rear.setSuffix('%')
        self.spin_rear.setLocale(_US_LOCALE)
        self.spin_rear.setValue(float(self._opts.get('rear_factor', 65.0)
                                      or 65.0))
        self.spin_rear.setToolTip(tr(
            'Fraction of ground-reflected light that effectively reaches the '
            'rear (view factor × structure shading × non-uniformity). Lower '
            'for close-to-ground / dense arrays; typical 50–80%.'))
        rowd.addWidget(self.spin_rear)
        rowd.addStretch(1)
        advv.addLayout(rowd)

        root.addWidget(self.pvgis_adv)
        self.chk_pvgis.toggled.connect(self._sync_pvgis_opts)
        self.chk_optimal.toggled.connect(self._sync_pvgis_opts)
        self.chk_pvsyst.toggled.connect(self._sync_pvgis_opts)
        self.chk_pvsyst.toggled.connect(self._recompute_loss_field)
        self.chk_bifacial.toggled.connect(self._sync_pvgis_opts)
        self._sync_pvgis_opts()

        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setObjectName('HSep')
        root.addWidget(line)

        # --- Tombol Batal / Pilih ---
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.btn_cancel = QPushButton(tr('Cancel'))
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton(tr('Select Location'))
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        foot.addWidget(self.btn_cancel)
        foot.addWidget(self.btn_ok)
        root.addLayout(foot)

        # --- QWebChannel & bridge ---
        self.bridge = _Bridge(self._on_picked, self._on_ready)
        self.channel = QWebChannel(self)
        self.channel.registerObject('bridge', self.bridge)
        self.view.page().setWebChannel(self.channel)

        # timer debounce reverse-geocode
        self._rev_timer = QTimer(self)
        self._rev_timer.setSingleShot(True)
        self._rev_timer.setInterval(900)
        self._rev_timer.timeout.connect(self._do_reverse)

        # sinyal hasil jaringan -> slot GUI
        self._geo_ok.connect(self._on_geo_ok)
        self._geo_err.connect(self._on_geo_err)
        self._rev_ok.connect(self._on_rev_ok)

        # editingFinished pada spinbox = perlakukan seperti "Go"
        self.lat.editingFinished.connect(self._go)
        self.lon.editingFinished.connect(self._go)

        # muat HTML peta (aset lokal via baseUrl)
        leaflet_dir = os.path.dirname(asset_path(os.path.join('leaflet',
                                                              'leaflet.js')))
        base = QUrl.fromLocalFile(os.path.join(leaflet_dir, ''))
        html = (_HTML.replace('__LAT__', repr(self._lat))
                     .replace('__LON__', repr(self._lon))
                     .replace('__ZOOM__', str(init_zoom)))
        self.view.setHtml(html, base)
        # WebEngine menginisialisasi jendela secara asinkron dan dapat mengatur
        # ulang bingkai OS -> warnai ulang bilah judul setelah halaman selesai.
        try:
            self.view.loadFinished.connect(lambda _ok: self._theme_titlebar())
        except Exception:
            pass
        # alamat awal (bila koordinat sudah diatur)
        if not unset:
            self._schedule_reverse()

    # ---------------------------------------------------------------- tema ----
    def _theme_titlebar(self):
        """Samakan bilah judul dialog dengan tema aktif (gelap)."""
        try:
            from .theme import apply_titlebar_theme, CURRENT_DARK
            apply_titlebar_theme(self, dark=CURRENT_DARK)
        except Exception:
            pass

    def event(self, e):
        # Saat QWebEngineView memaksa Qt membuat ulang handle jendela native,
        # atribut "dark title bar" (DWM) ikut ter-reset -> bilah judul jadi
        # putih. Tangkap tepat saat handle berubah lalu warnai ulang seketika.
        if e.type() == QEvent.Type.WinIdChange:
            self._theme_titlebar()
        return super().event(e)

    def showEvent(self, e):
        super().showEvent(e)
        # Terapkan berkali-kali: saat tampil, segera, dan setelah WebEngine
        # selesai menyiapkan jendela (jaring pengaman untuk WinIdChange).
        self._theme_titlebar()
        for _d in (0, 150, 400, 900, 1500):
            QTimer.singleShot(_d, self._theme_titlebar)

    # ------------------------------------------------------------------ util
    def _set_current(self, lat, lon):
        """Perbarui koordinat aktif + kolom angka (tanpa menggeser peta)."""
        self._lat, self._lon = float(lat), float(lon)
        for sb, val in ((self.lat, self._lat), (self.lon, self._lon)):
            sb.blockSignals(True)
            sb.setValue(val)
            sb.blockSignals(False)
        self.readout.setText(f'{self._lat:.6f}, {self._lon:.6f}')

    # ------------------------------------------------------------- callbacks
    def _on_ready(self):
        self.status.setText('')

    def _on_picked(self, lat, lon):
        """Dari peta (klik/seret pin)."""
        self._set_current(lat, lon)
        self._schedule_reverse()

    def _go(self):
        """Pusatkan peta ke koordinat pada kolom angka."""
        lat, lon = self.lat.value(), self.lon.value()
        self._set_current(lat, lon)
        self.bridge.move_to.emit(lat, lon, _PICK_ZOOM)
        self._schedule_reverse()

    # ------------------------------------------------- geocoding (nama tempat)
    def _search_place(self):
        q = self.place.text().strip()
        if not q:
            return
        self.status.setText(tr('Searching…'))
        lat0, lon0 = self._lat, self._lon

        def work():
            try:
                url = _NOMINATIM + '/search?' + urlencode(
                    {'q': q, 'format': 'json', 'limit': 1})
                req = Request(url, headers={'User-Agent': _UA})
                with urlopen(req, timeout=8) as resp:
                    data = json.load(resp)
                if data:
                    self._geo_ok.emit(float(data[0]['lat']),
                                      float(data[0]['lon']),
                                      data[0].get('display_name', ''))
                else:
                    self._geo_err.emit(tr('Place not found.'))
            except Exception:
                self._geo_err.emit(
                    tr('Search failed — check your internet connection.'))

        threading.Thread(target=work, daemon=True).start()

    def _on_geo_ok(self, lat, lon, name):
        self._set_current(lat, lon)
        self.bridge.move_to.emit(lat, lon, _PICK_ZOOM)
        self._address = name or ''
        self.addr.setText((tr('Address:') + ' ' + name) if name else '')
        self.status.setText('')

    def _on_geo_err(self, msg):
        self.status.setText(msg)

    # ------------------------------------------- reverse geocoding (alamat)
    def _schedule_reverse(self):
        self.addr.setText(tr('Getting address…'))
        self._rev_timer.start()

    def _do_reverse(self):
        lat, lon = self._lat, self._lon

        def work():
            try:
                url = _NOMINATIM + '/reverse?' + urlencode(
                    {'lat': lat, 'lon': lon, 'format': 'json', 'zoom': 14})
                req = Request(url, headers={'User-Agent': _UA})
                with urlopen(req, timeout=8) as resp:
                    data = json.load(resp)
                self._rev_ok.emit(data.get('display_name', '') or '')
            except Exception:
                self._rev_ok.emit('')

        threading.Thread(target=work, daemon=True).start()

    def _on_rev_ok(self, name):
        self._address = name or ''
        self.addr.setText((tr('Address:') + ' ' + name) if name
                          else tr('Address not available (offline?).'))

    # ------------------------------------------------------------- hasil API
    def result_latlon(self):
        """(latitude, longitude) terpilih."""
        return round(self._lat, 6), round(self._lon, 6)

    def result_address(self):
        """Alamat perkiraan (bisa kosong)."""
        return self._address

    def want_pvgis(self) -> bool:
        """True bila pengguna memilih mengunduh profil PV dari PVGIS."""
        try:
            return self.chk_pvgis.isChecked()
        except Exception:
            return False

    def _sync_pvgis_opts(self):
        """Aktif/nonaktifkan opsi lanjut sesuai centang unduh & mode optimal."""
        on = self.chk_pvgis.isChecked()
        self.pvgis_adv.setEnabled(on)
        manual = on and not self.chk_optimal.isChecked()
        self.spin_tilt.setEnabled(manual)
        self.spin_az.setEnabled(manual)
        ps = on and self.chk_pvsyst.isChecked()
        self.spin_dcac.setEnabled(ps)
        self.spin_inv_eff.setEnabled(ps)
        bf = on and self.chk_bifacial.isChecked()
        self.spin_albedo.setEnabled(bf)
        self.spin_bifac.setEnabled(bf)
        self.spin_rear.setEnabled(bf)

    def _recompute_loss_field(self, *_):
        """Jaga kolom Loss tetap jujur saat koreksi tipe-PVSyst diaktif/matikan.

        Saat koreksi aktif, inverter & kabel DC dimodelkan eksplisit sehingga
        DIKELUARKAN dari loss datar PVGIS; kolom Loss diperbarui agar nilainya =
        loss datar yang benar-benar dikirim ke PVGIS (bukan total penuh)."""
        comps = self._loss_components
        if not comps:
            return                           # tak ada komponen → biarkan manual
        from ..data.pvgis import combine_losses
        excl = (LossCalculatorDialog._PVSYST_EXCL
                if self.chk_pvsyst.isChecked() else ())
        self.spin_loss.setValue(round(combine_losses(comps, exclude=excl), 2))

    def _open_loss_calc(self):
        """Buka kalkulator rugi sistem; hasilnya mengisi kolom Loss."""
        dlg = LossCalculatorDialog(self._loss_components,
                                   pvsyst_on=self.chk_pvsyst.isChecked(),
                                   parent=self)
        try:
            from .theme import apply_titlebar_theme, CURRENT_DARK
            QTimer.singleShot(0, lambda: apply_titlebar_theme(
                dlg, dark=CURRENT_DARK))
        except Exception:
            pass
        if dlg.exec() == QDialog.Accepted:
            self._loss_components = dlg.result_components()
            self.spin_loss.setValue(dlg.result_total())

    def pvgis_options(self) -> dict:
        """Opsi PVGIS terpilih: optimal, tilt, azimuth, loss, year (None=Auto)."""
        try:
            year = int(self.combo_year.currentText())
        except (ValueError, TypeError):
            year = None                      # 'Auto'
        return {
            'optimal': self.chk_optimal.isChecked(),
            'tilt': float(self.spin_tilt.value()),
            'azimuth': float(self.spin_az.value()),
            'loss': float(self.spin_loss.value()),
            'mounting': self.combo_mount.currentData() or 'free',
            'year': year,
            'loss_components': self._loss_components,
            'pvsyst_match': self.chk_pvsyst.isChecked(),
            'dcac': float(self.spin_dcac.value()),
            'inv_eff': float(self.spin_inv_eff.value()),
            'bifacial': self.chk_bifacial.isChecked(),
            'albedo': float(self.spin_albedo.value()),
            'bifaciality': float(self.spin_bifac.value()),
            'rear_factor': float(self.spin_rear.value()),
        }
