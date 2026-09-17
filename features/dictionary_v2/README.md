# `features/dictionary_v2/` — dictionary dari `database_nihongo`

**MATI secara bawaan.** Repo tidak berubah sampai kamu menyalakannya sendiri.

## Kenapa opt-in, bukan mengganti cog lama

`features/dictionary/` sudah punya `/kanji`, `/kotoba`, `/bunpou` yang **jalan dan
dipakai**. Modul ini menawarkan perintah dengan nama yang sama dari sumber berbeda — `database_nihongo`,
bukan CSV — dan namanya bertabrakan di dua tempat.

Mengganti kode yang bekerja dengan kode yang **belum pernah jalan di Discord** adalah
arah yang salah, berapa pun contract test yang lolos. Jadi keduanya bisa hidup
berdampingan dulu sampai kamu sendiri membandingkannya.

## Menyalakan

```bash
# 1. siapkan database (lihat database/README.md)
unzip database_nihongo.zip -d data/
mv data/database_nihongo data/kamus_nihongo
python3 scripts/verifikasi_artefak.py database_nihongo.zip database/VERSI.json

# 2. nyalakan
export KOTABI_KAMUS_V2=1          # -> /kanji2 /kotoba2 /bunpou2 (berdampingan)
export KOTABI_DB_NIHONGO=data/kamus_nihongo
```

| `KOTABI_KAMUS_V2` | Akibat |
|---|---|
| `0` / tidak diset | cog **tidak dimuat**, tidak ada yang berubah |
| `1` | aktif sebagai `/kanji2` `/kotoba2` `/bunpou2` |
| `takeover` | memakai `/kanji` `/kotoba` `/bunpou` — **hanya setelah cog lama dinonaktifkan**, kalau tidak Discord menolak sync |

Keempat keadaan sudah diuji, termasuk database tidak ada → gagal rapi dengan pesan
yang menyebutkan langkah perbaikannya, bukan traceback.

## Penyajian 3 tingkat

| | Isi |
|---|---|
| **L1** | identitas, bacaan, arti Indonesia, 1 bukti penggunaan |
| **L2** | struktur, 部首, relasi, jukugo / contoh kalimat / 解説 |
| **L3** | klasifikasi, frekuensi, アクセント, daftar sumber |

Kontrak L1 **berbeda per domain**, diturunkan dari sifat masing-masing:

- `/kanji` — identitas + bacaan + arti
- `/kotoba` — arti; kalau lemma diselesaikan (走った→走る), **bentuk yang dicari wajib
  terlihat**, kalau tidak user mengira salah ketik
- `/bunpou` — arti + **接続**; daftar sumber jadi tombol, bukan blok teks

## Menguji tanpa Discord

```bash
cd features/dictionary_v2/support
python3 uji_tingkat.py        /path/ke/data/kamus_nihongo   # kontrak isi
python3 uji_adapter.py        /path/ke/data/kamus_nihongo   # state & bolak-balik
python3 uji_jalur_produksi.py /path/ke/data/kamus_nihongo   # discord.Embed sungguhan
```

### Kenapa `/kotoba`, bukan `/word`

言葉 mencakup kata, frasa, dan ungkapan — sesuai isi datanya (猫, 走る, お元気ですか,
〜に違いない). `/word` menyiratkan kosakata satu kata saja. Sekaligus menjaga
identitas Kotabi tetap satu bahasa: kanji / kotoba / bunpou.

Nama internal domain tetap `kata` di resolver/adapter/tes — itu urusan kode.

Hasil terakhir: **28 golden case → 97 payload Discord, 231 tombol, semua PASS.**
Bukti di `BUKTI_KONTRAK_UX.txt`; batasan yang diketahui di `BATASAN_DIKETAHUI.md`
(tidak ada blocker terbuka).

## Batas tanggung jawab

```
support/resolver.py    satu pintu ke database, tidak tahu Discord
support/renderer3.py   isi L1/L2/L3, tidak impor discord.py
support/adapter3.py    state tingkat, tombol, edit pesan
kamus_v2_cog.py        wiring ke KotabiBot — satu-satunya yang tahu Cog
```

Pemisahan ini nyata, bukan niat: `uji_adapter.py` mengimpor `adapter3` **tanpa
discord.py terpasang sama sekali**.
