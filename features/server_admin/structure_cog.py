"""
structure_cog.py — Penataan Ulang Struktur Kategori & Channel Kotabi
===========================================================================
VIP_CHANNEL_PERMISSIONS dan PUBLIC_CHANNELS_FOR_DRIFTER di-import dari
features/server_admin/support/permission_table.py — satu-satunya sumber
kebenaran, dipakai bersama oleh permissions_cog.py.

CATATAN (fix duplikasi): logic PENERAPAN permission (apply_vip_channel_permission,
apply_drifter_permission, get_role, get_channel_by_name, send_paginated) TIDAK
lagi didefinisikan di sini — di-import dari
features/server_admin/support/permission_engine.py, sama seperti yang dipakai
permissions_cog.py (/restore). Hanya SEKALI didefinisikan sekarang.

Yang TETAP eksklusif di file ini (bukan bagian dari permission_engine.py):
STRUCTURE_BLUEPRINT, _get_or_create_category(), _find_text_or_voice(), dan
_apply_structure() — logic kategori & posisi channel, yang justru menjadi
pembeda /setup_structure (struktur + permission) dari /restore (permission
saja).

PERUBAHAN (lihat DEVELOPMENT_GUIDE.md / catatan restrukturisasi channel):
  - quiz-public-1/2/3 (text) digabung jadi satu Forum Channel
    "quiz-public-forum" — otomatis dibersihkan oleh
    features/moderation/quiz_forum_cog.py.
  - today-i-learned dihapus dari JAPANESE AREA, digabung ke
    jlpt-study-group.
  - quiz-rank-up dipindah dari MEMBER AREA ke QUIZ HALL.
  - Study Room 1 & 2 (voice statis) diganti satu voice channel trigger
    "➕ Join to Create", dikelola oleh
    features/social/voice_jtc_cog.py.

Semua command dikelompokkan di bawah satu group /structure (lihat
PERMISSION_ENGINE_REFACTOR.md) supaya tidak ketuker dengan /permission
milik permissions_cog.py:
  /structure setup    — Membuat/menata kategori, memindahkan channel ke
                         kategori & posisi yang benar, lalu menerapkan ulang
                         semua permission VIP & Drifter (Khusus Admin).
  /structure preview  — Pratinjau rencana pemindahan tanpa mengubah apa pun.

Cara pakai:
  1. Taruh file ini di folder features/server_admin/ (sejajar dengan permissions_cog.py).
  2. Jalankan bot, lalu panggil %sync_guild atau %sync_global agar Discord
     mendaftarkan command barunya.
  3. Panggil /setup_structure di Discord.
  4. Command ini AMAN dijalankan berkali-kali (idempotent).
"""

import discord
import logging
from typing import Optional
from discord.ext import commands
from core.bot import KotabiBot
from shared.checks import has_authorized_access
from features.server_admin.support.permission_table import (
    VIP_CHANNEL_PERMISSIONS,
    PUBLIC_CHANNELS_FOR_DRIFTER,
)
from features.server_admin.support.permission_engine import (
    get_channel_by_name,
    apply_vip_channel_permission,
    apply_drifter_permission,
    send_paginated,
)

_log = logging.getLogger(__name__)


# ============================================================================
# HELPER KHUSUS STRUKTUR (bukan bagian dari permission_engine.py)
# ============================================================================

