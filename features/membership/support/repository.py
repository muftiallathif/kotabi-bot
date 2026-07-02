"""
features/membership/support/repository.py — Database Layer Membership System v2
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
# QUERIES — orders (schema v2, lihat migrations/v2_purchase_flow.sql)
# ============================================================

_ORDER_COLUMNS = """
    order_id, guild_id, user_id, product_key, product_version,
    product_name, price, quantity, total_duration, grant_payload,
    status, unique_code, payment_proof_url, sender_bank, payment_phash,
    reject_reason_type, notes, draft_created_at, confirmed_at,
    created_at, approved_at, approved_by
"""

_INSERT_DRAFT_ORDER = f"""
INSERT INTO orders (
    guild_id, user_id, product_key, product_version, product_name,
    price, quantity, total_duration, grant_payload, status,
    draft_created_at, created_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?);
"""

_SET_UNIQUE_CODE = """
UPDATE orders SET unique_code = ? WHERE order_id = ?;
"""

_ATTACH_PAYMENT_PROOF = """
UPDATE orders
SET payment_proof_url = ?,
    sender_bank       = ?,
    payment_phash     = ?
WHERE order_id = ?;
"""

_CONFIRM_ORDER = """
UPDATE orders
SET status = 'pending',
    confirmed_at = ?
WHERE order_id = ? AND status IN ('draft', 'needs_resubmit');
"""

_MARK_NEEDS_RESUBMIT = """
UPDATE orders
SET status = 'needs_resubmit',
    reject_reason_type = 'invalid_proof',
    notes = ?
WHERE order_id = ?;
"""

_GET_ORDER = f"""
SELECT {_ORDER_COLUMNS}
FROM orders
WHERE order_id = ?;
"""

_GET_PENDING_ORDERS = f"""
SELECT {_ORDER_COLUMNS}
FROM orders
WHERE guild_id = ? AND status = 'pending'
ORDER BY confirmed_at ASC;
"""

_GET_NEEDS_RESUBMIT_ORDERS = f"""
SELECT {_ORDER_COLUMNS}
FROM orders
WHERE guild_id = ? AND status = 'needs_resubmit'
ORDER BY confirmed_at ASC;
"""

# FIX (draft timeout): dulu query ini menyaring status IN ('draft',
# 'needs_resubmit'), padahal draft_created_at TIDAK di-refresh saat order
# pindah ke needs_resubmit (lihat mark_needs_resubmit() di bawah — hanya
# status/reject_reason_type/notes yang berubah). Akibatnya order yang baru
# saja di-reject "bukti tidak valid" dan diminta upload ulang bisa langsung
# auto-cancelled oleh draft_timeout_check kalau draft_created_at aslinya
# sudah lewat 24 jam, padahal user baru saja dapat DM "upload ulang".
#
# KOTABI_MEMBERSHIP_SYSTEM_v3.md bagian "Draft Timeout" hanya mendefinisikan
# batas 24 jam untuk draft yang BELUM PERNAH dikonfirmasi sama sekali —
# bukan untuk order yang sudah masuk ke jalur resubmit. Maka query ini
# sekarang hanya menyaring status = 'draft'.
_GET_DRAFT_ORDERS_OLDER_THAN = f"""
SELECT {_ORDER_COLUMNS}
FROM orders
WHERE guild_id = ? AND status = 'draft' AND draft_created_at < ?;
"""

_GET_USER_ORDERS = f"""
SELECT {_ORDER_COLUMNS}
FROM orders
WHERE guild_id = ? AND user_id = ?
ORDER BY created_at DESC
LIMIT ?;
"""

_GET_USER_DRAFT_ORDER = f"""
SELECT {_ORDER_COLUMNS}
FROM orders
WHERE guild_id = ? AND user_id = ? AND status IN ('draft', 'needs_resubmit')
ORDER BY created_at DESC
LIMIT 1;
"""

_UPDATE_ORDER_STATUS = """
UPDATE orders
SET status              = ?,
    approved_at         = ?,
    approved_by         = ?,
    reject_reason_type  = ?,
    notes               = COALESCE(?, notes)
