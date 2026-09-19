# Development Guide — Kotabi Bot

Panduan ini untuk kamu sendiri (owner, non-coder) supaya tahu aturan main
struktur baru dan tidak perlu restrukturisasi ulang lagi ke depannya.
Simpan file ini di root repo (`kotabi-bot/DEVELOPMENT_GUIDE.md`).

---

## 1. Prinsip utama: Feature-first

Setiap fitur = satu folder di `features/<nama_fitur>/`. Semua yang
berhubungan dengan fitur itu (perintah Discord, logic, file `.yml`
konfigurasinya) ada di satu tempat.

**Kalau mau edit atau nambah fitur X, kamu cuma perlu upload folder
`features/X/` ke Claude** — tidak perlu upload seluruh repo lagi, kecuali
fitur itu memang butuh sesuatu dari `shared/` atau `core/` yang juga
perlu diubah.

```
kotabi-bot/
├── main.py
├── core/bot.py              ← jantung bot, auto-discover semua cog
├── shared/                  ← HANYA yang dipakai lintas-fitur
│   ├── config.py            ← baca role ID / channel ID / harga aktif
│   ├── checks.py            ← cek VIP/staff/admin
│   ├── messages.py          ← semua teks yang tampil ke user
│   ├── username_cache.py
│   └── server_map.yml       ← SATU-SATUNYA sumber ID role & channel
│
└── features/
    ├── gatekeeper/          ← sistem kuis & kenaikan kasta
    ├── membership/          ← sistem membership & pembelian
    ├── immersion/           ← log belajar, statistik, achievement
    ├── dictionary/          ← kamus Jepang (/bunpou, /kanji, /kotoba)
    ├── server_admin/        ← backup, restore permission, struktur server
    ├── social/              ← bookmark, custom role, info, dsb
    ├── moderation/          ← selfmute, sticky message, thread resolver
    └── system/              ← watchdog, sync command
```

---

## 2. Aturan penamaan file (WAJIB diikuti)

| Jenis file | Aturan | Contoh |
|---|---|---|
| Perintah Discord (Cog) | **Harus** berakhiran `_cog.py` | `gatekeeper_cog.py`, `admin_cog.py` |
| Logic pendukung (bukan Cog) | Ditaruh di subfolder `support/` | `features/gatekeeper/support/journey_service.py` |
| Config `.yml` fitur | Taruh langsung di folder fitur, JANGAN di `support/` | `features/membership/products.yml` |

**Kenapa wajib `_cog.py`?** Karena `core/bot.py` otomatis scan semua file
`features/*/*_cog.py` saat startup — tidak perlu didaftarkan manual satu-
satu lagi. Kalau file baru **tidak** diakhiri `_cog.py`, bot tidak akan
memuatnya sebagai perintah Discord.

**Kenapa `support/` tidak ikut di-scan?** Supaya bot tidak salah coba
memuat file logic murni (bukan Cog) sebagai perintah.

---

## 3. Kalau mau menambah fitur BARU

1. Buat folder baru: `features/nama_fitur_baru/`
2. Buat file utamanya: `features/nama_fitur_baru/nama_fitur_baru_cog.py`
   — isinya class `commands.Cog` + fungsi `async def setup(bot): await bot.add_cog(...)`
   di baris paling bawah (lihat cog manapun sebagai contoh, semua polanya sama).
3. Kalau fitur butuh logic pendukung yang panjang, taruh di
   `features/nama_fitur_baru/support/nama_file.py`.
4. Kalau fitur butuh config `.yml`, taruh langsung di
   `features/nama_fitur_baru/nama_config.yml`.
5. **Wajib** buat `features/nama_fitur_baru/__init__.py` (boleh kosong) —
   dan `features/nama_fitur_baru/support/__init__.py` juga kalau ada
   folder `support/`. Tanpa ini, import bisa gagal.
