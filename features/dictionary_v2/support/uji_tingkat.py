#!/usr/bin/env python3
"""uji_tingkat.py — menegakkan KONTRAK PERILAKU tiga tingkat.

Yang dibekukan di sini adalah **aturan perilakunya**, bukan isi tiap tingkat.
Isi L2/L3 masih boleh berevolusi; yang tidak boleh berubah adalah janjinya:

    L1  scan cepat      identitas + bacaan + arti + satu bukti penggunaan
    L2  belajar dalam   struktur, 部首, relasi, jukugo
    L3  audit           sumber, klasifikasi, frekuensi, metadata

Diuji terhadap STRUKTUR, bukan kalimat. Kalau besok `7画` jadi `7 goresan`,
tes ini tetap lolos — itu memang bukan urusannya.

    python3 uji_tingkat.py [folder_database]
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resolver import Resolver
import renderer3 as R
import kartu_bunpou

ROOT = sys.argv[1] if len(sys.argv) > 1 else '..'

# Golden cases — dipilih karena karakternya berbeda, bukan sebanyak-banyaknya.
KANJI = ['妨', '愛', '猫', '螺', '𠮟', '⽉']
KATA = ['猫', '取る', '走った', '生', '食べました', '美しかった']
BUNPOU = ['あげる', 'かもしれない', 'あまりの', 'でできている', 'うちに', 'から']


def cek_l1(e, nama, gagal, arti_id_ada):
    """L1: ringkas, tanpa provenance, arti Indonesia tidak boleh disembunyikan."""
    nf = len(e.get('fields', []))
    if nf > 3:
        gagal.append(f'{nama} L1: {nf} field > 3 (blok berjudul, bukan baris)')

    for f in e.get('fields', []):
        if f['name'] in R.LARANGAN_L1:
            gagal.append(f'{nama} L1: blok `{f["name"]}` terlarang di L1 '
                         f'(provenance/metadata -> L3)')

    # arti Indonesia harus terlihat TANPA menekan tombol -> ada di description
    if arti_id_ada:
        d = e.get('description') or ''
        if '## ' not in d:
            gagal.append(f'{nama} L1: arti Indonesia tersedia tapi tidak tampil di L1')

    if e.get('_tingkat') != 1:
        gagal.append(f'{nama} L1: _tingkat={e.get("_tingkat")}, harusnya 1')


def cek_l1_kata(e, c, nama, gagal):
    """Khas /word: kalau lemma diselesaikan, bentuk yang DICARI wajib terlihat.

    Tanpa ini, user mengetik 走った lalu melihat kartu 走る dan mengira dirinya
    salah ketik atau bot salah cari.
    """
    if c.get('dari_bentuk'):
        d = e.get('description') or ''
        if c['dari_bentuk'] not in d:
            gagal.append(f'{nama} L1: lemma diselesaikan dari `{c["dari_bentuk"]}` '
                         f'tapi bentuk itu tidak terlihat di L1')


def cek_l1_bunpou(e, master, nama, gagal):
    """Khas /bunpou: 接続 wajib ada kalau datanya ada — itu yang paling dicari.

    Dan daftar sumber tidak boleh jadi blok teks di L1; cukup jumlahnya di tombol.
    """
    nama_blok = [f['name'] for f in e.get('fields', [])]
    if master and [x for x in (master[0].get('pembentukan') or []) if x]:
        if '接続' not in nama_blok:
            gagal.append(f'{nama} L1: 接続 tersedia tapi tidak tampil')
    for b in nama_blok:
        if 'sumber' in b.lower() or b in ('Sumber lain', 'Canonical'):
            gagal.append(f'{nama} L1: blok `{b}` — daftar sumber harus jadi tombol, bukan teks')


def cek_l3(e, nama, gagal):
    """L3 boleh memuat provenance — sekaligus memastikan L1 punya tujuan pindah."""
    if e.get('_tingkat') != 3:
        gagal.append(f'{nama} L3: _tingkat={e.get("_tingkat")}, harusnya 3')


def cek_tombol(h, nama, kunci, gagal):
    """Tombol tingkat WAJIB membawa entri yang SAMA.

    Kalau tombol menjalankan pencarian ulang dengan tafsir berbeda, tingkat
    berhenti menjadi state UI dan berubah jadi tiga command yang kebetulan
    tampil beda. Itu yang dicegah di sini.
    """
    for t in h['tombol']:
        aksi, _, sisa = t['id'].partition(':')
        if aksi[0] in 'kwb' and len(aksi) == 2 and aksi[1] in '123':
            entri = sisa.split(':')[0]
            if entri != kunci:
                gagal.append(f'{nama}: tombol `{t["label"]}` menuju `{entri}`, '
                             f'bukan `{kunci}` — tingkat harus mempertahankan entri')
        if len(t['id']) > 100:
            gagal.append(f'{nama}: custom_id > 100')
    if len(h['tombol']) > 5:
        gagal.append(f'{nama}: {len(h["tombol"])} tombol > 5')


def cek_batas(e, nama, gagal):
    if R.ukur(e) > R.MAKS['total']:
        gagal.append(f'{nama}: total {R.ukur(e)} > {R.MAKS["total"]}')
    for f in e.get('fields', []):
        if len(f['value']) > R.MAKS['field']:
            gagal.append(f'{nama}: field `{f["name"]}` > {R.MAKS["field"]}')
        if not f['value'].strip():
            gagal.append(f'{nama}: field `{f["name"]}` KOSONG')


def main():
    rsv = Resolver(ROOT)
    gagal, n = [], 0

    for k in KANJI:
        c = rsv.kanji(k)
        if not c:
            gagal.append(f'/kanji {k}: resolver mengembalikan None')
            continue
        pengalihan = c.get('_pengalihan')
        h1 = R.kanji_l1(c)
        cek_l1(h1['embed'], f'/kanji {k}', gagal, bool(c.get('arti_id')) if not pengalihan else False)
        cek_batas(h1['embed'], f'/kanji {k} L1', gagal)
        if not pengalihan:
            cek_tombol(h1, f'/kanji {k} L1', k, gagal)
            h2 = R.kanji_l2(c)
            h3 = R.kanji_l3(c, rsv._freq(k), rsv._aksen(k))
            cek_l3(h3['embed'], f'/kanji {k}', gagal)
            for lbl, h in [('L2', h2), ('L3', h3)]:
                cek_batas(h['embed'], f'/kanji {k} {lbl}', gagal)
                cek_tombol(h, f'/kanji {k} {lbl}', k, gagal)
            n += 3
        else:
            n += 1

    for w in KATA:
        r = rsv.kata(w)
        if not r:
            gagal.append(f'/kotoba {w}: resolver mengembalikan None')
            continue
        c, fr, ak = r
        kunci = c['kata']
        h1 = R.kata_l1(c)
        ada_id = any(x.get('arti_id') for x in c['catatan'])
        cek_l1(h1['embed'], f'/kotoba {w}', gagal, ada_id)
        cek_l1_kata(h1['embed'], c, f'/kotoba {w}', gagal)
        for lbl, h in [('L1', h1), ('L2', R.kata_l2(c, fr)), ('L3', R.kata_l3(c))]:
            cek_batas(h['embed'], f'/kotoba {w} {lbl}', gagal)
            cek_tombol(h, f'/kotoba {w} {lbl}', kunci, gagal)
        cek_l3(R.kata_l3(c)['embed'], f'/kotoba {w}', gagal)
        n += 3

    for p in BUNPOU:
        r = rsv.bunpou(p)
        if not r:
            gagal.append(f'/bunpou {p}: resolver mengembalikan None')
            continue
        m, rf, en = r
        B = kartu_bunpou.bersih
        h1 = R.bunpou_l1(p, m, rf, en, B)
        cek_l1(h1['embed'], f'/bunpou {p}', gagal, bool(m and m[0].get('arti_id')))
        cek_l1_bunpou(h1['embed'], m, f'/bunpou {p}', gagal)
        for lbl, h in [('L1', h1), ('L2', R.bunpou_l2(p, m, rf, en, B)),
                       ('L3', R.bunpou_l3(p, m, rf, en, B))]:
            cek_batas(h['embed'], f'/bunpou {p} {lbl}', gagal)
            cek_tombol(h, f'/bunpou {p} {lbl}', p, gagal)
        cek_l3(R.bunpou_l3(p, m, rf, en, B)['embed'], f'/bunpou {p}', gagal)
        n += 3

    print(f'{n} kartu diuji terhadap kontrak 3 tingkat')
    if gagal:
        print(f'\n*** KONTRAK DILANGGAR ({len(gagal)}) ***')
        for g in gagal:
            print('  X', g)
        sys.exit(1)
    print('LOLOS — invariant tingkat terjaga.')
    print('  L1 <= 3 blok berjudul, tanpa provenance, arti Indonesia tidak tersembunyi')
    print('  tombol tingkat mempertahankan entri yang sama')
    print('  batas embed Discord dipatuhi, tidak ada blok kosong')


if __name__ == '__main__':
    main()
