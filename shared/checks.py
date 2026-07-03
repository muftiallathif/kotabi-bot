"""
shared/checks.py — Reusable Access Control untuk Kotabi Bot
=============================================================
Semua role ID dibaca dari shared/server_map.yml + membership_settings.yml
via shared/config.py. TIDAK ada hardcode ID di sini.

Penggunaan decorator:
    from shared.checks import is_vip, is_premium, is_staff, is_authorized

    @app_commands.command(name='log', ...)
    @is_vip()
    async def log(self, interaction, ...):

Penggunaan helper langsung:
    from shared.checks import has_vip_role, has_authorized_access
"""

import os
import discord
from discord import app_commands
from typing import Optional

from shared.config import get_vip_role_ids, get_paid_role_ids, get_staff_role_ids

AUTHORIZED_USER_IDS: set[int] = {
    int(uid)
    for uid in os.getenv("AUTHORIZED_USERS", "").split(",")
    if uid.strip()
}

MSG_VIP_ONLY = (
    "❌ Fitur ini hanya tersedia untuk **member VIP** Kerajaan Kotabi.\n\n"
    "🎒 **Traveler** — Rp40.000 / bulan\n"
    "🤝 **Companion** — Rp80.000 / bulan\n"
    "👑 **Patron** — Seumur hidup\n\n"
    "Hubungi staf untuk mendaftar! 🙇‍♂️"
)

MSG_PREMIUM_ONLY = (
    "❌ Fitur ini hanya tersedia untuk **member berbayar** (bukan Trial).\n\n"
    "🎒 **Traveler** — Rp40.000 / bulan\n"
    "🤝 **Companion** — Rp80.000 / bulan\n\n"
    "Hubungi staf untuk mendaftar! 🙇‍♂️"
)

MSG_STAFF_ONLY      = "❌ Anda tidak memiliki wewenang untuk menggunakan perintah ini."
MSG_AUTHORIZED_ONLY = "❌ Anda tidak memiliki wewenang untuk menjalankan perintah ini."
MSG_GUILD_ONLY      = "❌ Perintah ini hanya dapat digunakan di dalam server."


def has_authorized_access(user: discord.Member | discord.User) -> bool:
    if user.id in AUTHORIZED_USER_IDS:
        return True
    if isinstance(user, discord.Member) and user.guild_permissions.administrator:
        return True
    return False


def has_vip_role(member: discord.Member, guild_id: int = None) -> bool:
    if member.guild_permissions.administrator:
        return True
    gid = guild_id or member.guild.id
    member_role_ids = {role.id for role in member.roles}
    if any(rid in member_role_ids for rid in get_staff_role_ids(gid).values()):
        return True
    return any(rid in member_role_ids for rid in get_vip_role_ids(gid).values())

def has_vip_role_from_ids(guild_id: int, role_ids: set[int]) -> bool:
    """
    Sama seperti has_vip_role(), tapi buat tempat yang cuma punya
    set role_ids (bukan objek discord.Member utuh) — dipakai di
    journey_service.py yang beroperasi di atas member_role_ids saja.
    """
    if any(rid in role_ids for rid in get_staff_role_ids(guild_id).values()):
        return True
    return any(rid in role_ids for rid in get_vip_role_ids(guild_id).values())


def has_premium_role(member: discord.Member, guild_id: int = None) -> bool:
    if member.guild_permissions.administrator:
        return True
    gid = guild_id or member.guild.id
    member_role_ids = {role.id for role in member.roles}
    if any(rid in member_role_ids for rid in get_staff_role_ids(gid).values()):
        return True
    return any(rid in member_role_ids for rid in get_paid_role_ids(gid).values())


def has_staff_role(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    gid = member.guild.id
    member_role_ids = {role.id for role in member.roles}
    return any(rid in member_role_ids for rid in get_staff_role_ids(gid).values())


def get_member_tier(member: discord.Member) -> Optional[str]:
    gid = member.guild.id
    member_role_ids = {role.id for role in member.roles}
    vip_ids = get_vip_role_ids(gid)
    # "scholar" dihapus dari daftar — bukan tier v3 (lihat membership_settings.yml).
    tier_priority = ["patron", "companion", "traveler", "trial"]
    for tier in tier_priority:
        if vip_ids.get(tier) in member_role_ids:
            return tier
    return None


def is_authorized():
    async def predicate(interaction: discord.Interaction) -> bool:
        if has_authorized_access(interaction.user):
            return True
        await interaction.response.send_message(MSG_AUTHORIZED_ONLY, ephemeral=True)
        return False
    return app_commands.check(predicate)


def is_vip():
    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(MSG_GUILD_ONLY, ephemeral=True)
            return False
        if has_vip_role(member, interaction.guild_id):
            return True
        await interaction.response.send_message(MSG_VIP_ONLY, ephemeral=True)
        return False
    return app_commands.check(predicate)


def is_premium():
    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(MSG_GUILD_ONLY, ephemeral=True)
            return False
        if has_premium_role(member, interaction.guild_id):
            return True
        await interaction.response.send_message(MSG_PREMIUM_ONLY, ephemeral=True)
        return False
    return app_commands.check(predicate)


def is_staff():
    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(MSG_GUILD_ONLY, ephemeral=True)
            return False
        if has_staff_role(member):
            return True
        await interaction.response.send_message(MSG_STAFF_ONLY, ephemeral=True)
        return False
    return app_commands.check(predicate)


def is_vip_or_dm():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return True
        member = interaction.user
        if has_vip_role(member, interaction.guild_id):
            return True
        await interaction.response.send_message(MSG_VIP_ONLY, ephemeral=True)
        return False
    return app_commands.check(predicate)