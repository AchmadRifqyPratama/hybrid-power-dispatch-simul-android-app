# ⚡ HPP Studio

Aplikasi desktop untuk **simulasi operasi & optimasi sizing Hybrid Power Plant**
(PV + BESS + Diesel Generator + Grid). Pengganti workbook Excel
`sizing_analysis_Villa_Bali` — logika dispatch **identik** dengan Excel
(tervalidasi hingga deviasi 1e-13 pada seluruh 8760 jam), namun ratusan kali
lebih cepat dan tidak membutuhkan Microsoft Excel.

## Fitur

- Simulasi operasi per jam selama 1 tahun (8760/8784 jam)
- Optimasi sizing PV / Inverter / BESS: sweep seluruh kombinasi range dengan
  **NumPy tervektorisasi + multiprocessing** (ratusan–ribuan simulasi/detik)
- 9 objective function (Min LCOE, Max NPV, Min CAPEX, Min Payback, Max RF,
  Min Fuel, Min Grid Import, Min PV Excess, Min Unserved) + optimization
  constraints
- KPI teknis & finansial lengkap: RF, cycles, throughput, curtailment, fuel,
  LCOE, CAPEX, OPEX, NPV, IRR, ROI, payback, cashflow
- Dashboard interaktif: time series (zoom/pan + overview region), pie energy
  mix, bar bulanan, heatmap harian (SOC / Diesel / Excess)
- Laporan HTML mandiri (bisa dibuka browser apa pun, siap kirim ke customer)
  dan export Excel
- Dark / Light mode, parameter tersimpan otomatis (SQLite + JSON)

## Struktur Proyek

```
HPPStudio/
├── main.py                  # entry point
├── requirements.txt
├── hpp_studio.spec          # konfigurasi PyInstaller
├── build_windows.bat        # build .exe satu-klik
├── assets/
│   └── sample_input.xlsx    # contoh input (profil Villa Bali)
└── app/
    ├── config/parameters.py # skema parameter (mudah ditambah)
    ├── engine/
    │   ├── dispatch.py      # logika dispatch per jam (vektorisasi batch)
    │   ├── kpi.py           # KPI teknis + agregasi bulanan
    │   ├── finance.py       # CAPEX/OPEX/LCOE/NPV/IRR/ROI/payback
    │   ├── simulation.py    # fasad simulasi tunggal
    │   └── optimization.py  # sweep grid + ProcessPoolExecutor
    ├── data/
    │   ├── importer.py      # baca Excel Load/PV/Grid (nama kolom fleksibel)
    │   ├── exporter.py      # export hasil ke Excel
    │   └── database.py      # SQLite proyek & profil
    ├── reports/report_builder.py  # laporan HTML (chart SVG inline)
    └── gui/                 # PySide6: theme, widgets, halaman-halaman
```

## Menjalankan (mode pengembangan / VS Code)

Cara tercepat: double-click **`run_dev.bat`** — otomatis memilih Python
3.10–3.13 yang terpasang (PySide6 belum tersedia untuk Python 3.14),
membuat venv di `%LOCALAPPDATA%\\hppstudio-venv` (di luar OneDrive agar
terhindar dari batas panjang path), menginstal dependensi, lalu menjalankan
aplikasi. Untuk menguji engine tanpa GUI: **`selftest.bat`**.

