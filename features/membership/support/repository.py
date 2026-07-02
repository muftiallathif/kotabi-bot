"""
features/membership/support/repository.py — Database Layer Membership System v1
==================================================================================
Semua SQL query ada di sini. Tidak ada logic bisnis.
Dipanggil oleh MembershipService, tidak pernah langsung dari cog.

Penggunaan:
    repo = MembershipRepository(bot)
    row = await repo.get_membership(guild_id, user_id)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from core.bot import KotabiBot
from features.membership.support.models import (
    HistoryEvent,
    MembershipRow,
    Order,
    TrialClaim,
)

_log = logging.getLogger("bot.membership.repository")


# ============================================================
# QUERIES — memberships
# ============================================================

_GET_MEMBERSHIP = """
SELECT
    guild_id, user_id, tier, granted_at, expires_at,
    is_lifetime, active, point_count, granted_by, source
FROM memberships
WHERE guild_id = ? AND user_id = ?;
"""

_UPSERT_MEMBERSHIP = """
INSERT INTO memberships (
    guild_id, user_id, tier, granted_at, expires_at,
    is_lifetime, active, point_count, granted_by, source
)
VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
ON CONFLICT (guild_id, user_id) DO UPDATE SET
    tier        = CASE
        WHEN memberships.is_lifetime = 1 THEN memberships.tier
        ELSE excluded.tier
    END,
    granted_at  = excluded.granted_at,
    expires_at  = CASE
        WHEN memberships.is_lifetime = 1 THEN memberships.expires_at
        ELSE excluded.expires_at
    END,
    is_lifetime = CASE
        WHEN memberships.is_lifetime = 1 THEN 1
        ELSE excluded.is_lifetime
    END,
    active      = 1,
    point_count = CASE
        WHEN memberships.is_lifetime = 1 THEN memberships.point_count
        ELSE excluded.point_count
    END,
    granted_by  = excluded.granted_by,
    source      = excluded.source;
"""

_SET_LIFETIME = """
UPDATE memberships
SET is_lifetime = 1,
    expires_at  = '9999-12-31 23:59:59',
    tier        = 'patron',
    active      = 1
WHERE guild_id = ? AND user_id = ?;
"""

_SET_POINT_COUNT = """
UPDATE memberships
SET point_count = ?
WHERE guild_id = ? AND user_id = ?;
"""

_REVOKE_MEMBERSHIP = """
UPDATE memberships
SET active = 0
WHERE guild_id = ? AND user_id = ? AND is_lifetime = 0;
"""

_GET_EXPIRING_SOON = """
SELECT
    guild_id, user_id, tier, granted_at, expires_at,
    is_lifetime, active, point_count, granted_by, source
FROM memberships
WHERE guild_id   = ?
  AND active     = 1
  AND is_lifetime = 0
  AND tier       != 'trial'
  AND expires_at <= ?
  AND expires_at >  ?;
"""

_GET_EXPIRED = """
SELECT
    guild_id, user_id, tier, granted_at, expires_at,
    is_lifetime, active, point_count, granted_by, source
FROM memberships
WHERE guild_id   = ?
  AND active     = 1
  AND is_lifetime = 0
  AND expires_at <= ?;
"""


# ============================================================
# QUERIES — orders
# ============================================================

_INSERT_ORDER = """
INSERT INTO orders (
    guild_id, user_id, product_key, product_version, product_name,
    price, quantity, total_duration, grant_payload, status, notes, created_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?);
"""

_GET_ORDER = """
SELECT
    order_id, guild_id, user_id, product_key, product_version,
    product_name, price, quantity, total_duration, grant_payload,
    status, notes, created_at, approved_at, approved_by
FROM orders
WHERE order_id = ?;
"""

_GET_PENDING_ORDERS = """
SELECT
    order_id, guild_id, user_id, product_key, product_version,
    product_name, price, quantity, total_duration, grant_payload,
    status, notes, created_at, approved_at, approved_by
