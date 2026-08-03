# PRICING_SYSTEM_REFACTOR.md — Rencana Single Source of Truth Harga Membership Kotabi

> **Status:** Rencana / belum diimplementasikan. Dokumen ini adalah hasil
> diskusi menentukan struktur harga launch, preset harga, dan rencana
> refactor supaya harga cukup diubah di **satu tempat**.
>
> **Keputusan akhir:** Opsi A dipilih — refactor kode satu kali supaya
> semua tempat yang menampilkan harga menarik angka dari satu sumber saat
> runtime. Preset diganti dengan **mengedit file & commit ke git**
> (bukan lewat command Discord), sesuai preferensi eksplisit pemilik
> project.

---

## 1. Masalah yang mau diselesaikan

Saat ini, harga tier (Traveler/Companion/Patron) tertulis terpisah dan
manual di **5 tempat berbeda** di kode. Kalau harga berubah, kelima
tempat itu harus diedit satu-satu — kalau lupa satu, teks yang
ditampilkan ke user jadi kontradiktif dengan harga asli di `/subscribe`.

Sudah ditemukan **1 bug nyata** akibat pola ini: `info_commands.yml` key
`member-reguler` masih menulis *"Patron otomatis setelah 60 poin
kumulatif"*, padahal `membership_settings.yml` sudah lama diubah ke
`point_threshold: 24`. Kemungkinan lupa disinkronkan saat threshold
diturunkan dari 60 ke 24.

### Lokasi harga & nama tier saat ini (sebelum refactor)

| # | File | Apa yang tertulis |
|---|---|---|
| 1 | `features/membership/products.yml` | `price` per produk (sumber asli buat `/subscribe`) + `name` tier |
| 2 | `features/membership/membership_settings.yml` | `price_rp` per tier (referensi/display, **tidak dipakai** `/subscribe`) + `name` + `point_threshold: 24` |
| 3 | `shared/messages.py` | `Msg.VIP_ONLY`, `Msg.PREMIUM_ONLY`, `Msg.GATEKEEPER_VIP_ONLY` — teks harga hardcode, `GATEKEEPER_VIP_ONLY` bahkan duplikat manual dari `VIP_ONLY` |
| 4 | `shared/checks.py` | `MSG_DIC_DETAIL_ONLY` — teks harga hardcode untuk gating kamus |
| 5 | `features/social/info_commands.yml` | key `member-reguler` — daftar harga lengkap ditulis manual (mengandung bug 60 vs 24 poin di atas) |

---

## 2. Struktur harga yang disepakati

### 2.1 Harga normal (target akhir, setelah promo launch berakhir)

| Tier | Harga normal |
|---|---|
| Traveler | Rp40.000 / bulan |
| Companion | Rp80.000 / bulan |
| Patron (lifetime) | Rp449.000 |

### 2.2 Preset harga launch — 6 opsi

Semua opsi diturunkan proporsional dari harga Patron (titik acuan),
karena Patron paling representatif untuk "seberapa besar diskon
launch-nya" — dibandingkan terhadap biaya total kalau member grinding
lewat Companion bulanan sampai otomatis jadi Patron (butuh 24 poin,
Companion = 2 poin/bulan → setara 12 bulan).

| Preset | Patron | Traveler/bln | Companion/bln | ~Diskon dari harga normal |
|---|---|---|---|---|
| **1** | 200.000 | 18.000 | 35.000 | ~55% |
| **2** | 250.000 | 22.000 | 45.000 | ~44% |
| **3** | 300.000 | 27.000 | 55.000 | ~33% |
| **4** | 350.000 | 30.000 | 60.000 | ~22% |
| **5** | 400.000 | 35.000 | 70.000 | ~11% |
| **6** | 450.000 | 40.000 | 80.000 | ~0% (≈ harga normal) |

> Rekomendasi titik awal: **Preset 3 atau 4** — diskon masih kerasa
> signifikan buat dorong FOMO, tapi nggak bikin harga normal nanti
> kelihatan mencekik pas promo berakhir.

### 2.3 Varian 6 bulan & 1 tahun — DIHITUNG, bukan diisi manual

Supaya tidak perlu isi 4 angka tambahan (Traveler 6bln, Traveler 1thn,
Companion 6bln, Companion 1thn) di **setiap** dari 6 preset (yang berarti
24 angka rawan typo/nggak sinkron), harga paket panjang **diturunkan
otomatis** dari harga bulanan preset yang aktif, pakai rumus tetap:

```
harga_6_bulan = harga_bulanan × 5     (bayar 5 bulan, dapat 6 — ~17% off)
harga_1_tahun = harga_bulanan × 10    (bayar 10 bulan, dapat 12 — ~17% off)
```

Poin lifetime (`point.amount`) untuk paket ini juga otomatis:
- 6 bulan → `amount` = poin_per_bulan_tier × 6
- 1 tahun → `amount` = poin_per_bulan_tier × 12

Dengan begini, ganti 1 angka preset (harga bulanan Traveler/Companion)
otomatis mengubah 4 varian durasi sekaligus, konsisten, tanpa sumber
data terpisah yang bisa nyasar.

*(Kalau nanti mau kasih diskon ekstra khusus 1 tahun, mis. 20-25%
alih-alih 17%, cukup ubah pengali `10` → `~9.5` di satu tempat kode,
tetap bukan per-preset.)*

---

## 3. Arsitektur Single Source of Truth (Opsi A)

### 3.1 Prinsip

**Satu file preset** (statis, diedit manual & di-commit ke git oleh
pemilik project) jadi satu-satunya tempat harga mentah ditulis. Semua
tempat lain (produk `/subscribe`, teks penolakan akses, `/info`)
**menghitung** harga dari sana saat runtime — tidak ada lagi angka
hardcode kedua di tempat lain.

```
┌─────────────────────────────────────────┐
│  pricing_presets.yml                     │   <- SATU-SATUNYA tempat
│  - 6 opsi preset (harga mentah)          │      harga ditulis manual
│  - active_preset: 4   <- diganti manual  │
└───────────────┬───────────────────────────┘
                │
                ▼
      shared/config.py
      get_active_prices()  <- fungsi baru, resolve preset aktif
      + hitung varian 6bln/1thn dari rumus
                │
    ┌───────────┼────────────────┬─────────────────┐
    ▼           ▼                ▼                  ▼
products.yml   shared/         shared/          info_commands.yml
(traveler/     messages.py     checks.py        key member-reguler
companion/     (VIP_ONLY,      (MSG_DIC_        (diganti jadi command
patron price   PREMIUM_ONLY,   DETAIL_ONLY       Python, generate teks
di-resolve     GATEKEEPER_     jadi fungsi)      dari get_active_prices())
saat load,     VIP_ONLY jadi
bukan statis)  fungsi)
```

### 3.2 Yang TIDAK ikut sistem ini

Produk non-tier (`jlpt_n5`, `jlpt_n4`, `kaiwa` — kelas intensif) di
`products.yml` **tetap statis seperti sekarang**. Harganya independen
dari harga tier VIP, jadi tidak perlu ikut preset.

---

## 4. Rencana implementasi (per file)

### 4.1 File baru: `features/membership/pricing_presets.yml`

```yaml
active_preset: 4   # <- SATU-SATUNYA angka yang diganti manual tiap kali mau ubah harga

presets:
  1: { traveler: 18000, companion: 35000, patron: 200000 }
  2: { traveler: 22000, companion: 45000, patron: 250000 }
  3: { traveler: 27000, companion: 55000, patron: 300000 }
  4: { traveler: 30000, companion: 60000, patron: 350000 }
  5: { traveler: 35000, companion: 70000, patron: 400000 }
  6: { traveler: 40000, companion: 80000, patron: 450000 }   # = harga normal

duration_multipliers:
  6_month: 5    # bayar 5 bulan, dapat 6
  12_month: 10  # bayar 10 bulan, dapat 12

points_per_month:
  traveler: 1
  companion: 2
```

### 4.2 `shared/config.py` — fungsi baru

Tambah `_load_pricing_presets()` (pola sama seperti `_load_membership_cfg()`)
dan `get_active_prices()` yang return dict:

```python
{
    "traveler": {"monthly": 30000, "6mo": 150000, "12mo": 300000},
    "companion": {"monthly": 60000, "6mo": 300000, "12mo": 600000},
    "patron": 350000,
}
```

### 4.3 `features/membership/support/product_loader.py`

Untuk product key `traveler`, `companion`, `patron` (dan varian
`traveler_6mo`, dst kalau mau ditambahkan sebagai entri `/subscribe`
terpisah): field `price` di-resolve dari `get_active_prices()` saat
`_load()`, bukan dibaca langsung dari `price:` statis di `products.yml`.
Produk kelas (`jlpt_n5` dst) tidak berubah — tetap baca `price:` apa
adanya.

