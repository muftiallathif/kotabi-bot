"""
lib/checks.py — Reusable Access Control untuk Kotabi Bot
=========================================================
Semua role ID dibaca dari server_map.yml + membership_settings.yml via lib/config.py.
TIDAK ada hardcode ID di sini. Kalau role berubah → cukup edit YAML.

Penggunaan decorator:
    from lib.checks import is_vip, is_premium, is_staff, is_authorized

    @app_commands.command(name='log', ...)
    @is_vip()
    async def log(self, interaction, ...):

    @app_commands.command(name='post_db', ...)
    @is_authorized()
    async def post_db(self, interaction, ...):

Penggunaan helper langsung (misal di non-slash context):
    from lib.checks import has_vip_role, has_authorized_access

    if not has_vip_role(member):
        return

    if not has_authorized_access(interaction.user):
        return
"""

import os
import discord
from discord import app_commands
from typing import Optional

from lib.config import get_vip_role_ids, get_paid_role_ids, get_staff_role_ids

# ============================================================================
# AUTHORIZED USER IDS
# Dibaca dari env var AUTHORIZED_USERS — sama persis dengan pola di cog-cog
# admin yang selama ini duplikasi baris ini sendiri-sendiri.
# Single source of truth: ubah env var, semua cog ikut.
# ============================================================================

AUTHORIZED_USER_IDS: set[int] = {
    int(uid)
    for uid in os.getenv("AUTHORIZED_USERS", "").split(",")
    if uid.strip()
}

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

MSG_STAFF_ONLY      = "❌ Anda tidak memiliki wewenang untuk menggunakan perintah ini."
MSG_AUTHORIZED_ONLY = "❌ Anda tidak memiliki wewenang untuk menjalankan perintah ini."
MSG_GUILD_ONLY      = "❌ Perintah ini hanya dapat digunakan di dalam server."


# ============================================================================
# HELPER FUNCTIONS
# Bisa dipanggil langsung tanpa decorator, misal di DynamicQuizMenu.callback
# ============================================================================

def has_authorized_access(user: discord.Member | discord.User) -> bool:
    """
    True jika user ada di AUTHORIZED_USER_IDS atau punya permission Administrator
    di guild-nya.

    Ini menggantikan fungsi _is_authorized() yang selama ini diduplikasi
    di export_server.py, restructure_server.py, backup_discord_server.py,
    database_backup.py, watchdog.py, dan sync.py.

    Contoh:
        if not has_authorized_access(interaction.user):
            return await interaction.followup.send(MSG_AUTHORIZED_ONLY, ephemeral=True)
    """
    if user.id in AUTHORIZED_USER_IDS:
        return True
    # guild_permissions tersedia jika user adalah discord.Member (bukan User di DM)
    if isinstance(user, discord.Member) and user.guild_permissions.administrator:
        return True
    return False


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

def is_authorized():
    """
    Decorator slash command: user harus ada di AUTHORIZED_USER_IDS
    atau punya permission Administrator.

    Menggantikan _is_authorized() lokal di tiap cog admin.

    Contoh:
        @app_commands.command(name='post_db')
        @is_authorized()
        async def post_db(self, interaction):
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        if has_authorized_access(interaction.user):
            return True
        await interaction.response.send_message(MSG_AUTHORIZED_ONLY, ephemeral=True)
        return False

    return app_commands.check(predicate)


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
        @app_commands.command(name='say message')
        @is_staff()
        async def say_message(self, interaction):
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