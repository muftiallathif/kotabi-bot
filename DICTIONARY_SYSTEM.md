# DICTIONARY_SYSTEM.md — Sistem Kamus Kotabi Bot (`/bunpou`, `/kotoba`, `/kanji`)

> **Status:** Aktif
> **Sumber kebenaran untuk:** arsitektur bersama 3 command kamus (pipeline
> render HTML/furigana, gating akses, pola loader CSV), skema field
> masing-masing command, keputusan cakupan data, status implementasi
> **BUKAN sumber untuk:** harga tier yang menentukan siapa dapat akses
> detail (lihat `PRICING_SYSTEM_REFACTOR.md`), isi konten kamus itu
> sendiri (lihat file CSV masing-masing: `bunpou-notes-master.csv`,
> `kotoba-notes-master.csv`, `kanji_master.csv`)
> **Terakhir diverifikasi terhadap kode:** 2026-07-21 — checklist
> implementasi di bagian 6 dicek satu-satu terhadap isi `bunpou_cog.py`,
> `kotoba_cog.py`, `kanji_cog.py` aktual, bukan disalin dari dokumen lama.

Menggantikan `panduan-kamus-grammar-versi-ringkas.md`,
`panduan-kamus-kotoba-versi-ringkas.md`, dan
`panduan-kamus-kanji-versi-ringkas.md` (ketiganya jadi Arsip — lihat
`DOCS_INDEX.md`). Digabung karena ketiganya berbagi arsitektur render
yang hampir identik (dokumen lama sendiri sudah punya bagian "Lampiran:
Perbandingan" yang menunjukkan ini) — dipertahankan terpisah cuma
menambah 3× duplikasi konten yang sebenarnya sama.

---

## 1. Perbandingan Tiga Command

| Aspek | `/bunpou` | `/kotoba` | `/kanji` |
|---|---|---|---|
| Perlu authoring manual? | Ya, satu-per-satu | Ya, satu-per-satu | **Tidak** — data sudah jadi (gabungan 4 sumber terbuka) |
| Sumber utama | `bunpou-notes-master.csv`, 91 kolom, flat | `kotoba-notes-master.csv`, 34 kolom, flat | `kanji_master.csv`, 41 kolom, **beberapa JSON-in-cell** |
| Sumber pendukung | — | — | `kanji_meanings_id.csv` (overlay terjemahan ID, LEFT JOIN) |
| Kolom list/object dalam sel? | Tidak | Tidak | **Ya**, 13 kolom — wajib `json.loads()` di layer render |
| Slot berulang | Catatan 1-7, kalimat 1-11 | Kalimat 1-4 saja | Tidak ada slot bernomor (kolom tetap, kecuali list JSON) |
| Pagination | Selalu 2 halaman (kalau ada kalimat contoh) | Selalu 1 halaman | **Dinamis**, 1-4 halaman tergantung isi |
| Mode list gratis, detail terkunci | Ya | Ya | Ya |
| JOIN ke tabel lain? | Tidak | Tidak | Sengaja dihindari (kecuali LEFT JOIN opsional ke `kanji_meanings_id.csv`) |
| Filter tambahan di command | Level JLPT | Level JLPT | JLPT + Jōyō + Kelas SD |
| Arti Bahasa Indonesia | Ada dari sumber (`*DefID`) | Ada dari sumber (`*DefID`) | **Tidak ada di sumber**, diisi bertahap via overlay, fallback EN/JP |

---

## 2. Arsitektur Bersama (berlaku ke ketiga command)

### 2.1 Single source skema field

Tiap command punya file `*_fields.py` sendiri di root `features/dictionary/`
(BUKAN di `support/`) — `bunpou_fields.py`, `kotoba_fields.py`,
`kanji_fields.py` — berisi `FIELD_NAMES`/`KEY_FIELD`/`CATEGORY_FIELDS`.
Cog **tidak pernah** hardcode nama kolom; semua baca dari file skema ini.
Kalau skema berubah, edit file `*_fields.py`, cog otomatis ikut
menyesuaikan.

### 2.2 Loader CSV — full-replace, bukan upsert parsial

Setiap `cog_load()` / command admin `/*_reload`: `DELETE` semua baris
tabel, lalu `INSERT` ulang dari CSV. Alasan sama di ketiga command:
sumbernya flat per-baris, tidak ada tabel anak yang perlu diselaraskan
terpisah. `kanji_meanings_id.csv` (overlay) juga full-replace terpisah,
supaya edit manual langsung kepakai setelah `/kanji_reload`.

### 2.3 Pipeline Rendering: HTML → Markdown & Notasi Furigana

Identik di ketiga command. CSV sumber (ekspor Anki untuk bunpou/kotoba)
memakai markup yang tidak di-render Discord apa adanya — transformasi
terjadi murni di layer tampilan, **CSV tidak pernah diubah**, supaya
tetap bisa disinkronkan ulang dari sumber tanpa kehilangan edit manual.

**1. HTML → Markdown Discord:**

| Tag sumber | Fungsi | Jadi di Discord |
|---|---|---|
| `<b>...</b>` | Bold kata/pola target | `**...**` |
| `<s>...</s>` | Coret (notasi textbook, mis. buang akhiran) | `~~...~~` |
| `<br>` | Baris baru | newline literal |

**2. Notasi furigana `kanji[bacaan]` → teks bersih + legenda spoiler.**
Bracket dibuang dari kalimat/catatan utama, tiap pasangan kata+bacaan
dikumpulkan jadi satu baris legenda disembunyikan di balik spoiler
Discord `||...||`. Berlaku di **field Jepang manapun** yang memuat
notasi ini, bukan cuma kalimat contoh (dikonfirmasi dari data mentah:
di `/bunpou`, notasi ini juga muncul luas di `GrammarNoteJP1-7`,
`GrammarMeaningJP`, `GrammarFormation1-3` — bukan eksklusif
`SentFurigana`). Karakter yang dianggap "kanji" untuk parsing: ideograf
CJK, tanda pengulangan `々`, digit ASCII/fullwidth.

### 2.4 Gating Akses

Sama persis di ketiga command, jangan bikin logic akses baru:
- `shared.checks.has_dic_access()` — Trial/Companion/Patron dapat akses
  detail, **Traveler tidak**, staff/admin selalu dapat.
- Mode list tetap terbuka untuk **semua role termasuk Drifter** (nama +
  level gratis), cuma kolom arti yang dikunci — parameter `show_meaning`
  di `build_list_pages()`, dikontrol dari `has_dic_access()` di command
  utama.
- Mode detail penuh di-gate lewat `shared.checks.MSG_DIC_DETAIL_ONLY()`
  (fungsi, bukan konstanta lagi — lihat `PRICING_SYSTEM_REFACTOR.md`
  Tahap 5, harganya sekarang dinamis ikut preset).
- **Celah component-interaction (kritis):** dropdown "pilih untuk
  detail" di mode list adalah interaksi komponen Discord, BUKAN
  pemanggilan slash command baru. Access check WAJIB dicek ulang di
  situ (`BunpouListView._on_select`, `KotobaListView._on_select`,
  `KanjiListView._on_select`), bukan cuma di command awal — kalau
  tidak, satu panggilan command bisa dipakai loncat ke mode detail
  tanpa access check terpisah. **Status: sudah ditutup di ketiga
  command** (diverifikasi langsung ke kode, lihat bagian 6).

### 2.5 Delimiter makna ganda

`;` = pemisah antar-makna/fungsi berbeda. `,` = pemisah antar-sinonim
dalam makna yang sama. Berlaku di `GrammarMeaningID` (bunpou) dan
`VocabDefID` (kotoba). Kalau makna ganda, urutan slot catatan/kalimat
terkait idealnya selaras dengan urutan makna.

---

## 3. `/bunpou` — Kamus Grammar

- **91 kolom**, slot: `GrammarFormation1-3`, `GrammarNoteJP/ID1-7`,
  `GrammarImage1-5`, `SentType/Kanji/Furigana/DefID/Audio1-11`. Jumlah
  slot dikonfirmasi dari 632 baris data mentah asli (bukan tebakan) —
  `ところだ` pakai sampai 11 kalimat, `ばいい` sampai 6 catatan, `あげる`/
  `くれる`/`もらう` pakai semua 5 slot gambar.
- **`GrammarFormationGakko1-10` dihapus dari skema** — dicek 0/632
  baris terisi di kolom sumber, bukan sekadar "jarang dipakai".
- **`GrammarBracket`** — label pembeda untuk pola yang berbagi
  bentuk/bacaan sama tapi fungsi beda (mis. て muncul sebagai entri
  terpisah dengan `GrammarBracket` `〈方法・状態〉` vs `〈理由・原因〉`).
  Terisi di 185/632 baris.
- **`GrammarStar`** — rating kepentingan dari sumber (`★1`-`★5`), BEDA
  dari `frequency` (kategori pemakaian umum) — jangan dicampur.
- **Pagination selalu 2 halaman** kalau ada kalimat contoh (halaman 1:
  接続+意味+備考, halaman 2: 例文 lengkap) — konsisten, bukan kondisional,
  supaya perilaku predictable.
- Menggantikan sepenuhnya `/grammar` versi 15-bagian lama (`①`-`⑮`) dan
  4 CSV relasionalnya — sudah tidak dipakai, ada migration guard di
  `cog_load()` yang `DROP TABLE IF EXISTS` tabel-tabel lama itu.

---

## 4. `/kotoba` — Kamus Kosakata

- **34 kolom**, cuma 1 field makna (`VocabDefID`, tidak ada versi JP),
  1 field catatan bebas (`VocabPlus`), dan 4 slot kalimat contoh
  (`SentType/Kanji/Furigana/DefID/Audio1-4`) — jumlah slot sesuai
  sumber (`deck-source/notes.csv` cuma py 4 slot, bukan 11 seperti
  bunpou).
- **1 halaman saja**, tidak ada pagination — semua detail muat di 1
  embed (field yang kepanjangan otomatis dipecah beberapa field embed
  lewat `_add_long_field()`, bukan halaman terpisah).
- `VocabAudio`/`SentAudio1-4` dipertahankan di skema CSV tapi **belum
  dirender** — tunggu file audio di-hosting di tempat yang bisa dirujuk
  Discord (CDN/URL publik).

---

## 5. `/kanji` — Kamus Kanji

Beda sifat dari dua command lain: **tidak butuh authoring manual**,
data sudah jadi (`kanji_master.csv`, 13.141 baris, gabungan 4 sumber
terbuka: mimneko/kanji-data, KanjiVG, KANJIDIC2, kanjiapi.dev + Anki
Kanken). Effort sepenuhnya di desain rendering & pemetaan kategori,
bukan pengisian data.

### 5.1 Kolom JSON-in-cell

13 kolom `kanji_master.csv` isinya teks JSON di dalam satu sel CSV
(list: `on_yomi`, `kun_yomi`, `nanori`, `meanings_en`, `jukugo_contoh`,
`antonim`, `sinonim`, `mirip_bentuk`, `varian`, `elemen_kanjivg`,
`radikal_kanjivg`, `radikal_posisi_kiri_kanan`, `radikal_posisi_atas_bawah`;
object: `radikal_info_kanken`, `struktur_dekomposisi_kanjivg`, `sumber`).
Disimpan **apa adanya sebagai TEXT** di SQLite, `json.loads()` dipanggil
saat render (bukan dinormalisasi ke tabel anak — over-engineering untuk
kebutuhan "tampil di 1 embed").

### 5.2 Overlay terjemahan Indonesia (`kanji_meanings_id.csv`)

`kanji_master.csv` **tidak punya kolom Bahasa Indonesia sama sekali**
(dicek langsung ke header, bukan asumsi). Solusinya file overlay
terpisah (2 kolom: `kanji`, `arti_id`), **sengaja file terpisah bukan
kolom baru di master** — supaya tidak fork data hasil gabungan 4 sumber.
LEFT JOIN saat render; kanji yang belum punya terjemahan fallback ke
`meanings_en`/`meaning_jp` **tanpa** placeholder "belum diterjemahkan"
(karena bakal muncul di hampir semua kanji di awal, mengganggu). Begitu
`arti_id` terisi, ditampilkan sebagai section utama, EN/JP tetap
sebagai pelengkap di bawahnya (bukan digantikan).

### 5.3 Pagination dinamis (1-4 halaman)

| Halaman | Isi | Selalu ada? |
|---|---|---|
| 1 | Info Dasar + Bacaan + Arti + Radikal ringkas | Selalu |
| 2 | Jukugo Contoh (per kategori 小/中/高/外) | Hanya kalau `jukugo_contoh` terisi (46.2%) |
| 3 | Cascading tree dekomposisi | Hanya kalau root punya ≥1 children (6.279/13.141 kanji) |
| 4 | Kanji Terkait + Link Referensi | Hanya kalau minimal 1 dari 4 kolom terisi |

### 5.4 Cascading tree dekomposisi (`struktur_dekomposisi_kanjivg`)

Direvisi 2× dari rencana awal ("jangan render sebagai pohon") setelah
verifikasi data: 99.7% elemen di seluruh tree (6.431/6.448 unik) punya
baris sendiri di `kanji_master` (bacaan & arti bisa di-lookup balik).
Format final: **2 kolom**, dipisah spasi ke lebar tetap (**bukan tab**
— tab tidak dijamin rata lintas prefix pohon beda panjang). Kolom 1 =
pohon (`├─`/`└─`/`│`) + karakter. Kolom 2 = 2 baris per node (bacaan:
1 on'yomi + 1 kun'yomi; arti: 1 arti Inggris, dipotong maks 45 karakter).
Lebar kolom dihitung dinamis pakai `unicodedata.east_asian_width()`
(karakter fullwidth dihitung 2 kolom tampil — `len()` biasa bikin kolom
2 tidak rata). Rule bar `│` di baris kontinuasi: ditambahkan kalau node
punya children, **titik**, terlepas dari status `is_last` (sempat salah
asumsi di iterasi awal, dikonfirmasi ulang lewat kasus nyata kanji 橋).
Dirender lewat `embed.description` (bukan field, batas 4096 vs 1024
karakter) dibungkus code block. Halaman ini **hanya muncul** kalau
root punya minimal 1 children — 118 kanji yang cuma leaf diri sendiri
tidak dapat halaman ini.

### 5.5 Yang sengaja ditunda (v2, di luar scope command ini)

- `joyo_kanji_onkun.csv` (bacaan resmi Jōyō detail) — v2, sebagai
  tombol/command terpisah.
- `joyo_kanji_fuhyo.csv` (ateji/jukujikun) — levelnya per-kata, lebih
  cocok jadi bagian `/kotoba`.
- JOIN penuh ke `kosakata.csv` (daftar kosakata pakai kanji tsb) — cukup
  angka pre-hitung `jumlah_kosakata_terkait` untuk sekarang.
- JOIN ke `radikal_master.csv` — sengaja dihindari (radikal Kanken
  sudah ter-embed penuh di `radikal_info_kanken`); direkomendasikan jadi
  command `/radikal` terpisah di v2 kalau dibutuhkan.

---

## 6. Status Implementasi — Diverifikasi Ulang Terhadap Kode

**Konteks kenapa bagian ini ditulis ulang:** dokumen lama
(`panduan-kamus-kanji-versi-ringkas.md` bagian 12) mencatat mayoritas
item checklist sebagai `[ ]` belum dikerjakan. Dicek satu-satu terhadap
`kanji_cog.py`/`kanji_fields.py` aktual — **semuanya ternyata sudah
selesai**, sama seperti temuan di `MEMBERSHIP_SYSTEM.md` bagian 8.

| Item | Klaim dokumen lama | Status verifikasi terhadap kode |
|---|---|---|
| `kanji_fields.py` dengan `FIELD_NAMES`/`KEY_FIELD`/`CATEGORY_FIELDS` | ☐ Belum | ✅ Ada, lengkap |
| Loader `json.loads()` aman terhadap sel kosong | ☐ Belum | ✅ `_parse_list()`/`_parse_object()` dengan fallback `[]`/`None` |
| `kanji_meanings_id.csv` + loader + fallback rendering | ☐ Belum | ✅ Ada, `load_meanings_csv()`, fallback tanpa placeholder sesuai spek |
| `grade_kanjiapi` vs `kyouiku_kelas_sd` tidak tercampur | ☐ Belum | ✅ Filter `kelas_sd` pakai `kyouiku_kelas_sd` secara eksplisit |
| Pagination dinamis 1-4 halaman | ☐ Belum | ✅ `build_detail_pages()` cek isi tiap kategori sebelum bikin halaman |
| Gating akses dicek ulang di dropdown | ☐ Belum | ✅ `KanjiListView._on_select` cek `has_dic_access()` ulang |
| Field teknis tidak bocor ke tampilan | ☐ Belum | ✅ `HIDDEN_FIELDS` di `kanji_fields.py`, `DISPLAYED_CATEGORIES` mengecualikannya |
| Radikal Kanken dari `radikal_info_kanken`, bukan JOIN baru | ☐ Belum | ✅ `_render_radikal()` pakai `radikal_info_kanken` langsung |
| Penamaan file sesuai `DEVELOPMENT_GUIDE.md` §2 | ☐ Belum | ✅ `kanji_cog.py`/`kanji_fields.py` di root `features/dictionary/`, bukan `support/` |
| Update referensi `/kanji` di `DEVELOPMENT_GUIDE.md` | ☐ Belum | ✅ Sudah benar di `DEVELOPMENT_GUIDE.md` bagian 12 (tabel dependency lintas-folder) — ditulis berdasarkan kode aktual, bukan rencana lama |
| Cascading tree dekomposisi | ✅ Sudah (ditandai di dokumen lama) | ✅ Terkonfirmasi, `_render_dekomposisi_tree()` |
| Header format `日本語 (Indonesia)` tanpa emoji dekoratif | ✅ Sudah (ditandai di dokumen lama) | ✅ Terkonfirmasi |

**Genuinely belum diverifikasi** (bukan soal kode ada/tidak, tapi
pengujian manual): autocomplete dites dengan kanji langka vs kanji
populer di kedua ekstrem data. Ini item testing, bukan implementasi —
tidak bisa dikonfirmasi cuma dari baca kode.

**`/bunpou` dan `/kotoba`:** kedua command ini juga sudah lengkap
diimplementasi (bukan cuma `/kanji`) — termasuk migration guard yang
membuang tabel `/grammar` versi lama, dan gating akses di level dropdown
untuk ketiga command sudah konsisten (lihat bagian 2.4). Tidak ada
temuan status "diklaim belum padahal sudah" untuk dua command ini,
karena dokumen sumbernya (panduan grammar & kotoba) tidak menyertakan
checklist implementasi seperti panduan kanji.

---

## Riwayat Perubahan Signifikan

- **2026-07-21** — Dibuat dari penggabungan 3 panduan kamus lama.
  Checklist implementasi `/kanji` (12 item) diverifikasi ulang terhadap
  `kanji_cog.py`/`kanji_fields.py` aktual — 10 dari 12 item yang
  diklaim "belum dikerjakan" ternyata sudah selesai (2 sisanya memang
  item testing manual, bukan implementasi kode).
