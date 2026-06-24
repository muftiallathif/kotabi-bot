"""
restore_server.py — Sistem Restore & Manajemen Permission Server Kotabi
Menggantikan setup_permissions.py dengan sistem yang lebih lengkap dan aman.

Commands:
  /restore              — Restore semua permission dari JSON
  /restore_channel      — Restore 1 channel saja
  /preview              — Preview perubahan tanpa apply
  /backup_permissions   — Simpan kondisi permission sekarang ke file JSON
"""

import discord
import json
import os
import io
import logging
from datetime import datetime, timezone
from typing import Optional
from discord.ext import commands
from core.bot import KotabiBot

_log = logging.getLogger(__name__)

# ============================================================================
# KONFIGURASI AKSES & PATH
# ============================================================================

AUTHORIZED_USER_IDS = [int(uid) for uid in os.getenv("AUTHORIZED_USERS", "").split(",") if uid.strip()]

# Path ke file server_backup JSON (yang di-export oleh /export_server)
SERVER_BACKUP_PATH = os.getenv("SERVER_BACKUP_PATH", "config/server_backup.json")

# ============================================================================
# TABEL VIP PERMISSION
# Sumber kebenaran tunggal untuk semua permission channel VIP.
# Format: channel_name: {role_name: bool}
# True  = allow (view + send)
# False = deny  (tidak bisa lihat sama sekali)
# ============================================================================

# Nama role VIP yang dikelola (urutan penting untuk display)
VIP_ROLES = ["trial", "traveler", "companion", "scholar", "patron"]

# Pemetaan channel ke hak akses per role VIP
# Royal Guard & Prime Minister selalu dapat akses penuh di semua channel VIP
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

# Role ID mapping — dari server_map.yml
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

# Channel-channel non-VIP yang perlu dapat akses Drifter
# (semua channel publik yang bukan VIP-only)
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
# FUNGSI PEMBANTU
# ============================================================================

def _is_authorized(user: discord.Member) -> bool:
    """Memeriksa apakah user memiliki hak akses (admin atau authorized ID)."""
    if user.id in AUTHORIZED_USER_IDS:
        return True
    if user.guild_permissions.administrator:
        return True
    return False


def _get_role(guild: discord.Guild, role_name: str) -> Optional[discord.Role]:
    """Mengambil objek Role dari guild berdasarkan nama kunci."""
    role_id = ROLE_NAME_TO_ID.get(role_name)
    if not role_id:
        return None
    return guild.get_role(role_id)


def _get_channel_by_name(guild: discord.Guild, channel_name: str) -> Optional[discord.abc.GuildChannel]:
    """Mencari channel di guild berdasarkan nama (case-insensitive)."""
    name_lower = channel_name.lower()
    for ch in guild.channels:
        if ch.name.lower() == name_lower:
            return ch
    return None


