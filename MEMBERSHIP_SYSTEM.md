# MEMBERSHIP_SYSTEM.md — Sistem Membership Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** filosofi & prinsip desain monetisasi, alur
> pembelian `/subscribe`, anti-fraud bukti transfer, command admin,
> tugas otomatis (scheduler), ringkasan struktur database membership,
> cara menambah produk baru, keputusan strategi final (tier, threshold,
> akses kamus, quiz rank-up), known issues
> **BUKAN sumber untuk:** harga aktual tier VIP (lihat
> `PRICING_SYSTEM_REFACTOR.md` — jangan tulis ulang angka Rupiah statis
> di sini, selalu arahkan ke sana), detail skema tabel SQL lengkap
> (lihat `DATABASE_SCHEMA.md`), detail sistem kuis kasta di luar aspek
> gating VIP-nya (lihat `GATEKEEPER_QUIZ_SYSTEM.md`)
> **Terakhir diverifikasi terhadap kode:** 2026-07-21 — setiap klaim
> "sudah di kode" di dokumen ini dicek langsung terhadap isi cog/support
> file yang bersangkutan, bukan disalin mentah dari dokumen lama.

Menggantikan `MEMBERSHIP_FEATURE_GUIDE.md`, `KOTABI_MEMBERSHIP_SYSTEM_v3.md`,
dan `MEMBERSHIP_STRATEGY_DECISIONS.md` (ketiganya jadi Arsip — lihat
`DOCS_INDEX.md`). Digabung karena tiga dokumen itu terbukti bisa punya
klaim status yang saling kontradiksi tanpa disadari (lihat bagian 8 —
ternyata *semua* item yang diklaim "belum dikerjakan" di dokumen lama
sudah selesai di kode).

---

## 1. Filosofi

**Kotabi tidak menjual akses channel. Kotabi menjual ekosistem belajar**
(AI, quiz, tracking, komunitas, immersion, event). Sistem membership ini
cuma "pipa" — yang membuat orang bertahan bayar adalah fitur yang
dipakai harian, bukan detail harga/poin.

### 1.1 Empat prinsip inti monetisasi

Semua keputusan tier/harga/gating di dokumen ini tunduk pada empat
prinsip berikut. Kalau ada usulan baru yang bertentangan dengan salah
satu, itu sinyal untuk mikir ulang, bukan langsung diterapkan.

**Freemium = "percepatan", bukan "gembok".** Versi gratis harus tetap
cukup enak dipakai supaya orang betah dan mau cerita ke teman.
Monetisasi menyasar progres, kenyamanan, dan status sosial (role, kamus
lanjutan, member area) — bukan mengunci alat belajar inti secara total.

**Bukan celah brutal, tapi tetap FOMO.** Batasan tier gratis harus
menutup penyalahgunaan brute-force (scraping, farming, bot otomatis) —
bukan menghambat pengguna wajar. FOMO sehat datang dari orang *melihat
ada lebih banyak* yang bisa dijangkau, bukan dari merasa dihalangi.
Kalau ada celah teknis yang memungkinkan orang melewati batasan yang
sudah didesain benar, itu wajib ditutup segera — bukan lagi soal
filosofi, itu bug keamanan.

**Jangan rugikan yang sudah subscribe.** Perubahan apa pun (harga,
threshold, aturan gating) tidak boleh membuat user yang sudah
bayar/berlangganan jadi lebih buruk posisinya dibanding sebelum
perubahan. Lihat `DEVELOPMENT_GUIDE.md` bagian 10 untuk checklist
konkretnya begitu server live.

**Jujur, bukan menyenangkan.** Lihat `DEVELOPMENT_GUIDE.md` bagian 11 —
prinsip ini berlaku umum ke semua diskusi project, bukan cuma
monetisasi, jadi dipindah ke sana. Ditulis pertama kali di dokumen ini.

---

## 2. Peta Folder

