# IMMERSION_SYSTEM.md — Sistem Immersion Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** mekanisme `/log` & `/log_undo`, sistem
> achievement, ekspor riwayat, leaderboard, sistem target belajar
> (goals), statistik visual, bar chart race, dan cache autocomplete API
> eksternal (AniList/VNDB/TMDB) — semua yang ada di `features/immersion/`
> **BUKAN sumber untuk:** daftar command dengan parameter lengkap (lihat
> `COMMANDS.md` — dokumen ini menjelaskan PERILAKU, `COMMANDS.md`
> menjelaskan SIGNATURE), skema tabel SQL lengkap lintas-fitur (lihat
> `DATABASE_SCHEMA.md`), permission channel (lihat `PERMISSION_MATRIX.md`)
> **Terakhir diverifikasi terhadap kode:** 2026-09-19 — dibaca penuh:
> `log_cog.py` (603 baris), `goals_cog.py`, `stats_cog.py`,
> `bar_races_cog.py`, `support/helpers.py`, `support/media_types.py`,
> `support/autocomplete/{anilist,vndb,tmdb}.py`, dan
> `immersion_log_settings.yml`. Setiap klaim dicek ke baris kode
> aslinya, bukan disimpulkan dari nama command/file.

**Dokumen ini baru** — sebelumnya fitur immersion (12 command, salah
satu command surface terbesar di bot) sama sekali tidak punya dokumen
topik, cuma tersebar di komentar kode.

---

## 1. Peta Folder & Alur Data

```
features/immersion/
├── log_cog.py              ← /log, /log_undo, /log_achievements,
│                              /log_export, /logs, /log_leaderboard
├── goals_cog.py             ← /log_set_goal, /log_remove_goal,
│                              /log_view_goals, /log_clear_goals,
│                              check_goal_status() (dipanggil log_cog)
├── stats_cog.py              ← /log_stats
├── bar_races_cog.py          ← /log_race
├── immersion_log_settings.yml ← SATU-SATUNYA sumber points_multipliers,
│                                 achievement threshold, allowed_log_channels
└── support/
    ├── helpers.py            ← is_valid_channel(), achievement lookup
    ├── media_types.py         ← MEDIA_TYPES (single source of truth
    │                             7 jenis media), LOG_CHOICES
    └── autocomplete/
        ├── anilist.py         ← cache + autocomplete Anime/Manga
        ├── vndb.py            ← cache + autocomplete Visual Novel
        └── tmdb.py             ← cache + autocomplete Listening Time
```

**Prinsip arsitektur kunci:** tidak ada running balance/counter tersimpan
di mana pun. Poin, streak, total achievement, dan leaderboard **semua
dihitung ulang live** dari `SUM()`/`COUNT()` atas tabel `logs` setiap
kali dibutuhkan — tidak ada kolom "total_points" di tabel `users` atau
sejenisnya. Konsekuensinya: menghapus 1 baris log lewat `/log_undo`
otomatis "membetulkan" semua angka turunan (poin bulan ini, achievement,
leaderboard) tanpa butuh langkah tambahan apa pun — tapi juga berarti
setiap command yang menampilkan angka ini melakukan query agregat
setiap kali dipanggil (tidak ada cache).

`media_types.py` adalah **single source of truth** untuk 7 jenis media
yang bisa di-log — file lain (`goals_cog.py`, `stats_cog.py`,
`bar_races_cog.py`) selalu import `MEDIA_TYPES`/`LOG_CHOICES` dari sini,
tidak pernah mendefinisikan ulang.

---

## 2. `/log` — Mekanisme Pencatatan

### 2.1 Jenis Media (`MEDIA_TYPES`, `media_types.py:38-123`)