### 4.4 `shared/messages.py`

`Msg.VIP_ONLY`, `Msg.PREMIUM_ONLY`, `Msg.GATEKEEPER_VIP_ONLY` diubah dari
konstanta string jadi `@staticmethod` (pola yang sama seperti
`Msg.log_amount_exceeded()` yang sudah ada di file ini), format harga dari
`get_active_prices()`. `GATEKEEPER_VIP_ONLY` tidak lagi duplikat manual
dari `VIP_ONLY` — cukup panggil method yang sama atau reuse teksnya.

### 4.5 `shared/checks.py`

`MSG_DIC_DETAIL_ONLY` diubah jadi fungsi dengan pola yang sama.

### 4.6 `features/social/info_commands.yml` + `info_cog.py`

Key `member-reguler` dipindah dari YAML statis menjadi digenerate oleh
`info_cog.py` dari `get_active_prices()` — sekaligus jadi momentum
membenarkan bug lama (60 poin → 24 poin, ambil dari
`get_lifetime_threshold()` yang sudah ada di `shared/config.py`, bukan
angka hardcode baru).

### 4.7 `features/membership/membership_settings.yml`

Field `price_rp` per tier dijadikan hasil resolve dari preset juga
(supaya tidak ada sumber kedua yang bisa nyasar), atau — kalau mau lebih
sederhana — dihapus sepenuhnya karena sudah terbukti tidak dipakai
`/subscribe` dan hanya berisiko bikin bingung.

---

## 5. Checklist saat ganti harga (SETELAH refactor selesai)

1. Buka `pricing_presets.yml`
2. Ganti `active_preset: N` ke opsi yang diinginkan (atau tambah opsi
   ke-7 dst kalau perlu preset baru)
3. Commit & push ke git seperti biasa
4. Restart bot (config di-load ulang, sama seperti perubahan YAML
   lainnya) — **satu-satunya langkah manual**, semua 5 lokasi lama
   otomatis konsisten

Dibandingkan checklist lama (5 file harus diedit manual satu-satu,
rawan lupa satu tempat), ini turun jadi **1 file, 1 angka**.

---

## 6. Hal yang sengaja TIDAK dipakai (dan alasannya)

- **Command Discord untuk ganti harga langsung** (`/admin set_price`)
  — ditolak karena mengubah state di database tanpa jejak git, di luar
  alur commit/deploy yang jadi preferensi pemilik project.
- **Command Discord untuk ganti nomor preset saja** (`/admin
  set_price_preset preset:4`) — sempat diusulkan sebagai jalan tengah
  (preset tetap statis di git, cuma pemilihan preset yang live lewat
  bot), tapi **tidak dipakai** karena Opsi A (edit file, commit
  manual) yang dipilih final — konsisten dengan preferensi kontrol
  penuh lewat git untuk seluruh proses, termasuk pemilihan preset aktif.
- **Harga varian 6bln/1thn diisi manual per preset** — ditolak karena
  24 angka (4 varian × 6 preset) jauh lebih rawan salah/nggak sinkron
  dibanding 1 rumus pengali yang berlaku ke semua preset otomatis.

---

## 7. Status implementasi

- [x] Buat `pricing_presets.yml`
- [x] Tambah `get_active_prices()` di `shared/config.py`
- [x] Update `product_loader.py` untuk resolve harga tier dari preset
- [x] Ubah `Msg.VIP_ONLY` / `PREMIUM_ONLY` / `GATEKEEPER_VIP_ONLY` jadi fungsi
- [x] Ubah `MSG_DIC_DETAIL_ONLY` jadi fungsi
- [x] Pindahkan `member-reguler` dari YAML statis ke generate dinamis + benarkan bug 60→24 poin
- [ ] (Opsional) Sinkronkan atau hapus `price_rp` di `membership_settings.yml`
- [ ] Tentukan preset aktif awal (rekomendasi: 3 atau 4) dan deadline promo launch

---

## 8. Log Eksekusi

### Tahap 1 — `pricing_presets.yml` ✅ Selesai

- **File:** `features/membership/pricing_presets.yml` (baru)
- **Isi:** 6 preset harga, `active_preset` default diset ke `4`
  (Traveler 30.000 / Companion 60.000 / Patron 350.000), rumus pengali
  durasi 6bln (×5) & 1thn (×10), dan `points_per_month` per tier.
