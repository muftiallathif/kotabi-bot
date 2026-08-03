# GATEKEEPER_QUIZ_SYSTEM.md — Sistem Kuis Kasta Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** alur kenaikan kasta, anti-cheat verifikasi
> kuis, sistem cooldown, journey/roadmap kasta, perbedaan quiz-rank-up
> vs quiz-public
> **BUKAN sumber untuk:** permission channel `quiz-rank-up`/`quiz-public`
> (lihat `PERMISSION_MATRIX.md` bagian 6), gating VIP untuk kuis
> tertentu (lihat `MEMBERSHIP_SYSTEM.md` bagian 3)
> **Terakhir diverifikasi terhadap kode:** 2026-07-21

**Dokumen ini baru** — sebelumnya sistem ini cuma didokumentasikan lewat
komentar tersebar di 5 file (`gatekeeper_cog.py`, `practice_cog.py`,
`journey_service.py`, `journey_models.py`, `journey_rules.py`).

---

## 1. Dua Sistem yang Terpisah Total (Penting)

Server punya **dua** tempat orang bisa ngerjain kuis Bahasa Jepang, dan
keduanya **tidak saling mempengaruhi**:

| | `quiz-rank-up` (kuis resmi) | `quiz-public` forum (latihan bebas) |
|---|---|---|
| Menaikkan kasta? | **Ya** | **Tidak, sama sekali** |
| Siapa yang bisa lihat thread? | Cuma pemilik bilik ujian | Publik, siapa saja boleh join |
| Cog yang menangani | `gatekeeper_cog.py` (`LevelUp`) | `practice_cog.py` (`PracticeThreads`) |
| Tabel thread | `user_threads` | `practice_threads` |
| Diproses `level_up_routine()`? | Ya | **Tidak** — dijaga channel guard eksplisit |
| Kena cooldown/timeout kalau salah format? | Ya | Tidak |

**Channel guard di `level_up_routine()`** (listener `on_message`) adalah
satu-satunya yang mencegah campur aduk dua sistem ini:

```python
quiz_rank_up_channel_id = get_channel_id(message.guild.id, "quiz_rank_up")
is_exam_thread = await self.bot.GET_ONE(
    "SELECT 1 FROM user_threads WHERE thread_id = ?;", (message.channel.id,)
)
if message.channel.id != quiz_rank_up_channel_id and not is_exam_thread:
    return
```

Kalau ada perubahan yang menyentuh salah satu sistem, **selalu cek**
apakah guard ini masih benar — kalau bocor, latihan bebas bisa
kepicu notice "belum berhasil"/kena cooldown, atau lebih parah, bisa
memicu kenaikan kasta yang tidak seharusnya.

---

## 2. Struktur Data Kuis (`gatekeeper_settings.yml`)

Setiap entri di `rank_structure` (per `guild_id`) adalah satu kuis
kasta. Field penting:

| Field | Fungsi |
|---|---|
| `name` | Nama tampilan kasta (mis. `【N5・従男爵】Baronet`) |
| `open_to_drifter` | `true` = Drifter (non-VIP) boleh ambil kuis ini juga |
| `require_role` | Role ID (atau list) yang wajib dimiliki sebelum kuis ini terbuka — biasanya kasta di bawahnya |
| `combination_rank` | `true` = kasta gabungan, didapat dari kombinasi beberapa kuis lain (lihat bagian 5), bukan dari kuis Kotoba langsung |
| `quizzes_required` | Khusus `combination_rank: true` — daftar nama kuis yang harus lulus semua |
| `rank_to_get` | Role ID yang diberikan kalau lulus |
| `command` | Perintah persis Bot Kotoba yang harus dikirim user |
| `deck_range`, `decks`, `score_limit`, `max_missed`, `time_limit`, `font`, `font_size`, `foreground`, `effect` | Parameter yang dicocokkan ke hasil API Kotoba saat verifikasi (bagian 4) |
| `no_timeout` | `true` = tidak ada cooldown mingguan (dipakai untuk kasta dasar yang sengaja bisa diulang bebas, mis. Commoner/Knight) |
| `emoji` | Emoji di dropdown menu kuis |

**Catatan:** per audit `DICTIONARY_SYSTEM.md`/`MEMBERSHIP_SYSTEM.md`,
`combination_rank`/`quizzes_required` **sudah siap dipakai di kode**
tapi saat ini **tidak ada satupun entri** di `gatekeeper_settings.yml`
dengan `combination_rank: true` — bukan bug, cuma belum ada data yang
memanfaatkannya.

---

## 3. Alur Kenaikan Kasta

