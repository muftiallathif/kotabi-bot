import discord
from discord.ext import commands
import aiosqlite
import asyncio
import logging
import os

logger = logging.getLogger("bot.core")

class KotabiBot(commands.Bot):
    def __init__(self, command_prefix: str, path_to_db: str = "data/db.sqlite3", **options):
        intents = discord.Intents.all()
        super().__init__(command_prefix=command_prefix, intents=intents, **options)
        self.db_path = path_to_db
        self._db_lock = asyncio.Lock()

    async def RUN(self, query: str, parameters: tuple = ()) -> int:
        async with self._db_lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(query, parameters)
                await db.commit()
                return cursor.rowcount

    async def GET_ONE(self, query: str, parameters: tuple = ()):
        async with self._db_lock:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(query, parameters) as cursor:
                    return await cursor.fetchone()