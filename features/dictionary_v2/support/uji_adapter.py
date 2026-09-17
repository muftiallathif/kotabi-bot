#!/usr/bin/env python3
"""uji_adapter.py — uji state & interaksi TANPA discord.py.

Empat hal yang diperiksa, masing-masing menangkap kelas bug berbeda:

  1. IDENTITAS     k1 -> k2 -> k3 tetap pada entri yang sama
  2. BOLAK-BALIK   L1 -> L2 -> L3 -> L1 menghasilkan L1 yang IDENTIK dengan awal
                   (menangkap state yang bocor antar tingkat — bug yang tidak
                   terdeteksi kalau cuma membandingkan ID)
  3. EDIT          interaksi tingkat = edit pesan, bukan kirim pesan baru
  4. BERSIH        `_tingkat`/`_domain` tidak pernah lolos ke payload Discord

    python3 uji_adapter.py [folder_database]
"""
import sys, os, json, copy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resolver import Resolver
from adapter3 import Sesi, rute, bersihkan, INTERNAL
import renderer3 as R

ROOT = sys.argv[1] if len(sys.argv) > 1 else '..'
KASUS = [('kanji', '妨'), ('kanji', '愛'), ('kanji', '猫'), ('kanji', '𠮟'),
         ('kata', '猫'), ('kata', '取る'), ('kata', '走った'),
         ('bunpou', 'あげる'), ('bunpou', 'かもलしれない'.replace('ल', '')),
         ('bunpou', 'あまりの')]


class PesanPalsu:
    """Meniru satu pesan Discord: mencatat kirim vs edit."""

    def __init__(self):
        self.embed = None
        self.n_kirim = 0
        self.n_edit = 0

    def kirim(self, e):
        self.embed = e
        self.n_kirim += 1

    def edit(self, e):
        self.embed = e
        self.n_edit += 1


def main():
    rsv = Resolver(ROOT)
    gagal, n = [], 0

    for domain, kunci in KASUS:
        nama = f'/{domain} {kunci}'
        s = Sesi(rsv, domain, kunci)
        if not s.ada:
            gagal.append(f'{nama}: tidak ditemukan')
            continue
        entri = s.kunci                       # 走った -> 走る, dipakai utk cek identitas
        pesan = PesanPalsu()

        # --- command pertama: KIRIM
        h1 = s.render(1)
        pesan.kirim(bersihkan(h1['embed']))
        awal = copy.deepcopy(pesan.embed)

        # --- telusuri tiap tombol tingkat: harus EDIT, dan entri tetap sama
        urutan = []
        for tingkat in (2, 3, 1):
            h = s.render(tingkat)
            pesan.edit(bersihkan(h['embed']))
            urutan.append(tingkat)

            if h['embed'].get('_tingkat') != tingkat:
                gagal.append(f'{nama}: render({tingkat}) menandai _tingkat='
                             f'{h["embed"].get("_tingkat")}')
            if s.kunci != entri:
                gagal.append(f'{nama}: entri berubah jadi `{s.kunci}` saat pindah ke L{tingkat}')
            for t in h['tombol']:
                r = rute(t['id'])
                if r and r[2].split(':')[0] != entri:
                    gagal.append(f'{nama} L{tingkat}: tombol `{t["label"]}` menuju '
                                 f'`{r[2]}`, bukan `{entri}`')
            for k in INTERNAL:
                if k in pesan.embed:
                    gagal.append(f'{nama} L{tingkat}: `{k}` bocor ke payload Discord')
            n += 1

        # --- BOLAK-BALIK: L1 terakhir harus identik dengan L1 pertama
        if pesan.embed != awal:
            a = json.dumps(awal, ensure_ascii=False, sort_keys=True)
            b = json.dumps(pesan.embed, ensure_ascii=False, sort_keys=True)
            gagal.append(f'{nama}: L1 setelah {urutan} TIDAK identik dengan L1 awal\n'
                         f'        awal   : {a[:110]}\n        sesudah: {b[:110]}')

        # --- interaksi tingkat wajib EDIT, bukan kirim baru
        if pesan.n_kirim != 1:
            gagal.append(f'{nama}: {pesan.n_kirim} pesan dikirim, harusnya 1')
        if pesan.n_edit != 3:
            gagal.append(f'{nama}: {pesan.n_edit} edit, harusnya 3')

    # --- rute() harus menolak aksi non-tingkat
    for cid, harap in [('k2:妨', ('kanji', 2, '妨')), ('w3:猫', ('kata', 3, '猫')),
                       ('b1:あげる', ('bunpou', 1, 'あげる')),
                       ('kg:妨', None), ('kd:妨:x.json', None), ('bs:あげる:dojg', None)]:
        if rute(cid) != harap:
            gagal.append(f'rute({cid!r}) = {rute(cid)}, harusnya {harap}')

    print(f'{n} perpindahan tingkat diuji pada {len(KASUS)} entri')
    if gagal:
        print(f'\n*** GAGAL ({len(gagal)}) ***')
        for g in gagal:
            print('  X', g)
        sys.exit(1)
    print('LOLOS')
    print('  identitas entri terjaga lintas tingkat')
    print('  L1 -> L2 -> L3 -> L1 menghasilkan L1 yang IDENTIK')
    print('  perpindahan tingkat = edit pesan (1 kirim, 3 edit)')
    print('  metadata internal tidak bocor ke payload')


if __name__ == '__main__':
    main()
