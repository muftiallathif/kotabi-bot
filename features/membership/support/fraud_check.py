"""
features/membership/support/fraud_check.py — Anti-Fraud pHash Check
======================================================================
Membandingkan pHash bukti transfer baru terhadap bukti transfer order lain
di guild yang sama, untuk mendeteksi kemungkinan bukti transfer dipakai ulang.

Ini WARNING untuk admin, bukan auto-reject — judgment tetap manual
(lihat KOTABI_MEMBERSHIP_SYSTEM_v3.md bagian "Anti-Fraud Bukti Transfer").
"""

from __future__ import annotations

import logging

import imagehash

from features.membership.support.repository import MembershipRepository

_log = logging.getLogger("bot.membership.fraud_check")

# Hamming distance <= ini dianggap "mirip" (pHash 64-bit: 0 = identik).
SIMILARITY_THRESHOLD = 10


async def check_similar_proof(
    repo: MembershipRepository,
    guild_id: int,
    order_id: int,
    new_phash: str,
) -> list[tuple[int, int]]:
    """Return list (other_order_id, hamming_distance) yang mirip (distance <= threshold)."""
    try:
        new_hash_obj = imagehash.hex_to_hash(new_phash)
    except (ValueError, TypeError):
        return []

    others = await repo.get_other_payment_phashes(guild_id, order_id)
    matches = []

    for other_order_id, other_phash_str in others:
        try:
            other_hash_obj = imagehash.hex_to_hash(other_phash_str)
        except (ValueError, TypeError):
            continue
        distance = new_hash_obj - other_hash_obj
        if distance <= SIMILARITY_THRESHOLD:
            matches.append((other_order_id, distance))

    return matches