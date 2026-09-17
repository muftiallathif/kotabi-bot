#!/usr/bin/env python3
"""renderer3.py — penyajian 3 tingkat.

Masalah yang diperbaiki: `renderer.py` (v1) menumpahkan semua yang tersedia ke satu
embed. Database ini jauh lebih kaya daripada kebutuhan tampilan normal, jadi yang
penting justru tenggelam.

    Level 1  Quick answer   — yang ingin diketahui orang dalam ±5 detik
    Level 2  Detail         — lebih lengkap, tetap TERKURASI (bukan dump field)
    Level 3  Sumber         — provenance, kamus, perbedaan antar sumber

Prinsipnya: database boleh brutal lengkap, UI jangan.

ISTILAH — didefinisikan supaya invariant bisa diuji, bukan ditafsir
-------------------------------------------------------------------
Embed Discord punya bagian dengan nama teknis yang PASTI:

    title        judul       -> identitas entri (kanji/kata/pola)
    description  deskripsi   -> blok pembuka: level, bacaan, arti
    fields[]     BLOK BERJUDUL, masing-masing punya `name` + `value`
    footer       kaki        -> catatan kecil

"maksimal N field" di bawah SELALU berarti `len(embed["fields"])` —
blok berjudul. Baris di dalam `description` TIDAK dihitung, karena
description adalah satu blok visual utuh.

Jadi L1 `/kanji 妨` = 1 field (熟語) + description berisi 4 baris.
Itu MEMENUHI "maksimal 3 field".

INVARIANT PER TINGKAT — ditegakkan `uji_tingkat.py`
-------------------------------------------------------------------
Kontrak L1 BERBEDA per domain — diturunkan dari sifat domainnya, bukan disalin:

    /kanji   wajib: identitas, bacaan, arti
    /word    wajib: arti; + kalau lemma diselesaikan (走った->走る), bentuk yang
             DICARI wajib terlihat — kalau tidak, user mengira salah ketik
    /bunpou  wajib: arti + 接続. Pola tata bahasa tanpa pembentukan tidak bisa
             dipakai; itu yang paling dicari. Daftar sumber TIDAK BOLEH jadi
             blok teks di L1 — cukup jumlahnya di tombol.

L1  - len(fields) <= 3
    - TIDAK boleh memuat blok provenance/sumber/metadata teknis
      (nama bloknya terdaftar di LARANGAN_L1)
    - kalau arti Indonesia tersedia, HARUS ada di description tanpa
      menekan tombol apa pun
L2  - boleh struktural & relasional; tidak wajib memuat provenance
L3  - boleh provenance, sumber, metadata teknis, dan boleh menyatakan
      ketiadaan data secara eksplisit

Tiap embed diberi tanda `_tingkat` dan `_domain` (dibuang adapter sebelum
dikirim) supaya pengujian memeriksa STRUKTUR, bukan mencocokkan kalimat.
Format boleh berubah — `7画` jadi `7 goresan` — tanpa merusak tes.

Tidak mengimpor discord.py — lihat renderer.py untuk alasannya.
"""
import re

WARNA = {'kanji': 0xD64550, 'kata': 0x3A7CA5, 'bunpou': 0x5B8C5A, 'kosong': 0x6E6E6E}
MAKS = {'judul': 256, 'desk': 4096, 'field': 1024, 'total': 6000}


def _p(s, n):
    s = s or ''
    return s if len(s) <= n else s[:n - 1] + '…'


LARANGAN_L1 = {'Klasifikasi', 'Kamus prosa', 'Kamus', 'Sumber', 'Sumber lain',
               'Frekuensi', 'Canonical', 'Catatan', 'アクセント', '類語'}


def embed(judul, desk='', field=None, warna=0x2B2D31, kaki=None, tingkat=None, domain=None):
    e = {'title': _p(judul, MAKS['judul']), 'color': warna}
    if tingkat:
        e['_tingkat'] = tingkat
    if domain:
        e['_domain'] = domain
    if desk:
        e['description'] = _p(desk, MAKS['desk'])
    if field:
        e['fields'] = [{'name': _p(n, 256), 'value': _p(v, MAKS['field']), 'inline': il}
                       for n, v, il in field[:25] if v]
    if kaki:
        e['footer'] = {'text': _p(kaki, 2048)}
    return e


