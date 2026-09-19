# KOTABI_SYSTEM_MAP.md — Peta Sistem Kotabi Bot

> **Status:** Aktif
> **Sumber kebenaran untuk:** gambaran Kotabi sebagai satu produk
> Discord utuh — Discord UX ↔ command ↔ feature ↔ role/permission ↔
> database ↔ dependency lintas-fitur — plus gap/overlap/known-issue
> level sistem yang cuma kelihatan kalau semua dokumen topik dilihat
> bersamaan
> **BUKAN sumber untuk:** detail teknis per fitur (selalu link ke
> dokumen topik aslinya — dokumen ini SENGAJA tidak mengulang detail
> yang sudah ada di sana), keputusan desain final (lihat §12, masih
> backlog), commit history/kode line-level (lihat dokumen topik +
> `COMMANDS.md`)
> **Terakhir diverifikasi terhadap kode:** N/A — dokumen ini **sintesis
> dari dokumen lain yang sudah terverifikasi** (`DOCS_INDEX.md`,
> `COMMANDS.md`, `PERMISSION_MATRIX.md`, `DATABASE_SCHEMA.md`, 8
> dokumen topik fitur, `tests/README.md`), bukan audit kode baru. Kalau
> ada ketidaksesuaian antara dokumen ini dan dokumen sumber, dokumen
> sumber yang benar — perbarui dokumen ini, bukan sebaliknya.

**Kenapa dokumen ini ada:** setelah audit dokumentasi 8 fitur + 7
reproduction test security selesai (Sep 2026), pertanyaan yang masih
belum terjawab di satu tempat adalah — *kalau Kotabi dilihat sebagai
satu produk Discord, sebenarnya seluruh sistemnya seperti apa?*
`DOCS_INDEX.md` menjawab "dokumen mana untuk topik apa" (direktori),
dokumen ini menjawab "bagaimana semuanya saling terhubung" (peta).

---

## 1. Purpose & Status

| | |
|---|---|
| Tujuan Kotabi | Ekosistem belajar Bahasa Jepang berbasis Discord — bukan sekadar bot kamus (lihat `MEMBERSHIP_SYSTEM.md` §1: "Kotabi tidak menjual akses channel, Kotabi menjual ekosistem belajar") |
| Status dokumentasi | 8/8 folder fitur punya dokumen topik terverifikasi; `COMMANDS.md`, `PERMISSION_MATRIX.md`, `DATABASE_SCHEMA.md`, `DEPLOYMENT.md` lengkap |
| Status testing | 7/7 known security/integrity finding punya reproduction test (`tests/`, 20/20 PASS) — belum ada acceptance test, belum ada fix |
| Status kode produksi | Tidak ada perubahan behavior dari seluruh sesi audit ini — murni dokumentasi + test |

---

## 2. Kotabi at a Glance

```
kotabi-bot/
├── core/bot.py       ← jantung: auto-discover cog, DB helper (RUN/GET/GET_ONE)
├── shared/           ← lintas-fitur: config.py, checks.py, messages.py, server_map.yml
└── features/
    ├── dictionary/    ← /kanji /kotoba /bunpou — kamus, tidak butuh membership khusus untuk mode list
    ├── gatekeeper/    ← sistem kuis kenaikan kasta + journey/roadmap
    ├── membership/    ← tier VIP, alur pembelian, grant/revoke
    ├── immersion/     ← /log + turunannya (achievement, goals, stats, race)
    ├── social/        ← bookmark, custom role, auto-role, voice JTC, daily question AI, event role, rank saver
    ├── moderation/     ← selfmute, sticky message, thread resolver, quiz forum cleanup
    ├── server_admin/    ← backup, restore permission, structure, /say
    └── system/           ← sync command, watchdog (dev tooling, prefix command)
```

32 cog, 44 slash command standalone + 4 command group (13 subcommand) +
5 prefix command + 12 cog tanpa command sama sekali (murni listener/
background task) — rincian penuh: `COMMANDS.md`.

Deploy: push ke `main` → GitHub Actions (self-hosted runner) → `docker
build` → `docker run` dengan bind mount `/data` — rincian: `DEPLOYMENT.md`.

---

## 3. Discord UX Map

Dipetakan dari grouping asli di `shared/server_map.yml` (komentar
per-blok) + `PERMISSION_MATRIX.md` §2-11, disilangkan ke fitur code
yang benar-benar memakainya.

