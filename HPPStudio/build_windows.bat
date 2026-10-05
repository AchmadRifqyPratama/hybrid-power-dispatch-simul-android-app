@echo off
REM ============================================================
REM  HPP Studio - build .exe standalone (Windows)
REM  Memakai venv di %LOCALAPPDATA% (hindari batas panjang path).
REM ============================================================
setlocal
cd /d "%~dp0"

set "VENV=%LOCALAPPDATA%\hppstudio-venv"
if not exist "%VENV%\Scripts\python.exe" (
    echo [!] Environment belum ada. Jalankan run_dev.bat lebih dulu.
    pause
    exit /b 1
)

REM --- Pastikan SEMUA dependensi (termasuk OCR terbawa) ada di venv build ------
REM PyInstaller hanya membungkus paket yang TERPASANG di venv ini; paket opsional
REM yang hilang (mis. onnxruntime) akan dilewati diam-diam -> fitur hilang di .exe.
echo Menyinkronkan dependensi build ...
"%VENV%\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller || goto :err
"%VENV%\Scripts\python.exe" -c "from app import ocr;import sys;ok=ocr.available();print('OCR terbawa:', 'siap' if ok else 'TIDAK AKTIF - '+ocr.last_error());sys.exit(0 if ok else 1)"
if errorlevel 1 (
    echo.
    echo [!] OCR terbawa tidak aktif - .exe akan dibuat TANPA pembacaan teks gambar.
    choice /M "Lanjutkan build"
    if errorlevel 2 exit /b 1
)
"%VENV%\Scripts\python.exe" -c "import pypdf" >nul 2>&1 || echo [i] pypdf tidak ada - teks PDF tidak dibaca di .exe.

echo Build .exe dengan PyInstaller ...
"%VENV%\Scripts\python.exe" -m PyInstaller hpp_studio.spec --noconfirm || goto :err

REM --- Sidik jari SHA-256 untuk verifikasi keaslian oleh penerima ----------
set "HASH="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "dist\HPPStudio\HPPStudio.exe" SHA256') do (
    if not defined HASH set "HASH=%%H"
)
set "HASH=%HASH: =%"
> "dist\HPPStudio\SHA256SUMS.txt" echo %HASH% *HPPStudio.exe

echo.
echo ============================================================
echo  Selesai! Aplikasi ada di:  dist\HPPStudio\HPPStudio.exe
echo  Salin seluruh folder dist\HPPStudio untuk distribusi
echo  (mis. ZIP dulu agar penerima menerima 1 berkas).
echo.
echo  SHA-256 HPPStudio.exe (sidik jari keaslian):
echo    %HASH%
echo  Tersimpan di: dist\HPPStudio\SHA256SUMS.txt
echo ============================================================
pause
goto :eof

:err
echo [!] Build gagal. Periksa pesan di atas.
pause
exit /b 1
