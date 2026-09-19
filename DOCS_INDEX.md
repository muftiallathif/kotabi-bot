# DOCS_INDEX.md — Peta Dokumentasi Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** daftar semua dokumen MD project ini, status
> masing-masing, dan topik apa yang diaturnya
> **BUKAN sumber untuk:** isi/detail topik itu sendiri — dokumen ini cuma
> penunjuk arah
> **Terakhir diverifikasi terhadap kode:** 2026-07-21

Kalau ragu dokumen mana yang harus dibuka/diupdate untuk suatu
perubahan, cek tabel di bawah dulu sebelum nebak. Lihat
`DEVELOPMENT_GUIDE.md` bagian 13 untuk aturan lengkap cara
update dokumentasi.

---

## Dokumen Aktif (sumber kebenaran saat ini)

| File | Ngatur apa | Kapan buka |
|---|---|---|
| `KOTABI_SYSTEM_MAP.md` | **Sintesis sistem utuh** — Discord UX ↔ command ↔ fitur ↔ role ↔ database ↔ dependency lintas-fitur, gap/overlap/known-issue level sistem | Mau lihat gambaran besar Kotabi sebagai produk, bukan detail satu fitur — mulai dari sini sebelum ke dokumen topik |
| `DEVELOPMENT_GUIDE.md` | Konvensi struktur folder/kode, aturan penamaan, checklist push, checklist ubah config yang berdampak user aktif, **protokol update dokumentasi** | Mau nambah/edit fitur apa pun; bingung dokumen mana yang relevan |
| `COMMANDS.md` | Daftar lengkap semua slash command & prefix command lintas-fitur — parameter, level akses (decorator + in-body check), lokasi file, plus cog yang tidak punya command sama sekali | Mau tau command apa saja yang ada, siapa yang boleh pakai, atau cari lokasi kode command tertentu |
| `IMMERSION_SYSTEM.md` | Mekanisme `/log`, achievement, goal, statistik, bar chart race, cache autocomplete AniList/VNDB/TMDB | Mau ubah poin/achievement/goal, atau debug fitur immersion apa pun |
| `SOCIAL_SYSTEM.md` | Mekanisme `/info`, `/kneelderboard`, `/bookmarks`, `/create_role`, auto-role, voice join-to-create, pertanyaan harian AI, role event, snapshot/restore role | Mau ubah fitur social apa pun, atau debug kenapa role balik sendiri setelah dicabut |
| `MODERATION_SYSTEM.md` | Mekanisme `/solved`, `/selfmute`, `/unmute_user`, `/sticky_last_message`, auto-archive thread, interaksi dengan `rank_saver_cog.py` | Mau ubah fitur moderation apa pun, atau debug kenapa mute bisa batal sendiri |
| `SERVER_ADMIN_SYSTEM.md` | Mekanisme `/backup_database`, `/backup_discord_server`, `/say` — rantai otorisasi lengkap tiap command | Mau ubah fitur backup/say, atau cek siapa sebenarnya bisa akses backup database |
| `tests/README.md` | Cara kerja regression harness (Level A/B/C), status test per finding keamanan | Mau jalankan/tambah test, atau cek finding mana yang sudah punya reproduction test |
| `PERMISSION_MATRIX.md` | Permission channel & role lintas-fitur (siapa bisa lihat/kirim di channel mana) | Mau ubah akses channel, role baru, atau `/permission`/`/structure` |
| `MEMBERSHIP_SYSTEM.md` | Alur `/subscribe`, anti-fraud bukti transfer, command admin, scheduler, skema tabel membership, cara nambah produk, keputusan strategi final | Mau ubah alur pembelian, tier, admin command membership |
| `PRICING_SYSTEM_REFACTOR.md` | Harga tier VIP (Traveler/Companion/Patron + varian 6bln/1thn), cara ganti harga lewat preset, riwayat audit dead config | Mau ganti harga, nambah/ubah preset, atau cari tau kenapa suatu field harga dihapus |
| `DICTIONARY_SYSTEM.md` | Arsitektur `/bunpou` `/kotoba` `/kanji` — skema field, pipeline render HTML/furigana, gating akses, pola tambah entri baru | Mau tambah/ubah entri kamus, atau ubah cara render command dictionary |
| `DATABASE_SCHEMA.md` | Semua tabel SQLite, di mana dibuat (`cog_load()` mana), migration files | Mau nambah tabel baru, debug data, atau cari tau tabel apa dipakai fitur apa |
| `GATEKEEPER_QUIZ_SYSTEM.md` | Sistem kuis kasta — cooldown, anti-cheat, journey/roadmap, combination rank | Mau ubah aturan kuis, cooldown, atau alur kenaikan kasta |
| `DEPLOYMENT.md` | Env var yang dibutuhkan, Docker, GitHub Actions self-hosted runner | Mau deploy ulang, pindah VPS, atau ada env var yang error |
| `CHANGELOG.md` | Log pointer super ringkas — cuma tanggal + 1 kalimat + link ke dokumen topik | Mau tau "apa yang berubah baru-baru ini" secara cepat |

