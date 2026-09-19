# COMMANDS.md — Referensi Semua Command Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** daftar lengkap semua slash command & prefix
> command yang terdaftar di kode — parameter, level akses (decorator DAN
> in-body check), lokasi file, cog pemilik — plus daftar cog yang TIDAK
> punya command sama sekali (listener/background task only), supaya
> tidak ada fitur yang "hilang" dari peta cuma karena tidak berbentuk
> command.
> **BUKAN sumber untuk:** detail business logic di balik tiap command
> (lihat dokumen topik masing-masing fitur — link di akhir tiap
> section), harga tier VIP (lihat `PRICING_SYSTEM_REFACTOR.md`), skema
> tabel SQL (lihat `DATABASE_SCHEMA.md`), permission channel (lihat
> `PERMISSION_MATRIX.md`)
> **Terakhir diverifikasi terhadap kode:** 2026-09-19 — setiap command
> dicek langsung ke `async def` di file cog aslinya (nama parameter,
> tipe, decorator, dan in-body access check), bukan disalin dari
> dokumen lain atau dari deskripsi command saja.

**Dokumen ini baru** — sebelumnya tidak ada satu tempat pun yang
mendaftar seluruh command bot. Setiap dokumen topik (`MEMBERSHIP_SYSTEM.md`,
`GATEKEEPER_QUIZ_SYSTEM.md`, dst) cuma mendaftar command miliknya sendiri;
`DEVELOPMENT_GUIDE.md` §9 cuma peta folder, bukan daftar command. Disusun
dengan grep `@app_commands.command`/`Group.command`/`@commands.command`
ke seluruh `features/*/*_cog.py`, lalu tiap command dibaca satu-satu ke
`async def`-nya.

**Total: 44 slash command standalone + 4 command group (13 subcommand) +
5 prefix command + 12 cog yang murni listener/background task (tanpa
command sama sekali).**

---

## Cara Baca Kolom "Akses"

Jangan asumsikan command tanpa decorator akses = terbuka untuk semua.
Banyak command mengecek akses **di dalam badan fungsi** (in-body), bukan
lewat decorator — kalau cuma baca daftar decorator, kesannya command itu
terbuka padahal sebenarnya tidak. Nilai yang dipakai di kolom ini:

| Nilai | Artinya |
|---|---|
| `@is_vip()` / `@is_premium()` / `@is_staff()` / `@is_authorized()` | Decorator dari `shared/checks.py` — cek dilakukan sebelum command jalan, pesan error otomatis lewat `Msg` |
| `admin (default_permissions)` | Native Discord `default_permissions(administrator=True/manage_guild=True/manage_messages=True)` — command **hilang dari UI Discord** buat yang tidak punya permission itu, bukan sekadar ditolak setelah diklik |
| `terbuka` | Tidak ada decorator maupun in-body check — benar-benar terbuka untuk siapa pun (kadang tetap dibatasi `guild_only()`, yaitu tidak bisa dipakai di DM) |
| `in-body: <fungsi>` | **Tidak ada decorator**, tapi command mengecek akses manual di dalam kode lewat fungsi yang disebut — kalau mengedit ulang command ini, cek eksplisit ke fungsi itu, jangan asumsikan dari decorator |

---

## 1. Dictionary (`features/dictionary/`)

| Command | Parameter | Akses | Ringkasan | Lokasi |
|---|---|---|---|---|
| `/kanji` | `kanji?`, `jlpt?`, `joyo?`, `kelas_sd?` | terbuka (mode list); `in-body: has_dic_access()` untuk mode detail | Cari kanji atau jelajahi berdasarkan JLPT/Jōyō/kelas SD | `kanji_cog.py:939` |
| `/kanji_reload` | — | admin (`default_permissions`) | Reload kamus kanji dari CSV | `kanji_cog.py:1025` |
| `/kotoba` | `kata?`, `level?` | terbuka (list); `in-body: has_dic_access()` untuk detail | Cari kosakata atau jelajahi per level JLPT | `kotoba_cog.py:632` |
| `/kotoba_reload` | — | admin | Reload kamus kotoba dari CSV | `kotoba_cog.py:700` |
| `/bunpou` | `pola?`, `level?` | terbuka (list); `in-body: has_dic_access()` untuk detail | Cari pola grammar atau jelajahi per level JLPT | `bunpou_cog.py:873` |
| `/bunpou_reload` | — | admin | Reload kamus bunpou dari CSV | `bunpou_cog.py:945` |