FROM orders
WHERE guild_id = ? AND status = 'pending'
ORDER BY created_at ASC;
"""

_GET_USER_ORDERS = """
SELECT
    order_id, guild_id, user_id, product_key, product_version,
    product_name, price, quantity, total_duration, grant_payload,
    status, notes, created_at, approved_at, approved_by
FROM orders
WHERE guild_id = ? AND user_id = ?
ORDER BY created_at DESC
LIMIT ?;
"""

_UPDATE_ORDER_STATUS = """
UPDATE orders
SET status      = ?,
    approved_at = ?,
    approved_by = ?,
    notes       = COALESCE(?, notes)
WHERE order_id = ?;
"""


# ============================================================
# QUERIES — trial_claims
# ============================================================

_GET_TRIAL_CLAIM = """
SELECT user_id, guild_id, trial_cycle, claimed_at
FROM trial_claims
WHERE user_id = ? AND guild_id = ? AND trial_cycle = ?;
"""

_INSERT_TRIAL_CLAIM = """
INSERT OR IGNORE INTO trial_claims (user_id, guild_id, trial_cycle, claimed_at)
VALUES (?, ?, ?, ?);
"""


# ============================================================
# QUERIES — membership_history_v1
# ============================================================

_INSERT_HISTORY = """
INSERT INTO membership_history_v1 (
    guild_id, user_id, event,
    tier_before, tier_after,
    expiry_before, expiry_after,
    point_before, point_after,
    order_id, actor, reason, created_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

_GET_HISTORY = """
SELECT
    id, guild_id, user_id, event,
    tier_before, tier_after,
    expiry_before, expiry_after,
    point_before, point_after,
    order_id, actor, reason, created_at
FROM membership_history_v1
WHERE guild_id = ? AND (? IS NULL OR user_id = ?)
ORDER BY created_at DESC
LIMIT ?;
"""


# ============================================================
# REPOSITORY CLASS
# ============================================================

class MembershipRepository:
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    # ----------------------------------------------------------
    # MEMBERSHIPS
    # ----------------------------------------------------------

    async def get_membership(
        self, guild_id: int, user_id: int
    ) -> Optional[MembershipRow]:
        row = await self.bot.GET_ONE(_GET_MEMBERSHIP, (guild_id, user_id))
        if not row:
            return None
        return MembershipRow.from_row(row)

    async def upsert_membership(
        self,
        guild_id:    int,
        user_id:     int,
        tier:        str,
        granted_at:  datetime,
        expires_at:  Optional[datetime],
        is_lifetime: bool,
        point_count: int,
        granted_by:  Optional[int],
        source:      str,
    ) -> None:
        await self.bot.RUN(
            _UPSERT_MEMBERSHIP,
            (
                guild_id, user_id, tier,
                granted_at.isoformat(),
                expires_at.isoformat() if expires_at else None,
                int(is_lifetime),
                point_count,
                granted_by,
                source,
            )
        )

    async def set_lifetime(self, guild_id: int, user_id: int) -> None:
        await self.bot.RUN(_SET_LIFETIME, (guild_id, user_id))

    async def set_point_count(
        self, guild_id: int, user_id: int, point_count: int
    ) -> None:
        await self.bot.RUN(_SET_POINT_COUNT, (point_count, guild_id, user_id))

    async def revoke_membership(self, guild_id: int, user_id: int) -> None:
        await self.bot.RUN(_REVOKE_MEMBERSHIP, (guild_id, user_id))

    async def get_expiring_soon(
        self, guild_id: int, threshold: datetime, now: datetime
    ) -> list[MembershipRow]:
        rows = await self.bot.GET(
            _GET_EXPIRING_SOON,
            (guild_id, threshold.isoformat(), now.isoformat())
        )
        return [MembershipRow.from_row(r) for r in rows]

    async def get_expired(
        self, guild_id: int, now: datetime
    ) -> list[MembershipRow]:
        rows = await self.bot.GET(_GET_EXPIRED, (guild_id, now.isoformat()))
        return [MembershipRow.from_row(r) for r in rows]

    # ----------------------------------------------------------
    # ORDERS
    # ----------------------------------------------------------

    async def create_order(
        self,
        guild_id:        int,
        user_id:         int,
        product_key:     str,
        product_version: str,
        product_name:    str,
        price:           int,
        quantity:        int,
        total_duration:  Optional[int],
        grant_payload:   dict,
        notes:           Optional[str] = None,
    ) -> int:
        """Return order_id yang baru dibuat."""
        now = datetime.utcnow()
        await self.bot.RUN(
            _INSERT_ORDER,
            (
                guild_id, user_id, product_key, product_version, product_name,
                price, quantity, total_duration,
                json.dumps(grant_payload, ensure_ascii=False),
                notes,
                now.isoformat(),
            )
        )
        # Ambil order_id yang baru saja dibuat
        row = await self.bot.GET_ONE(
            "SELECT order_id FROM orders WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 1",
            (guild_id, user_id)
        )
        return row[0] if row else -1

    async def get_order(self, order_id: int) -> Optional[Order]:
        row = await self.bot.GET_ONE(_GET_ORDER, (order_id,))
        if not row:
            return None
        return Order.from_row(row)

    async def get_pending_orders(self, guild_id: int) -> list[Order]:
        rows = await self.bot.GET(_GET_PENDING_ORDERS, (guild_id,))
        return [Order.from_row(r) for r in rows]

    async def get_user_orders(
        self, guild_id: int, user_id: int, limit: int = 10
    ) -> list[Order]:
        rows = await self.bot.GET(_GET_USER_ORDERS, (guild_id, user_id, limit))
        return [Order.from_row(r) for r in rows]

    async def update_order_status(
        self,
        order_id:    int,
        status:      str,
        approved_by: Optional[int] = None,
        notes:       Optional[str] = None,
    ) -> None:
        now = datetime.utcnow() if status == "approved" else None
        await self.bot.RUN(
            _UPDATE_ORDER_STATUS,
            (
                status,
                now.isoformat() if now else None,
                approved_by,
                notes,
                order_id,
            )
        )

    # ----------------------------------------------------------
    # TRIAL CLAIMS
    # ----------------------------------------------------------

    async def get_trial_claim(
        self, user_id: int, guild_id: int, trial_cycle: str
    ) -> Optional[TrialClaim]:
        row = await self.bot.GET_ONE(
            _GET_TRIAL_CLAIM, (user_id, guild_id, trial_cycle)
        )
        if not row:
            return None
        return TrialClaim.from_row(row)

    async def insert_trial_claim(
        self, user_id: int, guild_id: int, trial_cycle: str
    ) -> None:
        now = datetime.utcnow()
        await self.bot.RUN(
            _INSERT_TRIAL_CLAIM,
            (user_id, guild_id, trial_cycle, now.isoformat())
        )

    # ----------------------------------------------------------
    # HISTORY
    # ----------------------------------------------------------

    async def insert_history(self, event: HistoryEvent) -> None:
        now = datetime.utcnow()
        await self.bot.RUN(
            _INSERT_HISTORY,
            (
                event.guild_id,
                event.user_id,
                event.event,
                event.tier_before,
                event.tier_after,
                event.expiry_before.isoformat() if event.expiry_before else None,
                event.expiry_after.isoformat()  if event.expiry_after  else None,
                event.point_before,
                event.point_after,
                event.order_id,
                event.actor,
                event.reason,
                now.isoformat(),
            )
        )

    async def get_history(
        self,
        guild_id: int,
        user_id:  Optional[int] = None,
        limit:    int = 50,
    ) -> list[tuple]:
        rows = await self.bot.GET(
            _GET_HISTORY,
            (guild_id, user_id, user_id, limit)
        )
        return rows