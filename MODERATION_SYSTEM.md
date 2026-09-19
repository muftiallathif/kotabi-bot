# MODERATION_SYSTEM.md — Sistem Moderation Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** mekanisme `/solved`, `/selfmute`,
> `/unmute_user`, `/check_mute`, `/sticky_last_message`, `/unsticky`,
> dan auto-archive thread forum `quiz-public` — semua yang ada di
> `features/moderation/`, termasuk interaksi lintas-fitur dengan
> `rank_saver_cog.py` (social)
> **BUKAN sumber untuk:** parameter command lengkap (lihat `COMMANDS.md`),
> skema tabel SQL lintas-fitur (lihat `DATABASE_SCHEMA.md`), permission
> channel (lihat `PERMISSION_MATRIX.md`), detail snapshot/restore role
> di `rank_saver_cog.py` sendiri (lihat `SOCIAL_SYSTEM.md` §10 — dokumen
> ini cuma menjelaskan titik temunya dengan `/selfmute`)
> **Terakhir diverifikasi terhadap kode:** 2026-09-19 — dibaca penuh
> `thread_resolver_cog.py`, `selfmute_cog.py`, `sticky_messages_cog.py`,
> `quiz_forum_cog.py`, kedua file `.yml`, plus `git log -p --follow`
> tiap file, dan cross-check eksplisit terhadap `rank_saver_cog.py`
> (social) serta `practice_cog.py` (gatekeeper).

**Dokumen ini baru** — sebelumnya fitur moderation tidak punya dokumen
topik. Audit ini dijalankan dengan prioritas khusus: mencari pola
kegagalan yang sudah terbukti ada di fitur lain (klaim UI tanpa
penegakan, seperti `/log_stats`; state privilege yang bisa dipulihkan
tanpa validasi, seperti `rank_saver_cog.py`) — DAN mencari interaksi
lintas-fitur yang bisa membatalkan tindakan moderasi.

---

## 1. Peta Folder

```
features/moderation/
├── thread_resolver_cog.py    ← /solved, auto-reminder 48j, auto-archive 30h
├── selfmute_cog.py            ← /selfmute, /unmute_user, /check_mute
├── sticky_messages_cog.py      ← /sticky_last_message, /unsticky
├── quiz_forum_cog.py            ← auto-archive thread quiz-public (tanpa command)
├── selfmute_settings.yml
└── thread_resolver_settings.yml
```

---

## 2. `/solved` — ⚠️ Tidak Ada Pengecekan Otorisasi Sama Sekali

**Mekanisme:** status "selesai" **cuma disimpan sebagai prefix string
`[TERSELESAIKAN]` di nama thread Discord itu sendiri** — tidak ada
tabel database, tidak ada flag boolean terpisah di mana pun.

**Gap otorisasi:** `/solved` (`thread_resolver_cog.py:47-62`) cuma
punya 3 gate — guild dikonfigurasi, dijalankan di dalam thread, parent
forum-nya termasuk forum yang dipantau. **Tidak ada satu pun
pengecekan bahwa pemanggil adalah pembuat thread atau staff.** Siapa
pun yang bisa melihat forum bantuan itu bisa menutup/mengarsip thread
milik orang lain.

**Bisa "diakali" lewat 2 jalur independen:**
1. Lewat command itu sendiri (tanpa gate, siapa saja).
2. **Lewat rename thread langsung di Discord** — pembuat thread (thread
   starter) boleh mengedit nama thread miliknya sendiri tanpa perlu
   permission `Manage Threads` (aturan native Discord). Karena status
   "selesai" cuma dibaca dari substring nama thread (loop tiap jam,
   `ask_if_solved_for_guild`), **thread starter bisa menandai thread-nya
   sendiri "selesai" cuma dengan mengganti nama**, bahkan tanpa pernah
   memanggil `/solved` — command-nya jadi sekadar salah satu dari dua
   cara menulis prefix yang sama, bukan satu-satunya otoritas resmi.