Detail arsitektur render, gating, dan skema kolom: `DICTIONARY_SYSTEM.md`.

---

## 2. Gatekeeper (`features/gatekeeper/`)

| Command | Parameter | Akses | Ringkasan | Lokasi |
|---|---|---|---|---|
| `/journey` | — | terbuka | Roadmap kasta lengkap + langkah berikutnya | `gatekeeper_cog.py:1149` |
| `/my_next_action` | — | terbuka | Jawaban ringkas: langkah berikutnya + kuis yang terbuka | `gatekeeper_cog.py:1196` |
| `/ranktable` | — | terbuka | Statistik sebaran kasta seluruh server | `gatekeeper_cog.py:983` |
| `/rankusers` | `role` | terbuka | Daftar user pemegang kasta tertentu | `gatekeeper_cog.py:1010` |
| `/list_role_commands` | `guild_id?` | terbuka | Semua command kuis + status cooldown personal | `gatekeeper_cog.py:1049` |
| `/create_quiz_menu` | — | admin | Post dropdown menu pendaftaran kuis | `gatekeeper_cog.py:1132` |
| `/reset_user_cooldown` | `user`, `quiz_to_reset?` | admin | Reset cooldown kuis milik user (fungsi Python: `clear_user_cooldown`) | `gatekeeper_cog.py:965` |
| `/create_practice_menu` | — | admin | Post tombol "Mulai Latihan" di forum `quiz-public` | `practice_cog.py:209` |

Detail alur kuis, anti-cheat, cooldown, journey system: `GATEKEEPER_QUIZ_SYSTEM.md`.

---

## 3. Immersion (`features/immersion/`)

| Command | Parameter | Akses | Ringkasan | Lokasi |
|---|---|---|---|---|
| `/log` | `media_type`, `amount`, `name?`, `comment?`, `backfill_date?` | `@is_vip()` | Catat aktivitas immersion, dapat poin | `log_cog.py:167` |
| `/log_undo` | `log_entry` | `@is_vip()` | Batalkan satu entri log | `log_cog.py:364` |
| `/log_achievements` | — | `@is_vip()` | Lihat lencana pencapaian | `log_cog.py:405` |
| `/log_export` | `user?` | `@is_vip()` — deskripsi UI bilang "Khusus Staf", **TIDAK ditegakkan di kode** ⚠️ | Ekspor riwayat log sebagai CSV | `log_cog.py:442` |
| `/logs` | `user?` | `@is_vip()` — deskripsi UI bilang "Khusus Staf", **TIDAK ditegakkan di kode** ⚠️ | Ekspor riwayat log sebagai dokumen `.txt` | `log_cog.py:478` |
| `/log_leaderboard` | `media_type?`, `month?` | `@is_vip()` | Leaderboard keaktifan bulan ini (atau bulan/tipe media pilihan) | `log_cog.py:511` |
| `/log_race` | `from_date`, `to_date`, `media_type?`, `race_type?='points'` | terbuka (cooldown 300 detik, admin exempt) | Video bar chart race progress immersion | `bar_races_cog.py:127` |
| `/log_stats` | `user?`, `from_date?`, `to_date?`, `immersion_type?` | **terbuka — deskripsi UI parameter `user` bilang "Khusus Staf", TIDAK ADA gate sama sekali di kode** ⚠️ | Grafik bar chart + heatmap statistik immersion | `stats_cog.py:229` |
| `/log_set_goal` | `media_type`, `goal_type`, `goal_value`, `end_date_or_hours`, `start_date?` | `@is_vip()` | Pasang target belajar | `goals_cog.py:133` |
| `/log_remove_goal` | `goal_entry` | `@is_vip()` | Hapus satu target belajar | `goals_cog.py:208` |
| `/log_view_goals` | `member?` | `@is_vip()` | Lihat target belajar (sendiri atau warga lain) | `goals_cog.py:234` |
| `/log_clear_goals` | — | `@is_vip()` | Bersihkan target belajar yang sudah kedaluwarsa | `goals_cog.py:262` |

