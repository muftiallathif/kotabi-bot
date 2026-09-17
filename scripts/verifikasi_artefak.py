#!/usr/bin/env python3
"""verifikasi_artefak.py — pastikan artefak database memang versi yang diharapkan.

Dibuat setelah kejadian nyata: berkas bernama `database_nihongo.zip` (tanpa versi)
ternyata berisi build 8 September (518.937.899 byte) padahal yang dimaksud build
12 September (548.148.734 byte). Perbedaannya tidak terlihat dari nama, ukuran
sekilas, atau perintah salin yang "berhasil".

Jalankan SEBELUM mengekstrak zip-nya ke data/kamus_nihongo/:

    python3 scripts/verifikasi_artefak.py <zip> database/VERSI.json

Keluar dengan kode != 0 kalau tidak cocok, supaya deploy berhenti — bukan
melanjutkan dengan data yang salah secara diam-diam.
"""
import hashlib, json, os, sys, zipfile

# Penanda isi: build lama vs baru. Ukuran & checksum saja tidak cukup memberi tahu
# APA yang beda; ini menjawabnya langsung.
HARUS_ADA = ['database_nihongo/01_kanji/kanji_inti_terstruktur.json',
             'database_nihongo/01_kanji/kanji_klasifikasi.json',
             'database_nihongo/00_dokumentasi/KONTRAK_DATABASE.md']
TIDAK_BOLEH_ADA = ['database_nihongo/01_kanji/kanji_master.json',
                   'database_nihongo/01_kanji/kanji_dict_tismkanji.json',
                   'database_nihongo/01_kanji/kanji_map_lengkap.json']


def sha256(p, blok=1 << 20):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(blok), b''):
            h.update(b)
    return h.hexdigest()


def main(zip_path, versi_path):
    v = json.load(open(versi_path, encoding='utf-8'))
    gagal = []

    ukuran = os.path.getsize(zip_path)
    print(f'berkas  : {os.path.basename(zip_path)}')
    print(f'ukuran  : {ukuran:,} byte (harapan {v["ukuran_byte"]:,})')
    if ukuran != v['ukuran_byte']:
        gagal.append(f'ukuran tidak cocok: {ukuran:,} != {v["ukuran_byte"]:,}')

    h = sha256(zip_path)
    print(f'sha256  : {h}')
    if not v['sha256'].startswith('('):
        if h != v['sha256']:
            gagal.append(f'sha256 tidak cocok')

    isi = set(zipfile.ZipFile(zip_path).namelist())
    for n in HARUS_ADA:
        if n not in isi:
            gagal.append(f'HILANG (penanda build terbaru): {n}')
    for n in TIDAK_BOLEH_ADA:
        if n in isi:
            gagal.append(f'ADA (penanda build LAMA): {n}')

    if gagal:
        print('\n*** ARTEFAK TIDAK COCOK — JANGAN DIPAKAI ***')
        for g in gagal:
            print('  X', g)
        sys.exit(1)
    print(f'\n✅ cocok dengan {v["versi"]}')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