**Yang dikonfirmasi BENAR (bukan gap):** klaim auto-reminder 48 jam +
auto-archive 30 hari di `PERMISSION_MATRIX.md:122` **akurat**, memang
diimplementasikan persis begitu di `ask_if_solved_for_guild`
(`thread_resolver_cog.py:94-122`).

**Klasifikasi:** authorization gap — bukan soal role/privilege
administratif, tapi otoritas atas sebuah resource (thread bantuan
orang lain) yang seharusnya cuma milik starter thread/staff.

---

## 3. `/selfmute`, `/unmute_user`, `/check_mute`

### 3.1 Mekanisme (dikonfirmasi: strip-and-restore, bukan role overlay)

`perform_mute` (`selfmute_cog.py:68-84`): mengumpulkan role member saat
ini (`is_assignable()`, bukan booster, dikurangi `roles_not_to_remove`),
simpan sebagai `active_mutes.roles_to_restore`, lalu **satu kali
`member.edit(roles=...)`** yang sekaligus mencabut semua role tersimpan
dan menambahkan role mute pilihan. `perform_user_unmute`
(`selfmute_cog.py:107-131`) mencabut role mute apa pun yang sedang
terpasang, lalu restore persis `roles_to_restore` dari baris DB
(difilter ulang untuk role yang masih ada/assignable), baru hapus
barisnya.

### 3.2 Arti sesungguhnya `allowed_ids`

**Klarifikasi penting** (audit sebelumnya sempat salah kira):
`allowed_ids` di `selfmute_settings.yml` **mengontrol SIAPA yang boleh
memanggil `/selfmute` sama sekali** (`selfmute_cog.py:159-169`) — bukan
membatasi role mute mana yang boleh dipilih dari dropdown. Begitu lolos
gate ini, dropdown pilihan role mute selalu menampilkan **semua**
`mute_roles` yang dikonfigurasi, tanpa filter tambahan.

**Konfigurasi produksi saat ini** (`selfmute_settings.yml`, tidak
berubah sejak commit pertama):
```yaml
mute_roles: []
roles_not_to_remove: []
allowed_ids: []
```
Karena `mute_roles` kosong dan dicek lebih dulu, **`/selfmute` saat ini
inert/tidak fungsional** di guild yang dikonfigurasi — bukan indikasi
bug, cuma konfigurasi placeholder yang belum diisi.

### 3.3 Batas durasi

- **Batas bawah: tidak ada** — `hours=0, minutes=0` (default) sah-sah
  saja, menghasilkan self-mute berdurasi nyaris nol, otomatis ke-unmute
  lewat `clear_mutes` (loop tiap 1 menit) dalam ≤60 detik.
- **Batas atas: dua pengecekan independen** — `hours > 721`
  (`selfmute_cog.py:141-143`) dan total durasi `> 31 hari`
  (`selfmute_cog.py:173-175`). **Teks pesan `MUTE_TOO_LONG` bilang
  "maksimal 30 hari"** (`shared/messages.py:133`) — tidak persis cocok
  dengan batas yang sesungguhnya ditegakkan (~721 jam/~31 hari
  tergantung cek mana yang lebih dulu kena). Inkonsistensi kecil,
  bukan celah keamanan.
- Tidak ada command admin untuk memperpanjang/mempersingkat mute yang
  sedang berjalan — `/unmute_user` cuma bisa mencabut total.

### 3.4 Eksposur publik daftar role saat mute/unmute

- `perform_mute` mengirim daftar role SEBELUM di-mute ke
  `announce_channel` (konfigurasi saat ini: `honor-board`) **secara
  non-ephemeral** (`selfmute_cog.py:182-189`).
- `perform_user_unmute` (dipanggil dari `/unmute_user`) mengirim daftar
  role yang dipulihkan ke **channel tempat admin menjalankan command**
  (bukan channel privat tertentu) juga non-ephemeral
  (`selfmute_cog.py:125-129`).

Keduanya membocorkan daftar role (bisa dibaca sebagai riwayat status
sosial/tier VIP/faction dsb) milik satu user ke audiens yang lebih luas
dari sekadar staff/user bersangkutan.

---