6. Restart bot (atau tunggu watchdog kalau `WATCHDOG_AUTO_LOAD_NEW_COGS=true`,
   tapi defaultnya false — lihat bagian Watchdog di bawah).

---

## 4. Kalau mau edit fitur yang SUDAH ADA

1. Upload folder `features/<nama_fitur>/` itu saja ke Claude (plus
   `shared/` kalau perubahannya menyentuh role ID, channel ID, atau teks
   pesan bersama).
2. Edit filenya.
3. **Jangan taruh ID Discord (role ID, channel ID) langsung di kode
   fitur.** Semua ID WAJIB lewat `shared/server_map.yml` +
   `shared/config.py` (fungsi `get_role_id()` / `get_channel_id()`).
   Kalau kamu lihat ada angka panjang (contoh: `1517031166279159848`)
   ditulis langsung di kode Python, itu tanda bahaya — harusnya dari
   `server_map.yml`.
4. Restart bot untuk uji coba (lihat bagian Watchdog).

---

## 5. Single source of truth — JANGAN diduplikasi

Beberapa hal ini sengaja dibuat HANYA ADA SATU TEMPAT. Kalau nemu ada
salinan lain di tempat lain, itu bug lama yang harus dibersihkan, bukan
pola yang boleh ditiru:

| Apa | Satu-satunya lokasi |
|---|---|
| Role ID & Channel ID | `shared/server_map.yml` |
| Cek akses (VIP/staff/admin) | `shared/checks.py` |
| Teks/pesan ke user | `shared/messages.py` (class `Msg`) |
| Tabel permission VIP per channel | `features/server_admin/support/permission_table.py` |
| Cache username Discord | `shared/username_cache.py` |
| Harga tier VIP (Traveler/Companion/Patron) | `features/membership/pricing_presets.yml` (`active_preset`) — lihat `PRICING_SYSTEM_REFACTOR.md` |

Contoh yang **jangan** dilakukan: bikin fungsi `_is_authorized()` sendiri
di dalam satu cog. Selalu pakai `shared.checks.has_authorized_access()`.

**Prinsip ini berlaku juga ke dokumentasi, bukan cuma kode** — lihat
bagian 13.

---

## 6. Tentang Watchdog (auto-reload)

- Kalau kamu **edit** file `*_cog.py` yang sudah ada, watchdog otomatis
  reload dalam 3 detik. Tidak perlu restart manual saat development.
- Kalau kamu **bikin file baru** (`features/x/y_cog.py` yang belum pernah
  ada), watchdog **TIDAK** otomatis memuatnya kecuali env var
  `WATCHDOG_AUTO_LOAD_NEW_COGS=true` di-set. Defaultnya sengaja `false`
  supaya file baru selalu lewat jalur deploy resmi (restart bot via
  GitHub Actions), bukan diam-diam aktif di production.
- Cek status watchdog kapan saja dengan command prefix: `%watchdog_status`
  (khusus `AUTHORIZED_USERS`).

---

## 7. Sebelum push ke `main` (PENTING)

Repo ini pakai GitHub Actions **self-hosted runner** yang auto-deploy
setiap kali branch `main` di-push (lihat `.github/workflows/main.yml`).
Artinya kalau ada typo/error, bot di VPS langsung ikut rusak begitu
kamu push.

**Checklist sebelum push:**
1. Minta Claude cek syntax semua file yang diubah (`python3 -m py_compile <file>`
   untuk tiap file, atau minta Claude jalankan cek batch).
2. Kalau memungkinkan, coba jalankan `python main.py` di komputer/VPS
   staging dulu sebelum merge ke `main`, supaya ketahuan kalau ada
   `import` yang salah/kelewat sebelum production ikut down.
3. Baru push ke `main` kalau sudah yakin.

---

## 8. Migrasi database

Struktur folder Python berubah, tapi **nama tabel SQL di `data/db.sqlite3`
tidak ikut berubah sama sekali**. Jadi tidak perlu migrasi data apa pun
akibat restrukturisasi ini — file database lama tetap kompatibel penuh.

