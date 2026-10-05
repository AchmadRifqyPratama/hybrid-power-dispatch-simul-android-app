@echo off
REM ============================================================
REM  HPP Studio - build SATU BERKAS .exe (onefile) untuk Windows
REM  Distribusi cukup dengan membagikan: dist\HPPStudio.exe
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

echo Membersihkan hasil build lama ...
if exist build rmdir /s /q build
if exist "dist\HPPStudio.exe" del /q "dist\HPPStudio.exe"

echo Build SATU BERKAS .exe dengan PyInstaller ...
"%VENV%\Scripts\python.exe" -m PyInstaller hpp_studio_onefile.spec --noconfirm || goto :err

REM --- Sidik jari SHA-256 untuk verifikasi keaslian oleh penerima ----------
set "HASH="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "dist\HPPStudio.exe" SHA256') do (
    if not defined HASH set "HASH=%%H"
)
set "HASH=%HASH: =%"
> "dist\SHA256SUMS.txt" echo %HASH% *HPPStudio.exe

echo.
echo ============================================================
echo  Selesai!  Berkas tunggal ada di:  dist\HPPStudio.exe
echo  Cukup BAGIKAN berkas dist\HPPStudio.exe itu saja.
echo.
echo  SHA-256 (sidik jari keaslian):
echo    %HASH%
echo  Tersimpan di: dist\SHA256SUMS.txt
echo  Kirim nilai SHA-256 ini lewat jalur tepercaya (mis. email/chat)
echo  agar penerima dapat memverifikasi berkas dengan verify_download.bat.
echo ============================================================
pause
goto :eof

:err
echo [!] Build gagal. Periksa pesan di atas.
pause
exit /b 1
