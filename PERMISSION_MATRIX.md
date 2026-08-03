# PERMISSION_MATRIX.md — Peta Permission Channel & Role Kotabi Bot

> **Kenapa file terpisah** (bukan masuk `DEVELOPMENT_GUIDE.md` atau
> `MEMBERSHIP_FEATURE_GUIDE.md`): dokumen ini bukan spesifik fitur
> membership, tapi infrastruktur lintas-fitur yang menyentuh SEMUA role
> (staff, quiz-rank, faction, VIP, dst) dan SEMUA channel server.
>
> **Status: aktif digunakan.** Ini adalah dokumentasi kondisi permission
> yang SEHARUSNYA berlaku di server sekarang, sekaligus sumber kebenaran
> untuk `features/server_admin/support/permission_table.py`. Kalau ada
> yang mau ubah permission channel apa pun, edit dulu tabel di dokumen
> ini, baru terjemahkan ke `permission_table.py`, lalu jalankan
> `/permission restore` — jangan ubah permission langsung dari Discord UI
> kalau mau perubahannya persisten (perubahan manual dari UI akan
> ketimpa lagi setiap kali `/permission restore` dijalankan).

---

## 0. Cara kerja sistem restore permission

Bot punya command grup `/permission` (di `permissions_cog.py`) dan
`/structure` (di `structure_cog.py`) yang membaca satu sumber kebenaran:
`CHANNEL_PERMISSIONS` di `features/server_admin/support/permission_table.py`.

- **`/permission sync_roles`** — validasi: cek apakah semua role key dan
  nama channel yang dipakai di `CHANNEL_PERMISSIONS` benar-benar ada di
  server. Jalankan ini duluan sebelum restore, setiap kali ada channel
  atau role yang berubah nama/ID.
- **`/permission restore`** — terapkan seluruh `CHANNEL_PERMISSIONS` ke
  server. Aman dijalankan berkali-kali (idempotent).
- **`/permission restore_channel`** — restore satu channel saja.
- **`/permission preview`** — dry-run, lihat apa yang AKAN diterapkan
  tanpa benar-benar mengubah apa pun.
- **`/permission backup`** — snapshot kondisi permission semua channel
  saat ini ke file JSON, sebelum menjalankan restore.
- **`/structure setup`** — menata channel ke kategori yang benar (lihat
  `STRUCTURE_BLUEPRINT`), lalu otomatis menjalankan restore permission
  di akhir.

Setiap channel di `CHANNEL_PERMISSIONS` berbentuk:

```python
"nama-channel": {
    "role_key": {"permission_kwarg": True/False, ...},
    ...
}
```

`role_key` berupa `"everyone"` (khusus, di-resolve ke `guild.default_role`)
atau nama role dari `shared/server_map.yml` (mis. `"trial"`,
`"royal_guard"`). `permission_kwarg` harus persis sama dengan nama atribut
`discord.PermissionOverwrite` (mis. `view_channel`, `send_messages`,
`create_public_threads`, `connect`, `speak`).

Channel yang **tidak** muncul di `CHANNEL_PERMISSIONS` sengaja tidak
diberi overwrite apa pun — permission-nya murni warisan dari role-level
Discord biasa (lihat bagian 10).

---

## 1. Pemetaan Role → Grup Fungsional

Server punya banyak role (lihat `shared/server_map.yml`), tapi untuk
urusan **channel permission**, cuma segelintir yang relevan. Role kasta
kuis (Duke, Viscount, dst), faction (`faction_anime`, dst), badge
pencapaian (`flash_reader`, dst), dan role leveling (`level_bard`, dst)
tidak pernah dipakai untuk gating channel — mereka dipakai untuk hal lain
(kosmetik, atau gating fitur non-channel), jadi tidak muncul di matrix ini.

| Grup di matrix | Role Discord asli | Sumber kebenaran akses |
|---|---|---|
| **@everyone** | `@everyone` | Baseline, biasanya deny di channel privat |
| **Drifter** | `drifter` | Member gratis tanpa membership aktif |
| **Trial** | `trial` | Membership trial 5 hari |
| **Traveler** | `traveler` | Tier VIP termurah |
| **Companion** | `companion` | Tier VIP menengah (Traveler otomatis ikut lewat `TIER_ROLE_CHAIN` di `role_resolver.py`) |
| **Patron** | `patron` | Lifetime, tier VIP tertinggi |
| **Staff** | `royal_guard`, `prime_minister` | Moderator/admin operasional |
| **Admin** | Discord Administrator permission | Bypass total (`has_authorized_access`) |

---

## 2. SERVER INFO (read-only, staff yang posting)

Channel: `welcome-and-rules`, `announcements`, `channel-guide`, `join-log`

| Permission | @everyone | Staff |
|---|---|---|
| View Channel | ✅ | ✅ |
| Send Messages | ❌ | ✅ |
| Create Public Threads | ❌ | ✅ |
| Add Reactions | ✅ | ✅ |
| Read Message History | ✅ | ✅ |
| Attach Files / Embed Links | ❌ (`welcome-and-rules`, `announcements`) | ✅ |
| Manage Messages | ❌ | ✅ |