| Area UX | Channel (`server_map.yml`) | Fitur code yang mengisi | Command masuk |
|---|---|---|---|
| **Onboarding** | `welcome_and_rules`, `announcements`, `channel_guide`, `join_log`, `role_assign` | `social/auto_receive_cog.py` (auto-role Drifter + faction via reaksi) | — (murni event-driven) |
| **Kotabi System** | `membership`, `honor_board`, `bot_commands` | `membership/*` (info tier), `gatekeeper/*` (pengumuman kelulusan) | `/info`, semua command umum |
| **Japanese Area** | `questions_forum`, `jlpt_study_group` | `moderation/thread_resolver_cog.py` | `/solved` |
| **Community** | `general`, `jp_general`, `off_topic` | — (murni ruang obrolan manusia) | — |
| **Member Library** | `grammar_dic`, `kotoba_dic`, `kanji_dic`, `anime_sentences` | `dictionary/*` (3 dari 4 channel) | `/bunpou`, `/kotoba`, `/kanji` |
| **Member Area** | `member_lounge`, `deck_requests`, `immersion_race` | `immersion/*` (parsial — lihat §9) | `/log_race` (tanpa channel gate, lihat §9) |
| **Quiz Hall** | `quiz_rank_up`, `quiz_public` | `gatekeeper/gatekeeper_cog.py`, `gatekeeper/practice_cog.py`, `moderation/quiz_forum_cog.py` | `/journey`, `/create_quiz_menu`, dll |
| **Voice Hall** | `lounge`, `join_to_create`, `staff_voice` | `social/voice_jtc_cog.py` | — (event-driven) |
| **Resources** | `notes_and_resources` | — (murni ruang berbagi manusia) | — |
| **Staff** | `staff_chat`, `order_review` | `membership/purchase_cog.py` (order review) | `/orders`, `/say`, `/backup_*` |

**Catatan §3 vs §9:** `anime_sentences`, `deck_requests` tidak punya
command/fitur bot yang teridentifikasi secara eksplisit mengisinya —
kemungkinan channel konten manual staff, bukan gap otomatis (lihat §9
untuk kenapa ini tidak langsung diklaim sebagai bug).

---

## 4. Feature → Command → Channel → Role Map (ringkas)

Tabel lengkap 44+ command: `COMMANDS.md`. Ringkasan per fitur (channel
= channel yang di-gate eksplisit di kode via `is_valid_channel()`/
config, bukan sekadar "biasanya dipakai di sini"):

| Fitur | Command utama | Channel di-gate eksplisit? | Role/tier minimum |
|---|---|---|---|
| Dictionary | `/kanji`, `/kotoba`, `/bunpou` | Tidak | List: semua. Detail: Trial/Companion/Patron (bukan Traveler) — `has_dic_access()` |
| Gatekeeper | `/journey`, `/create_quiz_menu` | Tidak (channel `quiz_rank_up` dikontrol lewat UI dropdown, bukan command gate) | Bervariasi per kuis (`open_to_drifter`) |
| Membership | `/subscribe`, `/admin *` | Tidak | `/admin *` staff/authorized; `/subscribe` semua |
| Immersion | `/log`, `/log_stats`, dst | **Ya** (`is_valid_channel()`) kecuali `/log_race` — lihat §9 | `@is_vip()` di hampir semua, `/log_stats`/`/log_race` tidak ada gate sama sekali |
| Social | `/create_role`, `/kneelderboard` | Tidak | `has_premium_role()` untuk `/create_role`; sisanya terbuka |
| Moderation | `/selfmute`, `/solved`, `/sticky_*` | Tidak | Campuran: `allowed_ids` config, `default_permissions`, atau tanpa gate (`/solved`) |
| Server Admin | `/backup_*`, `/say`, `/permission *` | Tidak | `default_permissions(administrator=True)` + variasi in-body check — lihat `SERVER_ADMIN_SYSTEM.md` §6 untuk perbandingan lengkap mana yang benar-benar ditegakkan |
| System | `%sync_*` (prefix, bukan slash) | Tidak | `AUTHORIZED_USERS` env var |

---

## 5. Feature Dependencies / Cross-Feature Flows

**Dependency yang disengaja/aman:**
```
log_cog.py (immersion) → goals_cog.check_goal_status() (immersion)
media_types.py → 3 modul autocomplete (anilist/vndb/tmdb)
custom_role_cog.py (social) → shared/checks.has_premium_role()
say_cog.py (server_admin) → shared/checks.is_staff()
practice_cog.py (gatekeeper) → quiz_forum_cog.py (moderation) — cleanup thread,
    didokumentasikan eksplisit di kedua sisi sebagai desain aman
```