---

## 9. Ringkasan folder & isinya (peta cepat)

| Folder | Isi |
|---|---|
| `features/gatekeeper/` | Kuis kenaikan kasta, sistem journey/roadmap kasta |
| `features/membership/` | Grant/revoke membership, pembelian (`/subscribe`), scheduler expiry |
| `features/immersion/` | `/log`, statistik grafik, goals, bar chart race, achievement |
| `features/dictionary/` | Kamus Jepang — `/bunpou` (`bunpou-notes-master.csv`), `/kotoba` (`kotoba-notes-master.csv`), `/kanji` (`kanji_master.csv` + overlay `kanji_meanings_id.csv`) |
| `features/server_admin/` | Backup server & database, restore permission, tata ulang struktur channel, `/say` |
| `features/social/` | Bookmark, custom role, event roles, info, kneel leaderboard, rank saver, auto-receive role, daily question AI |
| `features/moderation/` | Selfmute, sticky message, thread resolver (forum bantuan) |
| `features/system/` | Watchdog (auto-reload dev), sync command (`%sync_guild`, dsb) |

---

## 10. Checklist: Ubah Config yang Berdampak ke User Aktif

Dipakai **setelah server live** (ada user nyata yang subscribe/punya poin/dsb),
setiap kali mengubah nilai di `.yml` yang menyentuh entitlement user yang sedang
berjalan — threshold poin, harga, kuota, aturan gating, dan sejenisnya. Selama
server masih tahap pengembangan tanpa user aktif, checklist ini belum relevan —
tapi kebiasaan ini sengaja ditulis dari awal supaya begitu launching, prosesnya
sudah baku dan tidak perlu didesain ulang tergesa-gesa.

1. **Klasifikasikan dulu: lazy atau butuh active re-check?**
   Kalau nilai baru dibandingkan ke state tersimpan per-user (poin, expiry, dsb)
   dan baru dicek ulang saat user melakukan transaksi/aksi berikutnya, itu
   **lazy** — dan ini berbahaya kalau ada user yang jarang aktif jadi "nyangkut"
   tanpa sadar dia sebenarnya sudah eligible untuk sesuatu yang lebih baik
   (contoh: threshold poin Patron diturunkan, tapi user lama yang sudah lewat
   threshold baru tidak otomatis ke-upgrade karena tidak ada transaksi baru).
   Kalau perubahan itu seharusnya langsung berlaku ke semua user existing,
   klasifikasikan sebagai **butuh active re-check**.

2. **Kalau butuh active re-check, tulis skrip migrasi sekali-jalan.**
   Taruh di `migrations/`, ikuti pola penamaan yang sudah ada (`v1_`, `v2_`,
   dst). Skrip ini re-evaluasi semua user existing terhadap config baru secara
   eksplisit — jangan andalkan event berikutnya buat men-trigger-nya.

3. **Wajib dijawab eksplisit sebelum merge:** perubahan ini membuat user
   existing diuntungkan, netral, atau dirugikan?
   - Kalau **dirugikan**, wajib ada rencana grandfathering (contoh: harga lama
     tetap berlaku sampai siklus berjalan selesai) sebelum di-deploy — jangan
     langsung diterapkan ke semua orang di titik itu juga.
   - Kalau **diuntungkan/netral**, tetap jalankan langkah 2 kalau butuh active
     re-check, supaya keuntungannya benar-benar sampai ke user, bukan cuma
     berlaku di teori.

4. **Uji dulu di staging/dry-run** sebelum push ke `main`, mengikuti checklist
   di bagian 7.

5. **Kalau perubahan menyentuh sesuatu yang user sadari langsung** (harga naik,
   kuota turun, dsb), siapkan pengumuman di channel yang relevan. Jangan biarkan
   user baru tahu karena tiba-tiba pengalamannya beda tanpa penjelasan.