Poin dihitung: `points_received = round(amount * points_multiplier, 2)`
(`log_cog.py:229`) — linear murni, **tidak ada cap/diminishing
returns/bonus**. Angka `points_multiplier` dibaca dari
`immersion_log_settings.yml` (`points_multipliers`), fallback ke `0`
kalau key hilang di YAML (supaya bot tetap start, bukan `KeyError` saat
import — `media_types.py:27-28`).

| Media | Unit | Poin/unit | Maks per log | Butuh lookup nama? | Achievement Group |
|---|---|---|---|---|---|
| Visual Novel | karakter | 0.0028571428571429 (≈1/350) | 2.000.000 | Ya (VNDB) | Visual Novel |
| Manga | halaman | 0.25 | 1.000 | Ya (AniList) | Manga |
| Anime | episode | 13.0 | 100 | Ya (AniList) | Anime |
| Book | halaman | 1.0 | 500 | Tidak (teks bebas) | **Reading** |
| Reading Time | menit | 0.67 | 1.440 | Tidak (teks bebas) | **Reading** |
| Listening Time | menit | 0.67 | 1.440 | Ya (TMDB) | Listening |
| Reading | karakter | 0.0028571428571429 (sama dengan VN) | 2.000.000 | Tidak (teks bebas) | **Reading** |

**Penting:** `Book`, `Reading Time`, dan `Reading` adalah 3 media type
berbeda tapi **berbagi satu achievement pool yang sama** ("Reading") —
progress achievement dihitung dari total poin gabungan ketiganya, bukan
per media type. `Visual Novel` dan `Reading` kebetulan punya
`points_multiplier` identik (karakter → poin), tapi achievement group-nya
tetap terpisah.

### 2.2 Validasi Input

- `amount` (tipe `str`, bukan `int`, karena bisa berarti durasi dalam
  menit) — ditolak kalau bukan `isdigit()` murni (`log_cog.py:191-192`,
  ini juga otomatis menolak angka negatif karena tanda `-` bukan digit).
  Guard `amount < 0` di baris 194-195 secara praktis **tidak pernah
  ter-trigger** karena sudah tertangkap `isdigit()` di atasnya — defensif,
  bukan mati fungsi.
- `amount > max_logged` (tabel di atas) → ditolak dengan pesan per-media.
- `name` maks 150 karakter, `comment` maks 200 karakter (`log_cog.py:200-206`).
- `backfill_date` — 2 format diterima: `YYYY-MM-DD HH:MM` atau
  `YYYY-MM-DD` (`log_cog.py:214-217`). Kosong = waktu sekarang (UTC).
  **Window mundur: maksimal 7 hari ke belakang, inklusif** (`(today -
  log_date_parsed.date()).days > 7` ditolak — persis 7 hari lalu masih
  boleh, `log_cog.py:221-222`). Tanggal masa depan ditolak.
- **Tidak ada dedup/rate-limit** pada `/log` itu sendiri — kombinasi
  media/jumlah/komentar yang sama bisa disubmit berkali-kali tanpa batas,
  masing-masing jadi baris baru.

### 2.3 Efek Samping Otomatis Setelah Insert

Setelah `INSERT INTO logs` (`log_cog.py:235-239`), urutan yang terjadi:

1. `check_goal_status(bot, user_id, media_type)` dipanggil (`log_cog.py:243`,
   lihat bagian 7) — hasilnya ditambahkan sebagai field embed
   ("Target 1", "Target 2", dst), dibatasi maks 24 field (satu di bawah
   limit keras Discord 25 field/embed) dengan notice kalau lebih.
2. `get_achievement_reached_info()` dicek (`log_cog.py:246`) — kalau
   baru saja melewati satu threshold achievement, bot **reply** pesan
   terpisah (bukan cuma field embed) mengumumkan achievement baru.
3. Kalau `name`/`comment` mengandung URL (`http://`/`https://`), bot
   membalas link itu secara terpisah supaya Discord unfurl-nya muncul
   (embed utama "menelan" link biasa).