```
features/membership/
├── admin_cog.py          ← /admin grant-member, grant-trial, grant-batch,
│                            revoke-member, check-member, membership-history,
│                            /membership sync, background task expiry check
├── purchase_cog.py       ← /subscribe, alur draft → pending → approved,
│                            tombol approve/reject/resubmit di channel staff
├── scheduler_cog.py      ← draft timeout, pending order cleanup, role sync
├── membership_settings.yml   ← guild_id, bank account, role_id per tier,
│                                point_threshold, channel ID, grace period
├── products.yml          ← definisi semua produk yang bisa dibeli
├── pricing_presets.yml   ← SATU-SATUNYA sumber harga (lihat PRICING_SYSTEM_REFACTOR.md)
└── support/
    ├── models.py          ← dataclass MembershipRow, Order, Product, dst
    ├── repository.py      ← semua query SQL (tidak ada SQL mentah di cog)
    ├── service.py         ← business logic grant/revoke/preview
    ├── product_loader.py  ← baca products.yml + resolve harga dari preset
    ├── role_resolver.py   ← mapping tier → Discord role (TIER_ROLE_CHAIN)
    ├── fraud_check.py     ← perceptual hash anti-fraud bukti transfer
    ├── helpers.py         ← send_dm/fmt_price/fmt_progress (satu tempat,
    │                         dulu triplikat di 3 cog — lihat bagian 8)
    └── grants/
        ├── engine.py             ← GrantEngine, entry point tunggal grant
        ├── membership_handler.py ← proses blok "membership" dari payload
        └── point_handler.py      ← proses blok "point" dari payload
```

---

## 3. Tier & Fitur

**Harga tidak ditulis di sini** — lihat `PRICING_SYSTEM_REFACTOR.md`
(`pricing_presets.yml`, `active_preset`). Yang berikut ini murni gap
fitur struktural, bukan angka Rupiah:

| Fitur | Trial | Traveler | Companion | Patron |
|---|---|---|---|---|
| Rank-up quiz semua level | ✅ (5 hari) | ✅ | ✅ | ✅ |
| Immersion log, stats, goals | ✅ | ✅ | ✅ | ✅ |
| Kamus — mode list/browse (nama + level, tanpa arti) | ✅ | ✅ | ✅ | ✅ |
| Kamus — mode detail (arti, contoh, cara pakai) | ✅ | ❌ | ✅ | ✅ |
| Member lounge, deck-requests, immersion-race | ❌ | ❌ | ✅ | ✅ |
| Custom role warna sendiri | ❌ | ❌ | ✅ | ✅ |
| Expiry | 5 hari | 30 hari (atau 6bln/1thn) | 30 hari (atau 6bln/1thn) | Tidak pernah (lifetime) |

**Catatan gating kamus:** Trial dapat mode detail, Traveler **tidak**
(lihat `shared/checks.py` `has_dic_access()` — sengaja mengecualikan
`traveler` dari daftar role yang diizinkan). Ini konsisten di seluruh
3 command kamus (`/bunpou`, `/kotoba`, `/kanji`), sudah diverifikasi
sampai ke level dropdown "pilih untuk detail" (lihat bagian 8, celah
arsitektur yang sempat jadi perhatian khusus).

**Patron** didapat dua cara: beli langsung (harga tetap, sekali bayar,
tidak ada "harga upgrade" dari riwayat pembelian sebelumnya), atau
otomatis saat poin kumulatif mencapai threshold (`get_lifetime_threshold()`,
saat ini 24 — lihat `PRICING_SYSTEM_REFACTOR.md` untuk audit lengkap
soal field ini). Role Companion otomatis mencakup Traveler
(`TIER_ROLE_CHAIN` di `role_resolver.py`); Patron cuma dapat role Patron
sendiri (tidak mewarisi Companion/Traveler).

---

## 4. Alur Pembelian (`/subscribe`)

