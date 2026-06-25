"""
full_backup.py — Backup Lengkap Struktur Server Kotabi
========================================================
Membackup seluruh struktur server (bukan isi chat) ke dalam satu file JSON.

LIMITASI (sesuai kebijakan & arsitektur Discord API — tidak bisa dilewati):
- TIDAK membackup isi pesan/chat di channel
- TIDAK membackup attachment/file yang dikirim di chat
- TIDAK membackup riwayat boost
- TIDAK membackup audit log lama (Discord hanya menyimpan ~90 hari)
- URL/token webhook TIDAK disimpan (hanya nama & channel) — demi keamanan,
  karena URL webhook itu sendiri adalah kredensial yang bisa dipakai siapa saja
  untuk mengirim pesan atas nama webhook tersebut.

Command:
  /backup_discord_server   — Backup seluruh STRUKTUR server Discord ke JSON (Khusus Admin)

PERBEDAAN dengan command backup lain yang sudah ada di project ini:
  - /post_db             → backup DATABASE SQLite bot (data poin, log, dll)
  - /backup_permissions  → backup PERMISSION OVERWRITE channel saja
  - /backup_discord_server (cog ini) → backup STRUKTUR Discord-nya sendiri:
    channel, kategori, role, emoji, sticker, scheduled event, webhook
    metadata, thread aktif, dan setting dasar server.

Cara pakai:
  Taruh file ini di folder cogs/, lalu bot akan otomatis memuatnya
  (mengikuti mekanisme load_cogs() di core/bot.py).
"""

import discord
import json
import io
import os
import logging
from datetime import datetime, timezone
from discord.ext import commands
from core.bot import KotabiBot

_log = logging.getLogger(__name__)

AUTHORIZED_USER_IDS = [int(uid) for uid in os.getenv("AUTHORIZED_USERS", "").split(",") if uid.strip()]


# ============================================================================
# FUNGSI PEMBANTU
# ============================================================================

def _is_authorized(user: discord.Member) -> bool:
    """Memeriksa apakah user memiliki hak akses (admin atau authorized ID)."""
    if user.id in AUTHORIZED_USER_IDS:
        return True
    if user.guild_permissions.administrator:
        return True
    return False


def _serialize_overwrites(channel: discord.abc.GuildChannel) -> list[dict]:
    """Menyimpan seluruh permission overwrite (role & member) milik satu channel."""
    overwrites = []
    for target, overwrite in channel.overwrites.items():
        allow, deny = overwrite.pair()
        overwrites.append({
            "id": target.id,
            "name": getattr(target, "name", str(target)),
            "type": "role" if isinstance(target, discord.Role) else "member",
            "allow": allow.value,
            "deny": deny.value,
        })
    return overwrites


def _serialize_channel(channel: discord.abc.GuildChannel) -> dict:
    """Menyimpan metadata channel sesuai tipenya (text/voice/stage/forum/category)."""
    data = {
        "id": channel.id,
        "name": channel.name,
        "type": str(channel.type),
        "position": getattr(channel, "position", None),
        "category_id": getattr(channel, "category_id", None),
        "category_name": channel.category.name if getattr(channel, "category", None) else None,
        "overwrites": _serialize_overwrites(channel),
    }

    if isinstance(channel, discord.TextChannel):
        data.update({
            "topic": channel.topic,
            "nsfw": channel.nsfw,
            "slowmode_delay": channel.slowmode_delay,
            "default_auto_archive_duration": channel.default_auto_archive_duration,
        })
    elif isinstance(channel, discord.VoiceChannel):
        data.update({
            "bitrate": channel.bitrate,
            "user_limit": channel.user_limit,
            "nsfw": channel.nsfw,
            "rtc_region": str(channel.rtc_region) if channel.rtc_region else None,
        })
    elif isinstance(channel, discord.StageChannel):
        data.update({
            "bitrate": channel.bitrate,
            "user_limit": channel.user_limit,
            "topic": channel.topic,
        })
    elif isinstance(channel, discord.ForumChannel):
        data.update({
            "topic": channel.topic,
            "nsfw": channel.nsfw,
            "slowmode_delay": channel.slowmode_delay,
            "default_auto_archive_duration": channel.default_auto_archive_duration,
            "available_tags": [
                {
                    "id": tag.id,
                    "name": tag.name,
                    "emoji": str(tag.emoji) if tag.emoji else None,
                    "moderated": tag.moderated,
                }
                for tag in channel.available_tags
            ],
        })
    elif isinstance(channel, discord.CategoryChannel):
        data["nsfw"] = channel.nsfw

    return data


