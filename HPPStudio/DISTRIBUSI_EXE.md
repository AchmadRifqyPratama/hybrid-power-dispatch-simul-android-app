# Cara Distribusi HPP Studio — Cukup Bagikan **Satu Berkas .exe**

Panduan ini menjelaskan cara membuat **satu berkas `HPPStudio.exe`** (mode *onefile*)
yang bisa Anda bagikan sendiri, tanpa perlu menyertakan folder atau berkas lain.
Semua dependensi (PySide6, pyqtgraph, dll.) dan aset (logo, ikon, panah) sudah
dibungkus **di dalam** berkas .exe tersebut.

> **Penting:** proses *build* harus dijalankan **di komputer Windows**.
> Berkas .exe untuk Windows tidak dapat dibuat dari macOS/Linux.

---

## Langkah Cepat (sekali build)

1. **Siapkan environment** (hanya perlu dilakukan **sekali**).
   Klik dua kali:

   ```
   run_dev.bat
   ```

   Skrip ini membuat virtual-environment di
   `%LOCALAPPDATA%\hppstudio-venv` dan memasang semua paket dari
   `requirements.txt` (plus PyInstaller). Setelah selesai aplikasi akan
   terbuka — boleh langsung ditutup.

2. **Build satu berkas .exe.** Klik dua kali:

   ```
   build_windows_onefile.bat
   ```

   Tunggu hingga muncul pesan **"Selesai!"**.

3. **Hasilnya:**

   ```
   dist\HPPStudio.exe
   ```

   👉 **Cukup bagikan berkas `dist\HPPStudio.exe` ini saja.** Penerima tinggal
   klik dua kali untuk menjalankan — tidak perlu meng-install Python maupun
   berkas pendukung apa pun.

---

## Dua Pilihan Mode Build