```
User /subscribe
    ↓
Pilih produk + jumlah (dropdown, termasuk varian 6bln/1thn — lihat PRICING_SYSTEM_REFACTOR.md)
    ↓
Bot tampilkan ringkasan order: produk, durasi, total harga,
preview poin sekarang→setelahnya, expiry sekarang→setelahnya
(Patron: field expiry diganti "Lifetime — tidak ada expiry")
    ↓
User klik "Lanjutkan" → order dibuat status DRAFT + kode unik nominal (order_id % 100)
    ↓
Bot tampilkan detail rekening bank + nominal final (harga + kode unik)
    ↓
User transfer manual di luar Discord
    ↓
User klik "Sudah Bayar" → modal isi bank/e-wallet pengirim
    ↓
Bot minta upload bukti transfer LEWAT DM (bukan channel publik — supaya
nominal/rekening di bukti tidak terlihat warga lain)
    ↓
User upload bukti → bot hitung perceptual hash (pHash)
    ↓
User klik "Konfirmasi Order" → status PENDING, baru masuk ke channel staff
    ↓
Embed muncul di channel staff: detail order + bukti transfer + total
seharusnya + ⚠️ warning otomatis kalau pHash mirip bukti order lain
    ↓
Admin cek mutasi rekening manual, cocokkan ke "Total seharusnya" order INI
(bukan sekadar "ada uang masuk ~segitu") — SOP wajib, jaring utama anti-fraud
    ↓
Admin klik Approve / Reject / Cancel
```

### Draft vs Pending vs Needs Resubmit

- **Draft** — order dibuat tapi belum dikonfirmasi user. Cuma terlihat
  user yang bersangkutan. Auto-cancelled kalau tidak dikonfirmasi dalam
  24 jam (`scheduler_cog.py` `draft_timeout_check`).
- **Pending** — sudah dikonfirmasi, masuk antrian review staff.
- **Needs Resubmit** — staff reject dengan alasan "bukti tidak
  valid/buram" (jalur A). Order **tidak** final ditolak — kode unik dan
  nominal tetap sama (user tidak perlu transfer ulang), tinggal upload
  ulang bukti lewat tombol di DM.
- **Rejected** — staff reject dengan alasan "lainnya" (jalur B). Final,
  immutable. User harus `/subscribe` baru (dapat `order_id` baru → kode
  unik baru) kalau masih mau lanjut.

### Kode Unik Nominal

2 digit terakhir dari `order_id % 100` ditambahkan ke nominal transfer,
supaya mutasi rekening gampang dicocokkan ke order yang tepat. Ini alat
bantu manual, **bukan validasi otomatis** — kalau nominal sedikit
meleset (salah ketik, pembulatan app banking), tetap boleh di-approve
kalau cocok dari konteks lain.

---

## 5. Anti-Fraud Bukti Transfer

Kasus yang dicegah: bukti transfer sah milik satu user dipakai/dipinjamkan
ke order user lain.

1. **Perceptual hash (pHash)** — dihitung pakai `imagehash` (bukan
   cryptographic hash), tetap terdeteksi mirip walau gambar di-crop/
   resize/ubah format. Dibandingkan (Hamming distance) ke semua bukti
   order lain di guild yang sama. Kalau mirip → warning di embed review,
   **bukan auto-reject** (tetap perlu judgment admin, hindari false
   positive).
2. **Kode unik nominal** (bagian 4) — jaring paling reliable, jalan
   otomatis dari desain sistem tanpa perlu deteksi tambahan.
3. **Bank pengirim** — dropdown yang diisi user saat upload bukti,
   sinyal tambahan untuk cross-check kalau nama pengirim di mutasi
   terasa janggal.

Yang sengaja **tidak** dipakai: OCR otomatis baca nominal dari gambar,
atau validasi API perbankan — over-engineering untuk volume order yang
masih kecil.

---

## 6. Command Admin

| Command | Fungsi |
|---|---|
| `/admin grant-member` | Grant membership langsung tanpa order |
| `/admin grant-trial` | Grant trial 5 hari (0 poin, cuma admin, bukan self-serve) |
| `/admin grant-batch` | Grant ke banyak user sekaligus |
| `/admin revoke-member` | Cabut membership, termasuk Patron lifetime — alasan bebas |
| `/admin check-member` | Cek status membership satu user |
| `/admin membership-history` | Lihat riwayat grant/revoke |
| `/admin membership-purge-history` | Hapus riwayat satu user (admin only) |
| `/admin reset-points` | Reset poin lifetime user ke 0 (tidak bisa untuk yang sudah Patron) |
| `/membership_sync` | Sinkronisasi role Discord dengan database — perbaiki kalau role tidak sinkron |
| `/orders` | Lihat order pending (staff) |
| `/my_orders` | User lihat riwayat order sendiri |

