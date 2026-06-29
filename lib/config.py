"""
lib/config.py — Pusat Pembaca Konfigurasi Kotabi Bot
=====================================================
SINGLE SOURCE OF TRUTH untuk semua ID dan konfigurasi.

Semua file lain cukup import dari sini. Jangan hardcode ID di cog manapun.

Penggunaan:
    from lib.config import get_role_id, get_channel_id, get_vip_role_ids

Jika ada perubahan role/channel ID → cukup edit server_map.yml, selesai.
"""

import os
import yaml
import logging
from typing import Optional

logger = logging.getLogger("bot.config")

CONFIG_PATH = "config/server_map.yml"
MEMBERSHIP_PATH = "config/membership_settings.yml"

# ============================================================================
# INTERNAL CACHE
# Dibaca sekali dari disk, disimpan di memory.
# Panggil reload_config() jika file YAML diubah saat bot berjalan.
# ============================================================================

_server_map: dict = {}
_membership_cfg: dict = {}


def _load_server_map() -> dict:
    global _server_map
    if _server_map:
        return _server_map
    if not os.path.exists(CONFIG_PATH):
        logger.warning(f"⚠️ File {CONFIG_PATH} tidak ditemukan!")
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _server_map = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"❌ Gagal memuat {CONFIG_PATH}: {e}")
        return {}
    return _server_map


def _load_membership_cfg() -> dict:
    global _membership_cfg
    if _membership_cfg:
        return _membership_cfg
    if not os.path.exists(MEMBERSHIP_PATH):
        logger.warning(f"⚠️ File {MEMBERSHIP_PATH} tidak ditemukan!")
        return {}
    try:
        with open(MEMBERSHIP_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            _membership_cfg = data.get("membership", {})
    except Exception as e:
        logger.error(f"❌ Gagal memuat {MEMBERSHIP_PATH}: {e}")
        return {}
    return _membership_cfg


def reload_config():
    """Paksa reload semua config dari disk. Panggil jika YAML diubah saat runtime."""
    global _server_map, _membership_cfg
    _server_map = {}
    _membership_cfg = {}
    _load_server_map()
    _load_membership_cfg()
    logger.info("✅ Semua config berhasil di-reload dari disk.")


# ============================================================================
# ROLE HELPERS
# ============================================================================

def get_role_id(guild_id: int, role_name: str) -> int:
    """
    Mengambil ID role berdasarkan nama kunci dari server_map.yml.
    Parameter guild_id dipertahankan untuk kompatibilitas multi-server ke depan.

    Contoh:
        patron_id = get_role_id(guild_id, "patron")
    """
    data = _load_server_map()
    role_id = data.get("roles", {}).get(role_name, 0)
    if not role_id:
        logger.warning(f"⚠️ Role '{role_name}' tidak ditemukan di server_map.yml")
    return int(role_id)


def get_all_role_ids(guild_id: int, *role_names: str) -> dict[str, int]:
    """
    Mengambil banyak role ID sekaligus. Lebih efisien dari memanggil get_role_id berkali-kali.

    Contoh:
        ids = get_all_role_ids(guild_id, "patron", "companion", "traveler")
        # → {"patron": 123, "companion": 456, "traveler": 789}
    """
    return {name: get_role_id(guild_id, name) for name in role_names}


def get_vip_role_ids(guild_id: int) -> dict[str, int]:
    """
    Mengembalikan dict semua role VIP (termasuk trial).
    Definisi VIP baca dari membership_settings.yml → tidak perlu hardcode.

    Return: {"trial": id, "traveler": id, "companion": id, "scholar": id, "patron": id}
    """
    cfg = _load_membership_cfg()
    roles_cfg = cfg.get("roles", {})

    # Ambil semua tier yang didefinisikan di membership_settings.yml
    result = {}
    for tier_name, tier_data in roles_cfg.items():
        role_id = tier_data.get("role_id")
        if role_id:
            result[tier_name] = int(role_id)
    return result


def get_paid_role_ids(guild_id: int) -> dict[str, int]:
    """
    Mengembalikan dict role VIP berbayar saja (TIDAK termasuk trial).
    """
    all_vip = get_vip_role_ids(guild_id)
    return {k: v for k, v in all_vip.items() if k != "trial"}


def get_staff_role_ids(guild_id: int) -> dict[str, int]:
    """Mengembalikan dict role staff (Royal Guard + Prime Minister)."""
    return get_all_role_ids(guild_id, "royal_guard", "prime_minister")


def get_tier_info(tier_name: str) -> dict:
    """
    Mengambil informasi lengkap satu tier dari membership_settings.yml.

    Contoh:
        info = get_tier_info("companion")
        # → {"name": "Companion", "role_id": 123, "duration_days": 30, ...}
    """
    cfg = _load_membership_cfg()
    return cfg.get("roles", {}).get(tier_name, {})


def get_lifetime_threshold() -> int:
    """Mengambil jumlah poin untuk unlock Lifetime membership."""
    cfg = _load_membership_cfg()
    return int(cfg.get("roles", {}).get("lifetime", {}).get("point_threshold", 30))


# ============================================================================
# MEMBERSHIP GUILD/CHANNEL HELPERS
# Dipakai oleh cogs/membership.py, membership_scheduler.py, membership_purchase.py
# — supaya ketiganya tidak baca ulang membership_settings.yml sendiri-sendiri.
# ============================================================================

def get_membership_guild_id() -> int:
    """Guild ID utama yang dipakai sistem membership."""
    cfg = _load_membership_cfg()
    guild_id = cfg.get("guild_id", 0)
    if not guild_id:
        logger.warning("⚠️ 'guild_id' tidak ditemukan di membership_settings.yml")
    return int(guild_id)


def get_announcement_channel_id() -> int:
    """Channel untuk pengumuman member baru."""
    cfg = _load_membership_cfg()
    return int(cfg.get("announcement_channel_id", 0))


def get_order_review_channel_id() -> int:
    """
    Channel untuk review order staff.
    Fallback ke announcement_channel_id kalau order_review_channel_id
    belum diisi di YAML.
    """
    cfg = _load_membership_cfg()
    return int(cfg.get("order_review_channel_id") or cfg.get("announcement_channel_id", 0))


def get_grace_period_days() -> int:
    """Jumlah hari peringatan sebelum membership expired (default 3)."""
    cfg = _load_membership_cfg()
    return int(cfg.get("grace_period_days", 3))


def get_moderator_role_ids() -> list[int]:
    """Role ID yang dianggap moderator/staff untuk command membership."""
    cfg = _load_membership_cfg()
    return [int(r) for r in cfg.get("moderator_role_ids", [])]

# ============================================================================
# CHANNEL HELPERS
# ============================================================================

def get_channel_id(guild_id: int, channel_name: str) -> int:
    """
    Mengambil ID channel berdasarkan nama kunci dari server_map.yml.

    Contoh:
        ch_id = get_channel_id(guild_id, "honor_board")
    """
    data = _load_server_map()
    channel_id = data.get("channels", {}).get(channel_name, 0)
    if not channel_id:
        logger.warning(f"⚠️ Channel '{channel_name}' tidak ditemukan di server_map.yml")
    return int(channel_id)


def get_all_channel_ids(guild_id: int, *channel_names: str) -> dict[str, int]:
    """
    Mengambil banyak channel ID sekaligus.

    Contoh:
        ids = get_all_channel_ids(guild_id, "honor_board", "bot_commands")
    """
    return {name: get_channel_id(guild_id, name) for name in channel_names}