- **Cara pakai sekarang:** taruh file ini di `features/membership/`
  dalam repo asli, commit. Belum ada kode lain yang membacanya —
  efeknya baru terasa setelah Tahap 2 (`shared/config.py`) selesai.
- **Belum ada perubahan** di file kode manapun yang sudah ada — semua
  masih baca harga statis lama seperti sebelumnya, jadi bot tetap
  jalan normal kalau file ini di-commit sekarang tanpa lanjut ke tahap
  berikutnya (aman, tidak breaking).

### Tahap 2 — `get_active_prices()` di `shared/config.py` ✅ Selesai

- **File:** `shared/config.py` — diberikan sebagai **file utuh siap
  replace** (`config.py`), bukan potongan tempel. Isinya kode asli
  + tambahan berikut menyatu jadi satu file.
- **Ditambahkan:**
  - `PRICING_PRESETS_PATH` (konstanta path, pola sama seperti
    `CONFIG_PATH`/`MEMBERSHIP_PATH` yang sudah ada)
  - `_pricing_presets_cfg` (cache module-level, pola sama seperti
    `_server_map`/`_membership_cfg`)
  - `_load_pricing_presets()` — loader YAML, fail-safe (return `{}`
    kalau file tidak ada, sama seperti loader lain di file ini)
  - `get_active_prices()` — **satu-satunya fungsi** yang boleh dipanggil
    tempat lain untuk tahu harga tier. Resolve preset aktif, hitung
    6bln/1thn dari `duration_multipliers`, hitung poin dari
    `points_per_month`. Ada fallback ke harga normal (preset "6" secara
    nilai) kalau file/preset rusak — supaya bot tidak crash total kalau
    `pricing_presets.yml` bermasalah.
  - `reload_config()` diupdate ikut reset & reload cache preset.
- **Belum ada tempat lain yang memanggil `get_active_prices()`** — jadi
  file ini aman ditempel sekarang, tidak mengubah perilaku bot yang
  sudah berjalan. Efeknya baru kepakai mulai Tahap 3.

### Tahap 3 — `product_loader.py` ✅ Selesai

- **File:** `features/membership/support/product_loader.py` (file
  utuh siap replace)
- **Yang berubah:**
  - Setelah `products.yml` dimuat seperti biasa, harga produk `traveler`
    dan `companion` **ditimpa** dari `get_active_prices()["traveler"/"companion"]["monthly"]`,
    dan `patron` ditimpa dari `get_active_prices()["patron"]`.
  - **4 produk baru digenerate otomatis** (tidak pernah ditulis di
    `products.yml`): `traveler_6mo`, `traveler_12mo`, `companion_6mo`,
    `companion_12mo` — harga & poinnya langsung dari
    `get_active_prices()`, durasi 180/365 hari.
  - Produk kelas (`jlpt_n5`, `jlpt_n4`, `kaiwa`) dan `trial`: **tidak
    disentuh sama sekali**, tetap baca `price:` statis dari
    `products.yml` seperti sebelumnya.
  - Ada fallback: kalau `get_active_prices()` gagal (mis. file preset
    rusak), harga tier VIP tetap pakai angka statis lama di
    `products.yml`, dan varian 6bln/1thn tidak dibuat — bot tetap
    jalan, cuma promo preset yang tidak aktif.
- **Efek nyata mulai sekarang:** `/subscribe` sudah menampilkan 4 opsi
  baru (6bln/1thn Traveler & Companion) di dropdown produk, dan harga
  Traveler/Companion/Patron yang tampil sudah ikut `active_preset` di
  `pricing_presets.yml` — **bukan lagi angka statis `products.yml`**.
- **Belum ikut berubah:** teks penolakan akses (`VIP_ONLY` dkk) dan
  `/info member-reguler` masih pakai angka hardcode lama — jadi untuk
  sementara ada inkonsistensi: harga di `/subscribe` sudah benar
  (ikut preset), tapi teks di tempat lain belum. Ini yang dibereskan
  Tahap 4-6.

### Tahap 4 — `Msg.VIP_ONLY`/`PREMIUM_ONLY`/`GATEKEEPER_VIP_ONLY` ✅ Selesai

- **File:** `shared/messages.py` (file utuh) + `shared/checks.py` (file
  utuh) + 1 baris di `features/gatekeeper/gatekeeper_cog.py` (exact
  find-replace, file tidak di-paste utuh karena ~900 baris — lihat
  instruksi persis di chat).
