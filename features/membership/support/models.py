"""
features/membership/support/models.py — Data Models Membership System v2
==========================================================================
Semua dataclass di sini adalah representasi Python dari baris database
atau dari products.yml. Tidak ada logic bisnis di sini.

Penggunaan:
    from features.membership.support.models import MembershipRow, Order, Product
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json


# ============================================================
# MEMBERSHIP
# ============================================================

@dataclass
class MembershipRow:
    """
    Representasi satu baris dari tabel `memberships`.
    Dibuat oleh MembershipRepository, dipakai oleh MembershipService.
    """
    guild_id:    int
    user_id:     int
    tier:        str
    granted_at:  datetime
    expires_at:  Optional[datetime]   # None jika lifetime
    is_lifetime: bool
    active:      bool
    point_count: int
    granted_by:  Optional[int]
    source:      Optional[str]        # trial | purchase | class | auto_patron | admin

    @property
    def is_active(self) -> bool:
        """True jika membership sedang aktif (belum expired dan active=1)."""
        if not self.active:
            return False
        if self.is_lifetime:
            return True
        if self.expires_at is None:
            return False
        return self.expires_at > datetime.utcnow()

    @property
    def is_expired(self) -> bool:
        if self.is_lifetime:
            return False
        if self.expires_at is None:
            return True
        return self.expires_at <= datetime.utcnow()

    @classmethod
    def from_row(cls, row: tuple) -> "MembershipRow":
        """
        Konversi dari hasil aiosqlite fetchone.
        Urutan kolom harus sesuai dengan query di repository.py.
        """
        (
            guild_id, user_id, tier, granted_at, expires_at,
            is_lifetime, active, point_count, granted_by, source
        ) = row

        return cls(
            guild_id=guild_id,
            user_id=user_id,
            tier=tier,
            granted_at=_parse_dt(granted_at),
            expires_at=_parse_dt(expires_at) if expires_at else None,
            is_lifetime=bool(is_lifetime),
            active=bool(active),
            point_count=point_count or 0,
            granted_by=granted_by,
            source=source,
        )


# ============================================================
# ORDER
# ============================================================

# Status yang berarti order masih "hidup" secara aktif dari sisi user
# (belum final). Dipakai helper is_terminal di bawah.
_TERMINAL_STATUSES = {"approved", "rejected", "cancelled"}


@dataclass
class Order:
    """
    Representasi satu baris dari tabel `orders` (schema v2, lihat
    migrations/v2_purchase_flow.sql).

    Field bisnis (product_name, price, grant_payload) immutable setelah
    order pertama kali dibuat — jangan pernah di-update setelah insert.
    Field alur (status, payment_proof_url, sender_bank, payment_phash,
    reject_reason_type, confirmed_at, approved_at, approved_by) memang
    berubah seiring order berjalan lewat draft -> pending -> approved/
    rejected/needs_resubmit -> (resubmit) -> pending -> ...
    """
    order_id:            Optional[int]    # None sebelum INSERT
    guild_id:            int
    user_id:              int
    product_key:         str
    product_version:     str
    product_name:        str
    price:               int              # harga per unit saat order dibuat
    quantity:            int
    total_duration:      Optional[int]    # total hari, None jika lifetime
    grant_payload:       dict             # parsed JSON dari database
    status:              str              # draft | pending | needs_resubmit | approved | rejected | cancelled
    unique_code:         Optional[int]    # order_id mod 100
    payment_proof_url:   Optional[str]
    sender_bank:         Optional[str]
    payment_phash:       Optional[str]
    reject_reason_type:  Optional[str]    # invalid_proof | other | None
    notes:                Optional[str]
    draft_created_at:    Optional[datetime]
    confirmed_at:        Optional[datetime]
    created_at:           Optional[datetime]
    approved_at:          Optional[datetime]
    approved_by:          Optional[int]

    @property
    def total_price(self) -> int:
        return self.price * self.quantity

    @property
    def total_price_with_unique_code(self) -> int:
        """Nominal yang harus ditransfer user: harga + kode unik (lihat v3 doc)."""
        return self.total_price + (self.unique_code or 0)

    @property
    def grant_payload_json(self) -> str:
        return json.dumps(self.grant_payload, ensure_ascii=False)

    @property
    def is_draft(self) -> bool:
        return self.status == "draft"

    @property
    def is_terminal(self) -> bool:
        """True kalau order sudah final (tidak bisa berubah lagi)."""
        return self.status in _TERMINAL_STATUSES

    @classmethod
    def from_row(cls, row: tuple) -> "Order":
        (
            order_id, guild_id, user_id, product_key, product_version,
            product_name, price, quantity, total_duration, grant_payload_str,
            status, unique_code, payment_proof_url, sender_bank, payment_phash,
            reject_reason_type, notes, draft_created_at, confirmed_at,
            created_at, approved_at, approved_by
        ) = row

        return cls(
            order_id=order_id,
            guild_id=guild_id,
            user_id=user_id,
            product_key=product_key,
            product_version=product_version,
            product_name=product_name,
            price=price,
            quantity=quantity,
            total_duration=total_duration,
            grant_payload=json.loads(grant_payload_str),
            status=status,
            unique_code=unique_code,
            payment_proof_url=payment_proof_url,
            sender_bank=sender_bank,
            payment_phash=payment_phash,
            reject_reason_type=reject_reason_type,
            notes=notes,
            draft_created_at=_parse_dt(draft_created_at) if draft_created_at else None,
            confirmed_at=_parse_dt(confirmed_at) if confirmed_at else None,
            created_at=_parse_dt(created_at) if created_at else None,
            approved_at=_parse_dt(approved_at) if approved_at else None,
            approved_by=approved_by,
        )


# ============================================================
# PRODUCT (dari products.yml)
# ============================================================

@dataclass
class GrantMembership:
    """Grant membership dari satu produk."""
    tier:          str
    duration_days: Optional[int]  # None jika lifetime
    lifetime:      bool = False


@dataclass
class GrantPoint:
    """Grant poin dari satu produk."""
    amount: int


@dataclass
class Product:
    """
    Representasi satu produk dari products.yml.
    Dibuat oleh ProductLoader, dipakai untuk membuat Order baru.
    TIDAK dipakai saat approval — approval selalu pakai grant_payload dari DB.
    """
    id:              str
    name:            str
    version:         str
    type:            str           # membership | class
    price:           int
    subscribable:    bool          # False = hanya bisa dari admin
    quantity_label:  Optional[str] # None = tidak ada pilihan quantity
    min_quantity:    int
    max_quantity:    int
    grant_membership: Optional[GrantMembership]
    grant_point:     Optional[GrantPoint]

    def build_grant_payload(self, quantity: int = 1) -> dict:
        """
        Buat grant_payload JSON untuk disimpan di order.
        Payload ini yang akan dipakai saat approval — bukan products.yml.
        """
        payload = {}

        if self.grant_membership:
            m = self.grant_membership
            membership_grant = {"tier": m.tier}
            if m.lifetime:
                membership_grant["lifetime"] = True
            else:
                membership_grant["duration_days"] = (m.duration_days or 0) * quantity
            payload["membership"] = membership_grant

        if self.grant_point:
            payload["point"] = {
                "amount": self.grant_point.amount * quantity
            }

        return payload

    def calculate_total_duration(self, quantity: int = 1) -> Optional[int]:
        """Total durasi dalam hari. None jika lifetime."""
        if self.grant_membership and self.grant_membership.lifetime:
            return None
        if self.grant_membership and self.grant_membership.duration_days:
            return self.grant_membership.duration_days * quantity
        return None

    @classmethod
    def from_dict(cls, data: dict) -> "Product":
        grants = data.get("grants", {})

        grant_membership = None
        if "membership" in grants:
            m = grants["membership"]
            grant_membership = GrantMembership(
                tier=m["tier"],
                duration_days=m.get("duration_days"),
                lifetime=m.get("lifetime", False),
            )

        grant_point = None
        if "point" in grants:
            grant_point = GrantPoint(amount=grants["point"]["amount"])

        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            type=data["type"],
            price=data["price"],
            subscribable=data.get("subscribable", True),
            quantity_label=data.get("quantity_label"),
            min_quantity=data.get("min_quantity", 1),
            max_quantity=data.get("max_quantity", 1),
            grant_membership=grant_membership,
            grant_point=grant_point,
        )


# ============================================================
# MEMBERSHIP HISTORY EVENT
# ============================================================

@dataclass
class HistoryEvent:
    """
    Satu event untuk ditulis ke tabel membership_history_v1.
    Dibuat oleh MembershipService, ditulis oleh MembershipRepository.
    """
    guild_id:     int
    user_id:      int
    event:        str
    tier_before:  Optional[str]      = None
    tier_after:   Optional[str]      = None
    expiry_before: Optional[datetime] = None
    expiry_after:  Optional[datetime] = None
    point_before: Optional[int]      = None
    point_after:  Optional[int]      = None
    order_id:     Optional[int]      = None
    actor:        Optional[int]      = None
    reason:       Optional[str]      = None


# ============================================================
# TRIAL CLAIM
# ============================================================

@dataclass
class TrialClaim:
    user_id:     int
    guild_id:    int
    trial_cycle: str    # '2026A' | '2026B'
    claimed_at:  datetime

    @classmethod
    def from_row(cls, row: tuple) -> "TrialClaim":
        user_id, guild_id, trial_cycle, claimed_at = row
        return cls(
            user_id=user_id,
            guild_id=guild_id,
            trial_cycle=trial_cycle,
            claimed_at=_parse_dt(claimed_at),
        )


# ============================================================
# HELPER
# ============================================================

def _parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None