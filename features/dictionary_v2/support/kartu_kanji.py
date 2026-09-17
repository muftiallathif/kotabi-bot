#!/usr/bin/env python3
"""kartu_kanji.py — merakit kartu kanji dari master database.

Vertical slice pertama: membuktikan database ini bisa DIPAKAI, bukan cuma lolos audit.

Prinsip yang dipegang, mengikuti KONTRAK_DATABASE.md:
  - Urutan baca mengikuti tabel resolusi di 01_kanji/README.md, bukan tebakan
  - Nilai yang kalah dalam resolusi konflik TIDAK dibuang, hanya tidak ditampilkan
    di lapis utama (lihat resolusi_konflik.json)
  - Kalau database tidak tahu, kartu MENGATAKANNYA — tidak diisi tebakan
  - Kamus prosa tidak dibaca untuk kartu utama; itu lapis "tombol", bukan lapis inti

Pemakaian:
    python3 kartu_kanji.py <folder_database> 妨
"""
import json, os, sys

BESAR = {'frequency_kata.json', 'pitch_accent.json'}


class DB:
    """Pembaca malas — berkas hanya dimuat kalau benar-benar diminta."""

    def __init__(self, root):
        self.root = root
        self._cache = {}

    def j(self, rel):
        if rel not in self._cache:
            p = os.path.join(self.root, rel)
            self._cache[rel] = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
        return self._cache[rel]

    def besar(self, rel, kunci):
        """Berkas ratusan MB dibaca mengalir — jangan pernah json.load()."""
        import ijson
        p = os.path.join(self.root, rel)
        if not os.path.exists(p):
            return None
        with open(p, 'rb') as f:
            for k, v in ijson.kvitems(f, ''):
                if k == kunci:
                    return v
        return None


def kartu(db, k):
    inti = db.j('01_kanji/kanji_inti_terstruktur.json').get(k) or {}
    kls = db.j('01_kanji/kanji_klasifikasi.json').get(k) or {}
    if not inti and not kls:
        # Radikal (⽉, ⻌ dsb) dipindah ke 02_bushu 2026-09-09 dan TIDAK ada di
        # berkas kanji. Tanpa jalur ini, mencari ⽉ berakhir "tidak ditemukan"
        # padahal maksud user jelas 月. Ditemukan lewat vertical slice, bukan audit.
        rad = db.j('02_bushu/radikal_klasifikasi.json').get(k)
        if rad:
            return {'_pengalihan': True, 'kanji': k,
                    'catatan': rad.get('classification_note'),
                    'jenis_entri': 'radikal'}
        return None

    tree = db.j('01_kanji/kanji_dekomposisi_tree.json').get(k)
    komp = [c['kanji'] for c in (tree or {}).get('anak', [])] if tree else []
    ri = inti.get('radikal_info') or {}

    # kanji lain yang berbagi bacaan — bahan pengecoh kuis
    bb = db.j('01_kanji/kanji_bacaan_bersama.json').get(k) or {}
    serupa = []
    for g in bb.get('berbagi_bacaan', []):
        serupa.append((g.get('bacaan'), g.get('kanji_lain') or []))

    return {
        'kanji': k,
        'goresan': inti.get('strokes'),
        'unicode': inti.get('unicode'),
        'bushu': inti.get('radical'),
        'bushu_arti': ri.get('arti_en'),
        'bushu_baca': ri.get('cara_baca_jp'),
        'on': inti.get('on_yomi') or [],
        'kun': inti.get('kun_yomi') or [],
        'nanori': inti.get('name_readings') or [],
        'arti_id': inti.get('meanings_id') or [],
        'arti_en': inti.get('meanings_en') or [],
        'arti_jp': inti.get('meaning_jp'),
        # --- level: SELALU dari kanji_klasifikasi (lihat KONTRAK §3)
        'jouyou': kls.get('jouyou'),
        'kyouiku': kls.get('kyouiku_gakunen'),
        'kanken': kls.get('kanken_resmi_level') or kls.get('kanken_level'),
        'jlpt': kls.get('jlpt_n_level'),
        'jlpt_dasar': kls.get('jlpt_n_dasar'),
        'jinmeiyou': kls.get('jinmeiyou_kubun'),
        'jis': kls.get('jis_men_ku_ten'),
        'jenis_entri': kls.get('jenis_entri'),
        'varian_dari': kls.get('varian_dari'),
        # --- struktur
        'komponen': komp,
        'posisi_kiri_kanan': inti.get('radikal_posisi_kiri_kanan'),
        'posisi_atas_bawah': inti.get('radikal_posisi_atas_bawah'),
        # --- relasi
        'sinonim': inti.get('sinonim') or [],
        'antonim': inti.get('antonim') or [],
        'mirip': inti.get('mirip_bentuk') or [],
        'varian': inti.get('varian') or [],
        'kyuujitai': inti.get('bentuk_lama_kyuujitai'),
        'berbagi_bacaan': serupa,
        'jukugo': inti.get('jukugo_contoh') or [],
        'n_kosakata': inti.get('jumlah_kosakata_terkait'),
        'svg': db.j('01_kanji/svg_urutan_goresan_indeks.json').get(k),
        # --- kamus prosa yang memuat kanji ini (lapis "tombol", tidak dibaca isinya)
        'kamus': sorted(x for x in (db.j('10_meta_kualitas/index_kanji_lintas_kategori.json').get(k) or {})
                        if x.startswith('kanji_dict_')),
        'sumber': inti.get('sources') or kls.get('sources') or [],
    }


