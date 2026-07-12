"""
features/membership/support/helpers.py — Helper Bersama Membership System
=============================================================================
Sebelumnya _send_dm(), _fmt_price(), _fmt_progress() terduplikasi di
admin_cog.py, purchase_cog.py, dan scheduler_cog.py (masing-masing punya
salinan sendiri). Sekarang satu-satunya sumber di sini, di-import oleh
ketiganya — kalau mau ubah perilaku (mis. format harga, pesan error DM
gagal), cukup edit sekali di file ini.
"""

import logging

import discord

from core.bot import KotabiBot
from shared.config import get_lifetime_threshold

_log = logging.getLogger("bot.membership.helpers")


def fmt_price(amount: int) -> str:
    """Format angka rupiah jadi 'Rp80.000'."""
    return f"Rp{amount:,}".replace(",", ".")


def fmt_progress(point_count: int) -> str:
    """Format progres poin lifetime jadi 'X/Y poin (Z poin lagi)'."""
    threshold = get_lifetime_threshold()
    remaining = max(0, threshold - point_count)
    return f"{point_count}/{threshold} poin ({remaining} poin lagi)"


async def send_dm(user_id: int, bot: KotabiBot, embed: discord.Embed) -> bool:
    """Kirim embed via DM ke user_id. Return False (dan log warning) kalau
    DM tertutup atau user tidak ditemukan — caller tidak perlu menangani
    exception sendiri."""
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if not user.dm_channel:
            await user.create_dm()
        await user.send(embed=embed)
        return True
    except (discord.Forbidden, discord.NotFound):
        _log.warning("Tidak bisa DM user %s", user_id)
        return False