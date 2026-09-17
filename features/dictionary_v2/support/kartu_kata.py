#!/usr/bin/env python3
"""kartu_kata.py — merakit kartu kosakata dari master database.

Vertical slice kedua. Pertanyaannya berbeda dari /kanji: bukan "apakah datanya benar"
(itu sudah diaudit) melainkan **"bagaimana 1.058.437 entri leksikal disajikan ke
manusia"**.

Sengaja TIDAK didesain panjang di atas kertas. Dibuat, dijalankan pada kata nyata,
lalu diperbaiki dari keluarannya.

Prinsip yang diwarisi dari /kanji:
  - berkas ratusan MB dibaca MENGALIR, tidak pernah json.load()
  - kalau database tidak tahu, kartu mengatakannya
  - resolver mencari jalurnya sendiri; user tidak perlu tahu batas domain
    (lihat pelajaran ⽉ di kartu_kanji.py)

Pemakaian:
    python3 kartu_kata.py <folder_database> 猫
"""
import json, os, sys, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kartu_kanji import DB

# Kamus prosa diurutkan pakai tier di sumber_otoritas.json; ini urutan cadangan
TIER = ['kotoba_dict_shinwaei.json', 'kotoba_dict_daijirin.json',
        'kotoba_dict_jitendex.json', 'kotoba_dict_meikyou.json',
        'kotoba_dict_shinmeikai.json', 'kotoba_dict_sanseido.json']


def cari(db, kata):
    """Cari kata; kalau tidak ketemu, telusuri jalur lain sebelum menyerah."""
    # 1. daftar kata milik user (satu-satunya yang punya arti Indonesia)
    user = None
    for e in db.j('03_kotoba/kotoba_kosakata_user.json'):
        if e.get('kata') == kata:
            user = e
            break
    # 2. bentuk terkonjugasi -> kata dasar (走った -> 走る)
    dasar = None
    if not user:
        bk = db.j('07_referensi_tambahan/bentuk_konjugasi.json').get('entri') or {}
        if kata in bk:
            dasar = bk[kata]
    return user, dasar


# partikel & kata bantu yang ikut terdaftar sbg "kata dasar" di 日本語活用形辞書
BANTU = {'た', 'ない', 'ます', 'て', 'だ', 'う', 'よう', 'れる', 'られる', 'せる',
         'させる', 'たい', 'ぬ', 'ん', 'です', 'ば', 'り'}


def kartu(db, kata, ikuti=True):
    user, dasar = cari(db, kata)

    # Kalau yang diketik bentuk terkonjugasi, JANGAN berhenti di "ini bentuk dari X" —
    # lanjutkan ke kartu X. Ditemukan lewat pemakaian: `/word 走った` dulu berhenti
    # tanpa memberi arti apa pun. Kelas yang sama dengan kasus ⽉ di /kanji.
    if dasar and not user and ikuti:
        kandidat = [x for x in (dasar.get('kata_dasar') or []) if x not in BANTU]
        for kd in kandidat:
            k2 = kartu(db, kd, ikuti=False)
            if k2['catatan'] or k2['kamus']:
                k2['dari_bentuk'] = kata
                k2['bacaan_bentuk'] = dasar.get('bacaan')
                return k2
    idx = db.j('10_meta_kualitas/index_kata_lintas_kategori.json').get(kata) or {}
    kamus = sorted(x for x in idx if x.startswith('kotoba_'))

    c = {'kata': kata, 'dasar': dasar, 'kamus': kamus,
         'catatan': (user or {}).get('catatan_belajar') or [],
         'arti_en': (user or {}).get('arti_en') or [],
         'mengandung_kanji': (user or {}).get('mengandung_kanji') or ''}

    # sinonim & antonim
    sy = db.j('06_sinonim_antonim/synonym_weblio_ruigo.json').get(kata) or {}
    c['sinonim'] = (sy.get('sinonim') or [])[:12]
    c['sinonim_kelompok'] = (sy.get('kelompok') or [])[:2]
    c['jlpt_waller'] = (db.j('08_data_kuantitatif/jlpt_kosakata.json').get(kata) or {}).get('level_jlpt')
    return c