⚠️ = gap keamanan/dokumentasi nyata, ditemukan saat audit 19 Sep — belum
diperbaiki (bukan refactor sekarang). Detail lengkap: `IMMERSION_SYSTEM.md` §14.

Detail lengkap mekanisme (poin, achievement, goal, statistik, race,
cache API eksternal): `IMMERSION_SYSTEM.md`.

---

## 4. Membership (`features/membership/`)

| Command | Parameter | Akses | Ringkasan | Lokasi |
|---|---|---|---|---|
| `/subscribe` | — | terbuka | Mulai alur pembelian membership | `purchase_cog.py:457` |
| `/orders` | — | admin (`manage_guild`) | Lihat order pending review (staff) | `purchase_cog.py:1073` |
| `/my_orders` | — | terbuka | Riwayat order milik sendiri | `purchase_cog.py:1113` |
| `/membership_sync` | — | admin + `in-body: _can_manage()` | Sinkronisasi role Discord dengan database membership | `admin_cog.py:657` |

### Group `/admin` — admin-only (`default_permissions(administrator=True)` di level grup, `admin_cog.py:168`)

Semua subcommand di bawah ini juga dicek ulang lewat `_can_manage()`
(admin, `AUTHORIZED_USERS`, atau `moderator_role_ids`), **kecuali**
`check-member` dan `membership-history` yang cuma mengandalkan
`default_permissions` grup, dan `membership-purge-history` yang justru
**lebih ketat** — wajib `administrator` asli, bukan cuma `_can_manage()`.

| Subcommand | Parameter | Ringkasan | Lokasi |
|---|---|---|---|
| `grant-member` | `user`, `product_id`, `quantity=1` | Grant produk membership ke 1 user | `admin_cog.py:178` |
| `grant-trial` | `user` | Grant trial 5 hari, 0 poin | `admin_cog.py:264` |
| `grant-batch` | `users`, `product_id`, `quantity=1` | Grant produk ke banyak user sekaligus | `admin_cog.py:317` |
| `reset-points` | `user` | Reset poin lifetime ke 0 (ditolak kalau sudah Patron) | `admin_cog.py:420` |
| `revoke-member` | `user` | Cabut membership + role Discord | `admin_cog.py:456` |
| `check-member` | `user` | Cek status membership satu user (read-only) | `admin_cog.py:507` |
| `membership-history` | `user?` | Lihat riwayat grant/revoke | `admin_cog.py:566` |
| `membership-purge-history` | `user` | Hapus permanen riwayat membership user — wajib admin asli | `admin_cog.py:632` |

Detail alur pembelian, anti-fraud, scheduler: `MEMBERSHIP_SYSTEM.md`.
Harga tier: `PRICING_SYSTEM_REFACTOR.md`.

---

## 5. Moderation (`features/moderation/`)

| Command | Parameter | Akses | Ringkasan | Lokasi |
|---|---|---|---|---|
| `/solved` | — | terbuka | Tandai thread forum bantuan sebagai selesai | `thread_resolver_cog.py:48` |
| `/selfmute` | `hours?=0`, `minutes?=0` | `guild_only` saja; role yang boleh dipilih dibatasi `in-body` dari `selfmute_settings.yml` | Bisukan diri sendiri untuk durasi tertentu | `selfmute_cog.py:135` |
| `/unmute_user` | `member` | admin | Unmute paksa warga lain, pulihkan role tersimpan | `selfmute_cog.py:90` |
| `/check_mute` | — | terbuka | Cek status mute sendiri, auto-unmute kalau sudah lewat | `selfmute_cog.py:210` |
| `/sticky_last_message` | — | admin (`manage_messages`) | Jadikan pesan terakhir sebagai sticky message | `sticky_messages_cog.py:59` |
| `/unsticky` | — | admin (`manage_messages`) | Hapus sticky message dari channel ini | `sticky_messages_cog.py:86` |

