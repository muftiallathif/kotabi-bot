"""
cogs/membership.py — Membership System v1 (Discord Layer)
==========================================================
Cog ini HANYA berisi:
  - Slash commands (Discord interface)
  - Background task scheduler
  - DM + embed ke user
  - Role update via RoleResolver

Semua logic bisnis ada di:
  - lib/membership/service.py
  - lib/grants/engine.py

Tidak ada SQL langsung di sini.
Tidak ada keputusan bisnis di sini.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord.ext import commands, tasks
from discord.utils import utcnow

from core.bot import KotabiBot
from lib.config import get_lifetime_threshold
from lib.grants.engine import ApplyResult, GrantEngine
from lib.membership.models import MembershipRow
from lib.membership.product_loader import ProductLoader
from lib.membership.role_resolver import RoleResolver
from lib.membership.service import (
    MembershipService,
    get_current_trial_cycle,
)

_log = logging.getLogger("bot.membership")

# ============================================================
# KONFIGURASI
# ============================================================

AUTHORIZED_USER_IDS = [
    int(uid) for uid in os.getenv("AUTHORIZED_USERS", "").split(",") if uid.strip()
]

# Dibaca dari membership_settings.yml via environment atau default
import yaml

_MEMBERSHIP_SETTINGS_PATH = (
    os.getenv("ALT_MEMBERSHIP_SETTINGS_PATH") or "config/membership_settings.yml"
)
with open(_MEMBERSHIP_SETTINGS_PATH, "r", encoding="utf-8") as _f:
    _membership_settings = yaml.safe_load(_f)

_MEMBERSHIP_CFG   = _membership_settings["membership"]
GUILD_ID          = _MEMBERSHIP_CFG["guild_id"]
ANNOUNCEMENT_CH   = _MEMBERSHIP_CFG["announcement_channel_id"]
GRACE_PERIOD_DAYS = _MEMBERSHIP_CFG.get("grace_period_days", 3)
MOD_ROLE_IDS      = _MEMBERSHIP_CFG.get("moderator_role_ids", [])

MEMBERSHIP_LOCK = asyncio.Lock()


# ============================================================
# HELPER
# ============================================================

def _can_manage(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    if member.id in AUTHORIZED_USER_IDS:
        return True
    return bool(MOD_ROLE_IDS and any(r.id in MOD_ROLE_IDS for r in member.roles))


def _fmt_progress(point_count: int) -> str:
    threshold = get_lifetime_threshold()
    remaining = max(0, threshold - point_count)
    return f"{point_count}/{threshold} poin ({remaining} poin lagi)"


async def _send_dm(user_id: int, bot: KotabiBot, embed: discord.Embed) -> bool:
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if not user.dm_channel:
            await user.create_dm()
        await user.send(embed=embed)
        return True
    except (discord.Forbidden, discord.NotFound):
        _log.warning("Tidak bisa DM user %s", user_id)
        return False


async def _apply_discord_role(
    guild: discord.Guild,
    user_id: int,
    result: ApplyResult,
) -> None:
    """Update Discord role berdasarkan ApplyResult."""
    member = guild.get_member(user_id)
    if not member:
        _log.warning("Member %d tidak ditemukan di guild saat apply role", user_id)
        return

    resolver = RoleResolver(guild)
    tier = result.tier or (result.membership.tier if result.membership else None)
    if tier:
        try:
            await resolver.apply_tier(member, tier)
        except Exception as e:
            _log.error("Gagal apply Discord role ke %d: %s", user_id, e)


def _build_grant_dm_embed(
    result: ApplyResult,
    product_name: str,
) -> discord.Embed:
    """Buat DM embed setelah grant berhasil."""
    if result.just_became_lifetime:
        embed = discord.Embed(
            title="✅ Membership Granted — LIFETIME 👑",
            description=(
                f"Selamat! Kamu telah mencapai **{get_lifetime_threshold()} poin kumulatif** "
                f"dan sekarang menjadi **Patron** secara permanen.\n\n"
                "Terima kasih atas dukunganmu! 🎉"
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="Progress Lifetime", value=f"{result.point_after}/{get_lifetime_threshold()} poin ✅")
    elif result.is_lifetime:
        embed = discord.Embed(
            title="✅ Membership Granted — LIFETIME 👑",
            description=f"Selamat! Kamu sekarang adalah **Patron** selamanya.",
            color=discord.Color.gold(),
        )
    else:
        membership = result.membership
        expires_at = membership.expires_at if membership else None
        expire_ts  = int(expires_at.timestamp()) if expires_at else 0

        embed = discord.Embed(
            title="✅ Membership Granted",
            description=f"Selamat! Kamu sekarang memiliki membership **{product_name}**.",
            color=discord.Color.green(),
        )
        if expire_ts:
            embed.add_field(name="Expires", value=f"<t:{expire_ts}:F>", inline=True)
        embed.add_field(
            name="Progress Lifetime",
            value=_fmt_progress(result.point_after),
            inline=False,
        )
    return embed


# ============================================================
# COG
# ============================================================

class Membership(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot    = bot
        self.svc    = MembershipService(bot)
        self.engine = GrantEngine(bot)
        self.loader = ProductLoader()

    async def cog_load(self):
        # Pastikan tabel sudah ada (migration bisa juga dijalankan manual)
        from lib.membership.repository import MembershipRepository
        # Tabel dibuat via migration SQL, bukan di sini
        if not self.membership_expiry_check.is_running():
            self.membership_expiry_check.start()

    def cog_unload(self):
        if self.membership_expiry_check.is_running():
            self.membership_expiry_check.cancel()

    # ============================================================
    # COMMAND GROUP
    # ============================================================

    admin_group = discord.app_commands.Group(
        name="admin",
        description="Admin commands membership.",
        default_permissions=discord.Permissions(administrator=True),
    )

    # ----------------------------------------------------------
    # /admin grant-member
    # ----------------------------------------------------------

    @admin_group.command(name="grant-member", description="Grant membership ke satu user.")
    @discord.app_commands.describe(
        user="User yang mau dikasih membership.",
        product_id="ID produk (traveler / companion / patron / jlpt_n5 / kaiwa / dll).",
        quantity="Jumlah bulan (untuk produk yang mendukung quantity).",
    )
    @discord.app_commands.guild_only()
    async def grant_member(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        product_id: str,
        quantity: int = 1,
    ):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not _can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        product = self.loader.get(product_id)
        if not product:
            return await interaction.followup.send(
                f"❌ Produk `{product_id}` tidak ditemukan di products.yml.", ephemeral=True
            )

        if quantity < product.min_quantity or quantity > product.max_quantity:
            return await interaction.followup.send(
                f"❌ Quantity harus antara {product.min_quantity}–{product.max_quantity}.",
                ephemeral=True,
            )

        grant_payload = product.build_grant_payload(quantity)

        async with MEMBERSHIP_LOCK:
            result = await self.engine.apply(
                guild_id=interaction.guild_id,
                user_id=user.id,
                grant_payload=grant_payload,
                actor=interaction.user.id,
                source="admin",
            )

        if not result.success:
            return await interaction.followup.send(
                f"❌ Grant gagal: {result.errors}", ephemeral=True
            )

        # Update Discord role
        await _apply_discord_role(interaction.guild, user.id, result)

        # Announcement
        ch = interaction.guild.get_channel(ANNOUNCEMENT_CH)
        if ch:
            ann = discord.Embed(
                title="🎉 Member Baru" + (" 👑 LIFETIME" if result.is_lifetime else ""),
                description=f"{user.mention} mendapat membership **{product.name}**",
                color=discord.Color.gold() if result.is_lifetime else discord.Color.green(),
            )
            ann.set_thumbnail(url=user.display_avatar.url)
            try:
                await ch.send(embed=ann)
            except discord.Forbidden:
                pass

        # DM ke user
        dm_embed = _build_grant_dm_embed(result, product.name)
        await _send_dm(user.id, self.bot, dm_embed)

        # Reply ke admin
        reply = (
            f"✅ **{product.name}** granted → {user.mention}\n"
            f"Progress Lifetime: **{result.point_after}/{get_lifetime_threshold()} poin**"
        )
        if result.just_became_lifetime:
            reply += "\n🎉 User sekarang **LIFETIME MEMBER**!"
        elif result.membership and result.membership.expires_at:
            ts = int(result.membership.expires_at.timestamp())
            reply += f"\nExpires: <t:{ts}:R>"

        await interaction.followup.send(reply, ephemeral=True)

    # ----------------------------------------------------------
    # /admin grant-trial
    # ----------------------------------------------------------

    @admin_group.command(name="grant-trial", description="Grant trial 5 hari (0 poin).")
    @discord.app_commands.describe(user="User yang mau dikasih trial.")
    @discord.app_commands.guild_only()
    async def grant_trial(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not _can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        async with MEMBERSHIP_LOCK:
            eligible, reason = await self.svc.can_take_trial(interaction.guild_id, user.id)
            if not eligible:
                return await interaction.followup.send(f"❌ {reason}", ephemeral=True)

            result = await self.svc.grant_trial(
                guild_id=interaction.guild_id,
                user_id=user.id,
                actor=interaction.user.id,
            )

        # Perlu build ApplyResult sederhana untuk apply_discord_role
        # Bug fix: hanya satu kali apply role, lewat ApplyResult yang dibangun bersih.
        from lib.grants.engine import ApplyResult as AR
        ar = AR()
        ar.membership = result
        await _apply_discord_role(interaction.guild, user.id, ar)

        expires_ts = int(result.expires_at.timestamp()) if result.expires_at else 0
        dm_embed = discord.Embed(
            title="🎁 Trial Membership Activated",
            description=(
                "Kamu mendapat akses **Trial** selama **5 hari**.\n\n"
                "Selama trial kamu bisa mencoba fitur premium seperti immersion log, "
                "quiz rank-up, kamus bot, dan member area."
            ),
            color=discord.Color.blurple(),
        )
        if expires_ts:
            dm_embed.add_field(name="Expires", value=f"<t:{expires_ts}:F>")
        dm_embed.add_field(name="Progress Lifetime", value="0 poin — trial tidak menambah lifetime", inline=False)
        await _send_dm(user.id, self.bot, dm_embed)

        await interaction.followup.send(
            f"✅ Trial granted → {user.mention}\n"
            + (f"Expires: <t:{expires_ts}:R>" if expires_ts else ""),
            ephemeral=True,
        )

    # ----------------------------------------------------------
    # /admin grant-batch
    # ----------------------------------------------------------

    @admin_group.command(name="grant-batch", description="Grant membership ke banyak user sekaligus.")
    @discord.app_commands.describe(
        users="Mention user (@User1 @User2 ...).",
        product_id="ID produk.",
        quantity="Jumlah bulan.",
    )
    @discord.app_commands.guild_only()
    async def grant_batch(
        self,
        interaction: discord.Interaction,
        users: str,
        product_id: str,
        quantity: int = 1,
    ):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not _can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        product = self.loader.get(product_id)
        if not product:
            return await interaction.followup.send(
                f"❌ Produk `{product_id}` tidak ditemukan.", ephemeral=True
            )

        import re
        ids = re.findall(r"<@!?(\d+)>", users)
        if not ids:
            return await interaction.followup.send(
                "❌ Tidak ada mention valid. Gunakan @User.", ephemeral=True
            )

        grant_payload = product.build_grant_payload(quantity)
        success_list, fail_list = [], []

        async with MEMBERSHIP_LOCK:
            for uid_str in ids:
                uid = int(uid_str)
                try:
                    # Trial: validasi dulu
                    if product_id == "trial":
                        eligible, reason = await self.svc.can_take_trial(interaction.guild_id, uid)
                        if not eligible:
                            fail_list.append(f"<@{uid}> — {reason}")
                            continue
                        result_svc = await self.svc.grant_trial(
                            guild_id=interaction.guild_id,
                            user_id=uid,
                            actor=interaction.user.id,
                        )
                        from lib.grants.engine import ApplyResult as AR
                        result = AR()
                        result.membership = result_svc
                    else:
                        result = await self.engine.apply(
                            guild_id=interaction.guild_id,
                            user_id=uid,
                            grant_payload=grant_payload,
                            actor=interaction.user.id,
                            source="admin",
                        )
                        if not result.success:
                            fail_list.append(f"<@{uid}> — {result.errors}")
                            continue

                    target = interaction.guild.get_member(uid)
                    name   = target.name if target else f"User {uid}"

                    await _apply_discord_role(interaction.guild, uid, result)
                    dm_embed = _build_grant_dm_embed(result, product.name)
                    await _send_dm(uid, self.bot, dm_embed)

                    label = name + (" 👑 LIFETIME" if result.is_lifetime else "")
                    success_list.append(label)

                except discord.NotFound:
                    fail_list.append(f"<@{uid}> — tidak ditemukan")
                except Exception as e:
                    fail_list.append(f"<@{uid}> — {e}")
                    _log.exception("Batch grant error uid %s", uid)

        summary = discord.Embed(title="✅ Batch Grant Complete", color=discord.Color.green())
        if success_list:
            summary.add_field(
                name=f"Berhasil ({len(success_list)})",
                value="\n".join(f"✅ {n}" for n in success_list)[:1024],
                inline=False,
            )
        if fail_list:
            summary.add_field(
                name=f"Gagal ({len(fail_list)})",
                value="\n".join(f"❌ {n}" for n in fail_list)[:1024],
                inline=False,
            )
        summary.add_field(name="Produk", value=product.name, inline=True)
        summary.add_field(name="Total", value=f"{len(success_list)}/{len(ids)}", inline=True)
        await interaction.followup.send(embed=summary, ephemeral=True)

    # ----------------------------------------------------------
    # /admin revoke-member
    # ----------------------------------------------------------

    @admin_group.command(name="revoke-member", description="Cabut membership dari user.")
    @discord.app_commands.describe(user="User yang mau di-revoke.")
    @discord.app_commands.guild_only()
    async def revoke_member(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not _can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        async with MEMBERSHIP_LOCK:
            try:
                revoke_result = await self.svc.revoke(
                    guild_id=interaction.guild_id,
                    user_id=user.id,
                    actor=interaction.user.id,
                    reason="Manual revoke by admin",
                )
            except ValueError as e:
                return await interaction.followup.send(f"❌ {e}", ephemeral=True)

        # Cabut Discord role
        target = interaction.guild.get_member(user.id)
        if target:
            resolver = RoleResolver(interaction.guild)
            try:
                await resolver.remove_tier(target, revoke_result.tier)
            except Exception as e:
                _log.error("Gagal cabut role dari %d: %s", user.id, e)

        # DM ke user
        dm_embed = discord.Embed(
            title="⚠️ Membership Revoked",
            description="Membership kamu telah dihapus dan role dicabut.",
            color=discord.Color.red(),
        )
        dm_embed.add_field(
            name="Info",
            value=f"Progress lifetime kamu (**{_fmt_progress(revoke_result.membership_before.point_count)}**) tetap tersimpan.",
            inline=False,
        )
        await _send_dm(user.id, self.bot, dm_embed)

        await interaction.followup.send(
            f"✅ Membership revoked → {user.mention}", ephemeral=True
        )

    # ----------------------------------------------------------
    # /admin check-member
    # ----------------------------------------------------------

    @admin_group.command(name="check-member", description="Cek status membership user.")
    @discord.app_commands.describe(user="User yang mau dicek.")
    @discord.app_commands.guild_only()
    async def check_member(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)

        row = await self.svc.get_membership(interaction.guild_id, user.id)
        if not row:
            return await interaction.followup.send(
                f"❌ {user.mention} tidak punya membership.", ephemeral=True
            )

        if row.is_lifetime:
            color      = discord.Color.gold()
            status_str = "👑 LIFETIME MEMBER"
        elif row.is_active:
            color      = discord.Color.green()
            status_str = "✅ Active"
        else:
            color      = discord.Color.red()
            status_str = "❌ Inactive / Expired"

        embed = discord.Embed(title=f"Membership Status — {user.name}", color=color)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Status",  value=status_str,   inline=False)
        embed.add_field(name="Tier",    value=row.tier,     inline=True)
        embed.add_field(name="Source",  value=row.source or "—", inline=True)

        granted_ts = int(row.granted_at.timestamp()) if row.granted_at else 0
        embed.add_field(name="Granted", value=f"<t:{granted_ts}:F>", inline=True)

        if row.is_lifetime:
            embed.add_field(name="Expires",           value="Tidak pernah ♾️",  inline=True)
            embed.add_field(name="Progress Lifetime", value=f"{row.point_count}/{get_lifetime_threshold()} ✅", inline=True)
        else:
            if row.expires_at:
                expires_ts = int(row.expires_at.timestamp())
                embed.add_field(name="Expires",        value=f"<t:{expires_ts}:F>", inline=True)
                embed.add_field(name="Time Remaining", value=f"<t:{expires_ts}:R>", inline=True)
            embed.add_field(
                name="Progress Lifetime",
                value=_fmt_progress(row.point_count),
                inline=False,
            )

        if row.granted_by:
            granter = self.bot.get_user(row.granted_by)
            embed.add_field(
                name="Granted By",
                value=granter.mention if granter else f"User {row.granted_by}",
                inline=True,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ----------------------------------------------------------
    # /admin membership-history
    # ----------------------------------------------------------

    @admin_group.command(name="membership-history", description="Lihat history grant/revoke membership.")
    @discord.app_commands.describe(user="Filter berdasarkan user (opsional).")
    @discord.app_commands.guild_only()
    async def membership_history(
        self, interaction: discord.Interaction, user: Optional[discord.User] = None
    ):
        await interaction.response.defer(ephemeral=True)

        uid     = user.id if user else None
        results = await self.svc.get_history(interaction.guild_id, uid, limit=25)

        if not results:
            return await interaction.followup.send("Tidak ada history membership.", ephemeral=True)

        emoji_map = {
            "trial_claimed":       "🎁",
            "membership_extended": "✅",
            "membership_expired":  "⌛",
            "patron_granted":      "👑",
            "admin_grant":         "✅",
            "admin_revoke":        "❌",
            "purchase_approved":   "🛒",
            "purchase_rejected":   "🚫",
            "class_granted":       "📚",
            "auto_patron":         "👑",
            # legacy
            "grant":               "✅",
            "revoke":              "❌",
            "warned_expiry":       "⚠️",
            "trial_expired":       "⌛",
            "lifetime_unlocked":   "👑",
        }

        embed = discord.Embed(title="Membership History", color=discord.Color.blue())

        for row in results:
            (
                _id, guild_id, user_id, event,
                tier_before, tier_after,
                expiry_before, expiry_after,
                point_before, point_after,
                order_id, actor, reason, created_at
            ) = row

            ts    = int(datetime.fromisoformat(created_at).timestamp())
            emoji = emoji_map.get(event, "•")

            try:
                tu    = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                uname = tu.name
            except Exception:
                uname = f"User {user_id}"

            tier_str = f"{tier_before or '—'} → {tier_after or '—'}"
            val      = f"{emoji} **{event.upper()}**\nTier: {tier_str}\n<t:{ts}:F>"
            if reason:
                val += f"\n_{reason}_"

            embed.add_field(name=uname, value=val, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ----------------------------------------------------------
    # /admin membership-purge-history
    # ----------------------------------------------------------

    @admin_group.command(
        name="membership-purge-history",
        description="Hapus history membership user (admin only).",
    )
    @discord.app_commands.describe(user="User yang history-nya mau dihapus.")
    @discord.app_commands.guild_only()
    async def membership_purge_history(
        self, interaction: discord.Interaction, user: discord.User
    ):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send(
                "❌ Hanya admin yang bisa purge history.", ephemeral=True
            )

        await self.bot.RUN(
            "DELETE FROM membership_history_v1 WHERE guild_id = ? AND user_id = ?",
            (interaction.guild_id, user.id),
        )
        await interaction.followup.send(
            f"✅ History membership {user.mention} telah dihapus.", ephemeral=True
        )

    # ----------------------------------------------------------
    # /membership sync
    # ----------------------------------------------------------

    @discord.app_commands.command(
        name="membership_sync",
        description="Sinkronisasi Discord role dengan database membership (Admin).",
    )
    @discord.app_commands.default_permissions(administrator=True)
    @discord.app_commands.guild_only()
    async def membership_sync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not _can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        guild    = interaction.guild
        resolver = RoleResolver(guild)
        fixed    = 0
        errors   = 0

        # Ambil semua member guild
        async for m in guild.fetch_members(limit=None):
            if m.bot:
                continue
            try:
                row = await self.svc.get_membership(guild.id, m.id)
                tier      = row.tier      if row else None
                is_active = row.is_active if row else False
                changes   = await resolver.sync_member(m, tier, is_active)
                if changes["added"] or changes["removed"]:
                    fixed += 1
            except Exception as e:
                _log.error("Sync error untuk member %d: %s", m.id, e)
                errors += 1

        await interaction.followup.send(
            f"✅ Sync selesai.\n"
            f"Diperbaiki: **{fixed}** member\n"
            f"Error: **{errors}** member",
            ephemeral=True,
        )

    # ============================================================
    # BACKGROUND TASK — EXPIRY CHECK
    # ============================================================

    @tasks.loop(minutes=30)
    async def membership_expiry_check(self):
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return

            now            = utcnow().replace(tzinfo=None)
            warn_threshold = now + timedelta(days=GRACE_PERIOD_DAYS)

            # --------------------------------------------------------
            # FASE 1 — Warning H-3 (paid member saja, bukan trial)
            # --------------------------------------------------------
            expiring = await self.svc.get_expiring_soon(guild.id, warn_threshold, now)
            for row in expiring:
                if row.tier == "trial":
                    continue

                # Cek apakah sudah pernah dikirim warning hari ini
                warned_today = await self.bot.GET_ONE(
                    """
                    SELECT id FROM membership_history_v1
                    WHERE guild_id=? AND user_id=? AND event='warned_expiry'
                    AND created_at > ?
                    """,
                    (guild.id, row.user_id, (now - timedelta(hours=23)).isoformat()),
                )
                if warned_today:
                    continue

                expires_ts = int(row.expires_at.timestamp()) if row.expires_at else 0
                embed = discord.Embed(
                    title="⏰ Membership Expiry Warning",
                    description=f"Membership kamu akan expired dalam **{GRACE_PERIOD_DAYS} hari**.",
                    color=discord.Color.orange(),
                )
                embed.add_field(name="Tier",    value=row.tier, inline=True)
                embed.add_field(name="Expires", value=f"<t:{expires_ts}:F>", inline=True)
                embed.add_field(
                    name="Progress Lifetime",
                    value=_fmt_progress(row.point_count),
                    inline=False,
                )
                embed.add_field(name="Action", value="Hubungi admin untuk renewal.", inline=False)

                await _send_dm(row.user_id, self.bot, embed)
                await self.bot.RUN(
                    """
                    INSERT INTO membership_history_v1
                    (guild_id, user_id, event, tier_after, created_at)
                    VALUES (?, ?, 'warned_expiry', ?, ?)
                    """,
                    (guild.id, row.user_id, row.tier, now.isoformat()),
                )

            # --------------------------------------------------------
            # FASE 2 — Expired (semua tier termasuk trial)
            # --------------------------------------------------------
            expired = await self.svc.get_expired(guild.id, now)
            for row in expired:
                try:
                    await self.svc.expire_membership(guild.id, row.user_id)

                    target = guild.get_member(row.user_id)
                    if target:
                        resolver = RoleResolver(guild)
                        await resolver.remove_tier(target, row.tier)

                    if row.tier == "trial":
                        embed = discord.Embed(
                            title="⏰ Trial Guest Kamu Sudah Berakhir",
                            description=(
                                "Masa preview 5 hari kamu sudah selesai dan akses premium sudah dicabut.\n\n"
                                "Suka dengan fiturnya? Lanjutkan dengan:\n"
                                "🎒 Traveler — Rp40.000/bulan\n"
                                "🤝 Companion — Rp80.000/bulan\n\n"
                                "Hubungi admin untuk upgrade!"
                            ),
                            color=discord.Color.orange(),
                        )
                    else:
                        embed = discord.Embed(
                            title="⚠️ Membership Expired",
                            description="Membership kamu telah berakhir dan role sudah dicabut.",
                            color=discord.Color.red(),
                        )
                        embed.add_field(
                            name="Next Steps",
                            value="Hubungi admin jika ingin renewal.",
                            inline=False,
                        )
                        embed.add_field(
                            name="Progress Lifetime",
                            value=_fmt_progress(row.point_count),
                            inline=False,
                        )

                    await _send_dm(row.user_id, self.bot, embed)
                    _log.info("Auto-expired membership user %s tier %s", row.user_id, row.tier)

                except Exception as e:
                    _log.error("Gagal expire membership user %d: %s", row.user_id, e)

        except Exception as e:
            _log.exception("Error di membership_expiry_check: %s", e)

    @membership_expiry_check.before_loop
    async def before_expiry_check(self):
        await self.bot.wait_until_ready()


# ============================================================
# SETUP
# ============================================================

async def setup(bot: KotabiBot):
    await bot.add_cog(Membership(bot))