# SERVER_ADMIN_SYSTEM.md — Sistem Server Admin Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** mekanisme `/backup_database`,
> `/backup_discord_server`, dan group `/say` (message/embed/edit/delete)
> — bagian `features/server_admin/` di luar permission/structure
> **BUKAN sumber untuk:** `/permission *` dan `/structure *` (lihat
> `PERMISSION_MATRIX.md` — sengaja tidak diaudit ulang di dokumen ini,
> sudah terverifikasi di sana), parameter command lengkap (lihat
> `COMMANDS.md`)
> **Terakhir diverifikasi terhadap kode:** 2026-09-19 — dibaca penuh
> `backup_database_cog.py`, `backup_discord_cog.py`, `say_cog.py`
> (628 baris total) + `git log -p --follow`/`git show` tiap file untuk
> mencari check yang pernah dihapus/dilemahkan.

**Dokumen ini baru.** Audit ini fokus ke rantai otorisasi penuh
(command → decorator/check → helper → operasi/API call → resource yang
disentuh → visibilitas output), bukan cuma "apakah ada decorator" —
karena fitur ini punya blast radius terbesar dari semua yang sudah
diaudit (backup menyentuh seluruh database/struktur server, `/say`
bisa posting/edit/delete pesan).

---

## 1. Cara Baca Kolom "Akses" di Dokumen Ini

Penting dibedakan secara eksplisit di fitur ini:

| Mekanisme | Ditegakkan backend (bot)? | Bisa diubah admin guild lewat Discord Integrations tanpa sepengetahuan bot? |
|---|---|---|
| `@app_commands.default_permissions(...)` | **Tidak** — cuma nilai default yang disarankan ke Discord, murni sisi-client | **Ya** |
| `@app_commands.checks.has_permissions(...)` | **Ya** — discord.py evaluasi `interaction.permissions` saat invoke | Tidak (independen dari Integration settings) |
| `@is_staff()`/`@is_authorized()` (decorator dari `shared/checks.py`) | **Ya** — `app_commands.check` predicate dieksekusi saat invoke | Tidak |
| In-body check manual (mis. `_is_authorized()`) | **Ya** — kode eksplisit yang jalan sebelum operasi | Tidak |

`default_permissions` **sendirian**, tanpa salah satu dari tiga
mekanisme lain sebagai backstop, **bukan pengecekan permission yang
sesungguhnya** — ini yang jadi sumber temuan paling serius di bagian 2.

---

## 2. `/backup_database` — ⚠️⚠️ Regresi Keamanan (Temuan Paling Serius di Seluruh Audit)

### 2.1 Apa yang terjadi

- **Kondisi sekarang** (`backup_database_cog.py:41-43`): cuma
  `@app_commands.guild_only()` + `@app_commands.default_permissions(administrator=True)`.
  **Tidak ada satu pun in-body check** — dibaca penuh 78 baris file
  ini, tidak ada pemanggilan `_is_authorized()`, `has_staff_role()`,
  `has_authorized_access()`, atau pengecekan manual
  `guild_permissions` apa pun. Juga tidak ada global error
  handler/command-tree check di `core/bot.py` yang bisa jadi backstop.
- **Ini REGRESI, bukan desain awal.** Commit pertama file ini
  (`e95d7f0`, 2 Jul, sebagai `database_backup_cog.py`/command
  `post_db`) memakai `@app_commands.checks.has_permissions(administrator=True)`
  — decorator ini **sungguhan ditegakkan backend** oleh discord.py.
  Commit `bb3b698` (16 Jul, "Update Fitur") merename file+command
  sekaligus **mengganti `has_permissions()` jadi `default_permissions()`**
  — tanpa menambah in-body check sebagai kompensasi.
- **Akibatnya:** command yang dulu punya pengecekan backend sungguhan,
  sekarang **satu-satunya penghalang** antara member mana pun dan
  ekspor mentah seluruh database adalah pengaturan Integration Discord
  di sisi guild — yang bisa diubah admin guild mana pun (bukan cuma
  "admin resmi" bot) kapan saja lewat Server Settings, tanpa kode bot
  tahu atau bisa mencegah.
