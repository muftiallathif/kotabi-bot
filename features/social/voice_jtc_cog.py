"""
features/social/voice_jtc_cog.py — Join to Create (Voice Channel Dinamis)
=============================================================================
Mengganti "Study Room 1" & "Study Room 2" yang statis dengan satu channel
trigger "➕ Join to Create". Begitu warga join channel trigger ini, bot
otomatis membuatkan voice channel privat baru untuknya (di kategori yang
sama), lalu memindahkan warga tersebut ke sana. Channel yang dibuat akan
otomatis dihapus lagi begitu kosong ditinggalkan semua orang.

Channel trigger dikonfigurasi lewat shared/server_map.yml:
    channels:
      join_to_create: <ID voice channel trigger>

Tidak butuh tabel database — daftar channel yang sedang "hidup" cukup
disimpan in-memory (self._created_channels), karena kalau bot restart di
tengah jalan dan channel voice tsb kebetulan sudah kosong, on_ready akan
menyapu bersih sisa channel kosong yang masih tertinggal.
"""

import logging

import discord
from discord.ext import commands

from core.bot import KotabiBot
from shared.config import get_channel_id

_log = logging.getLogger("bot.voice_jtc")

JTC_NAME_PREFIX = "🎧"


class VoiceJoinToCreate(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot
        # channel_id voice yang dibuat otomatis oleh cog ini, per guild
        self._created_channels: set[int] = set()

    def _get_trigger_channel_id(self, guild_id: int) -> int:
        return get_channel_id(guild_id, "join_to_create")

    @commands.Cog.listener()
    async def on_ready(self):
        """Sapu bersih channel Join-to-Create yang kosong dari sesi sebelumnya (mis. setelah restart)."""
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                if channel.name.startswith(JTC_NAME_PREFIX) and len(channel.members) == 0:
                    try:
                        await channel.delete(reason="Sapu bersih Join-to-Create kosong saat startup")
                        _log.info("Menghapus channel JTC kosong peninggalan sesi lama: %s", channel.name)
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        pass

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        # 1. Warga JOIN channel trigger -> buatkan room baru & pindahkan
        trigger_id = self._get_trigger_channel_id(member.guild.id)
        if trigger_id and after.channel and after.channel.id == trigger_id:
            await self._create_room_for(member, after.channel)

        # 2. Warga LEAVE sebuah channel -> kalau itu room JTC yang kosong, hapus
        if before.channel and before.channel.id in self._created_channels:
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="Room Join-to-Create sudah kosong")
                    _log.info("Room JTC '%s' dihapus (kosong)", before.channel.name)
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass
                finally:
                    self._created_channels.discard(before.channel.id)

    async def _create_room_for(self, member: discord.Member, trigger_channel: discord.VoiceChannel):
        guild = member.guild
        room_name = f"{JTC_NAME_PREFIX} Ruang {member.display_name}"[:100]

        try:
            new_channel = await guild.create_voice_channel(
                name=room_name,
                category=trigger_channel.category,
                reason=f"Join-to-Create oleh {member} ({member.id})",
            )
            self._created_channels.add(new_channel.id)
            await member.move_to(new_channel, reason="Dipindahkan ke room Join-to-Create baru")
            _log.info("Room JTC baru dibuat untuk %s: %s", member, room_name)
        except discord.Forbidden:
            _log.warning("Tidak punya izin membuat/memindahkan voice channel untuk %s", member)
        except discord.HTTPException as e:
            _log.warning("Gagal membuat room JTC untuk %s: %s", member, e)


async def setup(bot: KotabiBot):
    await bot.add_cog(VoiceJoinToCreate(bot))