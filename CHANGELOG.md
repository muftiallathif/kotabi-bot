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