**Cog tanpa command** (background task murni): `quiz_forum_cog.py` — auto-archive
thread latihan `quiz-public` yang tidak aktif (default tiap 1 jam, lihat
`GATEKEEPER_QUIZ_SYSTEM.md` §8).

**Belum ada dokumen topik konsolidasi untuk fitur ini** — cooldown
`selfmute` dan alur `/solved` cuma tersebar di komentar kode.

---

## 6. Social (`features/social/`)

| Command | Parameter | Akses | Ringkasan | Lokasi |
|---|---|---|---|---|
| `/info` | `info_key` | terbuka | Arsip informasi server (topik/keyword, ada autocomplete) | `info_cog.py:86` |
| `/kneelderboard` | `guild_id?` | terbuka | Leaderboard skor "kneel" (reaksi 🧎) | `kneel_leaderboard_cog.py:149` |
| `/bookmarks` | — | terbuka | Lihat 10 pesan bookmark terbaru | `bookmark_cog.py:151` |
| `/create_role` | `name`, `color_hex` | `in-body: has_premium_role()` (Companion/Patron) | Buat/update role kustom warna sendiri | `custom_role_cog.py:58` |
| `/delete_role` | — | terbuka (hapus milik sendiri saja) | Hapus role kustom sendiri | `custom_role_cog.py:106` |

**Cog tanpa command** (5 dari 9 cog di folder ini — semua listener/background task):

| Cog | Fungsi |
|---|---|
| `auto_receive_cog.py` | Auto-role Drifter member baru + role faction lewat reaksi emoji |
| `voice_jtc_cog.py` | Voice "Join to Create" — bikin room privat otomatis |
| `daily_question_cog.py` | Generate pertanyaan harian via OpenAI (background task tiap menit) |
| `event_roles_cog.py` | Role sementara mengikuti Discord Scheduled Event |
| `rank_saver_cog.py` | Snapshot role tiap 10 menit, pulihkan otomatis saat user rejoin |

**Belum ada dokumen topik untuk fitur ini** — termasuk yang `OPENAI_KEY`-nya
sudah dicatat sebagai gap env var di `DEPLOYMENT.md` §1.

---

## 7. Server Admin (`features/server_admin/`)

| Command | Parameter | Akses | Ringkasan | Lokasi |
|---|---|---|---|---|
| `/backup_database` | — | admin | Gzip database SQLite, kirim sebagai file privat | `backup_database_cog.py:43` |
| `/backup_discord_server` | — | admin + `in-body: _is_authorized()` | Ekspor struktur server (channel, role, emoji, dst) ke JSON | `backup_discord_cog.py:172` |

### Group `/say` — admin, `@is_staff()` di semua subcommand (`say_cog.py`)

| Subcommand | Parameter | Lokasi |
|---|---|---|
| `message` | `message`, `channel?`, `reply_to?` | `say_cog.py:31` |
| `embed` | `description`, `title?`, `color?`, `channel?`, `footer?`, `image_url?`, `thumbnail_url?` | `say_cog.py:72` |
| `edit` | `message_id`, `channel?`, `new_content?`, `new_description?`, `new_title?` | `say_cog.py:124` |
| `delete` | `message_id`, `channel?` | `say_cog.py:176` |

### Group `/permission` — `in-body: has_authorized_access()` di semua subcommand (`permissions_cog.py`)

| Subcommand | Parameter | Lokasi |
|---|---|---|
| `restore` | — | `permissions_cog.py:64` |
| `restore_channel` | `channel` | `permissions_cog.py:100` |
| `preview` | `channel?` | `permissions_cog.py:142` |
| `backup` | — | `permissions_cog.py:179` |
| `sync_roles` | — | `permissions_cog.py:238` |

### Group `/structure` — `in-body: has_authorized_access()` (`structure_cog.py`)

| Subcommand | Parameter | Lokasi |
|---|---|---|
| `preview` | — | `structure_cog.py:235` |
| `setup` | — | `structure_cog.py:252` |

Detail permission channel & struktur kategori: `PERMISSION_MATRIX.md`.
Fungsi backup/say sendiri **belum** punya dokumen topik.

---

