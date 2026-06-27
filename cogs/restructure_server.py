"""
restructure_server.py — Penataan Ulang Struktur Kategori & Channel Kotabi
===========================================================================
Cog BERDIRI SENDIRI (tidak import apa pun dari export_server.py) supaya tidak
rapuh terhadap perubahan nama fungsi/variabel internal di cog lain.
Semua helper otorisasi & permission didefinisikan ulang secara lokal di sini,
dengan logika yang SAMA seperti export_server.py — jadi hasil akhirnya tetap
konsisten satu sumber kebenaran (VIP_CHANNEL_PERMISSIONS & ROLE_NAME_TO_ID
nilainya disalin persis dari export_server.py).

Commands:
  /setup_structure   — Membuat/menata kategori, memindahkan channel ke
                        kategori & posisi yang benar, lalu menerapkan ulang
                        semua permission VIP & Drifter (Khusus Admin).
  /structure_preview — Pratinjau rencana pemindahan tanpa mengubah apa pun.

Cara pakai:
  1. Taruh file ini di folder cogs/ (sejajar dengan export_server.py).
  2. Jalankan bot, lalu panggil %sync_guild atau %sync_global agar Discord
     mendaftarkan command barunya.
  3. Panggil /setup_structure di Discord.
  4. Command ini AMAN dijalankan berkali-kali (idempotent).
"""

import os
import discord
import logging
from typing import Optional
from discord.ext import commands
from core.bot import KotabiBot

_log = logging.getLogger(__name__)


# ============================================================================
# OTORISASI — disalin dari export_server.py supaya tidak bergantung pada
# import lintas-cog yang rapuh.
# ============================================================================

AUTHORIZED_USER_IDS = [int(uid) for uid in os.getenv("AUTHORIZED_USERS", "").split(",") if uid.strip()]


def _is_authorized(user: discord.Member) -> bool:
    """Memeriksa apakah user memiliki hak akses (admin atau authorized ID)."""
    if user.id in AUTHORIZED_USER_IDS:
        return True
    if user.guild_permissions.administrator:
        return True
    return False


# ============================================================================
# TABEL PERMISSION VIP — disalin persis dari export_server.py
# (Sumber kebenarannya tetap export_server.py; kalau tabel di sana diubah,
# salin ulang juga ke sini supaya kedua cog tetap konsisten.)
# ============================================================================

VIP_CHANNEL_PERMISSIONS: dict[str, dict[str, bool]] = {
    "member-lounge":    {"trial": True,  "traveler": True,  "companion": True,  "scholar": True,  "patron": True},
    "immersion-log":    {"trial": True,  "traveler": True,  "companion": True,  "scholar": True,  "patron": True},
    "quiz-rank-up":     {"trial": True,  "traveler": True,  "companion": True,  "scholar": True,  "patron": True},
    "grammar-dic":      {"trial": True,  "traveler": False, "companion": True,  "scholar": True,  "patron": True},
    "kotoba-dic":       {"trial": True,  "traveler": False, "companion": True,  "scholar": True,  "patron": True},
    "kanji-dic":        {"trial": True,  "traveler": False, "companion": True,  "scholar": True,  "patron": True},
    "anime-sentences":  {"trial": True,  "traveler": False, "companion": True,  "scholar": True,  "patron": True},
    "deck-requests":    {"trial": True,  "traveler": False, "companion": True,  "scholar": True,  "patron": True},
    "immersion-race":   {"trial": True,  "traveler": False, "companion": True,  "scholar": True,  "patron": True},
}

ROLE_NAME_TO_ID: dict[str, int] = {
    "trial":           1518029306469548202,
    "traveler":        1517031166279159848,
    "companion":       1517676769954762804,
    "scholar":         1518084701431140524,
    "patron":          1517718386002628608,
    "royal_guard":     1517801101959631009,
    "prime_minister":  1517801149191819427,
    "drifter":         1518939950987612292,
}

