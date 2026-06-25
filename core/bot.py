import discord
from discord.ext import commands
import aiosqlite
import asyncio
import logging
import os

logger = logging.getLogger("bot.core")


class KotabiBot(commands.Bot):
    def __init__(
        self,
        command_prefix: str,
        cog_folder: str = "cogs",
        path_to_db: str = "data/db.sqlite3",
        **options,
    ):
        intents = discord.Intents.all()
        super().__init__(command_prefix=command_prefix, intents=intents, **options)
        self.db_path = path_to_db
        self.cog_folder = cog_folder
        self._db_lock = asyncio.Lock()

    async def RUN(self, query: str, parameters: tuple = ()) -> int:
        async with self._db_lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(query, parameters)
                await db.commit()
                return cursor.rowcount

    async def RUN_MANY(self, query: str, parameters_list: list) -> int:
        async with self._db_lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.executemany(query, parameters_list)
                await db.commit()
                return cursor.rowcount

    async def GET_ONE(self, query: str, parameters: tuple = ()):
        async with self._db_lock:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(query, parameters) as cursor:
                    return await cursor.fetchone()

    async def GET(self, query: str, parameters: tuple = ()):
        async with self._db_lock:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(query, parameters) as cursor:
                    return await cursor.fetchall()

    async def load_cogs(self, cogs_to_load):
        cogs = [
            cog for cog in os.listdir(self.cog_folder)
            if cog.endswith(".py")
            and not cog.startswith("_")
            and (cogs_to_load == "*" or cog[:-3] in cogs_to_load)
        ]

        for cog in cogs:
            cog_path = f"{self.cog_folder}.{cog[:-3]}"
            try:
                await self.load_extension(cog_path)
                logger.info(f"Loaded {cog_path}")
            except Exception as e:
                logger.error(f"Gagal memuat {cog_path}: {e}")