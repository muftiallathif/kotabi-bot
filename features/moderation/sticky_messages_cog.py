import asyncio

import discord
from discord.ext import commands

from core.bot import KotabiBot

CREATE_STICKY_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS sticky_messages (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    original_message_id INTEGER NOT NULL,
    stickied_message_id INTEGER,
    PRIMARY KEY (guild_id, channel_id));"""

GET_STICKY_MESSAGE = """
SELECT original_message_id, stickied_message_id 
FROM sticky_messages 
WHERE guild_id = ? AND channel_id = ?;"""

UPDATE_STICKY_MESSAGE = """
INSERT INTO sticky_messages (guild_id, channel_id, original_message_id, stickied_message_id)
VALUES (?, ?, ?, ?)
ON CONFLICT (guild_id, channel_id) DO UPDATE SET
original_message_id = excluded.original_message_id,
stickied_message_id = excluded.stickied_message_id;"""

DELETE_STICKY_MESSAGE = """
DELETE FROM sticky_messages 
WHERE guild_id = ? AND channel_id = ?;"""

FETCH_LOCK = asyncio.Lock()

class StickyMessages(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot
        self._sticky_locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, channel_id: int) -> asyncio.Lock:
        if channel_id not in self._sticky_locks:
            self._sticky_locks[channel_id] = asyncio.Lock()
        return self._sticky_locks[channel_id]

    async def cog_load(self):
        await self.bot.RUN(CREATE_STICKY_MESSAGES_TABLE)

    async def _get_message(self, channel_id: int, message_id: int) -> discord.Message:
        channel = self.bot.get_channel(channel_id)
        if not channel:
            channel = await self.bot.fetch_channel(channel_id)
        message = discord.utils.get(self.bot.cached_messages, id=message_id)
        if not message:
            message = await channel.fetch_message(message_id)
        return message

    @discord.app_commands.command(name="sticky_last_message", description="Jadikan pesan terakhir sebagai pesan tetap (sticky) di channel ini.")
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(manage_messages=True)
    async def sticky_last_message(self, interaction: discord.Interaction):
        await interaction.response.defer()

        async for message in interaction.channel.history(limit=5):
            if message.interaction:
                if message.interaction.id == interaction.id or message.interaction.name == "sticky_last_message":
                    continue
            last_message = message
            break

        sticky_message = await interaction.channel.send(
            f"📌 **Pesan Tetap:**\n\n{last_message.content}",
            embed=last_message.embeds[0] if last_message.embeds else None,
            files=[await attachment.to_file() for attachment in last_message.attachments]
        )

        await self.bot.RUN(UPDATE_STICKY_MESSAGE,
                           (interaction.guild_id,
                            interaction.channel_id,
                            last_message.id,
                            sticky_message.id))

        await interaction.followup.send("Pesan telah berhasil dijadikan pesan tetap!", ephemeral=True)

    @discord.app_commands.command(name="unsticky", description="Hapus pesan tetap dari channel ini.")
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(manage_messages=True)
    async def unsticky(self, interaction: discord.Interaction):
        await interaction.response.defer()

        sticky_data = await self.bot.GET_ONE(GET_STICKY_MESSAGE,
                                             (interaction.guild_id,
                                              interaction.channel_id))

        if not sticky_data:
            await interaction.followup.send("Tidak ditemukan pesan tetap di channel ini!", ephemeral=True)
            return

        try:
            _, stickied_message_id = sticky_data
            message = await self._get_message(interaction.channel_id, stickied_message_id)
            await message.delete()
        except discord.NotFound:
            pass

        await self.bot.RUN(DELETE_STICKY_MESSAGE,
                           (interaction.guild_id,
                            interaction.channel_id))

        await interaction.followup.send("Pesan tetap telah berhasil dihapus!", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        sticky_data = await self.bot.GET_ONE(GET_STICKY_MESSAGE,
                                             (message.guild.id,
                                              message.channel.id))

        if not sticky_data:
            return

        async with self._get_lock(message.channel.id):
            original_message_id, old_sticky_id = sticky_data

            try:
                if old_sticky_id:
                    old_sticky = await self._get_message(message.channel.id, old_sticky_id)
                    await old_sticky.delete()
            except discord.NotFound:
                pass

            try:
                original_message = await self._get_message(message.channel.id, original_message_id)

                new_sticky = await message.channel.send(
                    f"📌 **Pesan Tetap:**\n\n{original_message.content}",
                    embed=original_message.embeds[0] if original_message.embeds else None,
                    files=[await attachment.to_file() for attachment in original_message.attachments]
                )

                await self.bot.RUN(UPDATE_STICKY_MESSAGE,
                                   (message.guild.id,
                                    message.channel.id,
                                    original_message_id,
                                    new_sticky.id))

            except discord.NotFound:
                await self.bot.RUN(DELETE_STICKY_MESSAGE,
                                   (message.guild.id,
                                    message.channel.id))

async def setup(bot):
    await bot.add_cog(StickyMessages(bot))