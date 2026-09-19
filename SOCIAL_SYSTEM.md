# SOCIAL_SYSTEM.md — Sistem Social Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** mekanisme `/info`, `/kneelderboard`,
> `/bookmarks`, `/create_role`, `/delete_role`, auto-role member baru +
> faction lewat reaksi, voice join-to-create, pertanyaan harian AI, role
> event terjadwal, dan snapshot/restore role — semua yang ada di
> `features/social/`
> **BUKAN sumber untuk:** parameter command lengkap (lihat `COMMANDS.md`
> — dokumen ini menjelaskan PERILAKU, `COMMANDS.md` menjelaskan
> SIGNATURE), skema tabel SQL lintas-fitur (lihat `DATABASE_SCHEMA.md`),
> permission channel (lihat `PERMISSION_MATRIX.md`)
> **Terakhir diverifikasi terhadap kode:** 2026-09-19 — dibaca penuh
> kesembilan file di `features/social/` + `git log -p --follow` untuk
> tiap file (mencari pola "restriction yang tidak ditegakkan", sama
> seperti temuan `/log_stats` di `IMMERSION_SYSTEM.md`).

**Dokumen ini baru** — sebelumnya fitur social (5 command + 5 cog
background) sama sekali tidak punya dokumen topik.

---

## 1. Peta Folder

```
features/social/
├── info_cog.py               ← /info (arsip info, 1 entri dinamis)
├── kneel_leaderboard_cog.py    ← /kneelderboard
├── bookmark_cog.py              ← /bookmarks + listener 🔖
├── custom_role_cog.py            ← /create_role, /delete_role
├── auto_receive_cog.py            ← on_member_join, reaksi role-assign
├── voice_jtc_cog.py                ← voice "Join to Create"
├── daily_question_cog.py            ← pertanyaan harian AI (tasks.loop)
├── event_roles_cog.py                ← role Discord Scheduled Event
├── rank_saver_cog.py                  ← snapshot/restore role (tasks.loop)
├── info_commands.yml
├── rank_saver_settings.yml
└── daily_questions_settings.yml
```

**Catatan git history lintas-file:** seluruh riwayat commit di folder
ini (satu author, `mufti`) cuma berisi rename mekanis (`cogs/`→
`features/social/`, `lib.*`→`shared.*`) dan ekstraksi string ke `Msg`
class — **tidak ada satu pun check permission yang pernah
ditambah/dihapus/dilemahkan** di riwayat kesembilan file ini. Artinya
setiap gap yang ditemukan di bawah **ada sejak commit pertama**, bukan
regresi dari perubahan belakangan.

---

## 2. `/info`

Sumber data: `info_commands.yml` (statis) + 1 entri dinamis
(`member-reguler`, `_build_member_reguler_text()` — memanggil
`get_active_prices()`/`get_lifetime_threshold()` live, `info_cog.py:38-51`).
Tidak ada gate akses, tidak ada parameter user lain — publik, sesuai
niatnya (arsip info umum, bukan data personal).

**Riwayat penting:** `member-reguler` DULU teks statis berisi angka
"60 poin" yang basi (sudah lama tidak sesuai `point_threshold: 24` di
config) — diperbaiki jadi dinamis di commit `df9ed2d` (20 Jul). Ada
comment eksplisit di `info_commands.yml:20-27` melarang menambah
kembali key statis `member-reguler` supaya bug staleness ini tidak
terulang.

---

## 3. `/kneelderboard` — ⚠️ Cross-Guild Data Exposure

- Skor "kneel" dihitung **ulang dari nol** setiap ada event reaksi
  (bukan increment/decrement): `len([reaction for reaction in
  message.reactions if is_kneel_emoji(...) and message.author.id !=
  payload.user_id])` — menghitung **jumlah jenis emoji kneel yang
  sedang terpasang** (maks 4: `🧎`/`🧎‍♂️`/`🧎‍♀️`/emoji kustom
  `ikneel`), **bukan jumlah user yang bereaksi**. Konsekuensi: skor
  tidak bisa negatif dan tidak bisa "digembungkan" lewat spam
  react/unreact — tapi juga tidak bertambah sebanding jumlah orang yang
  kneel, cuma sebanding jenis emoji yang dipakai. Ini quirk model
  scoring yang perlu diketahui, bukan bug keamanan.
