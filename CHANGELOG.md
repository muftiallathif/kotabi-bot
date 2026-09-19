# CHANGELOG.md — Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** daftar kronologis perubahan signifikan,
> sebagai pointer cepat — SATU baris per perubahan
> **BUKAN sumber untuk:** detail/alasan perubahan (itu tugas dokumen
> topik masing-masing, bagian "Riwayat Perubahan Signifikan") — kalau
> ketemu baris di sini yang butuh konteks lebih, buka link-nya, jangan
> tambahkan detail di file ini
> **Terakhir diverifikasi terhadap kode:** 2026-07-21

Kalau kamu cuma butuh tau "ada perubahan apa aja baru-baru ini", cek
sini. Kalau butuh tau alasan/detail teknisnya, klik dokumen yang
ditunjuk. Lihat `DEVELOPMENT_GUIDE.md` bagian 13 untuk aturan kapan
suatu perubahan wajib dicatat di sini vs cukup di dokumen topiknya saja.

---

## 2026

- **19 Sep** — `MODERATION_SYSTEM.md` dibuat (belum pernah ada
  sebelumnya). Dibaca penuh 4 file `features/moderation/` + 2 config +
  `git log -p --follow` tiap file, plus cross-check eksplisit ke
  `rank_saver_cog.py` (social) dan `practice_cog.py` (gatekeeper) sesuai
  permintaan audit lintas-fitur. Ditemukan: `/solved` tanpa pengecekan
  otorisasi sama sekali (bisa dipalsukan lewat rename thread tanpa
  command); interaksi nyata `rank_saver_cog.py` ↔ `/selfmute` yang bisa
  membatalkan mute lewat leave-rejoin dalam window ≤10 menit —
  diklasifikasikan terpisah dari temuan role staff sebelumnya sebagai
  *moderation enforcement integrity* (bukan *authorization integrity*),
  walau root cause sama; race condition di `/sticky_last_message`.
  Klarifikasi: `allowed_ids` di `selfmute_settings.yml` mengatur siapa
  boleh memanggil `/selfmute`, bukan role mana yang boleh dipilih —
  koreksi atas kesimpulan awal di `COMMANDS.md`. `COMMANDS.md`/
  `DOCS_INDEX.md` diupdate. Documentation-only. Detail:
  `MODERATION_SYSTEM.md` §10.
- **19 Sep** — `SOCIAL_SYSTEM.md` §10 diperkuat lewat review kedua
  khusus `rank_saver_cog.py` (dibaca penuh + grep seluruh repo untuk
  `user_ranks`). Perubahan material: baris `user_ranks` dikonfirmasi
  tidak pernah dihapus di mana pun — masa eksposur snapshot basi TIDAK
  dibatasi 10 menit (cuma syarat *terjadinya* yang dibatasi window itu);
  ban→unban→rejoin dikonfirmasi juga memicu restorasi; koreksi framing
  "kick bypass ban" jadi "`on_member_join` tidak membedakan jenis
  rejoin"; root cause diklarifikasi lewat komentar kode asli
  (`role_ids_to_ignore` dirancang untuk role situasional, bukan exclude
  staff) — blacklist dicatat sebagai kandidat mitigasi, bukan solusi
  final. `COMMANDS.md`/`DOCS_INDEX.md` diselaraskan. Documentation-only,
  `rank_saver_cog.py` tidak diubah. Detail: `SOCIAL_SYSTEM.md` §10.
- **19 Sep** — `SOCIAL_SYSTEM.md` dibuat (belum pernah ada sebelumnya).
  Dibaca penuh 9 file `features/social/` + `git log -p --follow` tiap
  file, mencari pola "restriction UI tidak ditegakkan" sama seperti
  temuan `/log_stats`. Tidak ditemukan pola itu di 5 command
  (`/create_role` justru contoh yang benar menegakkan klaimnya, `/bookmarks`
  contoh pola ephemeral yang benar). Ditemukan 2 gap keamanan berbeda
  kelas: `rank_saver_cog.py` bisa mengembalikan role — termasuk role
  staff (`royal_guard`/`prime_minister`) — secara otomatis setelah
  sengaja dicabut, lewat window staleness kick/rejoin ≤10 menit
  (`role_ids_to_ignore` kosong sejak commit pertama); dan
  `/kneelderboard` membolehkan query leaderboard server Discord lain
  tanpa cek keanggotaan, hasil non-ephemeral. Keduanya belum diperbaiki,
  sengaja tidak disentuh (audit-only pass). `COMMANDS.md` diupdate
  dengan tanda ⚠️. Detail: `SOCIAL_SYSTEM.md` §14.