- **Perubahan sifat penting:** `VIP_ONLY`, `PREMIUM_ONLY`,
  `GATEKEEPER_VIP_ONLY` **berubah dari konstanta string jadi method**
  (`@staticmethod`). Semua caller lama yang akses tanpa kurung
  (`Msg.VIP_ONLY`) **wajib** diubah jadi `Msg.VIP_ONLY()`. Kalau ada
  yang kelewat, errornya langsung kelihatan saat command dites (bot
  akan coba kirim representasi object function ke Discord, bukan
  silent bug) — jadi mudah ketauan, tapi tetap wajib dicek semua
  caller-nya:
  - `shared/checks.py` → `is_vip()` dan `is_premium()` — **sudah
    diupdate** di file yang dikasih.
  - `features/gatekeeper/gatekeeper_cog.py` → `DynamicQuizMenu.callback`
    (1 tempat) — **instruksi diberikan, belum otomatis ditempel** (kamu
    perlu apply manual atau minta versi file utuh).
- **Ditemukan sekalian (di luar scope, dicatat saja):**
  `shared/checks.py` fungsi `is_authorized()` memanggil
  `Msg.AUTHORIZED_ONLY` — konstanta ini **tidak pernah didefinisikan**
  di `messages.py` manapun (versi lama maupun baru). Ini bug lama yang
  sudah ada sebelum refactor ini, di luar scope pricing — tapi kalau
  `/permission`, `/structure`, atau command admin lain pernah dipanggil
  user yang bukan authorized, baris itu akan `AttributeError` saat
  runtime. Perlu dibenerin terpisah (tambah `AUTHORIZED_ONLY` ke
  `Msg`), tidak masuk checklist pricing ini.
- **Belum ikut berubah:** `MSG_DIC_DETAIL_ONLY` di `checks.py` masih
  angka statis (Rp80.000) — itu Tahap 5.

### Tahap 5 — `MSG_DIC_DETAIL_ONLY` ✅ Selesai

- **File:** `shared/checks.py` (file utuh, replace `checks.py` versi
  Tahap 4) + 6 call site di 3 file cog (instruksi find-replace, tidak
  di-paste utuh — masing-masing file besar).
- **Perubahan:** `MSG_DIC_DETAIL_ONLY` diubah dari konstanta string
  jadi fungsi (`def MSG_DIC_DETAIL_ONLY() -> str:` — bukan
  `@staticmethod` karena ini fungsi module-level, bukan method di
  class `Msg`). Harga Companion di dalamnya sekarang pakai
  `Msg._format_rp()` (reuse formatter dari Tahap 4, bukan duplikat
  logic format rupiah).
- **Call site yang WAJIB diupdate manual** (pola sama persis di semua
  6 tempat — cari `MSG_DIC_DETAIL_ONLY,` ganti jadi
  `MSG_DIC_DETAIL_ONLY(),`, exact match, aman global find-replace per
  file):
  - `features/dictionary/bunpou_cog.py` — 2 tempat (`BunpouListView._on_select`, command `bunpou`)
  - `features/dictionary/kotoba_cog.py` — 2 tempat (`KotobaListView._on_select`, command `kotoba`)
  - `features/dictionary/kanji_cog.py` — 2 tempat (`KanjiListView._on_select`, command `kanji_command`)
- **Belum ikut berubah:** `features/social/info_commands.yml` key
  `member-reguler` masih statis (termasuk bug 60→24 poin yang belum
  dibenerin) — itu Tahap 6, sekaligus tahap terakhir dari checklist inti.

### Tahap 6 — `member-reguler` dinamis + bug 60→24 poin ✅ Selesai

- **File:** `features/social/info_cog.py` (file utuh) + `features/social/info_commands.yml` (file utuh, key `member-reguler` dihapus)
- **Perubahan:**
  - Key `member-reguler` **dihapus total** dari `info_commands.yml`,
    diganti komentar penjelasan supaya tidak ada yang tambah lagi
    key statis dengan nama sama di masa depan.
  - `info_cog.py` dapat `DYNAMIC_INFO_BUILDERS` — dict key → fungsi
    generator. `_build_member_reguler_text()` narik harga dari
    `get_active_prices()` dan threshold dari `get_lifetime_threshold()`
    (bukan angka hardcode).
  - **Bug lama dibenarkan**: teks sekarang otomatis nunjukin angka
    threshold yang BENAR (24, atau berapa pun `point_threshold` di
    `membership_settings.yml` nanti), bukan "60" yang basi.
  - `info_autocomplete()` diupdate supaya `member-reguler` tetap
    muncul di dropdown `/info` walau sudah tidak ada di
    `info_commands.yml` (digabung dari `DYNAMIC_INFO_BUILDERS.keys()`).