def _load_backup(path: str) -> Optional[dict]:
    """Membaca file JSON backup server."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log.error("Gagal membaca file backup: %s", e)
        return None


async def _apply_vip_channel_permission(
    channel: discord.abc.GuildChannel,
    guild: discord.Guild,
    everyone: discord.Role,
    dry_run: bool = False,
) -> list[str]:
    """
    Menerapkan permission VIP pada satu channel.
    Mengembalikan list log string untuk ditampilkan.
    """
    channel_name = channel.name.lower()
    vip_rules = VIP_CHANNEL_PERMISSIONS.get(channel_name)

    if vip_rules is None:
        return [f"⏭️  `#{channel.name}` — Bukan channel VIP, dilewati"]

    logs = [f"\n**#{channel.name}**"]

    if not dry_run:
        # Deny everyone terlebih dahulu
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

    # Royal Guard & Prime Minister selalu allow
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
    """Memberikan akses view kepada role Drifter pada channel publik."""
    drifter = _get_role(guild, "drifter")
    if not drifter:
        return f"  ❌ Role Drifter tidak ditemukan!"

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
            if first:
                await interaction.followup.send(embed=embed, ephemeral=True)
                first = False
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
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
# COG UTAMA
# ============================================================================

class RestoreServer(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  /restore — Restore semua permission VIP + Drifter sekaligus        #
    # ------------------------------------------------------------------ #

    @discord.app_commands.command(
        name="restore",
        description="Restore semua permission channel VIP dan publik sesuai tabel yang sudah ditentukan (Khusus Admin)."
    )
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def restore(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not _is_authorized(interaction.user):
            return await interaction.followup.send("❌ Anda tidak memiliki wewenang untuk menjalankan perintah ini.", ephemeral=True)

        guild = interaction.guild
        everyone = guild.default_role
        logs = ["🔄 **Restore Permission Server Dimulai...**\n"]

        # 1. Restore channel VIP
        logs.append("## 🔐 Channel VIP")
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

        # 2. Restore Drifter di channel publik
        logs.append("\n## 🌍 Channel Publik (Drifter)")
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

        logs.append("\n✅ **Restore selesai!**")
        _log.info("Restore permission dijalankan oleh %s (%s)", interaction.user, interaction.user.id)
        await _send_paginated(interaction, logs, "📋 Hasil Restore Permission")

    # ------------------------------------------------------------------ #
    #  /restore_channel — Restore 1 channel saja                          #
    # ------------------------------------------------------------------ #

    @discord.app_commands.command(
        name="restore_channel",
        description="Restore permission satu channel tertentu saja (Khusus Admin)."
    )
    @discord.app_commands.describe(channel="Pilih channel yang ingin di-restore permissionnya.")
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def restore_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)

        if not _is_authorized(interaction.user):
            return await interaction.followup.send("❌ Tidak memiliki wewenang.", ephemeral=True)

        guild = interaction.guild
        everyone = guild.default_role
        ch_name = channel.name.lower()

        # Cek apakah ini channel VIP
        if ch_name in VIP_CHANNEL_PERMISSIONS:
            try:
                logs = await _apply_vip_channel_permission(channel, guild, everyone, dry_run=False)
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
                result = await _apply_drifter_permission(channel, guild, dry_run=False)
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

    @discord.app_commands.command(
        name="preview",
        description="Lihat preview permission yang akan diterapkan tanpa mengubah apa pun (Khusus Admin)."
    )
    @discord.app_commands.describe(channel="Opsional: preview untuk channel tertentu saja.")
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def preview(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await interaction.response.defer(ephemeral=True)

        if not _is_authorized(interaction.user):
            return await interaction.followup.send("❌ Tidak memiliki wewenang.", ephemeral=True)

        guild = interaction.guild
        everyone = guild.default_role
        logs = ["🔍 **Preview Permission (DRY RUN — tidak ada perubahan)**\n"]

        if channel:
            # Preview untuk 1 channel
            ch_name = channel.name.lower()
            if ch_name in VIP_CHANNEL_PERMISSIONS:
                result = await _apply_vip_channel_permission(channel, guild, everyone, dry_run=True)
                logs.extend(result)
            elif channel.name in PUBLIC_CHANNELS_FOR_DRIFTER:
                result = await _apply_drifter_permission(channel, guild, dry_run=True)
                logs.append(result)
            else:
                logs.append(f"⚠️ `#{channel.name}` tidak terdaftar di sistem restore.")
        else:
            # Preview semua
            logs.append("## 🔐 Channel VIP")
            for ch_name in VIP_CHANNEL_PERMISSIONS:
                ch = _get_channel_by_name(guild, ch_name)
                if not ch:
                    logs.append(f"❌ `{ch_name}` — tidak ditemukan di server")
                    continue
                result = await _apply_vip_channel_permission(ch, guild, everyone, dry_run=True)
                logs.extend(result)

            logs.append("\n## 🌍 Channel Publik (Drifter)")
            for ch_name in PUBLIC_CHANNELS_FOR_DRIFTER:
                ch = _get_channel_by_name(guild, ch_name)
                if not ch:
                    logs.append(f"⚠️ `{ch_name}` — tidak ditemukan")
                    continue
                result = await _apply_drifter_permission(ch, guild, dry_run=True)
                logs.append(result)

            logs.append("\n_Tidak ada perubahan yang diterapkan. Gunakan `/restore` untuk apply._")

        await _send_paginated(interaction, logs, "🔍 Preview Permission")

    # ------------------------------------------------------------------ #
    #  /backup_permissions — Export kondisi permission sekarang ke JSON   #
    # ------------------------------------------------------------------ #

    @discord.app_commands.command(
        name="backup_permissions",
        description="Export kondisi permission semua channel saat ini ke file JSON (Khusus Admin)."
    )
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def backup_permissions(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not _is_authorized(interaction.user):
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

    @discord.app_commands.command(
        name="sync_roles",
        description="Validasi apakah semua role ID di konfigurasi restore masih valid (Khusus Admin)."
    )
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def sync_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not _is_authorized(interaction.user):
            return await interaction.followup.send("❌ Tidak memiliki wewenang.", ephemeral=True)

        guild = interaction.guild
        lines = ["🔎 **Validasi Role ID**\n"]
        all_ok = True

        for role_name, role_id in ROLE_NAME_TO_ID.items():
            role = guild.get_role(role_id)
            if role:
                lines.append(f"✅ `{role_name}` → **{role.name}** (ID: `{role_id}`)")
            else:
                lines.append(f"❌ `{role_name}` → Role ID `{role_id}` **tidak ditemukan** di server!")
                all_ok = False

        lines.append("\n## Channel VIP")
        for ch_name in VIP_CHANNEL_PERMISSIONS:
            ch = _get_channel_by_name(guild, ch_name)
            if ch:
                lines.append(f"✅ `#{ch_name}` ditemukan")
            else:
                lines.append(f"❌ `#{ch_name}` **tidak ditemukan** di server!")
                all_ok = False

        if all_ok:
            lines.append("\n✅ **Semua role dan channel valid!** Aman untuk menjalankan `/restore`.")
        else:
            lines.append("\n⚠️ **Ada yang tidak valid!** Periksa ID di `restore_server.py` sebelum menjalankan `/restore`.")

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
    await bot.add_cog(RestoreServer(bot))