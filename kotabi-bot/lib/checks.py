"""
lib/checks.py — Reusable VIP Access Control untuk Kotabi Bot
=============================================================
Semua role ID dibaca dari server_map.yml + membership_settings.yml via lib/config.py.
TIDAK ada hardcode ID di sini. Kalau role berubah → cukup edit YAML.

Penggunaan decorator:
    from lib.checks import is_vip, is_premium, is_staff

    @app_commands.command(name='log', ...)
    @is_vip()
    async def log(self, interaction, ...):

Penggunaan helper langsung (misal di non-slash context):
    from lib.checks import has_vip_role

    if not has_vip_role(member):
        return
"""

import discord
from discord import app_commands
from typing import Optional

from lib.config import get_vip_role_ids, get_paid_role_ids, get_staff_role_ids

# ============================================================================
# PESAN ERROR — edit di sini jika teks perlu diubah, tidak perlu cari per-cog
# ============================================================================

MSG_VIP_ONLY = (
    "❌ Fitur ini hanya tersedia untuk **member VIP** Kerajaan Kotabi.\n\n"
    "🎒 **Traveler** — Rp46.000 / bulan\n"
    "🤝 **Companion** — Rp92.000 / bulan\n"
    "📚 **Scholar** — Rp350.000 / bulan\n"
    "👑 **Patron** — Seumur hidup\n\n"
    "Hubungi staf untuk mendaftar! 🙇‍♂️"
)

MSG_PREMIUM_ONLY = (
    "❌ Fitur ini hanya tersedia untuk **member berbayar** (bukan Trial).\n\n"
    "🎒 **Traveler** — Rp46.000 / bulan\n"
    "🤝 **Companion** — Rp92.000 / bulan\n"
    "📚 **Scholar** — Rp350.000 / bulan\n\n"
    "Hubungi staf untuk mendaftar! 🙇‍♂️"
)

MSG_STAFF_ONLY = "❌ Anda tidak memiliki wewenang untuk menggunakan perintah ini."
MSG_GUILD_ONLY = "❌ Perintah ini hanya dapat digunakan di dalam server."


# ============================================================================
# HELPER FUNCTIONS
# Bisa dipanggil langsung tanpa decorator, misal di DynamicQuizMenu.callback
# ============================================================================

def has_vip_role(member: discord.Member, guild_id: int = None) -> bool:
    """
    True jika member punya role VIP (termasuk trial), staff, atau Administrator.

    Contoh:
        if not has_vip_role(interaction.user, interaction.guild_id):
            await interaction.followup.send(MSG_VIP_ONLY, ephemeral=True)
            return
    """
    if member.guild_permissions.administrator:
        return True

    gid = guild_id or member.guild.id
    member_role_ids = {role.id for role in member.roles}

    if any(rid in member_role_ids for rid in get_staff_role_ids(gid).values()):
        return True

    return any(rid in member_role_ids for rid in get_vip_role_ids(gid).values())


def has_premium_role(member: discord.Member, guild_id: int = None) -> bool:
    """
    True jika member punya role paid (TIDAK termasuk trial), staff, atau Administrator.
    Dipakai untuk fitur seperti custom_role yang butuh paid member.
    """
    if member.guild_permissions.administrator:
        return True

    gid = guild_id or member.guild.id
    member_role_ids = {role.id for role in member.roles}

    if any(rid in member_role_ids for rid in get_staff_role_ids(gid).values()):
        return True

    return any(rid in member_role_ids for rid in get_paid_role_ids(gid).values())


def has_staff_role(member: discord.Member) -> bool:
    """True jika member adalah Royal Guard, Prime Minister, atau Administrator."""
    if member.guild_permissions.administrator:
        return True

    gid = member.guild.id
    member_role_ids = {role.id for role in member.roles}
    return any(rid in member_role_ids for rid in get_staff_role_ids(gid).values())


def get_member_tier(member: discord.Member) -> Optional[str]:
    """
    Mengembalikan tier tertinggi yang dimiliki member.
    Return: 'patron' | 'scholar' | 'companion' | 'traveler' | 'trial' | None

    Contoh:
        tier = get_member_tier(member)
        if tier in ("companion", "scholar", "patron"):
            # akses fitur premium
    """
    gid = member.guild.id
    member_role_ids = {role.id for role in member.roles}
    vip_ids = get_vip_role_ids(gid)

    # Urutan prioritas dari tertinggi ke terendah
    tier_priority = ["patron", "scholar", "companion", "traveler", "trial"]
    for tier in tier_priority:
        if vip_ids.get(tier) in member_role_ids:
            return tier
    return None


# ============================================================================
# APP COMMAND DECORATORS
# ============================================================================

def is_vip():
    """
    Decorator slash command: user harus punya role VIP (termasuk trial).

    Contoh:
        @app_commands.command(name='log')
        @is_vip()
        async def log(self, interaction, ...):
    """
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
    """
    Decorator slash command: user harus punya role paid (tidak termasuk trial).

    Contoh:
        @app_commands.command(name='create_role')
        @is_premium()
        async def create_role(self, interaction, ...):
    """
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
    """
    Decorator slash command: user harus staff atau Administrator.

    Contoh:
        @app_commands.command(name='post_db')
        @is_staff()
        async def post_db(self, interaction):
    """
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
    """
    Decorator: izinkan jika user VIP ATAU command dipakai di DM.
    Cocok untuk command seperti log_view_goals yang bisa diakses dari DM.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        # DM — selalu lolos
        if interaction.guild is None:
            return True

        member = interaction.user
        if has_vip_role(member, interaction.guild_id):
            return True

        await interaction.response.send_message(MSG_VIP_ONLY, ephemeral=True)
        return False

    return app_commands.check(predicate)