"""
features/membership/support/product_loader.py — Loader untuk products.yml
=============================================================================
Dibaca HANYA saat user membuat order (/subscribe atau admin grant).
Tidak pernah dibaca saat approval.

Path default sekarang menunjuk ke features/membership/products.yml
(dulu config/products.yml) — konsisten dengan aturan restrukturisasi:
config .yml fitur ditaruh langsung di folder fitur.

HARGA TIER VIP (traveler/companion/patron) TIDAK LAGI dibaca sebagai angka
statis untuk field `price` — lihat PRICING_SYSTEM_REFACTOR.md. Sumber
kebenaran harga sekarang shared.config.get_active_prices(), yang membaca
features/membership/pricing_presets.yml. products.yml tetap jadi sumber
untuk STRUKTUR produk (grant, quantity rules, subscribable), tapi field
`price` untuk 3 tier itu ditimpa saat load.

Produk kelas (jlpt_n5, jlpt_n4, kaiwa) dan trial TIDAK terpengaruh —
harganya tetap statis apa adanya dari products.yml.

VARIAN 6 BULAN & 1 TAHUN (traveler_6mo, traveler_12mo, companion_6mo,
companion_12mo) TIDAK ditulis di products.yml sama sekali — digenerate
otomatis di sini dari get_active_prices() (harga & poin sudah dihitung
di shared/config.py lewat duration_multipliers). Kalau mau ubah nama/
durasi paket ini, edit _DURATION_VARIANT_LABELS di bawah, BUKAN
products.yml.

Penggunaan:
    loader = ProductLoader()
    product = loader.get("companion")            # tier bulanan biasa
    product = loader.get("companion_6mo")         # varian 6 bulan (auto)
    if not product:
        # produk tidak ditemukan
    payload = product.build_grant_payload(quantity=2)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import yaml

from features.membership.support.models import GrantMembership, GrantPoint, Product
from shared.config import get_active_prices

_log = logging.getLogger("bot.membership.product_loader")

PRODUCTS_PATH = os.getenv("ALT_PRODUCTS_PATH") or "features/membership/products.yml"

_cache: Optional[dict[str, Product]] = None

# Tier yang harganya dikontrol pricing_presets.yml. Produk lain (kelas
# JLPT/Kaiwa, trial) TIDAK disentuh sama sekali oleh loader ini — harganya
# tetap statis dari products.yml apa adanya.
_PRESET_CONTROLLED_TIERS = ("traveler", "companion")

# (label tampilan, jumlah hari, key harga & poin di get_active_prices())
_DURATION_VARIANT_LABELS: dict[str, tuple[str, int, str]] = {
    "6mo": ("6 Bulan", 180, "6mo"),
    "12mo": ("1 Tahun", 365, "12mo"),
}

_TIER_DISPLAY_NAME = {
    "traveler": "【旅人】 Traveler",
    "companion": "【同胞】 Companion",
}


def _build_duration_variant(tier: str, variant_key: str, active_prices: dict) -> Product:
    """
    Bangun Product untuk varian 6 bulan / 1 tahun dari harga preset aktif.
    Selalu dihitung ulang tiap _load() dari get_active_prices() — tidak ada
    angka harga/poin tersimpan manual untuk varian ini di mana pun.
    """
    label, duration_days, price_key = _DURATION_VARIANT_LABELS[variant_key]
    tier_prices = active_prices[tier]

    return Product(
        id=f"{tier}_{variant_key}",
        name=f"{_TIER_DISPLAY_NAME[tier]} ({label})",
        version="preset-derived",
        type="membership",
        price=tier_prices[price_key],
        subscribable=True,
        quantity_label=None,
        min_quantity=1,
        max_quantity=1,
        grant_membership=GrantMembership(tier=tier, duration_days=duration_days),
        grant_point=GrantPoint(amount=tier_prices[f"points_{variant_key}"]),
    )


def _load() -> dict[str, Product]:
    global _cache
    if _cache is not None:
        return _cache

    if not os.path.exists(PRODUCTS_PATH):
        _log.error("products.yml tidak ditemukan di %s", PRODUCTS_PATH)
        _cache = {}
        return _cache

    with open(PRODUCTS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    products_raw = data.get("products", {})
    _cache = {}
    for key, val in products_raw.items():
        try:
            _cache[key] = Product.from_dict(val)
        except Exception as e:
            _log.error("Gagal load produk '%s': %s", key, e)

    # --- Timpa harga tier yang dikontrol preset -------------------------
    # traveler/companion di products.yml TETAP dipakai untuk struktur
    # (quantity 1-12 bulan biasa), tapi field price-nya diganti dari
    # get_active_prices() supaya konsisten dengan preset aktif, bukan
    # angka statis di YAML. Kalau resolve gagal (mis. pricing_presets.yml
    # rusak), harga statis lama di products.yml tetap dipakai sebagai
    # fallback — bot tidak berhenti total.
    try:
        active_prices = get_active_prices()

        for tier in _PRESET_CONTROLLED_TIERS:
            if tier in _cache:
                _cache[tier].price = active_prices[tier]["monthly"]
        if "patron" in _cache:
            _cache["patron"].price = active_prices["patron"]

        # --- Tambah varian 6 bulan & 1 tahun (selalu digenerate) --------
        for tier in _PRESET_CONTROLLED_TIERS:
            for variant_key in _DURATION_VARIANT_LABELS:
                variant_product = _build_duration_variant(tier, variant_key, active_prices)
                _cache[variant_product.id] = variant_product

    except Exception as e:
        _log.error(
            "Gagal resolve harga dari pricing_presets.yml — produk tier VIP "
            "tetap pakai harga statis di products.yml, varian 6bln/1thn "
            "TIDAK dibuat: %s", e
        )

    _log.info(
        "Loaded %d products dari %s (termasuk varian durasi preset kalau berhasil dibuat)",
        len(_cache), PRODUCTS_PATH,
    )
    return _cache


class ProductLoader:
    def get(self, product_id: str) -> Optional[Product]:
        """Return Product atau None jika tidak ditemukan."""
        products = _load()
        return products.get(product_id)

    def get_subscribable(self) -> list[Product]:
        """Return semua produk yang bisa dibeli user lewat /subscribe."""
        products = _load()
        return [p for p in products.values() if p.subscribable]

    def all(self) -> list[Product]:
        return list(_load().values())