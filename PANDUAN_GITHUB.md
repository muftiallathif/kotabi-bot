# Apa yang masuk GitHub, apa yang tidak

## ✅ MASUK GitHub — isi `kotabi-bot-phase-c1c.zip`

Seluruh isi arsip itu **kecuali** yang sudah ditutup `.gitignore`. Ukurannya ~5,5 MB.

```
kotabi-bot/
├── core/              main/setup/bot  (TRANSAKSI() baru di bot.py)
├── features/          semua fitur, termasuk dictionary_v2/ yang baru
├── shared/
├── scripts/           build_kamus · verifikasi_artefak · buat_manifest
├── database/          README.md · VERSI.json     (metadata saja, bukan datanya)
├── tests/             uji_transaksi.py
├── fonts/
├── .gitignore
└── PANDUAN_GITHUB.md
```

## ❌ JANGAN masuk GitHub

| Berkas | Ukuran | Kenapa |
|---|---|---|
| `database_nihongo.zip` | **548 MB** | Git menyimpan SETIAP versi selamanya. Sekali di-commit, permanen di history; satu-satunya cara menghapus adalah rewrite history |
| `data/kamus_nihongo/` | ~2,8 GB terekstrak | idem |
| `data/*.sqlite3` | | hasil build, bisa dibuat ulang |
| 6.699 berkas SVG | 28,7 MB | aset, ikut di dalam artefak database |

Semuanya sudah ditutup `.gitignore`. **Jangan pakai `git add -f` pada berkas-berkas itu.**

## Cara memeriksa sebelum `git push`

```bash
git add -A
git status --short | head -30
du -sh .git

# berkas terbesar yang akan di-commit — semuanya harus di bawah ~1 MB
git diff --cached --name-only | xargs -I{} du -h {} 2>/dev/null | sort -rh | head
```

⚠️ Kalau ada berkas puluhan/ratusan MB muncul, **batalkan**: `git reset` lalu perbaiki
`.gitignore` dulu.

## Catatan: 4 CSV lama sudah ter-commit di repomu

```
features/dictionary/kanji_master.csv          10,5 MB
features/dictionary/kotoba-notes-master.csv    5,1 MB
features/dictionary/bunpou-notes-master.csv    1,7 MB
features/dictionary/kanji_meanings_id.csv
```

Totalnya ~17 MB dan sudah ada di history. **Biarkan saja** — cog lama membutuhkannya,
dan menghapusnya sekarang butuh rewrite history untuk keuntungan yang kecil. Yang
penting: jangan menambah yang lebih besar.

## Cara database sampai ke VPS

```bash
git pull                                    # kode saja

# artefak database diunduh/disalin terpisah, lalu:
cat db_nihongo_FINAL.zip.part0{0,1,2} > database_nihongo.zip
sha256sum database_nihongo.zip              # cocokkan dgn db_nihongo_FINAL.manifest.txt
python3 scripts/verifikasi_artefak.py database_nihongo.zip database/VERSI.json

unzip database_nihongo.zip -d data/
mv data/database_nihongo data/kamus_nihongo

export KOTABI_KAMUS_V2=1 KOTABI_DB_NIHONGO=data/kamus_nihongo
# lalu ikuti features/dictionary_v2/SMOKE_TEST.md
```

Simpan artefak database di GitHub **Releases** atau penyimpanan objek — bukan di dalam
repo. Releases memang untuk berkas besar dan tidak menambah ukuran history.
