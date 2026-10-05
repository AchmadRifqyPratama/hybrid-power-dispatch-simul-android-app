@echo off
REM ============================================================
REM  HPP Studio - pasang / perbarui dependensi ke venv
REM  Pakai ini bila muncul error "No module named ..." saat
REM  menjalankan dari sumber (mis. setelah ada paket baru
REM  seperti reportlab untuk laporan PDF).
REM ============================================================
setlocal
cd /d "%~dp0"

set "VENV=%LOCALAPPDATA%\hppstudio-venv"
if not exist "%VENV%\Scripts\python.exe" (
    echo [!] Environment belum ada. Jalankan run_dev.bat lebih dulu
    echo     (skrip itu membuat venv sekaligus memasang dependensi).
    pause
    exit /b 1
)

echo Memasang/memperbarui dependensi dari requirements.txt ...
"%VENV%\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
"%VENV%\Scripts\python.exe" -c "from app import ocr;print('OCR terbawa:', 'siap' if ocr.available() else 'TIDAK AKTIF - '+ocr.last_error())"

echo.
echo ============================================================
echo  Selesai. Dependensi sudah sinkron (termasuk onnxruntime untuk OCR).
echo  Silakan buka lagi aplikasi lewat run_dev.bat.
echo ============================================================
pause
goto :eof

:err
echo [!] Gagal memasang dependensi. Periksa koneksi internet / pesan di atas.
pause
exit /b 1