4. Streak hari berturut-turut dan total poin bulan ini dihitung live
   untuk ditampilkan — murni display, tidak mengubah apa pun.

**Tidak ada** pemberian role atau notifikasi ke cog lain dari `/log`.

### 2.4 Tabel `logs`

8 kolom ditulis eksplisit: `user_id, media_type, media_name, comment,
amount_logged, points_received, log_date, achievement_group`. `log_id`
(autoincrement) dan `created_at` (default `CURRENT_TIMESTAMP`) dibiarkan
default — **`created_at` selalu waktu insert sesungguhnya, walau log-nya
di-backfill** (beda dari `log_date` yang mencerminkan tanggal pilihan
user).

---

## 3. `/log_undo`

- Pemilihan lewat **autocomplete** (bukan list tetap) — menampilkan
  semua log milik user (tidak dibatasi tanggal di query, tapi hasil
  autocomplete dipotong 10 pertama yang cocok substring).
- Kepemilikan dicek ulang di server (bukan cuma percaya autocomplete)
  sebelum delete.
- **Yang dihapus murni 1 baris `logs`.** Tidak ada "pengurangan poin"
  terpisah — karena poin/streak/leaderboard/achievement semua live
  aggregate atas `logs` (lihat bagian 1), menghapus baris otomatis
  membetulkan semuanya di query berikutnya.
- **Asimetri penting:** `/log` punya batas backfill 7 hari, tapi
  `/log_undo` **tidak punya batas usia sama sekali** — log dari kapan
  pun (termasuk yang di-backfill sampai batas 7 hari, atau yang sudah
  berbulan-bulan) bisa dihapus selama masih milik user yang sama.

---

## 4. Achievement System (`/log_achievements`)

- **Tidak ada tabel status achievement.** Dihitung ulang tiap command
  dijalankan: `SUM(points_received)` per `achievement_group` dari tabel
  `logs`, lalu dicocokkan ke daftar threshold di
  `immersion_log_settings.yml` (`achievements:`).
- **5 achievement group**, masing-masing 9 tingkat (verifikasi langsung
  ke YAML, bukan asumsi jumlah tingkatnya sama di semua grup):

| Group | Tingkat 1 (poin) | Tingkat tertinggi (poin) |
|---|---|---|
| Visual Novel | 1 | 600.000 |
| Manga | 1 | 450.000 |
| Anime | 1 | 400.000 |
| Listening | 1 | 400.000 |
| Reading (Book+Reading Time+Reading) | 1 | 600.000 |

Detail nama/deskripsi tiap tingkat ada penuh di
`immersion_log_settings.yml` — tidak diduplikasi di sini supaya tidak
ada 2 sumber kebenaran untuk copy achievement (bisa berubah kapan saja
tanpa perlu update dokumen ini).

- **Kolom `achievement_group` di tabel `logs`** adalah snapshot
  denormalisasi dari `MEDIA_TYPES[media_type]['Achievement_Group']`
  pada saat log dibuat. Implikasi: kalau suatu saat mapping grup di
  config diubah, baris log LAMA tetap memakai grup lama (tidak
  ter-reklasifikasi otomatis).
- Achievement list di YAML **diasumsikan terurut ascending berdasarkan
  poin** — kode `break` di entri pertama yang melewati poin saat ini,
  tidak ada validasi/sorting eksplisit terhadap urutan YAML itu sendiri.

---

## 5. Ekspor Riwayat (`/log_export`, `/logs`)

Keduanya menjalankan **query yang sama persis**
(`SELECT log_id, media_type, media_name, comment, amount_logged,
points_received, log_date FROM logs WHERE user_id = ? ORDER BY log_date DESC`),
beda cuma format output:

| | `/log_export` | `/logs` |
|---|---|---|
| Format file | `.csv` (semua 7 kolom + header Indonesia) | `.txt` (1 baris ringkas per log, TANPA `log_id`/`points_received`, pakai `unit_name` bukan angka mentah) |
| Lokasi temp | `/tmp/immersion_logs_{user_id}.csv` | `/tmp/immersion_logs_{user_id}.txt` |
| Dihapus setelah kirim | Ya | Ya |