**Dependency yang TIDAK disengaja/bug** (lihat §10 untuk detail):
```
rank_saver_cog.py (social) ↔ role staff/administratif → SOCIAL_SYSTEM.md §10
rank_saver_cog.py (social) ↔ selfmute_cog.py (moderation) → MODERATION_SYSTEM.md §4
```

**Dependency yang BELUM diverifikasi tapi polanya konsisten dengan bug
di atas** (inferensi, bukan temuan terkonfirmasi — lihat §9):
membership expiry (`admin_cog.py` `membership_expiry_check`) mencabut
role tier VIP saat expired. Kalau member itu leave+rejoin dalam window
sebelum `rank_saver` sempat snapshot ulang, pola yang sama (role lama
ter-restore) secara struktural bisa berlaku ke role membership juga —
**belum ditest**, cuma pattern-matching dari finding yang sudah ada.

---

## 6. Data & Persistence Map

Sumber lengkap: `DATABASE_SCHEMA.md`. Ringkasan tabel → fitur:

| Fitur | Tabel |
|---|---|
| Core (lintas-fitur) | `users` |
| Gatekeeper | `quiz_attempts`, `passed_quizzes`, `user_threads`, `processed_quiz_reports`, `practice_threads` |
| Membership | `memberships`, `orders`, `trial_claims`, `membership_history_v1` (lewat `migrations/`, bukan `cog_load()`) |
| Immersion | `logs`, `user_goals`, `cached_{anilist,vndb,tmdb}_results` + FTS5 |
| Dictionary | `bunpou_entries`, `kotoba_entries`, `kanji_entries`, `kanji_meanings_id` |
| Social | `bookmarks`, `custom_roles`, `kneels`, `user_ranks`, `event_roles`, `daily_questions` |
| Moderation | `active_mutes`, `sticky_messages` |
| Server Admin, System | **Tidak ada** — operasi langsung ke Discord API/file export |

Prinsip yang konsisten di semua tabel: akses SQLite **selalu** lewat
`core/bot.py` (`bot.RUN`/`GET`/`GET_ONE`), koneksi baru per panggilan
(bukan connection pool) — ini juga alasan test harness (`tests/`) wajib
pakai SQLite temp file, bukan `:memory:` (lihat `tests/README.md`).

**Tech debt tercatat**: tabel `membership_history` lama (tanpa suffix
`_v1`) belum terkonfirmasi ter-drop pasca migrasi (`DATABASE_SCHEMA.md`
§3).

---

## 7. Permission & Access Model

**Tiga mekanisme populasi yang BERBEDA dan tidak selalu overlap**
(sintesis dari `shared/checks.py` + tiap dokumen topik):

| Mekanisme | Populasi | Dipakai di |
|---|---|---|
| `AUTHORIZED_USERS` (env var) | Set user ID tetap, di luar sistem role Discord | `has_authorized_access()`, `backup_discord_cog._is_authorized()` (duplikat terpisah), `sync_cog.is_authorized()` (duplikat terpisah lagi) |
| Role staff (`royal_guard`, `prime_minister`) | `get_staff_role_ids()` dari `server_map.yml` | `has_staff_role()`, `is_staff()`, otomatis lolos di `has_vip_role()`/`has_premium_role()`/`has_dic_access()` |
| Tier VIP (`trial`/`traveler`/`companion`/`patron`) | `get_vip_role_ids()` dari `membership_settings.yml` | `is_vip()`, `is_premium()` (Traveler dikecualikan), `has_dic_access()` (Traveler dikecualikan) |

**Rantai tier membership**: Trial (5 hari) → Traveler → Companion →
Patron (lifetime). Companion otomatis mencakup Traveler
(`TIER_ROLE_CHAIN`), Patron berdiri sendiri. Detail: `MEMBERSHIP_SYSTEM.md`
§3, harga: `PRICING_SYSTEM_REFACTOR.md` (belum di-deep-dive di sesi
audit ini — direferensikan, bukan disintesis ulang di sini).

**Kekuatan penegakan bervariasi liar antar command** — `default_permissions`
(cuma metadata Discord, TIDAK ditegakkan bot) vs
`app_commands.checks.has_permissions()`/`is_staff()`/`is_vip()`
(ditegakkan nyata) vs in-body check manual — dikonfirmasi empiris
beda failure semantics-nya juga (`tests/conftest.py`'s `run_checks()`
docstring). Ini akar dari 4 dari 7 known issue di §10.

