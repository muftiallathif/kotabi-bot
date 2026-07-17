"""
features/server_admin/support/permission_engine.py — Engine Penerapan Permission Bersama (v2)
==================================================================================================
GENERASI KEDUA — bekerja dengan skema CHANNEL_PERMISSIONS baru (lihat
PERMISSION_MATRIX.md): setiap channel punya {role_key: {permission_kwarg: bool}},
bukan {role_key: bool} seperti versi v1.

Perubahan dari v1:
- apply_channel_permission() menggantikan apply_vip_channel_permission() +
  apply_drifter_permission() — sekarang SATU fungsi menangani channel VIP
  MAUPUN channel publik, karena role_key "everyone" bisa langsung
  didefinisikan per channel di CHANNEL_PERMISSIONS (tidak perlu lagi
  daftar terpisah PUBLIC_CHANNELS_FOR_DRIFTER).
- kwargs permission diteruskan generic ke discord.PermissionOverwrite,
  jadi menambah permission baru (mis. attach_files) di permission_table.py
  TIDAK perlu ubah kode di sini sama sekali.

Dipakai oleh permissions_cog.py (/permission restore|preview|sync_roles)
dan structure_cog.py (/structure setup, tahap penerapan permission).
"""

import discord
from typing import Optional

from shared.config import get_role_id
from features.server_admin.support.permission_table import CHANNEL_PERMISSIONS


def get_role(guild: discord.Guild, role_key: str) -> Optional[discord.Role]:
    """
    Mengambil objek Role dari guild berdasarkan role_key.
    "everyone" adalah kata kunci khusus -> guild.default_role.
    Role lain di-resolve lewat shared.config.get_role_id() (server_map.yml).
    """
    if role_key == "everyone":
        return guild.default_role
    role_id = get_role_id(guild.id, role_key)
    if not role_id:
        return None
    return guild.get_role(role_id)


def get_channel_by_name(guild: discord.Guild, channel_name: str) -> Optional[discord.abc.GuildChannel]:
    """Mencari channel di guild berdasarkan nama (case-insensitive), tipe apa pun
    (text, voice, forum, dst)."""
    name_lower = channel_name.lower()
    for ch in guild.channels:
        if ch.name.lower() == name_lower:
            return ch
    return None


async def apply_channel_permission(
    channel: discord.abc.GuildChannel,
    guild: discord.Guild,
    dry_run: bool = False,
) -> list[str]:
    """
    Menerapkan seluruh rule permission untuk satu channel sesuai
    CHANNEL_PERMISSIONS. Menggantikan apply_vip_channel_permission() +
    apply_drifter_permission() dari versi v1 — satu fungsi untuk semua
    jenis channel (VIP-gated maupun publik, text/voice/forum).

    Mengembalikan list log string untuk ditampilkan ke admin.
    """
    channel_key = channel.name.lower()
    rules = CHANNEL_PERMISSIONS.get(channel_key)

    if rules is None:
        return [f"⏭️  `#{channel.name}` — Tidak ada di CHANNEL_PERMISSIONS, dilewati (warisan permission kategori)"]

    logs = [f"\n**#{channel.name}**"]

    for role_key, perm_kwargs in rules.items():
        role = get_role(guild, role_key)
        if not role:
            logs.append(f"  ❌ `{role_key}` — Role tidak ditemukan!")
            continue

        summary = ", ".join(f"{k}={'✅' if v else '❌'}" for k, v in perm_kwargs.items())
        logs.append(f"  🔧 `{role.name}` — {summary}")

        if not dry_run:
            try:
                overwrite = discord.PermissionOverwrite(**perm_kwargs)
                await channel.set_permissions(role, overwrite=overwrite)
            except TypeError as e:
                # Typo nama kwarg (tidak cocok dengan atribut discord.PermissionOverwrite)
                logs.append(f"    ⚠️ Nama permission tidak dikenal discord.py untuk `{role.name}`: {e}")
            except discord.Forbidden:
                logs.append(f"    ⚠️ Bot tidak punya izin mengubah permission `{role.name}` di channel ini")
            except discord.HTTPException as e:
                logs.append(f"    ⚠️ Gagal menerapkan ke `{role.name}`: {e}")

    return logs


async def send_paginated(interaction: discord.Interaction, lines: list[str], title: str):
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