def ukur(e):
    n = len(e.get('title', '')) + len(e.get('description', ''))
    for f in e.get('fields', []):
        n += len(f['name']) + len(f['value'])
    return n + len(e.get('footer', {}).get('text', ''))


def tombol(id_, label, gaya='secondary'):
    return {'id': id_, 'label': label, 'gaya': gaya}


# ═══════════════════════════════════════════════════════════════════ KANJI ══
def kanji_l1(c):
    """Level 1 — apa yang ingin diketahui orang saat mengetik /kanji 妨?

    Jawabannya: artinya apa, dibaca bagaimana, seberapa sulit. Titik.
    Dekomposisi, jukugo, frekuensi, relasi -> Level 2. Kamus -> Level 3.
    """
    if c.get('_pengalihan'):
        n = (c.get('catatan') or '').replace('Equivalents:', '').replace('Equivalent:', '').strip()
        t = n.split()[0] if n else ''
        return {'embed': embed(c['kanji'], f'Ini bentuk **radikal**, bukan kanji.\nKanjinya: **{t}**',
                               warna=WARNA['kosong'], tingkat=1, domain='kanji'),
                # `kn:` = NAVIGASI ke entri lain, bukan perpindahan tingkat.
                # Dibedakan supaya invariant "tombol tingkat tidak pindah entri"
                # tetap bisa ditegakkan mesin.
                'tombol': [tombol(f'kn:{t}', f'Lihat {t}', 'primary')] if t else []}

    baca = []
    if c['on']:
        baca.append('音 ' + '・'.join(c['on']))
    if c['kun']:
        baca.append('訓 ' + '・'.join(c['kun']))
    lv = ' · '.join(x for x in [
        f"{c['goresan']}画" if c['goresan'] else None,
        f"JLPT {c['jlpt']}" if c['jlpt'] else None,
        f"漢検{c['kanken'].replace('Level ','').replace('Pre-','準')}" if c['kanken'] else None,
        f"小{c['kyouiku']}" if c['kyouiku'] else ('常用' if c['jouyou'] else None)] if x)

    d = [lv, '　'.join(baca)] if lv else ['　'.join(baca)]
    d.append(f"## {'、'.join(c['arti_id'])}" if c['arti_id']
             else f"## {', '.join(c['arti_en'][:4])}" if c['arti_en'] else '')
    if c['arti_id'] and c['arti_en']:
        d.append(f"-# {', '.join(c['arti_en'][:5])}")

    # satu contoh jukugo saja — bukti kanji ini dipakai, bukan daftar
    f = []
    if c['jukugo']:
        j = c['jukugo'][0]
        s = j['kata'] + (f" ({j['romaji']})" if j.get('romaji') else '')
        if j.get('arti_en'):
            s += f" — {_p(j['arti_en'], 40)}"
        f.append(('熟語', s, False))

    tb = [tombol(f"k2:{c['kanji']}", '📖 Detail', 'primary')]
    if c['svg']:
        tb.append(tombol(f"kg:{c['kanji']}", '✏️ 筆順'))
    if c['kamus']:
        tb.append(tombol(f"k3:{c['kanji']}", '🔎 Sumber'))
    return {'embed': embed(c['kanji'], '\n'.join(x for x in d if x), f, WARNA['kanji'], tingkat=1, domain='kanji'),
            'tombol': tb}


