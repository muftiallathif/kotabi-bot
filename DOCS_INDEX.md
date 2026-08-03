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
