# SMOKE TEST — dijalankan di server sungguhan

Bukan test suite baru. Ini enam pemeriksaan manual untuk memastikan kontrak yang sudah
terbukti di Python **selamat melewati lingkungan Discord** — satu-satunya lapis yang
tidak bisa diuji dari luar.

```
local unit tests -> production-path tests -> Git -> VPS -> Discord -> DI SINI
```

## Persiapan

```bash
unzip database_nihongo.zip -d data/ && mv data/database_nihongo data/kamus_nihongo
python3 scripts/verifikasi_artefak.py database_nihongo.zip database/VERSI.json
export KOTABI_KAMUS_V2=1 KOTABI_DB_NIHONGO=data/kamus_nihongo
```

---

## 1 · Command muncul

Ketik `/` di server. Harus ada **`/kanji2` `/kotoba2` `/bunpou2`**.

- [ ] ketiganya muncul
- [ ] `/kanji` `/kotoba` `/bunpou` lama **masih ada dan masih bekerja**

> Kalau v2 tidak muncul: cek log startup. Harusnya
> `✅ kamus v2 aktif (mode=1, perintah: /kanji2 /kotoba2 /bunpou2)`.
> Kalau `❌ ... tidak ada`, path database salah.

## 2 · `/kanji2 妨`

- [ ] embed tampil, tidak error
- [ ] **arti Indonesia terlihat** — "mengganggu, menghalangi, menghambat, mencegah"
- [ ] baris level: `7画 · JLPT N1 · 漢検3 · 常用`
- [ ] tombol tampil: `📖 Detail` `✏️ 筆順` `🔎 Sumber`
- [ ] **tidak ada** `_tingkat` atau `_domain` di mana pun

## 3 · Tombol tingkat — yang paling penting

Klik berurutan: **Detail → Sumber → Kembali**

- [ ] tiap klik **mengedit pesan yang sama**, tidak mengirim pesan baru
- [ ] setelah kembali, L1 **sama persis** dengan yang pertama muncul
- [ ] judul tetap 妨 di semua tingkat

> Ini invariant yang paling mudah rusak di Discord tapi lolos di Python.
> Kalau pesan baru bermunculan, `edit_message` gagal — kirim log-nya.

## 4 · Tombol navigasi `/kanji2 ⽉`

- [ ] muncul "Ini bentuk **radikal**, bukan kanji. Kanjinya: **月**"
- [ ] tombol `Lihat 月`
- [ ] klik → **pindah ke kartu 月**, bukan tetap di ⽉
- [ ] di kartu 月, tombol `📖 Detail` bekerja terhadap **月**, bukan ⽉

## 5 · `/kotoba2 走った`

- [ ] judul kartu **走る**
- [ ] baris `← 走った (bentuk terkonjugasi)` **terlihat**
- [ ] arti Indonesia: "berlari; melaju, berjalan (kendaraan)"

## 6 · `/bunpou2 あげる`

- [ ] **接続** muncul di L1: `Ｎを＋あげる`
- [ ] arti Indonesia: "memberi, menyerahkan"
- [ ] tombol `📚 4 sumber`; klik salah satu → balasan ephemeral

---

## Kalau semua lolos

Dictionary V2 = **production-verified**, bukan sekadar tested code.

Lalu **berhenti**. Jangan test suite kelima, jangan percantik L3, jangan ganti `kata`
jadi `kotoba`, jangan kejar gap yang sudah masuk `BATASAN_DIKETAHUI.md`.

Berikutnya: **Gatekeeper → Quiz → Progress → Membership → Immersion.**

## Kalau ada yang gagal

Catat **nomor pemeriksaan + apa yang terlihat**, lalu lacak berurutan:

```
1. datanya memang salah?
2. resolver ambil field salah?
3. resolver pilih sumber salah?
4. query gagal menemukan entitas?
5. renderer salah menerjemahkan struktur?
6. adapter Discord gagal kirim/edit?
```

Nomor 1–5 sudah dijaga empat lapis tes. Jadi kegagalan di sini **kemungkinan besar
nomor 6** — dan itu memang lapis yang belum pernah teruji.
