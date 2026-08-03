# DATABASE_SCHEMA.md — Skema Database Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** daftar semua tabel SQLite, di mana
> masing-masing dibuat (`cog_load()` mana atau migration mana), dan
> fitur mana yang memakainya
> **BUKAN sumber untuk:** business logic yang mengoperasikan tabel ini
> (lihat dokumen topik masing-masing fitur — `MEMBERSHIP_SYSTEM.md`,
> `GATEKEEPER_QUIZ_SYSTEM.md`, dst)
> **Terakhir diverifikasi terhadap kode:** 2026-07-21

**Dokumen ini baru** — sebelumnya tidak ada satu tempat pun yang
mengumpulkan seluruh tabel. Setiap fitur bikin tabelnya sendiri lewat
`cog_load()` masing-masing (pola `CREATE TABLE IF NOT EXISTS`, aman
dijalankan berkali-kali), kecuali tabel membership yang lewat file
migration terpisah. Disusun dengan menelusuri setiap `cog_load()` dan
file di `migrations/` satu per satu.

Satu prinsip yang berlaku di semua tabel: **`sqlite3` diakses lewat
`core/bot.py`** (`bot.RUN`, `bot.RUN_LASTROWID`, `bot.RUN_MANY`,
`bot.GET`, `bot.GET_ONE`) — tidak ada koneksi SQLite langsung di cog
manapun. Kalau menemukan cog yang bikin koneksi `aiosqlite` sendiri,
itu penyimpangan dari pola yang sudah ada.

---

## 1. Tabel Lintas-Fitur (`core/bot.py`)

| Tabel | Dibuat di | Kolom kunci | Dipakai fitur |
|---|---|---|---|
| `users` | `core/bot.py` `SHARED_TABLES`, dijalankan sekali saat startup (`init_shared_tables()`) | `discord_user_id` (PK), `user_name` | `shared/username_cache.py` — cache nama user lintas-fitur, dipakai leaderboard immersion & kneel |

---

## 2. Gatekeeper (`features/gatekeeper/`)

| Tabel | Dibuat di | Kolom kunci | Catatan |
|---|---|---|---|
| `quiz_attempts` | `gatekeeper_cog.py` `cog_load()` | `id` PK autoincrement, `guild_id`, `user_id`, `quiz_name`, `created_at` | Riwayat percobaan kuis, dasar hitung cooldown |
| `passed_quizzes` | `gatekeeper_cog.py` `cog_load()` | PK gabungan `(guild_id, user_id, quiz_name)` | Kuis yang sudah lulus — dipakai journey system & combination rank |
| `user_threads` | `gatekeeper_cog.py` `cog_load()` | `user_id` PK, `thread_id` | Bilik ujian rank privat milik tiap user (beda dari `practice_threads`) |
| `processed_quiz_reports` | `gatekeeper_cog.py` `cog_load()` | `quiz_id` PK (dari Kotoba API) | Idempotency guard — cegah 1 hasil kuis diproses dua kali |
| `practice_threads` | `practice_cog.py` `cog_load()` (juga ada file migrasi terpisah `migrations/v3_practice_threads.sql`, opsional/redundan karena `cog_load()` sudah bikin otomatis) | `user_id` PK, `thread_id` | Thread latihan bebas PUBLIK di forum `quiz-public` — beda dari `user_threads` |

---

## 3. Membership (`features/membership/`)

