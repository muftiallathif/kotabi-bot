"""
features/moderation/quiz_forum_cog.py — Auto-Cleanup Forum Quiz Public
=========================================================================
Dulu ada 3 channel teks terpisah (quiz-public-1/2/3) untuk kuis biasa,
latihan, dan duel santai (bukan untuk naik kasta — itu tugas quiz-rank-up).
Sekarang digabung jadi SATU Forum Channel: satu thread = satu sesi kuis.

Cog ini menjaga forum supaya tidak dipenuhi thread basi:
  - Thread yang tidak ada aktivitas baru selama QUIZ_THREAD_INACTIVE_DAYS
    hari akan di-archive otomatis (bukan dihapus — histori tetap ada,
    tinggal di-unarchive manual kalau memang perlu dilanjut).
  - Dicek setiap QUIZ_FORUM_SCAN_INTERVAL_HOURS jam.

Nilai default 3 hari bisa diubah lewat env var QUIZ_THREAD_INACTIVE_DAYS
tanpa perlu ubah kode.
"""

import os
import logging
from datetime import timedelta

import discord
from discord.ext import commands, tasks

from core.bot import KotabiBot
from shared.config import get_channel_id

_log = logging.getLogger("bot.quiz_forum")

QUIZ_THREAD_INACTIVE_DAYS = int(os.getenv("QUIZ_THREAD_INACTIVE_DAYS", "3"))
QUIZ_FORUM_SCAN_INTERVAL_HOURS = int(os.getenv("QUIZ_FORUM_SCAN_INTERVAL_HOURS", "1"))


async def _get_last_activity(bot: KotabiBot, thread: discord.Thread):
    """Ambil waktu aktivitas terakhir thread (pesan terakhir, atau waktu dibuat kalau kosong)."""
    if thread.last_message_id:
        cached = discord.utils.get(bot.cached_messages, id=thread.last_message_id)
        if cached:
            return cached.created_at
        try:
            last_message = await thread.fetch_message(thread.last_message_id)
            return last_message.created_at
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    return thread.created_at or discord.utils.utcnow()


class QuizForumCleanup(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        if not self.cleanup_quiz_forum.is_running():
            self.cleanup_quiz_forum.start()

    def cog_unload(self):
        self.cleanup_quiz_forum.cancel()

    def _get_forum(self, guild: discord.Guild) -> discord.ForumChannel | None:
        forum_id = get_channel_id(guild.id, "quiz_public_forum")
        if not forum_id:
            return None
        channel = guild.get_channel(forum_id)
        return channel if isinstance(channel, discord.ForumChannel) else None

    @tasks.loop(hours=QUIZ_FORUM_SCAN_INTERVAL_HOURS)
    async def cleanup_quiz_forum(self):
        threshold = discord.utils.utcnow() - timedelta(days=QUIZ_THREAD_INACTIVE_DAYS)

        for guild in self.bot.guilds:
            forum = self._get_forum(guild)
            if not forum:
                continue

            for thread in list(forum.threads):
                if thread.archived or thread.locked:
                    continue
                try:
                    last_activity = await _get_last_activity(self.bot, thread)
                except Exception as e:
                    _log.warning("Gagal cek aktivitas thread %s: %s", thread.id, e)
                    continue

                if last_activity < threshold:
                    try:
                        await thread.edit(
                            archived=True,
                            reason=f"Tidak ada aktivitas selama {QUIZ_THREAD_INACTIVE_DAYS} hari",
                        )
                        _log.info(
                            "Thread kuis '%s' (%d) di-archive otomatis (tidak aktif sejak %s)",
                            thread.name, thread.id, last_activity,
                        )
                    except discord.Forbidden:
                        _log.warning("Tidak punya izin meng-archive thread %s", thread.id)
                    except discord.HTTPException as e:
                        _log.warning("Gagal meng-archive thread %s: %s", thread.id, e)

    @cleanup_quiz_forum.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()


async def setup(bot: KotabiBot):
    await bot.add_cog(QuizForumCleanup(bot))