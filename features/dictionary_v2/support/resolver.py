#!/usr/bin/env python3
"""resolver.py — satu pintu masuk ke master database untuk semua domain.

Tidak tahu apa-apa soal Discord. Mengembalikan struktur biasa, supaya bisa dipakai
ulang oleh web frontend / API / CLI tanpa ditulis ulang.

Rantai yang dijaga (KONTRAK_DATABASE.md):
    source → canonical/resolution → RESOLVER → renderer → output

Pelajaran yang sudah tertanam di sini, semuanya dari pemakaian nyata bukan audit:
  - ⽉ dicari di berkas kanji, tidak ketemu → dialihkan ke radikal (kartu_kanji.py)
  - 走った → lemma 走る, dan `た` disaring sebagai auksiliar (kartu_kata.py)
  - kunci bunpou kadang ber-anotasi furigana/〈〉 → dinormalkan saat cari
"""
import os, sys

_T = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '00_dokumentasi', 'tools')
sys.path.insert(0, os.path.abspath(_T))

import kartu_kanji, kartu_kata, kartu_bunpou


class Resolver:
    def __init__(self, root):
        self.db = kartu_kanji.DB(root)

    # -- dipakai bersama: berkas ratusan MB dibaca mengalir, tak pernah json.load
    def _freq(self, k, n=3):
        fr = self.db.besar('08_data_kuantitatif/frequency_kata.json', k) or {}
        return sorted(((s, v) for s, v in (fr.get('rank') or {}).items()
                       if isinstance(v, int)), key=lambda x: x[1])[:n]

    def _aksen(self, k):
        pa = self.db.besar('08_data_kuantitatif/pitch_accent.json', k) or {}
        for s, lst in (pa.get('aksen') or {}).items():
            for it in lst:
                if it.get('posisi_turun'):
                    return f"{it.get('bacaan','')} {it['posisi_turun']}"
        return None

    def kanji(self, k):
        return kartu_kanji.kartu(self.db, k)

    def kata(self, k):
        c = kartu_kata.kartu(self.db, k)
        if not c['catatan'] and not c['kamus'] and not c['dasar']:
            return None
        return c, self._freq(k), self._aksen(k)

    def bunpou(self, p):
        m, r, e = kartu_bunpou.cari(self.db, p)
        return (m, r, e) if (m or r or e) else None

    # -- lapis "tombol": baru dibaca kalau diminta
    def kamus_kanji(self, k, nama):
        d = self.db.j(f'01_kanji/{nama}')
        return d.get(k) if isinstance(d, dict) else None

    def daftar_kamus_kanji(self, k):
        idx = self.db.j('10_meta_kualitas/index_kanji_lintas_kategori.json').get(k) or {}
        return sorted(x for x in idx if x.startswith('kanji_dict_'))

    def svg_goresan(self, k):
        nm = self.db.j('01_kanji/svg_urutan_goresan_indeks.json').get(k)
        if not nm:
            return None
        p = os.path.join(self.db.root, '01_kanji/svg_urutan_goresan', nm)
        return p if os.path.exists(p) else None

    def sumber_bunpou(self, pola, sumber):
        _, r, _ = kartu_bunpou.cari(self.db, pola)
        return ((r or {}).get('penjelasan') or {}).get(sumber)
