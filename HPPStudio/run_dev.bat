@echo off
REM ============================================================
REM  HPP Studio (desktop) - jalankan mode pengembangan
REM  - Memilih Python 3.10-3.13 otomatis (PySide6 belum
REM    menyediakan paket untuk Python 3.14).
REM  - Virtual environment diletakkan di %LOCALAPPDATA% agar
REM    terhindar dari batas panjang path Windows & OneDrive.
REM ============================================================
setlocal
cd /d "%~dp0"

set "VENV=%LOCALAPPDATA%\hppstudio-venv"
set "PYEXE="

for %%V in (3.12 3.13 3.11 3.10) do (
    if not defined PYEXE (
        py -%%V -c "import sys" >nul 2>&1 && set "PYEXE=py -%%V"
    )
)
if not defined PYEXE (
    python -c "import sys; raise SystemExit(0 if (3,10)<=sys.version_info<(3,14) else 1)" >nul 2>&1 && set "PYEXE=python"
)

if not defined PYEXE (
    echo.
    echo [!] Tidak menemukan Python 3.10-3.13.
    echo     PySide6 belum menyediakan paket siap pasang untuk Python 3.14.
    echo     Pasang Python 3.12 dari https://www.python.org/downloads/
    echo     lalu jalankan ulang berkas ini.
    echo.
    echo     Untuk memverifikasi engine tanpa GUI:  python selftest.py
    echo.
    pause
    exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
    echo Membuat virtual environment di %VENV% ...
    %PYEXE% -m venv "%VENV%" || goto :err
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip
    echo Menginstal dependensi ...
    "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
)

REM --- Sinkronkan dependensi bila ada paket baru (mis. reportlab) -----------
REM Probe impor paket inti; bila ADA yang hilang, pasang ulang requirements.
"%VENV%\Scripts\python.exe" -c "import PySide6,pyqtgraph,numpy,pandas,matplotlib,openpyxl,reportlab,docx" >nul 2>&1
if errorlevel 1 (
    echo Menyinkronkan dependensi ^(terdeteksi paket baru/hilang^) ...
    "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
)

REM --- OCR terbawa (impor gambar/PDF CAD) + pembaca teks PDF --------------------
REM Model OCR sudah ada di app\ocr\models; yang dibutuhkan hanya onnxruntime.
REM Tidak fatal: bila gagal (mis. offline), aplikasi tetap jalan tanpa OCR.
"%VENV%\Scripts\python.exe" -c "import onnxruntime,pypdf" >nul 2>&1
if errorlevel 1 (
    echo Memasang komponen OCR terbawa - onnxruntime dan pypdf ...
    "%VENV%\Scripts\python.exe" -m pip install "onnxruntime>=1.16" "pypdf>=4.0"
    if errorlevel 1 echo [i] OCR belum terpasang - impor gambar tetap bisa, tanpa pembacaan teks.
)

"%VENV%\Scripts\python.exe" -c "import sys,PySide6;print('Python',sys.version.split()[0],'| PySide6',PySide6.__version__)"
"%VENV%\Scripts\python.exe" -c "from app import ocr;print('OCR terbawa:', 'siap' if ocr.available() else 'TIDAK AKTIF - '+ocr.last_error())"
"%VENV%\Scripts\python.exe" main.py
goto :eof

:err
echo.
echo [!] Gagal menyiapkan environment. Bila muncul error panjang path,
echo     aktifkan Long Path Windows atau pindahkan proyek ke C:\Dev\HPP.
pause
exit /b 1