## 4. ⚠️ Interaksi Lintas-Fitur: `rank_saver_cog.py` ↔ `/selfmute`

Ini konfirmasi eksplisit dari permintaan audit — dan hasilnya positif
(interaksi berbahaya benar ada), bukan cuma teoretis.

**Konfirmasi kondisi awal:** role mute **TIDAK ada di
`rank_saver_settings.yml`'s `role_ids_to_ignore` (list kosong)** — jadi
memang tidak ada kontrol yang sudah mencegah ini; ini bukan kasus
"sebenarnya sudah aman, cuma kelihatan berisiko".

**Alur eksploitasi:**
```
User /selfmute
      ↓
perform_mute() strip role LANGSUNG dari member object
      (tapi TIDAK menyentuh tabel user_ranks milik rank_saver)
      ↓
Tabel user_ranks masih menyimpan snapshot LAMA (sebelum mute,
sampai ≤10 menit basi — lihat SOCIAL_SYSTEM.md §10.3)
      ↓
User leave lalu rejoin SEBELUM tick rank_saver berikutnya
sempat merekam state ter-mute
      ↓
rank_saver_cog.py on_member_join (rank_restorer) memulihkan
snapshot LAMA — role asli SEBELUM mute, TANPA role mute
      ↓
Mute secara efektif batal — user kembali normal, tanpa
tindakan admin apa pun
```

**Yang tetap konsisten (tidak ikut kacau):** baris `active_mutes` di
`selfmute_cog.py` **tidak tersentuh** oleh leave/rejoin — `end_time`
dan `roles_to_restore` yang tersimpan di sana tetap seperti semula.
Begitu `clear_mutes` (loop tiap menit) akhirnya mendeteksi `end_time`
sudah lewat, dia tetap memanggil `perform_user_unmute` — tapi karena
user sudah tidak lagi memegang role mute (sudah "dibersihkan" duluan
oleh restorasi tadi), operasi ini jadi no-op yang tidak berbahaya.

**Window realistis kapan mute bisa "dibatalkan" seperti ini:** cuma
**≤10 menit pertama setelah `/selfmute` dipanggil** — kalau
leave/rejoin terjadi SETELAH tick `rank_saver` sempat merekam state
ter-mute (role mute + `roles_not_to_remove` saja), restorasinya justru
jadi "aman" ke arah sebaliknya (member cuma dapat balik role mute-nya
saja, kehilangan role normal sampai `active_mutes` yang benar akhirnya
diproses).

### 4.1 Klasifikasi: Berbeda dari Temuan `rank_saver_cog.py` Sebelumnya

Root cause **sama persis** dengan temuan di `SOCIAL_SYSTEM.md` §10
(snapshot `rank_saver` tidak pernah di-invalidate, `role_ids_to_ignore`
kosong) — tapi **impact dan klasifikasinya berbeda**, sengaja dipisah:

| | `SOCIAL_SYSTEM.md` §10 (role staff) | Temuan ini (`/selfmute`) |
|---|---|---|
| Yang dipulihkan | Role administratif (`royal_guard`/`prime_minister`) | Role normal yang sengaja dicabut sebagai **hukuman** |
| Dampak | Otoritas/privilege bisa balik ke user | **Sanksi moderasi bisa dibatalkan** |
| Klasifikasi | Authorization integrity bug | **Moderation enforcement integrity bug** |

Keduanya tetap satu root cause (`rank_saver_cog.py` §10), tapi dicatat
sebagai dua *consequence* terpisah karena kelas dampaknya beda — perlu
diingat kalau nanti fase *decide* mengevaluasi fix untuk `rank_saver`,
solusinya harus menutup KEDUA jalur ini, tidak cukup cuma exclude 2
role staff.

---

## 5. `/sticky_last_message` & `/unsticky`

### 5.1 Race condition nyata pada `/sticky_last_message`