- **Parameter `guild_id` opsional membolehkan query leaderboard server
  Discord LAIN mana pun** (`kneel_leaderboard_cog.py:149,158`) —
  **tidak ada pengecekan bahwa pemanggil adalah anggota server target**.
  Query `GET_TOP_KNEELS_QUERY`/personal-stats langsung dijalankan
  terhadap `target_guild_id` apa pun yang valid secara numerik. Hasil
  (nama + skor top-20, plus total personal pemanggil di server itu)
  dikirim **non-ephemeral** ke channel — publik.
- **Ini BUKAN kasus "janji UI tidak ditepati"** seperti `/log_stats` —
  fitur cross-guild ini memang diiklankan terbuka di describe text
  ("Ganti ID Server jika ingin meninjau sujud dari kerajaan lain").
  Tapi tetap gap otorisasi nyata: nama + skor per-user dari satu server
  bisa "dibocorkan" ke server lain yang tidak berhubungan, termasuk
  data historis dari server yang bot-nya sudah tidak ada di sana lagi
  (tabel `kneels` tidak pernah dibersihkan saat bot leave guild).

---

## 4. `/bookmarks` — Pola yang Benar

Trigger simpan/hapus lewat reaksi 🔖 (`on_raw_reaction_add`/`_remove`,
file yang sama). Query `/bookmarks` selalu di-scope ke
`interaction.user.id` sendiri (tidak ada parameter user lain), dan
respons **benar dikirim `ephemeral=True`**. Konfirmasi pesan simpan
dikirim lewat DM ke pembookmark (bukan pesan channel), dengan fallback
ke channel `bot_commands` (self-delete 10 detik) yang **tidak
membocorkan isi bookmark** kalau DM tertutup — cuma notice generik. Ini
dikutip sebagai contoh pola akses yang benar untuk dibandingkan dengan
gap di bagian lain dokumen ini.

---

## 5. `/create_role` & `/delete_role`

- `/create_role` digerbang `has_premium_role()` dari `shared/checks.py`
  (`custom_role_cog.py:63`), **bukan decorator** — tapi ditegakkan
  dengan benar, konsisten sejak commit pertama. `has_premium_role()`
  otomatis meloloskan administrator dan staff (`royal_guard`/
  `prime_minister`) sebelum cek tier berbayar (Traveler/Companion/
  Patron minus Trial) — jadi "Khusus Donatur VIP" di describe text
  **cocok dengan implementasi**.
- `/delete_role` tidak punya gate premium — tapi aman, karena cuma
  menghapus role/baris DB milik `interaction.user` sendiri, tidak ada
  parameter user lain.
- Validasi hex color (`^#[0-9a-fA-F]{6}$`) ada; validasi nama role
  (panjang/karakter) **tidak ada** — mengandalkan `discord.HTTPException`
  dari Discord sendiri, ditangkap broad `except Exception` di jalur
  create, tapi **jalur edit role yang sudah ada cuma menangkap
  `discord.Forbidden`** — `HTTPException` dari nama tidak valid saat
  edit bisa lolos jadi exception tak tertangani (bukan celah keamanan,
  tapi crash-risk kecil yang belum ditangani).

---

## 6. Auto-Role & Faction (`auto_receive_cog.py`)

- `on_member_join` → assign role `drifter` + post welcome embed ke
  `join_log`.