def _serialize_role(role: discord.Role) -> dict:
    """Menyimpan metadata satu role (warna, permission, posisi hierarki, dll)."""
    return {
        "id": role.id,
        "name": role.name,
        "color": str(role.color),
        "hoist": role.hoist,
        "mentionable": role.mentionable,
        "managed": role.managed,
        "position": role.position,
        "permissions": role.permissions.value,
        "icon_url": str(role.icon.url) if getattr(role, "icon", None) else None,
        "unicode_emoji": getattr(role, "unicode_emoji", None),
    }


# ============================================================================
# COG UTAMA
# ============================================================================

class FullBackup(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    @discord.app_commands.command(
        name="backup_discord_server",
        description="Backup STRUKTUR LENGKAP server Discord (channel, role, emoji, dst) ke JSON — bukan database, bukan permission saja. (Khusus Admin)."
    )
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def backup_discord_server(self, interaction: discord.Interaction):
        """Slash command untuk memicu pembuatan backup struktur server secara lengkap."""
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not _is_authorized(interaction.user):
            return await interaction.followup.send(
                "❌ Anda tidak memiliki wewenang untuk menjalankan perintah ini.", ephemeral=True
            )

        guild = interaction.guild

        try:
            backup = {
                "backup_format_version": "1.0",
                "guild_id": guild.id,
                "guild_name": guild.name,
                "backup_time": datetime.now(timezone.utc).isoformat(),
                "backed_up_by": str(interaction.user),
                "note": (
                    "Backup ini HANYA mencakup struktur server. Isi chat, attachment, "
                    "dan riwayat boost TIDAK disertakan (limitasi Discord API)."
                ),
            }

            # 1. Pengaturan dasar server
            backup["guild_settings"] = {
                "name": guild.name,
                "description": guild.description,
                "icon_url": str(guild.icon.url) if guild.icon else None,
                "banner_url": str(guild.banner.url) if guild.banner else None,
                "splash_url": str(guild.splash.url) if guild.splash else None,
                "verification_level": str(guild.verification_level),
                "explicit_content_filter": str(guild.explicit_content_filter),
                "default_notifications": str(guild.default_notifications),
                "preferred_locale": str(guild.preferred_locale),
                "premium_tier": guild.premium_tier,
                "afk_timeout": guild.afk_timeout,
                "afk_channel_id": guild.afk_channel.id if guild.afk_channel else None,
                "system_channel_id": guild.system_channel.id if guild.system_channel else None,
                "rules_channel_id": guild.rules_channel.id if guild.rules_channel else None,
                "public_updates_channel_id": (
                    guild.public_updates_channel.id if guild.public_updates_channel else None
                ),
            }

            # 2. Roles (urut dari tertinggi ke terendah)
            backup["roles"] = [
                _serialize_role(role)
                for role in sorted(guild.roles, key=lambda r: r.position, reverse=True)
            ]

            # 3. Channel & Kategori (urut posisi)
            backup["channels"] = [
                _serialize_channel(ch) for ch in sorted(guild.channels, key=lambda c: c.position)
            ]

            # 4. Emoji kustom
            backup["emojis"] = [
                {
                    "id": emoji.id,
                    "name": emoji.name,
                    "url": str(emoji.url),
                    "animated": emoji.animated,
                    "managed": emoji.managed,
                    "role_ids": [r.id for r in emoji.roles],
                }
                for emoji in guild.emojis
            ]

            # 5. Sticker kustom
            try:
                backup["stickers"] = [
                    {
                        "id": sticker.id,
                        "name": sticker.name,
                        "description": sticker.description,
                        "emoji": getattr(sticker, "emoji", None),
                        "url": str(sticker.url),
                    }
                    for sticker in guild.stickers
                ]
            except Exception as e:
                _log.warning("Gagal membackup sticker: %s", e)
                backup["stickers"] = []

            # 6. Scheduled Events
            try:
                events = await guild.fetch_scheduled_events()
                backup["scheduled_events"] = [
                    {
                        "id": event.id,
                        "name": event.name,
                        "description": event.description,
                        "start_time": event.start_time.isoformat() if event.start_time else None,
                        "end_time": event.end_time.isoformat() if event.end_time else None,
                        "location": event.location,
                        "status": str(event.status),
                        "channel_id": event.channel_id,
                    }
                    for event in events
                ]
            except Exception as e:
                _log.warning("Gagal membackup scheduled events: %s", e)
                backup["scheduled_events"] = []

            # 7. Webhook — HANYA metadata, URL/token TIDAK disimpan demi keamanan
            webhook_data = []
            for channel in guild.text_channels:
                try:
                    hooks = await channel.webhooks()
                    for hook in hooks:
                        webhook_data.append({
                            "id": hook.id,
                            "name": hook.name,
                            "channel_id": hook.channel_id,
                            "avatar_url": str(hook.avatar.url) if hook.avatar else None,
                        })
                except discord.Forbidden:
                    continue
                except Exception as e:
                    _log.warning("Gagal mengambil webhook di channel %s: %s", channel.id, e)
            backup["webhooks"] = webhook_data

            # 8. Thread aktif (thread yang sudah diarchive tidak ikut tercakup di sini)
            backup["active_threads"] = [
                {
                    "id": thread.id,
                    "name": thread.name,
                    "parent_id": thread.parent_id,
                    "archived": thread.archived,
                    "locked": thread.locked,
                    "owner_id": thread.owner_id,
                }
                for thread in guild.threads
            ]

        except Exception as e:
            _log.exception("Gagal membuat backup penuh server")
            return await interaction.followup.send(
                f"❌ Terjadi kesalahan saat membuat backup: `{e}`", ephemeral=True
            )

        # Kirim sebagai file JSON
        json_bytes = json.dumps(backup, indent=2, ensure_ascii=False).encode("utf-8")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"discord_server_structure_{guild.id}_{timestamp}.json"

        file_size_mb = len(json_bytes) / (1024 * 1024)
        if file_size_mb > 24:
            return await interaction.followup.send(
                f"❌ Ukuran backup (`{file_size_mb:.1f} MB`) terlalu besar untuk dikirim langsung via Discord.\n"
                f"Pertimbangkan untuk menjalankan backup ini dari skrip terpisah dan menyimpannya ke disk VPS.",
                ephemeral=True
            )

        file = discord.File(io.BytesIO(json_bytes), filename=filename)
        await interaction.followup.send(
            f"✅ **Backup STRUKTUR server Discord berhasil dibuat!**\n"
            f"_(Ini bukan backup database bot — gunakan `/post_db` untuk itu. Ini juga bukan sekadar permission overwrite — gunakan `/backup_permissions` untuk itu.)_\n\n"
            f"📦 Total channel: **{len(backup['channels'])}**\n"
            f"🎭 Total role: **{len(backup['roles'])}**\n"
            f"😀 Total emoji: **{len(backup['emojis'])}**\n"
            f"🏷️ Total sticker: **{len(backup['stickers'])}**\n"
            f"📅 Total scheduled event: **{len(backup['scheduled_events'])}**\n"
            f"🪝 Total webhook: **{len(backup['webhooks'])}**\n"
            f"🧵 Total thread aktif: **{len(backup['active_threads'])}**\n\n"
            f"⚠️ **Catatan:** Backup ini tidak mencakup isi chat, attachment, atau riwayat boost (limitasi Discord API). "
            f"Simpan berkas ini di tempat aman — meski tidak ada URL webhook, data ini tetap mengungkap struktur server Anda.",
            file=file,
            ephemeral=True
        )
        _log.info("Backup struktur server Discord dijalankan oleh %s (%s)", interaction.user, interaction.user.id)


async def setup(bot: KotabiBot):
    await bot.add_cog(FullBackup(bot))