## 8. System (`features/system/`) — Prefix Command, BUKAN Slash Command

Dipicu lewat `COMMAND_PREFIX` (`%` di production), bukan muncul di menu
slash Discord. Semua khusus `AUTHORIZED_USERS`.

| Command | Akses | Ringkasan | Lokasi |
|---|---|---|---|
| `%sync_guild` | `is_authorized()` versi lokal file ini | Sync command ke guild saat ini | `sync_cog.py:19` |
| `%sync_global` | idem | Sync command secara global | `sync_cog.py:28` |
| `%clear_global_commands` | idem | Hapus semua command global | `sync_cog.py:35` |
| `%clear_guild_commands` | idem | Hapus command guild saat ini | `sync_cog.py:43` |
| `%watchdog_status` | `in-body`: `AUTHORIZED_USER_IDS`, silent no-op kalau bukan | Status kesehatan watchdog | `watchdog_cog.py:154` |

**Catatan:** `is_authorized()` di `sync_cog.py` adalah fungsi **terpisah**
dari `shared/checks.py` — sama-sama baca `AUTHORIZED_USERS`, tapi objek
fungsi beda (duplikasi kecil, bukan bug fungsional).

---

## 9. Ringkasan Cog Tanpa Command Sama Sekali

Di luar 2 cog yang sudah disebut di section masing-masing di atas
(`quiz_forum_cog.py`, dan 5 cog di Social), berikut daftar lengkapnya
supaya tidak ada yang tercecer:

| Cog | Folder | Yang dikerjakan |
|---|---|---|
| `auto_receive_cog.py` | social | `on_member_join`, `on_raw_reaction_add/remove` — auto-role Drifter & faction |
| `voice_jtc_cog.py` | social | `on_ready`, `on_voice_state_update` — voice join-to-create |
| `daily_question_cog.py` | social | `tasks.loop` tiap 1 menit — cek jadwal pertanyaan harian AI |
| `event_roles_cog.py` | social | `on_scheduled_event_*` + `tasks.loop` tiap 5 menit — role event |
| `rank_saver_cog.py` | social | `on_ready`, `on_member_join` + `tasks.loop` tiap 10 menit — snapshot role |
| `quiz_forum_cog.py` | moderation | `tasks.loop` (default tiap 1 jam) — auto-archive thread `quiz-public` |
| `scheduler_cog.py` | membership | 3× `tasks.loop` — `draft_timeout_check` (1j), `pending_order_check` (6j), `role_sync_check` (24j) |

Total **7 cog** murni event/background, di luar 5 cog Social yang sudah
didaftar di section 6 (total 12 cog tanpa command dari 32 cog di
seluruh repo).

---

## Riwayat Perubahan Signifikan

- **2026-09-19** — Section Immersion ditandai ⚠️ pada `/log_export`,
  `/logs`, `/log_stats` — deskripsi UI ketiganya mengklaim "Khusus Staf"
  untuk parameter `user`, tapi audit `IMMERSION_SYSTEM.md` menemukan
  tidak ada pengecekan staff di kode sama sekali. Link ditambahkan ke
  `IMMERSION_SYSTEM.md` yang baru dibuat.
- **2026-09-19** — Dibuat dari nol. Grep seluruh `features/*/*_cog.py`
  untuk `@app_commands.command`/`Group.command`/`@commands.command`,
  tiap command diverifikasi satu-satu ke `async def` aslinya (parameter,
  decorator, in-body access check). Ditemukan: 12 dari 32 cog sama
  sekali tidak punya command (murni listener/background task) — 5 di
  antaranya (`auto_receive`, `voice_jtc`, `daily_question`, `event_roles`,
  `rank_saver`) tidak punya dokumen topik apa pun. Ditemukan juga pola
  yang belum terdokumentasi: banyak command admin (`/permission *`,
  `/structure *`, `/create_role`, `backup_discord_server`) tidak
  memakai decorator akses dari `shared/checks.py`, melainkan cek manual
  di dalam kode (`has_authorized_access()`, `has_premium_role()`,
  `_can_manage()`) — kalau cuma baca decorator, command-command ini
  terlihat terbuka padahal sebenarnya tidak.
