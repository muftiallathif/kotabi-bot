#!/usr/bin/env python3
"""buat_manifest.py — hasilkan bukti yang bisa dibaca TANPA membuka artefaknya.

Dibuat setelah dua kejadian nyata:
  1. berkas bernama `database_nihongo.zip` ternyata berisi build lama, dan
     perbedaannya tidak terlihat dari nama maupun perintah salin yang "berhasil";
  2. pemeriksaan ZIP di sisi penerima berulang kali timeout, sehingga verifikasi
     tidak bisa bergantung pada kemampuan membuka arsipnya.

Kesimpulannya: artefak harus **self-describing**. Manifest ini teks biasa,
beberapa KB, dan memuat identitas artefak + tiap berkas penting di dalamnya.

    python3 scripts/buat_manifest.py <artefak.zip> [keluaran.manifest.txt]

Manifest DIHASILKAN DARI arsip yang sama, bukan diketik tangan — jadi tidak bisa
menyimpang dari isinya.
"""
import hashlib, os, sys, zipfile, datetime

# Berkas yang identitasnya dicatat satu per satu. Sisanya cukup diwakili
# hash artefak keseluruhan.
PENTING = [
    'core/bot.py', '.gitignore',
    'database/README.md', 'database/VERSI.json',
    'scripts/build_kamus.py', 'scripts/verifikasi_artefak.py', 'scripts/buat_manifest.py',
    'tests/uji_transaksi.py', 'tests/README.md',
    'features/dictionary/kanji_cog.py',
    'features/dictionary/kotoba_cog.py',
    'features/dictionary/bunpou_cog.py',
]


def sha256_berkas(p, blok=1 << 20):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(blok), b''):
            h.update(b)
    return h.hexdigest()


def main(zip_path, out=None):
    out = out or zip_path.rsplit('.zip', 1)[0] + '.manifest.txt'
    z = zipfile.ZipFile(zip_path)
    nama = z.namelist()
    akar = nama[0].split('/')[0] + '/' if '/' in nama[0] else ''

    L = []
    L.append('MANIFEST ARTEFAK')
    L.append('=' * 72)
    L.append('Dihasilkan otomatis oleh scripts/buat_manifest.py dari arsip yang sama.')
    L.append('Tujuan: verifikasi tanpa perlu membuka arsipnya.')
    L.append('')
    L.append(f'artefak    : {os.path.basename(zip_path)}')
    L.append(f'ukuran     : {os.path.getsize(zip_path):,} byte')
    L.append(f'sha256     : {sha256_berkas(zip_path)}')
    L.append(f'entri zip  : {len(nama):,}')
    L.append(f'dibuat     : {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}')
    L.append('')
    L.append('BERKAS PENTING')
    L.append('-' * 72)
    L.append(f'{"berkas":44}{"byte":>10}  sha256')
    ada = set(nama)
    for t in PENTING:
        n = akar + t
        if n not in ada:
            L.append(f'{t:44}{"— tidak ada":>10}')
            continue
        d = z.read(n)
        L.append(f'{t:44}{len(d):>10,}  {hashlib.sha256(d).hexdigest()}')
    L.append('')
    L.append('CARA MEMERIKSA')
    L.append('-' * 72)
    L.append(f'  sha256sum {os.path.basename(zip_path)}')
    L.append('  # cocokkan dengan baris `sha256` di atas')
    L.append('')
    L.append('  unzip -p <artefak> <akar>/core/bot.py | sha256sum')
    L.append('  # cocokkan dengan baris core/bot.py di tabel')
    L.append('')
    L.append('Kalau salah satu tidak cocok, artefak yang kamu pegang BUKAN yang dimaksud')
    L.append('manifest ini — jangan dipakai untuk deploy.')

    teks = '\n'.join(L) + '\n'
    open(out, 'w', encoding='utf-8').write(teks)
    print(teks)
    print(f'-> ditulis ke {out}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
