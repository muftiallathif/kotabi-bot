"""
permissions_cog.py — Sistem Restore & Manajemen Permission Server Kotabi
Menggantikan setup_permissions.py dengan sistem yang lebih lengkap dan aman.

Semua command dikelompokkan di bawah satu group /permission (lihat
PERMISSION_ENGINE_REFACTOR.md) supaya tidak ketuker dengan /structure
milik structure_cog.py:
  /permission restore          — Restore semua permission dari tabel
  /permission restore_channel  — Restore 1 channel saja
  /permission preview          — Preview perubahan tanpa apply
  /permission backup           — Simpan kondisi permission sekarang ke file JSON
  /permission sync_roles       — Validasi semua role ID di konfigurasi restore

CATATAN (fix duplikasi): logic penerapan permission (_apply_vip_channel_permission,
_apply_drifter_permission, get_role, get_channel_by_name, send_paginated) TIDAK
lagi didefinisikan di sini — semuanya di-import dari
features/server_admin/support/permission_engine.py, yang juga dipakai oleh
structure_cog.py (/setup_structure). Dulu kedua cog ini menyimpan salinan
identik dari fungsi-fungsi tersebut; sekarang cukup diubah sekali di engine.
"""

import discord
import json
import io
import logging
from datetime import datetime, timezone
from typing import Optional
from discord.ext import commands
from core.bot import KotabiBot
from shared.config import get_role_id
from shared.checks import has_authorized_access
from features.server_admin.support.permission_table import (
    VIP_CHANNEL_PERMISSIONS,
    ROLE_KEYS_USED,
    PUBLIC_CHANNELS_FOR_DRIFTER,
)
from features.server_admin.support.permission_engine import (
    get_role,
    get_channel_by_name,
    apply_vip_channel_permission,
    apply_drifter_permission,
    send_paginated,
)

_log = logging.getLogger(__name__)


# ============================================================================
# COG UTAMA
# ============================================================================

