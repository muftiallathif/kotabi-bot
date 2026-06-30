import discord
from discord.ext import commands
import logging
import datetime

from lib.config import get_role_id, get_channel_id
from lib.messages import Msg   # ← baris baru

logger = logging.getLogger("bot.auto_receive")

class AutoReceive(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Otomatis memberikan role Drifter dan mengirim log sambutan saat warga baru bergabung."""
        guild = member.guild
        guild_id = guild.id

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

        join_log_id = get_channel_id(guild_id, "join_log")
        join_log_channel = guild.get_channel(join_log_id)

        if join_log_channel:
            role_assign_channel_id = get_channel_id(guild_id, 'role_assign')
            role_assign_channel = guild.get_channel(role_assign_channel_id)
            role_assign_mention = role_assign_channel.mention if role_assign_channel else '#role-assign'

            embed = discord.Embed(
                description=Msg.auto_receive_welcome(member.mention, role_assign_mention),
                color=discord.Color.light_gray(),
            )
            embed.set_author(
                name=member.display_name,
                icon_url=member.display_avatar.url,
            )
            embed.set_footer(text=f"ID: {member.id}")

            try:
                await join_log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"❌ Gagal mengirim pesan sambutan ke join-log: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Menangani pengambilan faksi otomatis ketika reaksi tombol emoji ditekan di saluran role-assign."""
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        role_assign_channel_id = get_channel_id(payload.guild_id, "role_assign")
        if payload.channel_id != role_assign_channel_id:
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

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
                    try:
                        await member.send(Msg.faction_left(role.name))
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
                        await member.send(f"Kamu keluar dari kubu **{role.name}**.")
                    except discord.Forbidden:
                        pass
                except Exception as e:
                    logger.error(f"❌ Gagal mencabut peran faksi {role_key} dari {member.name}: {e}")

async def setup(bot):
    await bot.add_cog(AutoReceive(bot))