def kanji_l2(c):
    """Level 2 — struktur, relasi, jukugo, frekuensi. Masih terkurasi."""
    f = []
    if c['komponen']:
        pos = c['posisi_kiri_kanan'] or c['posisi_atas_bawah']
        v = ' ＋ '.join(c['komponen'])
        if pos:
            v += f"\n-# {'／'.join(pos)}"
        f.append(('構成', v, True))
    if c['bushu']:
        v = c['bushu'] + (f" — {c['bushu_arti']}" if c['bushu_arti'] else '')
        if c['bushu_baca']:
            v += f" ({c['bushu_baca']})"
        f.append(('部首', v, True))
    rel = []
    if c['antonim']:
        rel.append('⇄ ' + '・'.join(c['antonim']))
    if c['sinonim']:
        rel.append('≈ ' + '・'.join(c['sinonim']))
    if c['mirip']:
        rel.append('👁 ' + '・'.join(c['mirip']))
    if c['kyuujitai']:
        rel.append('旧 ' + c['kyuujitai'])
    if rel:
        f.append(('関連漢字', '\n'.join(rel), False))
    if c['jukugo']:
        j = []
        for x in c['jukugo'][:8]:
            s = '・' + x['kata']
            if x.get('arti_en'):
                s += f" — {_p(x['arti_en'], 38)}"
            j.append(s)
        f.append(('熟語', '\n'.join(j), False))
    if c['nanori']:
        f.append(('名乗り', '・'.join(c['nanori']), True))
    kaki = f"{c['n_kosakata']:,} kosakata memakai kanji ini" if c['n_kosakata'] else None
    return {'embed': embed(f"{c['kanji']} — Detail", '', f, WARNA['kanji'], kaki, tingkat=2, domain='kanji'),
            'tombol': [tombol(f"k1:{c['kanji']}", '← Kembali', 'primary')]
                      + ([tombol(f"k3:{c['kanji']}", '🔎 Sumber')] if c['kamus'] else [])}


def kanji_l3(c, freq=None, aksen=None):
    """Level 3 — provenance & metadata. Untuk yang memang ingin mendalami."""
    f = []
    kl = [x for x in [
        f"常用 {c['jouyou']}" if c['jouyou'] is not None else None,
        f"教育 kelas {c['kyouiku']}" if c['kyouiku'] else None,
        f"漢検 {c['kanken']}" if c['kanken'] else None,
        f"JLPT {c['jlpt']} ({c['jlpt_dasar']})" if c['jlpt'] else None,
        f"人名用 {c['jinmeiyou']}" if c['jinmeiyou'] else None,
        f"JIS {c['jis']}" if c['jis'] else None,
        f"Unicode {c['unicode']}" if c['unicode'] else None] if x]
    if kl:
        f.append(('Klasifikasi', '\n'.join(kl), False))
    if freq:
        f.append(('Frekuensi', '\n'.join(f"{k} #{v:,}" for k, v in freq), True))
    if aksen:
        f.append(('アクセント', aksen, True))
    if c['kamus']:
        f.append((f"Kamus prosa ({len(c['kamus'])})",
                  '\n'.join('・' + x.replace('kanji_dict_', '').replace('.json', '')
                            for x in c['kamus']), False))
    if c.get('jenis_entri') and c['jenis_entri'] != 'kanji_utama':
        f.append(('Catatan', f"jenis entri: {c['jenis_entri']}"
                  + (f" dari {'・'.join(c['varian_dari'])}" if c.get('varian_dari') else ''), False))
    return {'embed': embed(f"{c['kanji']} — Sumber", '', f, WARNA['kanji'],
                           'sumber: ' + ', '.join(c['sumber'][:4]) if c['sumber'] else None, tingkat=3, domain='kanji'),
            'tombol': [tombol(f"k1:{c['kanji']}", '← Kembali', 'primary')]
                      + [tombol(f"kd:{c['kanji']}:{n}", n.replace('kanji_dict_', '').replace('.json', '')[:18])
                         for n in c['kamus'][:3]]}


