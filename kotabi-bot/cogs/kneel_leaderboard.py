import asyncio
from core.bot import KotabiBot
from typing import Union, Optional
from lib.messages import Msg

import discord
from discord.ext import commands

CREATE_KNEELS_TABLE = """
CREATE TABLE IF NOT EXISTS kneels (
    guild_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    discord_user_id INTEGER NOT NULL,
    kneel_score INTEGER NOT NULL,
    user_name TEXT,
    PRIMARY KEY (guild_id, message_id)
);"""

GET_USER_KNEELS_QUERY = """
SELECT SUM(kneel_score) AS total_kneel_score
FROM kneels
WHERE guild_id = ? AND discord_user_id = ?;"""

GET_TOP_KNEELS_QUERY = """
SELECT discord_user_id, user_name, SUM(kneel_score) AS total_kneel_score
FROM kneels
WHERE guild_id = ?
GROUP BY discord_user_id
ORDER BY total_kneel_score DESC
LIMIT 20;"""

UPDATE_USERNAME_QUERY = """
UPDATE kneels
SET user_name = ?
WHERE discord_user_id = ?;"""

UPDATE_KNEEL_SCORE_QUERY = """
INSERT INTO kneels (guild_id, message_id, discord_user_id, kneel_score, user_name)
VALUES (?,?,?,?,?)
ON CONFLICT (guild_id, message_id) DO UPDATE SET
    kneel_score = excluded.kneel_score,
    user_name = excluded.user_name;"""

FETCH_LOCK = asyncio.Lock()


async def _get_channel(bot: KotabiBot, channel_id: int) -> discord.TextChannel:
    channel = bot.get_channel(channel_id)
    if not channel:
        channel = await bot.fetch_channel(channel_id)
    return channel


async def _get_message(bot: KotabiBot, channel_id: int, message_id: int) -> discord.Message:
    channel = await _get_channel(bot, channel_id)
    message = discord.utils.get(bot.cached_messages, id=message_id)
    if not message:
        message = await channel.fetch_message(message_id)
    return message


async def is_kneel_emoji(emoji: Union[discord.Emoji, discord.PartialEmoji, str]) -> bool:
    emoji_str = str(emoji)
    if emoji_str in ["🧎", "🧎‍♂️", "🧎‍♀️"]:
        return True
    elif "ikneel" in emoji_str:
        return True
    elif isinstance(emoji, (discord.Emoji, discord.PartialEmoji)) and "ikneel" in str(emoji.name):
        return True
    else:
        return False


class Kneels(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        """Membuat tabel database saat modul dimuat."""
        await self.bot.RUN(CREATE_KNEELS_TABLE)

    async def update_kneel_score(self, payload: discord.RawReactionActionEvent):
        async with FETCH_LOCK:
            await asyncio.sleep(1)
            message = await _get_message(self.bot, payload.channel_id, payload.message_id)

            # Hitung total reaksi sujud kecuali dari penulis pesan itu sendiri
            kneel_count = len([
                reaction for reaction in message.reactions 
                if await is_kneel_emoji(reaction.emoji) and message.author.id != payload.user_id
            ])

            await self.bot.RUN(
                UPDATE_KNEEL_SCORE_QUERY, 
                (message.guild.id, message.id, message.author.id, kneel_count, message.author.display_name)
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Mendengarkan penambahan reaksi emoji."""
        if not await is_kneel_emoji(payload.emoji):
            return
        await self.update_kneel_score(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Mendengarkan pencabutan reaksi emoji."""
        if not await is_kneel_emoji(payload.emoji):
            return
        await self.update_kneel_score(payload)

    async def update_user_name(self, user_id, current_user_name):
        user = self.bot.get_user(user_id)
        if user and user.display_name != current_user_name:
            await self.bot.RUN(UPDATE_USERNAME_QUERY, (user.display_name, user_id))
            return user.display_name
        elif user and user.display_name == current_user_name:
            return current_user_name
        elif not user and current_user_name:
            return current_user_name
        else:
            async with FETCH_LOCK:
                await asyncio.sleep(1)
                try:
                    user = await self.bot.fetch_user(user_id)
                    if user:
                        await self.bot.RUN(UPDATE_USERNAME_QUERY, (user.display_name, user_id))
                        return user.display_name
                except discord.NotFound:
                    pass
                return 'Warga Misterius'

    @discord.app_commands.command(
        name="kneelderboard", 
        description="Tampilkan papan peringkat sujud hormat (berlutut) di Kerajaan Kotabi!"
    )
    @discord.app_commands.describe(guild_id="Ganti ID Server jika ingin meninjau sujud dari kerajaan lain (Opsional).")
    @discord.app_commands.guild_only()
    async def kneel_leaderboard(self, interaction: discord.Interaction, guild_id: Optional[str] = None):
        """Menampilkan daftar warga yang paling banyak menerima sujud hormat."""
        if guild_id and not guild_id.isdigit():
            await interaction.response.send_message(Msg.KNEEL_INVALID_GUILD_ID, ephemeral=True)
            return

        # Kirim status berpikir yang ramah & tematik
        await interaction.response.defer(thinking=True)
        
        target_guild_id = int(guild_id) if guild_id else interaction.guild.id
        leaderboard_data = await self.bot.GET(GET_TOP_KNEELS_QUERY, (target_guild_id,))
        
        if not leaderboard_data:
            await interaction.followup.send(Msg.KNEEL_NO_DATA)
            return

        # Resolusi emoji sujud kustom, fallback ke emoji standar jika tidak ada
        ikneel_emoji = discord.utils.get(interaction.guild.emojis, name="ikneel")
        if not ikneel_emoji:
            ikneel_emoji = "🧎"

        leaderboard_embed = discord.Embed(
            title=Msg.KNEEL_LEADERBOARD_TITLE, 
            color=discord.Color.blurple()
        )
        
        for index, (user_id, user_name, kneel_score) in enumerate(leaderboard_data):
            user_name = await self.update_user_name(user_id, user_name)
            leaderboard_embed.add_field(
                name=f"**{index + 1}. {user_name}**",
                value=f"{kneel_score} {ikneel_emoji}", 
                inline=True
            )

        # Ambil statistik pribadi pengakses
        user_kneels = await self.bot.GET_ONE(GET_USER_KNEELS_QUERY, (target_guild_id, interaction.user.id))
        try:
            total_personal = user_kneels[0] if user_kneels and user_kneels[0] is not None else 0
            leaderboard_embed.add_field(name=Msg.KNEEL_PERSONAL_FIELD, value=f"{total_personal} {ikneel_emoji}", inline=False)
        except (TypeError, IndexError):
            leaderboard_embed.add_field(name=Msg.KNEEL_PERSONAL_FIELD, value=f"0 {ikneel_emoji}", inline=False)

        await interaction.followup.send(embed=leaderboard_embed)


async def setup(bot):
    await bot.add_cog(Kneels(bot))