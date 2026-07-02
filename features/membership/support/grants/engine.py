"""
features/membership/support/grants/engine.py — Grant Engine v1
==================================================================
Entry point tunggal untuk semua operasi grant.
Generic — tidak tahu apakah grant berasal dari order, admin, atau sistem.
Semua konteks itu diberikan oleh caller.

Flow:
    Caller (cog/scheduler)
        ↓
    GrantEngine.apply(grant_payload, ...)
        ↓
    Handler membership  →  MembershipService  →  Repository  →  DB
    Handler point       →  MembershipService  →  Repository  →  DB
        ↓
    Cek auto Patron (di dalam MembershipService)
        ↓
    Return ApplyResult
        ↓
    Caller update Discord role + kirim DM

MENAMBAH GRANT TYPE BARU (contoh: badge, coupon, xp):
    1. Buat features/membership/support/grants/handlers/badge.py
    2. Daftarkan di HANDLERS dict di bawah
    3. Selesai — engine.py tidak perlu diubah

Penggunaan:
    engine = GrantEngine(bot)

    # Dari approval order
    result = await engine.apply(
        guild_id=...,
        user_id=...,
        grant_payload=order.grant_payload,
        actor=admin_id,
        order_id=order.order_id,
        source='purchase',
    )

    # Dari admin command
    result = await engine.apply(
        guild_id=...,
        user_id=...,
        grant_payload=product.build_grant_payload(quantity=2),
        actor=admin_id,
        source='admin',
    )

    # Gunakan result untuk update Discord
    if result.membership:
        resolver = RoleResolver(guild)
        await resolver.apply_tier(member, result.membership.tier)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from features.membership.support.service import GrantResult, MembershipService
from features.membership.support.grants.membership_handler import MembershipGrantHandler
from features.membership.support.grants.point_handler import PointGrantHandler

_log = logging.getLogger("bot.grants.engine")


# ============================================================
# RESULT
# ============================================================

@dataclass
class ApplyResult:
    """
    Hasil dari satu operasi apply().
    Berisi semua yang dibutuhkan caller untuk update Discord dan kirim DM.
    """
    # Hasil dari membership handler (None jika tidak ada grant membership)
    membership: Optional[GrantResult] = None

    # Hasil dari point handler
    point_before: int = 0
    point_after:  int = 0
    point_changed: bool = False

    # True jika user baru saja unlock Patron otomatis
    just_became_lifetime: bool = False

    # Errors per handler (key = nama handler)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    @property
    def tier(self) -> Optional[str]:
        return self.membership.tier if self.membership else None

    @property
    def is_lifetime(self) -> bool:
        return self.membership.is_lifetime if self.membership else False


# ============================================================
# ENGINE
# ============================================================

class GrantEngine:
    """
    Generic grant engine.
    Tambah handler baru tanpa mengubah class ini.
    """

    def __init__(self, bot):
        self._svc = MembershipService(bot)

    async def apply(
        self,
        guild_id:      int,
        user_id:       int,
        grant_payload: dict,
        actor:         Optional[int],
        source:        str,
        order_id:      Optional[int] = None,
    ) -> ApplyResult:
        """
        Proses semua grant dalam satu payload.
        Urutan eksekusi: membership dulu, lalu point.
        Kalau membership gagal, point tidak dijalankan.

        grant_payload contoh:
            {
                "membership": {"tier": "companion", "duration_days": 60},
                "point": {"amount": 2}
            }
        """
        result = ApplyResult()

        # ----------------------------------------------------------
        # 1. Membership grant
        # ----------------------------------------------------------
        if "membership" in grant_payload:
            try:
                membership_result = await MembershipGrantHandler(self._svc).handle(
                    guild_id=guild_id,
                    user_id=user_id,
                    payload=grant_payload["membership"],
                    actor=actor,
                    order_id=order_id,
                    source=source,
                )
                result.membership           = membership_result
                result.just_became_lifetime = membership_result.just_became_lifetime
                result.point_before         = membership_result.point_before
                result.point_after          = membership_result.point_after

                _log.info(
                    "Membership grant OK: guild=%d user=%d tier=%s lifetime=%s",
                    guild_id, user_id,
                    membership_result.tier,
                    membership_result.is_lifetime,
                )
            except Exception as e:
                _log.exception(
                    "Membership grant FAILED: guild=%d user=%d: %s",
                    guild_id, user_id, e
                )
                result.errors["membership"] = str(e)
                # Jika membership gagal, stop — jangan proses point
                return result

        # ----------------------------------------------------------
        # 2. Point grant
        # Dijalankan setelah membership karena point butuh membership
        # sudah ada di database.
        # Auto Patron dicek di dalam PointGrantHandler via service.
        # ----------------------------------------------------------
        if "point" in grant_payload and "membership" not in result.errors:
            try:
                point_result = await PointGrantHandler(self._svc).handle(
                    guild_id=guild_id,
                    user_id=user_id,
                    payload=grant_payload["point"],
                    actor=actor,
                    order_id=order_id,
                )
                result.point_before  = point_result["point_before"]
                result.point_after   = point_result["point_after"]
                result.point_changed = point_result["changed"]

                # Cek apakah point baru memicu auto Patron
                if not result.just_became_lifetime:
                    updated = await self._svc.get_membership(guild_id, user_id)
                    if updated and updated.is_lifetime and (
                        result.membership and not result.membership.is_lifetime
                    ):
                        result.just_became_lifetime = True

                _log.info(
                    "Point grant OK: guild=%d user=%d %d → %d",
                    guild_id, user_id,
                    result.point_before, result.point_after,
                )
            except Exception as e:
                _log.exception(
                    "Point grant FAILED: guild=%d user=%d: %s",
                    guild_id, user_id, e
                )
                result.errors["point"] = str(e)
                # Point gagal tidak membatalkan membership yang sudah berhasil

        # ----------------------------------------------------------
        # Handler lain bisa ditambahkan di sini nanti:
        #
        # if "badge" in grant_payload:
        #     ...
        #
        # if "coupon" in grant_payload:
        #     ...
        # ----------------------------------------------------------

        return result