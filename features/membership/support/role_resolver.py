"""
features/membership/support/role_resolver.py — Tier → Discord Role
======================================================================
Satu-satunya tempat yang tahu tentang mapping tier ke Discord role ID.
Semua ID dibaca dari shared/server_map.yml via shared/config.py.
Tidak ada hardcode ID di sini.

Penggunaan:
    resolver = RoleResolver(guild)
    await resolver.apply_tier(member, tier='companion')
    await resolver.remove_all_membership_roles(member)
"""

from __future__ import annotations

import logging
from typing import Optional

import discord

from shared.config import get_role_id

_log = logging.getLogger("bot.membership.role_resolver")

# Companion dan di atasnya otomatis dapat role Traveler juga
# Patron tidak mendapat role Companion/Traveler — hanya Patron
TIER_ROLE_CHAIN: dict[str, list[str]] = {
    "trial":     ["trial"],
    "traveler":  ["traveler"],
    "companion": ["companion", "traveler"],
    "patron":    ["patron"],
}

# Role yang dicabut saat tier tertentu di-revoke
TIER_REVOKE_ROLES: dict[str, list[str]] = {
    "trial":     ["trial"],
    "traveler":  ["traveler"],
    "companion": ["companion", "traveler"],
    "patron":    ["patron"],
}

# Semua role membership — untuk clean-slate sebelum assign baru
ALL_MEMBERSHIP_ROLE_KEYS = ["trial", "traveler", "companion", "patron"]


class RoleResolver:
    def __init__(self, guild: discord.Guild):
        self.guild = guild

    def _get_role(self, role_key: str) -> Optional[discord.Role]:
        role_id = get_role_id(self.guild.id, role_key)
        if not role_id:
            _log.warning("Role key '%s' tidak ditemukan di server_map.yml", role_key)
            return None
        role = self.guild.get_role(role_id)
        if not role:
            _log.warning("Role ID %d untuk '%s' tidak ditemukan di Discord", role_id, role_key)
        return role

    async def apply_tier(self, member: discord.Member, tier: str) -> list[discord.Role]:
        """
        Bersihkan semua role membership lama, lalu assign role chain untuk tier baru.
        Return list role yang berhasil ditambahkan.
        """
        # Cabut semua role membership dulu
        await self.remove_all_membership_roles(member)

        # Assign role chain untuk tier baru
        chain = TIER_ROLE_CHAIN.get(tier, [tier])
        to_add = []
        for key in chain:
            role = self._get_role(key)
            if role and role not in member.roles:
                to_add.append(role)

        if to_add:
            try:
                await member.add_roles(*to_add, reason=f"Membership tier: {tier}")
                _log.info(
                    "Applied tier '%s' to %s (%d) — roles: %s",
                    tier, member.name, member.id,
                    [r.name for r in to_add]
                )
            except discord.Forbidden:
                _log.error(
                    "Forbidden: cannot add roles to %s (%d)", member.name, member.id
                )
                return []

        return to_add

    async def remove_tier(self, member: discord.Member, tier: str) -> list[discord.Role]:
        """
        Cabut role chain untuk tier tertentu.
        Dipakai saat revoke atau expired.
        """
        keys = TIER_REVOKE_ROLES.get(tier, [tier])
        to_remove = []
        for key in keys:
            role = self._get_role(key)
            if role and role in member.roles:
                to_remove.append(role)

        if to_remove:
            try:
                await member.remove_roles(*to_remove, reason=f"Membership revoked: {tier}")
                _log.info(
                    "Removed tier '%s' from %s (%d) — roles: %s",
                    tier, member.name, member.id,
                    [r.name for r in to_remove]
                )
            except discord.Forbidden:
                _log.error(
                    "Forbidden: cannot remove roles from %s (%d)", member.name, member.id
                )
                return []

        return to_remove

    async def remove_all_membership_roles(self, member: discord.Member) -> None:
        """
        Cabut semua role membership (clean-slate sebelum assign tier baru).
        """
        to_remove = []
        for key in ALL_MEMBERSHIP_ROLE_KEYS:
            role = self._get_role(key)
            if role and role in member.roles:
                to_remove.append(role)

        if to_remove:
            try:
                await member.remove_roles(*to_remove, reason="Membership role reset")
            except discord.Forbidden:
                _log.error(
                    "Forbidden: cannot remove membership roles from %s (%d)",
                    member.name, member.id
                )

    async def sync_member(
        self, member: discord.Member, tier: Optional[str], is_active: bool
    ) -> dict:
        changes = {"added": [], "removed": []}

        if not is_active or tier is None:
            # Tidak ada membership aktif → cabut semua, lalu kembalikan ke Drifter
            await self.remove_all_membership_roles(member)
            changes["removed"] = ALL_MEMBERSHIP_ROLE_KEYS

            drifter = self._get_role("drifter")
            if drifter and drifter not in member.roles:
                try:
                    await member.add_roles(drifter, reason="Membership sync — kembali ke Drifter")
                    changes["added"].append("drifter")
                except discord.Forbidden:
                    _log.error(
                        "Forbidden: cannot add Drifter role to %s (%d) saat sync",
                        member.name, member.id,
                    )
            return changes

        # Hitung role yang seharusnya ada
        expected_keys = set(TIER_ROLE_CHAIN.get(tier, [tier]))
        all_keys      = set(ALL_MEMBERSHIP_ROLE_KEYS)
        should_remove = all_keys - expected_keys

        for key in should_remove:
            role = self._get_role(key)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Membership sync")
                    changes["removed"].append(key)
                except discord.Forbidden:
                    pass

        for key in expected_keys:
            role = self._get_role(key)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Membership sync")
                    changes["added"].append(key)
                except discord.Forbidden:
                    pass

        if changes["added"] or changes["removed"]:
            _log.info(
                "Synced %s (%d): +%s -%s",
                member.name, member.id, changes["added"], changes["removed"]
            )

        return changes
    
    async def revoke_to_drifter(self, member: discord.Member, tier: str) -> list[discord.Role]:
        """Cabut role tier, lalu kembalikan ke Drifter (status warga biasa)."""
        removed = await self.remove_tier(member, tier)

        drifter = self._get_role("drifter")
        if drifter and drifter not in member.roles:
            try:
                await member.add_roles(drifter, reason="Membership revoked/expired — kembali ke Drifter")
            except discord.Forbidden:
                _log.error("Forbidden: cannot add Drifter role to %s (%d)", member.name, member.id)

        return removed