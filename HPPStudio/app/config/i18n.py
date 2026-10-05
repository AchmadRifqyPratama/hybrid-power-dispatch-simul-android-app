"""Internasionalisasi (i18n) — Bahasa Indonesia (ID) & English (EN).

Cara pakai:
    from ...config.i18n import tr
    QLabel(tr('Belum ada hasil'))

Teks di dalam kode ditulis apa adanya (campuran ID untuk kalimat dan EN untuk
label parameter). Fungsi ``tr`` menerjemahkan ke bahasa aktif:

* Bahasa aktif **EN** → cari di tabel ID→EN. Bila tak ada, teks dikembalikan
  apa adanya (label parameter memang sudah berbahasa Inggris).
* Bahasa aktif **ID** → cari di tabel EN→ID. Bila tak ada, teks dikembalikan
  apa adanya (kalimat memang sudah berbahasa Indonesia).

Sengaja tanpa berkas .po/.mo agar tidak menambah dependensi dan tetap ringan
untuk PyInstaller maupun Android.
"""
from __future__ import annotations

LANGUAGES = {'ID': 'ID', 'EN': 'EN'}
_lang = 'ID'


def set_language(code: str) -> str:
    global _lang
    _lang = 'EN' if str(code).upper().startswith('EN') else 'ID'
    return _lang


def get_language() -> str:
    return _lang


