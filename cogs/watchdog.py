import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional
import discord
from discord.ext import commands, tasks
from core.bot import KotabiBot

_log = logging.getLogger(__name__)

AUTHORIZED_USER_IDS = [int(uid) for uid in os.getenv("AUTHORIZED_USERS", "").split(",") if uid.strip()]
DEBUG_USER_ID: Optional[int] = int(os.getenv("DEBUG_USER", 0)) or None

# Kontrol eksplisit: apakah file .py BARU di folder cogs/ boleh otomatis di-load
# tanpa restart manual. Default FALSE — file baru harus dimuat lewat restart bot
# (jalur deploy resmi/CI-CD, lihat DEVELOPMENT_GUIDE_v2.md §15), bukan otomatis
# oleh watchdog. Reload cog yang SUDAH ter-load (saat file-nya diedit) tetap
# berjalan otomatis seperti sebelumnya — itu kegunaan inti watchdog untuk dev.
WATCHDOG_AUTO_LOAD_NEW_COGS = os.getenv("WATCHDOG_AUTO_LOAD_NEW_COGS", "false").lower() == "true"

FILE_SCAN_INTERVAL = 3
HEALTH_CHECK_INTERVAL = 60
HEALTH_WARN_THRESHOLD = 120

class Watchdog(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot
        self.cog_folder = Path(bot.cog_folder)
        self._mtimes: dict[str, float] = {}
        self._last_heartbeat: float = time.monotonic()
        self._health_warned: bool = False

    async def cog_load(self):
        self._snapshot_mtimes()
        self.file_watcher.start()
        self.health_monitor.start()
        _log.info(
            "Watchdog aktif (pemantau file + monitor kesehatan). Auto-load cog baru: %s",
            "AKTIF" if WATCHDOG_AUTO_LOAD_NEW_COGS else "NONAKTIF (default aman)"
        )

    def cog_unload(self):
        self.file_watcher.cancel()
        self.health_monitor.cancel()
        _log.info("Watchdog berhenti.")

    def _snapshot_mtimes(self):
        for path in self.cog_folder.glob("*.py"):
            module = f"{self.cog_folder.name}.{path.stem}"
            self._mtimes[module] = path.stat().st_mtime

    def _module_to_path(self, module: str) -> Path:
        stem = module.split(".")[-1]
        return self.cog_folder / f"{stem}.py"

    def _beat(self):
        self._last_heartbeat = time.monotonic()
        self._health_warned = False

    async def _notify_debug_user(self, message: str):
        if not DEBUG_USER_ID:
            return
        try:
            user = self.bot.get_user(DEBUG_USER_ID) or await self.bot.fetch_user(DEBUG_USER_ID)
            await user.send(message)
        except Exception as exc:
            _log.warning("Gagal mengirim DM ke pengguna debug: %s", exc)

    @tasks.loop(seconds=FILE_SCAN_INTERVAL)
    async def file_watcher(self):
        for path in self.cog_folder.glob("*.py"):
            module = f"{self.cog_folder.name}.{path.stem}"
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue

            old_mtime = self._mtimes.get(module)

            if old_mtime is None:
                # File BARU terdeteksi — bukan reload cog yang sudah dikenal.
                self._mtimes[module] = mtime

                if not WATCHDOG_AUTO_LOAD_NEW_COGS:
                    _log.warning(
                        "[watchdog] File cog baru terdeteksi tapi TIDAK dimuat otomatis "
                        "(WATCHDOG_AUTO_LOAD_NEW_COGS=false): %s. "
                        "Restart bot atau set env var ini ke 'true' untuk memuatnya.",
                        module
                    )
                    await self._notify_debug_user(
                        f"⚠️ **Watchdog** — file cog baru terdeteksi tapi tidak dimuat otomatis: "
                        f"`{module}`. Restart bot untuk memuatnya."
                    )
                    continue

                try:
                    await self.bot.load_extension(module)
                    _log.info("[watchdog] Memuat modul baru: %s", module)
                    await self._notify_debug_user(f"✅ **Watchdog** — modul baru dimuat: `{module}`")
                except Exception as exc:
                    _log.error("[watchdog] Gagal memuat modul baru %s: %s", module, exc)
                continue

            if mtime != old_mtime:
                # Modul SUDAH dikenal (sudah ter-load sebelumnya) — reload otomatis tetap aman.
                self._mtimes[module] = mtime
                try:
                    await self.bot.reload_extension(module)
                    _log.info("[watchdog] Memuat ulang modul: %s", module)
                    await self._notify_debug_user(f"🔄 **Watchdog** — modul dimuat ulang: `{module}`")
                except commands.ExtensionNotLoaded:
                    pass
                except Exception as exc:
                    _log.error("[watchdog] Gagal memuat ulang modul %s: %s", module, exc)
                    await self._notify_debug_user(f"❌ **Watchdog** — gagal memuat ulang `{module}`:\n```{exc}```")

    @tasks.loop(seconds=HEALTH_CHECK_INTERVAL)
    async def health_monitor(self):
        elapsed = time.monotonic() - self._last_heartbeat
        if elapsed > HEALTH_WARN_THRESHOLD and not self._health_warned:
            msg = f"⚠️ **Peringatan kesehatan Watchdog** — bot tidak merespons selama `{int(elapsed)} detik` (ambang batas: {HEALTH_WARN_THRESHOLD} detik). Bot mungkin mengalami kemacetan."
            _log.warning("[watchdog] %s", msg)
            await self._notify_debug_user(msg)
            self._health_warned = True
        else:
            _log.debug("[watchdog] Kesehatan normal — aktivitas terakhir %.1fs lalu.", elapsed)

    @commands.Cog.listener()
    async def on_message(self, _message: discord.Message): self._beat()
    @commands.Cog.listener()
    async def on_interaction(self, _interaction: discord.Interaction): self._beat()
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, _payload): self._beat()
    @commands.Cog.listener()
    async def on_member_join(self, _member): self._beat()

    @commands.command(name="watchdog_status")
    async def watchdog_status(self, ctx: commands.Context):
        """Menampilkan status watchdog saat ini."""
        if ctx.author.id not in AUTHORIZED_USER_IDS: return
        elapsed = time.monotonic() - self._last_heartbeat
        health = "✅ Normal" if elapsed <= HEALTH_WARN_THRESHOLD else "⚠️ LAMBAT"
        embed = discord.Embed(title="Status Watchdog", color=discord.Color.green())
        embed.add_field(name="File Watcher", value=f"Pemindaian setiap `{FILE_SCAN_INTERVAL}s`", inline=True)
        embed.add_field(
            name="Auto-load Cog Baru",
            value="✅ Aktif" if WATCHDOG_AUTO_LOAD_NEW_COGS else "🔒 Nonaktif (default aman)",
            inline=True
        )
        embed.add_field(name="Monitor Kesehatan", value=f"{health}\nAktivitas terakhir: `{elapsed:.1f}s` lalu", inline=True)
        await ctx.send(embed=embed)

async def setup(bot: KotabiBot):
    await bot.add_cog(Watchdog(bot))