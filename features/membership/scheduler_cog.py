"""
features/membership/scheduler_cog.py — Membership Scheduler v1
=======================================================
Background tasks yang berjalan otomatis:

  Task 1 (setiap 1 jam) — di sini:
    - Draft timeout
      → Draft (status='draft') yang belum dikonfirmasi user dalam
        24 jam → auto-cancelled + notif user

  Task 2 (setiap 30 menit) — sudah ada di admin_cog.py:
    - Membership expiry check
    - Warning H-3
    - Auto revoke expired

  Task 3 (setiap 6 jam) — di sini:
    - Pending order cleanup
      → Order pending > 3 hari → notif staff
      → Order pending > 7 hari → auto-cancel + notif user

  Task 4 (setiap 24 jam) — di sini:
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
from features.membership.support.models import HistoryEvent
from features.membership.support.helpers import send_dm as _send_dm

_log = logging.getLogger("bot.membership_scheduler")

# ============================================================
# KONFIGURASI
# ============================================================
# guild_id & channel review order dibaca lewat shared/config.py (single source
# of truth untuk membership_settings.yml), bukan baca ulang YAML sendiri di
# file ini.

GUILD_ID        = get_membership_guild_id()
ORDER_REVIEW_CH = get_order_review_channel_id()

# Draft (belum dikonfirmasi user) lebih lama dari ini → auto-cancel
DRAFT_TIMEOUT_HOURS = 24

# Order pending lebih dari ini → notif staff
PENDING_WARN_DAYS   = 3

# Order pending lebih dari ini → auto-cancel
PENDING_CANCEL_DAYS = 7

# ============================================================
# COG
# ============================================================

class MembershipScheduler(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot  = bot
        self.svc  = MembershipService(bot)
        self.repo = MembershipRepository(bot)

    async def cog_load(self):
        if not self.draft_timeout_check.is_running():
            self.draft_timeout_check.start()
        if not self.pending_order_check.is_running():
            self.pending_order_check.start()
        if not self.role_sync_check.is_running():
            self.role_sync_check.start()
        _log.info("MembershipScheduler tasks started.")

    def cog_unload(self):
        self.draft_timeout_check.cancel()
        self.pending_order_check.cancel()
        self.role_sync_check.cancel()

    # ============================================================
    # TASK 1 — Draft Timeout (setiap 1 jam)
    # ============================================================
    # Draft yang dibuat >24 jam lalu dan belum pernah dikonfirmasi user
    # (belum klik "Konfirmasi Order") -> auto-cancelled. Lihat
    # KOTABI_MEMBERSHIP_SYSTEM_v3.md bagian "Draft Timeout".
    #
    # Sengaja HANYA menyasar status='draft' murni, BUKAN 'needs_resubmit' —
    # order yang sedang menunggu upload ulang bukti sudah pernah dikonfirmasi
    # sebelumnya dan tidak punya batas waktu 24 jam di desain v3 (lihat
    # catatan di repository.py bagian _GET_DRAFT_ORDERS_OLDER_THAN).

    @tasks.loop(hours=1)
    async def draft_timeout_check(self):
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return

            threshold = utcnow().replace(tzinfo=None) - timedelta(hours=DRAFT_TIMEOUT_HOURS)
            stale_drafts = await self.repo.get_draft_orders_older_than(GUILD_ID, threshold)

            for order in stale_drafts:
                await self.repo.update_order_status(
                    order_id=order.order_id,
                    status="cancelled",
                    notes=f"Auto-expired setelah {DRAFT_TIMEOUT_HOURS} jam tidak dikonfirmasi (draft timeout).",
                )

                dm_embed = discord.Embed(
                    title="⏳ Draft Order Kedaluwarsa",
                    description=(
                        f"Draft order **{order.product_name}** (#{order.order_id}) kamu "
                        f"otomatis dibatalkan karena tidak dikonfirmasi dalam "
                        f"**{DRAFT_TIMEOUT_HOURS} jam**."
                    ),
                    color=discord.Color.light_grey(),
                )
                dm_embed.add_field(
                    name="Info",
                    value="Kalau masih mau lanjut, silakan mulai ulang lewat `/subscribe`.",
                    inline=False,
                )
                await _send_dm(order.user_id, self.bot, dm_embed)

                _log.info(
                    "Auto-expired draft order #%d (draft_created_at=%s)",
                    order.order_id, order.draft_created_at
                )

        except Exception as e:
            _log.exception("Error di draft_timeout_check: %s", e)

    @draft_timeout_check.before_loop
    async def before_draft_timeout(self):
        await self.bot.wait_until_ready()

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
                    already_warned = await self.repo.has_recent_order_warning(
                        order.order_id, now - timedelta(hours=23)
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
                    await self.repo.insert_history(HistoryEvent(
                        guild_id=GUILD_ID, user_id=order.user_id,
                        event="order_pending_warned", reason=str(order.order_id),
                    ))

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

            # 1 query untuk seluruh guild, bukan 1 query per member (fix N+1).
            memberships_by_user = await self.svc.get_all_memberships(guild.id)

            async for member in guild.fetch_members(limit=None):
                if member.bot:
                    continue

                total += 1
                try:
                    row       = memberships_by_user.get(member.id)
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