- **Perbandingan langsung dalam folder yang sama membuktikan pola yang
  benar sudah dikenal**: `backup_discord_cog.py` (bagian 3) memakai
  decorator `default_permissions` yang SAMA, tapi di-backstop
  `_is_authorized()` in-body. `backup_database_cog.py` kehilangan
  perlindungan setara ini justru lewat commit yang **melemahkan**
  sesuatu yang tadinya lebih kuat.

### 2.2 Apa yang diekspor — semua tabel, tanpa filter

`create_temporary_gzip_file()` (baris 18-30) murni copy biner:
`db.sqlite3` → gzip, byte-for-byte, **tidak ada filter tabel/kolom
sama sekali**. Berdasarkan `DATABASE_SCHEMA.md`, ini termasuk:
`orders` (`payment_proof_url`, `payment_phash`, `sender_bank`,
`unique_code`), `membership_history_v1` (riwayat lengkap
before/after tier+expiry+poin+`actor`+`reason`), `memberships`,
`trial_claims`, `logs` (aktivitas immersion tiap user), `user_goals`,
data kuis (`quiz_attempts`/`passed_quizzes`/`user_threads`),
`active_mutes`, `custom_roles`, `kneels`, `user_ranks`, `event_roles`,
`daily_questions`, `bookmarks`, `sticky_messages`, plus seluruh cache
API. **Tidak ada satu tabel pun yang dikecualikan.**

### 2.3 Faktor yang meringankan (tapi tidak menutup gap-nya)

- Output **benar ephemeral** (`followup.send(..., ephemeral=True)`,
  baris 54-58) — kalau saja gate-nya benar, eksposur akan terbatas ke
  1 orang. Karena gate-nya bisa dilewati, ephemeral cuma membatasi
  eksposur ke "siapa pun yang kebetulan diizinkan Integration setting",
  bukan ke "admin bot yang sesungguhnya".

### 2.4 Temuan tambahan (kelas berbeda, tetap dicatat)

- **Tidak ada rate limit** — command bisa dipanggil berulang tanpa
  batas; tiap panggilan re-read + re-gzip seluruh file DB
  (`asyncio.to_thread`, baris 51). Kelas: **operational risk**
  (resource exhaustion) yang bertumpuk dengan gap otorisasi di atas
  (tiap panggilan berulang = kesempatan eksposur berulang).
- **Path temp file tetap/predictable**: `os.path.join(tempfile.gettempdir(), "db.sqlite3.gz")`
  (baris 21) — bukan `NamedTemporaryFile`/`mkstemp()`, tidak ada suffix
  acak. Dua invocation bersamaan bisa race di path yang sama. Kalau
  proses mati (OOM, restart container) sebelum blok `finally`
  (baris 68-74) sempat jalan, **file ekspor mentah seluruh DB
  tertinggal di path yang predictable** sampai invocation berikutnya
  menimpanya. Kelas: **operational risk**.
- Pesan error mentah (`{e}`) dikirim balik ke user saat exception
  (baris 64) — ephemeral jadi risiko rendah sendirian, tapi
  bertumpuk dengan gap gate di atas. Kelas: **code bug** (minor).

### 2.5 Verifikasi Ulang (2026-09-19, sebelum dikunci sebagai temuan final)

Diverifikasi langsung ke kode/git (bukan cuma dari laporan agen audit)
terhadap 6 hal, sebelum temuan ini dianggap final:

1. **Diff commit `bb3b698` dibaca penuh** (`git show bb3b698 --
   'features/server_admin/*database_backup_cog.py'
   'features/server_admin/backup_database_cog.py'`) — total perubahan
   untuk file ini di commit itu cuma 10 baris, dan **seluruhnya** ada
   di blok decorator + rename fungsi (`post_db`→`backup_database`,
   `has_permissions()`→`default_permissions()`). Tidak ada baris lain
   yang berubah — **tidak ada check yang dipindah ke helper/service
   mana pun**, murni dihapus.
