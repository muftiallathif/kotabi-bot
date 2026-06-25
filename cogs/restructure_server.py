"""
restructure_server.py — Penataan Ulang Struktur Kategori & Channel Kotabi
===========================================================================
Cog tambahan untuk melengkapi export_server.py (restore_server.py).
Tugasnya KHUSUS menata ULANG kategori dan urutan channel sesuai blueprint
yang ditentukan admin, lalu memanggil ulang sistem permission yang SUDAH
ADA di restore_server.py (VIP_CHANNEL_PERMISSIONS / PUBLIC_CHANNELS_FOR_DRIFTER)
supaya tidak ada logika permission yang terduplikasi atau berbeda.

Commands:
  /setup_structure   — Membuat/menata kategori, memindahkan channel ke
                        kategori & posisi yang benar, lalu menjalankan ulang
                        /restore secara otomatis di akhir (Khusus Admin).
  /structure_preview — Pratinjau rencana pemindahan tanpa mengubah apa pun.

Cara pakai:
  1. Taruh file ini di folder cogs/ (sejajar dengan export_server.py).
  2. Jalankan bot, lalu panggil /setup_structure di Discord.
  3. Command ini AMAN dijalankan berkali-kali (idempotent) — channel yang
     sudah berada di kategori & posisi yang benar tidak akan disentuh lagi.
"""

import discord
import logging
from typing import Optional
from discord.ext import commands
from core.bot import KotabiBot

# Re-pakai helper otorisasi & tabel permission yang SUDAH ada agar konsisten
# satu sumber kebenaran — tidak dobel logic.
from cogs.export_server import (
    _is_authorized,
    _get_channel_by_name,
    _apply_vip_channel_permission,
    _apply_drifter_permission,
    VIP_CHANNEL_PERMISSIONS,
    PUBLIC_CHANNELS_FOR_DRIFTER,
    _send_paginated,
)

_log = logging.getLogger(__name__)


# ============================================================================
# BLUEPRINT STRUKTUR SERVER
# Format: (nama_kategori, [daftar_nama_channel_text_dalam_urutan], tipe)
# tipe: "text" untuk TextChannel/ForumChannel biasa, "voice" untuk VoiceChannel
# Urutan list di sini = urutan posisi channel di dalam kategori tersebut.
# Urutan kategori di sini = urutan posisi kategori di server (dari atas).
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

    # STAFF tidak punya kategori sendiri di blueprint asli kamu — staff-chat
    # berada di top-level (tanpa kategori) di server live kamu saat ini.
    # Dibuatkan kategori "STAFF" agar konsisten dan mudah dikelola permission-nya.
    ("STAFF", [
        "staff-chat",
    ], "text"),
]


def _find_channel_by_name(guild: discord.Guild, name: str, kind: str) -> Optional[discord.abc.GuildChannel]:
    """Mencari channel case-insensitive berdasarkan nama dan tipe (text/voice)."""
    name_lower = name.lower()
    for ch in guild.channels:
        if ch.name.lower() != name_lower:
            continue
        if kind == "voice" and isinstance(ch, discord.VoiceChannel):
            return ch
        if kind == "text" and isinstance(ch, (discord.TextChannel, discord.ForumChannel)):
            return ch
    return None


async def _get_or_create_category(
    guild: discord.Guild,
    name: str,
    dry_run: bool,
    logs: list[str],
) -> Optional[discord.CategoryChannel]:
    """Mencari kategori berdasarkan nama, membuatnya jika belum ada."""
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
    """
    Inti logika: untuk setiap kategori di blueprint (dalam urutan),
    pastikan kategori ada lalu pindahkan setiap channel ke kategori itu
    dengan urutan posisi yang benar.
    """
    logs: list[str] = [f"{'🔍 PRATINJAU' if dry_run else '🔧 EKSEKUSI'} Penataan Struktur Server\n"]

    category_position = 0

    for category_name, channel_names, kind in STRUCTURE_BLUEPRINT:
        logs.append(f"\n## 📁 {category_name}")

        category = await _get_or_create_category(guild, category_name, dry_run, logs)

        # Jika dry run dan kategori belum ada, kita tetap lanjut preview channel-nya
        if category and not dry_run:
            if category.position != category_position:
                try:
                    await category.edit(position=category_position)
                except discord.Forbidden:
                    logs.append(f"  ⚠️ Tidak bisa mengubah posisi kategori `{category_name}` (izin kurang)")
                except discord.HTTPException:
                    pass  # posisi akan settle otomatis setelah beberapa edit channel

        for position_in_category, channel_name in enumerate(channel_names):
            channel = _find_channel_by_name(guild, channel_name, kind)

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
                    # Tetap pastikan urutan posisi benar walau kategori sudah pas
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

    # ------------------------------------------------------------------ #
    #  /structure_preview — Lihat rencana penataan tanpa eksekusi         #
    # ------------------------------------------------------------------ #

    @discord.app_commands.command(
        name="structure_preview",
        description="Lihat pratinjau penataan ulang kategori & channel tanpa mengubah apa pun (Khusus Admin)."
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

    # ------------------------------------------------------------------ #
    #  /setup_structure — Eksekusi penataan + jalankan ulang permission   #
    # ------------------------------------------------------------------ #

    @discord.app_commands.command(
        name="setup_structure",
        description="Tata ulang kategori & posisi channel sesuai blueprint, lalu terapkan ulang semua permission (Khusus Admin)."
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

        # TAHAP 1 — Tata ulang kategori & posisi channel
        logs = await _apply_structure(guild, dry_run=False)

        # TAHAP 2 — Terapkan ulang permission VIP & Drifter
        # (logika persis sama dengan /restore di export_server.py — dipanggil
        # langsung supaya tidak ada drift antara dua command)
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
