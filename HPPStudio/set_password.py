"""Ubah kata sandi HPP Studio (gerbang login).

Jalankan:
    python set_password.py

Skrip akan meminta kata sandi baru dua kali (input tersembunyi), menghitung
hash SHA-256-nya, lalu MENULIS otomatis nilai PASSWORD_SHA256 ke berkas
app/config/security.py. Tidak ada kata sandi yang disimpan sebagai teks.

Alternatif tanpa skrip ini: lihat petunjuk "CARA 2 — manual" di dalam
app/config/security.py.
"""
from __future__ import annotations
import getpass
import hashlib
import os
import re
import sys

SEC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'app', 'config', 'security.py')


def main() -> int:
    if not os.path.exists(SEC_PATH):
        print(f'[GAGAL] Tidak menemukan {SEC_PATH}')
        return 1

    # input tersembunyi bila terminal mendukung; jika tidak (mis. IDE),
    # getpass otomatis fallback ke input biasa dengan peringatan.
    pw1 = getpass.getpass('Kata sandi baru        : ')
    if not pw1:
        print('[BATAL] Kata sandi kosong — tidak ada perubahan.')
        return 1
    pw2 = getpass.getpass('Ulangi kata sandi baru : ')
    if pw1 != pw2:
        print('[GAGAL] Dua masukan tidak sama — tidak ada perubahan.')
        return 1

    new_hash = hashlib.sha256(pw1.encode('utf-8')).hexdigest()

    with open(SEC_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    pattern = r'(PASSWORD_SHA256\s*=\s*")[0-9a-fA-F]{64}(")'
    if not re.search(pattern, src):
        print('[GAGAL] Tidak menemukan baris PASSWORD_SHA256 yang valid di '
              'security.py. Ubah manual sesuai petunjuk di berkas itu.')
        return 1
    src2 = re.sub(pattern, lambda m: m.group(1) + new_hash + m.group(2), src,
                  count=1)

    with open(SEC_PATH, 'w', encoding='utf-8') as f:
        f.write(src2)

    print('\n[OK] Kata sandi diperbarui.')
    print(f'     PASSWORD_SHA256 = "{new_hash}"')
    print('     Berlaku saat aplikasi dibuka berikutnya.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