```
User klik dropdown DynamicQuizMenu di #quiz-rank-up
    ↓
Cek VIP (kecuali kuis ini open_to_drifter) + cek cooldown
    ↓
Bot buat/pakai ulang bilik ujian privat (Thread, user_threads)
— Bot Kotoba (ID hardcode 251239170058616833) ditambahkan ke thread
    ↓
User salin-tempel command persis dari bot ke thread
    ↓
User jalankan kuis lewat Bot Kotoba
    ↓
Bot Kotoba post embed hasil ("Ended") di thread
    ↓
level_up_routine() (listener on_message) tangkap embed itu
    ↓
Ekstrak quiz_id dari embed → fetch hasil lengkap dari Kotoba API
(retry dengan backoff 2s/4s, replikasi terhadap rate limit 429)
    ↓
IDEMPOTENCY CHECK: quiz_id sudah pernah diproses? (processed_quiz_reports)
    ↓
LOCK per (guild_id, user_id) — cegah race condition
    ↓
verify_quiz_settings() — anti-cheat (bagian 4)
    ↓
Lulus → reward_user() + embed reward + DM        Gagal → catat attempt + embed failure + DM
    ↓                                                          ↓
Cek combination_rank yang mungkin ikut terpenuhi      Cooldown mulai berlaku
```

---

## 4. Anti-Cheat: `verify_quiz_settings()`

Memverifikasi hasil API Kotoba **ketat** terhadap parameter yang
didefinisikan di `gatekeeper_settings.yml`, supaya user tidak bisa
mengelabui dengan setting kuis yang lebih mudah. Dicek satu-satu, gagal
di cek pertama langsung return `False` + alasan:

1. **Jumlah peserta** — harus tepat 1 (bukan multiplayer, cegah joki)
2. **Shuffle harus aktif** — kalau mati, ditolak
3. **Deck tidak boleh sudah ter-load sebelumnya** (`isLoaded`)
4. **Tipe kuis tidak boleh multiple choice**
5. **Index deck** (`startIndex`/`endIndex`) harus cocok persis kalau
   `deck_range` didefinisikan; kalau `deck_range` tidak didefinisikan,
   deck **tidak boleh** pakai index sama sekali
6. **Warna font, efek, jumlah soal, batas waktu, jenis font, ukuran
   font** — semua dicocokkan ke parameter yang ditentukan (kalau
   didefinisikan)
7. **Jumlah salah** harus di bawah `max_missed`
8. **Skor benar** harus sama persis dengan `score_limit`

**Circuit breaker** (`_track_verify_result()`): window bergulir 20
hasil verifikasi terakhir. Kalau fail rate ≥ 85% (minimal 10 sampel),
kirim DM alert ke `DEBUG_USER` — sinyal kemungkinan format API Kotoba
berubah atau ada bug di `verify_quiz_settings`, bukan otomatis diasumsikan
lonjakan kecurangan riil. Cooldown alert 60 menit supaya tidak spam.

---

## 5. Kasta Gabungan (`combination_rank`)

Kasta yang didapat dari kombinasi beberapa kuis lain, bukan dari 1 kuis
Kotoba langsung. `check_if_combination_rank_earned()` dipanggil setiap
kali user lulus kuis biasa (bukan combination) — cek semua
`combination_rank: true` di `rank_structure`, kalau semua
`quizzes_required` sudah ada di `passed_quizzes` milik user, otomatis
diberikan (lewat `reward_user()` juga, tanpa perlu verifikasi kuis
tambahan). **Saat ini tidak ada data yang memakai fitur ini** — lihat
catatan di bagian 2.

---

## 6. Sistem Cooldown

**Beda antara VIP dan Drifter** (`journey_rules.py`
`get_cooldown_release_time()`):

- **VIP** — sampai Minggu tengah malam UTC berikutnya
  (`get_next_sunday_midnight()`). Bisa kurang dari 7 hari kalau gagal
  di awal minggu.
- **Non-VIP (Drifter)** — tetap 7 hari penuh dari waktu gagal, lebih
  predictable tapi lebih lambat dibanding VIP.

`no_timeout: true` di suatu kuis (mis. Commoner, Knight) membuat kuis
itu **selalu tersedia**, tidak kena aturan cooldown sama sekali.

**Satu-satunya sumber logika ini**: `journey_rules.py`
`get_next_sunday_midnight()` dan `get_cooldown_release_time()`. Dipakai
identik oleh `gatekeeper_cog.py` (`is_on_cooldown`,
`is_on_cooldown_create`, `register_quiz_attempt`) **dan**
`journey_service.py`. Kalau aturan cooldown berubah, cukup ubah di 2
fungsi ini — jangan duplikasi logic tanggal di tempat lain.

---

## 7. Journey System (`/journey`, `/my_next_action`)