# ═══════════════════════════════════════════════════════════════════ KATA ══
def kata_l1(c):
    d = []
    if c.get('dari_bentuk'):
        d.append(f"-# ← {c['dari_bentuk']} (bentuk terkonjugasi)")
    kep = []
    for cat in c['catatan'][:1]:
        for k, pre in [('level_jlpt', 'JLPT '), ('jenis_kata', ''), ('pitch', '')]:
            if cat.get(k):
                kep.append(pre + str(cat[k]))
    if not kep and c.get('jlpt_waller'):
        kep.append(f"JLPT {c['jlpt_waller']}")
    if kep:
        d.append(' · '.join(kep))
    arti = [cat['arti_id'] for cat in c['catatan'] if cat.get('arti_id')]
    d.append(f"## {' / '.join(arti)}" if arti
             else (f"## {', '.join(c['arti_en'][:3])}" if c['arti_en'] else ''))
    if arti and c['arti_en']:
        d.append(f"-# {_p(', '.join(c['arti_en']), 160)}")

    f = []
    for cat in c['catatan'][:1]:
        ex = (cat.get('contoh_kalimat') or [])[:1]
        if ex:
            x = ex[0]
            f.append(('例文', f"{x.get('teks','')}\n-# {x.get('arti_id','')}", False))
    tb = [tombol(f"w2:{c['kata']}", '📖 Detail', 'primary')]
    if any(cat.get('audio') for cat in c['catatan'][:1]):
        tb.append(tombol(f"wa:{c['kata']}", '🔊'))
    if c['kamus']:
        tb.append(tombol(f"w3:{c['kata']}", '🔎 Sumber'))
    return {'embed': embed(c['kata'], '\n'.join(x for x in d if x), f, WARNA['kata'], tingkat=1, domain='kata'),
            'tombol': tb}


def kata_l2(c, freq=None):
    f = []
    for cat in c['catatan'][:1]:
        ex = (cat.get('contoh_kalimat') or [])[:3]
        if ex:
            f.append(('例文', '\n\n'.join(f"{x.get('teks','')}\n-# {x.get('arti_id','')}" for x in ex), False))
        if cat.get('bacaan_furigana'):
            f.append(('読み', cat['bacaan_furigana'], True))
        if cat.get('kata_terkait'):
            f.append(('関連語', '・'.join(x['teks'] for x in cat['kata_terkait'][:8]), True))
        if cat.get('antonim'):
            f.append(('対義語', '・'.join(x['teks'] for x in cat['antonim'][:8]), True))
    if c['sinonim']:
        f.append(('類語', '・'.join(c['sinonim'][:12]), False))
    if freq:
        f.append(('Frekuensi', ' · '.join(f"{k} #{v:,}" for k, v in freq), False))
    return {'embed': embed(f"{c['kata']} — Detail", '', f, WARNA['kata'],
                           f"kanji: {c['mengandung_kanji']}" if c['mengandung_kanji'] else None, tingkat=2, domain='kata'),
            'tombol': [tombol(f"w1:{c['kata']}", '← Kembali', 'primary')]
                      + ([tombol(f"w3:{c['kata']}", '🔎 Sumber')] if c['kamus'] else [])}


def kata_l3(c, definisi=None):
    f = []
    if definisi:
        nm, t = definisi
        f.append((nm, _p(t, 1000), False))
    if c['sinonim_kelompok']:
        for g in c['sinonim_kelompok'][:2]:
            f.append((f"類語 — {_p(g.get('makna') or g.get('sumber',''), 60)}",
                      '・'.join(g.get('sinonim', [])[:10]), False))
    if c['kamus']:
        f.append((f"Kamus ({len(c['kamus'])})",
                  '\n'.join('・' + x.replace('kotoba_dict_', '').replace('.json', '')
                            for x in c['kamus'][:12]), False))
    return {'embed': embed(f"{c['kata']} — Sumber", '', f, WARNA['kata'], tingkat=3, domain='kata'),
            'tombol': [tombol(f"w1:{c['kata']}", '← Kembali', 'primary')]}