Semua command admin di sini dijaga `_can_manage()` (admin, `AUTHORIZED_USER_IDS`,
atau `moderator_role_ids` dari `membership_settings.yml`).

---

## 7. Tugas Otomatis (Scheduler)

| Task | Interval | Fungsi |
|---|---|---|
| `membership_expiry_check` (`admin_cog.py`) | 30 menit | Warning H-3 sebelum expired (skip trial), auto-expire + cabut role setelah lewat |
| `draft_timeout_check` (`scheduler_cog.py`) | 1 jam | Auto-cancel draft yang tidak dikonfirmasi 24 jam |
| `pending_order_check` (`scheduler_cog.py`) | 6 jam | Reminder staff (>3 hari pending), auto-cancel (>7 hari pending) |
| `role_sync_check` (`scheduler_cog.py`) | 24 jam | Diam-diam perbaiki role Discord yang tidak sinkron dengan database |

---

## 8. Known Issues — Status Terverifikasi Ulang

**Konteks kenapa bagian ini ditulis ulang:** dokumen lama
(`MEMBERSHIP_STRATEGY_DECISIONS.md` bagian 8) mencatat 5 item sebagai
"belum dikerjakan". Saat disusun ulang jadi dokumen ini, **kelimanya
dicek langsung ke kode aktual — dan ternyata sudah selesai semua.**
Dicatat di sini supaya tidak ada yang menganggap ulang "belum
dikerjakan" di masa depan.

| # | Isu | Klaim dokumen lama | Status verifikasi terhadap kode |
|---|---|---|---|
| 1 | Auto-expire tidak kembalikan role Drifter | ❌ Belum, prioritas sebelum launch | ✅ **Sudah benar** — `membership_expiry_check` FASE 2 di `admin_cog.py` sudah pakai `resolver.revoke_to_drifter()`, sama seperti `/admin revoke-member`. `sync_member()` di `role_resolver.py` juga sudah tambah role Drifter balik kalau `is_active=False`. |
| 2 | N+1 query di `role_sync_check`/`/membership_sync` | ❌ Belum dioptimasi | ✅ **Sudah fixed** — `MembershipRepository.get_all_memberships()` (1 query untuk seluruh guild) sudah dipakai di kedua tempat, menggantikan query per-member di dalam loop. |
| 3 | `unique_code` via re-query, risiko race condition | ❌ Belum diperbaiki | ✅ **Sudah fixed** — `create_draft_order()` di `repository.py` sudah pakai `bot.RUN_LASTROWID()` langsung dari operasi INSERT, bukan `SELECT ... ORDER BY created_at DESC LIMIT 1` yang rawan race condition. |
| 4 | Duplikasi `_send_dm`/`_fmt_price`/`_fmt_progress` di 3 cog | ❌ Belum disatukan | ✅ **Sudah fixed** — sekarang satu tempat di `support/helpers.py`, di-import oleh `admin_cog.py`, `purchase_cog.py`, `scheduler_cog.py`. |
| 5 | SQL mentah langsung di cog (`pending_order_check`, `membership_purge_history`) | ❌ Belum lewat `repository.py` | ✅ **Sudah fixed** — sekarang `MembershipRepository.has_recent_order_warning()` dan `.purge_history()`, dipanggil dari cog, tidak ada SQL mentah lagi di level cog. |

**Isu yang genuinely masih terbuka** (dicek, belum ada solusinya di kode):

