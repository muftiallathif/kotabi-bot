"""
lib/grants/handlers/point.py — Grant Handler: Point
=====================================================
Bertanggung jawab memproses satu blok grant point dari payload:

    {
        "point": {
            "amount": 2
        }
    }

Handler ini hanya menambah poin ke membership yang sudah ada.
Auto Patron dicek dan ditrigger di MembershipService.grant(),
bukan di sini — supaya logic tetap di satu tempat.

Penggunaan (dari engine.py saja):
    await PointGrantHandler(svc).handle(
        guild_id, user_id, payload, actor, order_id
    )
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from lib.membership.models import HistoryEvent
from lib.membership.repository import MembershipRepository
from lib.membership.service import MembershipService
from lib.config import get_lifetime_threshold

_log = logging.getLogger("bot.grants.handlers.point")


class PointGrantHandler:
    def __init__(self, service: MembershipService):
        self.svc  = service
        self.repo = service.repo

    async def handle(
        self,
        guild_id: int,
        user_id:  int,
        payload:  dict,
        actor:    Optional[int],
        order_id: Optional[int],
    ) -> dict:
        """
        Tambah poin ke membership yang sudah ada.
        Return dict dengan point_before dan point_after.

        Catatan: handler ini dipanggil SETELAH MembershipGrantHandler
        karena membership harus sudah ada di database sebelum poin bisa ditambah.
        """
        amount = payload.get("amount", 0)
        if amount <= 0:
            return {"point_before": 0, "point_after": 0, "changed": False}

        existing = await self.repo.get_membership(guild_id, user_id)
        if not existing:
            _log.warning(
                "PointGrantHandler: membership tidak ditemukan untuk user %d guild %d",
                user_id, guild_id
            )
            return {"point_before": 0, "point_after": 0, "changed": False}

        # Lifetime member — poin tidak bertambah lagi
        if existing.is_lifetime:
            _log.debug(
                "PointGrantHandler: user %d sudah lifetime, poin tidak berubah",
                user_id
            )
            return {
                "point_before": existing.point_count,
                "point_after":  existing.point_count,
                "changed":      False,
            }

        threshold = get_lifetime_threshold()

        point_before = existing.point_count
        point_after  = min(point_before + amount, threshold + 99)

        await self.repo.set_point_count(guild_id, user_id, point_after)

        _log.debug(
            "PointGrantHandler: user %d guild %d poin %d → %d",
            user_id, guild_id, point_before, point_after
        )

        return {
            "point_before": point_before,
            "point_after":  point_after,
            "changed":      point_after != point_before,
        }