# ═════════════════════════════════════════════════════════════════ BUNPOU ══
def bunpou_l1(pola, master, ref, en, bersih):
    d, f = [], []
    m = master[0] if master else None
    if m:
        kep = [x for x in [m.get('level_jlpt'), m.get('tingkat_kepentingan'),
                           m.get('kurung')] if x and x != 'Tidak ada']
        if kep:
            d.append(' · '.join(kep))
        if m.get('arti_id'):
            d.append(f"## {m['arti_id']}")
        if m.get('arti_jp'):
            d.append(f"-# {m['arti_jp']}" + (f" · {m['arti_en']}" if m.get('arti_en') else ''))
        pb = [bersih(x) for x in (m.get('pembentukan') or []) if x]
        if pb:
            f.append(('接続', ' / '.join(pb), False))
        kal = [k for k in (m.get('contoh_kalimat') or []) if k.get('kalimat')][:1]
        if kal:
            k = kal[0]
            f.append(('例文', f"{bersih(k.get('furigana') or k['kalimat'], True)}\n"
                              f"-# {bersih(k.get('arti_id',''))}", False))
    else:
        d.append('-# belum ada arti Indonesia untuk pola ini')
        pj = (ref or {}).get('penjelasan') or {}
        if pj:
            f.append((list(pj)[0], _p(bersih(pj[list(pj)[0]]), 600), False))
        elif en:
            for p in (en.get('penjelasan_en') or [])[:1]:
                if p:
                    f.append(('EN', _p(p, 600), False))
    tb = [tombol(f"b2:{pola}", '📖 Detail', 'primary')]
    n_sumber = len((ref or {}).get('penjelasan') or {})
    if n_sumber:
        tb.append(tombol(f"b3:{pola}", f'📚 {n_sumber} sumber'))
    return {'embed': embed(pola, '\n'.join(x for x in d if x), f, WARNA['bunpou'], tingkat=1, domain='bunpou'),
            'tombol': tb}


def bunpou_l2(pola, master, ref, en, bersih):
    f = []
    m = master[0] if master else None
    if m:
        for i, cat in enumerate((m.get('catatan') or [])[:3]):
            if cat.get('id'):
                f.append((f'解説 {i+1}', _p(bersih(cat['id']), 1000), False))
        kal = [k for k in (m.get('contoh_kalimat') or []) if k.get('kalimat')][:4]
        if kal:
            f.append(('例文', '\n\n'.join(
                f"{bersih(k.get('furigana') or k['kalimat'], True)}\n-# {bersih(k.get('arti_id',''))}"
                for k in kal), False))
        if m.get('ragam_bahasa') and m['ragam_bahasa'] != 'Tidak ada':
            f.append(('語体', m['ragam_bahasa'], True))
    tb = [tombol(f"b1:{pola}", '← Kembali', 'primary')]
    if m and m.get('gambar'):
        tb.append(tombol(f"bg:{pola}", f"🖼 {len(m['gambar'])}"))
    return {'embed': embed(f'{pola} — Detail', '', f, WARNA['bunpou'], tingkat=2, domain='bunpou'), 'tombol': tb}


def bunpou_l3(pola, master, ref, en, bersih):
    """Level 3 — daftar sumber sebagai TOMBOL, bukan enam blok teks."""
    pj = (ref or {}).get('penjelasan') or {}
    d = (f"Pola ini dijelaskan di **{len(pj)} sumber**. Pilih untuk membandingkan."
         if pj else 'Tidak ada sumber tambahan.')
    f = []
    if master:
        f.append(('Canonical', 'bunpou_master (arti Indonesia)', False))
    if pj:
        f.append(('Sumber lain', '\n'.join('・' + s for s in pj), False))
    return {'embed': embed(f'{pola} — Sumber', d, f, WARNA['bunpou'], tingkat=3, domain='bunpou'),
            'tombol': [tombol(f"b1:{pola}", '← Kembali', 'primary')]
                      + [tombol(f"bs:{pola}:{s}", s[:18]) for s in list(pj)[:4]]}


def tidak_ada(q, domain):
    return {'embed': embed(q, f'Tidak ditemukan di {domain}.', warna=WARNA['kosong']),
            'tombol': []}
