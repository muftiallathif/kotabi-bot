"""
features/membership/support/grants/membership_handler.py — Grant Handler: Membership
=========================================================================================
(Dulu lib/grants/handlers/membership.py — di-flatten & rename sesuai rencana
restrukturisasi: handlers/membership.py -> grants/membership_handler.py)

Bertanggung jawab memproses satu blok grant membership dari payload:

    {
        "membership": {
            "tier": "companion",
            "duration_days": 60,   # atau
            "lifetime": true
        }
    }

Handler ini tidak tahu dari mana payload berasal (order, admin, trial).
Semua konteks itu ada di engine.py.

Penggunaan (dari engine.py saja, jangan dipanggil langsung dari cog):
    result = await MembershipGrantHandler(svc).handle(
        guild_id, user_id, payload, actor, order_id, source
    )
"""

from __future__ import annotations

import logging
from typing import Optional

from features.membership.support.service import GrantResult, MembershipService

_log = logging.getLogger("bot.grants.handlers.membership")


class MembershipGrantHandler:
    def __init__(self, service: MembershipService):
        self.svc = service

    async def handle(
        self,
        guild_id:  int,
        user_id:   int,
        payload:   dict,
        actor:     Optional[int],
        order_id:  Optional[int],
        source:    str,
    ) -> GrantResult:
        """
        Proses blok `membership` dari grant_payload.

        payload contoh:
            {"tier": "companion", "duration_days": 60}
            {"tier": "patron", "lifetime": true}
        """
        tier          = payload.get("tier")
        lifetime      = payload.get("lifetime", False)
        duration_days = payload.get("duration_days") if not lifetime else None

        if not tier:
            raise ValueError("Grant payload membership tidak memiliki field 'tier'.")

        _log.debug(
            "MembershipGrantHandler: guild=%d user=%d tier=%s lifetime=%s duration=%s",
            guild_id, user_id, tier, lifetime, duration_days
        )

        return await self.svc.grant(
            guild_id=guild_id,
            user_id=user_id,
            tier=tier,
            duration_days=duration_days,
            point_amount=0,   # point dihandle oleh PointGrantHandler
            actor=actor,
            source=source,
            order_id=order_id,
            lifetime=lifetime,
        )