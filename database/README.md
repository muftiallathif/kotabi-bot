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
├── skema                    ├── data/kamus_nihongo/   (hasil ekstrak, ~2,8 GB)
├── skrip verifikasi         └── SVG urutan goresan     (6.699 berkas)
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
python3 scripts/verifikasi_artefak.py <zip> database/VERSI.json
   ↓
unzip <zip> -d data/  &&  mv data/database_nihongo data/kamus_nihongo
   ↓
jalankan bot
```

## Dua database, bukan satu

| Berkas | Isi | Sifat | Lock |
|---|---|---|---|
| `data/state.sqlite3` | XP, membership, purchase, tracking, progress | baca+tulis | perlu `_db_lock` |
| `data/kamus_nihongo/` | kanji, kotoba, bunpou, frekuensi (JSON, dibaca langsung oleh `resolver.py`) | **read-only** | tidak ikut antre di lock state |

Kamus tidak perlu ikut antre di lock milik application state. Tapi itu **bukan**
berarti "read-only = bebas pertimbangan concurrency" — lihat
`features/dictionary_v2/README.md` untuk pola aksesnya.

## `VERSI.json`

Dibaca saat startup. Tujuannya satu: kalau suatu hari muncul pertanyaan
*"kenapa `/kotoba 猫` di VPS A beda dengan VPS B?"*, jawabannya bisa **dilacak ke
versi database**, bukan ditebak.
