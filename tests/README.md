# tests/ — Regression Harness untuk Temuan Audit Keamanan

> Dokumen ini menjelaskan **cara kerja test suite**, bukan detail per
> finding — untuk itu lihat dokumen topik yang direferensikan tiap
> file test (`IMMERSION_SYSTEM.md`, `SOCIAL_SYSTEM.md`,
> `MODERATION_SYSTEM.md`, `SERVER_ADMIN_SYSTEM.md`).

**Konteks:** audit dokumentasi menyeluruh (Sep 2026) menemukan 7
finding keamanan/integritas nyata di kode produksi, semuanya
**belum diperbaiki** secara sengaja (lihat prinsip *audit →
document → classify → decide → fix → test* yang dipakai sepanjang
audit). Tujuan harness ini: membuktikan finding-finding itu secara
reproducible SEBELUM fase *decide/fix* — supaya nanti fase fix bisa
diverifikasi otomatis (assertion yang tadinya PASS karena membuktikan
bug, berubah FAIL setelah fix, lalu di-flip untuk assert behavior yang
benar), bukan cuma "kelihatannya sudah dibenerin".

## Cara menjalankan

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

`requirements-dev.txt` **terpisah** dari `requirements.txt` produksi —
`Dockerfile` cuma install `requirements.txt`, jadi `pytest`/
`pytest-asyncio` tidak ikut membengkakkan image produksi.

## ⚠️ Caveat reproducibility yang perlu diketahui