2. **Seluruh file (79 baris) dibaca ulang penuh** — `create_temporary_gzip_file()`
   cuma fungsi utilitas gzip, nol logic otorisasi. Alur command:
   `defer()` → panggil fungsi itu → kirim file, dibungkus try/except
   generik. **Tidak ada check tersembunyi di call chain mana pun.**
3. **Perbandingan langsung baris-ke-baris dengan `backup_discord_cog.py`**
   — decorator dikonfirmasi **persis sama**
   (`@app_commands.guild_only()` + `@app_commands.default_permissions(administrator=True)`,
   `backup_discord_cog.py:170-171`), tapi `backup_discord_cog.py`
   punya `if not _is_authorized(interaction.user): return ...` sebagai
   baris pertama badan fungsinya (`backup_discord_cog.py:176`).
   `backup_database_cog.py` tidak punya padanan apa pun untuk baris
   itu.
4. **Scope data dikonfirmasi lengkap ke `DATABASE_SCHEMA.md`**, bukan
   disimpulkan: termasuk `orders` (`payment_proof_url`,
   `payment_phash`, `sender_bank`, `unique_code`),
   `membership_history_v1` (`actor`, `reason`, before/after tier/expiry/
   poin lengkap), `memberships`, `logs` (aktivitas immersion),
   `user_ranks`, `custom_roles`, `kneels`, `active_mutes`, dan seluruh
   tabel lintas-fitur lain. **Koreksi presisi:** konfigurasi (file
   `.yml` seperti `server_map.yml`, `membership_settings.yml`) **TIDAK
   ikut** — itu hidup di filesystem, bukan di `db.sqlite3`, jadi tidak
   ter-backup lewat command ini.
5. **Arti faktual `default_permissions` dikonfirmasi**: ini metadata
   yang dikirim ke Discord saat command di-sync, dipakai Discord untuk
   menentukan default akses di client — tapi **admin guild (siapa pun
   yang punya izin edit Integration di server itu) bisa mengubah siapa
   boleh menjalankan command ini kapan saja lewat Server Settings,
   independen dari kode bot**. Penegakannya terjadi di sisi Discord,
   SEBELUM interaction sampai ke bot — bot tidak menerima informasi
   permission apa pun untuk diverifikasi ulang saat interaction
   diterima.
6. **Pertanyaan inti dijawab langsung**: kalau seorang member biasa
   berhasil memperoleh izin invoke (lewat konfigurasi Integration
   guild), apakah bot sendiri punya jalur penolakan? **Tidak** —
   dikonfirmasi lewat grep `core/bot.py` + `main.py` untuk
   `interaction_check`/`on_check_failure`/`tree.check`/`CommandTree`/
   `app_commands.check(` apa pun: nihil hasil. Tidak ada backstop di
   level bot sama sekali, untuk command mana pun, bukan cuma yang ini.

**Severity & exploitability — wording final (disengaja presisi):** Bot
tidak lagi memiliki backstop authorization sendiri untuk command ini;
penegakan sepenuhnya bergantung pada konfigurasi permission command di
sisi Discord masing-masing guild. **Ini BUKAN klaim bahwa command ini
pasti bisa dijalankan member biasa di sembarang guild** — exploitability
sesungguhnya bergantung pada bagaimana admin guild yang bersangkutan
mengonfigurasi Integration permission untuk command ini, yang bisa
berbeda-beda per guild dan tidak diverifikasi di audit ini. Yang pasti
dan tidak bergantung konfigurasi guild mana pun: **kode bot sendiri
tidak lagi menjadi bagian dari pertahanan itu.**

### 2.6 Klasifikasi