- **Tidak perlu ubah caller lain** — `/info member-reguler` tetap
  command yang sama, cuma sumber teksnya yang berubah dari dalam.

---

## ✅ Checklist inti selesai (Tahap 1-6)

Sistem "ganti 1 angka, semua ikut" sekarang benar-benar berjalan untuk:
`/subscribe` (termasu 4 varian 6bln/1thn baru), `Msg.VIP_ONLY()`,
`Msg.PREMIUM_ONLY()`, `Msg.GATEKEEPER_VIP_ONLY()`, `MSG_DIC_DETAIL_ONLY()`,
dan `/info member-reguler`. Semua narik dari satu tempat:
`features/membership/pricing_presets.yml` → `active_preset`.

**Yang masih perlu kamu lakukan secara manual di repo asli** (bukan
kode, tapi langkah penerapan):
1. Apply 6 file yang dikasih Tahap 1-6 ke lokasi aslinya.
2. Apply 3 instruksi find-replace kecil yang TIDAK di-paste utuh
   (karena file besar): 1 baris di `gatekeeper_cog.py` (Tahap 4), dan
   6 baris tersebar di `bunpou_cog.py`/`kotoba_cog.py`/`kanji_cog.py`
   (Tahap 5) — semua exact-match, aman find-replace.
3. Commit & restart bot.
4. Tes `/subscribe`, `/info member-reguler`, dan salah satu command
   yang gated VIP (mis. `/log`) buat mastiin harga yang tampil
   konsisten di semua tempat.

### Item opsional (di luar checklist inti) — status terkini

- [x] Sinkronkan atau hapus `price_rp` di `membership_settings.yml`
      — **dihapus** (bukan disinkronkan), karena terbukti tidak
      pernah dibaca kode manapun. Lihat Tahap 7a.
- [x] (Di luar scope pricing) Benarkan `Msg.AUTHORIZED_ONLY` yang
      dipanggil `is_authorized()` di `checks.py` tapi tidak pernah
      didefinisikan di `messages.py` — **ditambahkan**. Lihat Tahap 7b.
- [ ] Tentukan preset aktif final & deadline promo launch (keputusan
      bisnis, bukan kode — lihat bagian 2.2 dokumen ini untuk opsi).

---

## 9. Tahap 7 (bonus, di luar checklist inti pricing)

### 7a — Hapus `price_rp` dari `membership_settings.yml`

- **File:** `features/membership/membership_settings.yml` (file utuh)
- **Keputusan:** dihapus, bukan disinkronkan ke preset — karena
  ditelusuri lagi, field ini **tidak pernah dibaca** kode manapun
  (`get_tier_info()` return dict-nya, tapi tidak ada caller yang
  mengambil key `price_rp` dari situ). Menyinkronkannya cuma nambah
  kerja tanpa manfaat; menghapusnya menghilangkan risiko orang
  ke depan salah kira ini sumber harga sungguhan.
- **Temuan sampingan (dicatat, TIDAK dieksekusi):** field `points` di
  tier yang sama (`roles.trial/traveler/companion.points`) kelihatannya
  **juga dead config** dengan alasan serupa — poin yang benar-benar
  dipakai sistem datang dari `products.yml` (`grant.point.amount`) dan
  `pricing_presets.yml` (`points_per_month`). Tidak dihapus sekarang,
  di luar permintaan eksplisit.

### 7b — Tambah `Msg.AUTHORIZED_ONLY`

- **File:** `shared/messages.py` (file utuh, gantikan versi Tahap 4)
- **Perubahan:** tambah `AUTHORIZED_ONLY` sebagai konstanta biasa
  (bukan method — tidak butuh harga, jadi tetap dipanggil tanpa
  kurung: `Msg.AUTHORIZED_ONLY`, sama seperti pemanggilan yang sudah
  ada di `is_authorized()` — **tidak perlu ubah `checks.py` lagi**,
  sudah otomatis benar begitu file `messages.py` ini di-replace).