> ⚠️ **Lihat bagian 14 (Known Issues)** — parameter `user` di kedua
> command ini diberi label "Khusus Staf" tapi TIDAK ada pengecekan staff
> di kode.

---

## 6. Leaderboard (`/log_leaderboard`)

- Query: `SUM(points_received)` per `user_id`, di-`GROUP BY user_id`,
  `ORDER BY total_points DESC`, **`LIMIT 20` (hard cap, tidak pernah
  menampilkan lebih dari 20 user)**.
- Filter `media_type` opsional (exact match).
- **`month` default = bulan kalender berjalan (UTC)**, dicocokkan lewat
  `strftime('%Y-%m', log_date) = ?` — **bukan rolling 30 hari**. Pilihan
  `month='ALL'` melepas filter tanggal sama sekali (agregat sepanjang
  masa).
- Rank/poin milik user pemanggil selalu ditampilkan terpisah (fallback),
  bahkan kalau dia di luar top 20.

---

## 7. Sistem Target Belajar (Goals)

### 7.1 Tabel `user_goals`

```sql
CREATE TABLE IF NOT EXISTS user_goals (
    goal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    goal_type TEXT NOT NULL CHECK(goal_type IN ('points', 'amount')),
    goal_value INTEGER NOT NULL,
    end_date TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Tidak ada kolom status/completed** — status goal selalu dihitung live
(lihat 7.2). `start_date` (kalau diisi user) disimpan **di kolom
`created_at`**, bukan kolom terpisah — kalau tidak diisi, `created_at`
memakai default `CURRENT_TIMESTAMP` (waktu insert sesungguhnya).

### 7.2 `check_goal_status()` — Jantung Sistem Goal

Dipanggil dari **2 tempat**: (1) `log_cog.py:243` setiap kali `/log`
sukses untuk media type yang baru dilog, (2) `goals_cog.py:249` di
`/log_view_goals`, sekali per jenis media.

Progress dihitung **live per goal** lewat correlated subquery:
`SUM(points_received)` atau `SUM(amount_logged)` (tergantung
`goal_type`) dari `logs` **WHERE `log_date` BETWEEN `user_goals.created_at`
AND `user_goals.end_date`**. Tiga kemungkinan hasil:

- **Sedang berjalan** — dalam window waktu, progress < target → progress
  bar + estimasi selesai.
- **Selesai** — `progress >= goal_value` (terlepas dari apakah window
  waktu sudah lewat atau belum) → pesan selamat, tanpa progress bar.
- **Gagal** — bukan keduanya di atas (window lewat, progress belum
  cukup) → pesan gagal + progress bar.

**Tidak ada DM dikirim** untuk goal tercapai — notifikasi murni lewat
field embed di respons command yang memicunya (`/log` atau
`/log_view_goals`), tidak ada `Member.send()` di file mana pun.

### 7.3 Perilaku Penghapusan Goal — Celah yang Perlu Diketahui

`/log_clear_goals` menghapus goal berdasarkan **`end_date < sekarang`
saja** (`goals_cog.py`, `GET_EXPIRED_GOALS_QUERY`/`DELETE_ALL_EXPIRED_GOALS_QUERY`)
— **status completion TIDAK jadi kriteria**. Akibatnya:

- Goal yang **sudah tercapai tapi belum lewat `end_date`** tidak bisa
  dibersihkan lewat `/log_clear_goals` (harus manual lewat
  `/log_remove_goal`).
- Goal yang **tercapai DAN sudah lewat `end_date`** ikut terhapus lewat
  `/log_clear_goals` — sama seperti goal yang gagal, tidak ada
  pembedaan status "sukses" vs "gagal" saat dibersihkan (riwayat
  keberhasilan tidak disimpan setelah dihapus).

### 7.4 Validasi Lain yang Perlu Dicatat

- `goal_value` hanya divalidasi `> 0` — **tidak ada batas atas**.
- `end_date_or_hours`: dua format (angka murni = jam relatif dari
  sekarang, atau `YYYY-MM-DD`). **Jalur "jam relatif" tidak punya
  validasi tanggal masa lalu** (beda dengan jalur tanggal absolut yang
  eksplisit menolak tanggal lampau) — secara teori `0` jam pun diterima.
- `start_date > end_date` ditolak eksplisit.

---

## 8. Statistik (`/log_stats`)

- **Tidak ada gate akses sama sekali** — bukan cuma tanpa `@is_vip()`,
  tapi juga tidak ada pengecekan staff untuk parameter `user` di dalam
  kode, walau deskripsinya di Discord bertuliskan "(Opsional/Khusus
  Staf)". Lihat bagian 14.
- Menghasilkan **2 gambar terpisah**: bar chart bertumpuk (poin atau
  jumlah per hari/minggu/bulan/kuartal, resampling otomatis tergantung
  panjang rentang: >730 hari → kuartalan, >210 → bulanan, >31 →
  mingguan, selebihnya harian) dan calendar heatmap (**selalu berbasis
  poin**, tidak ikut mode "amount" seperti bar chart).
- Query database selalu mengambil dari awal tahun (`from_date`/tahun
  berjalan) sampai `to_date`, supaya heatmap yang butuh konteks 1 tahun
  penuh tetap bisa dirender — bar chart baru dipotong ke rentang
  tampilan sesudahnya.
- Tidak ada cache gambar — digambar ulang dari nol setiap panggilan
  lewat `matplotlib`/`seaborn` (`Agg` backend, headless).
- **Font CJK/emoji TIDAK di-setup di file ini** — meski
  `DEPLOYMENT.md` menyebut font handling untuk grafik immersion,
  `set_fonts()` sesungguhnya cuma ada di `bar_races_cog.py` (bagian 9)
  dan kebetulan berlaku juga di sini karena `matplotlib.rcParams`
  bersifat global per-proses (kalau cog race sudah pernah di-load).

---

## 9. Bar Chart Race (`/log_race`)

- `race_type`: `points` (default) atau `amount`.
- **Tidak ada channel restriction** (`is_valid_channel` tidak dipanggil
  di sini, beda dari `/log_set_goal`/`/log_stats`) dan **tidak ada role
  gate** — hanya `guild_only()` + cooldown dinamis.
- **Cooldown: 1× per 300 detik (5 menit)**, admin (permission
  `administrator` di channel saat itu) **exempt total** (bukan cooldown
  lebih pendek — benar-benar tidak kena cooldown sama sekali).
- Rentang tanggal **dibatasi keras maksimal 210 hari** — di atas itu
  langsung ditolak (pesan hardcoded, bukan lewat `Msg.*` seperti
  kebiasaan file lain di fitur ini — inkonsistensi kecil pola kode).
- Resampling frekuensi menyesuaikan panjang rentang (2D–6D tergantung
  jumlah hari) supaya jumlah frame video terkendali.
- Render lewat library `bar_chart_race` — **ffmpeg dipanggil secara
  internal oleh library ini** (lewat `FFMpegWriter` matplotlib), tidak
  ada pemanggilan `subprocess`/ffmpeg manual di kode bot. Output `.mp4`
  ditulis ke file temp, dibaca ulang jadi `BytesIO`, filenya **selalu
  dihapus di blok `finally`** (sukses maupun gagal).
- `set_fonts()` (`bar_races_cog.py:41-65`) dipanggil sekali di
  `__init__` cog (bukan `cog_load`, jadi berjalan sinkron saat objek
  cog dibuat) — mencari font CJK dari daftar prioritas (`Noto Sans CJK
  JP` → ... → `Hiragino Sans`) dan font emoji (`Noto Emoji` saja),
  fallback `sans-serif`. Perubahan `plt.rcParams['font.family']` ini
  **global untuk seluruh proses bot**, bukan cuma cog ini.

---

## 10. Autocomplete & Cache API Eksternal

Ketiga modul (`anilist.py`, `vndb.py`, `tmdb.py`) berpola identik: tabel
cache `cached_<source>_results` + tabel virtual FTS5 `<source>_fts`
(`content=` external-content, `tokenize='porter'`) + trigger
INSERT/UPDATE/DELETE penyinkron. **Semua `CREATE TABLE`/`CREATE VIRTUAL
TABLE`/`CREATE TRIGGER` untuk ketiganya dieksekusi dari `log_cog.py
cog_load()`**, bukan dari file autocomplete itu sendiri.

| | AniList | VNDB | TMDB |
|---|---|---|---|
| Dipakai untuk | Anime, Manga | Visual Novel | Listening Time |
| API | GraphQL, `graphql.anilist.co` | Kana API, `api.vndb.org` | REST `search/multi` |
| Field unik | filter by `MediaType` | `cover_image_nsfw` flag (thumbnail cuma dipakai kalau `= 0`) | `media_type` dari TMDB sendiri (movie/tv/person — beda dari `MEDIA_TYPES` bot) |
| TTL cache | **Tidak ada — permanen** | **Tidak ada — permanen** | **Tidak ada — permanen** |
| Alur pencarian teks | FTS dulu, API kalau hasil < 1 | sama | sama |
| Lookup by ID | Ya (nomor AniList) | Ya (prefix `v` opsional) | **Tidak ada jalur ID** |
| HTTP 429 | Baca `Retry-After` (default 60s), `print()`, return `[]` — **tidak ada retry/backoff nyata** | sama | sama |
| Timeout eksplisit | Tidak ada | Tidak ada | Tidak ada |
| Fail-safe kalau API key kosong | n/a (tidak butuh key) | n/a | **Tidak fail-safe** — `raise ValueError` langsung (konsisten dengan `DEPLOYMENT.md` §4) |

Semua hasil API (baik dari lookup ID maupun search) otomatis ditulis ke
cache lewat `UPSERT` — sekali suatu judul pernah dicari, cache-nya tidak
pernah kedaluwarsa/di-refresh otomatis.

---

## 11. Tabel Database (Ringkasan)

Detail skema lengkap: `DATABASE_SCHEMA.md` §4. Ringkasan peran:

| Tabel | Dibuat di | Peran |
|---|---|---|
| `logs` | `log_cog.py cog_load()` | Satu baris = satu aktivitas immersion; sumber SEMUA angka turunan (poin, achievement, leaderboard, streak) |
| `user_goals` | `goals_cog.py cog_load()` | Target belajar aktif; tidak menyimpan status completion |
| `cached_anilist_results` + `anilist_fts` | `log_cog.py cog_load()` | Cache pencarian Anime/Manga, permanen |
| `cached_vndb_results` + `vndb_fts` | `log_cog.py cog_load()` | Cache pencarian Visual Novel, permanen, termasuk flag NSFW |
| `cached_tmdb_results` + `tmdb_fts` | `log_cog.py cog_load()` | Cache pencarian Listening Time, permanen |

---

## 12. Permission/Access (Ringkasan)

Detail parameter per command: `COMMANDS.md` §3. Ringkasan pola akses:

| Command | Gate |
|---|---|
| `/log`, `/log_undo`, `/log_achievements`, `/log_export`, `/logs`, `/log_leaderboard` | `@is_vip()` |
| `/log_set_goal`, `/log_remove_goal`, `/log_view_goals`, `/log_clear_goals` | `@is_vip()` |
| `/log_stats` | **Tidak ada gate sama sekali** (lihat bagian 14) |
| `/log_race` | Tidak ada role gate, hanya cooldown 300s (admin exempt) |

`is_valid_channel()` (`support/helpers.py`) jadi gate channel tambahan
di sebagian besar command (admin selalu lolos, channel di
`allowed_log_channels` — `immersion-log` dan `staff-chat` per
`immersion_log_settings.yml` — atau DM bot) — **kecuali `/log_race` yang
tidak memanggil `is_valid_channel()` sama sekali.**

---

## 13. Dependency ke Fitur Lain

- `log_cog.py` → `goals_cog.check_goal_status()` (impor langsung fungsi
  lintas-cog, bukan lewat event/listener).
- `goals_cog.py`, `stats_cog.py`, `bar_races_cog.py` → semua import
  `MEDIA_TYPES`/`LOG_CHOICES` dari `support/media_types.py`.
- `media_types.py` → import balik dari ketiga modul autocomplete
  (`support/autocomplete/*.py`) untuk mengisi field `autocomplete`.
- Tidak ditemukan dependency ke `membership`/`gatekeeper`/fitur lain di
  luar `features/immersion/` sendiri (mis. tidak ada pengecekan tier VIP
  spesifik selain lewat `@is_vip()` standar dari `shared/checks.py`).

---

## 14. Known Issues / Gotcha (Ditemukan Saat Audit 2026-09-19)

**1. Tiga command mengklaim "Khusus Staf" di parameter `user`, tapi
TIDAK ADA satu pun yang benar-benar mengecek role staff:**

| Command | Klaim di deskripsi Discord | Gate sesungguhnya di kode |
|---|---|---|
| `/log_export` | "Khusus Staf" | `@is_vip()` saja — **VIP mana pun** (bukan cuma staff) bisa ekspor riwayat log user lain |
| `/logs` | "Khusus Staf" | `@is_vip()` saja — sama seperti di atas |
| `/log_stats` | "(Opsional/Khusus Staf)" | **Tidak ada gate apa pun** — siapa saja (bahkan tanpa VIP) bisa lihat statistik user lain |

Tidak ada satu pun dari ketiganya yang memanggil `has_staff_role()`/
`is_staff()` dari `shared/checks.py`. Ini bukan salah tulis dokumentasi
— UI Discord (`app_commands.describe`) benar-benar menjanjikan
pembatasan yang tidak diimplementasikan.

**Investigasi tambahan pada `/log_stats` (2026-09-19, sebelum
diklasifikasikan)** — untuk memastikan ini bukan desain publik yang
disengaja:

- **Data yang ditampilkan bersifat personal, bukan agregat/anonim.**
  Embed hasil punya field `"Warga"` berisi nama tampilan target user
  (`stats_cog.py:290`), plus rincian aktivitas per media type, total
  poin, bar chart, dan calendar heatmap — semuanya spesifik ke satu
  `user_id` yang dipilih.
- **Output TIDAK ephemeral** — `interaction.followup.send(file=file_bar,
  embed=embed)` dan `interaction.followup.send(file=file_heatmap)`
  (`stats_cog.py:303-304`) tanpa `ephemeral=True`. Siapa pun yang
  menjalankan command ini terhadap warga lain, hasilnya **terpasang
  publik di channel**, terlihat semua orang — bukan cuma terlihat
  pemanggil.
- **Cek riwayat git** (`git log -p --follow -- stats_cog.py`): teks
  "Khusus Staf" sudah ada sejak **commit pertama** yang menambahkan
  `/log_stats` — tidak pernah ada `@is_staff()`/pengecekan staff apa pun
  di riwayat file ini yang kemudian dihapus. Bukan kasus "gate pernah
  ada lalu ke-hapus", tapi "gate tidak pernah diimplementasikan sejak
  awal".

**Kesimpulan klasifikasi:** kombinasi (data personal ditampilkan
by-name + output publik/non-ephemeral + teks "Khusus Staf" sudah ada
sejak commit pertama tanpa implementasi yang pernah menyertainya)
membuat ini **jauh lebih mungkin oversight implementasi (bug
permission) daripada keputusan desain publik yang disengaja** — kalau
memang sengaja publik, tidak ada alasan menulis "Khusus Staf" sejak
awal. `/log_stats` dinilai **sama seriusnya dengan `/log_export`/`/logs`,
bahkan lebih berisiko** karena hasilnya otomatis dipublikasikan ke
channel, bukan sekadar bisa "dibaca" oleh pemanggil.

Perlu diputuskan (belum diputuskan di audit ini): perbaiki kode supaya
sesuai klaim (tambah `@is_staff()`/`in-body` check + pertimbangkan
`ephemeral=True` untuk `/log_stats` kalau target bukan diri sendiri),
atau perbaiki deskripsinya supaya sesuai kode aktual kalau memang mau
dibuat publik — **belum diperbaiki di audit ini, sengaja tidak
disentuh** (lihat instruksi: jangan refactor sekarang). Status:
security/permission bug, backlog terpisah.

**2. Bug format URL di `get_source_url()`** (`log_cog.py:351-362`) —
untuk media type "Listening Time", kalau lookup tipe TMDB (movie/tv)
gagal ditemukan di cache, fungsi tetap mengembalikan string source URL
yang mengandung placeholder mentah `{tmdb_media_type}` (belum
di-`.format()`), bukan URL valid.

**3. Asimetri backfill vs undo** — `/log` dibatasi 7 hari ke belakang,
`/log_undo` tidak dibatasi usia log sama sekali (lihat bagian 3).

**4. Goal completion tidak dibedakan dari goal gagal saat dibersihkan**
— `/log_clear_goals` menghapus berdasarkan tanggal expired saja, bukan
status (lihat bagian 7.3).

**5. Cache autocomplete API eksternal tidak pernah kedaluwarsa** — kalau
judul/data di AniList/VNDB/TMDB berubah (judul di-update, cover diganti),
bot akan terus menampilkan versi cache lama tanpa batas waktu, tidak ada
mekanisme refresh selain entri baru yang belum pernah dicari.

**6. Tidak ada timeout eksplisit** pada request ke AniList/VNDB/TMDB —
API yang lambat/hang berpotensi menggantung autocomplete tanpa batas
waktu dari sisi kode bot sendiri (dibatasi tidak langsung oleh timeout
autocomplete ~3 detik dari Discord).

**7. `discord.ext.tasks` di-import tapi tidak dipakai** di ketiga file
autocomplete (`anilist.py`, `vndb.py`, `tmdb.py`) — dead import, bukan
bug fungsional.

---

## Riwayat Perubahan Signifikan

- **2026-09-19** — §14 diperkuat: `/log_stats` diinvestigasi lebih
  lanjut (bukan cuma disimpulkan dari teks "Khusus Staf") — dikonfirmasi
  menampilkan data personal by-name, hasil non-ephemeral (publik di
  channel), dan lewat `git log -p` dikonfirmasi teks "Khusus Staf" ada
  sejak commit pertama tanpa gate yang pernah diimplementasikan.
  Diklasifikasikan ulang dari "perlu keputusan" jadi security/permission
  bug — status tetap belum diperbaiki (audit ini bukan fase fix).
- **2026-09-19** — Dibuat dari nol. Dibaca penuh 9 file kode +
  `immersion_log_settings.yml`. Ditemukan 3 command (`log_export`,
  `logs`, `log_stats`) dengan label UI "Khusus Staf" yang tidak
  ditegakkan di kode sama sekali (gap keamanan/dokumentasi nyata, belum
  diperbaiki), 1 bug format URL di `get_source_url()`, dan beberapa
  asimetri desain (backfill vs undo, goal completion vs expiry) yang
  sebelumnya tidak tercatat di mana pun.
