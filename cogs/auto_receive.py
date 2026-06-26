import discord
from discord.ext import commands
import logging
import datetime

# Impor pembaca konfigurasi Level 0
from lib.config import get_role_id, get_channel_id

logger = logging.getLogger("bot.auto_receive")

class AutoReceive(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Otomatis memberikan role Drifter dan mengirim log sambutan saat warga baru bergabung."""
        guild = member.guild
        guild_id = guild.id

        # 1. Ambil ID peran Drifter secara dinamis dari server_map
        drifter_role_id = get_role_id(guild_id, "drifter")
        drifter_role = guild.get_role(drifter_role_id)

        if drifter_role:
            try:
                await member.add_roles(drifter_role)
                logger.info(f"✅ Berhasil menyematkan kasta Drifter ke warga baru: {member.name}")
            except Exception as e:
                logger.error(f"❌ Gagal menyematkan kasta Drifter ke {member.name}: {e}")
        else:
            logger.warning(f"⚠️ Peran 'drifter' tidak ditemukan di server_map.yml atau server Discord untuk Guild {guild_id}!")

        # 2. Kirim pesan log penyambutan ke saluran join-log
        join_log_id = get_channel_id(guild_id, "join_log")
        join_log_channel = guild.get_channel(join_log_id)

        if join_log_channel:
            role_assign_channel_id = get_channel_id(guild_id, 'role_assign')
            role_assign_channel = guild.get_channel(role_assign_channel_id)
            role_assign_mention = role_assign_channel.mention if role_assign_channel else '#role-assign'
            
            embed_welcome = discord.Embed(
                title="⛵ Kapal Baru Berlabuh!",
                description=(
                    f"Selamat datang di Kerajaan Kotabi, {member.mention}!\n"
                    f"Anda resmi menyandang kasta awal sebagai **{drifter_role.name if drifter_role else 'Drifter'}**.\n\n"
                    f"Silakan menuju ke saluran {role_assign_mention} untuk memilih kubu minat Anda!"
                ),
                color=discord.Color.light_gray(),
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed_welcome.set_thumbnail(url=member.display_avatar.url)
            embed_welcome.set_footer(text=f"ID Pengguna: {member.id}")
            try:
                await join_log_channel.send(embed=embed_welcome)
            except Exception as e:
                logger.error(f"❌ Gagal mengirim pesan sambutan ke join-log: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Menangani pengambilan faksi otomatis ketika reaksi tombol emoji ditekan di saluran role-assign."""
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        # Ambil ID saluran role-assign secara dinamis
        role_assign_channel_id = get_channel_id(payload.guild_id, "role_assign")
        if payload.channel_id != role_assign_channel_id:
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        # Pemetaan emoji reaksi ke nama kunci peran yang benar di server_map.yml (Telah diselaraskan)
        emoji_to_role = {
            "🎬": "faction_anime",
            "📚": "faction_bookworm",
            "🎮": "faction_gamer",
            "🎵": "faction_music",
            "🏯": "faction_history",
            "💬": "faction_kaiwa",
            "🦊": "faction_stream",
            "✍️": "faction_translator"
        }

        emoji_name = payload.emoji.name
        if emoji_name in emoji_to_role:
            role_key = emoji_to_role[emoji_name]
            role_id = get_role_id(payload.guild_id, role_key)
            role = guild.get_role(role_id)

            if role:
                try:
                    await member.add_roles(role)
                    # Kirim pesan sementara di DM agar warga tahu peran berhasil ditambahkan
                    try:
                        await member.send(f"✅ Anda berhasil bergabung dengan kubu faksi **{role.name}**!")
                    except discord.Forbidden:
                        pass
                except Exception as e:
                    logger.error(f"❌ Gagal memberikan peran faksi {role_key} ke {member.name}: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Menghapus faksi secara otomatis ketika reaksi emoji dicabut oleh warga."""
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        role_assign_channel_id = get_channel_id(payload.guild_id, "role_assign")
        if payload.channel_id != role_assign_channel_id:
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        # Pemetaan emoji reaksi ke nama kunci peran yang benar di server_map.yml (Telah diselaraskan)
        emoji_to_role = {
            "🎬": "faction_anime",
            "📚": "faction_bookworm",
            "🎮": "faction_gamer",
            "🎵": "faction_music",
            "🏯": "faction_history",
            "💬": "faction_kaiwa",
            "🦊": "faction_stream",
            "✍️": "faction_translator"
        }

        emoji_name = payload.emoji.name
        if emoji_name in emoji_to_role:
            role_key = emoji_to_role[emoji_name]
            role_id = get_role_id(payload.guild_id, role_key)
            role = guild.get_role(role_id)

            if role and role in member.roles:
                try:
                    await member.remove_roles(role)
                    try:
                        await member.send(f"🧹 Anda telah keluar dari kubu faksi **{role.name}**.")
                    except discord.Forbidden:
                        pass
                except Exception as e:
                    logger.error(f"❌ Gagal mencabut peran faksi {role_key} dari {member.name}: {e}")

async def setup(bot):
    await bot.add_cog(AutoReceive(bot))