- `on_raw_reaction_add`/`_remove` di channel `role_assign` → mapping
  emoji ke role faction **hardcode dict tertutup, 8 entri**
  (`auto_receive_cog.py`), semua resolve lewat `get_role_id()` ke
  `roles.faction_*` di `server_map.yml`. **Tidak ada jalur dari emoji
  yang tidak dikenal ke role staff/admin** — dict-nya tidak
  pakai `.get()` dengan fallback, emoji di luar 8 itu murni no-op. Dicek
  aman.

---

## 7. Voice Join-to-Create (`voice_jtc_cog.py`)

- Room dibuat baru tiap kali (`guild.create_voice_channel`, ID unik dari
  Discord tiap panggilan) — **tidak ada celah reuse/race ID channel**.
- Overwrite `manage_channels=True`+`move_members=True` untuk pemilik
  room **di-scope secara benar ke channel spesifik itu saja** (bukan
  guild-wide), diverifikasi lewat `set_permissions(member, ...)`
  langsung ke objek channel yang baru dibuat.
- **Catatan penting untuk `PERMISSION_MATRIX.md`:** deskripsi "room
  privat, pembuat + yang diundang saja" di `PERMISSION_MATRIX.md` §10
  **tidak ditegakkan di kode file ini** — tidak ada overwrite
  `view_channel`/`connect` yang membatasi anggota lain masuk. Privasi
  room sepenuhnya bergantung pada permission voice level kategori
  Discord (di luar kode bot), bukan logic eksplisit di cog ini. Bukan
  bug — cuma memastikan dokumen lain tidak salah menyiratkan ini
  ditegakkan di kode.

---

## 8. Pertanyaan Harian AI (`daily_question_cog.py`)

- `tasks.loop(minutes=1)`, efektif jalan sekali/hari jam 01:00 UTC
  (08:00 WIB). Dedupe lewat cek `date(created_at)=date('now')` sebelum
  generate ulang.
- Prompt ke OpenAI (`gpt-4o-mini`) **hanya berisi template instruksi +
  10 pertanyaan sebelumnya yang dibuat bot sendiri** — tidak ada nama
  user, ID, atau konten pesan member yang ikut terkirim ke API
  eksternal.
- Tidak ada command/listener apa pun yang bisa memicu ulang atau
  memanipulasi jadwal secara manual — satu-satunya trigger adalah
  `tasks.loop` berbasis jam wall-clock.
- Fail-safe dikonfirmasi: kalau `OPENAI_KEY` kosong, loop tidak jalan
  sama sekali (bukan crash), sesuai `DEPLOYMENT.md` §3.

---

## 9. Role Event Terjadwal (`event_roles_cog.py`)

- Role yang dibuat untuk tiap Scheduled Event **tanpa permission apa
  pun** (`Permissions.none()`, tidak ada `permissions=` di
  `create_role()`) — jadi bahkan kalau logic-nya salah, role ini tidak
  bisa dipakai eskalasi privilege apa pun.
- Siapa yang boleh membuat Scheduled Event murni permission native
  Discord (`Manage Events`) — cog ini tidak melakukan pengecekan
  sendiri, dan `event.creator_id` **tidak pernah dipakai** untuk apa
  pun yang privileged.
- Aman.

---

## 10. Snapshot & Restore Role (`rank_saver_cog.py`) — ⚠️ Temuan Paling Signifikan

**Mekanisme:**
1. `tasks.loop(minutes=10)` — snapshot semua role `is_assignable()`
   (role non-`@everyone`, non-managed, di bawah posisi role bot) milik
   tiap member, dikurangi `role_ids_to_ignore`, disimpan sebagai string
   comma-separated ke tabel `user_ranks`.
2. `on_member_join` — begitu member rejoin, role dari snapshot TERAKHIR
   langsung di-assign ulang **tanpa validasi ulang apa pun** (tidak ada
   approval staff, tidak ada cek apakah role itu baru saja dicabut
   secara sengaja).

**Kenapa ini masalah nyata:**

