"""
shared/config.py — Pusat Pembaca Konfigurasi Kotabi Bot
=========================================================
SINGLE SOURCE OF TRUTH untuk semua ID dan konfigurasi umum.

Semua fitur cukup import dari sini. Jangan hardcode ID di cog manapun.

Penggunaan:
    from shared.config import get_role_id, get_channel_id, get_vip_role_ids, get_active_prices

Jika ada perubahan role/channel ID -> cukup edit shared/server_map.yml, selesai.
Jika ada perubahan HARGA tier VIP -> cukup edit features/membership/pricing_presets.yml
(ganti active_preset), selesai. Lihat PRICING_SYSTEM_REFACTOR.md.

⚠️ TAHAP 8: get_tier_info() DIHAPUS dari file ini — fungsi ini punya NOL
caller di seluruh codebase (dead code), dan field yang dibacanya
(roles.*.name, roles.*.duration_days, lifetime.name di
membership_settings.yml) sudah ikut dihapus juga karena cuma bisa
diakses lewat fungsi ini. Kalau suatu saat butuh info tier lengkap lagi,
sumber nama & durasi yang BENAR sekarang ada di
features/membership/products.yml (lewat ProductLoader), bukan di sini.
"""

import os
import yaml
import logging
from typing import Optional

logger = logging.getLogger("bot.config")

CONFIG_PATH = "shared/server_map.yml"
MEMBERSHIP_PATH = "features/membership/membership_settings.yml"
PRICING_PRESETS_PATH = "features/membership/pricing_presets.yml"

# ============================================================================
# INTERNAL CACHE
# ============================================================================

_server_map: dict = {}
_membership_cfg: dict = {}
_pricing_presets_cfg: dict = {}


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


def _load_pricing_presets() -> dict:
    global _pricing_presets_cfg
    if _pricing_presets_cfg:
        return _pricing_presets_cfg
    if not os.path.exists(PRICING_PRESETS_PATH):
        logger.warning(f"⚠️ File {PRICING_PRESETS_PATH} tidak ditemukan!")
        return {}
    try:
        with open(PRICING_PRESETS_PATH, "r", encoding="utf-8") as f:
            _pricing_presets_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"❌ Gagal memuat {PRICING_PRESETS_PATH}: {e}")
        return {}
    return _pricing_presets_cfg


def reload_config():
    """Paksa reload semua config dari disk. Panggil jika YAML diubah saat runtime."""
    global _server_map, _membership_cfg, _pricing_presets_cfg
    _server_map = {}
    _membership_cfg = {}
    _pricing_presets_cfg = {}
    _load_server_map()
    _load_membership_cfg()
    _load_pricing_presets()
    logger.info("✅ Semua config berhasil di-reload dari disk.")


# ============================================================================
# ROLE HELPERS
# ============================================================================

def get_role_id(guild_id: int, role_name: str) -> int:
    data = _load_server_map()
    role_id = data.get("roles", {}).get(role_name, 0)
    if not role_id:
        logger.warning(f"⚠️ Role '{role_name}' tidak ditemukan di server_map.yml")
    return int(role_id)


def get_all_role_ids(guild_id: int, *role_names: str) -> dict[str, int]:
    return {name: get_role_id(guild_id, name) for name in role_names}


def get_vip_role_ids(guild_id: int) -> dict[str, int]:
    """
    Return semua role tier VIP: trial, traveler, companion, (scholar kalau
    diisi), DAN patron.

    FIX: di membership_settings.yml, blok `lifetime:` (berisi role_id Patron)
    SEJAJAR dengan `roles:`, BUKAN nested di dalamnya:

        membership:
          roles:
            trial: {...}
            traveler: {...}
            companion: {...}
          lifetime:              # <- sejajar dengan "roles", bukan child-nya
              role_id: ...
              point_threshold: 24

    Versi lama cuma baca cfg["roles"], jadi Patron TIDAK PERNAH masuk ke hasil
    dict ini -> has_vip_role()/has_premium_role()/has_dic_access()/
    get_member_tier() (semua di shared/checks.py) menolak member yang cuma
    punya role Patron murni (tanpa Companion/Traveler menyertai, sesuai
    TIER_ROLE_CHAIN di role_resolver.py: patron -> [patron] saja). Di-gabung
    manual di sini supaya Patron ikut terhitung sebagai VIP role tanpa perlu
    ubah caller manapun.
    """
    cfg = _load_membership_cfg()
    roles_cfg = dict(cfg.get("roles", {}))

    lifetime_cfg = cfg.get("lifetime", {})
    if lifetime_cfg.get("role_id"):
        roles_cfg = {**roles_cfg, "patron": lifetime_cfg}

    result = {}
    for tier_name, tier_data in roles_cfg.items():
        role_id = tier_data.get("role_id")
        if role_id:
            result[tier_name] = int(role_id)
    return result


def get_paid_role_ids(guild_id: int) -> dict[str, int]:
    all_vip = get_vip_role_ids(guild_id)
    return {k: v for k, v in all_vip.items() if k != "trial"}