- **Dampak:** command yang pakai `@is_authorized()` (`/permission`,
  `/structure`, dll) tidak lagi crash `AttributeError` kalau dipanggil
  user tanpa izin — sebelumnya bakal `AttributeError: type object
  'Msg' has no attribute 'AUTHORIZED_ONLY'` di titik itu.

---

## ✅ Semua item (inti + opsional) selesai

Total file final yang perlu di-apply ke repo:

| File | Status |
|---|---|
| `features/membership/pricing_presets.yml` | baru |
| `shared/config.py` | replace |
| `features/membership/support/product_loader.py` | replace |
| `shared/messages.py` | replace (final, termasuk `AUTHORIZED_ONLY`) |
| `shared/checks.py` | replace |
| `features/social/info_cog.py` | replace |
| `features/social/info_commands.yml` | replace |
| `features/membership/membership_settings.yml` | replace (`price_rp` dihapus) |
| `features/gatekeeper/gatekeeper_cog.py` | 1 baris find-replace |
| `features/dictionary/bunpou_cog.py` | 2 baris find-replace |
| `features/dictionary/kotoba_cog.py` | 2 baris find-replace |
| `features/dictionary/kanji_cog.py` | 2 baris find-replace |

Yang tersisa murni keputusan bisnis (preset mana yang aktif, kapan
promo launch berakhir), bukan lagi kerjaan kode.

---

## 10. Tahap 8 — Audit Dead Config / Dead Code Menyeluruh

**Cakupan:** diminta eksplisit "beresin semua dead config/dead code
dimana pun itu filenya" — dikerjakan dengan aturan ketat: **cuma
dihapus/diubah kalau bisa dibuktikan nol caller/pembaca di seluruh kode
yang ada di konteks pengerjaan ini.** Yang meragukan dilaporkan tapi
TIDAK disentuh (lihat bagian "Tidak disentuh" di bawah) — audit
codebase ~15.000 baris tanpa akses grep langsung ke repo asli punya
risiko false-positive, jadi kehati-hatian diprioritaskan di atas
kelengkapan yang tidak bisa dijamin 100%.

### Ditemukan & diperbaiki

| # | Apa | Lokasi | Kenapa dead |
|---|---|---|---|
| 1 | Field `price_rp` | `membership_settings.yml` (roles.*, lifetime) | Tidak ada caller yang baca key ini dari `get_tier_info()` maupun akses langsung — sudah dihapus Tahap 7 |
| 2 | Field `points` | `membership_settings.yml` (roles.trial/traveler/companion) | Poin sungguhan datang dari `products.yml`/`pricing_presets.yml`, field ini tidak pernah dibaca |
| 3 | `Msg.AUTHORIZED_ONLY` **hilang** (bukan dead, tapi *missing*) | `shared/messages.py` | Dipanggil `is_authorized()` di `checks.py` tapi tidak pernah didefinisikan — bug lama, ditambahkan Tahap 7 |
| 4 | Fungsi `get_tier_info()` | `shared/config.py` | **Nol caller** di seluruh codebase — tidak ada satupun cog yang import/panggil fungsi ini |
| 5 | Field `name`, `duration_days` (roles.*) | `membership_settings.yml` | Cuma bisa dibaca lewat `get_tier_info()` yang sudah terbukti dead (poin 4) — nama & durasi sungguhan ada di `products.yml` |
| 6 | Field `lifetime.name` | `membership_settings.yml` | Sama seperti poin 5 |
| 7 | Field top-level `trial_duration_days` | `membership_settings.yml` | Tidak ada fungsi accessor (`get_trial_duration_days()`) di `config.py` manapun — durasi trial 5 hari di-hardcode langsung sebagai parameter di `service.py` `grant_trial()` |
| 8 | Field `short_id` (7 entri) | `features/immersion/support/media_types.py` (`MEDIA_TYPES`) | Ditelusuri seluruh fitur immersion (log/stats/goals/bar_races/helpers/autocomplete) — tidak ada satupun yang baca `MEDIA_TYPES[...]['short_id']` |

**File final yang berubah karena audit ini:** `shared/config.py`
(hapus `get_tier_info()`), `membership_settings.yml` (final, jauh lebih
ramping — cuma `role_id`/`point_threshold`/config operasional yang
tersisa), `features/immersion/support/media_types.py` (hapus
`short_id`).

### Ditemukan tapi TIDAK disentuh (butuh keputusan kamu / risiko lebih tinggi)

