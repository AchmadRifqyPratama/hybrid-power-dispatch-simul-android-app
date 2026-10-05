"""Gerbang kata sandi — dialog masuk aplikasi (hanya kata sandi, tanpa username).

Kata sandi diverifikasi lewat SHA-256 (lihat app/config/security.py). Logo
Akartha mengikuti tema aktif (versi terang untuk light theme, versi pucat
untuk dark theme). Tutup jendela / tombol "Keluar" untuk membatalkan.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)

from ..config.i18n import tr
from ..config.security import verify_password
from .plotutil import asset_path


class LoginDialog(QDialog):
    """Minta kata sandi sebelum jendela utama tampil."""

    def __init__(self, dark: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName('LoginDialog')
        self.setWindowTitle('HPP Studio')
        self.setModal(True)
        self._authed = False
        _ic = QIcon(asset_path('logo.png'))
        if not _ic.isNull():
            self.setWindowIcon(_ic)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 26)
        root.setSpacing(6)

        # --- logo Akartha (mengikuti tema) ---
        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignCenter)
        name = 'logo_akartha_dark.png' if dark else 'logo_akartha.png'
        pm = QPixmap(asset_path(name))
        if pm.isNull():
            pm = QPixmap(asset_path('logo_akartha.png'))
        if not pm.isNull():
            self.logo.setPixmap(pm.scaledToWidth(300, Qt.SmoothTransformation))
        root.addWidget(self.logo)
        root.addSpacing(8)

        title = QLabel(tr('Selamat datang'))
        title.setObjectName('PageTitle')
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel(tr('Masukkan kata sandi untuk melanjutkan'))
        sub.setObjectName('PageSub')
        sub.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        root.addWidget(sub)
        root.addSpacing(16)

        # --- baris kata sandi + tombol tampil/sembunyi ---
        row = QHBoxLayout()
        row.setSpacing(6)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText(tr('Masukkan kata sandi'))
        self.pw.setMinimumHeight(38)
        self.pw.returnPressed.connect(self._try_login)
        self.btn_eye = QPushButton('\U0001F441')          # 👁
        self.btn_eye.setCheckable(True)
        self.btn_eye.setProperty('flat', True)
        self.btn_eye.setFixedWidth(46)
        self.btn_eye.setMinimumHeight(38)
        self.btn_eye.setCursor(Qt.PointingHandCursor)
        self.btn_eye.setToolTip(tr('Tampilkan kata sandi'))
        self.btn_eye.toggled.connect(self._toggle_echo)
        row.addWidget(self.pw, 1)
        row.addWidget(self.btn_eye)
        root.addLayout(row)

        self.err = QLabel('')
        self.err.setObjectName('LoginError')
        self.err.setAlignment(Qt.AlignCenter)
        self.err.setVisible(False)
        root.addWidget(self.err)
        root.addSpacing(6)

        self.btn_ok = QPushButton(tr('Masuk'))
        self.btn_ok.setMinimumHeight(40)
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setDefault(True)
        self.btn_ok.setAutoDefault(True)
        self.btn_ok.clicked.connect(self._try_login)
        root.addWidget(self.btn_ok)

        btn_exit = QPushButton(tr('Keluar'))
        btn_exit.setProperty('flat', True)
        btn_exit.setCursor(Qt.PointingHandCursor)
        btn_exit.setAutoDefault(False)
        btn_exit.clicked.connect(self.reject)
        root.addWidget(btn_exit)

        self.setMinimumWidth(384)
        self.pw.setFocus()

    def _toggle_echo(self, on: bool):
        self.pw.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        self.btn_eye.setToolTip(tr('Sembunyikan kata sandi') if on
                                else tr('Tampilkan kata sandi'))

    def _try_login(self):
        if verify_password(self.pw.text()):
            self._authed = True
            self.accept()
        else:
            self.err.setText(tr('Kata sandi salah. Coba lagi.'))
            self.err.setVisible(True)
            self.pw.selectAll()
            self.pw.setFocus()

    @property
    def authenticated(self) -> bool:
        return self._authed