`interaction.response.defer()` dipanggil dulu (round-trip ke Discord),
**baru setelah itu** command mengambil `interaction.channel.history(limit=5)`
untuk menentukan "pesan terakhir" (`sticky_messages_cog.py:56-73`). Ada
window beberapa ratus milidetik sampai beberapa detik di mana **user
lain bisa mengirim pesan baru** yang akan jadi `last_message` terpilih
menggantikan pesan yang staff maksud — tidak ada snapshot ID pesan
terakhir SEBELUM `defer()` dipanggil. User yang mengamati staff sedang
mengetik `/sticky_last_message` bisa dengan sengaja "membajak" pesan
apa yang jadi sticky.

### 5.2 Bug lain (bukan keamanan, tapi worth dicatat)

- **`UnboundLocalError` tak tertangani** — kalau 5 pesan terakhir semua
  ter-skip (mis. channel nyaris kosong, atau semuanya respons bot dari
  `/sticky_last_message` sebelumnya), variabel `last_message` tidak
  pernah ter-assign, lalu diakses langsung → crash interaksi tanpa
  pesan error yang jelas ke user.
- **`discord.Forbidden` tak tertangani di listener `on_message`** — beda
  dari `discord.NotFound` yang sudah ditangkap (dan otomatis
  membersihkan baris DB), kalau bot kehilangan permission "Send
  Messages" di channel yang sedang sticky, error ini lolos tak
  tertangani **di setiap pesan baru** sampai ada yang manual jalankan
  `/unsticky` — kondisi error yang menetap, bukan sekali gagal lalu
  selesai.
- Tidak ada rate-limit/cooldown pada mekanisme re-sticky — setiap pesan
  baru di channel ber-sticky memicu delete+repost, murni diserialkan
  lewat `asyncio.Lock` per-channel (mencegah race, bukan membatasi
  frekuensi).

---

## 6. `quiz_forum_cog.py` — Auto-Archive Thread `quiz-public`

Tidak ada command — murni `tasks.loop`. **Dicek aman**, termasuk cross-
check eksplisit dengan `practice_cog.py` (gatekeeper) sesuai permintaan
audit:

- Env var `QUIZ_THREAD_INACTIVE_DAYS` (default 3) dan
  `QUIZ_FORUM_SCAN_INTERVAL_HOURS` (default 1) dibaca benar saat modul
  di-import (butuh restart bot untuk berubah, bukan hot-reload — bukan
  bug, cuma catatan operasional).
- "Tidak aktif" = waktu pesan terakhir, fallback ke waktu thread dibuat
  kalau tidak ada pesan yang bisa di-resolve. Thread yang sudah
  archived/locked dilewati (locked sengaja tidak disentuh — thread
  yang di-lock manual oleh moderator tidak ikut auto-archive).
- **Tidak ada konflik dengan `practice_cog.py`** — `practice_cog.py`
  sendiri secara eksplisit mendokumentasikan (docstring-nya sendiri)
  bahwa cleanup thread diserahkan penuh ke cog ini, dan logic
  rank-up/exam (`gatekeeper_cog.level_up_routine()`) **cuma memproses
  pesan dari tabel `user_threads`/channel `quiz_rank_up`** — thread di
  forum `quiz_public` tidak pernah menjadi state resmi ujian, jadi
  tidak ada risiko auto-archive "menghapus" progress ujian siapa pun.

---

## 7. Tabel Database (Ringkasan)

| Tabel | Dibuat di | Catatan |
|---|---|---|
| `active_mutes` | `selfmute_cog.py` | `end_time` disimpan sebagai string terformat meski kolom dideklarasikan `INTEGER` (SQLite dinamis-tipe, "jalan" tapi tidak sesuai deklarasi) |
| `sticky_messages` | `sticky_messages_cog.py` | 1 baris aktif per `(guild_id, channel_id)` |

`thread_resolver_cog.py` dan `quiz_forum_cog.py` **tidak punya tabel**
— status keduanya murni disimpan di state Discord asli (nama
thread/status archived), bukan DB.

---

## 8. Permission/Access (Ringkasan)