- **`server_map.yml`** — banyak entri `channels:`/`roles:` yang tidak
  terlihat dipanggil lewat `get_channel_id()`/`get_role_id()` di kode
  yang aku telusuri (mis. `welcome_and_rules`, `general`, `grammar_dic`,
  dst). **TAPI ini beda sifat dari dead config di atas** — file ini
  didesain sebagai peta ID lengkap seluruh server (komentarnya sendiri
  bilang "satu-satunya sumber ID role & channel Discord"), dan sebagian
  channel di-resolve lewat *nama Discord literal* di
  `permission_table.py`/`structure_cog.py` (`get_channel_by_name()`),
  bukan lewat key YAML ini. Menghapus entri di sini berisiko tinggi
  kalau ternyata ada pemanggil yang tidak sempat tertelusuri penuh di
  codebase sebesar ini — **sengaja tidak disentuh**, cukup jadi catatan.
- **`MembershipRow.is_expired`** (properti di
  `features/membership/support/models.py`) — tidak ketemu caller-nya
  (yang dipakai di tempat lain cuma `.is_active`), tapi ini properti
  utilitas ringan, bukan angka config yang bisa menyesatkan kalau
  dibiarkan (beda risiko dari `price_rp` dkk) — kemungkinan memang
  disiapkan untuk kebutuhan mendatang. Tidak dihapus.
- **`gatekeeper_settings.yml`** — field `combination_rank`/
  `quizzes_required` di kode `gatekeeper_cog.py`/`journey_service.py`
  siap dipakai, tapi saat ini **tidak ada satupun entri kuis** dengan
  `combination_rank: true` di YAML. Ini bukan dead code (kodenya jalan
  kalau datanya diisi), cuma fitur yang belum ada datanya — tidak
  relevan untuk dihapus.

### Tindak lanjut 2 temuan yang sempat digantung

- **`MembershipRow.is_expired`** → **dihapus**. File:
  `features/membership/support/models.py` (file utuh). Ini properti
  Python murni, jadi bisa ditelusuri dengan pasti (bukan YAML config
  yang penuh kemungkinan jalur akses tidak langsung) — nol caller di
  `admin_cog.py`, `purchase_cog.py`, `scheduler_cog.py`, `service.py`.
  Semua tempat yang butuh cek status pakai `.is_active` (kebalikannya)
  atau bandingkan `expires_at` langsung. Kode lama ditinggal sebagai
  komentar kalau suatu saat perlu dikembalikan.
- **`server_map.yml`** → **tetap tidak disentuh**, sesuai arahan:
  hanya beresin yang benar-benar bisa dipastikan dead. File ini beda
  karakter dari kasus lain di atas — banyak entrinya diakses lewat
  pencocokan nama channel Discord literal di `permission_table.py`
  (bukan lewat key YAML langsung), jadi status "dipakai atau tidak"
  tidak bisa dipastikan dengan tingkat keyakinan yang sama seperti
  properti Python biasa. Dibiarkan.

---

## ✅ Status akhir: semua yang bisa dipastikan dead sudah dibersihkan

Total file final (pricing + dead code cleanup):

| File | Status |
|---|---|
| `features/membership/pricing_presets.yml` | baru |
| `shared/config.py` | replace (final — `get_active_prices()` + tanpa `get_tier_info()`) |
| `features/membership/support/product_loader.py` | replace |
| `shared/messages.py` | replace (final — termasuk `AUTHORIZED_ONLY`) |
| `shared/checks.py` | replace (final — `MSG_DIC_DETAIL_ONLY()` dinamis) |
| `features/social/info_cog.py` | replace |
| `features/social/info_commands.yml` | replace |
| `features/membership/membership_settings.yml` | replace (final — ramping, cuma field yang beneran dipakai) |
| `features/immersion/support/media_types.py` | replace (final — tanpa `short_id`) |
| `features/membership/support/models.py` | replace (final — tanpa `is_expired`) |
| `features/gatekeeper/gatekeeper_cog.py` | 1 baris find-replace |
| `features/dictionary/bunpou_cog.py` | 2 baris find-replace |
| `features/dictionary/kotoba_cog.py` | 2 baris find-replace |
| `features/dictionary/kanji_cog.py` | 2 baris find-replace |

Sisa kerjaan murni keputusan bisnis (preset harga aktif, deadline
promo) — tidak ada lagi dead config/dead code yang tersisa dari yang
bisa dipastikan dalam audit ini.
