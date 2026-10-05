"""Keamanan aplikasi — gerbang kata sandi (password gate).

Saat dibuka, HPP Studio meminta SATU kata sandi (tanpa username). Kata sandi
TIDAK pernah disimpan sebagai teks; yang tersimpan di sini hanyalah **hash
SHA-256**-nya (64 karakter heksadesimal). Perbandingan saat login memakai
`hmac.compare_digest` agar aman terhadap timing attack.

════════════════════════════════════════════════════════════════════════════
CARA MENGUBAH KATA SANDI
════════════════════════════════════════════════════════════════════════════

CARA 1 — lewat skrip bantu (paling mudah, TANPA mengedit kode):
    python set_password.py
  Skrip akan meminta kata sandi baru dua kali, lalu MENULIS otomatis nilai
  PASSWORD_SHA256 di berkas ini.

CARA 2 — manual (mengedit berkas ini sendiri):
  1. Hasilkan hash dari kata sandi baru, mis. di terminal:
         python -c "import hashlib;print(hashlib.sha256('SANDI_BARU'.encode()).hexdigest())"
  2. Salin keluarannya (64 karakter hex).
  3. Ganti string pada baris  PASSWORD_SHA256 = "..."  di bawah ini.
  4. Simpan berkas. Kata sandi baru langsung berlaku saat aplikasi dibuka lagi.

Kata sandi awal (default) adalah:  "engaeb"
════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import hashlib
import hmac

# Hash SHA-256 dari kata sandi aplikasi.
# Default di bawah = SHA-256("engaeb"). Ubah lewat set_password.py atau manual
# (lihat petunjuk di atas). WAJIB 64 karakter heksadesimal huruf kecil.
PASSWORD_SHA256 = "155960694f24bf8b81cbec1f21cff6a5f6143ff3f62d4a48f9fc005ca178ce76"


def hash_password(password: str) -> str:
    """Kembalikan hash SHA-256 (hex, huruf kecil) dari `password`."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def verify_password(password: str) -> bool:
    """True bila `password` cocok dengan PASSWORD_SHA256.

    Memakai perbandingan waktu-tetap (constant-time) agar tidak membocorkan
    informasi lewat lama waktu pencocokan.
    """
    try:
        return hmac.compare_digest(hash_password(password),
                                   PASSWORD_SHA256.strip().lower())
    except Exception:
        return False