6. **Catat sebagai event di riwayat/histori** (mis. tabel
   `membership_history_v1` dengan event type baru seperti `config_changed`)
   supaya ada jejak audit kapan dan kenapa suatu nilai berubah — berguna kalau
   ada komplain user nanti dan perlu ditelusuri ulang.

---

## 11. Prinsip Kerja Sama dengan Claude: Jujur, Bukan Menyenangkan

Berlaku untuk **semua** diskusi di project ini — review kode, keputusan
arsitektur, desain fitur baru, sampai strategi bisnis (bukan cuma satu topik
tertentu).

Setiap masukan yang diberikan Claude harus berdasarkan penilaian jujur tentang
apa yang dianggap paling baik, **bukan jawaban yang dibuat supaya kedengaran
enak didengar atau menyenangkan owner**. Kalau ada usulan (termasuk usulan
owner sendiri) yang berpotensi lemah atau punya trade-off yang belum disadari,
itu harus dikatakan terus terang beserta alasannya — bukan divalidasi begitu
saja karena percakapan sudah condong ke arah situ atau karena situasinya
sedang ingin cepat selesai/owner kelihatan capek.

Berlaku juga ke arah sebaliknya: kalau memang tidak ada masukan tambahan yang
genuinely lebih baik, jangan dipaksakan mengarang kritik supaya terlihat kritis.

**Kalau owner bertanya "apakah ini bijak/rencana terbaik?"** — jawab dari
penilaian sendiri, bukan sekadar mengonfirmasi arah yang baru dilontarkan owner.
Kalau jawaban sebelumnya di percakapan yang sama ternyata condong ke arah
"menyenangkan" (mis. karena owner bilang bingung dan minta opsi paling
sederhana), akui itu secara terbuka saat ditanya ulang, lalu berikan penilaian
yang lebih jujur.

*(Versi lengkap prinsip ini beserta konteks kenapa ini penting ada di riwayat
diskusi strategi membership — lihat `MEMBERSHIP_SYSTEM.md` bagian keputusan
strategi — ditulis pertama kali di sana, lalu dipindah ke sini juga karena
sifatnya berlaku umum, bukan cuma untuk diskusi strategi membership.)*

---

## 12. Kalau Mau Edit File Apapun: File Terkait yang Wajib Ikut Dilampirkan

Bagian 4 sudah bilang "upload folder fiturnya" — itu aturan level per-fitur.
Bagian ini levelnya lebih detail: dependency yang **melintasi** folder fitur,
yang tidak kelihatan cuma dari lihat nama foldernya sendiri. Kalau file yang
mau diedit ada di kolom kiri tabel bawah, lampirkan juga semua yang di kolom
kanan — bukan basa-basi, soalnya kalau tidak, Claude bisa saja mengedit tanpa
tahu ada pemakai lain atau sumber data lain yang ikut perlu disesuaikan.

### Tiga pertanyaan sebelum upload

1. Apakah file yang diedit **mendefinisikan** sesuatu yang dipakai file lain
   (fungsi, constant, tabel dict, dsb)? Kalau iya → lampirkan juga semua
   pemakainya, minimal supaya Claude bisa cek apakah perubahan itu berdampak.
2. Apakah file yang diedit **membaca** config/YAML/CSV/JSON tertentu? Kalau
   iya → lampirkan juga file config-nya, supaya Claude tahu bentuk datanya,
   bukan menebak-nebak skema.
3. Apakah perubahan menyentuh role ID, channel ID, atau teks pesan bersama?
   Kalau iya → selalu lampirkan `shared/server_map.yml`, `shared/config.py`,
   dan `shared/messages.py` (sudah disebut di bagian 4, diulang di sini
   karena paling sering kelupaan).

### Paket lampiran per skenario (dependency lintas-folder yang diketahui)