# ---------------------------------------------------------------- ID -> EN
_EN = {
    # --- v157: self consumption pada sizing per site (batch multi-site) ---
    'Sizing per Site (PV / INV / BESS / PCS / Self Cons.)': 'Per-Site Sizing (PV / INV / BESS / PCS / Self Cons.)',
    'Centang "Custom" pada sebuah site untuk memakai sizing khusus; bila tidak, site memakai nilai halaman Parameters. Anda juga dapat mengisi via Excel: kolom params (PV/INV/BESS/PCS/SELF CONS) × Unit × satu kolom per site (nama kolom = nama berkas data).':
        'Tick "Custom" on a site to use dedicated sizing; otherwise the site uses the Parameters page values. You can also fill via Excel: a params column (PV/INV/BESS/PCS/SELF CONS) × Unit × one column per site (column name = data file name).',
    'Self consumption BESS (kWh per jam) untuk site ini — sama dengan parameter Battery → Self Consumption.':
        'BESS self consumption (kWh per hour) for this site — same as the Battery → Self Consumption parameter.',
    # --- v156: self consumption BESS & kurva SOH ---
    'Konsumsi sendiri BESS (HVAC, BMS, PCS idle, dll.) dalam kWh per jam, berlaku sepanjang waktu selama BESS terpasang. Merupakan beban TAMBAHAN: pembangkitan harus memasok beban + self consumption. Isi 0 untuk menonaktifkan.':
        'BESS self consumption (HVAC, BMS, PCS idle, etc.) in kWh per hour, applied at all times while a BESS is installed. It is an ADDITIONAL load: generation must supply the load + self consumption. Enter 0 to disable.',
    'Sumber utama pemasok self consumption BESS. PV+BESS: dipasok PV lalu discharge BESS lebih dulu; kekurangannya dipasok Grid lalu DEG. DEG/Grid: dipasok Grid (bila tersedia) lalu DEG lebih dulu; kekurangannya dipasok kelebihan PV lalu BESS.':
        'Main supplier of the BESS self consumption. PV+BESS: supplied first by PV, then BESS discharge; any shortfall comes from the Grid, then DEG. DEG/Grid: supplied first by the Grid (when available), then DEG; any shortfall comes from surplus PV, then BESS.',
    'Cara menentukan SOH BESS per tahun. Annual Degradation: SOH = (1 − degradasi)^umur. SOH Curve (Excel): SOH per tahun dari berkas Excel/CSV 2 kolom (kolom 1 = tahun/umur, kolom 2 = SOH).':
        'How the yearly BESS SOH is determined. Annual Degradation: SOH = (1 − degradation)^age. SOH Curve (Excel): yearly SOH from a 2-column Excel/CSV file (column 1 = year/age, column 2 = SOH).',
    'Tabel SOH per tahun (umur BESS) dari berkas Excel/CSV: kolom pertama = tahun (End of Year, 0 = baru), kolom kedua = SOH (mis. 94.2% / 0.942 / 94.2). Umur di antara titik diinterpolasi linear; di luar tabel diekstrapolasi dengan laju tahun terakhir. Setelah penggantian BESS, kurva dimulai lagi dari tahun 0.':
        'Yearly SOH table (BESS age) from an Excel/CSV file: first column = year (End of Year, 0 = new), second column = SOH (e.g. 94.2% / 0.942 / 94.2). Ages between points are interpolated linearly; beyond the table the last year\'s rate is extrapolated. After a BESS replacement the curve restarts from year 0.',
    'Impor Excel…': 'Import Excel…',
    'Hapus': 'Clear',
    'Belum ada berkas — impor Excel/CSV 2 kolom (tahun, SOH)': 'No file yet — import a 2-column Excel/CSV (year, SOH)',
    '{n} titik · tahun {a:g}–{b:g} · SOH {s0:.1f}% → {s1:.1f}%': '{n} points · year {a:g}–{b:g} · SOH {s0:.1f}% → {s1:.1f}%',
    'Pilih berkas kurva SOH BESS': 'Select BESS SOH curve file',
    'Kurva SOH': 'SOH curve',
    'Berkas tidak dapat dibaca: {e}': 'The file could not be read: {e}',
    'Tidak ditemukan data SOH. Berkas harus berisi 2 kolom: kolom pertama tahun, kolom kedua SOH pada tahun tersebut.':
        'No SOH data found. The file must contain 2 columns: the first column is the year, the second the SOH in that year.',
    'Selesai — {n} tahun tersimulasi (degradasi PV {pv}%/th, BESS mengikuti kurva SOH impor, inflasi {infl}%, discount {disc}%).':
        'Done — {n} years simulated (PV degradation {pv}%/yr, BESS follows the imported SOH curve, inflation {infl}%, discount {disc}%).',
    # --- v154: pilihan halaman PDF ---
    'Halaman PDF yang berisi arsitektur (disarankan: {p}):': 'PDF page that contains the architecture (suggested: {p}):',
    # --- v150: toolbar ringkas ---
    'Impor…': 'Import…',
    'Dari konfigurasi': 'From config',
    'Gambar impor': 'Imported image',
    # --- v148: rapikan rute & kartu impor ---
    'Rapikan rute': 'Tidy routes',
    'Rutekan ulang semua kabel secara ortogonal (tidak menembus kotak & tidak saling berimpit) — sama dengan gambar laporan.': 'Re-route all cables orthogonally (not through boxes and without overlaps) — same as the report figure.',
    # --- v147: tata letak laporan 'sesuai gambar' ---
    'Tata letak:': 'Layout:',
    'Sesuai gambar (posisi blok dipertahankan)': 'As drawn (block positions kept)',
    'Diagram satu garis otomatis': 'Automatic single-line diagram',
    # --- v145: OCR terbawa (app/ocr) ---
    'OCR terbawa HPP Studio memerlukan paket "onnxruntime" yang belum terpasang pada Python yang menjalankan aplikasi ini:\n{py}\n\nPasang sekarang (± 15 MB, sekali saja)? Tanpa OCR, gambar tetap diimpor tetapi teks komponen tidak terbaca.': 'HPP Studio\'s built-in OCR needs the "onnxruntime" package, which is not installed in the Python running this application:\n{py}\n\nInstall it now (≈ 15 MB, one time)? Without OCR the drawing is still imported, but component text is not read.',
    'Detail: {e}': 'Details: {e}',
    'Memasang onnxruntime…': 'Installing onnxruntime…',
    'Pemasangan onnxruntime gagal. Jalankan manual:\n"{py}" -m pip install onnxruntime': 'Installing onnxruntime failed. Run it manually:\n"{py}" -m pip install onnxruntime',
    'Teks pada gambar tidak dapat dibaca: OCR terbawa HPP Studio memerlukan paket onnxruntime pada Python aplikasi ({py}). Jalankan install_deps.bat / run_dev.bat terbaru, lalu impor ulang. Sementara itu gambar asli tetap dapat dipakai di laporan.': "The text in the drawing could not be read: HPP Studio's built-in OCR needs the onnxruntime package in the application's Python ({py}). Run the latest install_deps.bat / run_dev.bat, then import again. Meanwhile the original drawing can still be used in the report.",
    # --- v144: OCR RapidOCR ---
    'Teks pada gambar tidak dapat dibaca karena mesin OCR belum terpasang (teks AutoCAD/SHX pada PDF berupa garis, bukan teks). Pasang paket Python berikut lalu impor ulang — tanpa aplikasi tambahan:\n    pip install rapidocr_onnxruntime\nSementara itu gambar asli tetap dapat dipakai di laporan, dan gambar ditaruh sebagai latar untuk digambar ulang manual.': 'The text in the drawing could not be read because no OCR engine is installed (AutoCAD/SHX text in a PDF is stored as lines, not text). Install the following Python package and import again — no extra application needed:\n    pip install rapidocr_onnxruntime\nMeanwhile the original drawing can still be used in the report, and the image is placed as a background for manual redrawing.',
    'Teks pada gambar tidak terbaca (gambar tanpa teks atau resolusi terlalu rendah). Gambar ditaruh sebagai latar — gambar ulang komponen di atasnya; gambar asli tetap dapat dipakai di laporan.': 'The text in the image could not be read (no text, or resolution too low). The image is placed as a background — redraw the components over it; the original drawing can still be used in the report.',
    # --- v143: impor lembar CAD & pilihan gambar laporan ---
    'Pilih gambar arsitektur yang dimuat di laporan — bandingkan kedua pratinjau:': 'Choose the architecture figure used in the report — compare both previews:',
    'Gambar asli': 'Original drawing',
    'Topologi digambar ulang': 'Redrawn topology',
    'Diagram jendela utama gambar impor, apa adanya (blok judul, label grid & legenda gambar tidak dimuat; legenda warna dirangkum ulang).': "The imported drawing's main-area diagram as is (title block, grid labels and drawing legend left out; the colour legend is restated).",
    'Komponen & sambungan hasil pembacaan, digambar ulang otomatis dalam format diagram satu garis standar laporan.': "Components and connections as read, automatically redrawn in the report's standard single-line format.",
    'Tidak ada gambar asli — impor gambar/PDF arsitektur untuk dapat memilih opsi ini.': 'No original drawing — import an architecture image/PDF to enable this option.',
    'Laporan: gambar asli': 'Report: original drawing',
    'Laporan: topologi digambar ulang': 'Report: redrawn topology',
    'Lembar gambar teknik terdeteksi: hanya diagram pada JENDELA UTAMA yang diambil (blok judul, label grid & legenda dikecualikan).': 'Engineering drawing sheet detected: only the diagram in the MAIN DRAWING AREA is taken (title block, grid labels and legend excluded).',
    '• jenis sambungan dibaca dari WARNA garis{lg}': '• connection types read from the line COLOUR{lg}',
    ' (sesuai legenda gambar)': ' (per the drawing legend)',
    '• {e} komponen eksisting (garis tepi biru), {f} rencana (abu-abu)': '• {e} existing components (blue outline), {f} future (grey)',
    'Untuk laporan, pilih di tab Pratinjau Laporan: GAMBAR ASLI atau TOPOLOGI DIGAMBAR ULANG (kedua pratinjau ditampilkan berdampingan).': 'For the report, choose in the Report Preview tab: ORIGINAL DRAWING or REDRAWN TOPOLOGY (both previews are shown side by side).',
    # --- v142: editor arsitektur (kabel komunikasi, bentuk) ---
    'Jenis kabel untuk sambungan baru pada mode Connect. Otomatis: daya AC/DC menurut komponen; RS485 untuk EMS dan antar perangkat sejenis; TCP/IP untuk Ethernet Hub / Server.': 'Cable type for new connections in Connect mode. Automatic: AC/DC power by component; RS485 for the EMS and between devices of the same type; TCP/IP for the Ethernet Hub / Server.',
    'Kabel: otomatis': 'Cable: automatic',
    'Mode Polygon: klik titik-titik sudut; klik-ganda atau Enter untuk selesai, Esc untuk batal.': 'Polygon mode: click the corner points; double-click or press Enter to finish, Esc to cancel.',
    'Tarik kabel untuk menambah titik belok; tarik titik belok untuk memindahkan, klik-ganda untuk menghapus.': 'Drag the cable to add a bend point; drag a bend point to move it, double-click to remove it.',
    'Tarik sudut kanan-bawah untuk mengubah ukuran. Komponen di dalam bentuk ditampilkan sebagai grup berlabel pada laporan.': 'Drag the bottom-right corner to resize. Components inside the shape are shown as a labelled group in the report.',
    'Tarik ujung rel di kanvas untuk mengubah panjangnya.': 'Drag the bus ends on the canvas to change its length.',
    'Tarik verteks untuk mengubah bentuk; klik-ganda sisi untuk menambah verteks, klik-ganda verteks untuk menghapus. Komponen di dalamnya menjadi grup berlabel pada laporan.': 'Drag a vertex to reshape; double-click an edge to add a vertex, double-click a vertex to remove it. Components inside become a labelled group in the report.',
    # --- v141: editor arsitektur sistem ---
    '(opsional)': '(optional)',
    '(otomatis)': '(automatic)',
    'Arsitektur Sistem': 'System Architecture',
    'Belum dapat digambar — tambahkan komponen dan sambungkan ke rel AC / beban.': 'Cannot be drawn yet — add components and connect them to an AC bus / load.',
    'Buat rancangan awal dari konfigurasi sistem di Parameters (dapat diedit).': 'Create a starting design from the system configuration in Parameters (editable).',
    'Desain': 'Design',
    'Gambar & PDF': 'Images & PDF',
    'Gambar tidak dapat dibaca.': 'The image cannot be read.',
    'Ganti rancangan saat ini dengan hasil impor?': 'Replace the current design with the import result?',
    'Ganti rancangan saat ini dengan rancangan dari konfigurasi?': 'Replace the current design with one generated from the configuration?',
    'Gunakan arsitektur ini pada laporan studi kelayakan': 'Use this architecture in the feasibility report',
    'Halaman PDF yang berisi arsitektur:': 'PDF page containing the architecture:',
    'Hapus seluruh isi kanvas?': 'Clear the entire canvas?',
    'Hasil pengenalan ({m}):\n• {n} komponen\n• {c} sambungan dari garis gambar\n• {s} sambungan disarankan (kuning) — mohon ditinjau': 'Recognition result ({m}):\n• {n} components\n• {c} connections from drawn lines\n• {s} suggested connections (amber) — please review',
    'Impor Gambar Arsitektur': 'Import Architecture Drawing',
    'Impor gambar arsitektur (PNG/JPG/PDF). Sistem mengenali komponen & sambungan, lalu Anda dapat meninjau dan mengoreksinya.': 'Import an architecture drawing (PNG/JPG/PDF). The system recognises components and connections, which you can then review and correct.',
    'Jenis': 'Type',
    'Klik untuk menambah, atau seret ke kanvas': 'Click to add, or drag onto the canvas',
    'Komponen': 'Components',
    'Kosongkan rating untuk memakai nilai dari Parameters: {r}': 'Leave the rating empty to use the value from Parameters: {r}',
    'Lebar rel': 'Bus width',
    'Mengenali komponen & sambungan…': 'Recognising components and connections…',
    'Modul QtPdf tidak tersedia pada instalasi PySide6 ini; ekspor PDF ke PNG lalu impor gambarnya.': 'The QtPdf module is not available in this PySide6 installation; export the PDF to PNG and import the image.',
    'PDF tidak dapat dibaca.': 'The PDF cannot be read.',
    'Pembacaan topologi & catatan konsistensi': 'Topology reading & consistency notes',
    'Periksa hasilnya, lalu buka tab Pratinjau Laporan untuk melihat versi profesionalnya.': 'Check the result, then open the Report Preview tab to see the professional version.',
    'Pilih & pindahkan komponen (V)': 'Select & move components (V)',
    'Pratinjau Laporan': 'Report Preview',
    'Properti': 'Properties',
    'Sambungan': 'Connection',
    'Sambungan ini disarankan dari tata letak (tanpa bukti garis di gambar). Terima atau hapus.': 'This connection is suggested from the layout (no line found in the drawing). Accept or delete it.',
    'Seret komponen ke kanvas. Mode Connect: tarik dari satu komponen ke komponen lain. Ctrl+scroll = zoom, tombol tengah = geser.': 'Drag components onto the canvas. Connect mode: drag from one component to another. Ctrl+scroll = zoom, middle button = pan.',
    'Tampilan pada laporan (digambar ulang otomatis dari topologi):': 'As shown in the report (automatically redrawn from the topology):',
    'Tarik dari satu komponen ke komponen lain untuk menyambungkan (C)': 'Drag from one component to another to connect them (C)',
    'Teks pada gambar tidak dapat dibaca (OCR Tesseract belum terpasang, atau gambar tanpa teks). Gambar ditaruh sebagai latar — gambar ulang komponen di atasnya, atau impor PDF yang memiliki lapisan teks.': 'The text in the image could not be read (Tesseract OCR is not installed, or the image has no text). The image is placed as a background — redraw the components over it, or import a PDF that has a text layer.',
    'Transparansi gambar impor': 'Imported image transparency',
    'Tutup tanpa menyimpan perubahan?': 'Close without saving changes?',
    'lapisan teks PDF': 'PDF text layer',
    'tidak ada (teks tak terbaca)': 'none (text unreadable)',
    '{n} item dipilih': '{n} items selected',
    '{n} komponen · {e} sambungan': '{n} components · {e} connections',
    '{s} saran (kuning) perlu ditinjau': '{s} suggestions (amber) to review',
    'Rancang arsitektur sistem dari nol atau impor gambar (PNG/JPG/PDF); sistem menggambar ulang secara profesional untuk laporan studi kelayakan.': 'Design the system architecture from scratch or import a drawing (PNG/JPG/PDF); the system redraws it professionally for the feasibility report.',
    # --- v135: Dashboard navigation ---
    'Pin:': 'Pin:',
    'Esc / klik-ganda: lepas': 'Esc / double-click: clear',
    'Ctrl+scroll: zoom · Shift+scroll: geser · klik: pin pembanding · klik-ganda: reset': 'Ctrl+scroll: zoom · Shift+scroll: pan · click: pin reference · double-click: reset',

    # --- v133: untranslated strings traced in EN mode ---
    'langkah': 'steps',
    '(langkah)': '(steps)',
    'MA Window\n(langkah)': 'MA Window\n(steps)',
    'Semua berkas (*)': 'All files (*)',
    'hasil_simulasi': 'simulation_results',
    'studi_kelayakan': 'feasibility_study',
    'hasil_optimasi': 'optimization_results',
    'hasil_optimasi_batch': 'optimization_batch_results',
    'hasil_multi_year': 'multi_year_results',
    'Tutup panel input manual': 'Close the manual input panel',
    'SOC Minimum harus < SOC Maksimum.': 'SOC Minimum must be < SOC Maximum.',
    'Berkas tidak ditemukan:': 'File not found:',
    'Berkas ini bukan proyek HPP Studio.': 'This file is not an HPP Studio project.',
    'Data profil dalam berkas tidak konsisten.': 'Profile data in the file is inconsistent.',
    'Berkas rusak atau bukan proyek HPP Studio': 'File is corrupt or not an HPP Studio project',
    'Berkas dibuat oleh versi HPP Studio yang lebih baru. Perbarui aplikasi terlebih dahulu.': 'This file was created by a newer version of HPP Studio. Please update the application first.',

    # --- Optimization: variabel mode Advanced, durasi & mulai (v101/v102) ---
    'Optimasi Variabel Mode Advanced': 'Advanced Mode Optimization Variables',
    'Sizing:': 'Sizing:',
    'Durasi:': 'Duration:',
    'Durasi (jendela) yang disimulasikan tiap iterasi, dari titik '
    'Mulai. Lebih pendek = lebih cepat; KPI (LCOE, PV generation, dll.) '
    'diekstrapolasi ke setahun. "Setahun penuh" = tanpa ekstrapolasi.':
        'The window simulated per iteration, from the Start point. '
        'Shorter = faster; KPIs (LCOE, PV generation, etc.) are extrapolated '
        'to a full year. "Full year" = no extrapolation.',
    'Bulan awal jendela simulasi tiap iterasi (durasi < setahun).':
        'Start month of each iteration’s simulation window (duration '
        '< 1 year).',
    'Batas pencarian Auto Optimizer diturunkan otomatis dari profil beban & '
    'PV; grid disempitkan iteratif hingga konvergen. Kapasitas inverter '
    'diikat INV = PV / rasio DC/AC.':
        'Auto Optimizer search bounds are derived automatically from the load '
        '& PV profiles; the grid is refined iteratively until convergence. '
        'Inverter capacity is tied to INV = PV / DC-AC ratio.',
    # --- Parameters: tooltip bantuan (help caption) mode Advanced (v100) ---
    # Ditambahkan agar caption bantuan pd halaman Parameters mengikuti bahasa EN.
    'Lintang lokasi proyek (−90…90). Pilih lewat tombol "Pilih di Peta" pada halaman Home.':
        'Project location latitude (−90…90). Pick it with the "Pick on Map" button on the Home page.',
    'Bujur lokasi proyek (−180…180). Pilih lewat tombol "Pilih di Peta" pada halaman Home.':
        'Project location longitude (−180…180). Pick it with the "Pick on Map" button on the Home page.',
    'Suplai yang DIKURANGI saat BESS discharge (mode Advanced): Grid saja, DEG saja, atau keduanya. Memengaruhi Peak Shaving & Load Shifting dan penerapan discharge ke suplai.':
        'The supply REDUCED when the BESS discharges (Advanced mode): Grid only, DEG only, or both. Affects Peak Shaving & Load Shifting and how discharge is applied to supply.',
    'Haluskan output PV yang dikirim ke sistem. Setpoint output PV = Moving Average (MA) PV EnetAC, lalu laju NAIK/TURUN-nya dibatasi PV Ramp-Up/Down Limit. BESS mengisi kekurangan (setpoint > PV EnetAC → discharge) & menyerap kelebihan (setpoint < PV EnetAC → charge) agar output PV mengikuti kurva halus; DEG menjadi base load. Tak dapat aktif bersamaan dengan Firming — mengaktifkan salah satu otomatis menonaktifkan yang lain.':
        'Smooth the PV output delivered to the system. PV output setpoint = Moving Average (MA) of PV EnetAC, then its RAMP UP/DOWN rate is capped by the PV Ramp-Up/Down Limit. The BESS fills the shortfall (setpoint > PV EnetAC → discharge) & absorbs the surplus (setpoint < PV EnetAC → charge) so PV output follows a smooth curve; DEG becomes the base load. Cannot be active at the same time as Firming — enabling one automatically disables the other.',
    'Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.':
        "This mode's PRIORITY number in the co-dispatch (1 = highest). When several modes are active, the higher-priority mode gets the SOC/PCS budget first.",
    'Batas laju NAIK (kW/menit) output PV ter-smoothed (setpoint). 0 = tanpa batas naik (hanya MA).':
        'Limit on the RAMP-UP rate (kW/min) of the smoothed PV output (setpoint). 0 = no up-ramp limit (MA only).',
    'Batas laju TURUN (kW/menit) output PV ter-smoothed (setpoint). 0 = tanpa batas turun (hanya MA).':
        'Limit on the RAMP-DOWN rate (kW/min) of the smoothed PV output (setpoint). 0 = no down-ramp limit (MA only).',
    'Ukuran jendela Moving Average (jumlah nilai PV EnetAC sebelumnya). Setpoint = rata-rata bergerak PV sepanjang window ini, lalu dibatasi PV Ramp-Up/Down Limit. Besar = lebih halus/lag besar.':
        'Moving Average window size (number of previous PV EnetAC values). Setpoint = moving average of PV over this window, then capped by the PV Ramp-Up/Down Limit. Larger = smoother/more lag.',
    'PV+BESS men-deliver DAYA KONSTAN (target) sebagai base load dalam JENDELA firming: BESS discharge saat PV di bawah target & charge dari kelebihan PV saat di atas target. Di LUAR jendela, PV dipakai untuk charge BESS saja (tak diinjeksi). Tak dapat aktif bersamaan dengan Smoothing — mengaktifkan salah satu otomatis menonaktifkan yang lain.':
        'PV+BESS deliver CONSTANT POWER (target) as base load within the firming WINDOW: the BESS discharges when PV is below target & charges from the PV surplus when above target. OUTSIDE the window, PV is used only to charge the BESS (not injected). Cannot be active at the same time as Smoothing — enabling one automatically disables the other.',
    'Daya konstan (kW) yang di-deliver PV+BESS sebagai base load. BESS menutup kekurangan (PV < target) & menyerap kelebihan (PV > target).':
        'Constant power (kW) delivered by PV+BESS as base load. The BESS covers the shortfall (PV < target) & absorbs the surplus (PV > target).',
    'Penentu KAPAN Firming aktif: "PV Power" (ambang daya PV EnetAC) atau "Time" (jam mulai/berhenti). Di luar jendela, PV hanya untuk charge BESS.':
        'Determines WHEN Firming is active: "PV Power" (a PV EnetAC power threshold) or "Time" (start/stop hour). Outside the window, PV only charges the BESS.',
    'Pagi: Firming MULAI saat PV EnetAC melampaui nilai ini. Sebelum itu PV hanya untuk charge BESS. (mode Firming Window = PV Power)':
        'Morning: Firming STARTS when PV EnetAC rises above this value. Before that, PV only charges the BESS. (Firming Window = PV Power)',
    'Sore: Firming BERHENTI saat PV EnetAC turun di bawah nilai ini. Setelahnya PV hanya untuk charge BESS. (mode PV Power)':
        'Evening: Firming STOPS when PV EnetAC falls below this value. After that, PV only charges the BESS. (PV Power mode)',
    'Jam (0–24) Firming MULAI. Sebelumnya PV hanya untuk charge BESS. (mode Firming Window = Time)':
        'Hour (0–24) when Firming STARTS. Before it, PV only charges the BESS. (Firming Window = Time)',
    'Jam (0–24) Firming BERHENTI. Setelahnya PV hanya untuk charge BESS. (mode Time)':
        'Hour (0–24) when Firming STOPS. After it, PV only charges the BESS. (Time mode)',
    'Persentase energi guna BESS (SOC maks−min) yang DITAHAN sebagai cadangan (0–100%). Dispatch normal tak menyentuhnya.':
        'Percentage of the BESS usable energy (SOC max−min) HELD as reserve (0–100%). Normal dispatch does not touch it.',
    # --- Dashboard: durasi simulasi & zoom grafik (v83) ---
    'Durasi simulasi:': 'Simulation duration:',
    '1 hari': '1 day',
    '1 minggu': '1 week',
    '1 bulan': '1 month',
    'Setahun penuh': 'Full year',
    'Perbesar': 'Zoom in',
    'Perkecil': 'Zoom out',
    'Atur ulang tampilan': 'Reset view',
    'Durasi (jendela) yang BENAR-BENAR disimulasikan, dihitung dari titik Mulai. '
    'Interval lebih halus membatasi durasi maksimum (mis. 1 menit → maks 1 bulan; '
    '1 detik → maks 1 hari). KPI kWh/tahun diekstrapolasi dari jendela ini.':
        'The window that is ACTUALLY simulated, counted from the Start point. '
        'A finer interval caps the maximum duration (e.g. 1 minute → max 1 month; '
        '1 second → max 1 day). Annual kWh KPIs are extrapolated from this window.',
    # --- EMS BESS multi-mode (v78): tab grafik ---
    'Grafik EMS multi-mode (mode Advanced): aliran daya & laju ramp PV untuk '
    'memverifikasi PV Smoothing. Mengikuti Interval tampilan & Window dari tab '
    'Time Series; jalankan Run dengan mode Advanced.':
        'Multi-mode EMS chart (Advanced mode): power flows & PV ramp rate to '
        'verify PV Smoothing. Follows the Display interval & Window from the '
        'Time Series tab; run with Advanced mode enabled.',
    # --- EMS BESS multi-mode (v78): tooltip mode ---
    'Batasi LAJU PERUBAHAN daya PV yang dikirim ke sistem (atasi fluktuasi awan). BESS mengisi kekurangan saat PV turun & menyerap saat PV melonjak. Malam (PV=0) tak aktif.':
        'Limit the RATE OF CHANGE of PV power delivered to the system (ride through cloud fluctuation). BESS fills the shortfall when PV drops & absorbs when PV surges. Inactive at night (PV=0).',
    'Batas laju perubahan output PV (kW per menit). Bila PV berubah lebih cepat, BESS meredamnya agar |ramp PV| ≤ batas ini.':
        'Limit on PV output rate of change (kW per minute). If PV changes faster, the BESS damps it so that |PV ramp| ≤ this limit.',
    'Simpan energi saat surplus/luar-puncak, lepaskan saat puncak untuk mengurangi grid/DEG. Memperhitungkan efisiensi charge/discharge (RTE).':
        'Store energy during surplus/off-peak, release during peak to reduce grid/DEG. Accounts for charge/discharge efficiency (RTE).',
    'Jam MULAI jendela puncak (0-23): di dalamnya BESS discharge; di luar BESS diisi. Start > End → melewati tengah malam.':
        'START hour of the peak window (0-23): inside it the BESS discharges; outside it charges. Start > End → wraps past midnight.',
    'Jam AKHIR jendela puncak (0-23, eksklusif).':
        'END hour of the peak window (0-23, exclusive).',
    'Tarif grid luar puncak (finansial). Impor jam puncak memakai Grid Tariff biasa.':
        'Off-peak grid tariff (financial). Peak-hour imports use the normal Grid Tariff.',
    'Batasi daya puncak dari grid/DEG. BESS discharge saat net load melebihi ambang. discharge = max(0, net load − ambang).':
        'Cap the peak power from grid/DEG. BESS discharges when net load exceeds the threshold. discharge = max(0, net load − threshold).',
    'Ambang net load. Di atas ambang, BESS discharge menutup selisihnya (sebatas SOC & PCS).':
        'Net-load threshold. Above it, the BESS discharges to cover the difference (bounded by SOC & PCS).',
    'Serap surplus PV (yang jika tidak akan ter-curtail) ke BESS selama ada kapasitas charge.':
        'Absorb PV surplus (that would otherwise be curtailed) into the BESS while charge capacity is available.',
    'Cegah DG beroperasi di bawah minimum loading: kelebihan output DG (di atas beban) dialihkan mengisi BESS. Pakai Minimum Loading (grup Diesel).':
        'Prevent DG from operating below minimum loading: the DG excess (above the load) is diverted to charge the BESS. Uses Minimum Loading (Diesel group).',
    'BESS meredam perubahan net load agar DG tak perlu naik lebih cepat dari batas ramp-nya.':
        'The BESS damps net-load changes so the DG need not ramp faster than its ramp limit.',
    'Batas laju NAIK output DG (kW/menit). BESS menutup kelebihannya.':
        'DG output ramp-UP limit (kW/min). The BESS covers the excess.',
    'Batas laju TURUN output DG (kW/menit).':
        'DG output ramp-DOWN limit (kW/min).',
    'Tahan sebagian kapasitas BESS (SOC & daya PCS) agar SELALU tersedia untuk kejadian tak terduga (DG trip, PV anjlok, lonjakan beban). Dispatch normal tak boleh memakai cadangan ini. Tak dapat aktif bersamaan dengan Backup — mengaktifkan salah satu otomatis menonaktifkan yang lain.':
        'Hold part of the BESS capacity (SOC & PCS power) so it is ALWAYS available for unexpected events (DG trip, PV drop, load surge). Normal dispatch must not use this reserve. Cannot be active at the same time as Backup — enabling one automatically disables the other.',
    'Fraksi energi guna BESS (SOC maks−min) yang DITAHAN sebagai cadangan (0-1). Dispatch normal tak menyentuhnya.':
        'Fraction of usable BESS energy (SOC max−min) HELD as reserve (0-1). Normal dispatch does not touch it.',
    'Daya PCS yang DITAHAN sebagai cadangan (tak dipakai dispatch normal).':
        'PCS power HELD as reserve (not used by normal dispatch).',
    'BESS (+PV bila tersedia) mengambil alih PENUH pelayanan beban saat Grid DAN DEG sama-sama tak tersedia (outage) — mengesampingkan Smoothing/Firming kapan pun outage terjadi. Di luar outage: BESS hanya charge oportunistik dari surplus PV (siaga), tak pernah discharge. Tak dapat aktif bersamaan dengan Operating Reserve — mengaktifkan salah satu otomatis menonaktifkan yang lain.':
        'The BESS (+PV when available) takes over FULL load service when Grid AND DEG are BOTH unavailable (outage) — overriding Smoothing/Firming whenever an outage occurs. Outside an outage: the BESS only charges opportunistically from surplus PV (standby), never discharges. Cannot be active at the same time as Operating Reserve — enabling one automatically disables the other.',
    # --- Fungsi BESS Advanced (v74/v75): Mode / Fungsi / Target / 4 strategi ---
    'Standard: dispatch seperti biasa (prioritas beban). Advanced: pilih '
    'FUNGSI BESS khusus (Peak Shaving, dll.) di atas dispatch dasar.':
        'Standard: dispatch as usual (load priority). Advanced: choose a '
        'dedicated BESS FUNCTION (Peak Shaving, etc.) on top of the base '
        'dispatch.',
    'Fungsi BESS saat mode Advanced. Peak Shaving: batasi output sumber pd '
    'ambang tertentu. Load Shifting / Arbitrage: geser pemakaian sumber dari '
    'jam puncak ke luar puncak. PV Smoothing: haluskan laju perubahan '
    'antarmuka sumber. Spinning Reserve: simpan sebagian energi BESS sebagai '
    'cadangan operasi.':
        'BESS function in Advanced mode. Peak Shaving: cap the source output '
        'at a set threshold. Load Shifting / Arbitrage: shift source usage '
        'from peak hours to off-peak. PV Smoothing: smooth the ramp of the '
        'source interface. Spinning Reserve: hold part of the BESS energy as '
        'operating reserve.',
    'Sumber yang DIBIDIK fungsi BESS. Grid: strategi bekerja pada impor grid '
    '(mis. batasi/geser impor). DEG: strategi bekerja pada output genset '
    'diesel (mis. batasi/geser output DEG, BESS menutup selisihnya). Pilih '
    'salah satu.':
        'The source the BESS function TARGETS. Grid: the strategy acts on grid '
        'import (e.g. cap/shift import). DEG: the strategy acts on the diesel '
        'genset output (e.g. cap/shift DEG output, BESS covers the '
        'difference). Choose one.',
    'Batas maksimum output sumber terpilih (Grid/DEG) untuk beban. Bila output '
    'melampaui ambang ini, BESS discharge menutup selisihnya (sebatas SOC & '
    'PCS). 0 = nonaktif. PV & pengisian normal mengisi ulang BESS.':
        'Maximum output of the selected source (Grid/DEG) for the load. When '
        'output exceeds this threshold, the BESS discharges to cover the '
        'difference (bounded by SOC & PCS). 0 = off. PV & normal charging '
        'refill the BESS.',
    'Jam MULAI jendela puncak (0-23). Di dalam jendela puncak BESS discharge '
    'menggantikan sumber terpilih; di luar puncak BESS diisi dari grid. Jika '
    'Start > End, jendela melewati tengah malam.':
        'START hour of the peak window (0-23). Inside the peak window the BESS '
        'discharges to displace the selected source; outside the peak the BESS '
        'is charged from the grid. If Start > End, the window wraps past '
        'midnight.',
    'Jam AKHIR jendela puncak (0-23, eksklusif). Lihat Peak Window Start.':
        'END hour of the peak window (0-23, exclusive). See Peak Window Start.',
    'Tarif grid LUAR puncak (dipakai finansial saat Arbitrage aktif; impor '
    'pada jam puncak memakai Grid Tariff biasa). Selisih tarif inilah sumber '
    'penghematan arbitrase.':
        'Off-peak grid tariff (used financially when Arbitrage is active; '
        'imports during peak hours use the normal Grid Tariff). This tariff '
        'difference is the source of arbitrage savings.',
    'Batas perubahan antarmuka sumber terpilih antar langkah simulasi. Bila '
    'melonjak lebih cepat dari ini, BESS charge/discharge meredamnya. 0 = '
    'nonaktif. Paling bermakna pada interval sub-jam.':
        'Limit on the change of the selected source interface between '
        'simulation steps. If it swings faster than this, the BESS '
        'charges/discharges to damp it. 0 = off. Most meaningful at sub-hourly '
        'intervals.',
    'Fraksi energi guna BESS (SOC maks−min) yang DITAHAN sebagai cadangan '
    'operasi untuk sumber terpilih (0-1). Cadangan ditahan saat sumber aktif '
    '& dilepas saat sumber tak tersedia (menutup kontingensi). 0 = nonaktif.':
        'Fraction of usable BESS energy (SOC max−min) HELD as operating '
        'reserve for the selected source (0-1). The reserve is held while the '
        'source is active and released when the source is unavailable (to '
        'cover a contingency). 0 = off.',
    # --- Case filter dropdown (v14b) ---
    'Pilih Case': 'Select Cases',
    'Tampilkan semua': 'Show all',
    'Sembunyikan semua': 'Hide all',
    'Pilih case mana yang blok warnanya ditampilkan.': "Choose which cases' colored blocks are shown.",
    # --- Mode Case Analysis (v14) ---
    'Tandai grafik dengan blok warna sesuai 16 case (Grid status × PV × BESS). Arahkan kursor ke blok untuk melihat keterangan case.': 'Mark the chart with colored blocks for the 16 cases (Grid status × PV × BESS). Hover a block to see the case description.',
    # --- opsi per status grid (v9/v10) ---
    'Skenario prioritas beban saat GRID PADAM (grid status = 0). Grid memasok 0 kW sehingga posisi "Grid" dalam rantai tak berpengaruh — opsi diringkas ke strategi yang benar-benar berbeda (urutan PV/BESS/DEG). Saat DEG Interlock with Grid nonaktif, genset dapat naik sebelum BESS (PV → DEG → BESS / DEG → PV → BESS). Dipakai bila "Load Priority Follows Grid Status" aktif.': 'Load supply priority when the GRID IS DOWN (grid status = 0). The grid supplies 0 kW, so the position of "Grid" in the chain has no effect — the options are reduced to genuinely distinct strategies (PV/BESS/DEG order). When DEG Interlock with Grid is off, the genset may come before BESS (PV → DEG → BESS / DEG → PV → BESS). Used when "Load Priority Follows Grid Status" is active.',
    'Aktif: atur "DEG Interlock with PV-BESS" dan "Allow DEG Charging to BESS" terpisah untuk saat grid tersedia (status 1) dan grid padam (status 0). Engine memakai setelan status-1 pada jam grid menyala dan setelan status-0 pada jam grid padam. Nonaktif: satu setelan berlaku untuk semua jam.': 'On: set "DEG Interlock with PV-BESS" and "Allow DEG Charging to BESS" separately for when the grid is available (status 1) and when it is down (status 0). The engine uses the status-1 settings during grid-up hours and the status-0 settings during outage hours. Off: a single setting applies to all hours.',
    'Aktif (default): genset boleh paralel & berbagi beban — dispatch seperti sekarang. Nonaktif: genset TIDAK dapat sinkron — hanya SATU genset menyala pada satu waktu; yang terkecil kapasitasnya menyala lebih dulu, dan saat mencapai maximum loading ia mati lalu genset lebih besar yang menyala, dan seterusnya.': 'On (default): gensets may run in parallel and share load — dispatch as now. Off: gensets CANNOT synchronise — only ONE genset runs at a time; the smallest-capacity unit starts first, and when it reaches maximum loading it shuts off and the next larger genset starts, and so on.',
    'Aktif: saat GRID PADAM atau proyek TANPA GRID, minimal SATU genset (terkecil) WAJIB menyala & melayani beban lebih dulu. Bila beban < MINIMUM LOADING: jika "Allow DEG Charging to BESS" AKTIF, DEG naik ke minimum loading & kelebihannya mengisi BESS (selama SOC < SOC maksimum & PCS cukup); jika NONAKTIF, DEG hanya sebesar beban (di bawah minimum loading) tanpa mengisi BESS. Saat grid TERSEDIA fitur ini tak berpengaruh — DEG bekerja normal. Nonaktif (default): DEG hanya menyala saat dibutuhkan.': 'On: when the GRID IS DOWN or the project has NO GRID, at least ONE genset (the smallest) MUST run and serve the load first. When the load is below the MINIMUM LOADING: if "Allow DEG Charging to BESS" is ON, the DEG rises to its minimum loading and the surplus charges the BESS (while SOC < maximum SOC and PCS headroom remains); if OFF, the DEG runs only at the load level (below minimum loading) without charging the BESS. When the grid IS available this feature has no effect — the DEG runs normally. Off (default): the DEG runs only when needed.',
    'Genset mana yang WAJIB menyala lebih dulu sebagai grid-forming saat "DEG Must Always Run" aktif & grid padam. "Auto" memilih — tiap jam — genset yang MINIMUM LOADING-nya (kapasitas × Lmin) paling dekat ke beban; jadi saat beban rendah dipakai genset lebih KECIL agar paling mendekati minimum loadingnya (surplus terkecil). DEG-1/2/3 = genset tetap. Bila memilih unit 0 kW / tak aktif, otomatis kembali ke Auto.': 'Which genset MUST start first as the grid-forming unit when "DEG Must Always Run" is on and the grid is down. "Auto" picks — each hour — the genset whose MINIMUM LOADING (capacity × Lmin) is closest to the load; so at low load a SMALLER genset is used, running closest to its minimum loading (least surplus). DEG-1/2/3 = fixed genset. If you pick a 0 kW / inactive unit, it automatically falls back to Auto.',
    'DEG Interlock with PV-BESS saat GRID TERSEDIA (status 1). Dipakai bila "DEG Options Follow Grid Status" aktif.': 'DEG Interlock with PV-BESS when the GRID IS AVAILABLE (status 1). Used when "DEG Options Follow Grid Status" is active.',
    'DEG Interlock with PV-BESS saat GRID PADAM (status 0). Dipakai bila "DEG Options Follow Grid Status" aktif.': 'DEG Interlock with PV-BESS when the GRID IS DOWN (status 0). Used when "DEG Options Follow Grid Status" is active.',
    'Allow DEG Charging to BESS saat GRID TERSEDIA (status 1). Otomatis nonaktif bila interlock status-1 aktif (bus DEG terpisah).': 'Allow DEG Charging to BESS when the GRID IS AVAILABLE (status 1). Automatically disabled when the status-1 interlock is active (DEG bus is separated).',
    'Allow DEG Charging to BESS saat GRID PADAM (status 0). Otomatis nonaktif bila interlock status-0 aktif (bus DEG terpisah).': 'Allow DEG Charging to BESS when the GRID IS DOWN (status 0). Automatically disabled when the status-0 interlock is active (DEG bus is separated).',
    # ---- navigasi & judul halaman ----
    'Home': 'Home', 'Parameters': 'Parameters', 'Data': 'Data',
    'Dashboard': 'Dashboard', 'Optimization': 'Optimization',
    'Results': 'Results',
    'Input Data': 'Input Data',
    'Simulasi': 'Simulation',
    'Grafik': 'Charts',
    'Optimizer': 'Optimizer',
    'Param': 'Param',

    # ---- umum / tombol ----
    'Tutup': 'Close', 'Batal': 'Cancel', 'Terapkan': 'Apply',
    'Sukses': 'Success', 'Gagal': 'Failed', 'Error': 'Error',
    'Simpan Excel': 'Save Excel', 'Simpan Laporan': 'Save Report',
    'Simpan Multi-Year': 'Save Multi-Year',
    'Export Excel': 'Export Excel',
    'Generate Report (HTML)': 'Generate Report (HTML)',
    'Generate Feasibility Study (PDF)': 'Generate Feasibility Study (PDF)',
    'Generate Feasibility Study': 'Generate Feasibility Study',
    'Simpan Studi Kelayakan (PDF)': 'Save Feasibility Study (PDF)',
    'Simpan Studi Kelayakan': 'Save Feasibility Study',
    'Susun laporan studi kelayakan PDF profesional (teknis + '
    'finansial + sensitivitas; bagian Multi-Year disertakan bila '
    'sudah dijalankan).':
        'Compile a professional PDF feasibility study (technical + financial + '
        'sensitivity; the Multi-Year section is included once it has been run).',
    'Susun laporan studi kelayakan profesional (PDF atau Word/DOCX; '
    'teknis + finansial + sensitivitas; bagian Multi-Year disertakan '
    'bila sudah dijalankan).':
        'Compile a professional feasibility study (PDF or Word/DOCX; technical '
        '+ financial + sensitivity; the Multi-Year section is included once it '
        'has been run).',
    'Aspek Laporan': 'Report Aspects',
    'Pilih aspek yang ingin ditampilkan pada laporan studi kelayakan:':
        'Choose which aspects to include in the feasibility study report:',
    'Aspek Teknis': 'Technical Aspect',
    'Aspek Finansial': 'Financial Aspect',
    'Modul laporan belum terpasang': 'Report module not installed',
    'Pustaka pembuat laporan (reportlab untuk PDF / python-docx untuk Word) '
    'belum terpasang di environment ini. Jalankan install_deps.bat (atau '
    'run_dev.bat) untuk memasangnya, lalu buka aplikasi kembali.':
        'The report libraries (reportlab for PDF / python-docx for Word) are '
        'not installed in this environment. Run install_deps.bat (or '
        'run_dev.bat) to install them, then reopen the app.',
    'Catatan: jalankan Multi-Year untuk menyertakan proyeksi lifetime '
    'terperinci.':
        'Note: run Multi-Year to include the detailed lifetime projection.',
    'Modul PDF belum terpasang': 'PDF module not installed',
    'Pustaka "reportlab" untuk membuat PDF belum terpasang di environment ini. '
    'Jalankan install_deps.bat (atau run_dev.bat) untuk memasangnya, lalu buka '
    'aplikasi kembali.':
        'The "reportlab" library used to build PDFs is not installed in this '
        'environment. Run install_deps.bat (or run_dev.bat) to install it, then '
        'reopen the app.',
    'Export Multi-Year…': 'Export Multi-Year…',
    'Export Hasil…': 'Export Results…',
    'Export hasil optimasi': 'Export optimization results',
    'Tersimpan:': 'Saved:',
    'Light Mode': 'Light Mode', 'Dark Mode': 'Dark Mode',
    'Developed by': 'Developed by',
    # --- gerbang login (kata sandi) ---
    'Selamat datang': 'Welcome',
    'Masukkan kata sandi untuk melanjutkan': 'Enter your password to continue',
    'Masukkan kata sandi': 'Enter password',
    'Tampilkan kata sandi': 'Show password',
    'Sembunyikan kata sandi': 'Hide password',
    'Masuk': 'Sign in',
    'Keluar': 'Exit',
    'Kata sandi salah. Coba lagi.': 'Incorrect password. Try again.',
    'part of Akartha Energy': 'part of Akartha Energy',

    # ---- halaman Home ----
    'Identitas Proyek': 'Project Identity',
    'Project Name': 'Project Name', 'Customer': 'Customer',
    'Site Name': 'Site Name', 'Location': 'Location',
    'Created Date': 'Created Date', 'Simulation Year': 'Simulation Year',

    # ---- halaman Data ----
    'Format: kolom "Datetime" + "Load (kW)" / "PV ENetAC (kW)" '
    '/ "Grid Status" — 8760 atau 8784 baris.':
        'Format: columns "Datetime" + "Load (kW)" / "PV ENetAC (kW)" '
        '/ "Grid Status" — 8760 or 8784 rows.',
    'Format: kolom "Datetime" + "Load (kW)" / "PV ENetAC (kW)" '
    '/ "Grid Status". Per jam (8760/8784 baris) atau resolusi '
    'tinggi dgn timestamp konsisten hingga 1 tahun (mis. 525.600 '
    'baris = 1 menit setahun). Interval terdeteksi dari timestamp.':
        'Format: columns "Datetime" + "Load (kW)" / "PV ENetAC (kW)" '
        '/ "Grid Status". Hourly (8760/8784 rows) or high-resolution '
        'data with consistent timestamps up to 1 year (e.g. 525,600 '
        'rows = 1 minute for a year). Interval is detected from the '
        'timestamps.',
    'Import Excel/CSV…': 'Import Excel/CSV…',
    'Buat Template Excel…': 'Create Excel Template…',
    'Input Load Manual (24 jam)…': 'Manual Load Input (24 hours)…',
    'Input Load Manual — pola 24 jam (diulang tiap hari)':
        'Manual Load Input — 24-hour pattern (repeated daily)',
    'Isi beban tiap jam (kW). Pola ini disalin ke seluruh hari dalam '
    'setahun. PV ENetAC memakai profil default bawaan; Grid Status '
    'mengikuti parameter Grid (1 penuh bila ada grid, 0 penuh bila '
    'off-grid).':
        'Enter hourly load (kW). This pattern is copied to every day of the '
        'year. PV ENetAC uses the bundled default profile; Grid Status '
        'follows the Grid parameter (all 1 when a grid exists, all 0 when '
        'off-grid).',
    '✕  Tutup': '✕  Close',
    'Isi dari Profil Saat Ini': 'Fill from Current Profile',
    'Isi Rata…': 'Fill Flat…',
    '▶  Terapkan ke Setahun': '▶  Apply to Full Year',
    'Status Data': 'Data Status',
    'Load Profile': 'Load Profile', 'PV ENetAC': 'PV ENetAC',
    'Grid Status': 'Grid Status',
    'DEG Status': 'DEG Status',
    'belum diimpor': 'not imported',
    'default: selalu tersedia': 'default: always available',
    'Pratinjau Profil (720 jam pertama)': 'Profile Preview (first 720 hours)',
    'Import gagal': 'Import failed',
    'Import berhasil': 'Import successful',
    'Kolom terbaca:': 'Columns read:',
    'Template': 'Template', 'Simpan template': 'Save template',
    'Template tersimpan di': 'Template saved to',
    'Data kosong': 'Empty data',
    'Isi setidaknya satu jam dengan nilai > 0.':
        'Fill at least one hour with a value > 0.',
    'Data dibuat': 'Data created',
    'PV tidak tersedia': 'PV not available',
    'Terisi rata-rata profil saat ini.': 'Filled with the current profile average.',
    'Terisi rata sebesar nilai tertinggi.': 'Filled flat at the highest value.',
    'Belum ada data': 'No data yet',
    'Impor profil dahulu, atau isi manual.':
        'Import a profile first, or fill it manually.',
    'jam · total': 'h · total', 'puncak': 'peak',

    # ---- Dashboard ----
    '▶  Run Simulation': '▶  Run Simulation',
    'Import data lalu jalankan simulasi.': 'Import data then run the simulation.',
    'Belum ada data — buka halaman Data untuk mengimpor Load Profile & '
    'PV ENetAC.':
        'No data yet — open the Data page to import the Load Profile & '
        'PV ENetAC.',
    'Menjalankan simulasi 8760 jam …': 'Running 8760-hour simulation …',
    'Menjalankan simulasi {iv} · {n} langkah …':
        'Running {iv} simulation · {n} steps …',
    'Menjalankan simulasi {iv} · {n} langkah … {p}%':
        'Running {iv} simulation · {n} steps … {p}%',
    'Mulai:': 'Start:',
    'Bulan awal jendela simulasi (interval sub-tahun). Diabaikan untuk '
    'interval 1 jam / 30 menit yang mencakup setahun penuh.':
        'Start month of the simulation window (sub-year intervals). Ignored for '
        '1 hour / 30 minute intervals that cover the full year.',
    'Tanggal awal jendela simulasi (1-31).':
        'Start day of the simulation window (1-31).',
    'Simulasi gagal.': 'Simulation failed.',
    'Simulasi selesai. Lihat halaman Results untuk KPI lengkap & laporan.':
        'Simulation complete. See the Results page for full KPIs & report.',
    'Time Series': 'Time Series', 'Energy Mix': 'Energy Mix',
    'Bulanan': 'Monthly', 'Heatmap': 'Heatmap',
    'Daya (kW)': 'Power (kW)', 'Waktu': 'Time',
    'Tampil (jam):': 'Window (hours):',
    'Lebar jendela tampilan time series (jumlah jam/data yang ditampilkan)':
        'Time-series window width (number of hours/points shown)',
    'Rentang tampil:': 'Visible range:',
    'auto': 'auto',
    # Dialog langkah/tick sumbu (klik-kanan pada sumbu)
    'Langkah Sumbu': 'Axis Step',
    '0 = otomatis': '0 = automatic',
    'Langkah tick sumbu Y-kiri (kW)': 'Y-left axis tick spacing (kW)',
    'Langkah tick sumbu Y-kanan (%)': 'Y-right axis tick spacing (%)',
    'Langkah tick sumbu X (jam)': 'X axis tick spacing (hours)',
    'Energy Mix (porsi beban terlayani)': 'Energy Mix (share of load served)',
    'Metode:': 'Metric:', 'Variabel:': 'Variable:',
    'Energi (kWh)': 'Energy (kWh)', 'Fuel Diesel (L)': 'Diesel Fuel (L)',
    'Curtailment / Excess (kWh)': 'Curtailment / Excess (kWh)',
    'Energi (kWh)  ': 'Energy (kWh)  ',
    'Jam dalam hari': 'Hour of day', 'Hari dalam tahun': 'Day of year',
    'Diesel (kW)': 'Diesel (kW)', 'PV Excess (kW)': 'PV Excess (kW)',

    # ---- Results ----
    'KPI Teknis': 'Technical KPIs',
    'KPI Finansial': 'Financial KPIs',
    'Cash Flow Kumulatif (savings vs baseline)':
        'Cumulative Cash Flow (savings vs baseline)',
    'Tahun': 'Year', 'Rp': 'Rp',
    'Belum ada hasil — jalankan simulasi di Dashboard.':
        'No results yet — run the simulation on the Dashboard.',
    'Hasil simulasi terbaru.': 'Latest simulation results.',
    'Belum ada hasil': 'No results yet',
    'Jalankan simulasi terlebih dahulu.': 'Run the simulation first.',
    'Laporan tersimpan:': 'Report saved:',
    'Buka dengan browser apa pun.': 'Open it with any browser.',
    'Simulasi Multi-Year (Project Lifetime)':
        'Multi-Year Simulation (Project Lifetime)',
    'Simulasi seluruh umur proyek (lifetime) untuk data aktif, serta batch '
    'multi-site.':
        'Full project-lifetime simulation for the active data, plus multi-site '
        'batch.',
    'Tunggu batch multi-site yang sedang berjalan selesai.':
        'Wait for the running multi-site batch to finish.',
    'Tunggu simulasi multi-year yang sedang berjalan selesai.':
        'Wait for the running multi-year simulation to finish.',
    '▶  Run Multi-Year': '▶  Run Multi-Year',
    'Simulasikan seluruh lifetime dengan degradasi PV & BESS per tahun '
    'serta eskalasi harga (inflasi) dan discount rate.':
        'Simulate the whole lifetime with yearly PV & BESS degradation plus '
        'price escalation (inflation) and discount rate.',
    'Menjalankan simulasi seluruh lifetime …':
        'Running the full lifetime simulation …',
    'Menjalankan simulasi seluruh lifetime … {p}%':
        'Running the full lifetime simulation … {p}%',
    'Multi-year gagal.': 'Multi-year run failed.',
    'Grafik per tahun:': 'Yearly chart:',
    'Tahun ke-': 'Year',
    'Impor Load Profile & PV ENetAC dahulu.':
        'Import the Load Profile & PV ENetAC first.',
    'Import Load Profile & PV ENetAC dahulu.':
        'Import the Load Profile & PV ENetAC first.',

    # ---- kolom tabel multi-year ----
    'PV Efektif (kWp)': 'Effective PV (kWp)',
    'BESS SOH (%)': 'BESS SOH (%)',
    'BESS SOH': 'BESS SOH',
    'BESS Efektif (kWh)': 'Effective BESS (kWh)',
    'PV Gen (kWh)': 'PV Gen (kWh)', 'RF (%)': 'RF (%)',
    'Fuel (L)': 'Fuel (L)', 'Grid Imp (kWh)': 'Grid Imp (kWh)',
    'Unused (kWh)': 'Unused (kWh)', 'Unserved (kWh)': 'Unserved (kWh)',
    'OPEX (Rp)': 'OPEX (Rp)', 'Savings (Rp)': 'Savings (Rp)',
    'Kumulatif (Rp)': 'Cumulative (Rp)',
    'Renewable Fraction (%)': 'Renewable Fraction (%)',
    'PV Generation (kWh)': 'PV Generation (kWh)',
    'Unused/Curtailment (kWh)': 'Unused/Curtailment (kWh)',
    'Cashflow Kumulatif (Rp)': 'Cumulative Cashflow (Rp)',

    # ---- Optimization ----
    'Grid search seluruh kombinasi — tervektorisasi + multiprocessing di '
    'semua core CPU.':
        'Grid search over all combinations — vectorized + multiprocessing on '
        'all CPU cores.',
    'Mode Sizing:': 'Sizing Mode:',
    'Manual Range (Grid Search)': 'Manual Range (Grid Search)',
    'Auto Optimizer (tanpa range)': 'Auto Optimizer (no range)',
    'Range PV': 'PV Range', 'Range PV Inverter': 'PV Inverter Range',
    'Range BESS': 'BESS Range',
    'Objective & Kontrol': 'Objective & Control',
    'Prioritas 1': 'Priority 1', 'Prioritas 2': 'Priority 2',
    'Prioritas 3': 'Priority 3',
    '— (tidak dipakai)': '— (not used)',
    'Toleransi antar prioritas': 'Tolerance between priorities',
    'Jumlah kombinasi': 'Number of combinations',
    'otomatis (iteratif)': 'automatic (iterative)',
    'Run Optimization': 'Run Optimization',
    'PCS BESS (Charge / Discharge)': 'BESS PCS (Charge / Discharge)',
    'Mode': 'Mode', 'Nilai': 'Value',
    'Ikut C-rate dari Parameters': 'Follow C-rate from Parameters',
    'C-rate tetap (1/jam)': 'Fixed C-rate (1/h)',
    'Daya PCS tetap (kW)': 'Fixed PCS power (kW)',
    'Terapkan Terbaik ke Parameters': 'Apply Best to Parameters',
    'Diterapkan': 'Applied',
    'Terbaik:': 'Best:',
    'feasible': 'feasible',
    'Optimasi gagal.': 'Optimization failed.',

    # ---- ekspor / laporan ----
    'Info': 'Info', 'Per Tahun': 'Per Year',
    'Ringkasan Lifetime': 'Lifetime Summary',
    'Hasil Optimasi': 'Optimization Results',
    'Metrik': 'Metric',
    'Item': 'Item',
    'Ganti BESS (Rp)': 'BESS Replacement (Rp)',
    'Baseline (Rp)': 'Baseline (Rp)',
    'Diesel Fuel (L)': 'Diesel Fuel (L)',
    'Grid Import (kWh)': 'Grid Import (kWh)',
    'Grid Export (kWh)': 'Grid Export (kWh)',
    'Unused/Curtailment (kWh)': 'Unused/Curtailment (kWh)',
    'Payback (th)': 'Payback (yr)',
    'Jumlah Penggantian BESS': 'BESS Replacement Count',
    'Total Biaya Penggantian BESS (Rp)': 'Total BESS Replacement Cost (Rp)',
    'Laporan Simulasi Hybrid Power Plant':
        'Hybrid Power Plant Simulation Report',
    'Project:': 'Project:', 'Lokasi:': 'Location:', 'Site:': 'Site:',
    'Dibuat:': 'Created:', 'Konfigurasi:': 'Configuration:',
    'Dihasilkan oleh HPP Studio': 'Generated by HPP Studio',
    'Laporan Simulasi': 'Simulation Report',
    'Profil Operasi (minggu pertama)': 'Operation Profile (first week)',
    'Agregat Bulanan': 'Monthly Aggregates',
    'Heatmap Operasi': 'Operation Heatmaps',
    'ya': 'yes', 'tidak': 'no', 'tanpa grid': 'no grid',
    'Project Lifetime (th)': 'Project Lifetime (yr)',
    'BESS Lifetime (th)': 'BESS Lifetime (yr)',
    'Exported At': 'Exported At',
    'Bersihkan Hasil':
        'Clear Results',
    '▾  Sembunyikan Konfigurasi': '▾  Hide Configuration',
    '▸  Tampilkan Konfigurasi': '▸  Show Configuration',
    'Bersihkan Multi-Year':
        'Clear Multi-Year',
    'Hapus hasil simulasi beserta seluruh grafiknya.':
        'Remove the simulation results and all their charts.',
    'Hapus hasil simulasi beserta seluruh grafiknya?':
        'Remove the simulation results and all their charts?',
    'Hapus hasil simulasi multi-year?':
        'Remove the multi-year results?',
    'Hapus hasil optimasi?':
        'Remove the optimization results?',
    'Data siap — tekan Run Simulation.':
        'Data ready — press Run Simulation.',
    'Bersihkan Batch':
        'Clear Batch',
    'Hapus daftar berkas dan seluruh hasil batch agar dapat memulai dengan berkas data baru.':
        'Remove the file list and all batch results so you can start with new data files.',
    'Hapus daftar berkas dan seluruh hasil batch?':
        'Remove the file list and all batch results?',
    'Sedang berjalan':
        'Still running',
    'Hentikan proses yang sedang berjalan terlebih dahulu.':
        'Stop the running process first.',
    'Site:':
        'Site:',
    'Pilih site yang hasil terbaiknya akan diterapkan.':
        'Choose the site whose best result will be applied.',
    'Terapkan Site Terpilih ke Parameters':
        'Apply Selected Site to Parameters',
    'Salin sizing terbaik site ini ke halaman Parameters sekaligus memuat berkas datanya sebagai profil aktif.':
        "Copy this site's best sizing to the Parameters page and load its data file as the active profile.",
    'Sizing terbaik site {site} disalin ke Parameters:':
        'Best sizing for site {site} copied to Parameters:',
    'Profil data site ini ikut dimuat.':
        "This site's data profile was loaded.",
    'Profil data TIDAK dimuat.':
        'The data profile was NOT loaded.',
    'Site Name & koordinat ({la:.5f}, {lo:.5f}) disalin ke halaman Home.':
        'Site Name & coordinates ({la:.5f}, {lo:.5f}) copied to the Home page.',
    'Site Name disalin ke halaman Home.':
        'Site Name copied to the Home page.',
    'Berkas data tidak ditemukan:':
        'Data file not found:',
    'Opsi': 'Option',
    'Aktifkan Batch Multi-Site (beberapa berkas data)':
        'Enable Multi-Site Batch (several data files)',
    'Tampilkan bagian untuk menjalankan optimasi pada beberapa berkas '
    'data sekaligus.':
        'Show the section for running the optimization on several data '
        'files at once.',
    'Unused/Curtail': 'Unused/Curtail',

    'Batch Multi-Site (beberapa berkas data)':
        'Multi-Site Batch (several data files)',
    'Jalankan optimasi untuk beberapa berkas data sekaligus memakai parameter & objective yang sama. Nama site diambil dari nama berkas.':
        'Run the optimization for several data files at once using the same parameters & objective. The site name is taken from the file name.',
    'Pilih Berkas Data…':
        'Choose Data Files…',
    'Pilih Berkas Data':
        'Choose Data Files',
    '▶  Jalankan Batch':
        '▶  Run Batch',
    'Export Batch…':
        'Export Batch…',
    'Export Batch':
        'Export Batch',
    'Belum ada berkas dipilih.':
        'No files selected yet.',
    '{n} berkas dipilih:':
        '{n} files selected:',
    'Menjalankan {i}/{n}: {site} …':
        'Running {i}/{n}: {site} …',
    'Selesai — {n} site dioptimasi.':
        'Done — {n} sites optimized.',
    'Batch dibatalkan.':
        'Batch cancelled.',
    'Semua site gagal dioptimasi.':
        'All sites failed to optimize.',
    'Batch selesai dengan galat':
        'Batch finished with errors',
    'Sebagian site gagal':
        'Some sites failed',
    '{n} site gagal (dilewati)':
        '{n} site(s) failed (skipped)',
    '{n} site dilewati karena galat:':
        '{n} site(s) skipped due to errors:',
    'Site':
        'Site',
    # --- Koordinat PV per site (batch multi-site) ---
    'Koordinat PV:': 'PV coordinates:',
    'Ikuti halaman Home': 'Follow Home page',
    'Per site dari Excel (unduh PVGIS)': 'Per site from Excel (PVGIS download)',
    'Semua site memakai PV ENetAC dari berkas datanya (seperti biasa).':
        'All sites use PV ENetAC from their own data file (as usual).',
    'Tiap site memakai koordinat sendiri dari berkas Excel. PV '
    'diunduh dari PVGIS memakai tilt/azimuth, mounting, loss, dan '
    'year dari jendela Select Project Location; PV base mengikuti '
    'halaman Parameters.':
        'Each site uses its own coordinates from an Excel file. PV is '
        'downloaded from PVGIS using tilt/azimuth, mounting, loss and year '
        'from the Select Project Location window; PV base follows the '
        'Parameters page.',
    'Tiap site memakai koordinat sendiri dari berkas Excel. PV '
    'diunduh dari PVGIS memakai tilt/azimuth, mounting, loss, dan '
    'year dari jendela Select Project Location.':
        'Each site uses its own coordinates from an Excel file. PV is '
        'downloaded from PVGIS using tilt/azimuth, mounting, loss and year '
        'from the Select Project Location window.',
    'Pilih Excel Koordinat…': 'Choose Coordinates Excel…',
    'Pilih Excel Koordinat': 'Choose Coordinates Excel',
    'Template…': 'Template…',
    'Unduh templat Excel koordinat (kolom Site, Latitude, Longitude).':
        'Download a coordinates Excel template (columns Site, Latitude, '
        'Longitude).',
    'PV ENetAC diambil dari tiap berkas data (halaman Data).':
        'PV ENetAC is taken from each data file (Data page).',
    '{n} koordinat dimuat:': '{n} coordinates loaded:',
    'Pilih berkas Excel koordinat (kolom Site, Latitude, Longitude).':
        'Choose a coordinates Excel file (columns Site, Latitude, Longitude).',
    'Simpan Template Koordinat': 'Save Coordinates Template',
    'Template koordinat disimpan:': 'Coordinates template saved:',
    'Koordinat PV': 'PV Coordinates',
    'Pilih berkas Excel koordinat lebih dulu, atau ganti '
    'ke "Ikuti halaman Home".':
        'Choose a coordinates Excel file first, or switch to '
        '"Follow Home page".',
    'Mengunduh PV dari PVGIS per site …':
        'Downloading PV from PVGIS per site …',
    'Unduh PVGIS {i}/{n}: {site} …': 'PVGIS download {i}/{n}: {site} …',
    'Latitude': 'Latitude',
    'Longitude': 'Longitude',
    'Ringkasan Site':
        'Site Summary',
    'Jumlah Site':
        'Number of Sites',
    'Beban (kWh/th)':
        'Load (kWh/yr)',
    'Objective':
        'Objective',
    'Kandidat dievaluasi':
        'Candidates evaluated',
    'Feasible':
        'Feasible',
    'PV (kWp)':
        'PV (kWp)',
    'INV (kW)':
        'INV (kW)',
    'BESS (kWh)':
        'BESS (kWh)',
    'PCS (kW)':
        'PCS (kW)',
    'BESS Autonomy (jam)':
        'BESS Autonomy (h)',
    'LCOE (Rp/kWh)':
        'LCOE (Rp/kWh)',
    'NPV (Rp)':
        'NPV (Rp)',
    'CAPEX (Rp)':
        'CAPEX (Rp)',
    'Payback (th)':
        'Payback (yr)',
    'PV Generation (kWh/th)':
        'PV Generation (kWh/yr)',
    'Diesel Energy (kWh/th)':
        'Diesel Energy (kWh/yr)',
    'Diesel Fuel (L/th)':
        'Diesel Fuel (L/yr)',
    'Grid Import (kWh/th)':
        'Grid Import (kWh/yr)',
    'Unserved (kWh/th)':
        'Unserved (kWh/yr)',
    'PCS':
        'PCS',
    'PV Curtailment (%)': 'PV Curtailment (%)',

    'PV melayani beban lebih dulu (menyisakan minimum loading untuk grid); grid memikul sisanya; BESS hanya menutup kekurangan yang melebihi kapasitas grid; genset menjadi cadangan terakhir.':
        'PV serves the load first (leaving the minimum loading for the grid); the grid carries the remainder; the BESS only covers a shortfall beyond the grid capacity; the genset is the last resort.',
    'PV melayani beban lebih dulu; grid memikul sisanya sampai batas kapasitasnya; genset menutup kekurangan berikutnya (boleh paralel dengan grid); BESS menjadi cadangan terakhir.':
        'PV serves the load first; the grid carries the remainder up to its capacity; the genset covers the next shortfall (may run in parallel with the grid); the BESS is the last resort.',
    'Grid memikul beban lebih dulu hingga batas loading maksimumnya; PV lalu BESS menutup sisanya; genset menjadi cadangan terakhir.':
        'The grid carries the load first up to its maximum loading; PV then the BESS cover the remainder; the genset is the last resort.',
    'Grid memikul beban lebih dulu; genset langsung menutup kekurangan yang tidak sanggup dipikul grid (boleh paralel); PV lalu BESS melayani sisanya.':
        'The grid carries the load first; the genset immediately covers whatever the grid cannot carry (may run in parallel); PV then the BESS serve the remainder.',
    'Grid memikul beban lebih dulu (hormati batas loading); PV lalu BESS menutup sisanya; genset menjadi cadangan TERAKHIR namun boleh menyala paralel dengan grid untuk menutup kekurangan yang tidak sanggup dipikul grid + PV + BESS.':
        'The grid carries the load first (respecting its loading limits); PV then the BESS cover the remainder; the genset is the LAST resort but may run in parallel with the grid to cover a shortfall that grid + PV + BESS cannot carry.',
    ('Strategi otomatis mengikuti status grid tiap jam. '
     'Grid TERSEDIA: beban dilayani Grid → DEG → PV → BESS '
     '(genset membantu bila beban melebihi grid), pengisian BESS '
     'Grid → PV (sisa kapasitas grid mengisi BESS hingga ambang '
     '"Charge from Grid below SOC"); grid, DEG, PV, dan BESS boleh '
     'paralel. Grid PADAM: beban dilayani PV → BESS → DEG dengan '
     'DEG interlock PV-BESS (saat genset menyala ia memikul '
     'seluruh beban, PV hanya mengisi BESS). Membutuhkan grid '
     'aktif, ada DEG, dan DEG tidak interlock dengan grid.'):
        ('Strategy adapts automatically to the hourly grid status. '
         'GRID AVAILABLE: load served Grid → DEG → PV → BESS '
         '(the genset assists when load exceeds the grid), BESS charging '
         'Grid → PV (spare grid capacity charges the BESS up to the '
         '"Charge from Grid below SOC" threshold); grid, DEG, PV and BESS '
         'may run in parallel. GRID DOWN: load served PV → BESS → DEG with '
         'DEG interlocked to PV-BESS (when the genset runs it carries the '
         'whole load and PV only charges the BESS). Requires grid enabled, '
         'at least one DEG, and DEG not interlocked with the grid.'),
    ('Beban dilayani Grid → PV → BESS → DEG. Saat grid TERSEDIA: '
     'genset boleh menyala paralel dengan Grid maupun PV-BESS '
     '(hanya menutup kekurangan yang tak sanggup dipikul '
     'grid + PV + BESS). Saat grid PADAM: DEG interlock dengan '
     'PV-BESS — begitu genset menyala ia memikul SELURUH beban, '
     'PV hanya mengisi BESS, dan BESS tidak discharge. '
     'Membutuhkan grid aktif, ada DEG, dan DEG tidak interlock '
     'dengan grid.'):
        ('Load served Grid → PV → BESS → DEG. When the grid is AVAILABLE: '
         'the genset may run in parallel with both the grid and PV-BESS '
         '(only covering a shortfall that grid + PV + BESS cannot carry). '
         'When the grid is DOWN: DEG is interlocked with PV-BESS — once the '
         'genset starts it carries the WHOLE load, PV only charges the BESS, '
         'and the BESS does not discharge. Requires grid enabled, at least '
         'one DEG, and DEG not interlocked with the grid.'),
    'PV lalu BESS melayani beban lebih dulu (menyisakan minimum loading untuk grid); grid mengambil sisanya; genset menjadi cadangan terakhir. Cocok untuk memaksimalkan pemakaian energi surya.':
        'PV then the BESS serve the load first (leaving the minimum loading for the grid); the grid takes the remainder; the genset is the last resort. Best for maximizing solar self-consumption.',
    'Aktif: bus grid dan bus genset saling kunci (seperti transfer '
    'switch) — keduanya tidak pernah memasok beban bersamaan. Bila '
    'grid (+PV/BESS) tidak sanggup memikul beban, sistem beralih ke '
    'genset dan grid dilepas. Nonaktif: genset boleh beroperasi '
    'paralel dengan grid, hanya menutup kekurangan yang tidak sanggup '
    'dipikul grid.':
        'On: the grid bus and genset bus are interlocked (like a '
        'transfer switch) — they never supply the load at the same '
        'time. If the grid (+PV/BESS) cannot carry the load, the '
        'system transfers to the genset and the grid is dropped. Off: '
        'the genset may run in parallel with the grid, covering only '
        'the shortfall the grid cannot carry.',
    'Urutan sumber yang melayani beban. Mode Grid dahulu memaksimalkan '
    'impor grid sebelum PV/BESS. Bila DEG Interlock with Grid '
    'dinonaktifkan, genset naik satu tingkat sebelum BESS: '
    'PV → Grid → DEG → BESS, dan Grid → DEG → PV → BESS.':
        'Order of sources serving the load. Grid-first maximizes grid '
        'import before PV/BESS. When DEG Interlock with Grid is turned '
        'off, the genset moves one step ahead of the BESS: '
        'PV → Grid → DEG → BESS, and Grid → DEG → PV → BESS.',
    ('Aktif: pilih skenario load priority terpisah untuk saat '
     'grid tersedia (status 1) dan saat grid padam '
     '(status 0). Engine memakai skenario status-1 pada jam '
     'grid menyala dan skenario status-0 pada jam grid padam. '
     'Nonaktif: satu skenario Load Supply Priority berlaku '
     'untuk semua jam.'):
        ('On: choose separate load-priority scenarios for when the grid is '
         'available (status 1) and when the grid is down (status 0). The '
         'engine uses the status-1 scenario during grid-up hours and the '
         'status-0 scenario during outage hours. Off: a single Load Supply '
         'Priority scenario applies to all hours.'),
    ('Skenario prioritas beban saat GRID TERSEDIA '
     '(grid status = 1). Dipakai bila '
     '"Load Priority Follows Grid Status" aktif.'):
        ('Load-priority scenario when the GRID IS AVAILABLE '
         '(grid status = 1). Used when "Load Priority Follows Grid Status" '
         'is enabled.'),
    ('Skenario prioritas beban saat GRID PADAM '
     '(grid status = 0). Grid tidak ada, jadi hanya urutan '
     'PV/BESS/DEG yang berlaku. Dipakai bila '
     '"Load Priority Follows Grid Status" aktif.'):
        ('Load-priority scenario when the GRID IS DOWN '
         '(grid status = 0). No grid is present, so only the PV/BESS/DEG '
         'order applies. Used when "Load Priority Follows Grid Status" is '
         'enabled.'),
    'Aktif: genset HANYA menyala saat grid tidak tersedia '
    '(padam/off-grid) — genset tidak pernah beroperasi paralel dengan '
    'grid. Nonaktif: genset boleh menyala bersama grid untuk menutup '
    'kekurangan yang tidak sanggup dipikul grid (mis. beban melebihi '
    'kapasitas sambungan).':
        'On: the genset runs ONLY when the grid is unavailable '
        '(outage/off-grid) — it never operates in parallel with the '
        'grid. Off: the genset may run alongside the grid to cover a '
        'shortfall the grid cannot carry (e.g. load exceeding the '
        'connection capacity).',
    'Buka Proyek…': 'Open Project…', 'Simpan Proyek…': 'Save Project…',
    'Simpan': 'Save', 'Simpan Sebagai…': 'Save As…',
    'Simpan Sebagai': 'Save As',
    'Simpan ke berkas yang sedang dibuka (Ctrl+S)':
        'Save to the currently open file (Ctrl+S)',
    'Simpan ke berkas .hpps baru (Ctrl+Shift+S)':
        'Save to a new .hpps file (Ctrl+Shift+S)',
    'Berkas proyek:': 'Project file:',
    'Proyek belum tersimpan ke berkas .hpps':
        'Project not yet saved to an .hpps file',
    'Tersimpan:': 'Saved:',
    'Buka Proyek': 'Open Project', 'Simpan Proyek': 'Save Project',
    'Buka berkas proyek HPP Studio (.hpps)':
        'Open an HPP Studio project file (.hpps)',
    'Simpan parameter & data ke berkas .hpps':
        'Save parameters & data to an .hpps file',
    'Proyek tersimpan:': 'Project saved:',
    'Proyek dimuat:': 'Project loaded:',
    'Disimpan pada': 'Saved at',

    'Tabel per jam': 'Hourly table',
    'Sertakan tabel per jam untuk setiap tahun? (satu sheet per tahun, '
    'proses lebih lama dan file jauh lebih besar)':
        'Include the hourly table for every year? (one sheet per year; '
        'slower and a much larger file)',
    'Datetime': 'Datetime', 'Grid — Status': 'Grid — Status',
    'BESS — Cap Start (kWh)': 'BESS — Cap Start (kWh)',
    'BESS — Cap End (kWh)': 'BESS — Cap End (kWh)',

    'Ringkasan Tahunan':
        'Annual Summary',
    'Nilai':
        'Value',
    'Grid — Total Use (kWh)':
        'Grid — Total Use (kWh)',
    'Grid — After Load (kWh)':
        'Grid — After Load (kWh)',
    'Grid — Loading (%)':
        'Grid — Loading (%)',
    'Grid — Outage (jam)':
        'Grid — Outage (h)',
    'DEG — Total (kWh)':
        'DEG — Total (kWh)',
    'DEG — Runtime (jam)':
        'DEG — Runtime (h)',
    'DEG — Fuel (L)':
        'DEG — Fuel (L)',
    'PV — ENetAC (kWh)':
        'PV — ENetAC (kWh)',
    'PV — After Load (kWh)':
        'PV — After Load (kWh)',
    'PV — Inverter Out (kWh)':
        'PV — Inverter Out (kWh)',
    'PV — Unused/Curtailment (kWh)':
        'PV — Unused/Curtailment (kWh)',
    'BESS — Charge (kWh)':
        'BESS — Charge (kWh)',
    'BESS — Charge from PV (kWh)':
        'BESS — Charge from PV (kWh)',
    'BESS — Charge from Grid (kWh)':
        'BESS — Charge from Grid (kWh)',
    'BESS — Charge from DEG (kWh)':
        'BESS — Charge from DEG (kWh)',
    'BESS — Discharge (kWh)':
        'BESS — Discharge (kWh)',
    'BESS — Balance (kWh)':
        'BESS — Balance (kWh)',
    'BESS — Throughput (kWh)':
        'BESS — Throughput (kWh)',
    'BESS — Cycles':
        'BESS — Cycles',
    'BESS — SOC Min (%)':
        'BESS — SOC Min (%)',
    'BESS — SOC Max (%)':
        'BESS — SOC Max (%)',
    'Load — PV+BESS (kWh)':
        'Load — PV+BESS (kWh)',
    'Load — Grid (kWh)':
        'Load — Grid (kWh)',
    'Load — DEG (kWh)':
        'Load — DEG (kWh)',
    'Load — Needed (kWh)':
        'Load — Needed (kWh)',
    'Load — Unserved (kWh)':
        'Load — Unserved (kWh)',
    'Aktif: beban dilayani Grid ATAU PV-BESS secara eksklusif (bus terpisah). PV-BESS dipakai bila sanggup memikul seluruh beban jam itu; selain itu grid yang memikul dan PV hanya mengisi BESS. Nonaktif: grid dan PV-BESS boleh memasok beban bersamaan (perilaku standar).':
        'On: the load is served by the Grid OR by PV-BESS exclusively (separate buses). PV-BESS is used when it can carry the entire hourly load; otherwise the grid carries it and PV only charges the BESS. Off: grid and PV-BESS may supply the load simultaneously (standard behaviour).',
    'Sizing terbaik disalin ke halaman Parameters. Jalankan simulasi di Dashboard untuk detail.':
        'The best sizing has been copied to the Parameters page. Run the simulation on the Dashboard for details.',
    'Simulasikan seluruh lifetime dengan degradasi PV & BESS per tahun serta eskalasi harga (inflasi) dan discount rate.':
        'Simulate the entire lifetime with yearly PV & BESS degradation plus price escalation (inflation) and the discount rate.',
    'Semua nilai tersimpan otomatis. Arahkan kursor ke label untuk melihat tooltip.':
        'All values are saved automatically. Hover a label to see its tooltip.',
    'Format: kolom "Datetime" + "Load (kW)" / "PV ENetAC (kW)" / "Grid Status" — 8760 atau 8784 baris.':
        'Format: columns "Datetime" + "Load (kW)" / "PV ENetAC (kW)" / "Grid Status" — 8760 or 8784 rows.',
    'Grid search seluruh kombinasi — tervektorisasi + multiprocessing di semua core CPU.':
        'Grid search over all combinations — vectorized + multiprocessing on all CPU cores.',
    '{n} jam · total {e} kWh · puncak {p} kW':
        '{n} h · total {e} kWh · peak {p} kW',
    '{n} jam · profil basis {e} (skala kWp/basis)':
        '{n} h · base profile {e} (kWp/base scale)',
    '{n} baris · {iv} · total {e} kWh · puncak {p} kW':
        '{n} rows · {iv} · total {e} kWh · peak {p} kW',
    '{n} baris · {iv} · profil basis {e} (skala kWp/basis)':
        '{n} rows · {iv} · base profile {e} (kWp/base scale)',
    '{n} baris · total {e} kWh · puncak {p} kW':
        '{n} rows · total {e} kWh · peak {p} kW',
    '{n} baris · profil basis {e} (skala kWp/basis)':
        '{n} rows · base profile {e} (kWp/base scale)',
    '{n} jam padam / tahun':
        '{n} outage hours / year',
    '{n} jam dibuat dari pola 24 jam · {src} · Grid Status {g} penuh.':
        '{n} hours generated from the 24-hour pattern · {src} · Grid Status {g} throughout.',
    'Load {e} kWh/tahun dari pola 24 jam (diulang {d} hari).':
        'Load {e} kWh/year from the 24-hour pattern (repeated {d} days).',
    '1 (tersedia)':
        '1 (available)',
    '0 (off-grid)':
        '0 (off-grid)',
    'Grid Status:':
        'Grid Status:',
    'selalu tersedia':
        'always available',
    'off-grid penuh':
        'fully off-grid',
    'Kembalikan semua parameter ke default?':
        'Reset all parameters to default?',
    'Isi beban tiap jam (kW). Pola ini disalin ke seluruh hari dalam setahun. PV ENetAC memakai profil default bawaan; Grid Status mengikuti parameter Grid (1 penuh bila ada grid, 0 penuh bila off-grid).':
        'Enter hourly load (kW). The pattern is copied to every day of the year. PV ENetAC uses the bundled default profile; Grid Status follows the Grid parameter (all 1 with a grid, all 0 when off-grid).',
    'Lebar jendela tampilan time series (jumlah jam/data yang ditampilkan)':
        'Time-series window width (number of hours/points displayed)',
    'Belum ada data — buka halaman Data untuk mengimpor Load Profile & PV ENetAC.':
        'No data yet — open the Data page to import the Load Profile & PV ENetAC.',
    '— (tidak dipakai)':
        '— (not used)',
    'Kandidat yang nilainya masih dalam pita toleransi ini terhadap yang terbaik pada suatu prioritas dianggap setara, lalu diurutkan oleh prioritas berikutnya.':
        'Candidates within this tolerance band of the best value on a given priority are treated as equal, then ranked by the next priority.',
    '{n} simulasi tahunan (8760 jam)':
        '{n} annual simulations (8760 hours)',
    '{n} simulasi tahunan':
        '{n} annual simulations',
    'Data belum ada':
        'No data yet',
    'Import Load Profile dan PV ENetAC dahulu di halaman Data.':
        'Import the Load Profile and PV ENetAC first on the Data page.',
    'Batas pencarian ditentukan otomatis dari profil beban & PV; grid disempitkan iteratif hingga konvergen. Kapasitas inverter diikat INV = PV / {r} (DC/AC).':
        'Search bounds are derived automatically from the load & PV profiles; the grid is refined iteratively until convergence. Inverter capacity is tied to INV = PV / {r} (DC/AC).',
    'Rasio DC/AC yang dipakai Auto Optimizer: kapasitas inverter = PV ÷ rasio ini.':
        'DC/AC ratio used by the Auto Optimizer: inverter capacity = PV ÷ this ratio.',
    'Daya charge/discharge tiap kandidat = kapasitas BESS × C-rate Parameters ({c} 1/jam), yaitu {p} kW pada {e} kWh.':
        'Charge/discharge power of each candidate = BESS capacity × the C-rate from Parameters ({c} 1/h), i.e. {p} kW at {e} kWh.',
    'Daya PCS = kapasitas BESS × C-rate ini (mis. 0,5 = 2 jam penuh).':
        'PCS power = BESS capacity × this C-rate (e.g. 0.5 = 2 full hours).',
    'Daya PCS tetap (kW) untuk semua kandidat, tidak ikut membesar dengan kapasitas BESS.':
        'Fixed PCS power (kW) for every candidate; it does not scale with BESS capacity.',
    'Auto: {n} evaluasi dalam {r} ronde':
        'Auto: {n} evaluations in {r} rounds',
    'Diterapkan':
        'Applied',
    'Sizing terbaik disalin ke halaman Parameters. Jalankan simulasi di Dashboard untuk detail.':
        'The best sizing has been copied to the Parameters page. Run the simulation on the Dashboard for details.',
    'Semua nilai tersimpan otomatis. Arahkan kursor ke label untuk melihat tooltip.':
        'All values are saved automatically. Hover a label to see its tooltip.',
    'Simulasikan seluruh lifetime dengan degradasi PV & BESS per tahun serta eskalasi harga (inflasi) dan discount rate.':
        'Simulate the entire lifetime with yearly PV & BESS degradation plus price escalation (inflation) and the discount rate.',
    'Laporan tersimpan:':
        'Report saved:',
    'Buka dengan browser apa pun.':
        'Open it with any browser.',
    'Jam (minggu pertama)':
        'Hour (first week)',
    'OPEX (tahun-1)':
        'OPEX (year 1)',
    'Savings (tahun-1)':
        'Savings (year 1)',
    'OPEX Tahun-1':
        'OPEX Year-1',
    'Baseline Cost Th-1':
        'Baseline Cost Yr-1',
    'Penghematan Th-1':
        'Savings Yr-1',
    'Pilih file profil':
        'Choose profile file',
    'profil PV yang sudah dimuat':
        'the PV profile already loaded',
    'profil PV default bawaan':
        'the bundled default PV profile',
    'Profil PV default tidak ditemukan (assets/sample_input.xlsx). Impor profil PV terlebih dahulu.':
        'Default PV profile not found (assets/sample_input.xlsx). Import a PV profile first.',
    'Identitas proyek dan status data': 'Project identity & data status',
    'Project': 'Project',
    'PV ENetAC Profile': 'PV ENetAC Profile',
    'Grid Availability': 'Grid Availability',
    'Simulasi Terakhir': 'Last Simulation',
    'jam padam': 'outage hours',

    'Ganti bahasa (ID / EN)': 'Switch language (ID / EN)',

    # ---- tooltip parameter ----
    'Genset menambah output Saat genset menyala dengan pembebanan di bawah Minimum Loading, kekurangannya dialihkan untuk mengisi BESS sehingga genset beroperasi minimal pada minimum loading-nya. Hanya berlaku bila DEG Interlock nonaktif (saat interlock, bus DEG terpisah dari PV-BESS).':
        'When the genset runs below its Minimum Loading, the shortfall is diverted into the BESS so the genset operates at least at its minimum loading. Only applies when DEG Interlock is off (with interlock, the DEG bus is separated from PV-BESS).',
    'Nama proyek untuk laporan':
        'Project name used in reports',
    'Nama pelanggan':
        'Customer name',
    'Nama site / lokasi pembangkit (dipakai pada nama file ekspor dan lembar Info)':
        'Site / plant name (used in export file names and the Info sheet)',
    'Lokasi site':
        'Site location',
    'Tahun kalender profil data':
        'Calendar year of the data profile',
    'Resolusi waktu simulasi':
        'Simulation time resolution',
    'Resolusi waktu simulasi (khusus halaman Dashboard). Interval lebih halus memakai JENDELA lebih pendek agar ringan: 1 hour & 30 minute = 1 tahun penuh; 1 minute = 3 bulan; 30 second = 1 bulan; 15 second = 1 minggu; 1 second = 1 hari. Data per-jam otomatis di-resample; boleh juga import data resolusi tinggi. Optimization & Multi-Year tetap memakai basis 1 jam (setahun).':
        'Simulation time resolution (Dashboard only). Finer intervals use a SHORTER window to stay light: 1 hour & 30 minute = full year; 1 minute = 3 months; 30 second = 1 month; 15 second = 1 week; 1 second = 1 day. Hourly data is auto-resampled; you may also import high-resolution data. Optimization & Multi-Year still use the 1-hour (annual) basis.',
    'Resolusi waktu simulasi (khusus halaman Dashboard). Interval lebih halus memakai JENDELA lebih pendek agar ringan: 1 hour & 30 minute = 1 tahun penuh; 1 minute & 30 second = 1 bulan; 15 second = 1 minggu; 1 second = 1 hari. Titik MULAI jendela dipilih di Dashboard. Energi diekstrapolasi ke setahun (kWh/tahun). Data per-jam otomatis di-resample; boleh juga import data resolusi tinggi. Optimization & Multi-Year tetap basis 1 jam.':
        'Simulation time resolution (Dashboard only). Finer intervals use a SHORTER window to stay light: 1 hour & 30 minute = full year; 1 minute & 30 second = 1 month; 15 second = 1 week; 1 second = 1 day. The window START is chosen on the Dashboard. Energy is extrapolated to a year (kWh/year). Hourly data is auto-resampled; you may also import high-resolution data. Optimization & Multi-Year still use the 1-hour basis.',
    'Interval tampilan:': 'Display interval:',
    'Resolusi tampilan grafik (agregasi dari hasil simulasi).':
        'Chart display resolution (aggregated from the simulation result).',
    'Nonaktifkan untuk sistem off-grid':
        'Disable for off-grid systems',
    'Kapasitas sambungan PLN':
        'Utility connection capacity',
    'Loading minimum grid saat tersambung':
        'Minimum grid loading while connected',
    'Loading maksimum grid':
        'Maximum grid loading',
    'Izinkan ekspor kelebihan PV ke grid (ekstensi; default OFF)':
        'Allow exporting surplus PV to the grid (extension; default OFF)',
    'Tarif energi impor grid':
        'Grid import energy tariff',
    'Harga jual energi ekspor ke grid (dipakai bila PV-BESS Export to Grid aktif)':
        'Sell price for energy exported to the grid (used when PV-BESS Export to Grid is enabled)',
    'Urutan sumber yang melayani beban. Mode Grid dahulu memaksimalkan impor grid sebelum PV/BESS.':
        'Order of sources serving the load. Grid-first maximizes grid import before PV/BESS.',
    'Nonaktifkan agar BESS hanya di-charge dari PV; grid tidak pernah mengisi baterai (W = 0).':
        'Disable so the BESS is charged from PV only; the grid never charges the battery (W = 0).',
    'Jumlah genset aktif':
        'Number of active gensets',
    'Harga solar per liter':
        'Diesel price per liter',
    'Laju konsumsi bahan bakar DEG-1 — konversi langsung energi genset ke liter solar: Fuel (L) = laju × energi DEG (kWh). Nilai 0,303 setara efisiensi 33% (referensi sebelumnya).':
        'DEG-1 fuel consumption rate — directly converts genset energy to liters of diesel: Fuel (L) = rate × DEG energy (kWh). 0.303 equals 33% efficiency (previous reference).',
    'Laju konsumsi bahan bakar DEG-2 — Fuel (L) = laju × energi DEG-2 (kWh). Boleh berbeda dari DEG lain.':
        'DEG-2 fuel consumption rate — Fuel (L) = rate × DEG-2 energy (kWh). May differ from the other gensets.',
    'Laju konsumsi bahan bakar DEG-3 — Fuel (L) = laju × energi DEG-3 (kWh). Boleh berbeda dari DEG lain.':
        'DEG-3 fuel consumption rate — Fuel (L) = rate × DEG-3 energy (kWh). May differ from the other gensets.',
    'Biaya investasi genset':
        'Genset investment cost',
    'Kapasitas nominal BESS':
        'Nominal BESS capacity',
    'Batas daya charge PCS':
        'PCS charge power limit',
    'Batas daya discharge PCS':
        'PCS discharge power limit',
    'BESS di-charge dari grid bila SOC < nilai ini':
        'The BESS is charged from the grid when SOC is below this value',
    'Biaya investasi baterai':
        'Battery investment cost',
    'Kapasitas array PV terpasang':
        'Installed PV array capacity',
    'Rating modul PV':
        'PV module rating',
    'Biaya investasi PV per kWp':
        'PV investment cost per kWp',
    'Biaya inverter per kW':
        'Inverter cost per kW',
    'Biaya operasi & pemeliharaan tahunan':
        'Annual operation & maintenance cost',
    'Biaya tetap (BOS, sipil, dll.)':
        'Fixed cost (BOS, civil works, etc.)',
    'Biaya aksesoris — komponen CAPEX tetap, ditambahkan langsung ke total CAPEX':
        'Accessories cost — a fixed CAPEX component added directly to total CAPEX',
    'Biaya logistik — komponen CAPEX tetap, ditambahkan langsung ke total CAPEX':
        'Logistics cost — a fixed CAPEX component added directly to total CAPEX',
    'Biaya EPC per kWp PV — CAPEX EPC = nilai ini × kapasitas PV (kWp)':
        'EPC cost per PV kWp — EPC CAPEX = this value × PV capacity (kWp)',
    'Pembanding penghematan: diesel murni atau grid+diesel':
        'Savings baseline: diesel-only or grid+diesel',
    'Batasi LCOE, CAPEX & OPEX (halaman Results & '
    'Optimization Constraints) hanya ke komponen biaya & energi '
    'teknologi terpilih. "DEG" = Diesel genset + Grid (gabungan, '
    'selaras label "DEG/Grid" pada grafik EMS); "PV-BESS" = PV + '
    'Inverter + BESS saja; "PV-BESS-DEG" (baku) = seluruh sistem, '
    'tak berubah dari sebelumnya. Biaya CAPEX tetap (Accessories & '
    'Logistic) selalu diikutkan penuh apa pun pilihannya. NPV, '
    'IRR, ROI, dan Payback TETAP dihitung dari seluruh sistem '
    'terlepas dari pilihan ini.':
        'Restrict LCOE, CAPEX & OPEX (Results page & Optimization '
        'Constraints) to only the cost & energy components of the selected '
        'technology. "DEG" = Diesel genset + Grid (combined, matching the '
        '"DEG/Grid" label used on the EMS chart); "PV-BESS" = PV + '
        'Inverter + BESS only; "PV-BESS-DEG" (default) = the whole system, '
        'unchanged from before. Fixed CAPEX costs (Accessories & Logistic) '
        'are always included in full regardless of this choice. NPV, IRR, '
        'ROI and Payback are ALWAYS computed from the whole system '
        'regardless of this setting.',
    'Umur proyek untuk analisis finansial':
        'Project life for financial analysis',
    'Tingkat diskonto untuk NPV & LCOE':
        'Discount rate for NPV & LCOE',
    'Eskalasi harga energi tahunan':
        'Annual energy price escalation',
    'Degradasi tahunan (analisis finansial)':
        'Annual degradation (financial analysis)',
    'Degradasi kapasitas tahunan (analisis finansial)':
        'Annual capacity degradation (financial analysis)',
    'Fraksi beban dilayani PV+BESS':
        'Share of load served by PV+BESS',
    '0 = tidak dibatasi':
        '0 = unlimited',
    'Reduksi fuel vs skenario diesel-only':
        'Fuel reduction vs the diesel-only scenario',
    'Informasi operasional (belum membatasi dispatch)':
        'Operational information (does not constrain dispatch yet)',
    'Saat genset menyala dengan pembebanan di bawah Minimum Loading, kekurangannya dialihkan untuk mengisi BESS sehingga genset beroperasi minimal pada minimum loading-nya. Hanya berlaku bila DEG Interlock nonaktif (saat interlock, bus DEG terpisah dari PV-BESS).':
        'When the genset runs below its Minimum Loading, the shortfall is diverted into the BESS so the genset operates at least at its minimum loading. Only applies when DEG Interlock is off (with interlock, the DEG bus is separated from PV-BESS).',
    'Aktif: sumber beban eksklusif — Grid+PV-BESS ATAU DEG; saat DEG memikul beban, PV hanya charge ke BESS, BESS tidak discharge, dan grid hanya boleh charge (bila diizinkan). Nonaktif: DEG hanya menutup residu dan boleh paralel dengan PV/BESS/Grid.':
        'On: exclusive load sources — Grid+PV-BESS OR DEG; while the DEG carries the load, PV only charges the BESS, the BESS does not discharge, and the grid may only charge (if allowed). Off: the DEG only covers the residual and may run in parallel with PV/BESS/Grid.',
    'Aktif: sumber prioritas kedua MENUNGGU — pada PV -> Grid, grid tidak mengisi BESS selama PV masih mengisi; pada Grid -> PV sebaliknya. Nonaktif: keduanya boleh mengisi bersamaan, berbagi limit PCS & headroom SOC menurut urutan prioritas.':
        'On: the second-priority source WAITS — with PV -> Grid the grid does not charge the BESS while PV is charging; with Grid -> PV the reverse. Off: both may charge simultaneously, sharing the PCS limit & SOC headroom according to priority.',
    'Sumber energi yang diprioritaskan untuk mengisi BESS ketika keduanya tersedia (charge dari grid tetap hanya saat SOC di bawah ambang).':
        'Energy source prioritized for charging the BESS when both are available (grid charging still only occurs when SOC is below the threshold).',
    'Pembebanan minimum tiap genset. Bila Allow DEG Charging to BESS aktif, genset menambah output untuk mengisi BESS agar beroperasi minimal pada loading ini':
        'Minimum loading of each genset. When Allow DEG Charging to BESS is on, the genset raises its output to charge the BESS so it runs at least at this loading',
    'Batas loading maksimum, asumsi sama untuk semua DEG — dipakai sebagai ambang eskalasi alokasi genset (AE* ≤ ΣD·Lmax)':
        'Maximum loading limit, assumed equal for all DEGs — used as the genset allocation escalation threshold (AE* ≤ ΣD·Lmax)',
    'Kapasitas pembangkit acuan yang menghasilkan profil PV ENetAC yang diimpor (dari PVsyst). Output = ENetAC × kWp desain ÷ nilai ini. Isi 1 bila profil sudah per-kWp.':
        'Reference plant size that produced the imported PV ENetAC profile (from PVsyst). Output = ENetAC × design kWp ÷ this value. Enter 1 if the profile is already per-kWp.',
    'Umur pakai BESS. Setelah mencapai umur ini, BESS diganti baru (biaya = CAPEX BESS) dan SOH kembali 100%. Isi 0 untuk menonaktifkan penggantian berbasis umur.':
        'BESS service life. Once reached, the BESS is replaced (cost = BESS CAPEX) and SOH returns to 100%. Enter 0 to disable age-based replacement.',
    'Ambang State of Health. Bila SOH turun di bawah nilai ini, BESS diganti baru (biaya = CAPEX BESS) dan SOH kembali 100%. Isi 0 untuk menonaktifkan penggantian berbasis SOH.':
        'State of Health threshold. When SOH drops below this value the BESS is replaced (cost = BESS CAPEX) and SOH returns to 100%. Enter 0 to disable SOH-based replacement.',
    'Rasio energi PV tak terpakai terhadap produksi ENetAC — istilah PVsyst: Unused Energy / EUnused (ENetAC yang tidak tersalurkan melalui inverter)':
        'Ratio of unused PV energy to ENetAC production — PVsyst term: Unused Energy / EUnused (ENetAC not delivered through the inverter)',
    'Simulasi selesai. Lihat halaman Results untuk KPI lengkap & laporan.':
        'Simulation complete. See the Results page for full KPIs & report.',
    'Selesai — {n} tahun tersimulasi (degradasi PV {pv}%/th, BESS {bess}%/th, '
    'inflasi {infl}%, discount {disc}%).':
        'Done — {n} years simulated (PV degradation {pv}%/yr, BESS {bess}%/yr, '
        'inflation {infl}%, discount {disc}%).',
    'BESS Autonomy': 'BESS Autonomy',
    '(jam)': '(h)', '(th)': '(yr)', '(kWh/th)': '(kWh/yr)', '(L/th)': '(L/yr)',
    'kWh/th': 'kWh/year', 'L/th': 'L/year',
    'siklus': 'cycles', 'jam': 'hours', 'tahun': 'years', 'Hari': 'Day',
    'baris': 'rows', 'kW/langkah': 'kW/step',
    # --- Dashboard Advanced (EMS): pemilih hari (jendela > 1 hari) ---
    'Hari:': 'Day:', 'Hari {n}': 'Day {n}',
    'Pilih hari yang ditampilkan pada grafik Advanced (EMS) -- muncul '
    'hanya bila jendela yang disimulasikan lebih dari 1 hari (24 jam).':
        'Select which day is shown on the Advanced (EMS) chart -- only '
        'appears when the simulated window is longer than 1 day (24h).',
    'PV Generation': 'PV Generation', 'Diesel Energy': 'Diesel Energy',
    'Unused/Curtail': 'Unused/Curtail', 'Unserved': 'Unserved',
    'Impor Grid': 'Grid Import',
    # --- Batch Multi-Site Multi-Year (Results) ---
    'Aktifkan Batch Multi-Site (Multi-Year)':
        'Enable Multi-Site Batch (Multi-Year)',
    'Tampilkan/sembunyikan bagian batch multi-site multi-year.':
        'Show/hide the multi-site multi-year batch section.',
    'Batch Multi-Site — Multi-Year (beberapa berkas data)':
        'Multi-Site Batch — Multi-Year (several data files)',
    'Jalankan simulasi multi-year untuk beberapa berkas data sekaligus. '
    'Nama site diambil dari nama berkas. Semua parameter mengikuti '
    'halaman Parameters (termasuk finance); PV/INV/BESS/PCS dapat '
    'dikhususkan per site di bawah. Berkas tanpa kolom PV ENetAC '
    'memakai profil PV aktif sebagai cadangan.':
        'Run a multi-year simulation for several data files at once. Site '
        'names are taken from the file names. All parameters follow the '
        'Parameters page (including finance); PV/INV/BESS/PCS can be '
        'customised per site below. Files without a PV ENetAC column use the '
        'active PV profile as a fallback.',
    'Pilih Berkas Data…': 'Pick Data Files…',
    'Pilih Berkas Data': 'Pick Data Files',
    '▶  Jalankan Batch Multi-Year': '▶  Run Multi-Year Batch',
    'Batalkan Batch': 'Cancel Batch',
    'Export Batch…': 'Export Batch…',
    'Bersihkan Batch': 'Clear Batch',
    'Sizing per Site (PV / INV / BESS / PCS)':
        'Per-Site Sizing (PV / INV / BESS / PCS)',
    'Centang "Custom" pada sebuah site untuk memakai sizing khusus; '
    'bila tidak, site memakai nilai halaman Parameters.':
        'Tick "Custom" on a site to use dedicated sizing; otherwise the site '
        'uses the values from the Parameters page.',
    'Custom': 'Custom', 'PV (kWp)': 'PV (kWp)', 'INV (kW)': 'INV (kW)',
    'BESS (kWh)': 'BESS (kWh)', 'PCS (kW)': 'PCS (kW)',
    'Pakai sizing khusus untuk site ini.': 'Use dedicated sizing for this site.',
    'Terapkan Data Site Terpilih': 'Apply Selected Site Data',
    'Salin sizing PV/INV/BESS/PCS (charge & discharge) site ini ke '
    'halaman Parameters, dan muat profil Load/PV/Grid-nya sebagai data '
    'aktif di halaman Data (untuk drill-down Run Multi-Year / grafik '
    'per tahun).':
        'Copy this site\'s PV/INV/BESS/PCS sizing (charge & discharge) to the '
        'Parameters page, and load its Load/PV/Grid profile as the active data '
        'on the Data page (to drill down via Run Multi-Year / per-year charts).',
    'Belum ada berkas dipilih.': 'No files selected yet.',
    '{n} berkas dipilih:': '{n} files selected:',
    'Menjalankan {i}/{n}: {site} …': 'Running {i}/{n}: {site} …',
    'Membaca berkas {i}/{n}: {site} …': 'Reading file {i}/{n}: {site} …',
    'Base Profile Plant (kWp)': 'Base Profile Plant (kWp)',
    'Menentukan Base Profile Plant Size yang dipakai saat menskala '
    'profil PV tiap site: q = profil × (PV kWp ÷ Base).':
        'Sets the Base Profile Plant Size used when scaling each site\'s PV '
        'profile: q = profile × (PV kWp ÷ Base).',
    'Ikuti halaman Parameters ({v:,.2f} kWp)':
        'Follow Parameters page ({v:,.2f} kWp)',
    'Sama dengan PV (kWp) tiap site': "Same as each site's PV (kWp)",
    'Nilai lain (kWp):': 'Other value (kWp):',
    'Nilai Base Profile Plant tidak valid.':
        'Base Profile Plant value is invalid.',
    'Nilai Base Profile Plant harus > 0.':
        'Base Profile Plant value must be > 0.',
    'Base = Parameters': 'Base = Parameters',
    'Base = PV kWp': 'Base = PV kWp',
    'Base = {v} kWp': 'Base = {v} kWp',
    'Selesai — {n} site tersimulasi.': 'Done — {n} sites simulated.',
    '{n} site gagal (dilewati)': '{n} sites failed (skipped)',
    'Semua site gagal.': 'All sites failed.',
    'Batch selesai dengan galat': 'Batch finished with errors',
    'Batch dibatalkan.': 'Batch cancelled.',
    'Membatalkan batch …': 'Cancelling batch …',
    'Sebagian site gagal': 'Some sites failed',
    '{n} site dilewati karena galat:': '{n} sites skipped due to errors:',
    'Nilai tidak valid': 'Invalid value',
    'Sizing custom site "{s}" tidak valid.':
        'Custom sizing for site "{s}" is invalid.',
    'Data diterapkan': 'Data applied',
    'Site diterapkan': 'Site applied',
    'Profil site "{s}" dimuat sebagai data aktif. Jalankan Run '
    'Multi-Year untuk rincian per tahun.':
        'Site "{s}" profile loaded as active data. Run Multi-Year for '
        'per-year detail.',
    'Site "{s}" diterapkan:\n'
    '• Sizing PV/INV/BESS/PCS (charge & discharge) disalin ke '
    'halaman Parameters.\n'
    '• Profil Load/PV/Grid dimuat sebagai data aktif di halaman '
    'Data.\n{home}\n\nJalankan Run Multi-Year untuk rincian per tahun.':
        'Site "{s}" applied:\n'
        '• PV/INV/BESS/PCS sizing (charge & discharge) copied to the '
        'Parameters page.\n'
        '• Load/PV/Grid profile loaded as active data on the Data page.\n'
        '{home}\n\nRun Multi-Year for per-year detail.',
    '• Site Name & koordinat disalin ke halaman Home.':
        '• Site Name & coordinates copied to the Home page.',
    '• Site Name disalin ke halaman Home.':
        '• Site Name copied to the Home page.',
    'Simpan Batch Multi-Year': 'Save Multi-Year Batch',
    # --- tabel per-tahun (dipakai Multi-Year & batch multi-site) ---
    'PV Efektif': 'Effective PV', 'BESS Efektif': 'Effective BESS',
    'BESS SOH': 'BESS SOH', 'PV Gen': 'PV Gen', 'PV - Inverter': 'PV - Inverter',
    'RF': 'RF', 'Fuel': 'Fuel', 'DEG - total': 'DEG - total',
    'DEG - runtime': 'DEG - runtime', 'Grid Imp': 'Grid Imp',
    'Unused': 'Unused', 'PV Curtailment': 'PV Curtailment',
    'Load Unserved': 'Load Unserved', 'Unserved': 'Unserved',
    'OPEX': 'OPEX', 'Savings': 'Savings', 'Kumulatif': 'Cumulative',
    'PV Pen': 'PV Pen', 'DEG Fuel': 'DEG Fuel',
    'BESS autonomous': 'BESS autonomous', 'L/tahun': 'L/year',
    'Seret untuk memblok sel, lalu Ctrl+C untuk menyalin ke Excel.':
        'Drag to select a block of cells, then press Ctrl+C to copy into Excel.',
    'Seret judul kolom untuk menggeser urutan site. Seret sel lalu '
    'Ctrl+C untuk menyalin ke Excel.':
        'Drag a column header to reorder sites. Drag cells then Ctrl+C to '
        'copy into Excel.',
    'pilih site pada dropdown untuk rincian per tahun.':
        'pick a site from the dropdown for per-year detail.',
    'Data:': 'Data:',
    'pilih Data pada dropdown; kolom = site, baris = tahun.':
        'pick a Data metric from the dropdown; columns = sites, rows = years.',
    'Site: {s}  ·  PV {pv:,.1f} kWp · INV {inv:,.1f} kW · '
    'BESS {bess:,.1f} kWh · PCS {pcs:,.1f} kW  ·  Lifetime {yr} th':
        'Site: {s}  ·  PV {pv:,.1f} kWp · INV {inv:,.1f} kW · '
        'BESS {bess:,.1f} kWh · PCS {pcs:,.1f} kW  ·  Lifetime {yr} yr',
    'Site: {s}{star}  ·  PV {pv:,.1f} kWp · INV {inv:,.1f} kW · '
    'BESS {bess:,.1f} kWh · PCS {pcs:,.1f} kW  ·  Lifetime {yr} th':
        'Site: {s}{star}  ·  PV {pv:,.1f} kWp · INV {inv:,.1f} kW · '
        'BESS {bess:,.1f} kWh · PCS {pcs:,.1f} kW  ·  Lifetime {yr} yr',
    'LCOE {lcoe:,.0f} Rp/kWh · NPV {npv:,.0f} Rp · IRR {irr:,.1f}% '
    '· Payback {pb:,.1f} th · ROI {roi:,.1f}% · CAPEX {cap:,.0f} Rp':
        'LCOE {lcoe:,.0f} Rp/kWh · NPV {npv:,.0f} Rp · IRR {irr:,.1f}% '
        '· Payback {pb:,.1f} yr · ROI {roi:,.1f}% · CAPEX {cap:,.0f} Rp',
    'Lifetime': 'Lifetime', 'Penggantian': 'Replacements',
    'RF Th-1': 'RF Y1', 'Diesel Th-1': 'Diesel Y1', 'Beban Th-1': 'Load Y1',
    'Unserved Th-1': 'Unserved Y1', 'LCOE Lifetime': 'Lifetime LCOE',
    'Custom Sizing': 'Custom Sizing', 'Ya': 'Yes', 'Tidak': 'No',
    'sizing custom': 'custom sizing',
    'Hentikan proses batch yang sedang berjalan.':
        'Stop the running batch process.',
    # --- sizing per site via Excel ---
    'Centang "Custom" pada sebuah site untuk memakai sizing khusus; '
    'bila tidak, site memakai nilai halaman Parameters. Anda juga dapat '
    'mengisi via Excel: kolom params (PV/INV/BESS/PCS) × Unit × satu '
    'kolom per site (nama kolom = nama berkas data).':
        'Tick "Custom" on a site to use dedicated sizing; otherwise the site '
        'uses the Parameters page values. You can also fill via Excel: a '
        'params column (PV/INV/BESS/PCS) × Unit × one column per site (column '
        'name = data file name).',
    'Unduh Template Excel': 'Download Excel Template',
    'Simpan template Excel berisi kolom untuk tiap site (memakai nama '
    'berkas data) yang dapat Anda isi lalu impor kembali.':
        'Save an Excel template with one column per site (using the data file '
        'names) that you can fill in and import back.',
    'Impor Sizing dari Excel…': 'Import Sizing from Excel…',
    'Belum ada berkas': 'No files yet',
    'Pilih berkas data dulu agar kolom site terbentuk.':
        'Pick data files first so the site columns can be created.',
    'Simpan Template Sizing per Site': 'Save Per-Site Sizing Template',
    'Template disimpan': 'Template saved',
    'Template tersimpan (nilai awal = halaman Parameters, silakan '
    'sunting lalu impor):':
        'Template saved (initial values = Parameters page; edit then import):',
    'Pilih berkas data dulu sebelum mengimpor sizing.':
        'Pick data files first before importing sizing.',
    'Impor Sizing per Site': 'Import Per-Site Sizing',
    'Berkas kosong.': 'File is empty.',
    'Kolom params wajib memuat baris PV, INV, BESS, PCS.':
        'The params column must contain rows PV, INV, BESS, PCS.',
    '{n} site diterapkan dari Excel.': '{n} sites applied from Excel.',
    'Kolom tanpa berkas data yang cocok (dilewati): ':
        'Columns with no matching data file (skipped): ',
    'Impor selesai': 'Import done', 'Impor selesai.': 'Import done.',
    'Gagal impor': 'Import failed', 'Template disimpan.': 'Template saved.',

    # --- Sapuan lengkapi terjemahan EN yang masih bolong (v128) ---------
    # Halaman Data / Optimization / Dashboard / Results / Multi-Year:
    'Durasi (jendela) yang disimulasikan tiap iterasi, dari titik Mulai. '
    'Lebih pendek = lebih cepat; KPI (LCOE, PV generation, dll.) '
    'diekstrapolasi ke setahun. "Setahun penuh" = tanpa ekstrapolasi. Mode '
    'Firming: kolom "Firming Target Met (%)" TIDAK diekstrapolasi, selalu '
    'dihitung hanya dari jendela ini — pilih "Setahun penuh" agar '
    'mencerminkan seluruh tahun, bukan hanya sampel.':
        'The window simulated per iteration, from the Start point. Shorter '
        '= faster; KPIs (LCOE, PV generation, etc.) are extrapolated to a '
        'full year. "Full year" = no extrapolation. Firming mode: the '
        '"Firming Target Met (%)" column is NOT extrapolated, always '
        'computed only from this window — choose "Full year" so it '
        'reflects the whole year, not just a sample.',
    'Format: kolom "Datetime" + "Load (kW)" / "PV ENetAC (kW)" / "Grid '
    'Status" / "DEG Status" (0/1/A). Per jam (8760/8784 baris) atau '
    'resolusi tinggi dgn timestamp konsisten hingga 1 tahun (mis. 525.600 '
    'baris = 1 menit setahun). Interval terdeteksi dari timestamp.':
        'Format: "Datetime" column + "Load (kW)" / "PV ENetAC (kW)" / '
        '"Grid Status" / "DEG Status" (0/1/A). Hourly (8760/8784 rows) or '
        'high-resolution data with consistent timestamps up to 1 year '
        '(e.g. 525,600 rows = 1-minute data for a year). The interval is '
        'detected from the timestamps.',
    'Grafik EMS multi-mode (mode Advanced): PV & suplai DEG/Grid, sebelum '
    'vs sesudah shaping BESS (Smoothing / Firming), + SOC. Zoom: '
    'seret-kiri kotak; klik-kanan → Reset view. Jalankan Run dengan mode '
    'Advanced.':
        'Multi-mode EMS chart (Advanced mode): PV & DEG/Grid supply, '
        'before vs after BESS shaping (Smoothing / Firming), + SOC. Zoom: '
        'left-drag a box; right-click → Reset view. Run with Advanced '
        'mode.',
    'Jam pertama (pratinjau · rata-rata per jam)':
        'First hours (preview · hourly average)',
    'Membaca file…': 'Reading file…',
    'Pratinjau Profil (7 hari pertama · rata-rata per jam)':
        'Profile Preview (first 7 days · hourly average)',
    'default: Auto (mengikuti dispatch normal)':
        'default: Auto (follows normal dispatch)',
    '{off} jam DEG dipaksa OFF · {on} jam dipaksa ON · {auto} jam Auto':
        '{off} h DEG forced OFF · {on} h forced ON · {auto} h Auto',
    'Impor Data': 'Import Data',
    'Selesai': 'Done',
    'Menyiapkan tampilan…': 'Preparing view…',
    'Kolom terbaca: {cols}': 'Columns read: {cols}',
    'Template tersimpan di\n{path}': 'Template saved to\n{path}',
    'Tersimpan:\n{path}': 'Saved:\n{path}',
    'Mode Case Analysis': 'Case Analysis Mode',
    'BESS Autonomy\n(jam)': 'BESS Autonomy\n(hours)',
    'Memuat & memvalidasi profil…': 'Loading & validating profile…',
    '{site}: kolom Load tidak ditemukan.': '{site}: Load column not found.',
    '{site}: kolom PV ENetAC tidak ada dan tidak ada profil PV yang dapat '
    'dipakai.':
        '{site}: no PV ENetAC column and no usable PV profile.',
    'kolom Load tidak ditemukan.': 'Load column not found.',

    # --- Pesan galat import (app/data/importer.py) -----------------------
    'Kolom "{col}" baris {row}: nilai "{val}" tidak dikenali — harus 0, 1, '
    'atau A (Auto).':
        'Column "{col}" row {row}: value "{val}" not recognized — must be '
        '0, 1, or A (Auto).',
    'File kosong.': 'File is empty.',
    'Kolom datetime "{col}" mengandung nilai tidak valid.':
        'Datetime column "{col}" contains invalid values.',
    'Jumlah baris {n} tidak dikenali — harus 8760/8784 (per jam) atau '
    'data resolusi tinggi dengan timestamp konsisten yang mencakup '
    'bilangan bulat jam hingga ≤ 1 tahun (mis. 525.600 = 1 menit setahun, '
    '43.200 = 1 menit sebulan).':
        'Row count {n} not recognized — must be 8760/8784 (hourly) or '
        'high-resolution data with consistent timestamps covering a whole '
        'number of hours up to ≤ 1 year (e.g. 525,600 = 1-minute data for '
        'a year, 43,200 = 1-minute data for a month).',
    'Kolom "{col}": {bad} nilai non-numerik/kosong.':
        'Column "{col}": {bad} non-numeric/empty value(s).',
    'Kolom "{col}" mengandung nilai negatif.':
        'Column "{col}" contains negative values.',
    'Grid status hanya boleh 0 atau 1.': 'Grid status may only be 0 or 1.',
    'Tidak ditemukan kolom Load / PV ENetAC / Grid Status / DEG Status.':
        'No Load / PV ENetAC / Grid Status / DEG Status column found.',
    'Sheet "Results" tidak ditemukan — bukan workbook sizing yang dikenal.':
        'Sheet "Results" not found — not a recognized sizing workbook.',
    'Nilai Load kosong — buka & simpan file di Excel agar formula '
    'terhitung, lalu import ulang.':
        'Load values are empty — open & save the file in Excel so '
        'formulas are calculated, then re-import.',
    'Berkas koordinat kosong.': 'Coordinate file is empty.',
    'Kolom Latitude/Longitude tidak ditemukan (butuh kolom Site, '
    'Latitude, Longitude).':
        'Latitude/Longitude column not found (needs Site, Latitude, '
        'Longitude columns).',
    'Tidak ada baris koordinat valid.': 'No valid coordinate rows.',

    # --- Pesan galat PVGIS (app/data/pvgis.py) ----------------------------
    'Gagal mengunduh GHI dari PVGIS: {e}':
        'Failed to download GHI from PVGIS: {e}',
    'Respons GHI PVGIS bukan JSON yang valid.':
        'PVGIS GHI response is not valid JSON.',
    'Koordinat/parameter PV tidak valid.': 'Invalid PV coordinates/parameters.',
    'PVGIS menolak permintaan (HTTP {code}). {detail}':
        'PVGIS rejected the request (HTTP {code}). {detail}',
    'Tidak dapat menghubungi server PVGIS — periksa koneksi internet. '
    '({e})':
        'Could not reach the PVGIS server — check your internet '
        'connection. ({e})',
    'Gagal mengunduh data PVGIS: {e}': 'Failed to download PVGIS data: {e}',
    'Respons PVGIS bukan JSON yang valid.':
        'PVGIS response is not valid JSON.',
    'Data per-jam PVGIS kosong/tidak ditemukan.':
        'PVGIS hourly data is empty/not found.',
    'PVGIS mengembalikan {n} jam (diharapkan 8760/8784).':
        'PVGIS returned {n} hours (expected 8760/8784).',
    'koordinat tidak ditemukan': 'coordinates not found',

    # --- Header ekspor Excel (app/data/exporter.py) -----------------------
    'Beban Th-1 (kWh)': 'Load Yr-1 (kWh)',
    'Diesel Th-1 (L)': 'Diesel Yr-1 (L)',
    'Grid Import Th-1 (kWh)': 'Grid Import Yr-1 (kWh)',
    'RF Th-1 (%)': 'RF Yr-1 (%)',
    'Unserved Th-1 (kWh)': 'Unserved Yr-1 (kWh)',
    'Lifetime (th)': 'Lifetime (yr)',
    'Penggantian BESS': 'BESS Replacement',
}

