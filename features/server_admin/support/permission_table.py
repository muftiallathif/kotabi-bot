"""
features/server_admin/support/permission_table.py — Sumber Tunggal Tabel Permission VIP
==========================================================================================
Dulu tabel ini ter-duplikasi manual di export_server.py DAN restructure_server.py,
dengan komentar "kalau diubah di sini, salin juga ke sana" — bom waktu.
Sekarang permissions_cog.py dan structure_cog.py sama-sama import dari sini
(lewat features/server_admin/support/permission_engine.py, yang menyatukan
LOGIC penerapannya juga — bukan cuma tabelnya).

Kalau mau ubah channel VIP mana yang punya akses ke role apa, ATAU menambah
channel publik baru untuk Drifter, cukup edit file ini SEKALI SAJA.

CATATAN (fix): role "scholar" DIHAPUS dari tabel ini. membership_settings.yml
sudah secara eksplisit menghapus Scholar sebagai tier v3 — tidak ada lagi
bagian dari sistem grant (grants/, service.py, products.yml) yang pernah
menetapkan role ini ke member manapun. Menguncinya sebagai salah satu role
yang di-"allow" di setiap channel VIP adalah beban mati yang tidak
berbahaya (tidak ada yang akan pernah punya role ini secara valid), tapi
tetap membingungkan untuk dibaca. Role ID "scholar" tetap dibiarkan ada di
shared/server_map.yml (untuk member lama yang masih memegangnya secara
manual), hanya dihapus dari tabel restore permission ini.
"""

# ============================================================================
# TABEL VIP PERMISSION
# Sumber kebenaran tunggal untuk semua permission channel VIP.
# Format: channel_name: {role_name: bool}
# True  = allow (view + send)
# False = deny  (tidak bisa lihat sama sekali)
# ============================================================================

# Pemetaan channel ke hak akses per role VIP
# Royal Guard & Prime Minister selalu dapat akses penuh di semua channel VIP
#
# FIX: "member-lounge" sebelumnya punya traveler: True, padahal secara
# kebijakan (lihat MEMBERSHIP_STRATEGY_DECISIONS.md bagian 4 / tabel gap
# fitur) member-lounge satu kelompok dengan deck-requests & immersion-race —
# ketiganya Companion-exclusive. traveler diubah jadi False supaya konsisten
# dengan dua channel lain di kelompok yang sama.
VIP_CHANNEL_PERMISSIONS: dict[str, dict[str, bool]] = {
    "member-lounge":    {"trial": True,  "traveler": False, "companion": True,  "patron": True},
    "immersion-log":    {"trial": True,  "traveler": True,  "companion": True,  "patron": True},
    "quiz-rank-up":     {"trial": True,  "traveler": True,  "companion": True,  "patron": True, "drifter": True},
    "grammar-dic":      {"trial": True,  "traveler": False, "companion": True,  "patron": True},
    "kotoba-dic":       {"trial": True,  "traveler": False, "companion": True,  "patron": True},
    "kanji-dic":        {"trial": True,  "traveler": False, "companion": True,  "patron": True},
    "anime-sentences":  {"trial": True,  "traveler": False, "companion": True,  "patron": True},
    "deck-requests":    {"trial": True,  "traveler": False, "companion": True,  "patron": True},
    "immersion-race":   {"trial": True,  "traveler": False, "companion": True,  "patron": True},
}

# Daftar role key yang dipakai untuk resolusi izin VIP/Drifter.
# ID-nya TIDAK disimpan di sini — selalu di-resolve lewat shared.config.get_role_id()
# dari shared/server_map.yml (single source of truth).
ROLE_KEYS_USED = [
    "trial", "traveler", "companion", "patron",
    "royal_guard", "prime_minister", "drifter",
]

# Channel-channel non-VIP yang perlu dapat akses Drifter
# (semua channel publik yang bukan VIP-only)
#
# PERUBAHAN:
#   - "today-i-learned" dihapus (digabung ke jlpt-study-group)
#   - "quiz-public-1/2/3" diganti satu "quiz-public-forum"
#   - "Study Room 1"/"Study Room 2" diganti "➕ Join to Create"
PUBLIC_CHANNELS_FOR_DRIFTER = [
    "welcome-and-rules",
    "announcements",
    "channel-guide",
    "join-log",
    "role-assign",
    "membership",
    "honor-board",
    "bot-commands",
    "homework-help",
    "jlpt-study-group",
    "general",
    "jp-general",
    "off-topic",
    "quiz-public-forum",
    "notes-and-resources",
    "Lounge",
    "➕ Join to Create",
]