- **19 Sep** — `IMMERSION_SYSTEM.md` dibuat (belum pernah ada
  sebelumnya). Dibaca penuh `log_cog.py`, `goals_cog.py`, `stats_cog.py`,
  `bar_races_cog.py`, `support/`, dan `immersion_log_settings.yml`.
  Ditemukan gap keamanan/dokumentasi nyata: `/log_export`, `/logs`,
  `/log_stats` mengklaim "Khusus Staf" di UI tapi tidak ada pengecekan
  staff di kode — belum diperbaiki, sengaja tidak di-refactor. Juga
  ditemukan 1 bug format URL (`get_source_url()`, placeholder
  `{tmdb_media_type}` tidak ke-format saat lookup TMDB gagal) dan
  beberapa asimetri desain (backfill 7 hari vs undo tanpa batas usia;
  goal completion vs expiry tidak dibedakan saat `/log_clear_goals`).
  `COMMANDS.md` diupdate dengan tanda ⚠️ pada 3 command tsb. Detail:
  `IMMERSION_SYSTEM.md` §14.
- **19 Sep** — `COMMANDS.md` dibuat (belum pernah ada sebelumnya).
  Grep seluruh `features/*/*_cog.py`, 44 slash command + 4 command
  group (13 subcommand) + 5 prefix command diverifikasi satu-satu ke
  `async def` aslinya. Ditemukan: 12 dari 32 cog murni listener/
  background task tanpa command; banyak command admin ternyata gated
  `in-body` (bukan lewat decorator `shared/checks.py`), berisiko
  terlihat "terbuka" kalau cuma baca decorator. `DOCS_INDEX.md`
  ditambah bagian "Gap Terbuka" — 4 fitur (`immersion`, `social`,
  `moderation`, sebagian `server_admin`) belum punya dokumen topik,
  dan tidak ada folder `tests/` di repo. Detail: `COMMANDS.md`.
- **21 Jul** — Sistem harga tier VIP (Traveler/Companion/Patron)
  dirombak jadi single-source-of-truth lewat preset harga
  (`pricing_presets.yml`), termasuk varian 6 bulan/1 tahun otomatis.
  Detail: `PRICING_SYSTEM_REFACTOR.md`.
- **21 Jul** — Audit dead config/dead code menyeluruh: hapus
  `get_tier_info()` (nol caller), field `price_rp`/`points`/
  `duration_days`/`name` basi di `membership_settings.yml`, field
  `short_id` basi di `media_types.py`, properti `is_expired` basi di
  `MembershipRow`; tambah `Msg.AUTHORIZED_ONLY` yang sebelumnya hilang
  (bug lama). Detail: `PRICING_SYSTEM_REFACTOR.md` bagian 8.
- **21 Jul** — Restrukturisasi dokumentasi: `DEVELOPMENT_GUIDE.md`
  dapat protokol update MD baku (bagian 13); `MEMBERSHIP_FEATURE_GUIDE.md`
  + `KOTABI_MEMBERSHIP_SYSTEM_v3.md` + `MEMBERSHIP_STRATEGY_DECISIONS.md`
  digabung jadi `MEMBERSHIP_SYSTEM.md`; 3 panduan kamus digabung jadi
  `DICTIONARY_SYSTEM.md`. Detail: `DOCS_INDEX.md`.
- **21 Jul** — `MEMBERSHIP_SYSTEM.md` dibuat dari gabungan 3 dokumen
  membership lama. Ditemukan: 5 dari 5 "known issue" yang dicatat belum
  dikerjakan di dokumen lama ternyata sudah fixed di kode. Detail:
  `MEMBERSHIP_SYSTEM.md` bagian 8.
- **21 Jul** — `DICTIONARY_SYSTEM.md` dibuat dari gabungan 3 panduan
  kamus. Ditemukan: 10 dari 12 item checklist implementasi `/kanji`
  yang dicatat belum dikerjakan ternyata sudah selesai di kode. Detail:
  `DICTIONARY_SYSTEM.md` bagian 6.
- **21 Jul** — `DATABASE_SCHEMA.md` dibuat (belum pernah ada
  sebelumnya). ~20 tabel dikumpulkan dari 15 `cog_load()` + 3 file
  migration. Ditemukan potensi utang teknis: tabel `membership_history`
  lama belum terkonfirmasi ter-drop pasca migrasi ke `_v1`. Detail:
  `DATABASE_SCHEMA.md` bagian 9.
- **21 Jul** — `GATEKEEPER_QUIZ_SYSTEM.md` dan `DEPLOYMENT.md` dibuat
  (belum pernah ada sebelumnya). Ditemukan: `OPENAI_KEY` hilang dari
  `.env.example` dan `docker-compose.yml`; `docker-compose.yml` bukan
  jalur yang dipakai production (production pakai `docker run`
  langsung via GitHub Actions). Detail: `DEPLOYMENT.md` bagian 1-2.
  Restrukturisasi dokumentasi selesai — 8 dokumen aktif, 6 diarsipkan.
  Lihat `DOCS_INDEX.md`.
