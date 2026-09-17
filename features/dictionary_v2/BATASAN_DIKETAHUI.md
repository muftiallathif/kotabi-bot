# BATASAN YANG DIKETAHUI — dictionary vertical

Dicatat, **bukan** alasan menunda rilis. Klasifikasi mengikuti Definition of Done:
🔴 blocker · 🟠 important · 🟡 known limitation · 🟢 nice-to-have

Tidak ada 🔴 yang terbuka.

---

## 🟡 Data belum lengkap

| ID | Hal | Angka | Dampak |
|---|---|---|---|
| D-01 | Kanji tanpa arti Indonesia | 3.003 dari 53.303 punya arti ID | L1 jatuh ke arti Inggris. **Seluruh 2.136 jōyō sudah ada** — kanji yang terdampak praktis tidak muncul dalam belajar |
| D-02 | Kosakata tanpa arti Indonesia | 10.562 dari 1.338.958 | L1 menampilkan `-# arti Indonesia belum ada — kata ini di luar daftar belajarmu` |
| D-03 | Pola tata bahasa tanpa arti ID | 632 dari 3.765 punya | L1 jatuh ke penjelasan sumber |
| D-04 | `U+FFFD` tersisa | 44 | di tengah prosa; bukti internal tidak cukup untuk memulihkan tanpa menebak |
| D-05 | Gaiji PUA `kogo_klasik` | 45.047 | tampil sebagai kotak kosong; pemetaan ke Unicode tidak bisa dipulihkan dari font |
| D-06 | Konflik goresan K-003 | 10 kanji | 遡=13 atau 14 — keputusan **produk** (bentuk glif acuan), bukan data |

## 🟠 Terbatas tapi berfungsi

| ID | Hal | Catatan |
|---|---|---|
| L-01 | `bentuk_konjugasi` tidak 100% | bentuk bertumpuk (食べさせられる) tidak ada; butuh deinflection berbasis aturan |
| L-02 | Level JLPT kosakata dari 4 daftar berbeda | konflik 49%; resolusi K-001 memilih deck user, dicatat di `resolusi_konflik.json` |
| L-03 | SVG goresan dikirim sebagai berkas | Discord tidak merender SVG inline; butuh konversi PNG kalau mau tampil di embed |

## 🟢 Diparkir

- isi L2/L3 bisa diperkaya — **sengaja tidak dibekukan**
- `/bunpou` perbandingan antar-sumber berdampingan
- autocomplete untuk ketiga command

---

## Yang TIDAK termasuk batasan

Ini sudah selesai dan tidak perlu dibuka lagi:

```
baseline database tervalidasi   65/65 provenance COCOK 100%
tiga vertical usable            97 payload Discord terverifikasi
kontrak L1 dibekukan            per domain, ditegakkan mesin
production path teruji          discord.Embed sungguhan
known limitations               berkas ini
```

→ **SHIP.** Database berkembang sebagai versi; bot dipakai sekarang.
