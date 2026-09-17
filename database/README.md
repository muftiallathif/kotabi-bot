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
├── kode                     ├── database_nihongo.zip  (~548 MB)
├── skema                    ├── kamus.sqlite3         (hasil build)
├── skrip build              └── SVG urutan goresan     (6.699 berkas)
├── migrasi
├── tes
└── database/VERSI.json      ← penunjuk versi + checksum
```

## Alur deploy

```
git pull
   ↓
unduh artefak database (versi sesuai database/VERSI.json)
   ↓
python3 scripts/build_kamus.py <zip> data/kamus.sqlite3
   ↓
jalankan bot
```

## Dua SQLite, bukan satu

| Berkas | Isi | Sifat | Lock |
|---|---|---|---|
| `data/state.sqlite3` | XP, membership, purchase, tracking, progress | baca+tulis | perlu `_db_lock` |
| `data/kamus.sqlite3` | kanji, kotoba, bunpou, frekuensi | **read-only** setelah build | tidak ikut antre di lock state |

Kamus tidak perlu ikut antre di lock milik application state. Tapi itu **bukan**
berarti "read-only = bebas pertimbangan concurrency" — `kamus.sqlite3` tetap dibuka
mode WAL/read-only dan punya pola aksesnya sendiri.

## `VERSI.json`

Dibaca saat startup. Tujuannya satu: kalau suatu hari muncul pertanyaan
*"kenapa `/kotoba 猫` di VPS A beda dengan VPS B?"*, jawabannya bisa **dilacak ke
versi database**, bukan ditebak.