| Kalau mau edit... | Lampirkan juga... | Kenapa |
|---|---|---|
| `features/server_admin/permissions_cog.py` | `structure_cog.py` + `support/permission_table.py` (satu folder) | Ketiganya berbagi satu tabel `CHANNEL_PERMISSIONS` yang sama — ubah salah satu tanpa lihat dua lainnya bisa bikin `/permission restore`, `/permission preview`, dan `/structure setup` jadi tidak sinkron. |
| `features/dictionary/bunpou_cog.py` | `bunpou_fields.py` + contoh beberapa baris `bunpou-notes-master.csv` + `support/bunpou_validator.py` | Skema kolom (`FIELD_NAMES`/`CATEGORY_FIELDS`) didefinisikan di `bunpou_fields.py`, bukan di cog — cog dan validator sama-sama import dari situ, jadi kalau skema berubah keduanya harus ikut. |
| `features/dictionary/kotoba_cog.py` | `kotoba_fields.py` + contoh beberapa baris `kotoba-notes-master.csv` | Sama seperti `bunpou_cog.py`: skema field didefinisikan terpisah dari cog di `kotoba_fields.py`, cog import dari situ. |
| `features/dictionary/kanji_cog.py` | `kanji_fields.py` + contoh baris `kanji_master.csv` + `kanji_meanings_id.csv` | Skema `FIELD_NAMES`/`LIST_JSON_FIELDS`/`OBJECT_JSON_FIELDS` didefinisikan di `kanji_fields.py`. Beberapa kolom `kanji_master.csv` berisi JSON-in-cell (list/object) — beda dari `bunpou`/`kotoba` yang semua kolomnya flat string. `kanji_meanings_id.csv` adalah overlay terjemahan Indonesia terpisah (boleh kosong), di-LEFT JOIN saat render. Detail lengkap: `DICTIONARY_SYSTEM.md`. |
| `features/gatekeeper/gatekeeper_cog.py` | `gatekeeper_settings.yml` + seluruh isi `support/` (`journey_service.py`, `journey_models.py`, `journey_queries.py`, `journey_rules.py`) | Cog memanggil `JourneyService` yang orkestrasi ke semua file itu — potong salah satu bisa bikin `/journey`, `/my_next_action`, atau embed reward/failure error. Detail lengkap: `GATEKEEPER_QUIZ_SYSTEM.md`. |
| `features/gatekeeper/practice_cog.py` | `features/moderation/quiz_forum_cog.py` (kalau perubahan menyangkut perilaku forum/thread) | Dua-duanya sama-sama beroperasi di channel `quiz_public` — `practice_cog.py` bikin thread baru, `quiz_forum_cog.py` auto-archive thread lama di forum yang sama. |
| `features/immersion/log_cog.py` | `support/media_types.py` + `support/helpers.py` + `immersion_log_settings.yml` + `goals_cog.py` | `MEDIA_TYPES` jadi sumber semua metadata media (poin, unit, autocomplete), dan `log_cog.py` memanggil `check_goal_status()` langsung dari `goals_cog.py`. |
| `features/immersion/support/media_types.py` | Ketiga file di `support/autocomplete/` (`anilist.py`, `vndb.py`, `tmdb.py`) | `MEDIA_TYPES` mereferensikan fungsi autocomplete dan query cache dari ketiga file itu. |
| `features/membership/*_cog.py` (mana pun) | Seluruh `features/membership/support/` + `membership_settings.yml` + `products.yml` + `pricing_presets.yml` | Semua cog membership (`admin_cog.py`, `purchase_cog.py`, `scheduler_cog.py`) sama-sama memanggil `MembershipService`/`GrantEngine`/`RoleResolver` yang sama, dan harga sekarang di-resolve dari `pricing_presets.yml` lewat `product_loader.py`. Detail lengkap: `MEMBERSHIP_SYSTEM.md` + `PRICING_SYSTEM_REFACTOR.md`. |
| `shared/config.py` (fungsi terkait membership/harga) | `features/membership/membership_settings.yml` + `pricing_presets.yml` | Path file-nya di-hardcode di `config.py` (`MEMBERSHIP_PATH`, `PRICING_PRESETS_PATH`) — perubahan fungsi baca config harus dicek terhadap struktur YAML aslinya. |
| `shared/checks.py` | `shared/config.py` + `shared/messages.py` | `checks.py` memanggil fungsi role/harga dari `config.py` untuk semua predicate VIP/staff/dic, dan teksnya harus konsisten dengan `messages.py`. |
| `features/social/auto_receive_cog.py` (bagian faction) | `shared/server_map.yml` (bagian `roles.faction_*`) | `emoji_to_role` hardcode di dalam Python cog ini, bukan YAML — role ID-nya tetap harus dicocokkan manual ke `server_map.yml`. |
| `core/bot.py` atau `main.py` | Salah satu contoh `*_cog.py` yang representatif (mis. dari `features/system/`) | Perubahan di sini menyangkut cara SEMUA cog di-load — enak ada 1 contoh cog nyata buat Claude verifikasi pola `setup(bot)` masih cocok. |

