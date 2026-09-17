# `database/` — data layer, siklus hidupnya TERPISAH dari kode

## Kenapa dipisah

Kode bot dan database pengetahuan berubah karena alasan yang berbeda:

| | Berubah karena |
|---|---|
| **Kode** | fitur, bug fix, UI, command, business logic |
| **Database** | sumber baru, koreksi, resolusi konflik, terjemahan, rebuild |

Kalau keduanya dalam satu siklus Git, tiap rebuild database menambah ratusan MB
**permanen** ke history — dan satu-satunya cara menghapusnya adalah rewrite history.

```
Git                          Artefak eksternal
├── kode                     ├── database_nihongo.zip   (~548 MB, GitHub Releases)
├── skema                    └── data/kamus_nihongo/     (hasil ekstrak, ~2,8 GB:
├── migrasi                       ~89 JSON + 6.699 SVG goresan — dibaca LANGSUNG
├── tes                           oleh resolver.py, tidak di-build jadi SQLite)
└── database/VERSI.json      ← penunjuk versi + checksum
```

## Alur deploy

```
git pull
   ↓
unduh database_nihongo.zip dari GitHub Releases (versi sesuai database/VERSI.json)
   ↓
python3 scripts/verifikasi_artefak.py database_nihongo.zip database/VERSI.json
   ↓
unzip database_nihongo.zip -d data/ && mv data/database_nihongo data/kamus_nihongo
   ↓
export KOTABI_KAMUS_V2=1 KOTABI_DB_NIHONGO=data/kamus_nihongo
   ↓
jalankan bot
```

## SQLite (state) vs JSON (kamus) — bukan "dua SQLite"

| | Isi | Bentuk | Lock |
|---|---|---|---|
| `data/db.sqlite3` (`PATH_TO_DB`) | users, gatekeeper, membership, immersion, **+ tabel dictionary lama** (CSV-based, `features/dictionary/`) | SQLite, baca+tulis | perlu `bot._db_lock`, lewat `core/bot.py` (`RUN`/`GET`/`TRANSAKSI()`) |
| `data/kamus_nihongo/` | kanji, kotoba, bunpou, frekuensi, aksen (`dictionary_v2`) | folder JSON mentah, **read-only** | tidak ada lock — dibaca lazy/streaming per-request oleh `resolver.py`, tidak ikut antre di `_db_lock` |

`dictionary_v2` **tidak** melewati SQLite sama sekali: `resolver.py` baca file JSON
langsung — `DB.j()` untuk file kecil (di-cache di memori), `DB.besar()` untuk file
ratusan MB (di-stream pakai `ijson`, tidak pernah di-`json.load()` penuh). Sempat ada
`scripts/build_kamus.py` untuk membangun `data/kamus.sqlite3` sebagai lapis ketiga,
tapi jalur produksi yang benar-benar dipakai (`kamus_v2_cog.py` → `resolver.py`) tidak
pernah membacanya — skrip itu dihapus supaya dokumen ini tidak menunjuk ke langkah
yang tidak ada efeknya.

## `VERSI.json`

Dibaca saat startup. Tujuannya satu: kalau suatu hari muncul pertanyaan
*"kenapa `/kotoba 猫` di VPS A beda dengan VPS B?"*, jawabannya bisa **dilacak ke
versi database**, bukan ditebak.
