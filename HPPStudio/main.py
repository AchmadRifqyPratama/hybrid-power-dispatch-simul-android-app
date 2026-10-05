"""HPP Studio — entry point.

Jalankan pengembangan :  python main.py
Build .exe (Windows)  :  build_windows.bat  (lihat README.md)
"""
import multiprocessing
import os
import sys


def _log_dir():
    """Folder untuk menulis log — di sebelah .exe saat frozen, atau folder
    proyek saat dijalankan dari sumber."""
    try:
        base = (os.path.dirname(sys.executable)
                if getattr(sys, 'frozen', False)
                else os.path.dirname(os.path.abspath(__file__)))
        os.makedirs(base, exist_ok=True)
        return base
    except Exception:
        return os.getcwd()


def _install_crash_logging():
    """Tangkap crash agar tak sekadar 'force close' tanpa jejak.

    * faulthandler menulis traceback crash C-level (segfault / abort, mis.
      'QThread destroyed while running') ke hppstudio_crash.log.
    * sys.excepthook mencatat exception Python tak-tertangani ke
      hppstudio_error.log (pada build --windowed stderr = None sehingga tanpa
      ini jejaknya hilang)."""
    try:
        import faulthandler
        fh = open(os.path.join(_log_dir(), 'hppstudio_crash.log'),
                  'a', buffering=1)
        faulthandler.enable(fh)
    except Exception:
        pass

    def _hook(exc_type, exc, tb):
        import traceback
        import datetime
        try:
            with open(os.path.join(_log_dir(), 'hppstudio_error.log'),
                      'a', encoding='utf-8') as f:
                f.write('\n=== ' + datetime.datetime.now().isoformat()
                        + ' ===\n')
                traceback.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass
        try:
            traceback.print_exception(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _hook


def main():
    _install_crash_logging()
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QDialog
    from app.gui.main_window import MainWindow

    # Berbagi konteks OpenGL — disarankan untuk Qt WebEngine (peta lokasi).
    # Harus disetel SEBELUM QApplication dibuat; aman bila WebEngine tak dipakai.
    try:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts,
                                  True)
    except Exception:
        pass

    app = QApplication(sys.argv)
    from PySide6.QtGui import QIcon
    from app.gui.plotutil import asset_path
    _icon = QIcon(asset_path('logo.png'))
    if not _icon.isNull():
        app.setWindowIcon(_icon)
    app.setApplicationName('HPP Studio')
    app.setApplicationVersion('0.31.0.0')
    app.setOrganizationName('Akartha Energi Baru')
    app.setOrganizationDomain('akarthaenergy.com')

    # --- Gerbang kata sandi (SHA-256) sebelum aplikasi utama tampil ---
    from app.gui.theme import apply_theme, apply_titlebar_theme
    from app.gui.login import LoginDialog
    from app.config.i18n import set_language
    from app.config.parameters import load_config
    from app.gui.state import CFG_PATH
    try:
        set_language(load_config(CFG_PATH).get('language', 'ID'))
    except Exception:
        set_language('ID')
    apply_theme(app, dark=True)          # dialog login memakai tema gelap default
    login = LoginDialog(dark=True)
    QTimer.singleShot(0, lambda: apply_titlebar_theme(login, dark=True))
    if login.exec() != QDialog.Accepted or not login.authenticated:
        sys.exit(0)                      # kata sandi salah / dibatalkan -> keluar

    win = MainWindow()
    win.showMaximized()      # penuhi layar laptop, apa pun ukurannya
    # winId() baru valid setelah jendela tampil -> warnai bilah judul
    apply_titlebar_theme(win, dark=getattr(win, 'dark', True))
    sys.exit(app.exec())


if __name__ == '__main__':
    # WAJIB untuk PyInstaller + ProcessPoolExecutor (optimization engine):
    # tanpa ini, tiap proses anak akan membuka jendela aplikasi baru.
    multiprocessing.freeze_support()
    main()
