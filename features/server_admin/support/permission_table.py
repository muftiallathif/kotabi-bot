"""
features/server_admin/support/permission_table.py — Sumber Tunggal Tabel Permission Channel
==============================================================================================
GENERASI KEDUA (v2) — lihat PERMISSION_MATRIX.md untuk rasional lengkap tiap
keputusan di bawah ini (per-channel, per-role, per-permission).

PERUBAHAN BESAR dari versi v1:
- Skema lama: {channel: {role: bool}} — satu bool sekaligus mengatur
  `view_channel` DAN `send_messages`, tidak bisa merepresentasikan
  read-only atau kontrol thread/reaction/attach dsb.
- Skema baru: {channel: {role_key: {permission_name: bool}}} — setiap
  permission Discord (view_channel, send_messages, create_public_threads,
  send_messages_in_threads, add_reactions, attach_files, dst) diatur
  independen per role per channel.
- Role key "everyone" adalah kata kunci khusus yang di-resolve ke
  `guild.default_role` oleh permission_engine.py — BUKAN dicari lewat
  shared/config.get_role_id().
- CHANNEL_PERMISSIONS sekarang mencakup SEMUA channel yang butuh overwrite
  (bukan cuma channel VIP) — termasuk channel publik (dulu ditangani
  terpisah lewat PUBLIC_CHANNELS_FOR_DRIFTER + apply_drifter_permission(),
  yang sekarang DIHAPUS karena redundan: cukup declare "everyone": {...}
  langsung di sini).
- Channel yang TIDAK muncul di dict ini (mis. voice `Lounge`, `➕ Join to
  Create`) berarti sengaja tidak diberi overwrite — cukup warisan
  permission kategori (lihat PERMISSION_MATRIX.md bagian 10).

Nama key permission harus PERSIS sama dengan nama kwarg
`discord.PermissionOverwrite` (mis. `view_channel`, `send_messages`,
`create_public_threads`, `connect`, `speak`, dst) — permission_engine.py
meneruskannya langsung sebagai **kwargs, jadi typo di sini akan meledak
saat runtime (TypeError), bukan silent-fail.

CATATAN NAMA CHANNEL: key di dict ini harus cocok (case-insensitive)
dengan nama channel di Discord. Kalau nama channel di server kamu beda
dari yang tertulis di sini (mis. "Staff Voice" vs "staff-voice"), restore
akan melewati channel itu dengan log "tidak ditemukan" — cek lewat
`/permission sync_roles`.
"""

# ============================================================================
# TABEL PERMISSION — SEMUA CHANNEL
# Format: channel_name (huruf kecil sesuai nama Discord): {
#     role_key: {permission_kwarg: bool, ...}
# }
# role_key "everyone" -> guild.default_role
# role_key lain -> di-resolve lewat shared.config.get_role_id()
# ============================================================================