**Authorization gap (regresi) — dikunci sebagai temuan final.**
Kategori paling serius yang ditemukan di seluruh rangkaian audit ini,
karena (a) ini bukan "lupa menambah check" seperti temuan lain, tapi
**secara aktif melemahkan check yang tadinya benar dan ditegakkan
backend**, dan (b) blast radius-nya seluruh database, bukan data satu
fitur.

---

## 3. `/backup_discord_server` — Pola yang Benar (Pembanding)

### 3.1 Rantai otorisasi — defense-in-depth yang benar

- Decorator: `default_permissions(administrator=True)` (baris 171) —
  sama seperti bagian 2, TIDAK ditegakkan backend sendirian.
- **Tapi di-backstop in-body check nyata**: `_is_authorized(interaction.user)`
  (baris 176-179, definisi baris 49-55) — `True` kalau
  `user.id in AUTHORIZED_USER_IDS` (env var `AUTHORIZED_USERS`) ATAU
  `user.guild_permissions.administrator`. Cek ini jalan dan bisa
  menolak **sebelum** data apa pun dikumpulkan.
- Populasi efektif = `{Discord administrator} ∪ {AUTHORIZED_USER_IDS}`
  — dijamin ditegakkan terlepas dari pengaturan Integration Discord:
  kalau admin guild melonggarkan Integration, `_is_authorized()` tetap
  menolak siapa pun di luar populasi itu. Ini pola yang **seharusnya**
  juga ada di `/backup_database`.

### 3.2 Apa yang diekspor — terverifikasi aman untuk bagian sensitif

- Setting guild, role (termasuk bitmask permission), channel (termasuk
  **permission overwrite per-role DAN per-member** — nama/ID member
  dengan overwrite channel spesifik ikut terekspos, mis. siapa yang
  pernah kena restriksi channel tertentu), emoji, sticker, scheduled
  event, metadata webhook, thread aktif.
- **Webhook — dikonfirmasi TIDAK termasuk credential.** Cuma
  `id`/`name`/`channel_id`/`avatar_url` yang diserialisasi (baris
  283-288); tidak ada akses ke `hook.url`/`hook.token` di mana pun di
  file ini. Komentar header file (baris 11-13) mengklaim URL webhook
  sengaja dikecualikan karena itu adalah credential — **klaim ini
  akurat**, diverifikasi ke kode. Tidak ada `guild.invites()` juga —
  kode invite tidak ikut terekspor.
- Output ephemeral (baris 327-342), dengan guard ukuran 24MB (kalau
  lebih, command menolak kirim dan menyarankan script terpisah —
  bukan kirim terpotong).

### 3.3 Klasifikasi

**Documented design** — aman, pola yang benar, dan justru jadi bukti
bahwa pola defense-in-depth ini **sudah dikenal dan dipakai** di repo
yang sama, memperkuat bahwa hilangnya pola ini di `/backup_database`
adalah regresi, bukan standar yang belum pernah ada.

- **Operational risk minor:** tidak ada rate limit, banyak Discord API
  call per invocation (satu per text channel untuk webhook, plus fetch
  scheduled events) — read-only jadi bukan risiko destruktif, cuma
  DoS-adjacent.

---

## 4. Group `/say` — message / embed / edit / delete

### 4.1 Rantai otorisasi — dikonfirmasi benar dan ditegakkan nyata

- Level grup: `default_permissions(administrator=True)` (tidak
  ditegakkan backend sendirian).
- **Tiap subcommand punya `@is_staff()`** (`say_cog.py:30,71,123,175`)
  — decorator `shared/checks.py` ini **sungguhan ditegakkan**
  (`app_commands.check` predicate, dievaluasi discord.py saat invoke,
  reject dengan pesan `STAFF_ONLY` kalau gagal). Populasi efektif =
  `{Discord administrator} ∪ {pemegang role staff dari server_map.yml}`
  — mekanisme populasi yang **beda** dari `AUTHORIZED_USER_IDS` di
  bagian 3 (berbasis role, bukan env var allowlist), tapi sama-sama
  ditegakkan nyata.

