"""
shared/messages.py — Teks & Pesan Terpusat Kotabi Bot
========================================================
Semua string yang tampil ke user disimpan di sini.
Kalau mau ubah teks, cukup edit file ini.

Sengaja TIDAK dipecah per fitur (lihat catatan restrukturisasi):
memecahnya berarti mengubah ratusan baris pemanggil Msg.XXX di semua
fitur — risiko tinggi untuk manfaat kecil, karena file ini sendiri
kecil dan aman diikutsertakan di upload fitur manapun.

Penggunaan:
    from shared.messages import Msg
    await interaction.response.send_message(Msg.VIP_ONLY(), ephemeral=True)

⚠️ PERUBAHAN PENTING (lihat PRICING_SYSTEM_REFACTOR.md Tahap 4):
VIP_ONLY, PREMIUM_ONLY, dan GATEKEEPER_VIP_ONLY DULU konstanta string
(dipanggil tanpa kurung: `Msg.VIP_ONLY`). SEKARANG method — WAJIB
dipanggil DENGAN kurung: `Msg.VIP_ONLY()`. Ini supaya harga yang
ditampilkan selalu ikut preset aktif di pricing_presets.yml, bukan
angka beku saat modul di-import.

⚠️ TAHAP 7: AUTHORIZED_ONLY ditambahkan di bawah — constant ini DULU
dipanggil di shared/checks.py (is_authorized()) tapi TIDAK PERNAH
didefinisikan di file ini (bug lama, ada sebelum refactor pricing ini,
ketemu tidak sengaja saat Tahap 4). Sekarang sudah ada, dipanggil
TANPA kurung seperti konstanta biasa (bukan method, tidak bergantung
harga).
"""

from shared.config import get_active_prices