Kalau file yang mau diedit tidak ada di tabel di atas, defaultnya tetap
bagian 4: upload folder fiturnya saja, plus `shared/` kalau menyentuh ID atau
teks bersama. Tabel ini bukan daftar final — kalau nanti ketemu dependency
lintas-folder baru yang tidak tercatat di sini, tambahkan barisnya supaya
tidak perlu ditemukan ulang dari nol lain kali.

---

## 13. Protokol Update Dokumentasi (MD)

**Kenapa bagian ini ada:** ditemukan langsung dari audit — dokumen yang
sempat diklaim "final" (`MEMBERSHIP_FEATURE_GUIDE.md`) ternyata bilang
`/kotoba` "belum dibangun" padahal sudah ada & lengkap di kode, dan
dokumen lain (`info_commands.yml`) sempat menyebut threshold poin "60"
padahal config sudah lama diisi 24. Dua-duanya gejala yang sama: **fakta
yang sama ditulis di lebih dari satu tempat, salah satu ketinggalan
diam-diam.** Prinsip "single source of truth" di bagian 5 sekarang
berlaku juga untuk dokumentasi, bukan cuma kode.

### 13.1 Header wajib di setiap MD topik (kecuali file ini & `DOCS_INDEX.md`)

```markdown
> **Status:** Aktif | Arsip
> **Sumber kebenaran untuk:** <daftar topik yang HARUS dicari di file ini>
> **BUKAN sumber untuk:** <topik yang harus dicari di file lain — sebutkan nama filenya>
> **Terakhir diverifikasi terhadap kode:** <tanggal>
```

- **Status "Arsip"** dipakai untuk dokumen histori/draft yang sengaja
  dipertahankan sebagai catatan diskusi, TAPI TIDAK BOLEH dipakai acuan
  fakta terkini — wajib nunjuk ke pengganti resminya.
- **"Terakhir diverifikasi terhadap kode"** diupdate setiap kali dokumen
  dicek ulang terhadap kode asli — bukan cuma setiap kali diedit. Tanggal
  yang sudah lama jadi sinyal "cek ulang dulu sebelum dipercaya penuh".

### 13.2 Bagian wajib di akhir setiap MD topik: Riwayat Perubahan Signifikan

```markdown
## Riwayat Perubahan Signifikan

- **[tanggal]** — <ringkas 1-2 kalimat: apa yang berubah + kenapa>
```

Urutan terbaru di atas. Ini pola yang sudah terbukti jalan di
`PRICING_SYSTEM_REFACTOR.md` ("Log Eksekusi" per tahap) — dibakukan ke
semua dokumen topik lain.

### 13.3 Alur kerja setiap kali ada perubahan

1. **Update isi dokumen topik yang relevan** dulu (bukan bikin catatan
   terpisah) — cari lewat `DOCS_INDEX.md` kalau tidak yakin dokumen mana
   yang mengatur topik itu.
2. **Tambah satu baris** di "Riwayat Perubahan Signifikan" milik dokumen
   itu sendiri.