Manual:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python selftest.py     :: verifikasi engine tanpa GUI (opsional)
python main.py         :: jalankan aplikasi
```

Folder `.vscode/` sudah disertakan: buka folder proyek di VS Code, pilih
interpreter `.venv\Scripts\python.exe`, lalu tekan **F5** untuk menjalankan
dengan debugger. `selftest.py` menguji seluruh rantai non-GUI (import →
simulasi → optimasi multiprocessing → export → laporan) dan mencetak ✔ bila
hasil simulasi identik dengan referensi Excel.

## Build .exe Windows

Cukup jalankan **`build_windows.bat`** (double-click). Hasil:
`dist\HPPStudio\HPPStudio.exe`. Salin seluruh folder `dist\HPPStudio`
untuk distribusi — tidak perlu Python maupun Excel di komputer tujuan.

> Mode default *onedir* (start-up cepat). Jika ingin satu file tunggal,
> jalankan `pyinstaller --onefile --windowed main.py` (start-up lebih lambat).

## Format Input

File Excel/CSV, satu sheet, baris pertama header. Kolom yang dikenali
(nama fleksibel, tidak case-sensitive):

| Kolom      | Alias yang dikenali                          | Wajib |
|------------|----------------------------------------------|-------|
| Datetime   | datetime, date, time, waktu, tanggal         | ya    |
| Load       | load, beban, load (kw), load_kw              | ya*   |
| PV ENetAC  | pv, earray, pv earray (kw), pv_kw            | ya*   |
| Grid Status| grid, pln, grid status (1/0)                 | tidak |

\* Load dan PV boleh di file terpisah (import dua kali) atau satu file.
Jumlah baris harus 8760 atau 8784 (tahun kabisat). `Grid Status` = 1 saat
PLN tersedia, 0 saat padam; jika tidak ada dianggap selalu tersedia.
Lihat `assets/sample_input.xlsx`. Tombol **Import dari Workbook Lama** di
halaman Data juga bisa membaca langsung workbook Excel Villa Bali.

## Berkas Proyek (.hpps)

Seluruh pekerjaan dapat disimpan ke satu berkas **`.hpps`** (HPP Studio
Project) lewat tombol **Simpan Proyek…** di halaman Home atau **Ctrl+S**;
membukanya kembali dengan **Buka Proyek…** atau **Ctrl+O**.

Isi berkas: identitas proyek, seluruh parameter (strategi dispatch,
finansial, multi-year, batasan optimasi), profil data 8760 jam (Load,
PV ENetAC, Grid Status), **dan seluruh hasil yang sudah dihitung** —
simulasi (Dashboard & Results), hasil optimasi, serta simulasi
multi-year. Membuka kembali berkas langsung menampilkan semuanya tanpa
perlu menghitung ulang. Formatnya JSON terkompresi gzip: tanpa hasil
hanya ±18 KB, lengkap dengan seluruh hasil ±0,2 MB.

## Alur Pakai

1. **Data** — import Load Profile & PV ENetAC (atau workbook lama / sample)
2. **Parameters** — atur grid, diesel, baterai, PV, finansial, constraints
3. **Dashboard** — *Run Simulation* → lihat time series, mix, bulanan, heatmap
4. **Optimization** — dua mode sizing (Manual Range / Auto Optimizer) dengan
   objective bertingkat. Bagian **Batch Multi-Site** di bawah tabel hasil
   memungkinkan menjalankan optimasi untuk beberapa berkas data sekaligus:
   pilih berkasnya, jalankan, dan tiap site (nama diambil dari nama berkas)
   dioptimasi memakai parameter & objective yang sama. Hasilnya dapat
   diekspor ke satu Excel berisi ringkasan per site plus satu sheet detail
   untuk masing-masing site.

   Alur lama tetap berlaku:
   4b. **Optimization** — isi range PV/INV/BESS + objective → *Run* →
   *Terapkan Terbaik* untuk memindah hasil ke Parameters
5. **Results** — KPI lengkap + cashflow → *Export Excel* / *Generate Report*

## Catatan Teknis

- Logika dispatch mengikuti urutan formula Excel: PV → BESS discharge →
  Diesel (saat grid padam) → Grid, charge dari PV surplus lalu dari
  grid saat SOC < ambang, dengan batas SOC min/max, RTE, dan C-rate.
- Pada optimasi, daya charge/discharge BESS mengikuti C-rate dari parameter
  (Max Charge ÷ Nominal Capacity) sehingga ikut terskala dengan kapasitas.
- Engine dipisah total dari GUI — bisa dipakai dari skrip Python biasa
  (`from app.engine.simulation import SimulationEngine`).