WHERE order_id = ?;
"""

_GET_OTHER_PAYMENT_PHASHES = """
SELECT order_id, payment_phash
FROM orders
WHERE guild_id = ?
  AND order_id != ?
  AND payment_phash IS NOT NULL;
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
    # ORDERS — draft lifecycle
    # ----------------------------------------------------------

    async def create_draft_order(
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
    ) -> int:
        """
        Buat order baru dengan status 'draft' dan langsung isi unique_code
        (order_id mod 100, lihat KOTABI_MEMBERSHIP_SYSTEM_v3.md bagian
        "Kode Unik Nominal"). Return order_id yang baru dibuat.

        Order di status draft ini murni draft privat milik user — belum
        masuk ke channel staff (baru masuk setelah confirm_order dipanggil).
        """
        now = datetime.utcnow()
        await self.bot.RUN(
            _INSERT_DRAFT_ORDER,
            (
                guild_id, user_id, product_key, product_version, product_name,
                price, quantity, total_duration,
                json.dumps(grant_payload, ensure_ascii=False),
                now.isoformat(),
                now.isoformat(),
            )
        )
        row = await self.bot.GET_ONE(
            "SELECT order_id FROM orders WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 1",
            (guild_id, user_id)
        )
        order_id = row[0] if row else -1
        if order_id != -1:
            await self.bot.RUN(_SET_UNIQUE_CODE, (order_id % 100, order_id))
        return order_id

    async def attach_payment_proof(
        self,
        order_id:          int,
        payment_proof_url: str,
        sender_bank:       Optional[str],
        payment_phash:     Optional[str],
    ) -> None:
        """Simpan bukti transfer + bank pengirim + pHash ke order (masih draft/needs_resubmit)."""
        await self.bot.RUN(
            _ATTACH_PAYMENT_PROOF,
            (payment_proof_url, sender_bank, payment_phash, order_id)
        )

    async def confirm_order(self, order_id: int) -> None:
        """
        draft/needs_resubmit -> pending. Titik inilah order pertama kali
        (atau kembali) masuk ke antrian review staff.
        """
        now = datetime.utcnow()
        await self.bot.RUN(_CONFIRM_ORDER, (now.isoformat(), order_id))

    async def mark_needs_resubmit(self, order_id: int, reason: Optional[str]) -> None:
        """
        Reject jalur A ("Bukti tidak valid/buram") — order TIDAK final ditolak.
        Sengaja TIDAK menyentuh draft_created_at — draft timeout hanya berlaku
        untuk draft yang belum pernah dikonfirmasi sama sekali, bukan untuk
        order yang sudah masuk jalur resubmit (lihat catatan di
        _GET_DRAFT_ORDERS_OLDER_THAN di atas).
        """
        await self.bot.RUN(_MARK_NEEDS_RESUBMIT, (reason, order_id))

    async def get_draft_orders_older_than(
        self, guild_id: int, threshold: datetime
    ) -> list[Order]:
        """Draft murni (status='draft', belum pernah dikonfirmasi) yang dibuat
        sebelum `threshold` — untuk auto-expire 24 jam."""
        rows = await self.bot.GET(
            _GET_DRAFT_ORDERS_OLDER_THAN, (guild_id, threshold.isoformat())
        )
        return [Order.from_row(r) for r in rows]

    async def get_user_draft_order(
        self, guild_id: int, user_id: int
    ) -> Optional[Order]:
        """Draft/needs_resubmit aktif milik user (kalau ada) — dipakai /subscribe
        untuk melanjutkan draft lama alih-alih bikin baru."""
        row = await self.bot.GET_ONE(_GET_USER_DRAFT_ORDER, (guild_id, user_id))
        if not row:
            return None
        return Order.from_row(row)

    async def get_other_payment_phashes(
        self, guild_id: int, exclude_order_id: int
    ) -> list[tuple[int, str]]:
        """Semua (order_id, payment_phash) order lain di guild ini — buat fraud_check bandingkan Hamming distance."""
        rows = await self.bot.GET(_GET_OTHER_PAYMENT_PHASHES, (guild_id, exclude_order_id))
        return [(r[0], r[1]) for r in rows]

    # ----------------------------------------------------------
    # ORDERS — read & status umum
    # ----------------------------------------------------------

    async def get_order(self, order_id: int) -> Optional[Order]:
        row = await self.bot.GET_ONE(_GET_ORDER, (order_id,))
        if not row:
            return None
        return Order.from_row(row)

    async def get_pending_orders(self, guild_id: int) -> list[Order]:
        rows = await self.bot.GET(_GET_PENDING_ORDERS, (guild_id,))
        return [Order.from_row(r) for r in rows]

    async def get_needs_resubmit_orders(self, guild_id: int) -> list[Order]:
        """
        Order berstatus 'needs_resubmit' — dipakai MembershipPurchase.cog_load()
        untuk mendaftar ulang ResubmitView (tombol "Upload Ulang Bukti" di DM)
        supaya tetap berfungsi setelah bot restart, sama seperti OrderApprovalView
        untuk order pending.
        """
        rows = await self.bot.GET(_GET_NEEDS_RESUBMIT_ORDERS, (guild_id,))
        return [Order.from_row(r) for r in rows]

    async def get_user_orders(
        self, guild_id: int, user_id: int, limit: int = 10
    ) -> list[Order]:
        rows = await self.bot.GET(_GET_USER_ORDERS, (guild_id, user_id, limit))
        return [Order.from_row(r) for r in rows]

    async def update_order_status(
        self,
        order_id:            int,
        status:               str,
        approved_by:          Optional[int] = None,
        notes:                Optional[str] = None,
        reject_reason_type:   Optional[str] = None,
    ) -> None:
        """
        Update status final (approved/rejected/cancelled) atau kembalikan ke
        pending (rollback kalau grant gagal). Untuk reject jalur "bukti tidak
        valid" pakai mark_needs_resubmit(), bukan method ini.
        """
        now = datetime.utcnow() if status == "approved" else None
        await self.bot.RUN(
            _UPDATE_ORDER_STATUS,
            (
                status,
                now.isoformat() if now else None,
                approved_by,
                reject_reason_type,
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