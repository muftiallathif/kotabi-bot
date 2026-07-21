import discord
import yaml
import os
import logging

from features.immersion.support.autocomplete.vndb import vn_name_autocomplete, CACHED_VNDB_THUMBNAIL_QUERY, CACHED_VNDB_TITLE_QUERY
from features.immersion.support.autocomplete.anilist import anime_manga_name_autocomplete, CACHED_ANILIST_THUMBNAIL_QUERY, CACHED_ANILIST_TITLE_QUERY
from features.immersion.support.autocomplete.tmdb import listening_autocomplete, CACHED_TMDB_THUMBNAIL_QUERY, CACHED_TMDB_TITLE_QUERY

_log = logging.getLogger(__name__)

# Single source of truth untuk immersion_log_settings.yml.
# features/immersion/support/helpers.py mengimpor `immersion_log_settings` dari sini —
# JANGAN baca ulang file ini di tempat lain.
IMMERSION_LOG_SETTINGS = os.getenv("IMMERSION_LOG_SETTINGS") or "features/immersion/immersion_log_settings.yml"
immersion_log_settings: dict = {}

if os.path.exists(IMMERSION_LOG_SETTINGS):
    try:
        with open(IMMERSION_LOG_SETTINGS, "r", encoding="utf-8") as f:
            immersion_log_settings = yaml.safe_load(f) or {}
    except Exception as e:
        _log.error("❌ Gagal memuat %s: %s", IMMERSION_LOG_SETTINGS, e)
else:
    _log.warning("⚠️ File %s tidak ditemukan. Menggunakan konfigurasi kosong.", IMMERSION_LOG_SETTINGS)

# Fallback aman: kalau YAML gagal load, semua multiplier jadi 0 supaya MEDIA_TYPES
# tetap bisa dibangun (bot tetap start), bukan KeyError saat import.
_multipliers = immersion_log_settings.get("points_multipliers", {})

# ⚠️ TAHAP 8 (PRICING_SYSTEM_REFACTOR.md — audit dead config/dead code):
# Field "short_id" DIHAPUS dari tiap entri di bawah. Ditelusuri seluruh
# fitur immersion (log_cog.py, stats_cog.py, goals_cog.py,
# bar_races_cog.py, helpers.py, semua file autocomplete/) — tidak ada
# satupun caller yang membaca MEDIA_TYPES[...]['short_id']. Dead sejak
# awal, kemungkinan sisa desain lama yang tidak jadi dipakai.

MEDIA_TYPES = {
    "Visual Novel": {
        "log_name": "Visual Novel (in characters read)",
        "max_logged": 2000000,
        "autocomplete": vn_name_autocomplete,
        "points_multiplier": _multipliers.get("Visual_Novel", 0),
        "thumbnail_query": CACHED_VNDB_THUMBNAIL_QUERY,
        "title_query": CACHED_VNDB_TITLE_QUERY,
        "unit_name": "character",
        "source_url": "https://vndb.org/",
        "Achievement_Group": "Visual Novel",
        "color": "#56B4E9",
    },
    "Manga": {
        "log_name": "Manga (in pages read)",
        "max_logged": 1000,
        "autocomplete": anime_manga_name_autocomplete,
        "points_multiplier": _multipliers.get("Manga", 0),
        "thumbnail_query": CACHED_ANILIST_THUMBNAIL_QUERY,
        "title_query": CACHED_ANILIST_TITLE_QUERY,
        "unit_name": "page",
        "source_url": "https://anilist.co/manga/",
        "Achievement_Group": "Manga",
        "color": "#D55E00",
    },
    "Anime": {
        "log_name": "Anime (in episodes watched)",
        "max_logged": 100,
        "autocomplete": anime_manga_name_autocomplete,
        "points_multiplier": _multipliers.get("Anime", 0),
        "thumbnail_query": CACHED_ANILIST_THUMBNAIL_QUERY,
        "title_query": CACHED_ANILIST_TITLE_QUERY,
        "unit_name": "episode",
        "source_url": "https://anilist.co/anime/",
        "Achievement_Group": "Anime",
        "color": "#F0E442",
    },
    "Book": {
        "log_name": "Book (in pages read)",
        "max_logged": 500,
        "autocomplete": None,
        "points_multiplier": _multipliers.get("Book", 0),
        "thumbnail_query": None,
        "title_query": None,
        "unit_name": "page",
        "source_url": None,
        "Achievement_Group": "Reading",
        "color": "#E69F00",
    },
    "Reading Time": {
        "log_name": "Reading Time (in minutes)",
        "max_logged": 1440,
        "autocomplete": None,
        "points_multiplier": _multipliers.get("Reading_Time", 0),
        "thumbnail_query": None,
        "title_query": None,
        "unit_name": "minute",
        "source_url": None,
        "Achievement_Group": "Reading",
        "color": "#009E73",
    },
    "Listening Time": {
        "log_name": "Listening Time (in minutes)",
        "max_logged": 1440,
        "autocomplete": listening_autocomplete,
        "points_multiplier": _multipliers.get("Listening_Time", 0),
        "thumbnail_query": CACHED_TMDB_THUMBNAIL_QUERY,
        "title_query": CACHED_TMDB_TITLE_QUERY,
        "unit_name": "minute",
        "source_url": "https://www.themoviedb.org/{tmdb_media_type}/",
        "Achievement_Group": "Listening",
        "color": "#0072B2",
    },
    "Reading": {
        "log_name": "Reading (in characters read)",
        "max_logged": 2000000,
        "autocomplete": None,
        "points_multiplier": _multipliers.get("Reading", 0),
        "thumbnail_query": None,
        "title_query": None,
        "unit_name": "character",
        "source_url": None,
        "Achievement_Group": "Reading",
        "color": "#CC79A7",
    },
}

LOG_CHOICES = [discord.app_commands.Choice(
    name=MEDIA_TYPES[media_type]['log_name'], value=media_type) for media_type in MEDIA_TYPES.keys()]