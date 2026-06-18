"""Watchdog cog — auto-reload cogs on file change + bot health monitor."""
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands, tasks

from lib.bot import KotabiBot

_log = logging.getLogger(__name__)

AUTHORIZED_USER_IDS = [int(uid) for uid in os.getenv("AUTHORIZED_USERS", "").split(",") if uid.strip()]
DEBUG_USER_ID: Optional[int] = int(os.getenv("DEBUG_USER", 0)) or None

# How often (seconds) to scan for file changes
FILE_SCAN_INTERVAL = 3

# How often (seconds) to run a health check
HEALTH_CHECK_INTERVAL = 60

# Max seconds bot is allowed to be unresponsive before we log a warning
HEALTH_WARN_THRESHOLD = 30


class Watchdog(commands.Cog):
    """
    Two-in-one watchdog:
    1. File watcher  — scans the cogs/ folder every few seconds and
       hot-reloads any .py file that has changed since it was last loaded.
    2. Health monitor — records the timestamp of every processed event and
       fires a warning if the bot appears to be stuck.
    """

    def __init__(self, bot: KotabiBot):
        self.bot = bot
        self.cog_folder = Path(bot.cog_folder)

        # Map of cog_module_name -> last known mtime
        self._mtimes: dict[str, float] = {}

        # Timestamp of the last observed bot activity
        self._last_heartbeat: float = time.monotonic()

        # Track whether we already warned about a stuck bot in this interval
        self._health_warned: bool = False

    # ------------------------------------------------------------------ #
    # lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def cog_load(self):
        # Snapshot current mtimes so we don't reload everything on startup
        self._snapshot_mtimes()
        self.file_watcher.start()
        self.health_monitor.start()
        _log.info("Watchdog started (file watcher + health monitor).")

    def cog_unload(self):
        self.file_watcher.cancel()
        self.health_monitor.cancel()
        _log.info("Watchdog stopped.")

    # ------------------------------------------------------------------ #
    # helpers                                                              #
    # ------------------------------------------------------------------ #

    def _snapshot_mtimes(self):
        """Record current modification times for all cog files."""
        for path in self.cog_folder.glob("*.py"):
            module = f"{self.cog_folder.name}.{path.stem}"
            self._mtimes[module] = path.stat().st_mtime

    def _module_to_path(self, module: str) -> Path:
        stem = module.split(".")[-1]
        return self.cog_folder / f"{stem}.py"

    def _beat(self):
        """Record that the bot is alive."""
        self._last_heartbeat = time.monotonic()
        self._health_warned = False

    async def _notify_debug_user(self, message: str):
        """DM the DEBUG_USER with a status message (best-effort)."""
        if not DEBUG_USER_ID:
            return
        try:
            user = self.bot.get_user(DEBUG_USER_ID) or await self.bot.fetch_user(DEBUG_USER_ID)
            await user.send(message)
        except Exception as exc:
            _log.warning("Could not DM debug user: %s", exc)

    # ------------------------------------------------------------------ #
    # task 1 — file watcher                                               #
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=FILE_SCAN_INTERVAL)
    async def file_watcher(self):
        for path in self.cog_folder.glob("*.py"):
            module = f"{self.cog_folder.name}.{path.stem}"
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue

            old_mtime = self._mtimes.get(module)

            # Brand-new file — load it
            if old_mtime is None:
                self._mtimes[module] = mtime
                try:
                    await self.bot.load_extension(module)
                    _log.info("[watchdog] Loaded new cog: %s", module)
                    await self._notify_debug_user(f"✅ **Watchdog** — loaded new cog: `{module}`")
                except Exception as exc:
                    _log.error("[watchdog] Failed to load new cog %s: %s", module, exc)
                continue

            # Modified file — reload it
            if mtime != old_mtime:
                self._mtimes[module] = mtime
                try:
                    await self.bot.reload_extension(module)
                    _log.info("[watchdog] Reloaded cog: %s", module)
                    await self._notify_debug_user(f"🔄 **Watchdog** — reloaded cog: `{module}`")
                except commands.ExtensionNotLoaded:
                    # Was never loaded (e.g. testing_ file), just track the mtime
                    pass
                except Exception as exc:
                    _log.error("[watchdog] Failed to reload cog %s: %s", module, exc)
                    await self._notify_debug_user(
                        f"❌ **Watchdog** — failed to reload `{module}`:\n```{exc}```"
                    )

    @file_watcher.before_loop
    async def _before_file_watcher(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    # task 2 — health monitor                                             #
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=HEALTH_CHECK_INTERVAL)
    async def health_monitor(self):
        elapsed = time.monotonic() - self._last_heartbeat
        if elapsed > HEALTH_WARN_THRESHOLD and not self._health_warned:
            msg = (
                f"⚠️ **Watchdog health alert** — bot has been silent for "
                f"`{int(elapsed)}s` (threshold: {HEALTH_WARN_THRESHOLD}s). "
                f"It may be stuck or rate-limited."
            )
            _log.warning("[watchdog] %s", msg)
            await self._notify_debug_user(msg)
            self._health_warned = True
        else:
            _log.debug("[watchdog] Health OK — last activity %.1fs ago.", elapsed)

    @health_monitor.before_loop
    async def _before_health_monitor(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    # heartbeat listeners — keep _last_heartbeat fresh                    #
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_message(self, _message: discord.Message):
        self._beat()

    @commands.Cog.listener()
    async def on_interaction(self, _interaction: discord.Interaction):
        self._beat()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, _payload):
        self._beat()

    @commands.Cog.listener()
    async def on_member_join(self, _member):
        self._beat()

    # ------------------------------------------------------------------ #
    # manual commands (authorized users only)                             #
    # ------------------------------------------------------------------ #

    def _is_authorized(self, ctx: commands.Context) -> bool:
        return ctx.author.id in AUTHORIZED_USER_IDS

    @commands.command(name="watchdog_status")
    async def watchdog_status(self, ctx: commands.Context):
        """Show current watchdog status."""
        if not self._is_authorized(ctx):
            return

        elapsed = time.monotonic() - self._last_heartbeat
        health = "✅ OK" if elapsed <= HEALTH_WARN_THRESHOLD else "⚠️ SLOW"
        cog_count = len(self._mtimes)

        embed = discord.Embed(title="Watchdog Status", color=discord.Color.green())
        embed.add_field(name="File Watcher", value=f"Scanning every `{FILE_SCAN_INTERVAL}s`\nTracking `{cog_count}` cog(s)", inline=True)
        embed.add_field(name="Health Monitor", value=f"{health}\nLast activity: `{elapsed:.1f}s` ago", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="watchdog_reload")
    async def watchdog_reload(self, ctx: commands.Context, cog_name: str):
        """Force-reload a cog by name (without .py)."""
        if not self._is_authorized(ctx):
            return

        module = f"{self.cog_folder.name}.{cog_name}"
        try:
            await self.bot.reload_extension(module)
            # Update tracked mtime
            path = self._module_to_path(module)
            if path.exists():
                self._mtimes[module] = path.stat().st_mtime
            await ctx.send(f"✅ Reloaded `{module}`.")
            _log.info("[watchdog] Manual reload of %s by %s", module, ctx.author)
        except Exception as exc:
            await ctx.send(f"❌ Failed to reload `{module}`:\n```{exc}```")


async def setup(bot: KotabiBot):
    await bot.add_cog(Watchdog(bot))