def _find_text_or_voice(guild: discord.Guild, name: str, kind: str) -> Optional[discord.abc.GuildChannel]:
    """Mencari channel case-insensitive berdasarkan nama DAN tipe (text/voice).
    kind="text" juga mencakup ForumChannel (mis. quiz-public-forum)."""
    name_lower = name.lower()
    for ch in guild.channels:
        if ch.name.lower() != name_lower:
            continue
        if kind == "voice" and isinstance(ch, discord.VoiceChannel):
            return ch
        if kind == "text" and isinstance(ch, (discord.TextChannel, discord.ForumChannel)):
            return ch
    return None


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
        "membership",
        "honor-board",
        "bot-commands",
    ], "text"),

    ("JAPANESE AREA", [
        "homework-help",
        "jlpt-study-group",
        # "today-i-learned" DIHAPUS — digabung ke jlpt-study-group.
    ], "text"),

    ("COMMUNITY", [
        "general",
        "jp-general",
        "off-topic",
    ], "text"),

    ("QUIZ HALL", [
        # quiz-public-1/2/3 digabung jadi satu Forum Channel.
        "quiz-public-forum",
        # Dipindah ke sini dari MEMBER AREA — lebih pas satu kategori
        # dengan channel kuis lainnya.
        "quiz-rank-up",
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
        # "quiz-rank-up" DIPINDAH ke QUIZ HALL (lihat di atas).
    ], "text"),

    ("RESOURCES SHARING", [
        "notes-and-resources",
    ], "text"),

    ("VOICE CHANNELS", [
        "Lounge",
        # Study Room 1 & 2 diganti sistem Join to Create dinamis —
        # channel yang dibuat otomatis TIDAK dimasukkan ke blueprint ini
        # (dikelola langsung oleh voice_jtc_cog.py).
        "➕ Join to Create",
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


class Structure(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    # Dikelompokkan di bawah /structure supaya tidak ketuker dengan
    # /permission milik permissions_cog.py — dulu nama cog "RestoreServer"
    # vs "RestructureServer" gampang salah baca.
    structure_group = discord.app_commands.Group(
        name="structure",
        description="Tata ulang kategori & channel server Kotabi sesuai blueprint.",
        default_permissions=discord.Permissions(administrator=True),
    )

    @structure_group.command(
        name="preview",
        description="Pratinjau penataan kategori & channel tanpa mengubah apa pun (Admin)."
    )
    @discord.app_commands.guild_only()
    async def structure_preview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send(
                "❌ Anda tidak memiliki wewenang untuk menjalankan perintah ini.", ephemeral=True
            )

        logs = await _apply_structure(interaction.guild, dry_run=True)
        logs.append("\n_Tidak ada perubahan yang diterapkan. Gunakan `/setup_structure` untuk eksekusi._")
        await send_paginated(interaction, logs, "🔍 Pratinjau Penataan Struktur")

    @structure_group.command(
        name="setup",
        description="Tata ulang kategori & channel sesuai blueprint, terapkan ulang permission (Admin)."
    )
    @discord.app_commands.guild_only()
    async def setup_structure(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send(
                "❌ Anda tidak memiliki wewenang untuk menjalankan perintah ini.", ephemeral=True
            )

        guild = interaction.guild

        logs = await _apply_structure(guild, dry_run=False)

        everyone = guild.default_role
        logs.append("\n\n## 🔐 Menerapkan Ulang Permission Channel VIP")
        for ch_name in VIP_CHANNEL_PERMISSIONS:
            channel = get_channel_by_name(guild, ch_name)
            if not channel:
                logs.append(f"❌ Channel `{ch_name}` tidak ditemukan di server!")
                continue
            try:
                result = await apply_vip_channel_permission(channel, guild, everyone, dry_run=False)
                logs.extend(result)
            except discord.Forbidden:
                logs.append(f"❌ `#{ch_name}` — Bot tidak punya izin Manage Channels!")
            except Exception as e:
                logs.append(f"❌ `#{ch_name}` — Error: {e}")

        logs.append("\n## 🌍 Menerapkan Ulang Permission Channel Publik (Drifter)")
        for ch_name in PUBLIC_CHANNELS_FOR_DRIFTER:
            channel = get_channel_by_name(guild, ch_name)
            if not channel:
                logs.append(f"⚠️ `{ch_name}` tidak ditemukan, dilewati")
                continue
            try:
                result = await apply_drifter_permission(channel, guild, dry_run=False)
                logs.append(result)
            except discord.Forbidden:
                logs.append(f"❌ `#{ch_name}` — Forbidden")
            except Exception as e:
                logs.append(f"❌ `#{ch_name}` — Error: {e}")

        logs.append("\n✅ **Penataan struktur server & permission selesai sepenuhnya!**")
        _log.info("Setup struktur server dijalankan oleh %s (%s)", interaction.user, interaction.user.id)
        await send_paginated(interaction, logs, "🔧 Hasil Penataan Struktur Server")


async def setup(bot: KotabiBot):
    await bot.add_cog(Structure(bot))