CHANNEL_PERMISSIONS: dict[str, dict[str, dict[str, bool]]] = {

    # ------------------------------------------------------------------
    # SERVER INFO — read-only, staff/bot yang posting
    # ------------------------------------------------------------------
    "welcome-and-rules": {
        "everyone": {
            "view_channel": True, "send_messages": False,
            "create_public_threads": False, "add_reactions": True,
            "read_message_history": True, "attach_files": False,
            "embed_links": False,
        },
        "royal_guard": {"view_channel": True, "send_messages": True, "create_public_threads": True, "manage_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True, "create_public_threads": True, "manage_messages": True},
    },
    "announcements": {
        "everyone": {
            "view_channel": True, "send_messages": False,
            "create_public_threads": False, "add_reactions": True,
            "read_message_history": True, "attach_files": False,
            "embed_links": False,
        },
        "royal_guard": {"view_channel": True, "send_messages": True, "create_public_threads": True, "manage_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True, "create_public_threads": True, "manage_messages": True},
    },
    "channel-guide": {
        "everyone": {"view_channel": True, "send_messages": False, "create_public_threads": False, "add_reactions": True, "read_message_history": True},
        "royal_guard": {"view_channel": True, "send_messages": True, "manage_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True, "manage_messages": True},
    },
    "join-log": {
        "everyone": {"view_channel": True, "send_messages": False, "create_public_threads": False, "add_reactions": True, "read_message_history": True},
        "royal_guard": {"view_channel": True, "send_messages": True, "manage_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True, "manage_messages": True},
    },
    "role-assign": {
        "everyone": {"view_channel": True, "send_messages": False, "add_reactions": True, "read_message_history": True},
        "royal_guard": {"view_channel": True, "send_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True},
    },

    # ------------------------------------------------------------------
    # KOTABI SYSTEM
    # ------------------------------------------------------------------
    "membership": {
        "everyone": {"view_channel": True, "send_messages": False, "add_reactions": True, "read_message_history": True},
        "royal_guard": {"send_messages": True},
        "prime_minister": {"send_messages": True},
    },
    "honor-board": {
        "everyone": {"view_channel": True, "send_messages": False, "add_reactions": True, "read_message_history": True},
        "royal_guard": {"send_messages": True},
        "prime_minister": {"send_messages": True},
    },
    "bot-commands": {
        "everyone": {"view_channel": True, "send_messages": True, "create_public_threads": True, "add_reactions": True},
    },

    # ------------------------------------------------------------------
    # JAPANESE AREA
    # ------------------------------------------------------------------
    "questions-forum": {  # ForumChannel BARU (1527241425488707634), menggantikan homework-help (dihapus)
        "everyone": {"view_channel": True, "create_public_threads": True, "send_messages_in_threads": True, "add_reactions": True, "attach_files": True},
        "royal_guard": {"manage_threads": True},
        "prime_minister": {"manage_threads": True},
    },
    "jlpt-study-group": {
        "everyone": {"view_channel": True, "send_messages": True, "create_public_threads": True, "send_messages_in_threads": True, "add_reactions": True},
    },

    # ------------------------------------------------------------------
    # COMMUNITY
    # ------------------------------------------------------------------
    "general": {
        "everyone": {
            "view_channel": True, "send_messages": True, "create_public_threads": True,
            "send_messages_in_threads": True, "add_reactions": True, "attach_files": True,
            "embed_links": True, "use_external_emojis": True, "use_external_stickers": True,
            "mention_everyone": False,
        },
        "royal_guard": {"manage_messages": True, "mention_everyone": True},
        "prime_minister": {"manage_messages": True, "mention_everyone": True},
    },
    "jp-general": {
        "everyone": {
            "view_channel": True, "send_messages": True, "create_public_threads": True,
            "send_messages_in_threads": True, "add_reactions": True, "attach_files": True,
            "embed_links": True, "use_external_emojis": True, "use_external_stickers": True,
            "mention_everyone": False,
        },
        "royal_guard": {"manage_messages": True, "mention_everyone": True},
        "prime_minister": {"manage_messages": True, "mention_everyone": True},
    },
    "off-topic": {
        "everyone": {
            "view_channel": True, "send_messages": True, "create_public_threads": True,
            "send_messages_in_threads": True, "add_reactions": True, "attach_files": True,
            "embed_links": True, "use_external_emojis": True, "use_external_stickers": True,
            "mention_everyone": False,
        },
        "royal_guard": {"manage_messages": True, "mention_everyone": True},
        "prime_minister": {"manage_messages": True, "mention_everyone": True},
    },

    # ------------------------------------------------------------------
    # QUIZ HALL
    # ------------------------------------------------------------------
    "quiz-public": {  # ForumChannel, di-rename dari quiz-public-forum (ID tetap sama)
        "everyone": {"view_channel": True, "create_public_threads": True, "send_messages_in_threads": True, "add_reactions": True, "attach_files": True},
        "royal_guard": {"manage_threads": True},
        "prime_minister": {"manage_threads": True},
    },
    "quiz-rank-up": {
        # Channel utama DIKUNCI TOTAL — interaksi murni lewat dropdown
        # DynamicQuizMenu, chat cuma boleh di bilik ujian (thread privat
        # yang dibuat bot). Lihat PERMISSION_MATRIX.md bagian 6.
        "everyone": {"view_channel": False, "send_messages": False},
        "trial":     {"view_channel": True, "send_messages": False, "send_messages_in_threads": True, "add_reactions": True},
        "traveler":  {"view_channel": True, "send_messages": False, "send_messages_in_threads": True, "add_reactions": True},
        "companion": {"view_channel": True, "send_messages": False, "send_messages_in_threads": True, "add_reactions": True},
        "patron":    {"view_channel": True, "send_messages": False, "send_messages_in_threads": True, "add_reactions": True},
        "drifter":   {"view_channel": True, "send_messages": False, "send_messages_in_threads": True, "add_reactions": True},  # kuis open_to_drifter
        "royal_guard":    {"view_channel": True, "send_messages": True, "create_private_threads": True},
        "prime_minister": {"view_channel": True, "send_messages": True, "create_private_threads": True},
    },

    # ------------------------------------------------------------------
    # MEMBER LIBRARY (kamus — command-only, semua respons ephemeral)
    # ------------------------------------------------------------------
    "grammar-dic": {
        "everyone":  {"view_channel": False},
        "trial":     {"view_channel": True, "send_messages": False, "read_message_history": True},
        "traveler":  {"view_channel": False},
        "companion": {"view_channel": True, "send_messages": False, "read_message_history": True},
        "patron":    {"view_channel": True, "send_messages": False, "read_message_history": True},
        "royal_guard":    {"view_channel": True, "send_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True},
    },
    "kotoba-dic": {
        "everyone":  {"view_channel": False},
        "trial":     {"view_channel": True, "send_messages": False, "read_message_history": True},
        "traveler":  {"view_channel": False},
        "companion": {"view_channel": True, "send_messages": False, "read_message_history": True},
        "patron":    {"view_channel": True, "send_messages": False, "read_message_history": True},
        "royal_guard":    {"view_channel": True, "send_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True},
    },
    "kanji-dic": {
        "everyone":  {"view_channel": False},
        "trial":     {"view_channel": True, "send_messages": False, "read_message_history": True},
        "traveler":  {"view_channel": False},
        "companion": {"view_channel": True, "send_messages": False, "read_message_history": True},
        "patron":    {"view_channel": True, "send_messages": False, "read_message_history": True},
        "royal_guard":    {"view_channel": True, "send_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True},
    },
    "anime-sentences": {
        "everyone":  {"view_channel": False},
        "trial":     {"view_channel": True, "send_messages": False, "read_message_history": True},
        "traveler":  {"view_channel": False},
        "companion": {"view_channel": True, "send_messages": False, "read_message_history": True},
        "patron":    {"view_channel": True, "send_messages": False, "read_message_history": True},
        "royal_guard":    {"view_channel": True, "send_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True},
    },

    # ------------------------------------------------------------------
    # MEMBER AREA
    # ------------------------------------------------------------------
    "member-lounge": {
        "everyone":  {"view_channel": False},
        "trial":     {"view_channel": True, "send_messages": True, "create_public_threads": True},
        "traveler":  {"view_channel": False},
        "companion": {"view_channel": True, "send_messages": True, "create_public_threads": True},
        "patron":    {"view_channel": True, "send_messages": True, "create_public_threads": True},
        "royal_guard":    {"view_channel": True, "send_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True},
    },
    "immersion-log": {
        "everyone":  {"view_channel": False},
        "trial":     {"view_channel": True, "send_messages": True},
        "traveler":  {"view_channel": True, "send_messages": True},
        "companion": {"view_channel": True, "send_messages": True},
        "patron":    {"view_channel": True, "send_messages": True},
        "royal_guard":    {"view_channel": True, "send_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True},
    },
    "deck-requests": {
        "everyone":  {"view_channel": False},
        "trial":     {"view_channel": True, "send_messages": True, "attach_files": True},
        "traveler":  {"view_channel": False},
        "companion": {"view_channel": True, "send_messages": True, "attach_files": True},
        "patron":    {"view_channel": True, "send_messages": True, "attach_files": True},
        "royal_guard":    {"view_channel": True, "send_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True},
    },
    "immersion-race": {
        "everyone":  {"view_channel": False},
        "trial":     {"view_channel": True, "send_messages": True, "attach_files": True},
        "traveler":  {"view_channel": False},
        "companion": {"view_channel": True, "send_messages": True, "attach_files": True},
        "patron":    {"view_channel": True, "send_messages": True, "attach_files": True},
        "royal_guard":    {"view_channel": True, "send_messages": True},
        "prime_minister": {"view_channel": True, "send_messages": True},
    },

    # ------------------------------------------------------------------
    # RESOURCES SHARING
    # ------------------------------------------------------------------
    "notes-and-resources": {
        "everyone": {"view_channel": True, "send_messages": True, "attach_files": True, "embed_links": True},
        "royal_guard": {"manage_messages": True},
        "prime_minister": {"manage_messages": True},
    },

    # ------------------------------------------------------------------
    # STAFF (text)
    # ------------------------------------------------------------------
    "staff-chat": {
        "everyone": {"view_channel": False, "send_messages": False},
        "royal_guard":    {"view_channel": True, "send_messages": True, "manage_messages": True, "create_public_threads": True, "mention_everyone": True},
        "prime_minister": {"view_channel": True, "send_messages": True, "manage_messages": True, "create_public_threads": True, "mention_everyone": True},
    },
    "order-review": {
        "everyone": {"view_channel": False, "send_messages": False},
        "royal_guard":    {"view_channel": True, "send_messages": True, "manage_messages": True, "attach_files": True, "embed_links": True},
        "prime_minister": {"view_channel": True, "send_messages": True, "manage_messages": True, "attach_files": True, "embed_links": True},
    },

    # ------------------------------------------------------------------
    # STAFF (voice) — BARU, ID 1527247030680817694
    # ------------------------------------------------------------------
    "staff voice": {
        "everyone": {"view_channel": False, "connect": False},
        "royal_guard":    {"view_channel": True, "connect": True, "speak": True, "stream": True},
        "prime_minister": {"view_channel": True, "connect": True, "speak": True, "stream": True},
    },
}

# ============================================================================
# ROLE KEYS — dipakai oleh /permission sync_roles untuk validasi
# ============================================================================
# Diturunkan OTOMATIS dari CHANNEL_PERMISSIONS (kecuali "everyone", yang
# di-resolve ke guild.default_role, bukan lewat get_role_id()) — supaya
# menambah role baru ke tabel di atas otomatis ikut divalidasi tanpa perlu
# diduplikasi manual di sini seperti versi v1.
ROLE_KEYS_USED: list[str] = sorted({
    role_key
    for rules in CHANNEL_PERMISSIONS.values()
    for role_key in rules
    if role_key != "everyone"
})