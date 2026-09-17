#!/usr/bin/env python3
"""kartu_bunpou.py — merakit kartu pola tata bahasa dari master database.

Vertical slice ketiga. Domain paling bersih dari ketiganya: 3.765 pola, 0 konflik
teridentifikasi. Kalau ada temuan di sini, kemungkinan besar soal PENYAJIAN, bukan
pencarian.

Tiga sumber, peran berbeda:
  bunpou_master             — canonical, 635 pola, 632 punya arti Indonesia
  bunpou_referensi_tambahan — 3.367 pola dari 7 sumber, penjelasan Jepang/Inggris
  bunpou_contoh_kalimat_en  — 450 pola, kalimat + penjelasan Inggris

Pemakaian:
    python3 kartu_bunpou.py <folder_database> あげる
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kartu_kanji import DB

FURI = re.compile(r'([\u4e00-\u9fff]+)\[([ぁ-ん]+)\]')
TAG = re.compile(r'<[^>]+>')
# 359 entri donna_toki_dou_tsukau lama (yang tidak tertimpa versi MDict) masih
# membawa tautan footer dari halaman sumbernya. Datanya SENGAJA dipertahankan —
# itu jejak sumber — tapi tidak layak muncul di kartu.
FOOTER = re.compile(r'^\s*(google\.com/search|itazuraneko\.neocities\.org|[ァ-ヶ]行[ぁ-ん～]+)\s*.*$',
                    re.M)


def bersih(s, furigana=False):
    if not s:
        return ''
    s = FURI.sub(r'\1(\2)' if furigana else r'\1', s)
    s = s.replace('<br>', '\n').replace('<br/>', '\n')
    s = TAG.sub('', s)
    s = FOOTER.sub('', s)
    return re.sub(r'\n{2,}', '\n', s).strip()


def cari(db, pola):
    """Cari pola di tiga berkas. Kunci bisa bervariasi (anotasi furigana, 〈〉)."""
    master = [e for e in db.j('04_bunpou/bunpou_master.json') if e.get('pola') == pola]
    ref = db.j('04_bunpou/bunpou_referensi_tambahan.json')
    r = ref.get(pola)
    if r is None:
        # kunci di referensi_tambahan kadang memuat anotasi: うえで〈目(もく)的(てき)〉
        for k, v in ref.items():
            if bersih(re.sub(r'\(.*?\)', '', k).split('〈')[0]) == pola:
                r = v
                break
    en = db.j('04_bunpou/bunpou_contoh_kalimat_en.json').get(pola)
    return master, r, en


def teks(db, pola):
    master, ref, en = cari(db, pola)
    if not master and not ref and not en:
        return f'{pola}: tidak ada di database'
    L = [f'# {pola}']

    for m in master:
        kep = [x for x in [m.get('level_jlpt'), m.get('tingkat_kepentingan'),
                           m.get('kurung'), m.get('ragam_bahasa')] if x and x != 'Tidak ada']
        if kep:
            L.append(' ・ '.join(kep))
        if m.get('arti_id'):
            L.append(f"**{m['arti_id']}**")
        for f, lbl in [('arti_jp', '意味'), ('arti_en', 'EN')]:
            if m.get(f):
                L.append(f"*{lbl}:* {m[f]}")
        pb = [x for x in (m.get('pembentukan') or []) if x]
        if pb:
            L.append('**接続** ' + ' / '.join(bersih(x) for x in pb))
        for cat in (m.get('catatan') or [])[:2]:
            if cat.get('id'):
                L.append(bersih(cat['id'])[:400])
        kal = [k for k in (m.get('contoh_kalimat') or []) if k.get('kalimat')][:3]
        for k in kal:
            L.append(f"> {bersih(k.get('furigana') or k['kalimat'], furigana=True)}\n"
                     f"> _{bersih(k.get('arti_id',''))}_")
        if m.get('gambar'):
            L.append(f"-# ada {len(m['gambar'])} gambar penjelas")

    if ref and not master:
        pj = ref.get('penjelasan') or {}
        L.append(f"*(belum ada arti Indonesia — {len(pj)} sumber referensi)*")
        for s, t in list(pj.items())[:1]:
            L.append(f"**{s}**\n{bersih(t)[:500]}")
    elif ref:
        pj = ref.get('penjelasan') or {}
        L.append('-# juga dijelaskan di: ' + ', '.join(pj))

    if en and not master:
        for p in (en.get('penjelasan_en') or [])[:1]:
            if p:
                L.append(f"**EN** {p[:300]}")
        for k in (en.get('contoh_kalimat') or [])[:2]:
            L.append(f"> {k.get('kalimat','')}\n> _{k.get('arti_en','')}_")
    return '\n'.join(L)


def main():
    print(teks(DB(sys.argv[1]), sys.argv[2]))


if __name__ == '__main__':
    main()
