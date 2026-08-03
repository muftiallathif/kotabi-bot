# DEPLOYMENT.md — Deployment Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** environment variable yang dibutuhkan,
> struktur Docker image, alur CI/CD, dependency sistem non-Python
> **BUKAN sumber untuk:** konfigurasi fitur (role ID, channel ID, harga
> — semua itu di `.yml` masing-masing fitur, bukan env var)
> **Terakhir diverifikasi terhadap kode:** 2026-07-21

**Dokumen ini baru.** Disusun dari `Dockerfile`, `docker-compose.yml`,
`.env.example`, `.github/workflows/main.yml`, `requirements.txt`.

---

## 1. ⚠️ Gap yang Ditemukan Saat Audit

**`.env.example` dan `docker-compose.yml` sama-sama tidak lengkap**
dibanding apa yang production sebenarnya butuhkan (lihat bagian 3):

| Env var | Ada di `.env.example`? | Ada di `docker-compose.yml`? | Ada di GitHub Actions (`main.yml`)? |
|---|---|---|---|
| `OPENAI_KEY` | ❌ **Tidak ada sama sekali** | ❌ **Tidak ada sama sekali** | ✅ Ada (`secrets.OPENAI_KEY`) |
| `TMDB_API_KEY` | ✅ Ada | ✅ Ada | ✅ Ada (`secrets.TMDB_API_KEY`) |

`OPENAI_KEY` dipakai `features/social/daily_question_cog.py` (generate
pertanyaan harian AI). Kalau ada yang coba jalanin bot dari
`docker-compose.yml` atau ngikutin `.env.example` apa adanya tanpa tau
soal `OPENAI_KEY`, fitur pertanyaan harian bakal diam-diam nonaktif
(cog-nya sendiri sudah fail-safe — lihat bagian 4 — tapi tetap
membingungkan kalau tidak didokumentasikan).

**Rekomendasi:** tambahkan `OPENAI_KEY=key` ke `.env.example`, dan
`- OPENAI_KEY` ke `environment:` di `docker-compose.yml`.

---

## 2. Dua Jalur Deployment yang Berbeda (Penting)

**Production TIDAK memakai `docker-compose.yml`.** GitHub Actions
(self-hosted runner) menjalankan `docker run` langsung dengan flag
`--env` eksplisit (lihat bagian 3). `docker-compose.yml` sepertinya
disiapkan untuk kebutuhan lokal/manual, bukan jalur yang benar-benar
dipakai VPS produksi — makanya bisa beda isi tanpa ketahuan (seperti
gap `OPENAI_KEY` di atas).

| | `docker-compose.yml` | `.github/workflows/main.yml` (production) |
|---|---|---|
| Trigger | Manual (`docker compose up`) | Otomatis, setiap push ke `main` |
| Lokasi data | `./data:/app/data` (relatif ke lokasi compose file) | `/usr/src/kotabi_bot/data` (absolut, path tetap di VPS) |
| Env var lengkap? | Tidak (lihat bagian 1) | Ya |

Kalau mengubah salah satu, **cek juga yang satunya** supaya tidak makin
divergen.

---

## 3. Environment Variable

### Wajib (bot tidak akan jalan tanpa ini)

| Var | Fungsi | Sumber di production |
|---|---|---|
| `TOKEN` | Token bot Discord | GitHub Secrets |
| `COMMAND_PREFIX` | Prefix command teks lama (`%`) — command modern pakai slash command, prefix ini cuma untuk command admin/debug seperti `%sync_guild`, `%watchdog_status` | GitHub Variables |
| `PATH_TO_DB` | Path file SQLite (`data/db.sqlite3`) | GitHub Variables |
| `AUTHORIZED_USERS` | Daftar Discord user ID (koma-separated) dengan akses penuh (`has_authorized_access()`) | GitHub Variables |

### Dibutuhkan fitur tertentu (bot tetap jalan tanpa ini, tapi fitur terkait nonaktif/error)

| Var | Fitur yang butuh | Kalau kosong |
|---|---|---|
| `TMDB_API_KEY` | Autocomplete Listening Time (`immersion/support/autocomplete/tmdb.py`) | `ValueError` saat autocomplete dipanggil (bukan fail-safe diam-diam — lihat bagian 4) |
| `OPENAI_KEY` | Daily question AI (`daily_question_cog.py`) | Fail-safe: task tidak dijalankan sama sekali, warning di log |
| `DEBUG_USER` | Watchdog & gatekeeper circuit breaker kirim DM alert ke user ini | Alert tidak terkirim, cuma masuk log biasa |

### Opsional — override path config (semua punya default, jarang perlu diisi)

Pola `ALT_*_PATH` dipakai beberapa fitur supaya path config bisa
dioverride tanpa ubah kode — **hanya perlu diisi kalau memang mau
pindah lokasi file dari default**:

`ALT_GATEKEEPER_SETTINGS_PATH`, `ALT_PRODUCTS_PATH`, `ALT_BUNPOU_CSV_PATH`,
`ALT_KOTOBA_CSV_PATH`, `ALT_KANJI_CSV_PATH`, `ALT_KANJI_MEANINGS_ID_CSV_PATH`,
`ALT_SELFMUTE_SETTINGS_PATH`, `ALT_THREAD_RESOLVER_SETTINGS`,
`ALT_RANKSAVER_SETTINGS_PATH`, `IMMERSION_LOG_SETTINGS`,
`DAILY_QUESTIONS_SETTINGS_PATH`

### Opsional — tuning perilaku

| Var | Default | Fungsi |
|---|---|---|
| `WATCHDOG_AUTO_LOAD_NEW_COGS` | `false` | `true` = file `*_cog.py` baru otomatis dimuat tanpa restart. Default sengaja `false` — lihat `DEVELOPMENT_GUIDE.md` bagian 6 |
| `QUIZ_THREAD_INACTIVE_DAYS` | `3` | Berapa hari thread forum `quiz-public` tidak aktif sebelum di-archive |
| `QUIZ_FORUM_SCAN_INTERVAL_HOURS` | `1` | Interval cek thread tidak aktif |

---

## 4. Fail-Safe vs Tidak Fail-Safe (penting saat debug env var hilang)

Tidak semua kode di project ini menangani env var kosong dengan cara
yang sama — perlu tau bedanya supaya tidak salah tebak gejala error:

- **Fail-safe (log warning, fitur nonaktif diam-diam):** kebanyakan
  `ALT_*_PATH` loader (`gatekeeper_settings.yml`, `products.yml`, CSV
  kamus dst) — kalau file tidak ketemu, warning di log, dict/list
  kosong dipakai, bot tetap start.
- **TIDAK fail-safe (`ValueError` / crash saat dipanggil):**
  `tmdb.py` `query_tmdb()` — `raise ValueError("TMDB API Key not found...")`
  kalau `TMDB_API_KEY` kosong. Bot tetap start (errornya baru muncul
  pas user coba autocomplete Listening Time), tapi bukan silent seperti
  yang lain.

---

## 5. Dependency Sistem Non-Python (`Dockerfile`)

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk ffmpeg
COPY fonts/NotoEmoji-VariableFont_wght.ttf /usr/share/fonts/NotoEmoji-VariableFont_wght.ttf
```

- **`fonts-noto-cjk`** — wajib untuk render karakter Jepang di grafik
  `matplotlib` (`stats_cog.py` bar chart & heatmap immersion,
  `bar_races_cog.py`). Tanpa ini, teks Jepang di grafik akan muncul
  sebagai kotak putus-putus (tofu boxes).
- **`fonts-noto-cjk` + font emoji custom** — `bar_races_cog.py`
  `set_fonts()` mencari font Jepang (`Noto Sans CJK JP` dst) dan font
  emoji (`Noto Emoji`) secara eksplisit lewat `matplotlib.font_manager`,
  fallback ke `sans-serif` kalau tidak ketemu — animasi bar chart race
  bisa jalan tanpa font ini, tapi karakter Jepang/emoji di dalamnya
  tidak akan tampil benar.
- **`ffmpeg`** — dibutuhkan `bar_chart_race` untuk render output video
  `.mp4` (`/log_race`).

Kalau membangun ulang image dari awal di lingkungan berbeda (bukan lewat
`main.yml` yang sudah teruji), pastikan dua dependency sistem ini tetap
ada — gejalanya kalau hilang tidak langsung crash, cuma output visual
yang rusak/kosong.

---

## 6. Alur CI/CD (`.github/workflows/main.yml`)

```
Push ke branch main (atau trigger manual)
    ↓
Checkout code
    ↓
Stop & remove container lama (docker stop/rm, || true supaya tidak gagal kalau belum ada)
    ↓
docker build -t discord-kotabi-bot .
    ↓
docker run -d dengan bind mount data + semua env var (lihat bagian 3)
    ↓
docker image prune -f (bersihkan image lama yang tidak terpakai)
```

Berjalan di **self-hosted runner** — artinya jalan langsung di VPS,
bukan runner cloud GitHub. Konsekuensi: **push ke `main` = langsung
deploy ke production**, tidak ada staging otomatis di alur ini. Lihat
`DEVELOPMENT_GUIDE.md` bagian 7 untuk checklist sebelum push.

Volume data di-bind mount dari `/usr/src/kotabi_bot/data` di VPS ke
`/app/data` di container — inilah yang membuat `data/db.sqlite3` tetap
aman meskipun container dihapus & dibuat ulang tiap deploy.

---

## Riwayat Perubahan Signifikan

- **2026-07-21** — Dibuat dari nol. Ditemukan: `OPENAI_KEY` hilang dari
  `.env.example` dan `docker-compose.yml` (ada di GitHub Actions),
  serta dikonfirmasi `docker-compose.yml` bukan jalur yang dipakai
  production sebenarnya (production pakai `docker run` langsung via
  GitHub Actions).