class Permissions(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    # Semua command permission dikelompokkan di bawah /permission, supaya
    # tidak ketuker dengan /structure (structure_cog.py) — dulu nama cog
    # "RestoreServer" vs "RestructureServer" gampang salah baca, dan
    # command /restore vs /setup_structure / /preview vs /structure_preview
    # tidak konsisten.
    permission_group = discord.app_commands.Group(
        name="permission",
        description="Kelola permission channel VIP & Drifter server Kotabi.",
        default_permissions=discord.Permissions(administrator=True),
    )

    # ------------------------------------------------------------------ #
    #  /permission restore — Restore semua permission VIP + Drifter       #
    # ------------------------------------------------------------------ #

    @permission_group.command(
        name="restore",
        description="Restore semua permission channel VIP dan publik sesuai tabel yang sudah ditentukan (Khusus Admin)."
    )
    @discord.app_commands.guild_only()
    async def restore(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send("❌ Anda tidak memiliki wewenang untuk menjalankan perintah ini.", ephemeral=True)

        guild = interaction.guild
        everyone = guild.default_role
        logs = ["🔄 **Restore Permission Server Dimulai...**\n"]

        # 1. Restore channel VIP
        logs.append("## 🔐 Channel VIP")
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

        # 2. Restore Drifter di channel publik
        logs.append("\n## 🌍 Channel Publik (Drifter)")
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

        logs.append("\n✅ **Restore selesai!**")
        _log.info("Restore permission dijalankan oleh %s (%s)", interaction.user, interaction.user.id)
        await send_paginated(interaction, logs, "📋 Hasil Restore Permission")

    # ------------------------------------------------------------------ #
    #  /restore_channel — Restore 1 channel saja                          #
    # ------------------------------------------------------------------ #

    @permission_group.command(
        name="restore_channel",
        description="Restore permission satu channel tertentu saja (Khusus Admin)."
    )
    @discord.app_commands.describe(channel="Pilih channel yang ingin di-restore permissionnya.")
    @discord.app_commands.guild_only()
    async def restore_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send("❌ Tidak memiliki wewenang.", ephemeral=True)

        guild = interaction.guild
        everyone = guild.default_role
        ch_name = channel.name.lower()

        # Cek apakah ini channel VIP
        if ch_name in VIP_CHANNEL_PERMISSIONS:
            try:
                logs = await apply_vip_channel_permission(channel, guild, everyone, dry_run=False)
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

        # Cek apakah ini channel publik Drifter
        elif channel.name in PUBLIC_CHANNELS_FOR_DRIFTER:
            try:
                result = await apply_drifter_permission(channel, guild, dry_run=False)
                embed = discord.Embed(
                    title=f"✅ Restore #{channel.name}",
                    description=result,
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

        else:
            await interaction.followup.send(
                f"⚠️ `#{channel.name}` tidak terdaftar di tabel VIP maupun daftar channel publik.\n"
                f"Pastikan nama channel sesuai dengan konfigurasi.",
                ephemeral=True
            )

        _log.info("Restore channel #%s dijalankan oleh %s", channel.name, interaction.user)

    # ------------------------------------------------------------------ #
    #  /preview — Lihat rencana perubahan tanpa apply                     #
    # ------------------------------------------------------------------ #

    @permission_group.command(
        name="preview",
        description="Lihat preview permission yang akan diterapkan tanpa mengubah apa pun (Khusus Admin)."
    )
    @discord.app_commands.describe(channel="Opsional: preview untuk channel tertentu saja.")
    @discord.app_commands.guild_only()
    async def preview(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send("❌ Tidak memiliki wewenang.", ephemeral=True)

        guild = interaction.guild
        everyone = guild.default_role
        logs = ["🔍 **Preview Permission (DRY RUN — tidak ada perubahan)**\n"]

        if channel:
            # Preview untuk 1 channel
            ch_name = channel.name.lower()
            if ch_name in VIP_CHANNEL_PERMISSIONS:
                result = await apply_vip_channel_permission(channel, guild, everyone, dry_run=True)
                logs.extend(result)
            elif channel.name in PUBLIC_CHANNELS_FOR_DRIFTER:
                result = await apply_drifter_permission(channel, guild, dry_run=True)
                logs.append(result)
            else:
                logs.append(f"⚠️ `#{channel.name}` tidak terdaftar di sistem restore.")
        else:
            # Preview semua
            logs.append("## 🔐 Channel VIP")
            for ch_name in VIP_CHANNEL_PERMISSIONS:
                ch = get_channel_by_name(guild, ch_name)
                if not ch:
                    logs.append(f"❌ `{ch_name}` — tidak ditemukan di server")
                    continue
                result = await apply_vip_channel_permission(ch, guild, everyone, dry_run=True)
                logs.extend(result)

            logs.append("\n## 🌍 Channel Publik (Drifter)")
            for ch_name in PUBLIC_CHANNELS_FOR_DRIFTER:
                ch = get_channel_by_name(guild, ch_name)
                if not ch:
                    logs.append(f"⚠️ `{ch_name}` — tidak ditemukan")
                    continue
                result = await apply_drifter_permission(ch, guild, dry_run=True)
                logs.append(result)

            logs.append("\n_Tidak ada perubahan yang diterapkan. Gunakan `/restore` untuk apply._")

        await send_paginated(interaction, logs, "🔍 Preview Permission")

    # ------------------------------------------------------------------ #
    #  /backup_permissions — Export kondisi permission sekarang ke JSON   #
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

        # Snapshot semua channel (teks & suara) beserta permission override-nya
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

        # Kirim sebagai file JSON
        json_bytes = json.dumps(backup, indent=2, ensure_ascii=False).encode("utf-8")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"permission_backup_{guild.id}_{timestamp}.json"

        file = discord.File(io.BytesIO(json_bytes), filename=filename)
        await interaction.followup.send(
            f"✅ **Backup permission berhasil!**\n"
            f"📦 Total channel di-backup: **{len(backup['channels'])}**\n"
            f"🕐 Waktu: `{backup['backup_time']}`\n\n"
            f"Simpan file ini sebelum menjalankan `/restore`.",
            file=file,
            ephemeral=True
        )
        _log.info("Backup permission dijalankan oleh %s (%s)", interaction.user, interaction.user.id)

    # ------------------------------------------------------------------ #
    #  /sync_roles — Validasi semua role ID di konfigurasi                #
    # ------------------------------------------------------------------ #

    @permission_group.command(
        name="sync_roles",
        description="Validasi apakah semua role ID di konfigurasi restore masih valid (Khusus Admin)."
    )
    @discord.app_commands.guild_only()
    async def sync_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not has_authorized_access(interaction.user):
            return await interaction.followup.send("❌ Tidak memiliki wewenang.", ephemeral=True)

        guild = interaction.guild
        lines = ["🔎 **Validasi Role ID**\n"]
        all_ok = True

        for role_name in ROLE_KEYS_USED:
            role_id = get_role_id(guild.id, role_name)
            role = guild.get_role(role_id) if role_id else None
            if role:
                lines.append(f"✅ `{role_name}` → **{role.name}** (ID: `{role_id}`)")
            else:
                lines.append(f"❌ `{role_name}` → Role ID `{role_id or '(tidak ditemukan di server_map.yml)'}` **tidak ditemukan** di server!")
                all_ok = False

        lines.append("\n## Channel VIP")
        for ch_name in VIP_CHANNEL_PERMISSIONS:
            ch = get_channel_by_name(guild, ch_name)
            if ch:
                lines.append(f"✅ `#{ch_name}` ditemukan")
            else:
                lines.append(f"❌ `#{ch_name}` **tidak ditemukan** di server!")
                all_ok = False

        if all_ok:
            lines.append("\n✅ **Semua role dan channel valid!** Aman untuk menjalankan `/restore`.")
        else:
            lines.append("\n⚠️ **Ada yang tidak valid!** Periksa `shared/server_map.yml` sebelum menjalankan `/restore`.")

        embed = discord.Embed(
            title="🔎 Hasil Validasi Role & Channel",
            description="\n".join(lines),
            color=discord.Color.green() if all_ok else discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


# ============================================================================
# SETUP
# ============================================================================

async def setup(bot: KotabiBot):
    await bot.add_cog(Permissions(bot))