| Command | Gate | Catatan |
|---|---|---|
| `/solved` | **Tidak ada** | ⚠️ Lihat bagian 2 |
| `/selfmute` | `guild_only()` + in-body `allowed_ids` (eligibility, bukan role-choice) | Saat ini inert (config kosong) |
| `/unmute_user` | `default_permissions(administrator=True)` | Cuma decorator, tidak ada backup in-body check |
| `/check_mute` | Tidak ada (self-scoped) | Aman |
| `/sticky_last_message`, `/unsticky` | `default_permissions(manage_messages=True)` | Cuma decorator, tidak ada backup in-body check |

---

## 9. Dependency ke Fitur Lain

- **`selfmute_cog.py` ↔ `rank_saver_cog.py` (social)** — lihat bagian 4,
  interaksi tidak disengaja lewat tabel `user_ranks`.
- **`quiz_forum_cog.py` ↔ `practice_cog.py` (gatekeeper)** — didesain
  aman, didokumentasikan eksplisit di kedua sisi.
- `selfmute_cog.py`, `thread_resolver_cog.py` → `shared/config.get_channel_id()`.

---

## 10. Known Issues / Gotcha (Ditemukan Saat Audit 2026-09-19)

Diurutkan dari yang paling serius:

**1. `/solved` — tidak ada pengecekan otorisasi sama sekali**, dan
statusnya bisa dipalsukan lewat rename thread langsung tanpa command
(bagian 2). **Authorization gap, belum diperbaiki.**

**2. `rank_saver_cog.py` bisa membatalkan `/selfmute` lewat leave-rejoin
dalam window ≤10 menit** (bagian 4) — role mute TIDAK ada di
`role_ids_to_ignore`, dikonfirmasi bukan kontrol yang sudah ada.
**Moderation enforcement integrity bug — root cause sama dengan
`SOCIAL_SYSTEM.md` §10, tapi diklasifikasikan terpisah karena dampaknya
beda (membatalkan sanksi, bukan memulihkan privilege). Belum
diperbaiki.**

**3. `/sticky_last_message` race condition** — "pesan terakhir"
ditentukan setelah `defer()`, bisa dibajak user lain (bagian 5.1).

**4. Eksposur publik daftar role saat mute/unmute** — dikirim
non-ephemeral ke channel publik/channel command dijalankan (bagian 3.4).

**5. `UnboundLocalError` tak tertangani** di `/sticky_last_message`
kalau tidak ada pesan valid dalam 5 pesan terakhir (bagian 5.2).

**6. `discord.Forbidden` tak tertangani** di listener sticky —
kondisi error menetap kalau bot kehilangan permission kirim pesan
(bagian 5.2).

**7. Minor: teks `MUTE_TOO_LONG` bilang "30 hari", batas sesungguhnya
~31 hari/721 jam** (bagian 3.3) — inkonsistensi kecil, bukan keamanan.

**8. Klarifikasi (bukan bug):** `allowed_ids` mengatur siapa boleh
`/selfmute`, bukan role mana yang boleh dipilih (bagian 3.2) — audit
sebelumnya (laporan katalog command awal) salah kira soal ini.

**Dikonfirmasi AMAN, dicatat supaya tidak diaudit ulang tanpa perlu:**
klaim auto-reminder/auto-archive `/solved` di `PERMISSION_MATRIX.md`
akurat; `quiz_forum_cog.py` tidak konflik dengan `practice_cog.py`.

---

## Riwayat Perubahan Signifikan

- **2026-09-19** — Dibuat dari nol. Dibaca penuh 4 file kode + 2 config
  + `git log -p --follow` tiap file, plus cross-check eksplisit ke
  `rank_saver_cog.py` (social) dan `practice_cog.py` (gatekeeper) sesuai
  permintaan audit lintas-fitur. Ditemukan: `/solved` tanpa otorisasi
  sama sekali (dan bisa dipalsukan lewat rename thread); interaksi
  nyata `rank_saver_cog.py` ↔ `/selfmute` yang bisa membatalkan mute
  dalam window ≤10 menit (diklasifikasikan terpisah dari temuan role
  staff sebelumnya sebagai *moderation enforcement integrity*, bukan
  *authorization integrity*, walau root cause sama); race condition di
  `/sticky_last_message`. Semua belum diperbaiki, sengaja tidak
  disentuh (audit-only pass).
