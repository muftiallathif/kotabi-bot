# `tests/`

Belum ada test suite formal di repo ini. Berkas di sini adalah **benih**-nya —
dimulai dari invariant yang paling mahal kalau rusak, bukan dari coverage.

| Berkas | Menguji |
|---|---|
| `uji_transaksi.py` | reload yang gagal di tengah **tidak boleh** mengosongkan kamus |

Dijalankan terhadap SQLite sungguhan, bukan mock:

```bash
python3 tests/uji_transaksi.py
```

## Kenapa ini yang pertama

`RUN()` dan `RUN_MANY()` masing-masing commit sendiri. Jadi:

```
RUN(DELETE_ALL)      -> COMMIT   <- kamus sudah kosong, permanen
RUN_MANY(INSERT)     -> gagal
```

Terbukti di uji: cara lama meninggalkan **0 entri**, cara baru (`TRANSAKSI()`)
mengembalikan **3 entri utuh**.

## Berikutnya

23 kartu + 10 rute tombol yang sudah terbukti bekerja (`/kanji 妨 愛 螺 𠮟 猫 ⽉`,
`/word 猫 取る 生 走った`, `/bunpou あげる かもしれない`) adalah **behavioral
contract**, bukan "pernah dicoba". Bekukan jadi regression suite sebelum refactor
dictionary — supaya refactor punya jaring.
