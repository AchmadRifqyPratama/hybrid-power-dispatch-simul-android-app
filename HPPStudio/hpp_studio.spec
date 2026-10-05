# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller hpp_studio.spec
# Hasil:  dist/HPPStudio/HPPStudio.exe  (mode onedir — start-up cepat)

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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HPPStudio',
    debug=False,
    strip=False,
    upx=False,
    console=False,          # tanpa jendela console
    icon='assets/icon.ico',
    version='assets/version_info.txt',   # metadata penerbit -> tab Details .exe
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name='HPPStudio',
)