PUBLIC_CHANNELS_FOR_DRIFTER = [
    "welcome-and-rules",
    "announcements",
    "channel-guide",
    "join-log",
    "role-assign",
    "rank-guide",
    "immersion-bot-info",
    "self-mute-info",
    "membership",
    "honor-board",
    "bot-commands",
    "homework-help",
    "jlpt-study-group",
    "today-i-learned",
    "general",
    "jp-general",
    "off-topic",
    "quiz-public-1",
    "quiz-public-2",
    "quiz-public-3",
    "notes-and-resources",
    "Lounge",
    "Study Room 1",
    "Study Room 2",
]


# ============================================================================
# HELPER UMUM
# ============================================================================

def _get_role(guild: discord.Guild, role_name: str) -> Optional[discord.Role]:
    role_id = ROLE_NAME_TO_ID.get(role_name)
    if not role_id:
        return None
    return guild.get_role(role_id)


def _get_channel_by_name(guild: discord.Guild, channel_name: str) -> Optional[discord.abc.GuildChannel]:
    """Mencari channel di guild berdasarkan nama (case-insensitive), tipe apa pun."""
    name_lower = channel_name.lower()
    for ch in guild.channels:
        if ch.name.lower() == name_lower:
            return ch
    return None


def _find_text_or_voice(guild: discord.Guild, name: str, kind: str) -> Optional[discord.abc.GuildChannel]:
    """Mencari channel case-insensitive berdasarkan nama DAN tipe (text/voice)."""
    name_lower = name.lower()
    for ch in guild.channels:
        if ch.name.lower() != name_lower:
            continue
        if kind == "voice" and isinstance(ch, discord.VoiceChannel):
            return ch
        if kind == "text" and isinstance(ch, (discord.TextChannel, discord.ForumChannel)):
            return ch
    return None


async def _apply_vip_channel_permission(
    channel: discord.abc.GuildChannel,
    guild: discord.Guild,
    everyone: discord.Role,
    dry_run: bool = False,
) -> list[str]:
    channel_name = channel.name.lower()
    vip_rules = VIP_CHANNEL_PERMISSIONS.get(channel_name)

    if vip_rules is None:
        return [f"⏭️  `#{channel.name}` — Bukan channel VIP, dilewati"]

    logs = [f"\n**#{channel.name}**"]

    if not dry_run:
        await channel.set_permissions(everyone, view_channel=False, send_messages=False)

    for role_name, allowed in vip_rules.items():
        role = _get_role(guild, role_name)
        if not role:
            logs.append(f"  ❌ `{role_name}` — Role tidak ditemukan!")
            continue

        status = "✅ Allow" if allowed else "❌ Deny"
        logs.append(f"  {status} `{role.name}`")

        if not dry_run:
            if allowed:
                await channel.set_permissions(role, view_channel=True, send_messages=True)
            else:
                await channel.set_permissions(role, view_channel=False, send_messages=False)

    for staff_key in ("royal_guard", "prime_minister"):
        staff_role = _get_role(guild, staff_key)
        if staff_role:
            logs.append(f"  ✅ Allow `{staff_role.name}` (Staff)")
            if not dry_run:
                await channel.set_permissions(staff_role, view_channel=True, send_messages=True)

    return logs


async def _apply_drifter_permission(
    channel: discord.abc.GuildChannel,
    guild: discord.Guild,
    dry_run: bool = False,
) -> str:
    drifter = _get_role(guild, "drifter")
    if not drifter:
        return "  ❌ Role Drifter tidak ditemukan!"

    if not dry_run:
        await channel.set_permissions(drifter, view_channel=True)

    return f"  ✅ Drifter diberi akses ke `#{channel.name}`"