### 4.2 `/say edit` & `/say delete` — dikonfirmasi AMAN untuk pertanyaan inti

**Pertanyaan yang diminta dijawab presisi: bisakah staff menargetkan
pesan yang BUKAN dari bot ini?** Jawaban: **tidak bisa.**

- `/say edit` (baris 140-157): fetch pesan dulu, lalu
  **baris 144**: `if target_message.author != self.bot.user: return ...`
  ("hanya pesan yang dikirim oleh bot ini yang dapat diubah") — cek
  ini jalan **sebelum** operasi edit (baris 155/157). Tidak ada
  mutasi parsial mungkin terjadi.
- `/say delete` (baris 189-197): pola identik — fetch → cek authorship
  (baris 193) → baru delete (baris 197).
- **Nuansa scope yang perlu dicatat (bukan bug):** cek-nya cuma
  memverifikasi "pesan ini dari bot", bukan "pesan ini spesifik dari
  `/say`". Tidak ada tabel yang melacak asal-usul pesan bot (dikonfirmasi
  `DATABASE_SCHEMA.md` §8: `server_admin/*` tidak bikin tabel apa pun).
  Jadi `/say edit`/`/say delete` bisa menargetkan **pesan bot mana pun**
  di channel itu — termasuk pesan welcome, log moderasi, pengumuman
  achievement, konfirmasi immersion, dst — bukan cuma pesan yang
  sebelumnya dibuat lewat `/say` sendiri. Deskripsi subcommand sendiri
  ("pesan bot yang telah dikirim sebelumnya") memang tidak menjanjikan
  lebih sempit dari ini, jadi kemungkinan besar memang disengaja — tapi
  lebih luas dari asumsi "cuma bisa edit/hapus apa yang `/say` buat".

### 4.3 `/say message` dengan `reply_to`

Bisa membalas **pesan siapa pun** di channel target (fetch tanpa
filter author, baris 42-49) — ini memang perilaku normal untuk fitur
reply, tidak ada restriksi yang seharusnya ada di sini secara
struktural. Tapi berarti staff bisa membuat bot "membalas secara
resmi" ke pesan siapa pun, termasuk berpotensi dipakai memancing atau
menyiratkan respons editorial ke konten tertentu.

### 4.4 ⚠️ Parameter `channel` — Permission Laundering, Dikonfirmasi Nyata di Ke-4 Subcommand

- Tiap subcommand terima `channel: discord.TextChannel` opsional;
  `target_channel = channel or interaction.channel`. **Tidak ada
  pemanggilan `target_channel.permissions_for(interaction.user)` di
  mana pun di file ini** — permission Discord milik staff yang
  memanggil command, di channel TARGET, **tidak pernah dicek**.
  Satu-satunya permission yang relevan adalah milik BOT sendiri,
  ditemukan reaktif lewat `discord.Forbidden` (baris 57-58, 111-112,
  166-167, 200-201).
- **Konsekuensi:** kalau role bot punya akses channel lebih luas dari
  staff tertentu (mis. channel khusus staff senior, atau channel yang
  bot bisa posting tapi staff itu sendiri tidak — karena overwrite
  per-role/per-member), staff itu tetap bisa mengarahkan `/say
  message|embed|edit|delete` ke channel itu lewat parameter `channel`
  — secara efektif **"mencuci" permission-nya sendiri naik ke level
  permission bot yang lebih luas**. Berlaku untuk posting baru, dan
  untuk edit/delete pesan bot di channel itu (tetap tunduk cek
  authorship di 4.2).

### 4.5 Temuan minor lain

- `/say edit` pada pesan embed: kalau `new_title`/`new_description`
  keduanya `None`, kode tetap jalan `old_embed.copy()` +
  `target_message.edit(embed=new_embed)` tanpa perubahan apa pun
  (baris 148-155, tidak ada guard "minimal 1 field harus berubah" —
  beda dari cabang teks biasa yang memang mensyaratkan `new_content`
  terisi). Command tetap melaporkan "✅ Pesan berhasil diperbarui"
  walau tidak ada yang berubah. Kelas: **code bug** (minor, pesan
  menyesatkan, bukan keamanan).

