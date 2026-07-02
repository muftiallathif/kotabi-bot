import discord
from discord.ext import commands
from discord import app_commands
import logging

from shared.config import get_channel_id
from shared.messages import Msg

logger = logging.getLogger("bot.bookmark")

CREATE_BOOKMARKS_TABLE = """
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    message_id INTEGER,
    channel_id INTEGER,
    author_id INTEGER,
    content TEXT,
    jump_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, message_id)
)
"""

SAVE_BOOKMARK_QUERY = """
INSERT OR IGNORE INTO bookmarks (guild_id, user_id, message_id, channel_id, author_id, content, jump_url)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

DELETE_BOOKMARK_QUERY = """
DELETE FROM bookmarks WHERE user_id = ? AND message_id = ?
"""

GET_USER_BOOKMARKS_QUERY = """
SELECT author_id, content, jump_url 
FROM bookmarks 
WHERE guild_id = ? AND user_id = ? 
ORDER BY created_at DESC LIMIT 10
"""


class Bookmark(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Inisialisasi tabel database secara asinkron saat cog dimuat."""
        await self.bot.RUN(CREATE_BOOKMARKS_TABLE)

    async def save_bookmark(self, guild_id: int, user_id: int, message: discord.Message) -> bool:
        """Menyimpan pesan yang di-bookmark ke database secara asinkron."""
        try:
            content = message.content or "[Pesan Berisi Media/Embed]"
            await self.bot.RUN(SAVE_BOOKMARK_QUERY, (
                guild_id,
                user_id,
                message.id,
                message.channel.id,
                message.author.id,
                content,
                message.jump_url
            ))
            return True
        except Exception as e:
            logger.error(f"❌ Gagal menyimpan bookmark ke database: {e}")
            return False

    async def delete_bookmark(self, user_id: int, message_id: int) -> bool:
        """Menghapus pesan dari daftar bookmark pengguna secara asinkron."""
        try:
            await self.bot.RUN(DELETE_BOOKMARK_QUERY, (user_id, message_id))
            return True
        except Exception as e:
            logger.error(f"❌ Gagal menghapus bookmark dari database: {e}")
            return False

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Mendengarkan reaksi emoji 🔖 untuk menyimpan pesan ke bookmark pengguna secara privat."""
        if payload.emoji.name != "🔖":
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception as e:
            logger.warning(f"⚠️ Tidak dapat mengambil pesan untuk dibookmark: {e}")
            return

        user = guild.get_member(payload.user_id)
        if not user or user.bot:
            return

        inserted = await self.save_bookmark(payload.guild_id, payload.user_id, message)

        if inserted:
            try:
                embed = discord.Embed(
                    title=Msg.BOOKMARK_SAVED_TITLE,
                    description=message.content or Msg.BOOKMARK_NO_TEXT_CONTENT,
                    color=discord.Color.gold(),
                    timestamp=message.created_at
                )
                embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
                embed.add_field(name=Msg.BOOKMARK_FIELD_CHANNEL, value=channel.mention, inline=True)
                embed.add_field(name=Msg.BOOKMARK_FIELD_JUMP_LINK, value=Msg.bookmark_jump_link(message.jump_url), inline=True)

                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.content_type and attachment.content_type.startswith("image/"):
                            embed.set_image(url=attachment.url)
                            break

                await user.send(embed=embed)
            except discord.Forbidden:
                # ✅ Pakai Msg.bookmark_dm_locked() dari lib/messages
                bot_commands_id = get_channel_id(payload.guild_id, "bot_commands")
                notify_channel = guild.get_channel(bot_commands_id)
                if notify_channel:
                    await notify_channel.send(
                        Msg.bookmark_dm_locked(user.mention),
                        delete_after=10
                    )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Menghapus pesan dari database ketika reaksi emoji 🔖 dicabut."""
        if payload.emoji.name != "🔖":
            return

        deleted = await self.delete_bookmark(payload.user_id, payload.message_id)
        if deleted:
            guild = self.bot.get_guild(payload.guild_id)
            if guild:
                user = guild.get_member(payload.user_id)
                if user:
                    try:
                        await user.send(Msg.BOOKMARK_REMOVED_DM)
                    except discord.Forbidden:
                        pass

    @app_commands.command(name="bookmarks", description="Melihat daftar pesan yang telah Anda simpan.")
    async def show_bookmarks(self, interaction: discord.Interaction):
        """Menampilkan daftar bookmark milik pengguna dalam bentuk ringkasan privat."""
        rows = await self.bot.GET(GET_USER_BOOKMARKS_QUERY, (interaction.guild_id, interaction.user.id))

        if not rows:
            # ✅ Pakai Msg.BOOKMARK_NO_DATA dari lib/messages
            await interaction.response.send_message(Msg.BOOKMARK_NO_DATA, ephemeral=True)
            return

        embed = discord.Embed(
            title=Msg.BOOKMARK_LIST_TITLE,
            description=Msg.BOOKMARK_LIST_INTRO,
            color=discord.Color.gold()
        )

        for idx, row in enumerate(rows, 1):
            author_id, content, jump_url = row
            author = interaction.guild.get_member(author_id)
            author_name = author.display_name if author else "Warga Asing"

            short_content = content[:80] + "..." if len(content) > 80 else content
            embed.description += f"{idx}. **{author_name}**: {short_content}\n🔗 [Lihat Pesan]({jump_url})\n\n"

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Bookmark(bot))