class Msg:

    # --- Access Control ---

    @staticmethod
    def _format_rp(amount: int) -> str:
        """Format angka rupiah jadi 'Rp80.000'. Helper internal, dipakai
        method harga di bawah supaya format konsisten satu tempat."""
        return f"Rp{amount:,}".replace(",", ".")

    @staticmethod
    def VIP_ONLY() -> str:
        prices = get_active_prices()
        return (
            "❌ Fitur ini hanya tersedia untuk **member VIP** Kotabi Japanese.\n\n"
            f"🎒 **Traveler** — {Msg._format_rp(prices['traveler']['monthly'])} / bulan\n"
            f"🤝 **Companion** — {Msg._format_rp(prices['companion']['monthly'])} / bulan\n"
            "👑 **Patron** — Seumur hidup\n\n"
            "Hubungi staf untuk mendaftar! 🙇‍♂️"
        )

    @staticmethod
    def PREMIUM_ONLY() -> str:
        prices = get_active_prices()
        return (
            "❌ Fitur ini hanya tersedia untuk **member berbayar** (bukan Trial).\n\n"
            f"🎒 **Traveler** — {Msg._format_rp(prices['traveler']['monthly'])} / bulan\n"
            f"🤝 **Companion** — {Msg._format_rp(prices['companion']['monthly'])} / bulan\n\n"
            "Hubungi staf untuk mendaftar! 🙇‍♂️"
        )

    @staticmethod
    def GATEKEEPER_VIP_ONLY() -> str:
        prices = get_active_prices()
        return (
            "❌ Sistem ujian kasta hanya tersedia untuk **member VIP**.\n\n"
            f"🎒 **Traveler** — {Msg._format_rp(prices['traveler']['monthly'])} / bulan\n"
            f"🤝 **Companion** — {Msg._format_rp(prices['companion']['monthly'])} / bulan\n"
            "👑 **Patron** — Seumur hidup\n\n"
            "Hubungi staf untuk mendaftar! 🙇‍♂️"
        )

    PATRON_ALREADY_LIFETIME = (
        "👑 Kamu sudah menjadi **Patron (Lifetime)** dan mendapat akses penuh selamanya.\n"
        "Tidak perlu berlangganan lagi!"
    )

    # AUTHORIZED_ONLY — BARU (Tahap 7). Dipakai is_authorized() di
    # shared/checks.py, untuk command yang butuh AUTHORIZED_USER_IDS atau
    # Administrator (beda dari STAFF_ONLY yang untuk role Royal Guard/
    # Prime Minister biasa — is_authorized() itu tingkatan lebih tinggi,
    # dipakai command sensitif seperti /permission dan /structure).
    AUTHORIZED_ONLY = "❌ Perintah ini hanya dapat digunakan oleh pengguna dengan otorisasi khusus (Admin/Authorized User)."

    STAFF_ONLY      = "❌ Anda tidak memiliki wewenang untuk menggunakan perintah ini."
    GUILD_ONLY      = "❌ Perintah ini hanya dapat digunakan di dalam server."
    INVALID_CHANNEL = "Anda hanya dapat menggunakan perintah ini di DM atau di saluran khusus pencatatan log."
    NOT_FOUND       = "❌ Data tidak ditemukan."

    # --- Log Channel ---
    LOG_INVALID_CHOICE        = "Pilihan catatan log tidak valid."
    LOG_INVALID_MONTH_FORMAT  = "Format penulisan bulan salah! Harap gunakan format YYYY-MM."
    LOG_INVALID_AMOUNT        = "Jumlah input harus berupa angka bulat positif yang valid."
    LOG_NEGATIVE_AMOUNT       = "Jumlah input tidak boleh bernilai negatif."
    LOG_NAME_TOO_LONG         = "Nama media terlalu panjang! Batas maksimal adalah 150 karakter."
    LOG_COMMENT_TOO_LONG      = "Komentar terlalu panjang! Batas maksimal adalah 200 karakter."
    LOG_FUTURE_DATE           = "Anda tidak bisa mencatat aktivitas untuk tanggal di masa depan."
    LOG_TOO_OLD               = "Anda tidak bisa mencatat aktivitas yang sudah berlalu lebih dari 7 hari."
    LOG_INVALID_DATE_FORMAT   = "Format tanggal salah! Harap gunakan format YYYY-MM-DD atau YYYY-MM-DD HH:MM."
    LOG_NOT_FOUND             = "Catatan log tersebut tidak ditemukan atau bukan milik Anda."
    LOG_NO_HISTORY            = "Tidak ada riwayat log belajar yang dapat diekspor untuk warga tersebut."
    LOG_NO_DATA_PERIOD        = "Tidak ditemukan data log aktivitas belajar untuk periode waktu yang ditentukan."
    LOG_EMPTY_RANGE           = "Tidak ada riwayat aktivitas yang tercatat dalam rentang waktu tersebut."
    LOG_INVALID_START_DATE    = "Format penulisan tanggal awal salah! Harap gunakan format YYYY-MM-DD."
    LOG_INVALID_END_DATE      = "Format penulisan tanggal akhir salah! Harap gunakan format YYYY-MM-DD."
    LOG_FIELD_LIMIT_REACHED = (
        "Anda telah mencapai jumlah bidang maksimal. "
        "Harap selesaikan atau bersihkan beberapa target Anda."
    )
    LOG_ACHIEVEMENT_UNLOCKED_FIELD = "Pencapaian Baru Terbuka! 🎉"
    LOG_NEXT_ACHIEVEMENT_FIELD = "Pencapaian Berikutnya"
    LOG_FIELD_LIMIT_TITLE = "Perhatian"
    LOG_NO_ACHIEVEMENTS_YET = "Belum ada pencapaian yang terbuka. Teruslah konsisten belajar!"
    LOG_EXPORT_CSV_READY    = "Berikut berkas riwayat log immersion yang berhasil diekspor:"
    LOG_EXPORT_TXT_READY    = "Berikut berkas dokumen teks catatan log belajar Anda:"
    LOG_LEADERBOARD_EMPTY   = "Belum ada catatan log keaktifan untuk periode bulan ini. Jadilah yang pertama dengan mencatat log Anda!"

    # --- Goal ---
    GOAL_INVALID_START_DATE_FORMAT = "Input tidak valid. Harap gunakan tanggal dalam format YYYY-MM-DD atau YYYY-MM-DD HH:MM."
    GOAL_END_DATE_PAST   = "Tanggal berakhir harus berada di masa mendatang (masa depan)."
    GOAL_START_AFTER_END = "Tanggal mulai harus sebelum tanggal berakhir."
    GOAL_INVALID_DATE    = "Input tidak valid. Harap gunakan jumlah jam atau tanggal dalam format YYYY-MM-DD."
    GOAL_INVALID_VALUE   = "❌ Nilai target harus berupa angka positif lebih dari 0."
    GOAL_INVALID_CHOICE  = "Pilihan target tidak valid."
    GOAL_NOT_OWNED       = "Target yang dipilih tidak ada atau bukan milikmu."
    GOAL_NONE_EXPIRED    = "> Kamu tidak memiliki target kedaluwarsa untuk dibersihkan."

    # --- Selfmute ---
    MUTE_NEGATIVE_DURATION = "Anda tidak dapat membisukan diri untuk durasi negatif."
    MUTE_TOO_LONG          = "Anda hanya dapat membisukan diri maksimal selama 30 hari."
    MUTE_NO_ROLE           = "Server ini belum memiliki peran bisu mandiri yang dikonfigurasi."
    MUTE_ALREADY_MUTED     = "Anda sudah berada dalam status bisu."
    MUTE_NOT_ALLOWED       = "Anda tidak diizinkan untuk menggunakan perintah ini."
    MUTE_NOT_ACTIVE        = "Anda tidak sedang dalam status bisu."
    MUTE_RECORD_NOT_FOUND = "Warga ini tidak ditemukan dalam data pembisuan. Membatalkan peran bisu secara paksa."
    MUTE_ENDED            = "Status bisu Anda telah berakhir."
    MUTE_SELECT_ROLE      = "Pilih peran untuk membisukan diri Anda:"
    MUTE_SELECT_PLACEHOLDER = "Pilih peran untuk membisukan diri..."

    # --- Bookmark ---
    BOOKMARK_NO_DATA = "📖 Anda belum memiliki pesan yang disimpan. Berikan reaksi emoji 🔖 pada pesan mana pun untuk menyimpannya!"
    BOOKMARK_SAVED_TITLE      = "📌 Pesan Berhasil Disimpan!"
    BOOKMARK_NO_TEXT_CONTENT  = "_Pesan ini tidak memiliki teks (mungkin gambar atau berkas)._"
    BOOKMARK_FIELD_CHANNEL    = "Saluran Asal"
    BOOKMARK_FIELD_JUMP_LINK  = "Tautan Pesan"
    BOOKMARK_LIST_TITLE       = "🔖 Perpustakaan Bookmark Pribadi"
    BOOKMARK_LIST_INTRO       = "Berikut adalah 10 pesan terakhir yang Anda simpan:\n\n"
    BOOKMARK_REMOVED_DM       = "🧹 Pesan telah dihapus dari daftar bookmark kerajaan Anda."

    # --- Custom Role ---
    CUSTOM_ROLE_NO_PREMIUM = (
        "❌ Fitur kustomisasi peran hanya tersedia bagi donatur aktif "
        "(**Patron** atau **Companion**)! Dukung server kami untuk membuka akses."
    )
    CUSTOM_ROLE_INVALID_HEX  = "❌ Format kode warna Hex salah! Gunakan format standar seperti `#ff0055`."
    CUSTOM_ROLE_NOT_FOUND    = "❌ Anda belum memiliki peran kustom di server ini."
    CUSTOM_ROLE_BOT_NO_PERMS = "❌ Terjadi kegagalan sistem saat membuat peran baru. Pastikan posisi bot berada di atas kasta target."
    CUSTOM_ROLE_DELETED          = "🧹 Peran kustom Anda berhasil dihapus dari sistem kerajaan."
    CUSTOM_ROLE_DELETE_FAILED    = "❌ Terjadi masalah teknis saat menghapus peran kustom Anda."
    CUSTOM_ROLE_DB_CLEANED       = "🧹 Peran kustom Anda telah dibersihkan dari database kerajaan."

    # --- Kneels ---
    KNEEL_NO_DATA = "❌ Tidak ditemukan data sujud hormat di kerajaan ini."
    KNEEL_INVALID_GUILD_ID  = "❌ ID Server tidak valid! Pastikan Anda memasukkan deretan angka."
    KNEEL_LEADERBOARD_TITLE = "🏆 Papan Peringkat Sujud Hormat (Berlutut)"
    KNEEL_PERSONAL_FIELD    = "🛡️ Sujud Hormat Anda"

    @staticmethod
    def log_amount_exceeded(limit: int, media_type: str) -> str:
        return f"Jumlah input tidak boleh melebihi {limit} untuk jenis media `{media_type}`."

    @staticmethod
    def bookmark_dm_locked(user_mention: str) -> str:
        return (
            f"⚠️ {user_mention}, pesan berhasil disimpan! "
            "Namun, kami gagal mengirim detailnya ke DM Anda karena DM Anda terkunci."
        )

    @staticmethod
    def mute_applied(user_mention: str, role_name: str, unmute_timestamp: int) -> str:
        return (
            f"**🔇 Anda ({user_mention}) telah dibisukan dengan peran `{role_name}` "
            f"hingga <t:{unmute_timestamp}:F> (<t:{unmute_timestamp}:R>). 🔇\n**"
        )

    @staticmethod
    def mute_status(guild_name: str, unmute_timestamp: int) -> str:
        return (
            f"Anda dibisukan hingga <t:{unmute_timestamp}:F> "
            f"(<t:{unmute_timestamp}:R>) di `{guild_name}`."
        )

    @staticmethod
    def goal_removed(mention: str, goal_type_display: str, goal_value: int, unit_name: str, media_type: str) -> str:
        return (
            f"> {mention} Target `{goal_type_display}` sebesar "
            f"`{goal_value} {unit_name}` untuk `{media_type}` telah berhasil dihapus."
        )

    @staticmethod
    def log_undo_success(
        mention: str, amount: int, unit_name: str, media_type: str, media_name: str, date_str: str
    ) -> str:
        return (
            f"> {mention} Log aktivitas Anda sebanyak `{amount} {unit_name}` "
            f"dari `{media_type}` (`{media_name}`) pada tanggal `{date_str}` telah berhasil dihapus."
        )

    @staticmethod
    def rank_restored(mention: str, roles_mention_str: str) -> str:
        return (
            f"Selamat datang kembali, {mention}!\n\n"
            f"Sistem Kerajaan Kotabi telah memulihkan seluruh gelar kehormatan lama Anda:\n"
            f"✨ {roles_mention_str}"
        )

    @staticmethod
    def cooldown_active(mention: str, unix_timestamp: int) -> str:
        return (
            f"⏳ {mention}, Anda hanya diperbolehkan mengulang ujian kuis ini 1 kali dalam seminggu.\n"
            f"Kesempatan Anda berikutnya akan terbuka kembali pada "
            f"<t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)."
        )

    @staticmethod
    def goal_no_active(display_name: str) -> str:
        return f"> {display_name} tidak memiliki target belajar aktif saat ini."

    @staticmethod
    def log_success_title(amount, unit_name: str, media_type: str) -> str:
        return f"Berhasil Mencatat {amount} {unit_name} {media_type}"

    @staticmethod
    def log_next_achievement_info(title: str, total_points_after: float, target_points: int, group: str) -> str:
        return f"{title} (`{int(total_points_after)}/{target_points}` poin {group})"

    @staticmethod
    def log_achievement_unlocked_reply(title: str, description: str) -> str:
        return f"🎉 **Pencapaian Terbuka!** 🎉\n\n**{title}**\n\n{description}"

    @staticmethod
    def bookmark_jump_link(jump_url: str) -> str:
        return f"[Lompat ke Pesan]({jump_url})"

    @staticmethod
    def custom_role_updated(name: str, color_hex: str) -> str:
        return f"✨ Berhasil memperbarui peran kustom Anda menjadi **{name}** dengan warna baru `{color_hex}`!"

    @staticmethod
    def custom_role_created(name: str) -> str:
        return f"🎨 Sukses! Peran estetik **{name}** telah diciptakan dan disematkan di profil Anda!"

    @staticmethod
    def mute_unmuted_by_admin(mention: str) -> str:
        return f"{mention} telah dibebaskan dari status bisu dan peran aslinya telah dipulihkan."

    @staticmethod
    def mute_roles_restored(mention: str, roles_mention_str: str) -> str:
        return f"**🕒 Status bisu {mention} telah dicabut dan peran berikut telah dipulihkan: 🕒\n{roles_mention_str}**"

    @staticmethod
    def mute_not_allowed(allowed_roles_mention: str) -> str:
        return f"Anda tidak diizinkan untuk menggunakan perintah ini.\nPeran yang diizinkan untuk membisukan diri sendiri: {allowed_roles_mention}"

    @staticmethod
    def mute_previous_roles(roles_mention_str: str) -> str:
        return f"Peran Anda sebelumnya: {roles_mention_str}"

    @staticmethod
    def auto_receive_welcome(member_mention: str, role_assign_mention: str) -> str:
        return (
            f"{member_mention} bergabung.\n\n"
            f"Pilih kubu minat di {role_assign_mention} untuk memulai."
        )

    @staticmethod
    def faction_joined(role_name: str) -> str:
        return f"✅ Kamu bergabung dengan kubu **{role_name}**."

    @staticmethod
    def faction_left(role_name: str) -> str:
        return f"Kamu keluar dari kubu **{role_name}**."