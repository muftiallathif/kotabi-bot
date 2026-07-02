"""
shared/username_cache.py — Cache Username Lintas-Fitur
=========================================================
Dulu bernama cogs/username_fetcher.py dan berbentuk Cog (padahal tidak
punya slash command sendiri, cuma numpang cog_load() untuk bikin tabel).
Sekarang jadi modul biasa: fungsi get_username_db() bisa dipanggil dari
fitur manapun tanpa import lintas-folder yang rapuh.

Tabel `users` dibuat sekali oleh core/bot.py saat startup, bukan lewat
cog_load lagi.

Penggunaan:
    from shared.username_cache import get_username_db
    name = await get_username_db(bot, user_id)
"""

import asyncio
import discord

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    discord_user_id INTEGER PRIMARY KEY,
    user_name TEXT
);"""

UPDATE_USERNAME_QUERY = """
UPDATE users
SET user_name = ?
WHERE discord_user_id = ?;"""

INSERT_USER_QUERY = """
INSERT INTO users (discord_user_id, user_name)
VALUES (?, ?) ON CONFLICT(discord_user_id) DO UPDATE SET user_name = excluded.user_name;"""

FETCH_USER_QUERY = """
SELECT user_name FROM users WHERE discord_user_id = ?;"""

FETCH_LOCK = asyncio.Lock()


async def get_username_db(bot, user_id: int) -> str:
    user = bot.get_user(user_id)
    if user:
        await bot.RUN(INSERT_USER_QUERY, (user.id, user.display_name))
        return user.display_name
    user_name = await bot.GET_ONE(FETCH_USER_QUERY, (user_id,))
    if user_name:
        return user_name[0]
    async with FETCH_LOCK:
        await asyncio.sleep(1)
        user = await bot.fetch_user(user_id)
        if user:
            await bot.RUN(INSERT_USER_QUERY, (user.id, user.display_name))
            return user.display_name
        else:
            return 'Pengguna Tidak Dikenal'