- **Celah component-interaction kamus** — akses mode detail harus dicek
  di *setiap* titik masuk (command awal DAN dropdown "pilih untuk
  detail"), bukan cuma command awal. **Status: sudah beres** untuk
  `/bunpou`, `/kotoba`, `/kanji` — ketiganya sudah cek `has_dic_access()`
  di command handler *dan* di `*ListView._on_select()` masing-masing
  (`BunpouListView`, `KotobaListView`, `KanjiListView`). Dokumen lama
  sempat mencatat "`/kotoba` masih belum dibangun" — itu sudah tidak
  akurat, `/kotoba` sudah lengkap dengan pola gating yang sama.
- **Trial cycle bukan rolling 180 hari rata** — **Status: sudah
  diperbaiki**, `can_take_trial()` di `service.py` sekarang pakai
  `get_last_trial_claim()` + `TRIAL_ROLLING_WINDOW_DAYS = 180`, bukan
  cycle kalender tetap (`2026A`/`2026B` sekarang murni label historis
  di kolom `trial_cycle`, bukan penentu eligibility lagi).
- **Perbandingan "sisa poin vs beli langsung" di UI** — nice-to-have,
  prioritas rendah, belum diimplementasikan. Genuinely belum ada.
- **Harga kelas intensif (`jlpt_n5`, `jlpt_n4`, `kaiwa`)** — belum
  dievaluasi ulang bareng harga tier utama. Masih pertanyaan terbuka.

---

## 9. Cara Menambah Produk Baru

Semua produk didefinisikan di `features/membership/products.yml`. Baca
`PRICING_SYSTEM_REFACTOR.md` dulu kalau produknya adalah tier VIP
(traveler/companion/patron) — harga tier TIDAK ditulis manual di
`products.yml` lagi, di-resolve otomatis dari `pricing_presets.yml`
lewat `product_loader.py`.

**Untuk produk non-tier (kelas intensif, dsb):** cukup tambah entri baru
di `products.yml`, tidak perlu ubah kode:

```yaml
nama_produk_baru:
  id: nama_produk_baru
  name: "Nama Tampilan"
  version: v1
  type: class            # atau "membership" kalau grant tier
  price: 400000
  quantity_label: null
  min_quantity: 1
  max_quantity: 1
  grants:
    membership:
      tier: companion     # tier yang di-grant, bukan berarti bikin tier baru
      duration_days: 90
    point:
      amount: 2
```

`price` di sini **hanya berlaku untuk produk non-tier** (dibaca apa
adanya oleh `product_loader.py`) — untuk `traveler`/`companion`/`patron`,
field `price` di `products.yml` DITIMPA saat load, jangan andalkan
angka yang tertulis di situ.

Menambah produk baru **tidak pernah** mengubah order yang sudah ada —
approval selalu pakai `grant_payload` snapshot yang disimpan saat order
dikonfirmasi, bukan baca ulang `products.yml`.

---

## 10. Jaminan Data

- Database adalah source of truth, Discord hanya representasi.
- Order immutable setelah dikonfirmasi — sebelum itu masih draft, boleh
  dibatalkan user.
- Setiap perubahan membership dicatat di `membership_history_v1` lengkap
  kondisi sebelum-sesudah, termasuk revoke manual Patron.
- Approval selalu pakai snapshot `grant_payload` — perubahan harga/produk
  di YAML tidak mempengaruhi order yang sudah ada.
- Migrasi database additive, tidak destructive.

Detail lengkap semua tabel: `DATABASE_SCHEMA.md`.

---

## Riwayat Perubahan Signifikan

- **2026-07-21** — Dibuat dari penggabungan `MEMBERSHIP_FEATURE_GUIDE.md`
  + `KOTABI_MEMBERSHIP_SYSTEM_v3.md` + `MEMBERSHIP_STRATEGY_DECISIONS.md`.
  Semua klaim "belum dikerjakan" di dokumen lama diverifikasi ulang
  terhadap kode aktual — ditemukan 5 dari 5 item di bagian 8 ternyata
  sudah selesai (dokumen lama ketinggalan). Harga tier dipindah
  sepenuhnya ke `PRICING_SYSTEM_REFACTOR.md`, tidak ditulis ulang di
  sini untuk mencegah drift yang sama terulang.