- `role_ids_to_ignore` di `rank_saver_settings.yml` **kosong (`[]`) —
  sejak commit pertama, tidak pernah diisi**. `is_assignable()` cuma
  cek hierarki posisi role, bukan "apakah role ini boleh
  di-auto-restore". Akibatnya **role staff (`royal_guard`,
  `prime_minister`) diperlakukan sama seperti role faction/kasta biasa**
  — ikut ter-snapshot dan ikut ter-restore.
- **Skenario eksploitasi konkret:**
  ```
  Staff cabut role (mis. demosi royal_guard) dari seorang member
             ↓
  Member leave (sendiri, atau di-kick — BUKAN di-ban)
             ↓
  Member rejoin dalam window ≤10 menit (sebelum snapshot berikutnya
  sempat merekam pencabutan tadi)
             ↓
  on_member_join baca snapshot LAMA yang masih berisi role tsb
             ↓
  member.add_roles() otomatis, TANPA validasi ulang
             ↓
  Role yang baru dicabut (termasuk role staff) balik lagi
  ```
- **Ban** mencegah rejoin sehingga menghindari celah ini — tapi **kick**
  atau sekadar mencabut role tanpa kick sama sekali tidak terlindungi.
- `member.add_roles(*assignable_roles)` di jalur restore **tidak
  dibungkus try/except apa pun** — beda dari listener lain di folder
  ini yang semuanya defensif — kalau Discord API gagal di sini, error
  akan lolos tak tertangani (crash-risk tambahan, bukan cuma isu
  permission).
- Ini bukan regresi — perilaku ini **identik sejak commit pertama**
  (`a4635c4`, 28 Jun), tidak pernah didokumentasikan sebagai known
  tradeoff di komentar kode mana pun.

**Klasifikasi:** privilege-restoration bug, prioritas setara/lebih
tinggi dari temuan `/log_stats` — ini bukan cuma soal siapa bisa
*melihat* data, tapi soal role (termasuk role staff) bisa **kembali
otomatis** setelah sengaja dicabut, dalam window waktu yang nyata dan
reprodusibel.

---

## 11. Tabel Database (Ringkasan)

Detail skema lengkap: `DATABASE_SCHEMA.md` §6. Ringkasan peran:

| Tabel | Dibuat di | Peran |
|---|---|---|
| `bookmarks` | `bookmark_cog.py` | Pesan yang disimpan user via reaksi 🔖 |
| `custom_roles` | `custom_role_cog.py` | 1 role kustom per user (Companion/Patron) |
| `kneels` | `kneel_leaderboard_cog.py` | Skor kneel per pesan (live recount, bukan counter) |
| `user_ranks` | `rank_saver_cog.py` | Snapshot role tiap 10 menit — **sumber celah §10** |
| `event_roles` | `event_roles_cog.py` | Role sementara per Scheduled Event, permission-less |
| `daily_questions` | `daily_question_cog.py` | Pertanyaan harian hasil generate OpenAI |

`auto_receive_cog.py` dan `voice_jtc_cog.py` **tidak punya tabel**
(voice_jtc murni in-memory by design, restart-safe lewat sweep
`on_ready`).

---

## 12. Permission/Access (Ringkasan)

Detail parameter per command: `COMMANDS.md` §6.

| Command/Cog | Gate | Catatan |
|---|---|---|
| `/info` | Tidak ada (publik) | Sesuai, konten bukan personal |
| `/kneelderboard` | `guild_only()` saja | ⚠️ `guild_id` cross-server tanpa cek membership |
| `/bookmarks` | Tidak ada (self-scoped) | Aman, benar `ephemeral=True` |
| `/create_role` | `has_premium_role()` in-body | Sesuai klaim "Khusus Donatur VIP" |
| `/delete_role` | Tidak ada (self-scoped) | Aman |
| `auto_receive_cog` | N/A (listener) | Mapping emoji→role tertutup, aman |
| `voice_jtc_cog` | N/A (listener) | Overwrite di-scope benar per-channel |
| `daily_question_cog` | N/A (tasks.loop) | Tidak ada trigger manual sama sekali |
| `event_roles_cog` | Native Discord `Manage Events` | Role yang dibuat permission-less |
| `rank_saver_cog` | N/A (tasks.loop + listener) | ⚠️ Lihat §10 — tidak ada re-validasi saat restore |