# ---------------------------------------------------------------- EN -> ID
# Label parameter & KPI (ditulis dalam bahasa Inggris di dalam kode).
_ID = {
    # --- v156: self consumption BESS & kurva SOH ---
    'Self Consumption': 'Konsumsi Sendiri',
    'Self Consumption Supplied by': 'Self Consumption Dipasok oleh',
    'BESS SOH Model': 'Model SOH BESS',
    'BESS SOH Curve': 'Kurva SOH BESS',
    'BESS Self Consumption': 'Konsumsi Sendiri BESS',
    'Annual Degradation': 'Degradasi Tahunan',
    'SOH Curve (Excel)': 'Kurva SOH (Excel)',
    'Import Excel…': 'Impor Excel…',
    # --- v143: sensor & kabel FO/CAN ---
    'Sensor / Camera': 'Sensor / Kamera',
    'Fibre optic (FO)': 'Serat optik (FO)',
    'CAN bus': 'CAN bus',
    # --- v142: editor arsitektur (kabel komunikasi, bentuk) ---
    'Ethernet Hub': 'Ethernet Hub',
    'Polygon': 'Poligon',
    'Rectangle': 'Persegi',
    'RS485': 'RS485',
    'Reset route': 'Reset rute',
    'Server / Cloud Monitoring': 'Server / Cloud Monitoring',
    'TCP/IP (Ethernet)': 'TCP/IP (Ethernet)',
    'Wired control': 'Kabel kendali',
    'Wireless': 'Nirkabel',
    # --- v141: editor arsitektur sistem ---
    'AC power': 'Daya AC',
    'DC power': 'Daya DC',
    'Control / communication': 'Kendali / komunikasi',
    'Accept suggestion': 'Terima saran',
    'Clear': 'Bersihkan',
    'Connect': 'Sambung',
    'Delete': 'Hapus',
    'Fit': 'Paskan',
    'Import Image / PDF…': 'Impor Gambar / PDF…',
    'Label': 'Label',
    'Rating': 'Rating',
    'Redo': 'Ulangi',
    'Undo': 'Batalkan',
    'Refresh': 'Muat ulang',
    'Remove image': 'Hapus gambar',
    'Select': 'Pilih',
    'Show imported image': 'Tampilkan gambar impor',
    'Start from Configuration': 'Mulai dari Konfigurasi',
    'OCR': 'OCR',
    'Design Architecture…': 'Rancang Arsitektur…',
    'PV Array': 'Array PV',
    'PV Inverter': 'Inverter PV',
    'DC/DC Converter': 'Konverter DC/DC',
    'Battery (BESS)': 'Baterai (BESS)',
    'PCS': 'PCS',
    'Diesel Genset': 'Genset Diesel',
    'Utility Grid': 'Grid Utilitas',
    'PCC / Meter': 'PCC / Meter',
    'Transformer': 'Trafo',
    'Circuit Breaker': 'Pemutus (CB)',
    'ATS': 'ATS',
    'AC Bus': 'Rel AC',
    'DC Bus': 'Rel DC',
    'EMS / Controller': 'EMS / Pengendali',
    'Note': 'Catatan',
    # --- v136: Data page ---
    'Active source': 'Sumber aktif', 'Availability': 'Ketersediaan',
    'Export': 'Ekspor',

    # --- v134 ---
    'Objective Control': 'Objective && Kontrol',

    # --- Dashboard & Parameters (v83) ---
    'Priority': 'Prioritas',
    'Discharge Target': 'Target Discharge',
    'BESS Role Function': 'Fungsi Peran BESS',
    'Base Parameters': 'Parameter Dasar',
    'PV before smoothing': 'PV sebelum smoothing',
    'PV after smoothing': 'PV setelah smoothing',
    # --- EMS BESS multi-mode (v78) — tab & grafik ---
    'Advanced (EMS)': 'Advanced (EMS)',
    'PV Ramp': 'Ramp PV',
    'PV Ramp Actual': 'Ramp PV Aktual',
    'PV Ramp Allowed': 'Ramp PV Diizinkan',
    'PV Ramp Smoothed': 'Ramp PV Dihaluskan',
    # --- EMS BESS multi-mode — label mode & parameter (v85: tanpa prefiks induk) ---
    'Smoothing': 'Smoothing',
    'Firming': 'Firming',
    'Load Shifting': 'Load Shifting',
    'Peak Shaving': 'Peak Shaving',
    'DG Minimum Loading': 'DG Minimum Loading',
    'Operating Reserve': 'Cadangan Operasi',
    'Backup': 'Backup',
    'Priority': 'Prioritas',
    'DEG/Grid Ramp-Up Limit': 'Batas Ramp-Naik DEG/Grid',
    'DEG/Grid Ramp-Down Limit': 'Batas Ramp-Turun DEG/Grid',
    'Target Power': 'Daya Target',
    'Firming Target Met': 'Target Firming Tercapai',
    'Firming Window': 'Jendela Firming', 'PV Power': 'Daya PV', 'Time': 'Waktu',
    'PV Threshold Start': 'Ambang PV Mulai', 'PV Threshold End': 'Ambang PV Berhenti',
    'Start Time': 'Jam Mulai', 'End Time': 'Jam Berhenti',
    'Peak Window Start': 'Awal Jendela Puncak',
    'Peak Window End': 'Akhir Jendela Puncak',
    'Off-Peak Tariff': 'Tarif Luar Puncak',
    'Threshold': 'Ambang',
    'SOC Fraction': 'Fraksi SOC',
    'Power': 'Daya',
    # --- Advanced (EMS) chart (v85) ---
    'PV only': 'PV saja',
    'PV smoothed': 'PV dihaluskan',
    'PV firmed': 'PV di-firming',
    'DEG/Grid only': 'DEG/Grid saja',
    'DEG/Grid smoothed': 'DEG/Grid dihaluskan',
    'DEG/Grid firmed': 'DEG/Grid di-firming',
    'BESS Balance': 'Neraca BESS',
    'Reset view': 'Atur ulang tampilan',
    'DEG/Grid Ramp': 'Ramp DEG/Grid',
    'DEG/Grid Ramp Allowed': 'Ramp DEG/Grid Diizinkan',
    'PV Ramp Allowed': 'Ramp PV Diizinkan',
    'EMA Alpha (Smoothing, auto)': 'Alpha EMA (Smoothing, otomatis)',
    # v88 — label mode Smoothing & grafik EMS
    'Target': 'Target', 'MA Window': 'Window MA',
    'MA Window (Smoothing)': 'Window MA (Smoothing)',
    'Ramp-Up Limit': 'Batas Ramp-Naik', 'Ramp-Down Limit': 'Batas Ramp-Turun',
    'PV Ramp-Up Limit': 'Batas Ramp-Naik PV',
    'PV Ramp-Down Limit': 'Batas Ramp-Turun PV',
    'DEG/Grid Base Load': 'Base Load DEG/Grid',
    'Load': 'Beban', 'PV wBESS': 'PV wBESS',
    'DEG/Grid wPV': 'DEG/Grid wPV', 'DEG/Grid wPVBESS': 'DEG/Grid wPVBESS',
    'PV only ramp actual': 'Ramp PV only aktual', 'PV wBESS ramp': 'Ramp PV wBESS',
    'DEG/Grid wPV Ramp': 'Ramp DEG/Grid wPV',
    'DEG/Grid wPVBESS Ramp': 'Ramp DEG/Grid wPVBESS',
    'Plant Inj.': 'Injeksi Plant', 'Plant Inj ramp': 'Ramp Injeksi Plant',
    'Dispatch Config': 'Konfigurasi Dispatch', 'Setting': 'Setelan',
    # --- Fungsi BESS Advanced (v74/v75) ---
    'Dispatch Mode': 'Mode Dispatch',
    'BESS Function (Advanced)': 'Fungsi BESS (Advanced)',
    'Strategy Target (Advanced)': 'Target Strategi (Advanced)',
    'Peak Shaving — Output Cap': 'Peak Shaving — Batas Output',
    'Arbitrage — Peak Window Start': 'Arbitrase — Awal Jendela Puncak',
    'Arbitrage — Peak Window End': 'Arbitrase — Akhir Jendela Puncak',
    'Arbitrage — Off-Peak Tariff': 'Arbitrase — Tarif Luar Puncak',
    'PV Smoothing — Max Ramp': 'PV Smoothing — Ramp Maksimum',
    'Spinning Reserve — Fraction': 'Spinning Reserve — Fraksi',
    # --- Mode Case Analysis (v14) ---
    'Mode Case Analysis': 'Mode Analisis Case',
    # --- label umum yang belum diterjemahkan ---
    'Generate Feasibility Study (PDF)': 'Buat Studi Kelayakan (PDF)',
    'Generate Feasibility Study': 'Buat Studi Kelayakan',
    'Project Name': 'Nama Proyek',
    'Customer': 'Pelanggan',
    'Site Name': 'Nama Lokasi',
    'Location': 'Lokasi',
    'Simulation Year': 'Tahun Simulasi',
    'Any Grid Connection': 'Ada Sambungan Grid',
    'PV-BESS Export to Grid': 'Ekspor PV-BESS ke Grid',
    'PV Capacity (DC)': 'Kapasitas PV (DC)',
    'PV Inverter Capacity (AC)': 'Kapasitas Inverter PV (AC)',
    # --- label opsi per status grid (v9/v10) ---
    'Load Priority Follows Grid Status': 'Prioritas Beban Mengikuti Status Grid',
    'Load Priority — Grid Available (1)': 'Prioritas Beban — Grid Tersedia (1)',
    'Load Priority — Grid Unavailable (0)': 'Prioritas Beban — Grid Padam (0)',
    'DEG Options Follow Grid Status': 'Opsi DEG Mengikuti Status Grid',
    'DEG Interlock with PV-BESS — Grid Available (1)': 'Interlock DEG dengan PV-BESS — Grid Tersedia (1)',
    'DEG Interlock with PV-BESS — Grid Unavailable (0)': 'Interlock DEG dengan PV-BESS — Grid Padam (0)',
    'Allow DEG Charging to BESS — Grid Available (1)': 'Izinkan DEG Mengisi BESS — Grid Tersedia (1)',
    'Allow DEG Charging to BESS — Grid Unavailable (0)': 'Izinkan DEG Mengisi BESS — Grid Padam (0)',
    # grup parameter
    'General': 'Umum', 'Grid': 'Jaringan (Grid)',
    'Dispatch Strategy': 'Strategi Dispatch', 'Diesel': 'Diesel',
    'Battery': 'Baterai (BESS)', 'PV': 'PV', 'Finance': 'Finansial',
    'Multi-Year (Lifetime)': 'Multi-Tahun (Lifetime)',
    'Optimization Constraints': 'Batasan Optimasi',
    # label parameter penting
    'Simulation Interval': 'Interval Simulasi',
    'Match simulation': 'Ikuti simulasi',
    'Time Resolution': 'Resolusi Waktu',
    'Discount Rate': 'Tingkat Diskonto',
    'Inflation': 'Inflasi', 'Project Lifetime': 'Umur Proyek',
    'Any grid connection?': 'Ada sambungan grid?',
    'Grid Capacity': 'Kapasitas Grid',
    'Grid Minimum Loading': 'Loading Minimum Grid',
    'Grid Maximum Loading': 'Loading Maksimum Grid',
    'Grid Tariff': 'Tarif Grid', 'Export Tariff': 'Tarif Ekspor',
    'PV-BESS Export to Grid?': 'PV-BESS Boleh Ekspor ke Grid?',
    'Load Supply Priority': 'Prioritas Pasokan Beban',
    'BESS Charging Priority': 'Prioritas Pengisian BESS',
    'Strict Charging Priority': 'Prioritas Pengisian Ketat',
    'Allow Grid Charging to BESS': 'Izinkan Grid Mengisi BESS',
    'Allow DEG Charging to BESS': 'Izinkan DEG Mengisi BESS',
    'DEG Interlock with PV-BESS': 'Interlock DEG dengan PV-BESS',
    'DEG Can Synchronise': 'DEG Dapat Sinkron',
    'DEG Must Always Run': 'DEG Wajib Selalu Nyala',
    'Grid-Forming DEG Priority': 'Prioritas DEG Grid-Forming',
    'Grid Interlock with PV-BESS': 'Interlock Grid dengan PV-BESS',
    'DEG Interlock with Grid': 'Interlock DEG dengan Grid',
    'Total DEG': 'Jumlah DEG', 'Diesel Price': 'Harga Solar',
    'DEG-1 Capacity': 'Kapasitas DEG-1', 'DEG-2 Capacity': 'Kapasitas DEG-2',
    'DEG-3 Capacity': 'Kapasitas DEG-3',
    'Minimum Loading per DEG': 'Loading Minimum per DEG',
    'Maximum Loading per DEG': 'Loading Maksimum per DEG',
    'DEG-1 Fuel Consumption Rate': 'Laju Konsumsi BBM DEG-1',
    'DEG-2 Fuel Consumption Rate': 'Laju Konsumsi BBM DEG-2',
    'DEG-3 Fuel Consumption Rate': 'Laju Konsumsi BBM DEG-3',
    'DEG CAPEX': 'CAPEX DEG',
    'Nominal Capacity': 'Kapasitas Nominal',
    'Initial SOC': 'SOC Awal', 'Minimum SOC': 'SOC Minimum',
    'Maximum SOC': 'SOC Maksimum',
    'Round Trip Efficiency': 'Efisiensi Round-Trip',
    'Maximum Charge Power': 'Daya Charge Maksimum',
    'Maximum Discharge Power': 'Daya Discharge Maksimum',
    'Charge from Grid below SOC': 'Charge dari Grid di bawah SOC',
    'BESS Lifetime': 'Umur Pakai BESS',
    'BESS SOH Threshold': 'Ambang SOH BESS',
    'BESS Degradation per Year': 'Degradasi BESS per Tahun',
    'BESS CAPEX': 'CAPEX BESS',
    'PV Capacity': 'Kapasitas PV', 'PV Module Rating': 'Rating Modul PV',
    'PV Inverter Capacity': 'Kapasitas Inverter PV',
    'PV Degradation per Year': 'Degradasi PV per Tahun',
    'Base Profile Plant Size': 'Kapasitas Acuan Profil',
    'PV CAPEX': 'CAPEX PV', 'Inverter CAPEX': 'CAPEX Inverter',
    'O&M Cost': 'Biaya O&M',
    'Accessories Cost': 'Biaya Aksesoris',
    'Logistic Cost': 'Biaya Logistik',
    'EPC Cost': 'Biaya EPC',
    'Baseline Comparison': 'Pembanding Baseline',
    'Maximum Unused Energy (Curtailment)':
        'Unused Energy Maksimum (Curtailment)',
    'Minimum Renewable Fraction': 'Renewable Fraction Minimum',
    'Maximum LCOE': 'LCOE Maksimum', 'Maximum CAPEX': 'CAPEX Maksimum',
    'Maximum Diesel Consumption': 'Konsumsi Solar Maksimum',
    'Target Diesel Reduction': 'Target Pengurangan Solar',
    'Maximum Unserved Energy': 'Unserved Energy Maksimum',
    # KPI
    'Annual Load': 'Beban Tahunan',
    'Annual PV Generation': 'Produksi PV Tahunan',
    'PV Inverter Output': 'Output Inverter PV',
    'Battery Charge': 'Charge Baterai',
    'BESS Charge from PV': 'Charge BESS dari PV',
    'BESS Charge from Grid': 'Charge BESS dari Grid',
    'BESS Charge from DEG': 'Charge BESS dari DEG',
    'Battery Discharge': 'Discharge Baterai',
    'Battery Throughput': 'Throughput Baterai',
    'Battery Cycles': 'Siklus Baterai',
    'Renewable Fraction': 'Renewable Fraction',
    'Unused Energy / Curtailment': 'Unused Energy / Curtailment',
    'PV Curtailment': 'PV Curtailment',
    'Diesel Runtime': 'Jam Operasi Diesel',
    'Diesel Energy': 'Energi Diesel', 'Diesel Fuel': 'Konsumsi Solar',
    'Diesel Avg Loading': 'Loading Rata-rata Diesel',
    'SOC Min': 'SOC Min', 'SOC Max': 'SOC Maks',
    'Grid Import': 'Impor Grid', 'Grid Export': 'Ekspor Grid',
    'Unserved Energy': 'Unserved Energy',
    'CAPEX': 'CAPEX', 'OPEX Tahun-1': 'OPEX Tahun-1',
    'LCOE Lifetime': 'LCOE Lifetime', 'NPV': 'NPV', 'IRR': 'IRR',
    'ROI': 'ROI', 'Payback': 'Payback',
    'PV + BESS → Load': 'PV + BESS → Beban',
    'Grid → Load': 'Grid → Beban',
    'Diesel → Load': 'Diesel → Beban',
    'BESS Autonomy': 'Autonomy BESS', 'PV Generation': 'Produksi PV',
    'Diesel Energy': 'Energi Diesel', 'Unused/Curtail': 'Unused/Curtail',
    'Unserved': 'Unserved', 'Payback': 'Payback',
    # --- Pemilih lokasi (peta) ---
    'Coordinates': 'Koordinat', 'Lat': 'Lat', 'Lon': 'Lon',
    'Select on Map': 'Pilih di Peta',
    'Pick the project location on an interactive map (search by lat/lon or '
    'place name).':
        'Pilih lokasi proyek pada peta interaktif (cari via lat/lon atau '
        'nama tempat).',
    'Latitude (−90…90)': 'Latitude (−90…90)',
    'Longitude (−180…180)': 'Longitude (−180…180)',
    'Select Project Location': 'Pilih Lokasi Proyek',
    'Search coordinates or a place, or click the map / drag the pin to set '
    'the project location.':
        'Cari koordinat atau nama tempat, atau klik peta / seret pin untuk '
        'menentukan lokasi proyek.',
    'Go': 'Cari',
    'Search place (e.g. Denpasar, Bali)': 'Cari tempat (mis. Denpasar, Bali)',
    'Search Place': 'Cari Tempat',
    'Searching…': 'Mencari…',
    'Place not found.': 'Tempat tidak ditemukan.',
    'Search failed — check your internet connection.':
        'Pencarian gagal — periksa koneksi internet.',
    'Address:': 'Alamat:',
    'Getting address…': 'Mengambil alamat…',
    'Address not available (offline?).': 'Alamat tidak tersedia (offline?).',
    'Select Location': 'Pilih Lokasi', 'Cancel': 'Batal',
    'Map unavailable': 'Peta tidak tersedia',
    'The map component is not available in this build. You can still type '
    'latitude and longitude manually.':
        'Komponen peta tidak tersedia pada build ini. Anda masih dapat '
        'mengetik latitude dan longitude secara manual.',
    # --- Unduh data PV/iradiansi PVGIS ---
    'Download PV/irradiance data (PVGIS) for this location':
        'Unduh data PV/iradiansi (PVGIS) untuk lokasi ini',
    'When enabled, pressing "Select Location" downloads the hourly PV profile '
    'from the PVGIS open API for these coordinates and uses it as the PV '
    'ENetAC profile (optimal tilt/azimuth, 14% system loss). Requires '
    'internet; leave unchecked to keep the current profile.':
        'Bila aktif, menekan "Pilih Lokasi" akan mengunduh profil PV per-jam '
        'dari API terbuka PVGIS untuk koordinat ini dan memakainya sebagai '
        'profil PV ENetAC (kemiringan/azimut optimal, rugi sistem 14%). '
        'Butuh internet; biarkan nonaktif untuk mempertahankan profil saat ini.',
    'Downloading PV data from PVGIS…': 'Mengunduh data PV dari PVGIS…',
    'PV profile downloaded from PVGIS for {lat:.5f}, {lon:.5f}.':
        'Profil PV berhasil diunduh dari PVGIS untuk {lat:.5f}, {lon:.5f}.',
    'Reference size {p:,.1f} kWp · data year {y}.':
        'Ukuran acuan {p:,.1f} kWp · tahun data {y}.',
    'Annual PV energy {e:,.0f} kWh · specific yield {sy:,.0f} kWh/kWp/yr.':
        'Energi PV tahunan {e:,.0f} kWh · hasil spesifik {sy:,.0f} kWh/kWp/thn.',
    'Note: load profile is still empty — import or enter load data on the '
    'Data page.':
        'Catatan: profil beban masih kosong — impor atau isi data beban di '
        'halaman Data.',
    'Could not download PV data from PVGIS:':
        'Gagal mengunduh data PV dari PVGIS:',
    'When enabled, pressing "Select Location" downloads the hourly PV profile '
    'from the PVGIS open API for these coordinates and uses it as the PV '
    'ENetAC profile. Requires internet; leave unchecked to keep the current '
    'profile.':
        'Bila aktif, menekan "Pilih Lokasi" mengunduh profil PV per-jam dari '
        'API terbuka PVGIS untuk koordinat ini dan memakainya sebagai profil '
        'PV ENetAC. Butuh internet; biarkan nonaktif untuk mempertahankan '
        'profil saat ini.',
    # --- Opsi lanjut PVGIS ---
    'Optimal tilt/azimuth': 'Kemiringan/azimut optimal',
    'Let PVGIS optimise both tilt and azimuth for this location.':
        'Biarkan PVGIS mengoptimalkan kemiringan & azimut untuk lokasi ini.',
    'Tilt': 'Kemiringan',
    'Panel tilt from horizontal (0–90°).':
        'Kemiringan panel dari bidang datar (0–90°).',
    'Azimuth': 'Azimut',
    'PVGIS azimuth: 0=South, 90=West, −90=East, 180=North.':
        'Azimut PVGIS: 0=Selatan, 90=Barat, −90=Timur, 180=Utara.',
    'Loss': 'Rugi',
    'Combined PV system losses (%).': 'Total rugi sistem PV (%).',
    'Year': 'Tahun', 'Auto': 'Otomatis',
    'Radiation-data year. "Auto" matches the length of your existing data.':
        'Tahun data radiasi. "Otomatis" menyesuaikan panjang data yang ada.',
    'orientation: optimal tilt/azimuth':
        'orientasi: kemiringan/azimut optimal',
    'orientation: tilt {t:.0f}° / azimuth {a:.0f}°':
        'orientasi: kemiringan {t:.0f}° / azimut {a:.0f}°',
    ' · loss {l:.1f}%.': ' · rugi {l:.1f}%.',
    # --- Ekspor data PVGIS ke Excel ---
    'Save to Excel…': 'Simpan ke Excel…', 'Close': 'Tutup',
    'Save PVGIS data to Excel': 'Simpan data PVGIS ke Excel',
    'Failed to save Excel:': 'Gagal menyimpan Excel:',
    'PVGIS data saved to Excel:': 'Data PVGIS tersimpan ke Excel:',
    'Datetime': 'Waktu', 'PV Power (kW)': 'Daya PV (kW)',
    'In-plane Irradiance G(i) (W/m2)': 'Iradiansi Bidang G(i) (W/m2)',
    'Global Horizontal Irradiance GHI (W/m2)':
        'Iradiansi Global Horizontal GHI (W/m2)',
    'Annual GHI (kWh/m2/yr)': 'GHI Tahunan (kWh/m2/thn)',
    'Ambient Temperature (C)': 'Suhu Lingkungan (C)',
    'Wind Speed 10m (m/s)': 'Kecepatan Angin 10m (m/s)',
    'Source': 'Sumber', 'Data Year': 'Tahun Data',
    'Time zone (approx.)': 'Zona waktu (perkiraan)', '(local time)': '(waktu lokal)',
    'Reference PV Size (kWp)': 'Ukuran PV Acuan (kWp)',
    'Orientation': 'Orientasi', 'System Loss (%)': 'Rugi Sistem (%)',
    'Mounting': 'Pemasangan', 'Free-standing': 'Berdiri bebas',
    'Building-integrated': 'Terpasang di bangunan',
    'Free-standing: rack-mounted, air flows behind the modules (cooler). '
    'Building-integrated: fixed to a building, less ventilation (warmer, '
    'slightly lower yield).':
        'Berdiri bebas: dipasang pada rak, udara mengalir di belakang modul '
        '(lebih sejuk). Terpasang di bangunan: menempel pada bangunan, '
        'ventilasi kurang (lebih panas, hasil sedikit lebih rendah).',
    'Combined system losses excl. temperature & low-irradiance (cables, '
    'inverter, mismatch, soiling…). PVGIS default 14%.':
        'Total rugi sistem di luar suhu & iradiansi-rendah (kabel, inverter, '
        'mismatch, kotoran…). Bawaan PVGIS 14%.',
    # --- Koreksi tipe-PVSyst ---
    'PVSyst-like correction': 'Koreksi tipe-PVSyst',
    'Apply inverter clipping, inverter part-load efficiency, and '
    'irradiance-dependent DC cabling loss on top of the PVGIS profile '
    'so P/G(i) is closer to PVSyst E_Grid/GlobInc. Inverter and DC '
    'cabling are then removed from the flat PVGIS loss to avoid '
    'double-counting; DC cabling @STC is taken from the loss '
    'calculator.':
        'Terapkan clipping inverter, efisiensi inverter beban-parsial, dan '
        'rugi kabel DC yang bergantung iradiansi di atas profil PVGIS agar '
        'P/G(i) lebih dekat ke E_Grid/GlobInc PVSyst. Inverter & kabel DC lalu '
        'dikeluarkan dari loss datar PVGIS agar tidak dobel-hitung; kabel DC '
        '@STC diambil dari kalkulator rugi.',
    'DC/AC': 'DC/AC',
    'DC/AC ratio = array DC (kWp) ÷ inverter AC (kW). Output is '
    'clipped at Pnom AC = reference kWp ÷ DC/AC.':
        'Rasio DC/AC = array DC (kWp) ÷ inverter AC (kW). Output di-clip pada '
        'Pnom AC = kWp acuan ÷ DC/AC.',
    'Inverter η': 'η Inverter',
    'Inverter plateau efficiency (e.g. Euro/CEC %). Used with a small '
    'self-consumption term for the low-load roll-off.':
        'Efisiensi plateau inverter (mis. Euro/CEC %). Dipakai bersama '
        'konsumsi-sendiri kecil untuk rolloff beban rendah.',
    'PVSyst-like correction applied: clipping @ Pnom AC {pn:,.1f} kW '
    '(DC/AC {r:.2f}), inverter {e:.2f}%, DC cabling @STC {d:.2f}%.':
        'Koreksi tipe-PVSyst diterapkan: clipping @ Pnom AC {pn:,.1f} kW '
        '(DC/AC {r:.2f}), inverter {e:.2f}%, kabel DC @STC {d:.2f}%.',
    'Applied': 'Diterapkan',
    'Handled by "Inverter η" in the PVSyst-like correction — not counted '
    'here.':
        'Ditangani oleh "η Inverter" pada koreksi tipe-PVSyst — tidak '
        'dihitung di sini.',
    'PVSyst-like correction is on: Inverter uses "Inverter η" (this row is '
    'disabled) and DC cabling is scaled with irradiance. Both are excluded '
    'from the total below to avoid double-counting.':
        'Koreksi tipe-PVSyst aktif: Inverter memakai "η Inverter" (baris ini '
        'dinonaktifkan) dan kabel DC diterapkan sebanding iradiansi. Keduanya '
        'dikeluarkan dari Total di bawah agar tidak dobel-hitung.',
    'Inverter DC/AC ratio': 'Rasio DC/AC inverter',
    'Inverter Pnom AC (kW)': 'Pnom AC inverter (kW)',
    'Inverter efficiency (%)': 'Efisiensi inverter (%)',
    'DC cabling @STC (%)': 'Kabel DC @STC (%)',
    # --- Modul bifacial ---
    'Bifacial module': 'Modul bifacial',
    'Add rear-side (bifacial) gain from ground-reflected light on top '
    'of the PVGIS monofacial profile. Requires GHI (downloaded '
    'automatically). Gain per hour = bifaciality × albedo × GHI × '
    'rear-side factor ÷ front G(i).':
        'Tambahkan gain sisi belakang (bifacial) dari pantulan tanah di atas '
        'profil monofacial PVGIS. Butuh GHI (diunduh otomatis). Gain per jam '
        '= bifaciality × albedo × GHI × faktor sisi belakang ÷ G(i) depan.',
    'Albedo': 'Albedo',
    'Ground reflectance: grass ~0.20, dry sand ~0.40, concrete ~0.30, '
    'white membrane ~0.60.':
        'Reflektansi tanah: rumput ~0.20, pasir kering ~0.40, beton ~0.30, '
        'membran putih ~0.60.',
    'Bifaciality': 'Bifaciality',
    'Bifaciality factor from the module datasheet (rear ÷ front '
    'efficiency), typically 65–85%.':
        'Faktor bifaciality dari datasheet modul (efisiensi belakang ÷ '
        'depan), umumnya 65–85%.',
    'Rear factor': 'Faktor belakang',
    'Fraction of ground-reflected light that effectively reaches the '
    'rear (view factor × structure shading × non-uniformity). Lower '
    'for close-to-ground / dense arrays; typical 50–80%.':
        'Fraksi cahaya pantulan tanah yang efektif sampai ke sisi belakang '
        '(view factor × naungan struktur × non-uniformitas). Lebih kecil '
        'untuk array rapat/dekat tanah; umumnya 50–80%.',
    'Bifacial gain +{g:.2f}% (albedo {a:.2f}, bifaciality {b:.2f}%, '
    'rear factor {r:.2f}%).':
        'Gain bifacial +{g:.2f}% (albedo {a:.2f}, bifaciality {b:.2f}%, '
        'faktor belakang {r:.2f}%).',
    'Bifacial requested but GHI unavailable — gain not applied.':
        'Bifacial diminta tetapi GHI tidak tersedia — gain tidak diterapkan.',
    'Bifaciality (%)': 'Bifaciality (%)',
    'Rear-side factor (%)': 'Faktor sisi belakang (%)',
    'Bifacial gain (%)': 'Gain bifacial (%)',
    'n/a (no GHI)': 'tidak ada (tanpa GHI)',
    # --- Kalkulator rugi sistem ---
    'Calc…': 'Hitung…',
    'Open the system-loss calculator (fill components → total loss).':
        'Buka kalkulator rugi sistem (isi komponen → total rugi).',
    'System Loss Calculator': 'Kalkulator Rugi Sistem',
    'Enter each loss component (%). Temperature and low-irradiance losses are '
    'excluded — PVGIS models them separately.':
        'Isi tiap komponen rugi (%). Rugi suhu & iradiansi-rendah tidak '
        'termasuk — PVGIS memodelkannya tersendiri.',
    'Cabling (DC+AC)': 'Kabel (DC+AC)', 'Module mismatch': 'Mismatch modul',
    'DC cabling': 'Kabel DC', 'AC cabling': 'Kabel AC',
    'Soiling / dust': 'Kotoran / debu', 'Shading': 'Bayangan',
    'Availability / other': 'Ketersediaan / lainnya',
    'Total system loss: {v:.2f}%': 'Total rugi sistem: {v:.2f}%',
    'Use This Value': 'Pakai Nilai Ini',
    # --- Sumber PV ENetAC (halaman Data) ---
    'PV ENetAC Source': 'Sumber PV ENetAC',
    'From Excel input': 'Dari input Excel', 'From PVGIS': 'Dari PVGIS',
    'Download modified input Excel…': 'Unduh Input Excel termodifikasi…',
    'Save an input Excel (Datetime, Load, active PV ENetAC, Grid Status) — '
    'e.g. with the PV column replaced by PVGIS data.':
        'Simpan file input Excel (Datetime, Load, PV ENetAC aktif, Grid '
        'Status) — mis. dengan kolom PV diganti data PVGIS.',
    'available': 'tersedia', 'not loaded': 'belum ada',
    'Load and PV ENetAC profiles are required first.':
        'Perlu profil Load dan PV ENetAC terlebih dahulu.',
    'Download Input Excel': 'Unduh Input Excel',
    'Input Excel saved:': 'Input Excel tersimpan:',
    'Annual PV Energy (kWh)': 'Energi PV Tahunan (kWh)',
    'Specific Yield (kWh/kWp/yr)': 'Hasil Spesifik (kWh/kWp/thn)',
    'Hours': 'Jumlah Jam',
    # --- UI shell (redesign v132) ---
    'PROJECT': 'PROYEK', 'ANALYSIS': 'ANALISIS', 'REPORTING': 'LAPORAN',
    'No data loaded': 'Belum ada data',
    'rows': 'baris',
    'Not simulated': 'Belum disimulasi',
    'Simulation ready': 'Hasil simulasi tersedia',
    'Unsaved project': 'Proyek belum disimpan',
    'Language': 'Bahasa', 'Theme': 'Tema',
}


def tr(text: str) -> str:
    """Terjemahkan `text` ke bahasa aktif (fallback: teks asli)."""
    if text is None:
        return text
    if _lang == 'EN':
        return _EN.get(text, text)
    return _ID.get(text, text)