Facade (`JourneyService`) yang orkestrasi `journey_queries.py` (baca DB)
+ `journey_rules.py` (business logic murni, tidak ada DB/Discord —
paling mudah di-unit-test) untuk menjawab "kasta apa saja yang tersedia
buat user ini sekarang, dan apa langkah berikutnya".

### Status ketersediaan kuis (`QuizAvailability`)

| Status | Arti |
|---|---|
| `PASSED` | Sudah lulus |
| `AVAILABLE` | Bisa diambil sekarang |
| `ON_COOLDOWN` | Lulus... eh, gagal, masih cooldown |
| `LOCKED` | `require_role` belum terpenuhi (atau kuis bukan `open_to_drifter` buat Drifter) |
| `NO_TIMEOUT` | Kuis tanpa cooldown, selalu tersedia |

### Prioritas `NextAction` (`calculate_next_action()`)

1. Ada kuis `AVAILABLE`? → `TAKE_QUIZ`, ambil yang pertama sesuai
   urutan `rank_structure` (representasi urutan progression)
2. Semua lagi cooldown? → `WAIT`, ambil yang paling cepat selesai
3. Ada yang `LOCKED`? → `LOCKED`, tampilkan role yang kurang
4. Semua sudah lulus → `COMPLETE`

### Riwayat & fallback timestamp

Kuis `no_timeout` yang lulus first-try **tidak** tercatat di
`quiz_attempts` (karena tidak pernah gagal dulu), jadi tidak ada
timestamp asli untuk timeline. `_build_history_with_fallback()` sengaja
**tidak** memalsukan `now()` untuk kasus ini (akan merusak urutan
kronologis) — event ditandai `timestamp=None` dan selalu ditampilkan di
akhir daftar riwayat, bukan diselipkan seolah baru terjadi.

---

## 8. Auto-Cleanup Forum `quiz-public`

`quiz_forum_cog.py` (`features/moderation/`) — thread latihan yang
tidak ada aktivitas baru selama `QUIZ_THREAD_INACTIVE_DAYS` (default 3
hari, via env var) di-**archive** otomatis (bukan dihapus, histori tetap
ada). Dicek tiap `QUIZ_FORUM_SCAN_INTERVAL_HOURS` jam (default 1).
Terpisah dari `practice_cog.py` — cog ini cuma cleanup, tidak bikin
thread baru.

---

## 9. Command yang Tersedia

| Command | Siapa | Fungsi |
|---|---|---|
| `/create_quiz_menu` | Admin | Post dropdown `DynamicQuizMenu` ke channel (persistent, tidak perlu di-post ulang setelah restart) |
| `/create_practice_menu` | Admin | Post tombol "Mulai Latihan" di forum `quiz-public` — sengaja bisa dijalankan dari channel mana pun karena Forum Channel tidak punya kotak ketik di level root |
| `/journey` | Semua | Roadmap lengkap + tombol lihat timeline |
| `/my_next_action` | Semua | Satu jawaban ringkas: langkah berikutnya + daftar kuis yang sudah terbuka |
| `/list_role_commands` | Semua | Daftar semua kuis + command persis + status cooldown personal |
| `/ranktable` | Semua | Statistik sebaran kasta seluruh server |
| `/rankusers` | Semua | Daftar user yang punya kasta tertentu |
| `/reset_user_cooldown` | Admin | Bebaskan cooldown 1 kuis atau semua kuis milik 1 user |

---

## 10. Gotcha

- **ID Bot Kotoba di-hardcode** (`KOTOBA_BOT_ID = 251239170058616833`)
  di dua file (`gatekeeper_cog.py`, `practice_cog.py`) — bukan dari
  `server_map.yml`. Kalau server pindah pakai bot Kotoba lain/instance
  lain, perlu diganti manual di kedua tempat.
- **`_get_rank_structure()` coba baca `guild_id` sebagai int dulu,
  fallback ke str** — karena YAML kadang ke-load sebagai key string
  tergantung parser. Kalau nambah guild baru ke `gatekeeper_settings.yml`,
  tidak masalah pakai salah satu, tapi jangan campur dua bentuk untuk
  guild yang sama.
- **Thread bilik ujian dipakai ulang** (bukan dibuat baru tiap kali) —
  `user_threads` nyimpen 1 thread per user, di-unarchive/unlock kalau
  ternyata sudah archived/locked. Jangan asumsikan tiap sesi ujian dapat
  thread baru.

---

## Riwayat Perubahan Signifikan

- **2026-07-21** — Dibuat dari nol, disintesis dari `gatekeeper_cog.py`,
  `practice_cog.py`, `journey_service.py`, `journey_models.py`,
  `journey_rules.py`, `quiz_forum_cog.py`, dan `gatekeeper_settings.yml`.