### 4.6 Klasifikasi

- Rantai otorisasi inti (`@is_staff()`, cek authorship edit/delete):
  **documented design**, aman, dan yang paling teliti dari 3 file di
  audit ini.
- Parameter `channel` tanpa cek permission staff: **authorization gap
  (permission laundering)** — berlaku di ke-4 subcommand, belum
  diperbaiki.

---

## 5. Tabel Database

**Tidak ada.** Ketiga file di scope ini (`backup_database_cog.py`,
`backup_discord_cog.py`, `say_cog.py`) **tidak membuat atau menyentuh
tabel SQLite apa pun** — dikonfirmasi ke `DATABASE_SCHEMA.md` §8 dan
lewat baca penuh ketiga file (tidak ada `bot.RUN`/`GET`/query
aiosqlite di mana pun). "Data yang disentuh" `/backup_database` adalah
seluruh file `db.sqlite3` sebagai blob biner, bukan tabel spesifik.

---

## 6. Permission/Access (Ringkasan Perbandingan)

| Command | Decorator | Backstop in-body? | Populasi efektif ditegakkan? | Kelas |
|---|---|---|---|---|
| `/backup_database` | `default_permissions` saja | **Tidak ada** | **Tidak** — bergantung penuh Integration setting Discord | ⚠️⚠️ Authorization gap (regresi) |
| `/backup_discord_server` | `default_permissions` | `_is_authorized()` (admin ∪ `AUTHORIZED_USER_IDS`) | Ya | Aman |
| `/say message\|embed\|edit\|delete` | `default_permissions` (grup) | `@is_staff()` (admin ∪ role staff) | Ya, untuk siapa boleh panggil — **tapi channel target tidak ikut divalidasi** | Aman (auth) / ⚠️ gap (channel param) |

---

## 7. Dependency ke Fitur Lain

- `backup_discord_cog.py`, `say_cog.py` → `shared/checks.py`
  (`_is_authorized()` lokal di backup_discord berbeda objek dari
  `has_authorized_access()` di `shared/checks.py`, tapi baca env var
  `AUTHORIZED_USERS` yang sama — pola duplikasi kecil yang sama
  seperti ditemukan di `sync_cog.py` — lihat `COMMANDS.md`).
- `say_cog.py` → `shared/checks.get_staff_role_ids()` →
  `shared/server_map.yml`.
- Tidak ditemukan dependency ke fitur lain di luar `shared/`.

---

## 8. Known Issues / Gotcha (Ditemukan Saat Audit 2026-09-19)

Diklasifikasikan sesuai taksonomi: **authorization gap / data exposure
/ destructive-action integrity / operational risk / code bug /
documented design**. Diurutkan dari yang paling serius:

**1. `/backup_database` — authorization gap (regresi), bukan cuma "lupa
check".** Commit `bb3b698` (16 Jul) mengganti
`@app_commands.checks.has_permissions(administrator=True)` (ditegakkan
backend) menjadi `@app_commands.default_permissions(administrator=True)`
(cuma saran sisi-client) tanpa backstop in-body — satu-satunya
penghalang sekarang adalah Integration setting Discord yang bisa
diubah admin guild mana pun. **Temuan paling serius di seluruh
rangkaian audit ini** — blast radius-nya seluruh database (payment
proof, riwayat membership, aktivitas semua user). Belum diperbaiki.

**2. `/backup_database` — data exposure tanpa filter.** Ekspor mentah
seluruh `db.sqlite3`, tidak ada tabel/kolom yang dikecualikan —
menjadi lebih serius karena digabung dengan temuan #1.