`requirements.txt` **tidak pin versi `discord.py`** (temuan engineering
tersendiri, dicatat di sini karena langsung relevan ke test). Harness
ini divalidasi terhadap `discord.py` 2.7.1 (versi 2.x stabil terbaru
saat harness dibuat) — **ini bukan konfirmasi versi produksi**, karena
tidak ada lockfile atau version pin yang menyatakannya. Kalau perilaku
`discord.py` yang diasumsikan test ini (lihat bagian "Cara kerja
Level A/B" di bawah) ternyata berbeda di versi produksi sesungguhnya,
itu sendiri layak jadi temuan baru — bukan alasan mengabaikan hasil
test ini begitu saja.

## Tiga level test — kenapa dipisah

Dikunci lewat eksperimen empiris (bukan asumsi) sebelum baris test
pertama ditulis — lihat riwayat commit untuk detail eksperimennya.

### Level A — Pure callback

```python
await SomeCog.some_command.callback(cog_instance, interaction, ...)
```

Memanggil badan fungsi command **langsung**, melewati seluruh mesin
check discord.py. Ini **secara sengaja** cuma menjawab "apa yang
dilakukan badan fungsi itu sendiri" — termasuk in-body check manual
(`if not has_authorized_access(...): return ...`), yang memang kode
Python biasa dan tetap jalan lewat jalur ini.

**Yang TIDAK diuji Level A**: decorator check (`@is_staff()`,
`@app_commands.checks.has_permissions(...)`) — decorator cuma
mendaftarkan predicate ke `command.checks`, tidak dievaluasi otomatis
kalau `.callback()` dipanggil langsung. Kalau cuma pakai Level A untuk
command yang authorization-nya lewat decorator, hasilnya **false
negative** — kelihatan seperti "tidak ada penolakan" padahal check-nya
memang ada, cuma tidak pernah dijalankan test-nya.

### Level B — Authorization composition

```python
allowed = await run_checks(command, interaction)  # dari conftest.py
```

Menjalankan `command.checks` satu per satu, meniru cara dispatch asli
discord.py — **tanpa** memanggil badan fungsi. Dibutuhkan karena
dikonfirmasi empiris ada **dua pola failure berbeda** di codebase ini:

| Check | Async? | Gagal dengan |
|---|---|---|
| `shared/checks.py` (`is_staff()`, `is_vip()`, dst) | Ya | `return False` (+ efek samping: kirim response) |
| `app_commands.checks.has_permissions()` (native discord.py, dulu dipakai `/backup_database` sebelum commit `bb3b698`) | Tidak | `raise app_commands.MissingPermissions` |

`run_checks()` di `conftest.py` menangani keduanya — falsy return ATAU
`app_commands.CheckFailure` (dan subclass-nya) sama-sama berarti
"ditolak". **Exception lain (`RuntimeError`, `AttributeError`, dst)
SENGAJA tidak ditangkap** — itu bug di predicate-nya sendiri, bukan
keputusan otorisasi, dan menelannya di harness akan menyembunyikan bug
produksi di balik hasil "ditolak" yang palsu.

**Satu command dianggap "tidak ada backstop otorisasi sama sekali"
cuma kalau Level A DAN Level B sama-sama tidak menolak** — lihat
`test_backup_database_permissions.py` untuk contoh nyata di mana
keduanya memang sengaja diuji berdampingan.

### Level C — State integration (belum ada file-nya)

Untuk bug yang sifatnya *state transition*, bukan otorisasi statis —
`rank_saver_cog.py` dan interaksinya dengan `/selfmute`. Polanya:

```
DB nyata (temp SQLite file, LIHAT DI BAWAH — bukan :memory:)
    +
repository/helper produksi yang sama (bot.RUN/GET/GET_ONE)
    +
mock boundary Discord (Interaction/Member/Role)
```

Belum dibangun — akan dikerjakan saat masuk finding #3/#4 (rank_saver).

## Kenapa DB pakai temp file, BUKAN `:memory:`

`core/bot.py` membuka **koneksi `aiosqlite` baru di setiap panggilan**
`RUN`/`GET`/`GET_ONE` (`async with aiosqlite.connect(self.db_path)`),
bukan satu koneksi persisten. SQLite `:memory:` terikat ke koneksi yang
membuatnya — begitu koneksi ditutup, datanya hilang. Karena pola
produksi buka-tutup koneksi per panggilan, `:memory:` akan membuat tiap
`RUN`/`GET` seolah-olah database kosong yang terpisah, tidak nyambung
satu sama lain. **Dikonfirmasi lewat baca kode langsung, bukan
diasumsikan** — lihat `conftest.py`'s `tmp_db_path` fixture.

## Filosofi fixture: primitif, bukan keputusan bisnis

`conftest.py` cuma menyediakan `interaction_factory` (`make_interaction(user_id=..., is_admin=..., roles=...)`) — **bukan** fixture siap pakai seperti `staff_interaction`/`admin_interaction`. Tiap test file menyatakan sendiri kombinasi actor/resource yang relevan untuk finding-nya — supaya fixture generik tidak diam-diam mengandung asumsi bisnis (mis. "role ID sekian = staff") yang beda-beda tiap finding.

Untuk config/role ID yang perlu diisolasi dari `server_map.yml`/`membership_settings.yml` produksi:
- `shared/config.py` sudah punya `reload_config()` — dipakai lewat fixture kalau test butuh config YAML terisolasi.
- `shared/checks.py`'s `AUTHORIZED_USER_IDS` **dihitung sekali saat modul di-import** dari env var — `monkeypatch.setenv(...)` setelah import **tidak berefek**. Harus `monkeypatch.setattr(shared.checks, "AUTHORIZED_USER_IDS", {...})` langsung ke atributnya.

## Pola "reproduction test", bukan "acceptance test"

Test yang target behavior-nya **sudah jelas/tidak kontroversial** dari
kontrak yang sudah dinyatakan (mis. `/backup_database` — jelas
seharusnya balik ditegakkan backend; `/log_export`/`/logs`/`/log_stats`
— UI-nya sendiri sudah bilang "Khusus Staf") ditulis sebagai
**reproduction test**: assertion-nya membuktikan behavior SAAT INI
(yang salah), dengan pesan assertion yang menjelaskan itu eksplisit.
Begitu fix diterapkan, assertion ini **diharapkan mulai gagal** — itu
sinyal untuk membalik assertion-nya jadi assert behavior yang benar,
bukan menghapus test-nya.

Test untuk finding yang target behavior-nya **masih pertanyaan desain
terbuka** (`rank_saver` — scope sempit vs lebar; `/kneelderboard` —
block total vs gate staff vs redact) **belum ditulis sama sekali**
sampai keputusan desainnya diambil eksplisit — supaya test suite tidak
diam-diam melakukan fase *decide* yang belum pernah didiskusikan.

## Pola tambahan yang muncul dari finding #2

- **Authorization dan visibility selalu jadi class/assertion
  terpisah**, bahkan kalau root cause-nya berdekatan (lihat
  `TestLogExportAuthorization` vs `TestLogExportVisibility` di
  `test_immersion_export_stats_permissions.py`) — supaya fix yang
  mengubah *siapa boleh* tidak otomatis dianggap juga memperbaiki
  *bagaimana hasilnya ditampilkan*, atau sebaliknya.
- **Sanity-check arah sebaliknya** ditambahkan kalau relevan (mis.
  `test_level_b_non_vip_is_still_rejected` untuk `/log_export`) — supaya
  test tidak melebih-lebihkan temuan. `/log_export`/`/logs` punya gate
  yang salah populasi (VIP, bukan staff), BUKAN "tanpa gate sama
  sekali" seperti `/log_stats` — dua finding yang beda, jangan
  dicampur jadi satu klaim generik.
- **Mocking cuma untuk mesin yang benar-benar incidental** terhadap
  finding yang diuji — `/log_stats`'s chart rendering (matplotlib/
  seaborn) di-mock karena bukan itu yang diuji (authorization +
  visibility respons, bukan isi grafiknya), sementara layer DB tetap
  SQLite temp file asli. Jangan mock sesuatu cuma karena "lebih cepat"
  kalau itu bagian dari apa yang sedang dibuktikan.