**Beda dari fitur lain: tabel-tabel ini TIDAK dibuat lewat
`cog_load()`** — dibuat lewat file di `migrations/`, dijalankan manual
sekali (comment di `admin_cog.py cog_load()`: *"Tabel dibuat via
migration SQL, bukan di sini"*).

| Tabel | Dibuat di (migration) | Kolom kunci | Catatan |
|---|---|---|---|
| `memberships` | (skema dasar sudah ada sebelum `v1`, `v1` nambah kolom `source`) | PK `(guild_id, user_id)` — implisit dari `ON CONFLICT (guild_id, user_id)` di query | `tier`, `granted_at`, `expires_at`, `is_lifetime`, `active`, `point_count`, `granted_by`, `source` |
| `orders` | `v1_membership_system.sql`, di-**recreate total** di `v2_purchase_flow.sql` (rename → tabel baru → copy data → drop lama, karena SQLite tidak bisa `ALTER` `CHECK` constraint) | `order_id` PK autoincrement | Skema v2: tambah `status` (`draft`/`pending`/`needs_resubmit`/`approved`/`rejected`/`cancelled`), `unique_code`, `payment_proof_url`, `sender_bank`, `payment_phash`, `reject_reason_type`, `draft_created_at`, `confirmed_at` |
| `trial_claims` | `v1_membership_system.sql` | PK `(user_id, guild_id, trial_cycle)` | `trial_cycle` sekarang murni label historis — eligibility asli pakai rolling window 180 hari dari `claimed_at` terakhir, bukan dari kolom ini |
| `membership_history_v1` | `v1_membership_system.sql` (migrasi data dari tabel `membership_history` lama, TIDAK auto-drop tabel lama — perlu manual verify dulu) | `id` PK autoincrement | Before/after lengkap: `tier_before/after`, `expiry_before/after`, `point_before/after`, `order_id`, `actor`, `reason` |

**Catatan migrasi tertunda:** komentar di `v1_membership_system.sql`
bilang tabel `membership_history` (lama, tanpa suffix `_v1`) **belum**
di-`DROP` otomatis — perlu diverifikasi manual dulu bahwa migrasi data
berhasil, baru drop manual. Kalau belum pernah dicek, kemungkinan
tabel lama itu masih ada di database sebagai sisa yang tidak terpakai.

---

## 4. Immersion (`features/immersion/`)

| Tabel | Dibuat di | Kolom kunci | Catatan |
|---|---|---|---|
| `logs` | `log_cog.py` `cog_load()` | `log_id` PK autoincrement | Catatan aktivitas belajar — `media_type`, `amount_logged`, `points_received`, `log_date`, `achievement_group` |
| `user_goals` | `goals_cog.py` `cog_load()` | `goal_id` PK autoincrement | `goal_type` CHECK `('points','amount')` |
| `cached_anilist_results` + `anilist_fts` (virtual FTS5) | `log_cog.py` `cog_load()`, definisi di `support/autocomplete/anilist.py` | `anilist_id` UNIQUE | Cache hasil AniList API + trigger sync ke tabel FTS5 (`anilist_fts_insert/update/delete`) untuk pencarian cepat saat autocomplete |
| `cached_vndb_results` + `vndb_fts` | sama pola, `support/autocomplete/vndb.py` | `vndb_id` UNIQUE | Cache VNDB API, termasuk flag `cover_image_nsfw` |
| `cached_tmdb_results` + `tmdb_fts` | sama pola, `support/autocomplete/tmdb.py` | `tmdb_id` UNIQUE | Cache TMDB API, termasuk `media_type` (dipakai bangun URL sumber dinamis) |

---

## 5. Dictionary (`features/dictionary/`)

| Tabel | Dibuat di | Kolom kunci | Catatan |
|---|---|---|---|
| `bunpou_entries` | `bunpou_cog.py` `cog_load()` | `NoteID` PK (dari `FIELD_NAMES`/`KEY_FIELD` di `bunpou_fields.py`) | Full-replace tiap reload. `cog_load()` juga `DROP TABLE IF EXISTS` 4 tabel `/grammar` lama: `grammar_entries`, `grammar_translations`, `grammar_key_sentences`, `grammar_examples` — migration guard, bukan tabel aktif |
| `kotoba_entries` | `kotoba_cog.py` `cog_load()` | `NoteID` PK (dari `kotoba_fields.py`) | Full-replace tiap reload |
| `kanji_entries` | `kanji_cog.py` `cog_load()` | `kanji` PK (dari `kanji_fields.py`) | Full-replace tiap reload, beberapa kolom isinya JSON-in-cell (lihat `DICTIONARY_SYSTEM.md`) |
| `kanji_meanings_id` | `kanji_cog.py` `cog_load()` | `kanji` PK | Overlay terjemahan Indonesia, terpisah dari `kanji_entries`, LEFT JOIN saat render, boleh kosong |

---

## 6. Social (`features/social/`)

| Tabel | Dibuat di | Kolom kunci | Catatan |
|---|---|---|---|
| `bookmarks` | `bookmark_cog.py` `cog_load()` | `id` PK autoincrement, UNIQUE `(user_id, message_id)` | Trigger reaksi 🔖 |
| `custom_roles` | `custom_role_cog.py` `cog_load()` | PK `(guild_id, user_id)` | 1 role kustom per user, khusus Companion/Patron |
| `kneels` | `kneel_leaderboard_cog.py` `cog_load()` | PK `(guild_id, message_id)` | Skor dihitung ulang tiap ada reaksi 🧎/custom emoji `ikneel` ditambah/dicabut |
| `user_ranks` | `rank_saver_cog.py` `cog_load()` | PK `(guild_id, discord_user_id)` | Snapshot role tiap 10 menit, dipulihkan otomatis saat user rejoin |
| `event_roles` | `event_roles_cog.py` `cog_load()` | PK `(guild_id, event_id)` | Role sementara per Discord Scheduled Event, auto-cleanup saat event selesai |
| `daily_questions` | `daily_question_cog.py` `cog_load()` | `id` PK autoincrement | Pertanyaan harian hasil generate OpenAI, 1x per hari per channel |

`voice_jtc_cog.py` (Join to Create) **tidak punya tabel** — state room
aktif cuma disimpan in-memory (`self._created_channels`,
`self._room_owners`), disengaja karena kalau bot restart, `on_ready()`
sudah nyapu bersih room kosong peninggalan sesi lama.

---

## 7. Moderation (`features/moderation/`)

| Tabel | Dibuat di | Kolom kunci | Catatan |
|---|---|---|---|
| `active_mutes` | `selfmute_cog.py` `cog_load()` | PK `(guild_id, user_id)` | Simpan role yang dicabut sementara (`roles_to_restore`, comma-separated ID) untuk dipulihkan saat unmute |
| `sticky_messages` | `sticky_messages_cog.py` `cog_load()` | PK `(guild_id, channel_id)` | Pesan tetap yang di-repost otomatis tiap ada pesan baru di channel |

`thread_resolver_cog.py` **tidak punya tabel** — status "terselesaikan"
disimpan langsung di nama thread Discord (prefix `[TERSELESAIKAN]`),
bukan di database.

---

## 8. Tidak Ada Tabel (Server Admin & System)

`features/server_admin/*` (backup, restore permission, structure) dan
`features/system/*` (watchdog, sync) **tidak membuat tabel apa pun** —
operasinya langsung ke Discord API atau file export (JSON/gzip), tidak
ada state persisten di SQLite.

---

## 9. Riwayat File Migration

| File | Isi |
|---|---|
| `migrations/v1_membership_system.sql` | Skema dasar `orders`, `trial_claims`, `membership_history_v1` (migrasi data dari `membership_history` lama), kolom `source` di `memberships` |
| `migrations/v2_purchase_flow.sql` | Recreate total tabel `orders` (status baru, kolom bukti transfer, kode unik, draft timeout) — SQLite tidak bisa `ALTER` `CHECK` constraint jadi rename→create→copy→drop |
| `migrations/v3_practice_threads.sql` | Tabel `practice_threads` — sifatnya opsional, karena `practice_cog.py cog_load()` sudah bikin tabel yang sama otomatis. File ini murni konsistensi dengan pola `migrations/` yang sudah ada |

---

## Riwayat Perubahan Signifikan

- **2026-07-21** — Dibuat dari nol, menelusuri semua `cog_load()` dan
  file `migrations/` satu per satu. Ditemukan 1 potensi utang teknis:
  tabel `membership_history` (tanpa suffix, versi lama) belum pernah
  dikonfirmasi ter-drop setelah migrasi ke `membership_history_v1` —
  perlu dicek manual di database production.