def teks(c, freq=None, aksen=None):
    """Render untuk Discord (markdown, di bawah 4.096 karakter)."""
    if c.get('_pengalihan'):
        n = (c.get('catatan') or '').replace('Equivalents:', '').replace('Equivalent:', '').strip()
        return (f"# {c['kanji']}\n**Ini bentuk RADIKAL, bukan kanji.**\n"
                f"Kanjinya: **{n}**\n-# coba `/kanji {n.split()[0] if n else ''}`")
    L = []
    kepala = f"# {c['kanji']}"
    lv = [x for x in [
        f"{c['goresan']} goresan" if c['goresan'] else None,
        f"部首 {c['bushu']}" if c['bushu'] else None,
        f"Kanken {c['kanken']}" if c['kanken'] else None,
        f"JLPT {c['jlpt']}" if c['jlpt'] else None,
        f"SD kelas {c['kyouiku']}" if c['kyouiku'] else None,
        "jōyō" if c['jouyou'] else None,
    ] if x]
    L.append(kepala)
    L.append(' ・ '.join(lv))
    if c['arti_id']:
        L.append(f"**{', '.join(c['arti_id'])}**")
    else:
        L.append("*(arti Indonesia belum ada)*")
    if c['arti_en']:
        L.append(f"_{', '.join(c['arti_en'])}_")
    if c['on']:
        L.append(f"**音** {'・'.join(c['on'])}")
    if c['kun']:
        L.append(f"**訓** {'・'.join(c['kun'])}")
    if c['nanori']:
        L.append(f"**名乗** {'・'.join(c['nanori'])}")
    if aksen:
        L.append(f"**アクセント** {aksen}")
    if c['komponen']:
        pos = c['posisi_kiri_kanan'] or c['posisi_atas_bawah']
        L.append(f"**構成** {' ＋ '.join(c['komponen'])}"
                 + (f"  (posisi {'/'.join(pos)})" if pos else ''))
    if c['bushu_arti']:
        L.append(f"**部首** {c['bushu']} — {c['bushu_arti']}"
                 + (f" ({c['bushu_baca']})" if c['bushu_baca'] else ''))
    rel = []
    if c['antonim']:
        rel.append(f"⇄ lawan {'・'.join(c['antonim'])}")
    if c['sinonim']:
        rel.append(f"≈ mirip arti {'・'.join(c['sinonim'])}")
    if c['mirip']:
        rel.append(f"👁 mirip bentuk {'・'.join(c['mirip'])}")
    if c['kyuujitai']:
        rel.append(f"旧 {c['kyuujitai']}")
    if rel:
        L.append('\n'.join(rel))
    if c['jukugo']:
        j = []
        for x in c['jukugo'][:6]:
            s = x['kata']
            if x.get('romaji'):
                s += f" ({x['romaji']})"
            if x.get('arti_en'):
                s += f" — {x['arti_en'][:40]}"
            j.append(s)
        L.append("**熟語**\n" + '\n'.join('・' + x for x in j))
    if freq:
        L.append("**Frekuensi** " + ' ・ '.join(f"{k} #{v:,}" for k, v in freq))
    if c['berbagi_bacaan']:
        b, lain = c['berbagi_bacaan'][0]
        if lain:
            L.append(f"**Bacaan {b} juga dipakai** {''.join(lain[:20])}"
                     + (f" (+{len(lain)-20})" if len(lain) > 20 else ''))
    kaki = []
    if c['svg']:
        kaki.append(f"urutan goresan: {c['svg']}")
    if c['n_kosakata']:
        kaki.append(f"{c['n_kosakata']:,} kosakata memakai kanji ini")
    if c['kamus']:
        kaki.append(f"{len(c['kamus'])} kamus prosa")
    if kaki:
        L.append('-# ' + ' ・ '.join(kaki))
    return '\n'.join(L)


def main():
    root, k = sys.argv[1], sys.argv[2]
    db = DB(root)
    c = kartu(db, k)
    if not c:
        print(f'{k}: tidak ada di database')
        return
    fr = db.besar('08_data_kuantitatif/frequency_kata.json', k) or {}
    rank = sorted(((s, v) for s, v in (fr.get('rank') or {}).items()
                   if isinstance(v, int)), key=lambda x: x[1])[:3]
    pa = db.besar('08_data_kuantitatif/pitch_accent.json', k) or {}
    ak = None
    for s, lst in (pa.get('aksen') or {}).items():
        for it in lst:
            if it.get('posisi_turun'):
                ak = f"{it.get('bacaan','')} {it['posisi_turun']} ({s})"
                break
        if ak:
            break
    print(teks(c, rank, ak))


if __name__ == '__main__':
    main()
