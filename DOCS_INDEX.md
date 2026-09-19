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
| `DEVELOPMENT_GUIDE.md` | Konvensi struktur folder/kode, aturan penamaan, checklist push, checklist ubah config yang berdampak user aktif, **protokol update dokumentasi** | Mau nambah/edit fitur apa pun; bingung dokumen mana yang relevan |
| `COMMANDS.md` | Daftar lengkap semua slash command & prefix command lintas-fitur — parameter, level akses (decorator + in-body check), lokasi file, plus cog yang tidak punya command sama sekali | Mau tau command apa saja yang ada, siapa yang boleh pakai, atau cari lokasi kode command tertentu |
| `IMMERSION_SYSTEM.md` | Mekanisme `/log`, achievement, goal, statistik, bar chart race, cache autocomplete AniList/VNDB/TMDB | Mau ubah poin/achievement/goal, atau debug fitur immersion apa pun |
| `SOCIAL_SYSTEM.md` | Mekanisme `/info`, `/kneelderboard`, `/bookmarks`, `/create_role`, auto-role, voice join-to-create, pertanyaan harian AI, role event, snapshot/restore role | Mau ubah fitur social apa pun, atau debug kenapa role balik sendiri setelah dicabut |
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

**Update 19 Sep:** `IMMERSION_SYSTEM.md` dan `SOCIAL_SYSTEM.md` sudah
dibuat (lihat tabel di atas) — dicoret dari daftar di bawah. Kedua audit
menemukan gap keamanan/dokumentasi nyata yang **belum diperbaiki**
(sengaja, lihat prinsip audit→document→classify→decide→fix→test):

- 3 command immersion (`log_export`, `logs`, `log_stats`) mengklaim
  "Khusus Staf" di UI tapi tidak ditegakkan di kode —
  `IMMERSION_SYSTEM.md` §14.
- `rank_saver_cog.py` (social) bisa mengembalikan role — termasuk role
  staff — secara otomatis setelah sengaja dicabut; masa eksposurnya
  TIDAK dibatasi 10 menit (baris DB tidak pernah dihapus), berlaku juga
  untuk rejoin setelah ban→unban — `SOCIAL_SYSTEM.md` §10, §14.
- `/kneelderboard` (social) membolehkan query leaderboard server
  Discord lain tanpa cek keanggotaan — `SOCIAL_SYSTEM.md` §3, §14.

Fitur berikut **masih belum punya dokumen topik sama sekali** — cuma
terdokumentasi sebagian lewat `COMMANDS.md` (daftar command-nya saja,
bukan business logic) atau tersebar di komentar kode:

- **Moderation** (`features/moderation/`) — 6 command + 1 cog background
  (`quiz_forum_cog.py`), tidak ada `MODERATION_SYSTEM.md`.
- **Server Admin** non-permission (`backup_database_cog.py`,
  `backup_discord_cog.py`, `say_cog.py`) — bagian permission/structure
  sudah tercakup `PERMISSION_MATRIX.md`, tapi fungsi backup & `/say`
  belum.

Juga ditemukan: **role sistem** (faction, achievement, leveling di
`shared/server_map.yml`) belum punya dokumen konsolidasi — `PERMISSION_MATRIX.md`
§1 secara eksplisit mengecualikannya karena tidak dipakai gating
channel, dan **tidak ada folder `tests/`** di repo — bukan gap
dokumentasi, tapi gap pengujian otomatis.

Keputusan yang belum diambil: apakah tiap folder yang kosong butuh 1 MD
sendiri, atau sebagian cukup digabung/masuk dokumen lain (mis. `system/`
kemungkinan lebih cocok masuk `DEVELOPMENT_GUIDE.md`/`DEPLOYMENT.md`
daripada `SYSTEM_SYSTEM.md` terpisah) — perlu dievaluasi per-fitur,
bukan otomatis 1 folder = 1 file.
