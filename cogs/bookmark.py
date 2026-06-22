"""Cog penanda pesan (Bookmark) ke DM pengguna via reaksi emoji.""" 

import asyncio
import discord
from discord.ext import commands
from lib.bot import KotabiBot
from .username_fetcher import get_username_db

# Keterangan: Membuat tabel database relasi antara pesan asli dengan pesan pengingat di DM.
CREATE_USER_BOOKMARKS_TABLE = """
CREATE TABLE IF NOT EXISTS user_bookmarks (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    message_link TEXT NOT NULL,
    dm_message_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, message_id));"""

# Keterangan: Membuat tabel hitungan jumlah total bookmark per pesan untuk papan peringkat (Leaderboard).
CREATE_BOOKMARKED_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS bookmarked_messages (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    message_author_id INTEGER NOT NULL,
    message_link TEXT NOT NULL,
    bookmark_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, message_id));"""

# Keterangan: Query SQL untuk memasukkan atau memperbarui total jumlah reaksi bookmark.
UPDATE_BOOKMARK_COUNT_QUERY = """
INSERT INTO bookmarked_messages (guild_id, channel_id, message_id, message_author_id, message_link, bookmark_count)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (guild_id, message_id) DO UPDATE SET
bookmark_count = ?;"""

# Keterangan: Query SQL untuk mencatat riwayat klaim bookmark baru oleh pengguna.
INSERT_USER_BOOKMARK_QUERY = """
INSERT INTO user_bookmarks (guild_id, channel_id, user_id, message_id, message_link, dm_message_id)
VALUES (?, ?, ?, ?, ?, ?);"""

# Keterangan: Query SQL untuk menghapus riwayat bookmark saat pengguna membatalkannya.
DELETE_USER_BOOKMARK_QUERY = """
DELETE FROM user_bookmarks WHERE user_id = ? AND dm_message_id = ?;"""

# Keterangan: Query SQL untuk mengecek apakah pengguna sudah mem-bookmark pesan tersebut sebelumnya.
CHECK_BOOKMARK_EXISTS_QUERY = """
SELECT 1 FROM user_bookmarks 
WHERE user_id = ? AND message_id = ?;"""

# Keterangan: Query SQL untuk menarik data 10 pesan dengan jumlah bookmark terbanyak di server.
GET_TOP_BOOKMARKS_QUERY = """
SELECT channel_id, message_id, message_author_id, message_link, bookmark_count
FROM bookmarked_messages
WHERE guild_id = ?
ORDER BY bookmark_count DESC
LIMIT 10;"""

# Keterangan: Query SQL untuk menghapus data dari papan peringkat jika pesan aslinya sudah dihapus.
DELETE_BOOKMARKED_MESSAGE_QUERY = """
DELETE FROM bookmarked_messages WHERE guild_id = ? AND message_id = ?;"""

# Keterangan: Mengunci alur ambil data pesan lintas channel agar tidak tabrakan proses asinkronus.
FETCH_LOCK = asyncio.Lock()


class Bookmarks(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot
        self.bookmark_emoji = "🔖"  # Tombol emoji untuk simpan ke DM
        self.remove_emoji = "❌"    # Tombol emoji untuk hapus dari DM

    async def cog_load(self):
        """Fungsi bawaan discord.py yang otomatis jalan saat modul ini pertama kali dimuat."""
        # Menjalankan perintah pembuatan tabel database saat bot menyala
        await self.bot.RUN(CREATE_USER_BOOKMARKS_TABLE)
        await self.bot.RUN(CREATE_BOOKMARKED_MESSAGES_TABLE)

    async def _get_message(self, channel_id: int, message_id: int) -> discord.Message:
        """Fungsi internal untuk mengambil objek pesan secara aman dari cache atau via API fetch."""
        channel = self.bot.get_channel(channel_id)
        if not channel:
            channel = await self.bot.fetch_channel(channel_id)
        message = discord.utils.get(self.bot.cached_messages, id=message_id)
        if not message:
            message = await channel.fetch_message(message_id)
        return message

    async def send_bookmark_dm(self, user: discord.User, message: discord.Message) -> discord.Message:
        """Fungsi untuk merakit kotak pesan Embed indah dan mengirimkannya langsung ke DM pengguna."""
        embed = discord.Embed(title=f"**Bookmark from {message.guild.name}**", description=message.content,
                              timestamp=message.created_at, color=discord.Color.blue())
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)

        files_to_send = []
        # Memeriksa lampiran berkas jika ada di dalam pesan asli
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type:
                    # Jika gambar, pasang langsung di dalam badan utama Embed
                    if attachment.content_type.startswith('image/'):
                        embed.set_image(url=attachment.url)
                        break

            # Mencatat link file berkas lampiran dan memisahkan video untuk dikirim sebagai file
            for idx, attachment in enumerate(message.attachments, 1):
                if attachment.content_type and attachment.content_type.startswith('video/'):
                    files_to_send.append(await attachment.to_file())
                embed.add_field(
                    name=f"Attachment {idx}",
                    value=f"[{attachment.filename}]({attachment.url})",
                    inline=False
                )

        # Menambahkan tautan tombol navigasi otomatis untuk loncat ke lokasi pesan asli di server
        embed.add_field(name="Source", value=f"[[Jump to message]]({message.jump_url})", inline=False)

        # Memastikan kamar saluran pesan pribadi (DM Channel) terbuka
        if not user.dm_channel:
            await user.create_dm()
        
        # Kirim embed beserta lampiran file video ke DM pengguna
        dm_message = await user.dm_channel.send(embed=embed, files=files_to_send)
        try:
            # Otomatis pin pesan tersebut di DM agar tidak hilang tenggelam chat lain
            await dm_message.pin()
        except discord.HTTPException:
            # Info jika batas maksimal pin bawaan Discord (50 pesan) sudah penuh
            await user.dm_channel.send("Reached 50 pinned messages limit. Unpin messages to pin more.")
            
        # Tambahkan tombol silang merah sebagai fitur hapus cepat bagi pengguna dari kamar DM
        await dm_message.add_reaction(self.remove_emoji)
        return dm_message

    async def update_bookmark_count(self, payload: discord.RawReactionActionEvent):
        """Fungsi internal untuk menghitung ulang dan memperbarui jumlah skor reaksi di database."""
        async with FETCH_LOCK:
            await asyncio.sleep(1)  # Jeda aman memastikan event reaksi Discord selesai diproses
            message = await self._get_message(payload.channel_id, payload.message_id)

        bookmark_count = 0
        # Melakukan perulangan untuk menghitung total emoji bookmark yang menempel pada pesan
        for reaction in message.reactions:
            if str(reaction.emoji) == self.bookmark_emoji:
                bookmark_count = reaction.count
                break

        # Menyimpan atau memperbarui akumulasi jumlah skor terbaru ke tabel database SQLite
        await self.bot.RUN(UPDATE_BOOKMARK_COUNT_QUERY,
                           (message.guild.id, message.channel.id, message.id, message.author.id,
                            message.jump_url, bookmark_count, bookmark_count))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Listener otomatis untuk mendeteksi setiap kali ada pengguna yang menambahkan reaksi emoji baru."""
        # Jika reaksi tersebut dipicu oleh akun bot itu sendiri, abaikan prosesnya
        if payload.user_id == self.bot.user.id:
            return

        # LOGIKA A: Jika reaksi terjadi di dalam DM (Pesan Pribadi, bukan di server)
        if payload.guild_id is None:
            # Jika pengguna menekan tanda silang merah, hapus riwayat bookmark dan bersihkan pesan DM-nya
            if str(payload.emoji) == self.remove_emoji:
                user = self.bot.get_user(payload.user_id)
                if not user:
                    user = await self.bot.fetch_user(payload.user_id)
                if not user.dm_channel:
                    await user.create_dm()

                try:
                    # Perbaikan: Menghapus berdasarkan dm_message_id yang tersimpan
                    await self.bot.RUN(DELETE_USER_BOOKMARK_QUERY, (payload.user_id, payload.message_id))
                    
                    # Hapus pesan fisik dari DM
                    channel = await self.bot.fetch_channel(payload.channel_id)
                    message = await channel.fetch_message(payload.message_id)
                    await message.delete()
                except Exception as e:
                    _log.error(f"Gagal menghapus bookmark di DM: {e}")
                return

        # LOGIKA B: Jika reaksinya bukan emoji bookmark, abaikan prosesnya
        if str(payload.emoji) != self.bookmark_emoji or payload.guild_id is None:
            return

        # Memeriksa ke database apakah pengguna ini sudah pernah mengklaim bookmark untuk pesan ini sebelumnya
        exists = await self.bot.GET_ONE(CHECK_BOOKMARK_EXISTS_QUERY,
                                        (payload.user_id, payload.message_id))

        # Jika data klaim sudah ada, cukup perbarui jumlah akumulasi skor totalnya saja
        if exists:
            await self.update_bookmark_count(payload)
            return

        # Jika klaim bookmark baru, ambil data objek pesan asli dan profil penggunanya
        async with FETCH_LOCK:
            message = await self._get_message(payload.channel_id, payload.message_id)
            user = self.bot.get_user(payload.user_id)
            if not user:
                user = await self.bot.fetch_user(payload.user_id)

        try:
            # Jalankan perintah pengiriman kotak pesan salinan Embed ke DM pengguna
            dm_message = await self.send_bookmark_dm(user, message)
        except discord.Forbidden:
            # Terjadi jika pengaturan privasi DM akun pengguna tersebut ditutup, batalkan eksekusi
            return

        # Rekam data rincian klaim penandaan sukses tersebut ke dalam tabel database SQLite
        await self.bot.RUN(INSERT_USER_BOOKMARK_QUERY,
                           (payload.guild_id, payload.channel_id, payload.user_id, payload.message_id,
                            message.jump_url, dm_message.id))

        # Perbarui papan klasemen akumulasi skor bookmark di server
        await self.update_bookmark_count(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Listener otomatis untuk mendeteksi ketika pengguna mencopot kembali emoji reaksi mereka di server."""
        if payload.guild_id is not None and str(payload.emoji) == self.bookmark_emoji:
            # Hitung ulang sisa akumulasi jumlah skor reaksi setelah dicopot oleh pengguna
            await self.update_bookmark_count(payload)

    @discord.app_commands.command(name="bookmarkboard", description="Shows most bookmarked messages")
    @discord.app_commands.guild_only()
    async def bookmark_leaderboard(self, interaction: discord.Interaction):
        """Slash Command publik untuk menampilkan daftar 10 pesan yang paling banyak disimpan oleh warga server."""
        await interaction.response.defer(thinking=True)

        # Mengambil data urutan top 10 pesan ber-bookmark terbanyak dari database
        leaderboard_data = await self.bot.GET(GET_TOP_BOOKMARKS_QUERY, (interaction.guild.id,))
        if not leaderboard_data:
            return await interaction.followup.send("No bookmarked messages found.")

        leaderboard_embed = discord.Embed(
            title="Most Bookmarked Messages",
            color=discord.Color.blue()
        )

        # Menyusun tampilan field klasemen berdasarkan data nama pembuat pesan asli dari database
        for index, (channel_id, message_id, author_id, message_link, bookmark_count) in enumerate(leaderboard_data, 1):
            author_name = await get_username_db(self.bot, author_id)
            leaderboard_embed.add_field(
                name=f"{index}. By {author_name} ({bookmark_count} bookmarks)",
                value=f"[Jump to message]({message_link})",
                inline=False
            )

        # Mengirimkan hasil cetakan papan peringkat ke channel tempat perintah dipicu
        await interaction.followup.send(embed=leaderboard_embed)

    @discord.app_commands.command(name="checkbookmarks", description="Check and remove deleted messages from bookmark leaderboard")
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def check_bookmarked_messages(self, interaction: discord.Interaction):
        """Slash Command khusus Administrator untuk membersihkan data sampah jika pesan aslinya sudah terhapus di server."""
        await interaction.response.defer(thinking=True)

        leaderboard_data = await self.bot.GET(GET_TOP_BOOKMARKS_QUERY, (interaction.guild.id,))
        if not leaderboard_data:
            return await interaction.followup.send("No bookmarked messages found.")

        removed_count = 0
        # Memeriksa status keberadaan fisik pesan asli di server satu per satu
        for channel_id, message_id, author_id, message_link, _ in leaderboard_data:
            try:
                await self._get_message(channel_id, message_id)
            except (discord.NotFound, discord.Forbidden):
                # Jika pesan asli tidak ditemukan/terhapus, bersihkan baris datanya dari database klasemen
                await self.bot.RUN(DELETE_BOOKMARKED_MESSAGE_QUERY, (interaction.guild.id, message_id))
                removed_count += 1
            except Exception as e:
                raise

        await interaction.followup.send(f"Cleanup complete. Removed {removed_count} deleted messages from bookmarks.")


async def setup(bot):
    """Fungsi utama dari sistem ekosistem discord.py untuk mendaftarkan modul Cog Bookmarks ini."""
    await bot.add_cog(Bookmarks(bot))
