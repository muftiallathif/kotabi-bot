"""
permissions_cog.py — Sistem Restore & Manajemen Permission Server Kotabi (v2)
==================================================================================
GENERASI KEDUA — bekerja dengan skema CHANNEL_PERMISSIONS baru di
permission_table.py (lihat PERMISSION_MATRIX.md). Restore sekarang
menangani channel VIP MAUPUN publik dalam satu proses, karena role
"everyone" sudah didefinisikan langsung per channel di tabel — tidak ada
lagi tahap terpisah untuk "channel publik Drifter".

  /permission restore          — Restore semua channel di CHANNEL_PERMISSIONS
  /permission restore_channel  — Restore 1 channel saja
  /permission preview          — Preview perubahan tanpa apply
  /permission backup           — Simpan kondisi permission sekarang ke file JSON
  /permission sync_roles       — Validasi semua role ID & channel di konfigurasi restore
"""

import discord
import json
import io
import logging
from datetime import datetime, timezone
from typing import Optional, Union
from discord.ext import commands
from core.bot import KotabiBot
from shared.config import get_role_id
from shared.checks import has_authorized_access
from features.server_admin.support.permission_table import (
    CHANNEL_PERMISSIONS,
    ROLE_KEYS_USED,
)
from features.server_admin.support.permission_engine import (
    get_channel_by_name,
    apply_channel_permission,
    send_paginated,
)

_log = logging.getLogger(__name__)

# Channel bisa berupa teks, forum (quiz-public, questions-forum), atau
# voice (staff voice) — union type ini dipakai supaya picker channel di
# Discord slash command menampilkan ketiga jenis channel tersebut.
RestorableChannel = Union[discord.TextChannel, discord.ForumChannel, discord.VoiceChannel]