**`role-assign`** — pengecualian: butuh reaction untuk memilih faction
(`auto_receive_cog.py` on_raw_reaction_add):

| Permission | @everyone | Staff |
|---|---|---|
| View Channel | ✅ | ✅ |
| Send Messages | ❌ | ✅ |
| Add Reactions | ✅ | ✅ |

---

## 3. KOTABI SYSTEM

| Channel | View | Send | Catatan |
|---|---|---|---|
| `membership` | Semua ✅ | Staff only | Info tier + bank account, read-only untuk warga |
| `honor-board` | Semua ✅ | Staff only | Announcement kelulusan kasta, kneel leaderboard |
| `bot-commands` | Semua ✅ | Semua ✅ | Tempat mencoba slash command bebas |

---

## 4. JAPANESE AREA

| Channel | View | Interaksi | Catatan |
|---|---|---|---|
| `questions-forum` (ID `1527241425488707634`) | Semua ✅ | Create Posts + Send in Posts ✅ | ForumChannel, menggantikan `homework-help` (channel teks lama, sudah dihapus). Dipantau `thread_resolver_cog.py` (`/solved`, auto-reminder 48 jam, auto-archive 30 hari) |
| `jlpt-study-group` | Semua ✅ | Send + Create Threads ✅ | Gabungan dengan bekas `today-i-learned` |

---

## 5. COMMUNITY

Channel: `general`, `jp-general`, `off-topic`

| Permission | Semua role | Staff |
|---|---|---|
| View / Send / Create Threads / Reactions / Attach Files / Embed Links / External Emoji-Stiker | ✅ | ✅ |
| Mention @everyone/@here/roles | ❌ | ✅ |
| Manage Messages | ❌ | ✅ |

---

## 6. QUIZ HALL

### `quiz-public` (ForumChannel, di-rename dari `quiz-public-forum`)

Dipakai untuk latihan bebas (`practice_cog.py`) — siapa saja boleh
membuat post baru ("🎮 Mulai Latihan"), bukan cuma VIP.

| Permission | Semua role | Staff |
|---|---|---|
| View / Create Posts / Send in Posts / Reactions / Attach Files | ✅ | ✅ |
| Manage Threads/Posts | ❌ | ✅ (dipakai `quiz_forum_cog.py` auto-archive) |

### `quiz-rank-up`