- **Isolasi config eksplisit** (`isolated_role_config` fixture) —
  `get_staff_role_ids()`/`get_vip_role_ids()` di-patch ke mapping
  tetap yang dikontrol test, bukan bergantung pada isi
  `server_map.yml`/`membership_settings.yml` produksi yang sesungguhnya
  (supaya test tidak diam-diam rusak kalau seseorang mengedit config
  asli, dan tidak diam-diam salah kalau config asli kebetulan berubah
  bentuk).

## Status per finding

| # | Finding | Dokumen | Level A | Level B | Level C |
|---|---|---|---|---|---|
| 1 | `/backup_database` authorization regression | `SERVER_ADMIN_SYSTEM.md` §2 | ✅ | ✅ | N/A |
| 2 | `/log_export`/`/logs`/`/log_stats` "Khusus Staf" tidak ditegakkan + non-ephemeral | `IMMERSION_SYSTEM.md` §14 | ✅ | ✅ | N/A |
| 3 | `rank_saver` — role staff auto-restore | `SOCIAL_SYSTEM.md` §10 | ⏳ | N/A | ⏳ (scope A/B belum diputuskan) |
| 4 | `rank_saver` ↔ `/selfmute` | `MODERATION_SYSTEM.md` §4 | ⏳ | N/A | ⏳ |
| 5 | `/solved` tanpa otorisasi | `MODERATION_SYSTEM.md` §2 | ⏳ | ⏳ | N/A |
| 6 | `/kneelderboard` cross-guild | `SOCIAL_SYSTEM.md` §3 | ⏳ | ⏳ | N/A (scope belum diputuskan) |
| 7 | `/say` permission laundering via `channel` | `SERVER_ADMIN_SYSTEM.md` §4.4 | ⏳ | ⏳ | N/A |

Belum ada satu pun fix diterapkan ke kode produksi — semua file di
`features/`/`shared/` di luar `tests/` tetap seperti kondisi audit.