---

## 8. Documentation Coverage

| Layer | Dokumen | Status |
|---|---|---|
| Navigasi/index | `DOCS_INDEX.md` | ✅ Aktif |
| Konvensi kerja | `DEVELOPMENT_GUIDE.md` | ✅ Aktif (§14 baru: disiplin pacing audit/test) |
| Command reference | `COMMANDS.md` | ✅ Aktif |
| Per-fitur | `DICTIONARY_SYSTEM.md`, `GATEKEEPER_QUIZ_SYSTEM.md`, `MEMBERSHIP_SYSTEM.md`, `IMMERSION_SYSTEM.md`, `SOCIAL_SYSTEM.md`, `MODERATION_SYSTEM.md`, `SERVER_ADMIN_SYSTEM.md` | ✅ Aktif, semua |
| Harga | `PRICING_SYSTEM_REFACTOR.md` | Ada, **belum di-deep-dive** sesi ini |
| Permission/struktur | `PERMISSION_MATRIX.md` | ✅ Aktif |
| Database | `DATABASE_SCHEMA.md` | ✅ Aktif |
| Deployment | `DEPLOYMENT.md` | ✅ Aktif |
| Testing | `tests/README.md` | ✅ Aktif, 7/7 finding punya reproduction test |
| **Sintesis sistem** | **dokumen ini** | ✅ Baru |
| Role sistem (faction/achievement/leveling) | — | ❌ Belum ada, masih tersebar di `server_map.yml` + kode |
| `system/` (sync/watchdog) | — | ❌ Belum diputuskan perlu dokumen sendiri atau masuk `DEVELOPMENT_GUIDE.md`/`DEPLOYMENT.md` |

---

## 9. System Gaps

**Repo-only** (ada di kode, tidak/kurang punya entry point Discord):
- `system/` — prefix command (`%sync_guild` dst), tidak muncul di menu
  slash Discord sama sekali, cuma bisa dipakai yang tahu syntax-nya.
- 12 cog tanpa command (`COMMANDS.md` §9) — murni by-design (listener/
  background task), bukan gap, tapi berarti tidak ada cara user biasa
  "melihat" fitur ini bekerja selain efeknya (mis. `rank_saver` tidak
  pernah terlihat kecuali lewat efek sampingnya).

**Discord-only** (channel/kategori ada, fitur bot yang mengisinya tidak
teridentifikasi jelas — lihat §3):
- `anime_sentences`, `deck_requests` — kemungkinan besar channel
  konten manual staff, **bukan diklaim sebagai bug**, cuma dicatat
  karena tidak ada command/cog yang secara eksplisit menyebut channel
  ini di seluruh audit.

**Implementation gap yang paling signifikan** — `/log_race` (immersion)
tidak memanggil `is_valid_channel()` sama sekali (`IMMERSION_SYSTEM.md`
§9), padahal ada channel `immersion_race` di `server_map.yml` yang
namanya menyiratkan command ini seharusnya terikat ke sana. Belum
dikonfirmasi apakah ini disengaja (command boleh dipanggil di mana
saja) atau kelalaian — **candidate untuk didecide**, bukan known issue
resmi (belum pernah masuk daftar 7 finding karena bukan celah
keamanan, cuma potensi UX mismatch).

**Documentation gap:** lihat §8 — role sistem konsolidasi, `system/`.

**Cross-feature gap yang belum diverifikasi:** lihat §5 (membership
expiry ↔ rank_saver, inferensi belum ditest).

**Testing gap:** `discord.py` tidak di-pin di `requirements.txt` —
dicatat sebagai reproducibility risk di `tests/README.md`, belum
masuk daftar 7 finding karena bukan security issue, murni engineering
hygiene.

---

## 10. Known Issues (7 Finding Terverifikasi + Reproduction Test)

Semua **documentation + test only** — belum ada fix. Detail lengkap
tiap finding: dokumen topik masing-masing. Status test: `tests/README.md`.

