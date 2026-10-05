@echo off
REM ============================================================
REM  HPP Studio - verifikasi keaslian unduhan (SHA-256)
REM
REM  Untuk PENERIMA berkas. Letakkan verify_download.bat di folder
REM  yang SAMA dengan HPPStudio.exe, lalu klik dua kali. Skrip ini
REM  membandingkan sidik jari SHA-256 berkas dengan nilai resmi
REM  (dari SHA256SUMS.txt bila ada, atau yang Anda tempel sendiri).
REM  COCOK  = berkas asli & utuh.   TIDAK COCOK = jangan dijalankan.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM --- Berkas yang diverifikasi (argumen / seret-jatuh / default .exe) ---
set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=HPPStudio.exe"
if not exist "%TARGET%" (
    echo [!] Berkas "%TARGET%" tidak ditemukan di folder ini.
    echo     Letakkan verify_download.bat di sebelah HPPStudio.exe,
    echo     atau seret berkas .exe ke atas ikon verify_download.bat.
    pause
    exit /b 1
)

REM --- Hitung SHA-256 aktual (certutil bawaan Windows) ---
set "ACTUAL="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%TARGET%" SHA256') do (
    if not defined ACTUAL set "ACTUAL=%%H"
)
set "ACTUAL=%ACTUAL: =%"

REM --- Hash resmi: dari SHA256SUMS.txt bila ada, selain itu minta tempel ---
set "EXPECT="
if exist "SHA256SUMS.txt" (
    for /f "usebackq tokens=1 delims= " %%A in ("SHA256SUMS.txt") do (
        if not defined EXPECT set "EXPECT=%%A"
    )
)
if not defined EXPECT (
    echo.
    echo Tempel nilai SHA-256 resmi dari pengirim, lalu tekan Enter:
    set /p "EXPECT=> "
)
set "EXPECT=%EXPECT: =%"

echo.
echo   Berkas : %TARGET%
echo   Aktual : %ACTUAL%
echo   Resmi  : %EXPECT%
echo.
if /i "%ACTUAL%"=="%EXPECT%" (
    echo   ================  COCOK / MATCH  ================
    echo   Berkas ASLI dan utuh - aman dijalankan.
) else (
    echo   ============  TIDAK COCOK / MISMATCH  ============
    echo   PERINGATAN: sidik jari berbeda. Berkas mungkin rusak saat
    echo   diunduh atau telah diubah. JANGAN dijalankan; minta ulang
    echo   berkas asli dari pengirim.
)
echo.
pause