def teks(c, freq=None, aksen=None, definisi=None):
    L = [f"# {c['kata']}"]
    if c.get('dari_bentuk'):
        L.append(f"*dicari sebagai* **{c['dari_bentuk']}**"
                 + (f" ({c['bacaan_bentuk']})" if c.get('bacaan_bentuk') else '')
                 + f" — bentuk terkonjugasi dari {c['kata']}")
    if c['dasar']:
        d = c['dasar']
        kd = [x for x in (d.get('kata_dasar') or []) if x not in BANTU] or (d.get('kata_dasar') or [])
        L.append(f"*bentuk terkonjugasi dari* **{'・'.join(kd)}**"
                 + (f"  ({d.get('bacaan')})" if d.get('bacaan') else ''))

    # --- kepala: level, PoS, pitch — dari catatan user kalau ada
    kep = []
    for cat in c['catatan'][:1]:
        if cat.get('level_jlpt'):
            kep.append(f"JLPT {cat['level_jlpt']}")
        if cat.get('jenis_kata'):
            kep.append(cat['jenis_kata'])
        if cat.get('pitch'):
            kep.append(f"アクセント {cat['pitch']}")
    if not kep and c['jlpt_waller']:
        kep.append(f"JLPT {c['jlpt_waller']} (Waller)")
    if aksen and not any('アクセント' in x for x in kep):
        kep.append(f"アクセント {aksen}")
    if kep:
        L.append(' ・ '.join(kep))

    # --- arti: Indonesia dulu, lalu Inggris
    ada_id = False
    for cat in c['catatan']:
        if cat.get('arti_id'):
            ada_id = True
            pre = f"[{cat.get('jenis_kata')}] " if cat.get('jenis_kata') and len(c['catatan']) > 1 else ''
            L.append(f"**{pre}{cat['arti_id']}**")
    if not ada_id:
        L.append("*(arti Indonesia belum ada — kata ini di luar daftar belajarmu)*")
    if c['arti_en']:
        L.append(f"_{', '.join(c['arti_en'])}_")

    # --- definisi kamus Jepang (satu, dari tier tertinggi)
    if definisi:
        nm, teks_def = definisi
        L.append(f"**{nm}**\n{teks_def[:300]}")

    # --- contoh kalimat
    for cat in c['catatan'][:1]:
        for ex in (cat.get('contoh_kalimat') or [])[:2]:
            kal = ex.get('teks') or ex.get('kalimat') or ''
            L.append(f"> {kal}\n> _{ex.get('arti_id','')}_")
        if cat.get('kata_terkait'):
            L.append("**関連** " + '・'.join(x['teks'] for x in cat['kata_terkait'][:5]))
        if cat.get('antonim'):
            L.append("**対義** " + '・'.join(x['teks'] for x in cat['antonim'][:5]))

    if c['sinonim']:
        L.append("**類語** " + '・'.join(c['sinonim']))
    if freq:
        L.append("**Frekuensi** " + ' ・ '.join(f"{k} #{v:,}" for k, v in freq))

    kaki = []
    if c['mengandung_kanji']:
        kaki.append(f"kanji: {c['mengandung_kanji']}")
    if c['kamus']:
        kaki.append(f"{len(c['kamus'])} kamus")
    for cat in c['catatan'][:1]:
        if cat.get('audio'):
            kaki.append('ada audio')
    if kaki:
        L.append('-# ' + ' ・ '.join(kaki))
    return '\n'.join(L)


def main():
    root, kata = sys.argv[1], sys.argv[2]
    db = DB(root)
    c = kartu(db, kata)
    if not c['catatan'] and not c['kamus'] and not c['dasar']:
        print(f'{kata}: tidak ada di database')
        return
    fr = db.besar('08_data_kuantitatif/frequency_kata.json', kata) or {}
    rank = sorted(((s, v) for s, v in (fr.get('rank') or {}).items()
                   if isinstance(v, int)), key=lambda x: x[1])[:3]
    pa = db.besar('08_data_kuantitatif/pitch_accent.json', kata) or {}
    ak = None
    for s, lst in (pa.get('aksen') or {}).items():
        for it in lst:
            if it.get('posisi_turun'):
                ak = f"{it.get('bacaan','')} {it['posisi_turun']}"
                break
        if ak:
            break
    # definisi dari kamus tier tertinggi yang memuat kata ini
    d = None
    for nm in TIER:
        if nm in c['kamus']:
            for e in db.j('03_kotoba/' + nm):
                if e.get('kata') == kata:
                    d = (nm.replace('kotoba_dict_', '').replace('.json', ''), e.get('arti', ''))
                    break
        if d:
            break
    print(teks(c, rank, ak, d))


if __name__ == '__main__':
    main()
