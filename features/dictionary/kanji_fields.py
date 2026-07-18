"""
Skema field untuk entri Kamus Kanji (kanji_master.csv), meniru pola
FIELD_NAMES / KEY_FIELD / CATEGORY_FIELDS di bunpou_fields.py / kotoba_fields.py.

BEDA PENTING dengan bunpou_fields.py/kotoba_fields.py: beberapa kolom di sini
isinya TEKS JSON di dalam satu sel CSV (list atau object), bukan string flat.
Loader (kanji_cog.py) WAJIB json.loads() kolom-kolom itu saat query/render —
lihat LIST_JSON_FIELDS dan OBJECT_JSON_FIELDS di bawah. Ini beda dari semua
kolom bunpou/kotoba yang flat string murni.

Sumber: kanji_master.csv, 13.141 baris, hasil gabungan 4 repo (lihat
README.md database gabungan kanji). Field urutan HARUS PERSIS sama dengan
header asli file itu — loader melakukan pengecekan header == FIELD_NAMES
sebelum memuat data, sama seperti bunpou_cog.py/kotoba_cog.py.

CATATAN struktur_dekomposisi_kanjivg (DIREVISI dari keputusan awal panduan
desain -- lihat kanji_cog.py _render_dekomposisi_tree()):
  Rencana awal bilang "jangan pernah dirender sebagai pohon nested, terlalu
  kompleks". Setelah dicek langsung ke data: 6.279 dari 6.397 kanji yang
  punya struktur ini BENERAN py children (bukan leaf trivial), dan 99.7%
  dari SEMUA elemen di dalam tree itu (6.431 dari 6.448 elemen unik) py
  baris sendiri di kanji_master -- artinya bacaan & arti tiap cabang BISA
  di-lookup balik, bukan cuma karakter kosong. Kedalaman & ukuran juga
  masih wajar (95%+ kanji depth <=6, tree terbesar cuma 23 node/~1.187
  karakter -- masih di bawah batas embed description 4096 char, walau di
  atas batas field 1024 char).
  Jadi SEKARANG DIRENDER sebagai "cascading tree" pakai box-drawing chars
  (├── └── │), 1 halaman terpisah di embed description (BUKAN field biasa,
  supaya muat kanji dg tree besar), dibungkus code block ``` supaya
  karakter tree-nya rata (monospace). Halaman ini HANYA muncul kalau
  root node py minimal 1 children (tree.get("g") non-empty) -- kanji yg
  struktur_dekomposisi_kanjivg-nya cuma leaf diri sendiri (118 kanji)
  TIDAK dapat halaman ini, sama saja dengan tidak py data.

CATATAN radikal_kanken vs radikal_kanjivg (dikonfirmasi manual dari data,
BUKAN cuma dari README.md):
- radikal_kanken: HAMPIR SELALU 1 karakter tunggal (skema 214-bushu resmi
  Kanken). Contoh: 語 -> "言", 橋 -> "木". Dicek ke seluruh 13.141 baris:
  cuma ADA 1 anomali di sumber asli (丗 -> "一、十", dua kandidat radikal
  dipisah 、) -- bukan bug loader, tampilkan apa adanya, jangan diasumsikan
  selalu bisa di-split jadi 1 karakter saat rendering.
- radikal_kanjivg: list BEBERAPA karakter (bukan 1), berisi elemen struktural
  signifikan versi KanjiVG untuk kanji tsb -- BUKAN representasi pohon/tree
  utuh (itu tugas struktur_dekomposisi_kanjivg yang nested). Contoh: 語 ->
  ["言", "吾"], 橋 -> ["木", "喬"]. Ini semacam "radikal-radikal penting"
  hasil dekomposisi 1 level, beda cakupan dari elemen_kanjivg yang lebih
  superset (termasuk komponen non-radikal, mis. 橋 -> ["木","夭","大","喬",
  "丿","冂","口","呑"]).
  Karena radikal_kanjivg BUKAN 1 radikal tunggal seperti radikal_kanken,
  jangan pernah ditampilkan sebagai "radikal utama alternatif" satu-satu --
  render sebagai daftar ringkas terpisah ("Elemen KanjiVG: 言, 吾"), bukan
  dibandingkan baris-per-baris dengan radikal_kanken.

CATATAN radikal_info_kanken (object, sudah di-lookup, tidak perlu JOIN ke
radikal_master.csv):
  keys: nomor, strokes, kategori, arti_en, cara_baca_jp, cara_baca_romaji
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

# Kolom yang isinya list JSON di dalam sel CSV -- json.loads() -> fallback [].
LIST_JSON_FIELDS = [
    "on_yomi",
    "kun_yomi",
    "nanori",
    "meanings_en",
    "jukugo_contoh",          # list of {"kategori": "小|中|高|外", "kata": str}
    "antonim",
    "sinonim",
    "mirip_bentuk",
    "varian",
    "elemen_kanjivg",
    "radikal_kanjivg",
    "radikal_posisi_kiri_kanan",
    "radikal_posisi_atas_bawah",
]

# Kolom yang isinya object JSON di dalam sel CSV -- json.loads() -> fallback None.
OBJECT_JSON_FIELDS = [
    "radikal_info_kanken",              # {nomor, strokes, kategori, arti_en, cara_baca_jp, cara_baca_romaji}
    "struktur_dekomposisi_kanjivg",     # pohon nested -- JANGAN dirender utuh, lihat kanji_cog.py
    "sumber",
]

# Kategori tampilan -> daftar field sumber yang relevan (dipakai kanji_cog.py
# untuk grouping halaman, bukan untuk validasi header seperti CATEGORY_FIELDS
# bunpou/kotoba karena skema di sini lebih heterogen / butuh logic custom
# per kategori, bukan sekadar gabung field).
CATEGORY_FIELDS = {
    "Info Dasar": [
        "jumlah_goresan", "joyo_status", "joyo_urutan", "kyouiku_kelas_sd",
        "grade_kanjiapi", "jlpt_baru", "jlpt_lama", "kanken_level",
        "kanken_level_alt", "kanken_kyu_resmi", "freq_rank_mainichi_shinbun",
    ],
    "Bacaan": ["on_yomi", "kun_yomi", "nanori"],
    "Arti": ["meanings_en", "meaning_jp"],   # + arti_id dari overlay kanji_meanings_id.csv
    "Radikal": ["radikal_kanken", "radikal_info_kanken", "radikal_kanjivg"],
    "Jukugo Contoh": ["jukugo_contoh"],
    "Kanji Terkait": ["antonim", "sinonim", "mirip_bentuk", "varian", "bentuk_lama_kyuujitai"],
    "Dekomposisi": ["elemen_kanjivg"],
    "Referensi": ["kanken_url", "kanjipedia_url", "jumlah_kosakata_terkait"],
}

# Field teknis yang SENGAJA tidak pernah dirender ke user (lihat panduan §3.8/§9).
HIDDEN_FIELDS = {
    "unicode", "jis_menkuten", "jis_unicode", "jis_level",
    "kategori_nama_anak", "kanken_zititai_kubun", "kanken_dict_page", "sumber",
}

JUKUGO_KATEGORI_LABEL = {
    "小": "🟢 SD",
    "中": "🟡 SMP",
    "高": "🔴 SMA",
    "外": "⚪ Luar Kurikulum",
}