---

## Dokumen Arsip (jangan dipakai acuan, dibiarkan sebagai histori)

| File lama | Status | Diganti oleh |
|---|---|---|
| `MEMBERSHIP_FEATURE_GUIDE.md` | Arsip | `MEMBERSHIP_SYSTEM.md` |
| `KOTABI_MEMBERSHIP_SYSTEM_v3.md` | Arsip | `MEMBERSHIP_SYSTEM.md` |
| `MEMBERSHIP_STRATEGY_DECISIONS.md` | Arsip | `MEMBERSHIP_SYSTEM.md` (bagian keputusan strategi) |
| `panduan-kamus-grammar-versi-ringkas.md` | Arsip | `DICTIONARY_SYSTEM.md` |
| `panduan-kamus-kotoba-versi-ringkas.md` | Arsip | `DICTIONARY_SYSTEM.md` |
| `panduan-kamus-kanji-versi-ringkas.md` | Arsip | `DICTIONARY_SYSTEM.md` |

**Kenapa tidak langsung dihapus fisik:** isinya masih dipakai sebagai
bahan sumber saat menyusun dokumen pengganti (lihat catatan status
progres di bawah). Setelah semua dokumen pengganti final & terverifikasi
lengkap, file-file arsip ini boleh dihapus betulan dari repo — bukan
cuma diklaim dihapus di dokumen lain (pelajaran dari
`MEMBERSHIP_FEATURE_GUIDE.md` yang sempat bilang
`MEMBERSHIP_STRATEGY_DECISIONS.md` "sudah dihapus" padahal filenya
masih ada).

---

## Status Penyusunan (selesai per 2026-07-21)

| Dokumen | Status |
|---|---|
| `DEVELOPMENT_GUIDE.md` (update bagian 13) | ✅ Selesai |
| `DOCS_INDEX.md` (file ini) | ✅ Selesai |
| `CHANGELOG.md` | ✅ Selesai |
| `MEMBERSHIP_SYSTEM.md` | ✅ Selesai |
| `DICTIONARY_SYSTEM.md` | ✅ Selesai |
| `DATABASE_SCHEMA.md` | ✅ Selesai |
| `GATEKEEPER_QUIZ_SYSTEM.md` | ✅ Selesai |
| `DEPLOYMENT.md` | ✅ Selesai |

Sekarang file arsip di atas boleh dihapus fisik dari repo kalau sudah
yakin dokumen penggantinya lengkap — jangan cuma diklaim dihapus di
tempat lain (lihat alasan di atas).

---

## Gap Terbuka (ditemukan lewat audit 2026-09-19, belum dikerjakan)

**Update 19 Sep:** `IMMERSION_SYSTEM.md`, `SOCIAL_SYSTEM.md`,
`MODERATION_SYSTEM.md`, dan `SERVER_ADMIN_SYSTEM.md` sudah dibuat
(lihat tabel di atas) — semua fitur (`dictionary`, `gatekeeper`,
`membership`, `immersion`, `social`, `moderation`, `server_admin`,
`system`) sekarang punya dokumen topik. Keempat audit menemukan gap
keamanan/dokumentasi nyata yang **belum diperbaiki** (sengaja, lihat
prinsip audit→document→classify→decide→fix→test):

