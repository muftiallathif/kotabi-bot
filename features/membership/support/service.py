"""
features/membership/support/service.py — Business Logic Membership System v1
================================================================================
Semua keputusan bisnis ada di sini.
Tidak ada SQL langsung — semua lewat MembershipRepository.
Tidak ada Discord API langsung — semua lewat caller (cog/scheduler).

Penggunaan:
    svc = MembershipService(bot)

    # Grant dari admin
    result = await svc.grant(
        guild_id=..., user_id=..., tier='companion',
        duration_days=30, point_amount=2,
        actor=admin_id, source='admin'
    )

    # Grant dari approval order
    result = await svc.apply_grant_payload(
        guild_id=..., user_id=...,
        grant_payload=order.grant_payload,
        actor=admin_id, order_id=order.order_id,
        source='purchase'
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from features.membership.support.models import (
    GrantMembership,
    HistoryEvent,
    MembershipRow,
)
from features.membership.support.repository import MembershipRepository
from shared.config import get_lifetime_threshold

_log = logging.getLogger("bot.membership.service")

# Tier hierarchy (untuk validasi downgrade)
TIER_ORDER = ["trial", "traveler", "companion", "patron"]


# ============================================================
# RESULT OBJECTS
# ============================================================

class GrantResult:
    """
    Hasil dari satu operasi grant.
    Dipakai oleh cog untuk memutuskan apa yang perlu dilakukan di Discord.
    """
    def __init__(
        self,
        membership:           MembershipRow,
        previous_tier:        Optional[str],
        just_became_lifetime: bool,
        point_before:         int,
        point_after:          int,
    ):
        self.membership           = membership
        self.previous_tier        = previous_tier
        self.just_became_lifetime = just_became_lifetime
        self.point_before         = point_before
        self.point_after          = point_after

    @property
    def tier(self) -> str:
        return self.membership.tier

    @property
    def is_lifetime(self) -> bool:
        return self.membership.is_lifetime

    @property
    def expires_at(self) -> Optional[datetime]:
        return self.membership.expires_at

    @property
    def point_count(self) -> int:
        return self.membership.point_count


class RevokeResult:
    def __init__(self, membership_before: MembershipRow):
        self.membership_before = membership_before
        self.tier              = membership_before.tier


# ============================================================
# SERVICE
# ============================================================

class MembershipService:

    def __init__(self, bot):
        self.repo = MembershipRepository(bot)

    # ----------------------------------------------------------
    # GRANT — entry point utama untuk semua jenis grant
    # ----------------------------------------------------------

    async def grant(
        self,
        guild_id:     int,
        user_id:      int,
        tier:         str,
        duration_days: Optional[int],   # None jika lifetime
        point_amount: int,
        actor:        Optional[int],
        source:       str,
        order_id:     Optional[int] = None,
        lifetime:     bool = False,
    ) -> GrantResult:
        """
        Core grant logic. Dipanggil dari:
        - /admin grant-member
        - apply_grant_payload (approval order)
        - grant_trial

        Return GrantResult untuk dipakai caller memberi tahu Discord.
        """
        now = datetime.utcnow()
        threshold = get_lifetime_threshold()

        # Ambil state sebelum grant
        existing = await self.repo.get_membership(guild_id, user_id)
        point_before  = existing.point_count if existing else 0
        tier_before   = existing.tier        if existing else None
        expiry_before = existing.expires_at  if existing else None

        # Hitung point baru — dibatasi maksimal `threshold` (60), tidak boleh
        # lebih. Poin adalah indikator loyalitas menuju lifetime, bukan mata
        # uang yang boleh menumpuk lewat cap; lihat KOTABI_MEMBERSHIP_SYSTEM_v3.md
        # bagian "Kenapa threshold poin 60" — membeli lebih banyak dari yang
        # dibutuhkan untuk mencapai threshold tidak menambah poin lagi.
        if existing and existing.is_lifetime:
            point_after = existing.point_count  # frozen
        else:
            point_after = min(point_before + point_amount, threshold)

        # Hitung expiry baru
        if lifetime:
            expires_at = datetime(9999, 12, 31, 23, 59, 59)
            is_lifetime = True
        else:
            if existing and existing.is_lifetime:
                # Jangan timpa expiry lifetime — pakai sentinel yang sama
                expires_at = datetime(9999, 12, 31, 23, 59, 59)
                is_lifetime = True
            else:
                base = max(
                    existing.expires_at if (existing and existing.expires_at and existing.active) else now,
                    now
                )
                expires_at = base + timedelta(days=duration_days or 0)
                is_lifetime = False

        # Upsert membership
        await self.repo.upsert_membership(
            guild_id=guild_id,
            user_id=user_id,
            tier=tier,
            granted_at=now,
            expires_at=expires_at,
            is_lifetime=is_lifetime,
            point_count=point_after,
            granted_by=actor,
            source=source,
        )

        # Cek auto Patron
        just_became_lifetime = False
        if (
            not is_lifetime
            and not (existing and existing.is_lifetime)
            and point_after >= threshold
        ):
            await self.repo.set_lifetime(guild_id, user_id)
            just_became_lifetime = True
            is_lifetime = True
            expires_at = None
            tier = "patron"

            _log.info(
                "Auto Patron: user %s guild %s (%d points)",
                user_id, guild_id, point_after
            )

            await self.repo.insert_history(HistoryEvent(
                guild_id=guild_id,
                user_id=user_id,
                event="auto_patron",
                tier_before=tier_before,
                tier_after="patron",
                expiry_before=expiry_before,
                expiry_after=None,
                point_before=point_before,
                point_after=point_after,
                order_id=order_id,
                actor=None,
                reason=f"Reached {threshold} points",
            ))

        # Tulis history untuk grant ini
        event = _source_to_event(source)
        await self.repo.insert_history(HistoryEvent(
            guild_id=guild_id,
            user_id=user_id,
            event=event,
            tier_before=tier_before,
            tier_after=tier,
            expiry_before=expiry_before,
            expiry_after=expires_at,
            point_before=point_before,
            point_after=point_after,
            order_id=order_id,
            actor=actor,
        ))

        # Ambil state terbaru
        updated = await self.repo.get_membership(guild_id, user_id)

        return GrantResult(
            membership=updated,
            previous_tier=tier_before,
            just_became_lifetime=just_became_lifetime,
            point_before=point_before,
            point_after=point_after,
        )

    # ----------------------------------------------------------
    # APPLY GRANT PAYLOAD — dipakai saat approval order
    # ----------------------------------------------------------

    async def apply_grant_payload(
        self,
        guild_id:      int,
        user_id:       int,
        grant_payload: dict,
        actor:         Optional[int],
        order_id:      Optional[int] = None,
        source:        str = "purchase",
    ) -> GrantResult:
        """
        Eksekusi grants dari order.grant_payload.
        Tidak pernah membaca products.yml.
        """
        m = grant_payload.get("membership", {})
        p = grant_payload.get("point", {})

        tier          = m.get("tier", "traveler")
        lifetime      = m.get("lifetime", False)
        duration_days = m.get("duration_days") if not lifetime else None
        point_amount  = p.get("amount", 0)

        return await self.grant(
            guild_id=guild_id,
            user_id=user_id,
            tier=tier,
            duration_days=duration_days,
            point_amount=point_amount,
            actor=actor,
            source=source,
            order_id=order_id,
            lifetime=lifetime,
        )

    # ----------------------------------------------------------
    # PREVIEW GRANT — read-only, dipakai di step ringkasan /subscribe
    # ----------------------------------------------------------

    async def preview_grant_payload(
        self,
        guild_id:      int,
        user_id:       int,
        grant_payload: dict,
    ) -> dict:
        """
        Hitung apa yang AKAN terjadi kalau grant_payload ini diproses,
        pakai rule yang sama persis dengan grant() (expiry_baru = max(expiry_lama,
        sekarang) + durasi, poin dibatasi maksimal threshold), TAPI tidak
        menulis apa pun ke database. Murni untuk ditampilkan di step ringkasan
        order sebelum user diarahkan ke rekening bank.

        Return dict:
            {
                "tier": str,
                "is_lifetime": bool,
                "point_before": int,
                "point_after": int,
                "expiry_before": Optional[datetime],
                "expiry_after": Optional[datetime],   # None kalau lifetime
                "will_become_lifetime": bool,
            }
        """
        now = datetime.utcnow()
        threshold = get_lifetime_threshold()

        m = grant_payload.get("membership", {})
        p = grant_payload.get("point", {})

        tier          = m.get("tier", "traveler")
        lifetime      = m.get("lifetime", False)
        duration_days = m.get("duration_days") if not lifetime else None
        point_amount  = p.get("amount", 0)

        existing = await self.repo.get_membership(guild_id, user_id)
        point_before  = existing.point_count if existing else 0
        expiry_before = existing.expires_at  if existing else None

        if existing and existing.is_lifetime:
            point_after = existing.point_count
            expiry_after = None
            will_become_lifetime = False
            is_lifetime = True
        elif lifetime:
            point_after = min(point_before + point_amount, threshold)
            expiry_after = None
            will_become_lifetime = False
            is_lifetime = True
        else:
            point_after = min(point_before + point_amount, threshold)
            base = max(
                existing.expires_at if (existing and existing.expires_at and existing.active) else now,
                now
            )
            expiry_after = base + timedelta(days=duration_days or 0)
            will_become_lifetime = point_after >= threshold
            is_lifetime = will_become_lifetime

            if will_become_lifetime:
                expiry_after = None
                tier = "patron"

        return {
            "tier": tier,
            "is_lifetime": is_lifetime,
            "point_before": point_before,
            "point_after": point_after,
            "expiry_before": expiry_before,
            "expiry_after": expiry_after,
            "will_become_lifetime": will_become_lifetime,
        }

    # ----------------------------------------------------------
    # TRIAL
    # ----------------------------------------------------------

    async def grant_trial(
        self,
        guild_id: int,
        user_id:  int,
        actor:    Optional[int],
    ) -> GrantResult:
        """
        Grant trial. Validasi cycle dilakukan oleh caller sebelum memanggil ini.
        """
        result = await self.grant(
            guild_id=guild_id,
            user_id=user_id,
            tier="trial",
            duration_days=5,
            point_amount=0,
            actor=actor,
            source="trial",
        )

        # Catat trial claim
        cycle = get_current_trial_cycle(datetime.utcnow())
        await self.repo.insert_trial_claim(user_id, guild_id, cycle)

        return result

    # ----------------------------------------------------------
    # REVOKE
    # ----------------------------------------------------------

    async def revoke(
        self,
        guild_id: int,
        user_id:  int,
        actor:    Optional[int],
        reason:   Optional[str] = None,
    ) -> RevokeResult:
        """
        Cabut membership. Tidak berlaku untuk lifetime member.
        Validasi (apakah lifetime) dilakukan sebelum memanggil ini.
        """
        existing = await self.repo.get_membership(guild_id, user_id)
        if not existing:
            raise ValueError("Membership tidak ditemukan.")
        if existing.is_lifetime:
            raise ValueError("Lifetime member tidak bisa di-revoke.")

        await self.repo.revoke_membership(guild_id, user_id)

        await self.repo.insert_history(HistoryEvent(
            guild_id=guild_id,
            user_id=user_id,
            event="admin_revoke",
            tier_before=existing.tier,
            tier_after=None,
            expiry_before=existing.expires_at,
            expiry_after=None,
            point_before=existing.point_count,
            point_after=existing.point_count,
            actor=actor,
            reason=reason or "Manual revoke",
        ))

        return RevokeResult(membership_before=existing)

    # ----------------------------------------------------------
    # EXPIRY (dipanggil dari scheduler)
    # ----------------------------------------------------------

    async def expire_membership(
        self,
        guild_id: int,
        user_id:  int,
    ) -> RevokeResult:
        existing = await self.repo.get_membership(guild_id, user_id)
        if not existing:
            raise ValueError("Membership tidak ditemukan.")

        await self.repo.revoke_membership(guild_id, user_id)

        await self.repo.insert_history(HistoryEvent(
            guild_id=guild_id,
            user_id=user_id,
            event="membership_expired",
            tier_before=existing.tier,
            tier_after=None,
            expiry_before=existing.expires_at,
            expiry_after=None,
            point_before=existing.point_count,
            point_after=existing.point_count,
            actor=None,
            reason="Auto expire",
        ))

        return RevokeResult(membership_before=existing)

    # ----------------------------------------------------------
    # TRIAL ELIGIBILITY CHECK
    # ----------------------------------------------------------

    async def can_take_trial(
        self, guild_id: int, user_id: int
    ) -> tuple[bool, Optional[str]]:
        """
        Return (True, None) jika boleh trial.
        Return (False, reason) jika tidak boleh.
        """
        existing = await self.repo.get_membership(guild_id, user_id)

        if existing and existing.is_lifetime:
            return False, "Kamu sudah **Lifetime Member**."

        if existing and existing.is_active:
            return False, "Kamu masih punya membership aktif."

        now = datetime.utcnow()
        current_cycle = get_current_trial_cycle(now)
        claim = await self.repo.get_trial_claim(user_id, guild_id, current_cycle)

        if claim:
            next_cycle_dt = _next_cycle_start(now)
            ts = int(next_cycle_dt.timestamp())
            return False, (
                f"Trial untuk periode ini sudah digunakan.\n"
                f"Trial berikutnya tersedia pada <t:{ts}:F>."
            )

        return True, None

    # ----------------------------------------------------------
    # READ
    # ----------------------------------------------------------

    async def get_membership(
        self, guild_id: int, user_id: int
    ) -> Optional[MembershipRow]:
        return await self.repo.get_membership(guild_id, user_id)

    async def get_history(
        self,
        guild_id: int,
        user_id:  Optional[int] = None,
        limit:    int = 50,
    ) -> list[tuple]:
        return await self.repo.get_history(guild_id, user_id, limit)

    async def get_expiring_soon(
        self, guild_id: int, threshold: datetime, now: datetime
    ) -> list[MembershipRow]:
        return await self.repo.get_expiring_soon(guild_id, threshold, now)

    async def get_expired(
        self, guild_id: int, now: datetime
    ) -> list[MembershipRow]:
        return await self.repo.get_expired(guild_id, now)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_current_trial_cycle(now: datetime) -> str:
    """
    Jan–Ags → '2026A'
    Sep–Des → '2026B'
    """
    period = "A" if now.month < 9 else "B"
    return f"{now.year}{period}"


def _next_cycle_start(now: datetime) -> datetime:
    """Tanggal mulai cycle berikutnya."""
    if now.month < 9:
        return datetime(now.year, 9, 1)
    else:
        return datetime(now.year + 1, 1, 1)


def _source_to_event(source: str) -> str:
    mapping = {
        "trial":       "trial_claimed",
        "purchase":    "purchase_approved",
        "class":       "class_granted",
        "auto_patron": "patron_granted",
        "admin":       "admin_grant",
    }
    return mapping.get(source, "admin_grant")