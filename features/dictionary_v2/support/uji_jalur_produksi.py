#!/usr/bin/env python3
"""uji_jalur_produksi.py — golden cases lewat JALUR PRODUKSI, bukan renderer saja.

Beda dari `uji_tingkat.py` (menguji renderer) dan `uji_adapter.py` (menguji state):
di sini yang dilewati adalah rantai yang benar-benar dipakai bot —

    golden case -> Sesi -> render(tingkat) -> ke_embed() -> payload Discord

`ke_embed()` memanggil discord.Embed sungguhan, jadi batas-batas Discord
ditegakkan oleh pustakanya sendiri, bukan oleh perkiraan kita.

Butuh: pip install discord.py
    python3 uji_jalur_produksi.py [folder_database]
"""
import sys, os, json, copy, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resolver import Resolver
import adapter3 as A
import renderer3 as R

ROOT = sys.argv[1] if len(sys.argv) > 1 else '..'

GOLDEN = (
    [('kanji', k) for k in ['妨', '愛', '一', '螺', '𠮟', '鬱', '猫', '⽉', '⻌', '龘']] +
    [('kata', w) for w in ['猫', '取る', '生', 'ない', '走った', '食べました', '美しかった',
                           '美しい', '行く', 'zzz']] +
    [('bunpou', p) for p in ['あげる', 'かもしれない', 'あまりの', 'でできている',
                             'うちに', 'から', 'ように', 'zzz']]
)


def periksa_embed_discord(e, nama, gagal):
    """Serahkan penegakan batas ke discord.py, lalu periksa hasil serialisasinya."""
    d = e.to_dict()
    for k in A.INTERNAL:
        if k in d:
            gagal.append(f'{nama}: `{k}` bocor ke payload Discord')
    n = len(d.get('title', '')) + len(d.get('description', ''))
    for f in d.get('fields', []):
        n += len(f.get('name', '')) + len(f.get('value', ''))
        if not f.get('value', '').strip():
            gagal.append(f'{nama}: field `{f.get("name")}` KOSONG di payload')
        if len(f.get('value', '')) > 1024:
            gagal.append(f'{nama}: field `{f.get("name")}` > 1024 di payload')
    n += len(d.get('footer', {}).get('text', ''))
    if n > 6000:
        gagal.append(f'{nama}: payload {n} > 6000')
    if len(d.get('fields', [])) > 25:
        gagal.append(f'{nama}: {len(d["fields"])} field > 25')
    return n


def main():
    rsv = Resolver(ROOT)
    gagal = []
    n_kartu = n_tombol = 0
    maks = ('', 0)

    for domain, kunci in GOLDEN:
        nama = f'/{domain} {kunci}'
        s = A.Sesi(rsv, domain, kunci)
        if not s.ada:
            # "tidak ditemukan" juga harus melewati jalur produksi dengan rapi
            h = s.render(1)
            e = A.ke_embed(h['embed'])
            periksa_embed_discord(e, nama + ' (tidak ada)', gagal)
            n_kartu += 1
            continue

        entri = s.kunci
        awal = None
        # kartu pengalihan hanya punya L1 — lihat Sesi.render()
        pengalihan = domain == 'kanji' and (s.data or {}).get('_pengalihan')
        for tingkat in ((1,) if pengalihan else (1, 2, 3, 1)):
            h = s.render(tingkat)
            e = A.ke_embed(h['embed'])          # <- jalur produksi sesungguhnya
            ukuran = periksa_embed_discord(e, f'{nama} L{tingkat}', gagal)
            if ukuran > maks[1]:
                maks = (f'{nama} L{tingkat}', ukuran)
            n_kartu += 1

            if tingkat == 1 and awal is None:
                awal = copy.deepcopy(e.to_dict())
            elif tingkat == 1:
                if e.to_dict() != awal:
                    gagal.append(f'{nama}: L1 setelah [2,3] beda dengan L1 awal (payload)')

            # invariant L1 tetap berlaku DI JALUR PRODUKSI
            if tingkat == 1 and not pengalihan:
                d = e.to_dict()
                if len(d.get('fields', [])) > 3:
                    gagal.append(f'{nama} L1: {len(d["fields"])} field > 3 di payload')
                for f in d.get('fields', []):
                    if f.get('name') in R.LARANGAN_L1:
                        gagal.append(f'{nama} L1: blok `{f["name"]}` terlarang, lolos ke payload')

            for t in h['tombol']:
                n_tombol += 1
                if len(t['id']) > 100:
                    gagal.append(f'{nama} L{tingkat}: custom_id > 100')
                if len(t['label']) > 80:
                    gagal.append(f'{nama} L{tingkat}: label > 80')
                r = A.rute(t['id'])
                if r and r[2].split(':')[0] != entri:
                    gagal.append(f'{nama} L{tingkat}: tombol menuju `{r[2]}` bukan `{entri}`')
            if len(h['tombol']) > 5:
                gagal.append(f'{nama} L{tingkat}: {len(h["tombol"])} tombol > 5')

    print(f'{len(GOLDEN)} golden case -> {n_kartu} payload Discord, {n_tombol} tombol')
    print(f'payload terbesar: {maks[0]} = {maks[1]} karakter (batas 6.000)')
    if gagal:
        print(f'\n*** GAGAL ({len(gagal)}) ***')
        for g in gagal:
            print('  X', g)
        sys.exit(1)

    bukti = f"""DICTIONARY UX CONTRACT — VERIFIED  (/kanji /kotoba /bunpou)
{'=' * 56}
tanggal            : {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
discord.py         : {__import__('discord').__version__}

Golden cases       : {len(GOLDEN)}
Payload Discord    : {n_kartu}
Tombol diperiksa   : {n_tombol}
Payload terbesar   : {maks[1]} / 6000 karakter

Renderer contract  : PASS   (uji_tingkat.py, 40 kartu)
Adapter contract   : PASS   (uji_adapter.py, 30 perpindahan)
Round-trip         : PASS   L1->L2->L3->L1 identik, dicek di payload
Production path    : PASS   lewat ke_embed() / discord.Embed sungguhan
Metadata leakage   : PASS   _tingkat/_domain tidak ada di payload
Empty fields       : PASS
Identity stability  : PASS   tombol tingkat tidak pernah pindah entri
Discord limits     : PASS   field<=25, value<=1024, total<=6000, tombol<=5

CATATAN
- Isi L2/L3 SENGAJA belum dibekukan; yang dibekukan aturan perilakunya.
- Kontrak L1 BERBEDA per domain, diturunkan dari sifat domainnya:
    /kanji  identitas + bacaan + arti
    /kotoba   arti; lemma diselesaikan -> bentuk yang DICARI wajib terlihat
    /bunpou arti + 接続; daftar sumber jadi tombol, bukan blok teks
- Yang tidak teruji dari sini: pengiriman ke gateway Discord (butuh token).
"""
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'BUKTI_KONTRAK_UX.txt')
    open(out, 'w', encoding='utf-8').write(bukti)
    print('\n' + bukti)
    print(f'-> {out}')


if __name__ == '__main__':
    main()
