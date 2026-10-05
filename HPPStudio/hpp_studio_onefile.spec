# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
#  HPP Studio — build SATU BERKAS .exe (onefile)
#
#  Build :  pyinstaller hpp_studio_onefile.spec --noconfirm
#  Hasil :  dist/HPPStudio.exe   <-- CUKUP BAGIKAN BERKAS INI SAJA
#
#  Semua dependensi + aset (logo, ikon, panah) sudah dibungkus ke dalam satu
#  berkas .exe; tidak perlu menyertakan folder atau berkas lain.
#  (Mode onedir tetap tersedia lewat hpp_studio.spec bila ingin start-up lebih
#   cepat dengan cara distribusi 1 folder.)
# =============================================================================

from PyInstaller.utils.hooks import collect_submodules, collect_data_files


def _opt(mod):
    """Sertakan paket opsional bila terpasang di environment build."""
    try:
        __import__(mod)
        return collect_submodules(mod)
    except Exception:
        return []


def _mod(mod):
    """Nama modul (tanpa seluruh sub-paket) bila terpasang di environment build."""
    try:
        __import__(mod)
        return [mod]
    except Exception:
        return []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')] + collect_data_files('reportlab')
          + collect_data_files('docx')
          # OCR terbawa: model ONNX PP-OCRv4 (app/ocr/models)
          + [('app/ocr/models', 'app/ocr/models')],
    hiddenimports=[
        'pyqtgraph', 'openpyxl',
        'matplotlib.backends.backend_agg',
        'matplotlib.backends.backend_svg',
        # Peta lokasi (Qt WebEngine + Leaflet) — diimpor lazily di map_picker.py
        'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebChannel', 'PySide6.QtNetwork',
        # Editor arsitektur (Results) — render PDF impor & proses latar
        'PySide6.QtPdf', 'app.gui.arch_editor', 'app.reports.arch_design',
        'app.reports.arch_import', 'app.ocr',
    ] + collect_submodules('reportlab') + collect_submodules('docx')
      + _opt('pypdf') + _opt('pytesseract') + _mod('onnxruntime'),
    # onnxruntime: DLL inti dikumpulkan hook pyinstaller-hooks-contrib; sub-paket
    # alat (transformers/quantization/tools) tak dipakai OCR → dikecualikan
    excludes=['tkinter', 'PyQt5', 'PyQt6', 'IPython', 'jupyter',
              'onnxruntime.transformers', 'onnxruntime.quantization',
              'onnxruntime.tools', 'onnx', 'torch'],
    noarchive=False,
)
pyz = PYZ(a.pure)

# ONEFILE: seluruh binaries + datas dimasukkan ke dalam EXE (tanpa COLLECT).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='HPPStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # tanpa jendela console
    icon='assets/icon.ico',
    version='assets/version_info.txt',   # metadata penerbit -> tab Details .exe
)
