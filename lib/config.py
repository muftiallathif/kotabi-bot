import os
import yaml
import logging

logger = logging.getLogger("bot.config")
CONFIG_PATH = "config/server_map.yml"
_cache: dict = {}

def _load_yaml() -> dict:
    global _cache
    if _cache:
        return _cache
    if not os.path.exists(CONFIG_PATH):
        logger.warning(f"⚠️ File {CONFIG_PATH} tidak ditemukan!")
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _cache = yaml.safe_load(f) or {}
    return _cache

def reload_config():
    global _cache
    _cache = {}
    _load_yaml()
    logger.info("✅ server_map.yml berhasil di-reload.")

def get_role_id(guild_id: int, role_name: str) -> int:
    data = _load_yaml()
    role_id = data.get("roles", {}).get(role_name, 0)
    if not role_id:
        logger.warning(f"⚠️ Role '{role_name}' tidak ditemukan di server_map.yml")
    return int(role_id)

def get_channel_id(guild_id: int, channel_name: str) -> int:
    data = _load_yaml()
    channel_id = data.get("channels", {}).get(channel_name, 0)
    if not channel_id:
        logger.warning(f"⚠️ Channel '{channel_name}' tidak ditemukan di server_map.yml")
    return int(channel_id)
