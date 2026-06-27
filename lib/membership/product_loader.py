"""
lib/membership/product_loader.py — Loader untuk config/products.yml
====================================================================
Dibaca HANYA saat user membuat order (/subscribe atau admin grant).
Tidak pernah dibaca saat approval.

Penggunaan:
    loader = ProductLoader()
    product = loader.get("companion")
    if not product:
        # produk tidak ditemukan
    payload = product.build_grant_payload(quantity=2)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import yaml

from lib.membership.models import Product

_log = logging.getLogger("bot.membership.product_loader")

PRODUCTS_PATH = os.getenv("ALT_PRODUCTS_PATH") or "config/products.yml"

_cache: Optional[dict[str, Product]] = None


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

    _log.info("Loaded %d products from %s", len(_cache), PRODUCTS_PATH)
    return _cache


def reload() -> None:
    """Paksa reload products.yml dari disk."""
    global _cache
    _cache = None
    _load()


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