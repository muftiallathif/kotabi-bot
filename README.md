# Kotabi Japanese Discord Bot

Bot Discord multi-fungsi yang dikembangkan untuk server Kotabi Japanese. Bot ini dirancang secara modular dan mudah diperluas dengan fitur-fitur baru.

---

## Fitur / Commands

#### `auto_receive.py`

Memungkinkan admin mengatur role yang secara otomatis mendapatkan role lain. Misalnya, jika user memiliki role 'メンバー / Member' mereka mendapatkan role tertentu secara otomatis.

---

#### `bookmark.py`

Memungkinkan user mem-bookmark pesan dengan bereaksi 🔖. Pesan yang di-bookmark dikirim ke DM user dan dapat dihapus dengan ❌. Juga melacak pesan yang paling banyak di-bookmark per server.

Commands:
* `/bookmarkboard` - Menampilkan 10 pesan yang paling banyak di-bookmark di server beserta link untuk langsung ke pesan tersebut.
* `/checkbookmarks` - Khusus admin. Membersihkan leaderboard bookmark dengan menghapus entri untuk pesan yang sudah dihapus.

User Actions:
* React dengan 🔖 untuk bookmark pesan
* React dengan ❌ pada DM bookmark untuk menghapusnya

---

#### `custom_role.py`

Memungkinkan user membuat dan mengelola role kustom mereka sendiri dengan warna dan ikon kustom (jika server memiliki cukup boost). Role kustom diposisikan di bawah reference role dan otomatis dihapus jika user kehilangan izin yang diperlukan.