Channel utama **dikunci total** — interaksi murni lewat dropdown
`DynamicQuizMenu`. Chat cuma boleh di bilik ujian (thread privat yang
dibuat bot lewat `create_thread()`; user tidak butuh permission "Create
Private Threads" karena ditambahkan manual lewat `thread.add_user()`).

| Permission | Trial–Patron | Drifter | Staff |
|---|---|---|---|
| View Channel | ✅ | ✅ (kuis `open_to_drifter`) | ✅ |
| Send Messages (channel utama) | ❌ | ❌ | ✅ |
| Send Messages in Threads | ✅ | ✅ | ✅ |
| Create Private Threads | ❌ | ❌ | ✅ (bot yang bikin bilik ujian) |

---

## 7. MEMBER LIBRARY (kamus — command-only)

Channel: `grammar-dic`, `kotoba-dic`, `kanji-dic`, `anime-sentences`

Per `shared/checks.has_dic_access()`: Trial dapat, **Traveler TIDAK
dapat**, Companion/Patron/Staff dapat. Semua respons command
(`/bunpou`, `/kotoba`, `/kanji`) berupa `ephemeral=True`, jadi chat biasa
di channel ini dikunci — tidak ada gunanya.

| Permission | Trial | Traveler | Companion | Patron | Staff |
|---|---|---|---|---|---|
| View Channel | ✅ | ❌ | ✅ | ✅ | ✅ |
| Send Messages | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## 8. MEMBER AREA

| Channel | Trial | Traveler | Companion | Patron | Catatan |
|---|---|---|---|---|---|
| `member-lounge` | ✅ | ❌ | ✅ | ✅ | Companion-exclusive |
| `immersion-log` | ✅ | ✅ | ✅ | ✅ | Semua tier VIP, dibatasi `is_valid_channel()` |
| `deck-requests` | ✅ | ❌ | ✅ | ✅ | Companion-exclusive, Attach Files ✅ |
| `immersion-race` | ✅ | ❌ | ✅ | ✅ | Companion-exclusive, Attach Files ✅ (screenshot progres) |

---

## 9. RESOURCES SHARING

| Channel | View | Send | Attach Files | Catatan |
|---|---|---|---|---|
| `notes-and-resources` | Semua ✅ | Semua ✅ | ✅ (inti fungsinya) | Staff: + Manage Messages untuk moderasi |

---

## 10. VOICE CHANNELS

| Channel | Akses | Catatan |
|---|---|---|
| `Lounge` | Semua ✅ | Voice publik statis, tidak ada overwrite khusus |
| `➕ Join to Create` (trigger) | Semua ✅ | Dikelola `voice_jtc_cog.py` — begitu join, langsung dipindah ke room baru |
| Room JTC yang dibuat otomatis | Pembuat + yang diundang | Lihat "Kontrol Pemilik Room" di bawah |
| `Staff Voice` (ID `1527247030680817694`) | @everyone ❌, Staff ✅ | Voice privat khusus Royal Guard/Prime Minister |

Voice channel selain `Staff Voice` tidak butuh overwrite di kode — cukup
diatur di level role Discord biasa (tabel "Voice Channel Permissions"
bawaan Discord).

### Kontrol Pemilik Room JTC (rename & user limit)

Begitu bot membuat room baru untuk seseorang, bot langsung memberi
overwrite permission **personal** (bukan role-wide) `manage_channels=True`
+ `move_members=True` khusus untuk channel itu dan khusus untuk pemiliknya
(diimplementasikan di `voice_jtc_cog.py`). Efeknya: pemilik room bisa
klik kanan channel-nya di Discord → Edit Channel → ganti nama atau atur
User Limit sendiri lewat UI native Discord, tanpa command bot. Overwrite
ini otomatis hilang begitu channel dihapus (saat kosong ditinggalkan).

---

## 11. STAFF

Channel: `staff-chat`, `order-review`

| Permission | @everyone | Staff |
|---|---|---|
| View Channel | ❌ | ✅ |
| Send Messages | ❌ | ✅ |
| Manage Messages | ❌ | ✅ |
| Mention @everyone/@here | ❌ | ✅ |

`order-review` menerima embed order dari `purchase_cog.py` + tombol
Approve/Reject — Staff juga diberi Attach Files/Embed Links untuk
menampilkan bukti transfer.

---

## 12. Riwayat Migrasi Channel

Dua channel di server ini pernah berganti nama/dibuat ulang — dicatat di
sini untuk konteks historis, bukan lagi rencana yang perlu dieksekusi:

- **`homework-help`** (channel teks) → dihapus, digantikan
  **`questions-forum`** (ForumChannel baru, ID `1527241425488707634`)
  supaya `thread_resolver_cog.py` (`/solved`, auto-archive) bisa aktif.
  Nama sengaja tidak dipertahankan sebagai `homework-help-forum` karena
  channel lama sudah dihapus total, tidak ada ambiguitas nama yang perlu
  dihindari.
- **`quiz-public-forum`** → di-rename jadi **`quiz-public`** (ID tetap
  sama). Referensi ke channel ini di kode memakai key `quiz_public` di
  `shared/server_map.yml`, dipakai oleh `practice_cog.py` dan
  `quiz_forum_cog.py`.

---

## 13. Lokasi Implementasi di Kode

| File | Peran |
|---|---|
| `features/server_admin/support/permission_table.py` | Sumber kebenaran tunggal — `CHANNEL_PERMISSIONS` (dict channel → role → permission) |
| `features/server_admin/support/permission_engine.py` | Engine generic yang menerjemahkan `CHANNEL_PERMISSIONS` jadi `discord.PermissionOverwrite` |
| `features/server_admin/permissions_cog.py` | Command `/permission restore\|restore_channel\|preview\|backup\|sync_roles` |
| `features/server_admin/structure_cog.py` | `STRUCTURE_BLUEPRINT` (kategori & posisi channel) + command `/structure setup\|preview` |
| `shared/server_map.yml` | ID channel & role aktual di Discord (key `questions_forum`, `quiz_public`, `staff_voice`, dst) |
| `features/gatekeeper/practice_cog.py`, `features/moderation/quiz_forum_cog.py` | Konsumen key `quiz_public` |
| `features/moderation/thread_resolver_settings.yml` | Daftar ID forum yang dipantau `thread_resolver_cog.py` (berisi `questions-forum`) |
| `features/social/voice_jtc_cog.py` | Kontrol pemilik room JTC (rename/user limit) |

**Skema data** (`CHANNEL_PERMISSIONS`):

```python
CHANNEL_PERMISSIONS: dict[str, dict[str, dict[str, bool]]] = {
    "nama-channel": {
        "role_key": {"permission_kwarg": True_atau_False, ...},
    },
}
```

Contoh nyata dari `quiz-rank-up` (channel utama dikunci, thread terbuka):

```python
"quiz-rank-up": {
    "everyone": {"view_channel": False, "send_messages": False},
    "trial":    {"view_channel": True, "send_messages": False, "send_messages_in_threads": True, "add_reactions": True},
    # ... traveler, companion, patron, drifter sama polanya
    "royal_guard": {"view_channel": True, "send_messages": True, "create_private_threads": True},
},
```

**Cara menambah/ubah permission channel di masa depan:**
1. Edit tabel di dokumen ini (bagian 2–11) sesuai kebutuhan baru.
2. Terjemahkan ke `CHANNEL_PERMISSIONS` di `permission_table.py`.
3. Jalankan `/permission sync_roles` untuk validasi, lalu `/permission
   preview` untuk cek dry-run, baru `/permission restore` untuk apply.

**`ROLE_KEYS_USED`** di `permission_table.py` diturunkan otomatis dari
`CHANNEL_PERMISSIONS` — tidak perlu diedit manual saat menambah role baru
ke tabel permission.