**3. `/say` — authorization gap (permission laundering) via parameter
`channel`.** Berlaku di `message`/`embed`/`edit`/`delete` — permission
Discord milik staff pemanggil di channel TARGET tidak pernah dicek,
cuma permission bot yang (reaktif) relevan. Staff bisa posting/edit/
delete di channel yang harusnya di luar akses pribadinya lewat
permission bot yang lebih luas. Belum diperbaiki.

**4. `/backup_database` — operational risk.** Tidak ada rate limit
(resource exhaustion + eksposur berulang); path temp file tetap/
predictable tanpa randomisasi (`tempfile.gettempdir()/db.sqlite3.gz`)
— race antar-invocation, dan file ekspor mentah bisa tertinggal di
path predictable kalau proses mati sebelum cleanup.

**5. `/backup_discord_server` — operational risk minor.** Tidak ada
rate limit, banyak API call per invocation — read-only jadi
DoS-adjacent saja, bukan risiko destruktif.

**6. `/say edit` — code bug minor.** Cabang embed bisa "berhasil"
tanpa perubahan apa pun kalau `new_title`/`new_description` kosong,
tetap melaporkan sukses.

**Dikonfirmasi AMAN, dicatat supaya tidak diaudit ulang tanpa perlu:**
- `/backup_discord_server` — pola defense-in-depth yang benar
  (`default_permissions` + `_is_authorized()` in-body); webhook secret
  dikonfirmasi TIDAK ikut terekspor (klaim di komentar kode akurat).
- `/say edit`/`/say delete` — dikonfirmasi tidak bisa menargetkan pesan
  non-bot; cek authorship jalan sebelum mutasi, tidak ada operasi
  parsial.
- `/say message` `reply_to` bisa membalas pesan siapa pun — ini
  perilaku normal fitur reply, bukan gap struktural.

---

## Riwayat Perubahan Signifikan

- **2026-09-19** — §2 diperkuat lewat review kedua khusus
  `/backup_database` sebelum temuan dikunci final (diff commit `bb3b698`
  dibaca penuh, file 79 baris dibaca ulang, perbandingan baris-ke-baris
  dengan `backup_discord_cog.py`, scope data dikonfirmasi ke
  `DATABASE_SCHEMA.md`, dan dikonfirmasi tidak ada backstop
  `interaction_check`/tree-level apa pun di `core/bot.py`/`main.py`).
  Wording severity diperhalus supaya presisi: bot tidak lagi punya
  backstop sendiri (fakta, tidak bergantung konfigurasi), tapi
  exploitability aktual bergantung konfigurasi Integration tiap guild
  (tidak diklaim "pasti bisa dieksploitasi member biasa di semua
  guild"). Koreksi kecil: konfigurasi `.yml` tidak ikut ter-backup
  (cuma `db.sqlite3`). Temuan dikunci sebagai final — authorization
  gap (regresi), prioritas tertinggi.
- **2026-09-19** — Dibuat dari nol. Dibaca penuh 3 file (628 baris) +
  `git log -p --follow`/`git show` tiap file untuk mencari check yang
  pernah dihapus/dilemahkan — dan ditemukan satu: `/backup_database`
  kehilangan pengecekan backend nyata (`has_permissions(administrator=True)`
  → `default_permissions(administrator=True)` tanpa backstop) di commit
  `bb3b698` (16 Jul), regresi dari desain yang tadinya benar. Ini
  temuan paling serius di seluruh rangkaian audit series (Immersion,
  Social, Moderation, Server Admin) karena blast radius-nya seluruh
  database dan sifatnya regresi (bukan sekadar belum pernah
  diimplementasi). Juga dikonfirmasi aman: `/backup_discord_server`
  (defense-in-depth benar, webhook secret tidak terekspor) dan
  `/say edit`/`/say delete` (cek authorship bot berfungsi). Ditemukan
  gap baru: parameter `channel` di `/say` memungkinkan permission
  laundering di ke-4 subcommand. Semua belum diperbaiki, sengaja tidak
  disentuh (audit-only pass).