class Permissions(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    permission_group = discord.app_commands.Group(
        name="permission",
        description="Kelola permission channel server Kotabi.",
        default_permissions=discord.Permissions(administrator=True),
    )

    # ------------------------------------------------------------------ #
    #  /permission restore — Restore semua channel di CHANNEL_PERMISSIONS #
    # ------------------------------------------------------------------ #

    @permission_group.command(
        name="restore",
        description="Restore semua permission channel sesuai tabel yang sudah ditentukan (Khusus Admin)."
    )
    @discord.app_commands.guild_only()
    async def restore(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send("❌ Anda tidak memiliki wewenang untuk menjalankan perintah ini.", ephemeral=True)

        guild = interaction.guild
        logs = ["🔄 **Restore Permission Server Dimulai...**\n"]

        for channel_name in CHANNEL_PERMISSIONS:
            channel = get_channel_by_name(guild, channel_name)
            if not channel:
                logs.append(f"❌ Channel `{channel_name}` tidak ditemukan di server!")
                continue
            try:
                result = await apply_channel_permission(channel, guild, dry_run=False)
                logs.extend(result)
            except discord.Forbidden:
                logs.append(f"❌ `#{channel_name}` — Bot tidak punya izin Manage Channels/Manage Roles!")
            except Exception as e:
                logs.append(f"❌ `#{channel_name}` — Error: {e}")

        logs.append("\n✅ **Restore selesai!**")
        _log.info("Restore permission dijalankan oleh %s (%s)", interaction.user, interaction.user.id)
        await send_paginated(interaction, logs, "📋 Hasil Restore Permission")

    # ------------------------------------------------------------------ #
    #  /permission restore_channel — Restore 1 channel saja               #
    # ------------------------------------------------------------------ #

    @permission_group.command(
        name="restore_channel",
        description="Restore permission satu channel tertentu saja (Khusus Admin)."
    )
    @discord.app_commands.describe(channel="Pilih channel yang ingin di-restore permissionnya.")
    @discord.app_commands.guild_only()
    async def restore_channel(self, interaction: discord.Interaction, channel: RestorableChannel):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send("❌ Tidak memiliki wewenang.", ephemeral=True)

        guild = interaction.guild
        ch_name = channel.name.lower()

        if ch_name not in CHANNEL_PERMISSIONS:
            return await interaction.followup.send(
                f"⚠️ `#{channel.name}` tidak terdaftar di `CHANNEL_PERMISSIONS`.\n"
                f"Channel ini mungkin sengaja tidak diberi overwrite (warisan permission kategori) — "
                f"lihat PERMISSION_MATRIX.md.",
                ephemeral=True
            )

        try:
            logs = await apply_channel_permission(channel, guild, dry_run=False)
            embed = discord.Embed(
                title=f"✅ Restore #{channel.name}",
                description="\n".join(logs),
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"❌ Bot tidak punya izin untuk edit permission `#{channel.name}`.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

        _log.info("Restore channel #%s dijalankan oleh %s", channel.name, interaction.user)

    # ------------------------------------------------------------------ #
    #  /permission preview — Lihat rencana perubahan tanpa apply          #
    # ------------------------------------------------------------------ #

    @permission_group.command(
        name="preview",
        description="Lihat preview permission yang akan diterapkan tanpa mengubah apa pun (Khusus Admin)."
    )
    @discord.app_commands.describe(channel="Opsional: preview untuk channel tertentu saja.")
    @discord.app_commands.guild_only()
    async def preview(self, interaction: discord.Interaction, channel: Optional[RestorableChannel] = None):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send("❌ Tidak memiliki wewenang.", ephemeral=True)

        guild = interaction.guild
        logs = ["🔍 **Preview Permission (DRY RUN — tidak ada perubahan)**\n"]

        if channel:
            ch_name = channel.name.lower()
            if ch_name not in CHANNEL_PERMISSIONS:
                logs.append(f"⚠️ `#{channel.name}` tidak terdaftar di sistem restore.")
            else:
                result = await apply_channel_permission(channel, guild, dry_run=True)
                logs.extend(result)
        else:
            for channel_name in CHANNEL_PERMISSIONS:
                ch = get_channel_by_name(guild, channel_name)
                if not ch:
                    logs.append(f"❌ `{channel_name}` — tidak ditemukan di server")
                    continue
                result = await apply_channel_permission(ch, guild, dry_run=True)
                logs.extend(result)
            logs.append("\n_Tidak ada perubahan yang diterapkan. Gunakan `/permission restore` untuk apply._")

        await send_paginated(interaction, logs, "🔍 Preview Permission")

    # ------------------------------------------------------------------ #
    #  /permission backup — Export kondisi permission sekarang ke JSON    #
    # ------------------------------------------------------------------ #

    @permission_group.command(
        name="backup",
        description="Export kondisi permission semua channel saat ini ke file JSON (Khusus Admin)."
    )
    @discord.app_commands.guild_only()
    async def backup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send("❌ Tidak memiliki wewenang.", ephemeral=True)

        guild = interaction.guild
        backup = {
            "guild_name": guild.name,
            "guild_id": guild.id,
            "backup_time": datetime.now(timezone.utc).isoformat(),
            "backed_up_by": str(interaction.user),
            "channels": []
        }

        # Snapshot semua channel (teks, voice, forum) beserta permission override-nya
        for ch in sorted(guild.channels, key=lambda c: c.position):
            ch_data = {
                "id": ch.id,
                "name": ch.name,
                "type": str(ch.type),
                "category": ch.category.name if ch.category else None,
                "permissions": []
            }
            for target, overwrite in ch.overwrites.items():
                allow, deny = overwrite.pair()
                ch_data["permissions"].append({
                    "id": target.id,
                    "name": target.name if hasattr(target, "name") else str(target),
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value,
                })
            backup["channels"].append(ch_data)

        json_bytes = json.dumps(backup, indent=2, ensure_ascii=False).encode("utf-8")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"permission_backup_{guild.id}_{timestamp}.json"

        file = discord.File(io.BytesIO(json_bytes), filename=filename)
        await interaction.followup.send(
            f"✅ **Backup permission berhasil!**\n"
            f"📦 Total channel di-backup: **{len(backup['channels'])}**\n"
            f"🕐 Waktu: `{backup['backup_time']}`\n\n"
            f"Simpan file ini sebelum menjalankan `/permission restore`.",
            file=file,
            ephemeral=True
        )
        _log.info("Backup permission dijalankan oleh %s (%s)", interaction.user, interaction.user.id)

    # ------------------------------------------------------------------ #
    #  /permission sync_roles — Validasi semua role ID & channel          #
    # ------------------------------------------------------------------ #

    @permission_group.command(
        name="sync_roles",
        description="Validasi apakah semua role ID & channel di konfigurasi restore masih valid (Khusus Admin)."
    )
    @discord.app_commands.guild_only()
    async def sync_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send("❌ Tidak memiliki wewenang.", ephemeral=True)

        guild = interaction.guild
        lines = ["🔎 **Validasi Role ID**\n"]
        all_ok = True

        for role_key in ROLE_KEYS_USED:
            role_id = get_role_id(guild.id, role_key)
            role = guild.get_role(role_id) if role_id else None
            if role:
                lines.append(f"✅ `{role_key}` → **{role.name}** (ID: `{role_id}`)")
            else:
                lines.append(f"❌ `{role_key}` → Role ID `{role_id or '(tidak ditemukan di server_map.yml)'}` **tidak ditemukan** di server!")
                all_ok = False

        lines.append("\n## Channel di CHANNEL_PERMISSIONS")
        for channel_name in CHANNEL_PERMISSIONS:
            ch = get_channel_by_name(guild, channel_name)
            if ch:
                lines.append(f"✅ `#{channel_name}` ditemukan ({ch.type})")
            else:
                lines.append(f"❌ `#{channel_name}` **tidak ditemukan** di server!")
                all_ok = False

        if all_ok:
            lines.append("\n✅ **Semua role dan channel valid!** Aman untuk menjalankan `/permission restore`.")
        else:
            lines.append("\n⚠️ **Ada yang tidak valid!** Periksa `shared/server_map.yml` dan nama channel di Discord sebelum menjalankan `/permission restore`.")

        embed = discord.Embed(
            title="🔎 Hasil Validasi Role & Channel",
            description="\n".join(lines),
            color=discord.Color.green() if all_ok else discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: KotabiBot):
    await bot.add_cog(Permissions(bot))