---

## 13. Dependency ke Fitur Lain

- `custom_role_cog.py` → `shared/checks.has_premium_role()` →
  `shared/config.get_staff_role_ids()`/`get_paid_role_ids()`.
- `auto_receive_cog.py`, `voice_jtc_cog.py`, `rank_saver_cog.py` →
  `shared/config.get_role_id()`/`get_channel_id()` → `shared/server_map.yml`.
- `event_roles_cog.py` — **satu-satunya cog di folder ini yang benar-benar
  independen**, tidak import apa pun dari `shared/`.
- Tidak ditemukan dependency ke `membership`/`gatekeeper`/`dictionary`.

---

## 14. Known Issues / Gotcha (Ditemukan Saat Audit 2026-09-19)

Diurutkan dari yang paling serius:

**1. `rank_saver_cog.py` — role (termasuk role staff) bisa otomatis
kembali setelah sengaja dicabut**, lewat window staleness ≤10 menit
kalau member kick/leave lalu rejoin sebelum snapshot berikutnya
(bagian 10). `role_ids_to_ignore` kosong sejak awal, tidak pernah
mengecualikan `royal_guard`/`prime_minister`. **Privilege-restoration
bug, belum diperbaiki — sengaja tidak disentuh di audit ini.**

**2. `/kneelderboard` — cross-guild data exposure.** Parameter `guild_id`
membolehkan query leaderboard server lain tanpa cek keanggotaan, hasil
dikirim publik/non-ephemeral (bagian 3). Gap desain (fitur ini memang
diiklankan, bukan janji kosong), tapi tetap layak masuk backlog
keamanan.

**3. `voice_jtc_cog.py` vs `PERMISSION_MATRIX.md` — mismatch dokumentasi
minor.** Model privasi "pembuat + yang diundang" yang disebut di
`PERMISSION_MATRIX.md` §10 tidak ditegakkan lewat overwrite eksplisit
di kode cog ini — bergantung penuh pada permission kategori Discord di
luar kode bot. Bukan bug, tapi dokumentasi lain perlu tahu ini bukan
jaminan level-kode.

**4. `custom_role_cog.py` — `discord.HTTPException` tak tertangani di
jalur edit role** (nama role tidak valid saat mengedit role yang sudah
ada) — beda dari jalur create yang menangkap broad `Exception`.
Crash-risk kecil, bukan celah keamanan.

**5. Skor `/kneelderboard` adalah hitungan jenis emoji, bukan jumlah
user** — quirk model data yang perlu diketahui sebelum mengira-ngira
"berapa orang yang kneel" dari command ini (bagian 3).

**6. Komentar basi menyebut path lama `lib/checks`/`lib/messages`** di
`bookmark_cog.py:124,156` dan `custom_role_cog.py:62` — sisa era sebelum
rename ke `shared/*` (commit `e95d7f0`). Kosmetik, tidak fungsional.

---

## Riwayat Perubahan Signifikan

- **2026-09-19** — Dibuat dari nol. Dibaca penuh 9 file kode +
  `git log -p --follow` tiap file untuk mencari pola "restriction UI
  tidak ditegakkan" (sama seperti temuan `/log_stats`). Tidak ditemukan
  pola itu di 5 command (`/create_role` justru contoh yang BENAR
  menegakkan klaimnya). Ditemukan 1 privilege-restoration bug nyata di
  `rank_saver_cog.py` (role staff bisa auto-restore lewat window
  staleness kick/rejoin) dan 1 cross-guild data exposure di
  `/kneelderboard` — keduanya belum diperbaiki, sengaja tidak disentuh
  di audit ini.
