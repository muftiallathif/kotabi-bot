import discord
from discord.ext import commands
from discord import app_commands
import logging

from lib.config import get_channel_id

logger = logging.getLogger("bot.bookmark")

class Bookmark(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Inisialisasi tabel database secara asinkron saat cog dimuat."""
        await self.bot.RUN("""
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
        """)

    async def save_bookmark(self, guild_id: int, user_id: int, message: discord.Message) -> bool:
        """Menyimpan pesan yang di-bookmark ke database secara asinkron."""
        try:
            content = message.content or "[Pesan Berisi Media/Embed]"
            await self.bot.RUN("""
                INSERT OR IGNORE INTO bookmarks (guild_id, user_id, message_id, channel_id, author_id, content, jump_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
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
            await self.bot.RUN("DELETE FROM bookmarks WHERE user_id = ? AND message_id = ?", (user_id, message_id))
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

        # Simpan ke database menggunakan metode asinkron baru
        inserted = await self.save_bookmark(payload.guild_id, payload.user_id, message)

        if inserted:
            try:
                # Kirim rincian pesan ke DM pengguna secara rapi dan estetik
                embed = discord.Embed(
                    title="📌 Pesan Berhasil Disimpan!",
                    description=message.content or "_Pesan ini tidak memiliki teks (mungkin gambar atau berkas)._",
                    color=discord.Color.gold(),
                    timestamp=message.created_at
                )
                embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
                embed.add_field(name="Saluran Asal", value=channel.mention, inline=True)
                embed.add_field(name="Tautan Pesan", value=f"[Lompat ke Pesan]({message.jump_url})", inline=True)

                # Lampirkan gambar jika pesan berisi gambar
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.content_type and attachment.content_type.startswith("image/"):
                            embed.set_image(url=attachment.url)
                            break

                await user.send(embed=embed)
            except discord.Forbidden:
                # Jika DM ditutup, kirim notifikasi sementara di saluran bot-commands agar tidak mengotori obrolan umum
                bot_commands_id = get_channel_id(payload.guild_id, "bot_commands")
                notify_channel = guild.get_channel(bot_commands_id)
                if notify_channel:
                    await notify_channel.send(
                        f"⚠️ {user.mention}, pesan berhasil disimpan! Namun, kami gagal mengirim detailnya ke DM Anda karena DM Anda terkunci.",
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
                        await user.send("🧹 Pesan telah dihapus dari daftar bookmark kerajaan Anda.")
                    except discord.Forbidden:
                        pass

    @app_commands.command(name="bookmarks", description="Melihat daftar pesan yang telah Anda simpan.")
    async def show_bookmarks(self, interaction: discord.Interaction):
        """Menampilkan daftar bookmark milik pengguna dalam bentuk ringkasan privat."""
        guild_id = interaction.guild_id
        user_id = interaction.user.id

        # Mengambil data secara asinkron dari core database manager
        rows = await self.bot.GET("""
            SELECT author_id, content, jump_url 
            FROM bookmarks 
            WHERE guild_id = ? AND user_id = ? 
            ORDER BY created_at DESC LIMIT 10
        """, (guild_id, user_id))

        if not rows:
            await interaction.response.send_message("📖 Anda belum memiliki pesan yang disimpan. Berikan reaksi emoji 🔖 pada pesan mana pun untuk menyimpannya!", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔖 Perpustakaan Bookmark Pribadi",
            description="Berikut adalah 10 pesan terakhir yang Anda simpan:\n\n",
            color=discord.Color.gold()
        )

        for idx, row in enumerate(rows, 1):
            author_id, content, jump_url = row
            author = interaction.guild.get_member(author_id)
            author_name = author.display_name if author else "Warga Asing"

            # Potong teks jika terlalu panjang agar muat di embed
            short_content = content[:80] + "..." if len(content) > 80 else content
            embed.description += f"{idx}. **{author_name}**: {short_content}\n🔗 [Lihat Pesan]({jump_url})\n\n"

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Bookmark(bot))