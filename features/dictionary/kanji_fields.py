"""
Skema field untuk entri Kamus Kanji Bahasa Jepang (`/kanji`), sumber
`kanji_master.csv` (41 kolom, 13.141 baris, hasil gabungan 4 sumber terbuka:
mimneko/kanji-data, KanjiVG, KANJIDIC2, kanjiapi.dev + Anki Kanken).

Beda dengan bunpou_fields.py/kotoba_fields.py (semua kolom flat string),
`kanji_master.csv` punya kolom yang isinya **teks JSON di dalam satu sel**
(list atau object). Kolom-kolom itu TETAP disimpan sebagai TEXT biasa di
sini (lihat kanji_cog.py — json.loads() dipanggil saat render, bukan saat
load), tapi tetap didaftarkan lewat dua set di bawah supaya kanji_cog.py
tidak perlu hardcode nama kolom di banyak tempat:

- LIST_JSON_FIELDS: kolom berisi list JSON, fallback [] kalau sel kosong.
- OBJECT_JSON_FIELDS: kolom berisi object JSON, fallback {}/None kalau
  sel kosong.

Lihat panduan-kamus-kanji-versi-ringkas.md untuk pemetaan kolom -> kategori
tampilan (§3) dan keputusan desain lainnya.
"""

FIELD_NAMES = [
    "kanji",
    "unicode",
    "jumlah_goresan",
    "joyo_status",
    "joyo_urutan",
    "kyouiku_kelas_sd",
    "grade_kanjiapi",
    "jlpt_baru",
    "jlpt_lama",
    "kanken_level",
    "kanken_level_alt",
    "kanken_kyu_resmi",
    "kanken_dict_page",
    "kanken_url",
    "kanjipedia_url",
    "freq_rank_mainichi_shinbun",
    "on_yomi",
    "kun_yomi",
    "nanori",
    "meanings_en",
    "meaning_jp",
    "bentuk_lama_kyuujitai",
    "radikal_kanken",
    "radikal_info_kanken",
    "jukugo_contoh",
    "jumlah_kosakata_terkait",
    "antonim",
    "sinonim",
    "mirip_bentuk",
    "varian",
    "struktur_dekomposisi_kanjivg",
    "elemen_kanjivg",
    "radikal_kanjivg",
    "radikal_posisi_kiri_kanan",
    "radikal_posisi_atas_bawah",
    "jis_menkuten",
    "jis_unicode",
    "jis_level",
    "kategori_nama_anak",
    "kanken_zititai_kubun",
    "sumber",
]

KEY_FIELD = "kanji"

# Pemetaan kolom -> kategori tampilan, sesuai §3 panduan. Kategori
# "Referensi & Data Teknis" berisi field yang sebagian besar DISEMBUNYIKAN
# dari tampilan utama (lihat HIDDEN_TECHNICAL_FIELDS di kanji_cog.py) kecuali
# kanken_url/kanjipedia_url (link referensi) dan jumlah_kosakata_terkait
# (statistik kecil) — keduanya tetap dirender, hanya bukan sebagai section
# penuh.
CATEGORY_FIELDS = {
    "Info Dasar & Goresan": [
        "kanji", "jumlah_goresan", "joyo_status", "joyo_urutan",
        "kyouiku_kelas_sd", "grade_kanjiapi", "jlpt_baru", "jlpt_lama",
        "kanken_level", "kanken_level_alt", "kanken_kyu_resmi",
        "freq_rank_mainichi_shinbun",
    ],
    "Bacaan": ["on_yomi", "kun_yomi", "nanori"],
    "Arti": ["meanings_en", "meaning_jp"],
    "Radikal": [
        "radikal_kanken", "radikal_info_kanken", "radikal_kanjivg",
        "radikal_posisi_kiri_kanan", "radikal_posisi_atas_bawah",
    ],
    "Jukugo Contoh": ["jukugo_contoh"],
    "Kanji Terkait": [
        "antonim", "sinonim", "mirip_bentuk", "varian",
        "bentuk_lama_kyuujitai",
    ],
    "Dekomposisi Grafis": ["struktur_dekomposisi_kanjivg", "elemen_kanjivg"],
    "Referensi & Data Teknis": [
        "unicode", "jis_menkuten", "jis_unicode", "jis_level",
        "kategori_nama_anak", "kanken_zititai_kubun", "kanken_dict_page",
        "sumber", "kanken_url", "kanjipedia_url", "jumlah_kosakata_terkait",
    ],
}

# Kolom list JSON-in-cell (parse ke Python list, fallback [] kalau sel kosong).
LIST_JSON_FIELDS = [
    "on_yomi", "kun_yomi", "nanori", "meanings_en",
    "jukugo_contoh",  # list of {"kategori", "kata"}
    "antonim", "sinonim", "mirip_bentuk", "varian",
    "elemen_kanjivg", "radikal_kanjivg",
    "radikal_posisi_kiri_kanan", "radikal_posisi_atas_bawah",
]

# Kolom object JSON-in-cell (parse ke dict, fallback {} kalau sel kosong).
OBJECT_JSON_FIELDS = [
    "radikal_info_kanken", "struktur_dekomposisi_kanjivg", "sumber",
]