3. **Update tanggal "Terakhir diverifikasi terhadap kode"** di header.
4. **Kalau perubahannya cukup besar** (breaking change, menyentuh banyak
   file, atau perlu diketahui lintas-topik) — tambah **satu baris saja**
   di `CHANGELOG.md` root, isinya cuma tanggal + ringkasan sangat singkat
   + link ke dokumen topiknya. `CHANGELOG.md` sengaja **tidak pernah**
   diisi detail lengkap kedua kalinya — itu tugas dokumen topik.
5. Kalau perubahan bikin suatu MD lama jadi tidak relevan sepenuhnya
   (digantikan dokumen baru) — ubah statusnya jadi **Arsip** dan tunjuk
   ke penggantinya, JANGAN diklaim "sudah dihapus" kalau filenya
   nyatanya masih ada di repo. Kalau memang mau dihapus fisik, hapus
   betulan filenya, jangan cuma diklaim dihapus di dokumen lain.

### 13.4 Kalau ragu dokumen mana yang harus dicek/diupdate

Cek `DOCS_INDEX.md` di root repo — peta satu halaman semua dokumen MD
project ini, isinya per dokumen: apa yang diaturnya, status, dan kapan
harus dibuka.

---

## 14. Jangan Over-Invest di Audit/Testing Granular Kalau Tujuannya Sintesis

**Ditemukan dari pengalaman langsung** (audit dokumentasi 8 fitur +
testing harness, Sep 2026): begitu pola audit→document→classify→
decide→fix→test terbukti jalan di 1-2 kasus pertama, **nilai marginal
mengulanginya persis sama untuk tiap finding berikutnya menurun
cepat** — sementara biaya waktu tetap linear atau lebih. Itu bukan
salah arah per langkah (tiap langkah individual masuk akal), tapi bisa
jadi salah arah secara kumulatif kalau tujuan sebenarnya adalah
**gambaran sistem secara utuh**, bukan menuntaskan tiap temuan sampai
ke acceptance test.

**Sinyal untuk berhenti eskalasi rigor dan pindah ke sintesis:**
- Pola/metodologi sudah terbukti jalan di ≥1-2 contoh nyata (mis. test
  harness sudah reproduce finding pertama dengan sukses) — mengulang
  persis yang sama ke finding ke-3, ke-5, ke-7 dst boleh dipercepat
  (dokumentasi minimal, tidak perlu review panjang tiap kali), bukan
  di-skip, tapi juga tidak perlu seremonial sebesar yang pertama.
- Tujuan yang dinyatakan user adalah **peta/gambaran/keputusan
  prioritas**, bukan "selesaikan semua bug" — kalau begitu, temuan
  yang sudah terverifikasi cukup masuk sebagai *Known Issues* di
  dokumen sintesis, tidak perlu di-fix/acceptance-test dulu sebelum
  lanjut ke sintesis.
- User mulai bertanya "kok nggak selesai-selesai" — itu sinyal
  eksplisit, jangan dianggap keluhan yang perlu "dijustifikasi lebih
  jauh kenapa metodologinya benar". Tanya balik langkah mana yang
  masih perlu presisi tinggi vs mana yang boleh dipercepat.

**Yang tetap tidak boleh dikorbankan** biar cepat: jangan sampai
"percepat" berarti berhenti verifikasi sebelum klaim (baca kode
sebelum tulis dokumentasi/test tetap wajib — itu yang justru menangkap
temuan nyata seperti `/log_export`/`/logs` non-ephemeral). Yang
dipercepat itu *ritual pelaporannya* (commit message super panjang,
review putaran kedua, dokumentasi tambahan tiap finding kecil) —
bukan *verifikasi faktanya*.

---

*Dokumen ini dibuat saat migrasi struktur lama (`cogs/`, `lib/`,
`config/` flat) menjadi feature-first. Kalau ada pertanyaan struktur di
masa depan, tunjukkan file ini ke Claude di awal percakapan.*
