"""
features/membership/scheduler_cog.py — Membership Scheduler v1
=======================================================
Background tasks yang berjalan otomatis:

  Task 1 (setiap 30 menit) — sudah ada di admin_cog.py:
    - Membership expiry check
    - Warning H-3
    - Auto revoke expired

  Task 2 (setiap 6 jam) — di sini:
    - Pending order cleanup
      → Order pending > 3 hari → notif staff
      → Order pending > 7 hari → auto-cancel + notif user

  Task 3 (setiap 24 jam) — di sini:
    - Role sync
      → Bandingkan Discord role dengan database
      → Perbaiki yang tidak sinkron secara diam-diam
      → Log hasilnya
"""

import logging
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord.utils import utcnow

from core.bot import KotabiBot
from shared.config import get_membership_guild_id, get_order_review_channel_id
from features.membership.support.repository import MembershipRepository
from features.membership.support.role_resolver import RoleResolver
from features.membership.support.service import MembershipService

_log = logging.getLogger("bot.membership_scheduler")

# ============================================================
# KONFIGURASI
# ============================================================
# guild_id & channel review order dibaca lewat shared/config.py (single source
# of truth untuk membership_settings.yml), bukan baca ulang YAML sendiri di
# file ini.

GUILD_ID        = get_membership_guild_id()
ORDER_REVIEW_CH = get_order_review_channel_id()

# Order pending lebih dari ini → notif staff
PENDING_WARN_DAYS   = 3

# Order pending lebih dari ini → auto-cancel
PENDING_CANCEL_DAYS = 7


# ============================================================
# HELPER
# ============================================================

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


# ============================================================
# COG
# ============================================================

class MembershipScheduler(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot  = bot
        self.svc  = MembershipService(bot)
        self.repo = MembershipRepository(bot)

    async def cog_load(self):
        if not self.pending_order_check.is_running():
            self.pending_order_check.start()
        if not self.role_sync_check.is_running():
            self.role_sync_check.start()
        _log.info("MembershipScheduler tasks started.")

    def cog_unload(self):
        self.pending_order_check.cancel()
        self.role_sync_check.cancel()

    # ============================================================
    # TASK 2 — Pending Order Cleanup (setiap 6 jam)
    # ============================================================

    @tasks.loop(hours=6)
    async def pending_order_check(self):
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return

            now           = utcnow().replace(tzinfo=None)
            warn_threshold   = now - timedelta(days=PENDING_WARN_DAYS)
            cancel_threshold = now - timedelta(days=PENDING_CANCEL_DAYS)

            pending_orders = await self.repo.get_pending_orders(GUILD_ID)
            if not pending_orders:
                return

            review_ch = guild.get_channel(ORDER_REVIEW_CH)

            for order in pending_orders:
                created_at = order.created_at
                if not created_at:
                    continue

                # AUTO-CANCEL: pending > 7 hari
                if created_at < cancel_threshold:
                    await self.repo.update_order_status(
                        order_id=order.order_id,
                        status="cancelled",
                        notes=f"Auto-cancelled setelah {PENDING_CANCEL_DAYS} hari tidak diproses.",
                    )

                    # DM ke user
                    dm_embed = discord.Embed(
                        title="🚫 Order Otomatis Dibatalkan",
                        description=(
                            f"Order **{order.product_name}** kamu (#{order.order_id}) "
                            f"telah otomatis dibatalkan karena tidak diproses selama "
                            f"**{PENDING_CANCEL_DAYS} hari**."
                        ),
                        color=discord.Color.light_grey()
                    )
                    dm_embed.add_field(
                        name="Info",
                        value="Buat order baru atau hubungi admin jika ada pertanyaan.",
                        inline=False,
                    )
                    await _send_dm(order.user_id, self.bot, dm_embed)

                    # Notif staff
                    if review_ch:
                        created_ts = int(created_at.timestamp())
                        await review_ch.send(
                            f"⚠️ Order **#{order.order_id}** dari <@{order.user_id}> "
                            f"(`{order.product_name}`) otomatis dibatalkan karena pending "
                            f"sejak <t:{created_ts}:R>."
                        )

                    _log.info(
                        "Auto-cancelled order #%d (pending since %s)",
                        order.order_id, created_at
                    )

                # WARN STAFF: pending > 3 hari (tapi belum 7 hari)
                elif created_at < warn_threshold:
                    # Cek apakah sudah pernah diingatkan hari ini
                    already_warned = await self.bot.GET_ONE(
                        """
                        SELECT 1 FROM membership_history_v1
                        WHERE event = 'order_pending_warned'
                          AND reason = ?
                          AND created_at > ?
                        """,
                        (
                            str(order.order_id),
                            (now - timedelta(hours=23)).isoformat(),
                        ),
                    )
                    if already_warned:
                        continue

                    if review_ch:
                        created_ts = int(created_at.timestamp())
                        await review_ch.send(
                            f"⏰ **Reminder:** Order **#{order.order_id}** dari "
                            f"<@{order.user_id}> (`{order.product_name}`) sudah pending "
                            f"sejak <t:{created_ts}:R>. Harap segera diproses."
                        )

                    # Catat supaya tidak spam
                    await self.bot.RUN(
                        """
                        INSERT INTO membership_history_v1
                        (guild_id, user_id, event, reason, created_at)
                        VALUES (?, ?, 'order_pending_warned', ?, ?)
                        """,
                        (
                            GUILD_ID,
                            order.user_id,
                            str(order.order_id),
                            now.isoformat(),
                        ),
                    )

                    _log.info(
                        "Warned staff about pending order #%d", order.order_id
                    )

        except Exception as e:
            _log.exception("Error di pending_order_check: %s", e)

    @pending_order_check.before_loop
    async def before_pending_check(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # TASK 3 — Role Sync (setiap 24 jam)
    # ============================================================

    @tasks.loop(hours=24)
    async def role_sync_check(self):
        """
        Sinkronisasi diam-diam Discord role dengan database.
        Tidak mengirim notif ke user — hanya log.
        Kalau ada yang tidak sinkron, perbaiki otomatis.
        """
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return

            resolver = RoleResolver(guild)
            fixed    = 0
            errors   = 0
            total    = 0

            async for member in guild.fetch_members(limit=None):
                if member.bot:
                    continue

                total += 1
                try:
                    row       = await self.svc.get_membership(guild.id, member.id)
                    tier      = row.tier      if row else None
                    is_active = row.is_active if row else False
                    changes   = await resolver.sync_member(member, tier, is_active)

                    if changes["added"] or changes["removed"]:
                        fixed += 1
                        _log.info(
                            "Role sync fixed: %s (%d) +%s -%s",
                            member.name, member.id,
                            changes["added"], changes["removed"]
                        )
                except Exception as e:
                    errors += 1
                    _log.error("Role sync error untuk %d: %s", member.id, e)

            _log.info(
                "Role sync selesai: %d member diperiksa, %d diperbaiki, %d error",
                total, fixed, errors
            )

        except Exception as e:
            _log.exception("Error di role_sync_check: %s", e)

    @role_sync_check.before_loop
    async def before_role_sync(self):
        await self.bot.wait_until_ready()
        # Tunda 1 jam setelah bot start supaya tidak bentrok dengan startup
        import asyncio
        await asyncio.sleep(3600)


# ============================================================
# SETUP
# ============================================================

async def setup(bot: KotabiBot):
    await bot.add_cog(MembershipScheduler(bot))