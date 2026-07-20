"""
shared/checks.py — Reusable Access Control untuk Kotabi Bot
=============================================================
Semua role ID dibaca dari shared/server_map.yml + membership_settings.yml
via shared/config.py. TIDAK ada hardcode ID di sini.

Semua teks pesan dibaca dari shared/messages.py (Msg). TIDAK ada salinan
teks pesan sendiri di sini — single source of truth untuk copy ada di
messages.py.

Penggunaan decorator:
    from shared.checks import is_vip, is_premium, is_staff, is_authorized

    @app_commands.command(name='log', ...)
    @is_vip()
    async def log(self, interaction, ...):

Penggunaan helper langsung:
    from shared.checks import has_vip_role, has_authorized_access

⚠️ PERUBAHAN PENTING (lihat PRICING_SYSTEM_REFACTOR.md Tahap 5):
MSG_DIC_DETAIL_ONLY DULU konstanta string (dipanggil tanpa kurung).
SEKARANG fungsi — WAJIB dipanggil DENGAN kurung: `MSG_DIC_DETAIL_ONLY()`.
Dipakai di features/dictionary/bunpou_cog.py, kotoba_cog.py, kanji_cog.py
(masing-masing 2 tempat) — lihat instruksi find-replace di chat/log MD
untuk update caller-nya, TIDAK otomatis ikut berubah cuma dengan
mengganti file ini saja.
"""

import os
import discord
from discord import app_commands
from typing import Optional

from shared.config import get_vip_role_ids, get_paid_role_ids, get_staff_role_ids, get_active_prices
from shared.messages import Msg

AUTHORIZED_USER_IDS: set[int] = {
    int(uid)
    for uid in os.getenv("AUTHORIZED_USERS", "").split(",")
    if uid.strip()
}


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
        await interaction.response.send_message(Msg.AUTHORIZED_ONLY, ephemeral=True)
        return False
    return app_commands.check(predicate)


def is_vip():
    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(Msg.GUILD_ONLY, ephemeral=True)
            return False
        if has_vip_role(member, interaction.guild_id):
            return True
        await interaction.response.send_message(Msg.VIP_ONLY(), ephemeral=True)
        return False
    return app_commands.check(predicate)


def is_premium():
    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(Msg.GUILD_ONLY, ephemeral=True)
            return False
        if has_premium_role(member, interaction.guild_id):
            return True
        await interaction.response.send_message(Msg.PREMIUM_ONLY(), ephemeral=True)
        return False
    return app_commands.check(predicate)


def is_staff():
    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(Msg.GUILD_ONLY, ephemeral=True)
            return False
        if has_staff_role(member):
            return True
        await interaction.response.send_message(Msg.STAFF_ONLY, ephemeral=True)
        return False
    return app_commands.check(predicate)


def MSG_DIC_DETAIL_ONLY() -> str:
    """
    Pesan gating detail kamus (/bunpou, /kotoba, /kanji). DULU konstanta
    string, SEKARANG fungsi — harga Companion di dalamnya sekarang ikut
    get_active_prices(), bukan angka beku Rp80.000.

    Nama tetap huruf besar (menyalahi konvensi PEP8 untuk fungsi) supaya
    caller lama gampang ditemukan lewat pencarian teks biasa, dan supaya
    jelas ini pesan "konstan secara konsep" — beda dari fungsi berparameter
    seperti Msg.log_amount_exceeded() dkk.
    """
    prices = get_active_prices()
    return (
        "🔒 **Detail lengkap** (arti, contoh kalimat, cara pakai) khusus member **Trial**, "
        "**Companion**, atau **Patron**.\n\n"
        "Kamu tetap bisa menjelajahi **daftar nama & level** semua entri secara gratis dan "
        "unlimited — cuma detailnya yang terkunci.\n\n"
        f"🤝 **Companion** — {Msg._format_rp(prices['companion']['monthly'])} / bulan\n"
        "👑 **Patron** — Seumur hidup\n\n"
        "Hubungi staf untuk upgrade! 🙇‍♂️"
    )


def has_dic_access(member: discord.Member, guild_id: int = None) -> bool:
    """
    Sama seperti has_vip_role(), TAPI Traveler dikecualikan.
    Dipakai untuk seluruh fitur kamus (/grammar, /kotoba, /kanji) sesuai
    keputusan gating: Trial dapat, Traveler TIDAK dapat,
    Companion/Patron dapat, staff & admin selalu dapat.
    """
    if member.guild_permissions.administrator:
        return True
    gid = guild_id or member.guild.id
    member_role_ids = {role.id for role in member.roles}
    if any(rid in member_role_ids for rid in get_staff_role_ids(gid).values()):
        return True
    vip_ids = get_vip_role_ids(gid)
    allowed_ids = {tier: rid for tier, rid in vip_ids.items() if tier != "traveler"}
    return any(rid in member_role_ids for rid in allowed_ids.values())