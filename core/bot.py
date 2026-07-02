import discord
from discord.ext import commands
import aiosqlite
import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger("bot.core")

# Tabel-tabel kecil yang dipakai lintas-fitur (shared/) dibuat sekali di sini,
# supaya shared/username_cache.py tidak perlu jadi Cog cuma demi cog_load().
SHARED_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS users (
        discord_user_id INTEGER PRIMARY KEY,
        user_name TEXT
    );
    """
]


class KotabiBot(commands.Bot):
    def __init__(
        self,
        command_prefix: str,
        features_folder: str = "features",
        path_to_db: str = "data/db.sqlite3",
        **options,
    ):
        intents = discord.Intents.all()
        super().__init__(command_prefix=command_prefix, intents=intents, **options)
        self.db_path = path_to_db
        self.features_folder = features_folder
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

    async def init_shared_tables(self):
        """Bikin tabel-tabel kecil lintas-fitur (mis. users) sekali saat startup."""
        for query in SHARED_TABLES:
            await self.RUN(query)

    def _discover_cog_modules(self, filter_names) -> list[str]:
        """
        Cari semua *_cog.py di dalam features/<nama_fitur>/ (satu level saja —
        TIDAK masuk ke sub-folder support/, karena isinya bukan Cog).

        Return list path module Python, misal:
            ["features.gatekeeper.gatekeeper_cog", "features.membership.admin_cog", ...]
        """
        base = Path(self.features_folder)
        modules = []

        for feature_dir in sorted(base.iterdir()):
            if not feature_dir.is_dir() or feature_dir.name.startswith("_"):
                continue
            for cog_file in sorted(feature_dir.glob("*_cog.py")):
                stem = cog_file.stem  # contoh: "admin_cog"
                if filter_names != "*" and stem not in filter_names and cog_file.name[:-3] not in filter_names:
                    continue
                module_path = f"{self.features_folder}.{feature_dir.name}.{stem}"
                modules.append(module_path)

        return modules

    async def load_cogs(self, cogs_to_load):
        """
        cogs_to_load = "*" → load semua *_cog.py di semua features/.
        cogs_to_load = list nama file (tanpa .py) → load cog spesifik saja,
        misal: python main.py gatekeeper_cog admin_cog
        """
        await self.init_shared_tables()

        modules = self._discover_cog_modules(cogs_to_load)

        for module_path in modules:
            try:
                await self.load_extension(module_path)
                logger.info(f"Loaded {module_path}")
            except Exception as e:
                logger.error(f"Gagal memuat {module_path}: {e}")