| # | Finding | Klasifikasi | Dokumen |
|---|---|---|---|
| 1 | `/backup_database` — regresi permission check (dulu ditegakkan backend, sekarang cuma metadata) | **Authorization gap (regresi)** — paling serius | `SERVER_ADMIN_SYSTEM.md` §2 |
| 2 | `/log_export`, `/logs`, `/log_stats` — klaim "Khusus Staf" tidak ditegakkan + hasil non-ephemeral | Authorization gap + data exposure | `IMMERSION_SYSTEM.md` §14 |
| 3 | `rank_saver` → role staff/admin bisa auto-restore setelah dicabut, tanpa batas waktu | Authorization integrity | `SOCIAL_SYSTEM.md` §10 |
| 4 | `rank_saver` ↔ `/selfmute` — mute bisa batal lewat leave-rejoin | Moderation enforcement integrity (root cause sama dengan #3, dampak beda, sengaja dipisah) | `MODERATION_SYSTEM.md` §4 |
| 5 | `/solved` — tanpa otorisasi sama sekali, state bisa dipalsukan via rename thread | Authorization gap + state integrity | `MODERATION_SYSTEM.md` §2 |
| 6 | `/kneelderboard` — cross-guild query tanpa cek keanggotaan | Design gap (bukan broken promise — fitur ini diiklankan) | `SOCIAL_SYSTEM.md` §3 |
| 7 | `/say` — parameter `channel` tidak mengecek permission staff di channel target | Authorization gap (permission laundering) | `SERVER_ADMIN_SYSTEM.md` §4.4 |

---

## 11. Overlap / Duplication

- **Tiga implementasi terpisah untuk konsep "authorized user" yang
  mirip**: `shared/checks.has_authorized_access()`,
  `backup_discord_cog._is_authorized()`, `sync_cog.is_authorized()` —
  ketiganya baca `AUTHORIZED_USERS` env var secara independen, bukan
  1 fungsi bersama. Bukan bug fungsional (belum ditemukan kasus di
  mana mereka disagree), tapi pelanggaran prinsip "single source of
  truth" yang dinyatakan `DEVELOPMENT_GUIDE.md` §5 sendiri.
- **`kneel_leaderboard_cog.py` punya `update_user_name()` sendiri**,
  terpisah dari `shared/username_cache.get_username_db()` yang dipakai
  fitur lain (immersion) — kemungkinan karena `kneels` table
  menyimpan `user_name` ter-denormalisasi sendiri (beda kebutuhan),
  bukan duplikasi murni — **belum diverifikasi lebih lanjut, dicatat
  sebagai kandidat, bukan temuan pasti**.

---

## 11.5 Product/UX Gap Analysis (Sep 2026) — Evidence, Bukan Solusi

Dianalisis lewat lensa 8-tahap perjalanan user (entry → first success →
learning loop → progression → discovery → community → membership →
return), murni dari dokumen yang sudah ada, tanpa buka kode/dokumen
baru. Dua isu utama, ditulis sebagai *evidence + pertanyaan produk*,
sengaja **bukan** rekomendasi solusi:

**A. `/log` (inti loop immersion) digerbang `@is_vip()`** — Drifter
(user gratis, baru masuk) tidak punya akses ke logging immersion sama
sekali, bukan sekadar dibatasi (`IMMERSION_SYSTEM.md` §3, `COMMANDS.md` §3).

> **✅ DIPUTUSKAN (19 Sep 2026):** `/log` **seharusnya tersedia untuk
> Drifter**, dengan batasan (bukan dibuka penuh tanpa syarat).
> Alasannya: `/log` membentuk loop belajar (catat → lihat progres →
> terdorong lanjut), bukan cuma fitur tambahan — mengunci totalnya
> membuat beda free/VIP jadi "bisa belajar sebagian vs bisa menjalankan
> sistem belajar" (gating *permission to participate*), bukan
> "acceleration" seperti yang dinyatakan filosofi freemium Kotabi
> sendiri (lihat B). Model kasar: **Drifter → `/log` jalan dengan
> batasan; VIP → penuh** (progression/analytics/convenience jadi
> pembeda tier, bukan akses dasar).
>
> **BELUM diputuskan (turunan langsung dari keputusan ini, prioritas
> berikutnya):** bentuk batasan Drifter secara konkret — kandidat yang
> disebut saat decide: jumlah log, periode history, statistik, goals,
> leaderboard/race, achievement, export, atau kombinasi beberapa itu.
> Jangan diasumsikan/diimplementasikan sebelum ini dijawab eksplisit.

**B. Tegangan filosofi vs implementasi** — `MEMBERSHIP_SYSTEM.md` §1
menyatakan "freemium = percepatan, bukan gembok — versi gratis harus
tetap enak dipakai", tapi temuan A menunjukkan fitur paling
"ekosistem" (bukan sekadar konten kamus) justru gembok total di level
paling dasar. A dan B bukan dua temuan terpisah — keduanya satu
pertanyaan besar: **apakah positioning freemium Kotabi konsisten
dengan pengalaman first-user yang sesungguhnya?**

**Pertanyaan untuk fase Product Decision:**

| Pertanyaan | Tujuan | Status |
|---|---|---|
| Apakah immersion termasuk core loop? | Menentukan status `/log` | ✅ **Diputuskan 19 Sep** — ya, lihat kotak di atas |
| Kalau gratis, apa batas premium-nya untuk `/log`? | Menghindari "gembok" tanpa disadari | ⏳ Turunan langsung dari keputusan di atas — **prioritas berikutnya** |
| Apa core loop gratis Kotabi secara keseluruhan (di luar immersion)? | Menentukan pengalaman dasar | ⏳ Belum |
| Apa yang sebenarnya dipercepat oleh premium (di luar immersion)? | Menentukan value membership | ⏳ Belum |
| Apa first success newcomer yang sesungguhnya? | Menentukan onboarding | ⏳ Belum |

Open question yang lebih lemah evidence-nya (dicatat, bukan
diprioritaskan): kualitas `channel_guide`/`/info` sebagai mekanisme
discovery belum diverifikasi; efektivitas `daily_question_cog` sebagai
return-loop belum diverifikasi; 4 track progression paralel (kasta,
achievement, leveling, faction) belum ada satu penjelasan yang
mengikat — status UX gap, bukan bug.

---

## 12. Open Decisions / Backlog

Belum diputuskan — **jangan mulai fix sebelum ini diputuskan**, sesuai
prinsip audit→document→classify→**decide**→fix→test:

| # | Yang perlu diputuskan |
|---|---|
| 1 | `/backup_database` perlu authorization check administrator yang ditegakkan backend — kontraknya sudah jelas, tinggal implementasi mana (`has_permissions()` kembali, atau in-body check konsisten dengan `backup_discord_cog.py`) |
| 2 | `/log_export`/`/logs`/`/log_stats`: siapa yang boleh (staff sungguhan, bukan VIP)? Hasil tetap public atau jadi ephemeral? Dua sub-keputusan terpisah |
| 3 | `rank_saver`: scope sempit (cuma role rank/tier) vs scope lebar + lifecycle invalidation — **paling penting, menentukan desain #4 juga** |
| 4 | Role mute harus dianggap non-restorable secara eksplisit, atau ikut keputusan #3 |
| 5 | `/solved`: minimal thread owner ATAU staff boleh menutup — perlu diputuskan exact rule-nya |
| 6 | `/kneelderboard`: cross-guild dilarang total, staff-gate, atau redact data? |
| 7 | `/say`: caller harus punya permission Discord asli di target channel, bukan cuma lolos `@is_staff()` global |
| — | Kandidat tambahan (§9): apakah `/log_race` sengaja tanpa channel gate? |

---

## 13. Next-Stage Priorities (Rekomendasi, Bukan Keputusan)

1. **Decide finding #1** (`/backup_database`) dulu — paling serius,
   paling sedikit ambiguitas desain, langsung bisa lanjut ke fix+flip
   acceptance test.
2. **Decide #3 sebelum #4** — #4 kemungkinan besar ikut terjawab
   begitu scope Rank Saver diputuskan.
3. #2, #5, #7 — masing-masing independen, bisa diputuskan kapan saja
   setelah #1 selesai, tidak saling bergantung.
4. #6 — prioritas lebih rendah (design gap, bukan regresi/broken
   promise), aman ditunda.
5. Dokumentasi (§8 gap: role sistem, `system/`) — non-urgent, tidak
   memblokir apa pun, kerjakan kalau ada waktu luang, bukan sebagai
   sesi khusus lagi (`DEVELOPMENT_GUIDE.md` §14).
6. Cross-feature gap di §5 (membership ↔ rank_saver) — verifikasi
   singkat kapan-kapan, jangan jadi audit besar lagi.

---

## Riwayat Perubahan Signifikan

- **2026-09-19** — Dibuat dari nol, murni sintesis dari 12 dokumen
  sumber yang sudah ada (tidak ada pembacaan kode baru). Tujuan:
  menjawab "Kotabi sebagai produk Discord itu apa" di satu tempat,
  setelah audit dokumentasi 8 fitur + 7 reproduction test selesai.