async def _send_paginated(interaction: discord.Interaction, lines: list[str], title: str):
    """Mengirimkan hasil log yang panjang secara paginated (maks 1900 char per pesan)."""
    chunk = ""
    first = True
    for line in lines:
        if len(chunk) + len(line) + 1 > 1900:
            embed = discord.Embed(
                title=title if first else f"{title} (lanjutan)",
                description=chunk,
                color=discord.Color.blurple()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            first = False
            chunk = line + "\n"
        else:
            chunk += line + "\n"

    if chunk:
        embed = discord.Embed(
            title=title if first else f"{title} (lanjutan)",
            description=chunk,
            color=discord.Color.blurple()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


# ============================================================================
# BLUEPRINT STRUKTUR SERVER
# ============================================================================

STRUCTURE_BLUEPRINT: list[tuple[str, list[str], str]] = [
    ("SERVER INFO", [
        "welcome-and-rules",
        "announcements",
        "channel-guide",
        "join-log",
        "role-assign",
    ], "text"),

    ("KOTABI SYSTEM", [
        "rank-guide",
        "immersion-bot-info",
        "self-mute-info",
        "membership",
        "honor-board",
        "bot-commands",
    ], "text"),

    ("JAPANESE AREA", [
        "homework-help",
        "jlpt-study-group",
        "today-i-learned",
    ], "text"),

    ("COMMUNITY", [
        "general",
        "jp-general",
        "off-topic",
    ], "text"),

    ("QUIZ HALL", [
        "quiz-public-1",
        "quiz-public-2",
        "quiz-public-3",
    ], "text"),

    ("MEMBER LIBRARY", [
        "grammar-dic",
        "kotoba-dic",
        "kanji-dic",
        "anime-sentences",
    ], "text"),

    ("MEMBER AREA", [
        "member-lounge",
        "immersion-log",
        "deck-requests",
        "immersion-race",
        "quiz-rank-up",
    ], "text"),

    ("RESOURCES SHARING", [
        "notes-and-resources",
    ], "text"),

    ("VOICE CHANNELS", [
        "Lounge",
        "Study Room 1",
        "Study Room 2",
    ], "voice"),

    ("STAFF", [
    "staff-chat",
    "order-review",
    ], "text"),
]


async def _get_or_create_category(
    guild: discord.Guild,
    name: str,
    dry_run: bool,
    logs: list[str],
) -> Optional[discord.CategoryChannel]:
    existing = discord.utils.find(
        lambda c: isinstance(c, discord.CategoryChannel) and c.name.lower() == name.lower(),
        guild.channels,
    )
    if existing:
        return existing

    if dry_run:
        logs.append(f"  🆕 (DRY RUN) Kategori `{name}` akan dibuat baru")
        return None

    try:
        new_cat = await guild.create_category(name, reason="Penataan ulang struktur server otomatis")
        logs.append(f"  🆕 Kategori `{name}` berhasil dibuat")
        return new_cat
    except discord.Forbidden:
        logs.append(f"  ❌ Gagal membuat kategori `{name}` — bot tidak punya izin Manage Channels")
        return None


async def _apply_structure(
    guild: discord.Guild,
    dry_run: bool,
) -> list[str]:
    logs: list[str] = [f"{'🔍 PRATINJAU' if dry_run else '🔧 EKSEKUSI'} Penataan Struktur Server\n"]

    category_position = 0

    for category_name, channel_names, kind in STRUCTURE_BLUEPRINT:
        logs.append(f"\n## 📁 {category_name}")

        category = await _get_or_create_category(guild, category_name, dry_run, logs)

        if category and not dry_run:
            if category.position != category_position:
                try:
                    await category.edit(position=category_position)
                except discord.Forbidden:
                    logs.append(f"  ⚠️ Tidak bisa mengubah posisi kategori `{category_name}` (izin kurang)")
                except discord.HTTPException:
                    pass

        for position_in_category, channel_name in enumerate(channel_names):
            channel = _find_text_or_voice(guild, channel_name, kind)

            if not channel:
                logs.append(f"  ❌ Channel `{channel_name}` ({kind}) tidak ditemukan di server — dilewati")
                continue

            current_category_name = channel.category.name if channel.category else "(tanpa kategori)"
            needs_move = (
                channel.category is None
                or channel.category.name.lower() != category_name.lower()
            )

            if dry_run:
                if needs_move:
                    logs.append(
                        f"  ➡️ `#{channel_name}` akan dipindah dari `{current_category_name}` → `{category_name}` (posisi {position_in_category})"
                    )
                else:
                    logs.append(f"  ✅ `#{channel_name}` sudah benar di `{category_name}`")
                continue

            try:
                if needs_move and category:
                    await channel.edit(category=category, position=position_in_category, sync_permissions=False)
                    logs.append(f"  ➡️ `#{channel_name}` dipindahkan ke `{category_name}` (posisi {position_in_category})")
                elif not needs_move:
                    await channel.edit(position=position_in_category)
                    logs.append(f"  ✅ `#{channel_name}` — posisi disesuaikan ({position_in_category})")
            except discord.Forbidden:
                logs.append(f"  ❌ `#{channel_name}` — bot tidak punya izin Manage Channels")
            except discord.HTTPException as e:
                logs.append(f"  ❌ `#{channel_name}` — gagal dipindah: {e}")

        category_position += 1

    return logs


class RestructureServer(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    @discord.app_commands.command(
        name="structure_preview",
        description="Pratinjau penataan kategori & channel tanpa mengubah apa pun (Admin)."
    )
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def structure_preview(self, interaction: discord.Interaction):    
        await interaction.response.defer(ephemeral=True)

        if not _is_authorized(interaction.user):
            return await interaction.followup.send(
                "❌ Anda tidak memiliki wewenang untuk menjalankan perintah ini.", ephemeral=True
            )

        logs = await _apply_structure(interaction.guild, dry_run=True)
        logs.append("\n_Tidak ada perubahan yang diterapkan. Gunakan `/setup_structure` untuk eksekusi._")
        await _send_paginated(interaction, logs, "🔍 Pratinjau Penataan Struktur")

    @discord.app_commands.command(
    name="setup_structure",
    description="Tata ulang kategori & channel sesuai blueprint, terapkan ulang permission (Admin)."
    )
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def setup_structure(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not _is_authorized(interaction.user):
            return await interaction.followup.send(
                "❌ Anda tidak memiliki wewenang untuk menjalankan perintah ini.", ephemeral=True
            )

        guild = interaction.guild

        logs = await _apply_structure(guild, dry_run=False)

        everyone = guild.default_role
        logs.append("\n\n## 🔐 Menerapkan Ulang Permission Channel VIP")
        for ch_name in VIP_CHANNEL_PERMISSIONS:
            channel = _get_channel_by_name(guild, ch_name)
            if not channel:
                logs.append(f"❌ Channel `{ch_name}` tidak ditemukan di server!")
                continue
            try:
                result = await _apply_vip_channel_permission(channel, guild, everyone, dry_run=False)
                logs.extend(result)
            except discord.Forbidden:
                logs.append(f"❌ `#{ch_name}` — Bot tidak punya izin Manage Channels!")
            except Exception as e:
                logs.append(f"❌ `#{ch_name}` — Error: {e}")

        logs.append("\n## 🌍 Menerapkan Ulang Permission Channel Publik (Drifter)")
        for ch_name in PUBLIC_CHANNELS_FOR_DRIFTER:
            channel = _get_channel_by_name(guild, ch_name)
            if not channel:
                logs.append(f"⚠️ `{ch_name}` tidak ditemukan, dilewati")
                continue
            try:
                result = await _apply_drifter_permission(channel, guild, dry_run=False)
                logs.append(result)
            except discord.Forbidden:
                logs.append(f"❌ `#{ch_name}` — Forbidden")
            except Exception as e:
                logs.append(f"❌ `#{ch_name}` — Error: {e}")

        logs.append("\n✅ **Penataan struktur server & permission selesai sepenuhnya!**")
        _log.info("Setup struktur server dijalankan oleh %s (%s)", interaction.user, interaction.user.id)
        await _send_paginated(interaction, logs, "🔧 Hasil Penataan Struktur Server")


async def setup(bot: KotabiBot):
    await bot.add_cog(RestructureServer(bot))