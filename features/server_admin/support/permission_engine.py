"""
features/server_admin/support/permission_engine.py — Engine Penerapan Permission Bersama
============================================================================================
Sebelumnya, logic penerapan permission (_apply_vip_channel_permission,
_apply_drifter_permission, _get_role, _get_channel_by_name, _send_paginated)
ter-duplikasi PERSIS SAMA di dua tempat:
  - features/server_admin/permissions_cog.py  (/restore, /preview, dst)
  - features/server_admin/structure_cog.py    (/setup_structure, tahap akhir)

Sekarang keduanya import dari sini. Kalau mau ubah aturan permission (mis.
tambah role VIP baru, ubah default deny/allow), cukup edit SEKALI di file ini.

PENTING — file ini TIDAK berisi logic struktur kategori/posisi channel.
STRUCTURE_BLUEPRINT, _apply_structure(), _get_or_create_category(), dan
_find_text_or_voice() TETAP tinggal di structure_cog.py, karena itu yang
membedakan /setup_structure (struktur + permission) dari /restore
(permission saja). Lihat DEVELOPMENT_GUIDE.md jawaban Q2.

Penggunaan:
    from features.server_admin.support.permission_engine import (
        get_role, get_channel_by_name,
        apply_vip_channel_permission, apply_drifter_permission,
        send_paginated,
    )
"""

import discord
from typing import Optional

from shared.config import get_role_id
from features.server_admin.support.permission_table import VIP_CHANNEL_PERMISSIONS


def get_role(guild: discord.Guild, role_name: str) -> Optional[discord.Role]:
    """Mengambil objek Role dari guild berdasarkan nama kunci, lewat shared.config (server_map.yml)."""
    role_id = get_role_id(guild.id, role_name)
    if not role_id:
        return None
    return guild.get_role(role_id)


def get_channel_by_name(guild: discord.Guild, channel_name: str) -> Optional[discord.abc.GuildChannel]:
    """Mencari channel di guild berdasarkan nama (case-insensitive), tipe apa pun."""
    name_lower = channel_name.lower()
    for ch in guild.channels:
        if ch.name.lower() == name_lower:
            return ch
    return None


async def apply_vip_channel_permission(
    channel: discord.abc.GuildChannel,
    guild: discord.Guild,
    everyone: discord.Role,
    dry_run: bool = False,
) -> list[str]:
    """
    Menerapkan permission VIP pada satu channel sesuai VIP_CHANNEL_PERMISSIONS.
    Mengembalikan list log string untuk ditampilkan ke admin.
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
        role = get_role(guild, role_name)
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
        staff_role = get_role(guild, staff_key)
        if staff_role:
            logs.append(f"  ✅ Allow `{staff_role.name}` (Staff)")
            if not dry_run:
                await channel.set_permissions(staff_role, view_channel=True, send_messages=True)

    return logs


async def apply_drifter_permission(
    channel: discord.abc.GuildChannel,
    guild: discord.Guild,
    dry_run: bool = False,
) -> str:
    """Memberikan akses view kepada role Drifter pada channel publik."""
    drifter = get_role(guild, "drifter")
    if not drifter:
        return "  ❌ Role Drifter tidak ditemukan!"

    if not dry_run:
        await channel.set_permissions(drifter, view_channel=True)

    return f"  ✅ Drifter diberi akses ke `#{channel.name}`"


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