- ⚠️⚠️ **`/backup_database` mengalami REGRESI keamanan** — commit
  `bb3b698` mengganti pengecekan permission yang tadinya ditegakkan
  backend (`has_permissions(administrator=True)`) jadi cuma saran
  sisi-client (`default_permissions`) tanpa backstop apa pun. Sekarang
  siapa pun bisa mengekspor SELURUH database (termasuk bukti
  pembayaran, riwayat membership, aktivitas semua user) kalau admin
  guild kebetulan melonggarkan Integration setting. **Temuan paling
  serius di seluruh rangkaian audit ini.** —
  `SERVER_ADMIN_SYSTEM.md` §2, §8.
- `/say` (server_admin) — parameter `channel` di keempat subcommand
  memungkinkan permission laundering: permission staff pemanggil di
  channel target tidak pernah dicek — `SERVER_ADMIN_SYSTEM.md` §4.4, §8.

- 3 command immersion (`log_export`, `logs`, `log_stats`) mengklaim
  "Khusus Staf" di UI tapi tidak ditegakkan di kode —
  `IMMERSION_SYSTEM.md` §14.
- `rank_saver_cog.py` (social) bisa mengembalikan role — termasuk role
  staff — secara otomatis setelah sengaja dicabut; masa eksposurnya
  TIDAK dibatasi 10 menit (baris DB tidak pernah dihapus), berlaku juga
  untuk rejoin setelah ban→unban — `SOCIAL_SYSTEM.md` §10, §14.
- `/kneelderboard` (social) membolehkan query leaderboard server
  Discord lain tanpa cek keanggotaan — `SOCIAL_SYSTEM.md` §3, §14.
- `/solved` (moderation) tidak punya pengecekan otorisasi sama sekali,
  dan bisa dipalsukan lewat rename thread tanpa command —
  `MODERATION_SYSTEM.md` §2, §10.
- **`rank_saver_cog.py` juga bisa membatalkan `/selfmute`** lewat
  leave-rejoin dalam window ≤10 menit — root cause sama dengan temuan
  role staff di atas, tapi diklasifikasikan terpisah sebagai
  *moderation enforcement integrity* (bukan *authorization integrity*)
  karena dampaknya berbeda (membatalkan sanksi, bukan memulihkan
  privilege) — `MODERATION_SYSTEM.md` §4, §10.

**Sisa gap non-dokumentasi (bukan "fitur belum diaudit", tapi utang
teknis lain yang sudah ketahuan sepanjang audit):**

- **`system/`** (`sync_cog.py`, `watchdog_cog.py`) — belum diputuskan
  perlu `SYSTEM_SYSTEM.md` sendiri atau cukup masuk
  `DEVELOPMENT_GUIDE.md`/`DEPLOYMENT.md` (folder ini kecil, prefix
  command saja, bukan slash command — lihat `COMMANDS.md` §8).
- **Role sistem** (faction, achievement, leveling di
  `shared/server_map.yml`) belum punya dokumen konsolidasi —
  `PERMISSION_MATRIX.md` §1 secara eksplisit mengecualikannya karena
  tidak dipakai gating channel.
- ~~**Tidak ada folder `tests/`** di repo~~ — **update 19 Sep:**
  `tests/` dibuat, vertical slice pertama (`/backup_database`, finding
  paling serius) sudah jalan sebagai regression test — lihat
  `tests/README.md`. 6 finding lain masih menunggu test-nya masing-
  masing (2 di antaranya, `rank_saver` & `/kneelderboard`, menunggu
  keputusan desain dulu sebelum bisa ditulis — lihat status table di
  `tests/README.md`).

Keputusan yang belum diambil: apakah `system/` butuh 1 MD sendiri, atau
cukup digabung ke dokumen lain — perlu dievaluasi, bukan otomatis
1 folder = 1 file.