def get_staff_role_ids(guild_id: int) -> dict[str, int]:
    return get_all_role_ids(guild_id, "royal_guard", "prime_minister")


def get_lifetime_threshold() -> int:
    """
    FIX: sebelumnya baca cfg["roles"]["lifetime"]["point_threshold"], padahal
    "lifetime" sejajar dengan "roles", bukan di dalamnya -> selalu fallback ke
    default (30), TIDAK PERNAH membaca nilai 24 yang sudah diisi di YAML.
    """
    cfg = _load_membership_cfg()
    return int(cfg.get("lifetime", {}).get("point_threshold", 30))


# ============================================================================
# PRICING HELPERS
# ============================================================================

def get_active_prices() -> dict:
    """
    Satu-satunya fungsi yang boleh dipanggil tempat lain untuk tahu harga
    tier VIP saat ini (Traveler/Companion/Patron, termasuk varian 6 bulan
    dan 1 tahun). Baca features/membership/pricing_presets.yml, resolve
    preset aktif (`active_preset`), lalu hitung otomatis harga 6bln/1thn
    dari `duration_multipliers` — TIDAK ada angka harga kedua yang
    di-hardcode di sini atau di tempat lain manapun.

    Return:
        {
            "preset": int,  # nomor preset aktif (0 = fallback, lihat bawah)
            "patron": int,
            "traveler": {
                "monthly": int, "6mo": int, "12mo": int,
                "points_6mo": int, "points_12mo": int,
            },
            "companion": {
                "monthly": int, "6mo": int, "12mo": int,
                "points_6mo": int, "points_12mo": int,
            },
        }

    Kalau pricing_presets.yml tidak ada / active_preset tidak valid,
    fallback ke harga normal (Traveler 40rb, Companion 80rb, Patron 449rb)
    supaya bot tidak crash total kalau file preset bermasalah — preset
    hasil fallback ditandai dengan "preset": 0 (bukan 1-6 asli), berguna
    untuk logging/debug kalau harga yang tampil di bot kelihatan aneh.
    """
    cfg = _load_pricing_presets()

    FALLBACK_PRESET = {"traveler": 40000, "companion": 80000, "patron": 449000}
    FALLBACK_MULTIPLIERS = {"6_month": 5, "12_month": 10}
    FALLBACK_POINTS = {"traveler": 1, "companion": 2}

    active_preset_num = cfg.get("active_preset")
    presets = cfg.get("presets", {})
    preset = presets.get(active_preset_num)

    if not preset:
        logger.warning(
            f"⚠️ active_preset {active_preset_num!r} tidak ditemukan di "
            f"pricing_presets.yml, fallback ke harga normal."
        )
        preset = FALLBACK_PRESET
        active_preset_num = 0  # menandakan fallback, bukan preset asli 1-6

    multipliers = cfg.get("duration_multipliers") or FALLBACK_MULTIPLIERS
    points_per_month = cfg.get("points_per_month") or FALLBACK_POINTS

    result = {"preset": active_preset_num, "patron": preset["patron"]}

    for tier in ("traveler", "companion"):
        monthly = preset[tier]
        result[tier] = {
            "monthly": monthly,
            "6mo": monthly * multipliers["6_month"],
            "12mo": monthly * multipliers["12_month"],
            "points_6mo": points_per_month[tier] * 6,
            "points_12mo": points_per_month[tier] * 12,
        }

    return result


# ============================================================================
# MEMBERSHIP GUILD/CHANNEL HELPERS
# ============================================================================

def get_membership_guild_id() -> int:
    cfg = _load_membership_cfg()
    guild_id = cfg.get("guild_id", 0)
    if not guild_id:
        logger.warning("⚠️ 'guild_id' tidak ditemukan di membership_settings.yml")
    return int(guild_id)


def get_announcement_channel_id() -> int:
    cfg = _load_membership_cfg()
    return int(cfg.get("announcement_channel_id", 0))


def get_order_review_channel_id() -> int:
    cfg = _load_membership_cfg()
    return int(cfg.get("order_review_channel_id") or cfg.get("announcement_channel_id", 0))


def get_grace_period_days() -> int:
    cfg = _load_membership_cfg()
    return int(cfg.get("grace_period_days", 3))


def get_moderator_role_ids() -> list[int]:
    cfg = _load_membership_cfg()
    return [int(r) for r in cfg.get("moderator_role_ids", [])]

# ============================================================================
# CHANNEL HELPERS
# ============================================================================

def get_channel_id(guild_id: int, channel_name: str) -> int:
    data = _load_server_map()
    channel_id = data.get("channels", {}).get(channel_name, 0)
    if not channel_id:
        logger.warning(f"⚠️ Channel '{channel_name}' tidak ditemukan di server_map.yml")
    return int(channel_id)


def get_bank_account_info() -> dict:
    cfg = _load_membership_cfg()
    return cfg.get("bank_account", {})