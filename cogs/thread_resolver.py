from lib.bot import KotabiBot
import discord
import os
import yaml
import asyncio
from datetime import timedelta
from discord.ext import commands, tasks
import logging

_log = logging.getLogger(__name__)

THREAD_RESOLVER_SETTINGS_PATH = os.getenv("ALT_THREAD_RESOLVER_SETTINGS") or "config/thread_resolver_settings.yml"
with open(THREAD_RESOLVER_SETTINGS_PATH, "r", encoding="utf-8") as f:
    thread_resolver_settings = yaml.safe_load(f)

async def _get_channel(bot: KotabiBot, channel_id: int) -> discord.TextChannel:
    channel = bot.get_channel(channel_id)
    if not channel:
        channel = await bot.fetch_channel(channel_id)
    return channel

async def _get_message(bot: KotabiBot, channel_id: int, message_id: int) -> discord.Message:
    if not message_id:
        return None
    channel = await _get_channel(bot, channel_id)
    message = discord.utils.get(bot.cached_messages, id=message_id)
    if not message:
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            return None
    return message

class Resolver(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        self.ask_if_solved.start()

    async def get_guild_help_forums(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        return [channel for channel in guild.forums if channel.id in thread_resolver_settings[guild_id]]

    @discord.app_commands.command(name="solved", description="Menandai thread bantuan sebagai sudah selesai (solved).")
    async def solved(self, interaction: discord.Interaction):
        if interaction.guild_id not in thread_resolver_settings:
            return await interaction.response.send_message("Server ini tidak memiliki saluran bantuan yang terkonfigurasi.", ephemeral=True)
        if not isinstance(interaction.channel, discord.Thread):
            return await interaction.response.send_message("Perintah ini hanya dapat digunakan di dalam thread bantuan.", ephemeral=True)
        
        question_forums = await self.get_guild_help_forums(interaction.guild_id)
        if interaction.channel.parent not in question_forums:
            return await interaction.response.send_message("Saluran ini bukan merupakan saluran bantuan.", ephemeral=True)
        
        if not "[TERSELESAIKAN]" in interaction.channel.name or interaction.channel.archived:
            await interaction.response.send_message(f'{interaction.user.mention} menutup thread ini.')
        else:
            await interaction.response.send_message("Thread ini sudah ditandai sebagai terselesaikan.", ephemeral=True)
        await self.mark_thread_as_solved(interaction.channel)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if thread.guild.id not in thread_resolver_settings:
            return
        if thread.parent.id not in thread_resolver_settings[thread.guild.id]:
            return

        # Bug fix: beri batas retry (maks ~30 detik) supaya tidak infinite loop
        # kalau thread.last_message_id tidak pernah ter-populate pada objek ini.
        max_attempts = 10
        for _ in range(max_attempts):
            if thread.last_message_id:
                break
            await asyncio.sleep(3)
        else:
            _log.warning(
                "Thread %s (%d) tidak mendapat last_message_id setelah %d detik, melanjutkan tanpa menunggu.",
                thread.name, thread.id, max_attempts * 3
            )

        if not thread.owner:
            return
        await thread.send(f'{thread.owner.mention} Harap gunakan perintah `/solved` jika masalah Anda sudah terselesaikan.')

    async def mark_thread_as_solved(self, thread: discord.Thread):
        new_thread_name = "[TERSELESAIKAN] " + thread.name if not "[TERSELESAIKAN]" in thread.name else thread.name
        if len(new_thread_name) > 100:
            new_thread_name = new_thread_name[:97] + "..."
        await thread.edit(reason='Ditandai sebagai terselesaikan.', name=new_thread_name, archived=True)

    async def ask_if_solved_for_guild(self, guild: discord.Guild):
        question_forums = await self.get_guild_help_forums(guild.id)
        if not question_forums:
            return
        for question_forum in question_forums:
            for thread in question_forum.threads:
                if "[TERSELESAIKAN]" in thread.name and not thread.archived:
                    await self.mark_thread_as_solved(thread)
                    continue
                elif thread.archived and "[TERSELESAIKAN]" not in thread.name:
                    await self.mark_thread_as_solved(thread)
                    continue
                elif thread.archived and "[TERSELESAIKAN]" in thread.name:
                    continue

                last_message = await _get_message(self.bot, thread.id, thread.last_message_id)
                if not last_message:
                    if discord.utils.utcnow() - thread.created_at > timedelta(days=30):
                        await self.mark_thread_as_solved(thread)
                    continue
                if discord.utils.utcnow() - last_message.created_at > timedelta(days=30):
                    await self.mark_thread_as_solved(thread)
                    continue
                if not thread.owner:
                    await self.mark_thread_as_solved(thread)
                    continue
                if discord.utils.utcnow() - last_message.created_at > timedelta(hours=48):
                    await thread.send(f'{thread.owner.mention} apakah masalah Anda sudah terselesaikan? Jika ya, silakan gunakan perintah `/solved` untuk menutup thread ini.')
                    continue

    @tasks.loop(hours=1)
    async def ask_if_solved(self):
        for guild in self.bot.guilds:
            if guild.id not in thread_resolver_settings:
                continue
            else:
                await self.ask_if_solved_for_guild(guild)

async def setup(bot):
    await bot.add_cog(Resolver(bot))