| Mode | Skrip | Hasil | Kapan dipakai |
|------|-------|-------|----------------|
| **Onefile** (satu berkas) | `build_windows_onefile.bat` | `dist\HPPStudio.exe` (1 berkas) | Ingin distribusi **paling ringkas** — cukup kirim 1 file |
| **Onedir** (satu folder) | `build_windows.bat` | folder `dist\HPPStudio\` berisi `HPPStudio.exe` + pustaka | Ingin **start-up lebih cepat**; distribusi 1 folder (zip dulu) |

Kedua mode memakai kode dan mesin simulasi yang **sama persis** — hasil
perhitungan identik. Yang berbeda hanya cara pembungkusannya.

---

## Yang Perlu Diketahui tentang Mode Onefile

- **Waktu buka pertama sedikit lebih lama.** Saat dijalankan, berkas .exe
  mengekstrak isinya ke folder sementara Windows lebih dulu, jadi *launch*
  pertama bisa 3–10 detik. Peluncuran berikutnya lebih cepat.

- **Ukuran berkas cukup besar (~150–250 MB)** karena seluruh runtime Python +
  Qt ikut dibungkus. Ini normal untuk aplikasi PySide6 onefile.

- **Data pengguna tetap aman & persisten.** Konfigurasi, bahasa, dan berkas
  proyek `.hpps` **tidak** hilang saat aplikasi ditutup — semuanya disimpan di
  folder pengaturan pengguna (mis. `C:\Users\<nama>\.hpp_studio`), **bukan** di
  dalam .exe.

- **Log jika terjadi error.** Bila aplikasi menutup tak terduga, berkas
  `hppstudio_crash.log` / `hppstudio_error.log` akan tertulis di folder yang
  sama dengan tempat .exe dijalankan. Lampirkan berkas ini bila melapor bug.

- **SmartScreen / antivirus.** Karena .exe belum ditandatangani digital,
  Windows SmartScreen mungkin menampilkan "Windows protected your PC", dan
  sebagian antivirus dapat menandainya keliru (*false positive*). Ini **wajar**
  untuk aplikasi PyInstaller yang belum bersertifikat — **bukan** berarti ada
  virus. Cara memastikan berkas aman & asli, serta langkah bila diblokir,
  dijelaskan lengkap di bagian **"Keamanan & Keaslian Unduhan"** di bawah.

---

## Keamanan & Keaslian Unduhan

Bagian ini memastikan HPP Studio **aman diunduh & dijalankan** saat dibagikan
(mis. lewat email/drive perusahaan atau folder jaringan internal Akartha).

### 1. Kenapa antivirus / SmartScreen kadang menandai (padahal aman)

- **.exe hasil PyInstaller** membungkus runtime Python + Qt lalu mengekstraknya
  ke folder sementara saat dijalankan. Pola ini mirip cara sebagian *installer*
  bekerja, sehingga mesin antivirus berbasis heuristik **kadang** menandainya
  keliru (*false positive*) — bukan karena menemukan kode berbahaya.
- **SmartScreen** menampilkan "Windows protected your PC" semata-mata karena
  berkas ini **baru dan belum bersertifikat digital** (belum punya reputasi),
  **bukan** karena mendeteksi ancaman.
- HPP Studio dibangun dari kode sumber Anda sendiri, **tidak** mengakses
  internet dan **tidak** mengirim data apa pun ke luar.

### 2. Metadata penerbit sudah ditanam di .exe

Sejak versi ini, `HPPStudio.exe` membawa identitas penerbit yang jelas. Klik
kanan `HPPStudio.exe` → **Properties** → tab **Details** akan menampilkan:

| Field | Isi |
|-------|-----|
| Company name | Akartha Energi Baru |
| Product name | HPP Studio |
| File description | HPP Studio — Hybrid Power Plant Simulator (PV + BESS + Diesel + Grid) |
| File / Product version | 0.31.0.0 |
| Copyright | © 2026 Akartha Energi Baru — Developed by ARP · Engineering, Akartha Energy |

.exe dengan metadata penerbit yang jelas **terlihat sah** dan lebih jarang
ditandai keliru dibanding .exe anonim. (Untuk menaikkan versi, sunting angka di
`assets\version_info.txt` lalu build ulang.)

### 3. Verifikasi keaslian dengan SHA-256 (cara utama untuk internal)

Ini **cara paling penting** memastikan penerima mendapat berkas yang **asli &
utuh** — tidak rusak saat diunduh dan tidak diubah pihak lain.

**Otomatis setelah build:** skrip build kini menuliskan sidik jari SHA-256 ke
`dist\SHA256SUMS.txt` dan menampilkannya di layar.

**Pengirim (Anda):**

1. Setelah build, catat nilai SHA-256 yang muncul (atau buka `SHA256SUMS.txt`).
2. Kirim `HPPStudio.exe` lewat jalur tepercaya (drive/email perusahaan).
3. Sampaikan nilai SHA-256 itu **lewat jalur terpisah** (mis. chat/email
   internal) supaya penerima bisa membandingkannya.

**Penerima:** letakkan `verify_download.bat` (disertakan) di folder yang sama
dengan `HPPStudio.exe`, lalu **klik dua kali**. Hasilnya:

- **COCOK / MATCH** → berkas asli & utuh, aman dijalankan.
- **TIDAK COCOK / MISMATCH** → jangan dijalankan; minta berkas ulang.

Atau verifikasi manual lewat Command Prompt di folder berkas:

```
certutil -hashfile HPPStudio.exe SHA256
```

lalu bandingkan hasilnya dengan nilai resmi dari pengirim (abaikan perbedaan
huruf besar/kecil).

### 4. Cara aman mendistribusikan (internal Akartha)

- **Gunakan kanal tepercaya:** OneDrive/Google Drive akun perusahaan, SharePoint,
  atau folder jaringan internal — **hindari** situs *file-hosting* publik acak.
- **Sertakan tiga berkas** agar penerima bisa memverifikasi:
  `HPPStudio.exe`, `SHA256SUMS.txt`, dan `verify_download.bat`.
  (Untuk mode *onedir*, ZIP dulu seluruh folder `dist\HPPStudio\` — ketiga berkas
  sudah ada di dalamnya.)
- **Beri tahu penerima** bahwa peringatan SmartScreen itu wajar dan cara
  melewatinya (langkah di bawah), agar mereka tidak khawatir.

### 5. Menjalankan pertama kali (untuk penerima) — melewati SmartScreen

1. Klik dua kali `HPPStudio.exe`.
2. Bila muncul **"Windows protected your PC"** → klik **More info** →
   **Run anyway**.
3. Alternatif: klik kanan `HPPStudio.exe` → **Properties** → centang
   **Unblock** di bagian bawah → **OK**. Ini menghapus penanda "berkas dari
   internet" sehingga peringatan tidak muncul lagi di komputer itu.

### 6. Jika antivirus memblokir (false positive)

1. **Verifikasi SHA-256 dulu** (bagian 3) untuk memastikan itu berkas build asli
   Anda — bukan berkas lain yang menyamar.
2. **Tambahkan pengecualian (allowlist)** untuk `HPPStudio.exe` atau foldernya di
   antivirus perusahaan — biasanya lewat IT/admin.
3. **Laporkan false positive** ke vendor antivirus (kebanyakan punya halaman
   *submit a file / report false positive*) agar build berikutnya tidak ditandai.
4. Opsional: unggah ke **VirusTotal** untuk menunjukkan bahwa hanya sedikit mesin
   heuristik yang menandai — bukti kuat bahwa ini *false positive*, bukan malware.

### 7. Menghilangkan peringatan secara permanen (opsional, berbayar)

Satu-satunya cara **menghapus** peringatan SmartScreen untuk semua orang adalah
menandatangani .exe dengan **code-signing certificate** (OV atau EV, berlangganan
tahunan berbayar). Untuk **distribusi internal**, langkah ini biasanya **tidak
perlu** — verifikasi SHA-256 + allowlist antivirus perusahaan sudah cukup untuk
kepercayaan di dalam organisasi. Simpan opsi sertifikat untuk nanti bila aplikasi
akan dibagikan ke pihak eksternal.

---

## Ganti Ikon / Logo (opsional)

Ikon aplikasi diambil dari `assets\icon.ico`. Ganti berkas itu (format `.ico`)
lalu build ulang untuk memakai ikon baru.

---

## Ringkas

```
run_dev.bat                 (sekali saja — menyiapkan environment)
build_windows_onefile.bat   (setiap kali ingin build ulang)
→ bagikan: dist\HPPStudio.exe  +  dist\SHA256SUMS.txt  +  verify_download.bat
→ kirim nilai SHA-256 lewat jalur terpisah; penerima cek via verify_download.bat
```

*Catatan: mesin simulasi/dispatch tidak diubah sama sekali dari versi
sebelumnya — hasil perhitungan tetap identik dengan referensi Excel
(deviasi < 1e-6 kWh).*