Commands:
* `/make_custom_role` `<role_name>` `<color_code>` `<role_icon>` - Buat role kustom. Nama role maksimal 14 karakter, warna harus berupa kode hex (misal #A47267), ikon role opsional.
* `/delete_custom_role` - Hapus role kustom kamu.
* `/_create_custom_role_settings` `<reference_role>` - Khusus admin. Atur role mana yang bisa membuat role kustom dan reference role.

---

#### `dumb_db.py`

Command sederhana yang memungkinkan user mengunduh salinan terkompresi dari file database bot.

Commands:
* `/post_db` - Membuat salinan gzip dari file database dan mempostingnya ke channel.

---

#### `event_roles.py`

Secara otomatis membuat dan mengelola role untuk Discord scheduled events. Ketika event dibuat, role yang sesuai dibuat dan diberikan ke peserta. Role secara otomatis dihapus ketika event berakhir.

Tidak ada command user - sepenuhnya otomatis.

---

#### `gatekeeper.py`

Bekerja dengan quiz Kotoba bot untuk memverifikasi dan memberikan role berdasarkan performa quiz.

Commands:
* `/reset_user_cooldown` `<user>` `<quiz_to_reset>` - Khusus admin. Reset cooldown quiz user. Parameter quiz opsional untuk mereset quiz tertentu.
* `/ranktable` - Menampilkan distribusi role quiz di server, menunjukkan persentase user dengan setiap role.
* `/rankusers` `<role>` - Lihat semua user dengan role tertentu.
* `/list_role_commands` `<guild_id>` - Daftar semua command quiz dan role reward yang sesuai. Guild ID opsional.
* `/create_quiz_menu` - Khusus admin. Membuat menu quiz interaktif di channel saat ini.

Struktur Rank Kotabi Japanese:
| Rank | Quiz Command | ID Role |
|------|-------------|---------|
| 平民 / Commoner | `k!quiz hiragana+katakana 20 nd mmq=10 dauq=2 font=1 atl=30 color=#c92a2a size=100` | 1515997732966502441 |
| 騎士 / Knight | `k!quiz hiragana+katakana 50 hardcore nd mmq=10 dauq=1 font=5 atl=16 color=#c92a2a size=100` | 1515998050336641117 |
| 【N5】准男爵 / Baronet | `k!quiz n5 50 hardcore nd mmq=10 dauq=1 font=5 atl=16 color=#c92a2a size=100 effect=antiocr` | 1404219557333303419 |
| 【N5】男爵 / Baron | `k!quiz gn5 nd 20 mmq=4 atl=60` | 1515998513807495248 |
| 【N4】准子爵 / Junior Viscount | `k!quiz n4 50 hardcore nd mmq=10 dauq=1 font=5 atl=16 color=#c92a2a size=100 effect=antiocr` | 1515998740203180202 |
| 【N4】子爵 / Viscount | `k!quiz gn4 nd 20 mmq=4 atl=60` | 1404219560248348772 |
| 【N3】准伯爵 / Junior Count | `k!quiz n3 50 hardcore nd mmq=10 dauq=1 font=5 atl=16 color=#c92a2a size=100 effect=antiocr` | 1515999058915758090 |
| 【N3】伯爵 / Count | `k!quiz gn3 nd 20 mmq=4 atl=60` | 1404219539113246854 |
| 【N2】准侯爵 / Junior Marquess | `k!quiz n2 50 hardcore nd mmq=10 dauq=1 font=10 atl=16 color=#ffda56 size=100 effect=antiocr` | 1515999289388699779 |
| 【N2】侯爵 / Marquess | `k!quiz gn2 nd 20 mmq=4 atl=60` | 1404219483727331379 |
| 【N1】准公爵 / Junior Duke | `k!quiz n1 50 hardcore nd mmq=10 dauq=1 font=10 atl=16 color=#c92a2a size=100 effect=antiocr` | 1515999731355222136 |
| 【N1】公爵 / Duke | `k!quiz gn1 nd 20 mmq=4 atl=60` | 1404219327833444362 |
| 大公 / Archduke | `k!quiz yoji_2k+yoji_j1k+2k+j1k+insane 50 hardcore nd mmq=10 dauq=1 font=10 atl=16 color=#c92a2a size=100 effect=antiocr` | 1516000372441874452 |
| 王 / King | `k!quiz yoji_1k+1k 50 hardcore nd mmq=10 dauq=1 font=10 atl=16 color=#c92a2a size=100 effect=antiocr` | 1516000507414577173 |
| 大王 / High King | `k!quiz imm_nandoku+haado+insane+j1k 50 hardcore nd mmq=10 dauq=1 font=10 atl=16 color=#c92a2a size=100 effect=antiocr` | 1516000520521650247 |
| 皇帝 / Emperor | `k!quiz n0+cope+kunyomi1kfull+loli+Myouji+jpdefs+places_full 50 hardcore nd mmq=10 dauq=1 font=7 atl=16 color=#c92a2a size=90 effect=antiocr` | 1516000555070394368 |

---

#### `immersion_log.py`, `immersion_goals.py`, `immersion_stats.py`

Sistem pelacakan immersion komprehensif yang memungkinkan user mencatat aktivitas belajar bahasa Jepang, menetapkan target, dan melihat statistik.

Commands:
* `/log` `<media_type>` `<amount>` `<name>` `<comment>` `<backfill_date>` - Catat aktivitas immersion.
* `/log_undo` `<log_entry>` - Hapus entri log sebelumnya.
* `/log_achievements` - Tampilkan semua pencapaian immersion kamu.
* `/log_export` `<user>` - Ekspor log immersion sebagai file CSV.
* `/logs` `<user>` - Output log immersion sebagai file teks terformat.
* `/log_leaderboard` `<media_type>` `<month>` - Tampilkan leaderboard bulanan.

Goal Management:
* `/log_set_goal` `<media_type>` `<goal_type>` `<goal_value>` `<end_date_or_hours>` - Tetapkan target immersion baru.
* `/log_remove_goal` `<goal_entry>` - Hapus target tertentu.
* `/log_view_goals` `<member>` - Lihat target kamu atau target user lain.
* `/log_clear_goals` - Hapus semua target yang sudah kadaluarsa.

Statistics:
* `/log_stats` `<user>` `<from_date>` `<to_date>` `<immersion_type>` - Tampilkan statistik immersion detail dengan grafik.

---

#### `immersion_bar_races.py`

Membuat racing bar chart dari log immersion untuk periode waktu tertentu.

Commands:
* `/log_race` `<from_date>` `<to_date>` `<media_type>` `<race_type>` - Buat racing bar chart log immersion.

---

#### `info.py`

Menyediakan command informasi yang menampilkan pengetahuan dan dokumentasi yang telah ditentukan sebelumnya kepada user.

Commands:
* `/info` `<topic>` - Tampilkan informasi tentang topik tertentu.

Topic yang tersedia:
* `cara-naik-rank` - Panduan cara naik rank
* `panduan-belajar` - Panduan belajar bahasa Jepang di Kotabi
* `kelas-intensif` - Info kelas intensif
* `member-reguler` - Info paket member reguler

---

#### `kneels.py`

Melacak dan menampilkan statistik reaksi "kneel" pada pesan.

Commands:
* `/kneelderboard` - Tampilkan 20 user teratas dengan kneel terbanyak diterima.

---

#### `rank_saver.py`

Secara otomatis menyimpan dan memulihkan role user ketika mereka keluar dan bergabung kembali ke server. Berjalan setiap 10 menit untuk menyimpan role saat ini.

Tidak ada command user - sepenuhnya otomatis.

---

#### `selfmute.py`

Memungkinkan user untuk sementara membisukan diri sendiri untuk durasi tertentu.

Commands:
* `/selfmute` `<hours>` `<minutes>` - Bisukan diri sendiri untuk durasi tertentu (maks 30 hari).
* `/check_mute` - Periksa status bisukan saat ini atau hapus bisukan jika waktu sudah habis.
* `/unmute_user` `<member>` - Khusus admin. Hapus bisukan dari user tertentu.

---

#### `sticky_messages.py`

Memungkinkan moderator membuat pesan "sticky" di channel, artinya pesan akan muncul kembali setelah pesan baru.

Commands:
* `/sticky_last_message` - Jadikan pesan terakhir di channel sticky. Memerlukan izin manage messages.
* `/unsticky` - Hapus pesan sticky saat ini dari channel. Memerlukan izin manage messages.

---

#### `sync.py`

Mengelola sinkronisasi command antara bot dan sistem command Discord. Hanya untuk user yang diotorisasi.

Commands (gunakan dengan prefix):
* `sync_guild` - Sinkronkan command ke guild saat ini.
* `sync_global` - Sinkronkan command secara global di semua guild.
* `clear_global_commands` - Hapus semua command global.
* `clear_guild_commands` - Hapus semua command dari guild saat ini.

---

#### `thread_resolver.py`

Mengelola thread bantuan di channel forum dengan melacak status solved.

Commands:
* `/solved` - Tandai thread bantuan sebagai solved, yang menambahkan "[SOLVED]" ke judul dan mengarsipkannya.

---

## Cara Berkontribusi

1. Laporkan bug dan saran fitur di tab issues.
2. Buat PR dengan perubahan kamu.

## Cara Menjalankan

1. Clone repository ini
2. Buat virtual environment dan install requirements dengan `pip install -r requirements.txt`
3. Buat salinan `.env.example` dan rename menjadi `.env` di direktori root, lalu isi variabel berikut:

    ```
    TOKEN=YOUR_DISCORD_BOT_TOKEN
    AUTHORIZED_USERS=926239001923420200
    DEBUG_USER=926239001923420200
    COMMAND_PREFIX=%
    PATH_TO_DB=data/db.sqlite3
    TMDB_API_KEY=YOUR_TMDB_API_KEY
    ```

4. Jalankan bot dengan `python main.py`, pastikan bot kamu memiliki [Privileged Message Intents](https://discord.com/developers/docs/events/gateway#privileged-intents)
5. Jalankan `%sync_global` atau `%sync_guild` untuk membuat application commands di server kamu

## Cara Menjalankan di Docker

1. Clone repository ini
2. Build docker image dengan `docker build -t discord-kotabi-bot .`
3. Buat salinan `.env.example` dan rename `.env`, sesuaikan variabel
4. `docker compose up -d`

## Channel & Role IDs Kotabi Japanese

| Tipe | Nama | ID |
|------|------|----|
| Server | Kotabi Japanese | 1403184187669872650 |
| Channel | moderator-only | 1403191211652681841 |
| Channel | info-title-kehormatan | 1515633144525754429 |
| Channel | immersion-log | 1516671526345113671 |
| Channel | quiz-rank-up | 1517023518984896564 |
| Channel | quiz-public-1 | 1404383455898501204 |
| Channel | quiz-public-2 | 1516017411231580200 |
| Channel | quiz-public-3 | 1517023365947199508 |
| Channel | general | 1403184188148027506 |
