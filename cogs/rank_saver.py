import discord
import os
import yaml
import logging
from discord.ext import commands, tasks
from discord.utils import utcnow

# Mengimpor jantung bot asinkron dan helper konfigurasi Level 0
from core.bot import KotabiBot
from lib.config import get_channel_id

_log = logging.getLogger("bot.rank_saver")

# Konfigurasi pembacaan berkas pengaturan pengabaian peran
RANKSAVER_SETTINGS_PATH = os.getenv("ALT_RANKSAVER_SETTINGS_PATH") or "config/rank_saver_settings.yml"

try:
    with open(RANKSAVER_SETTINGS_PATH, "r", encoding="utf-8") as f:
        ranksaver_settings = yaml.safe_load(f) or {}
except Exception as e:
    _log.warning(f"⚠️ Berkas konfigurasi {RANKSAVER_SETTINGS_PATH} tidak ditemukan. Menggunakan pengaturan kosong: {e}")
    ranksaver_settings = {"role_ids_to_ignore": []}

CREATE_USER_RANKS_TABLE = """
CREATE TABLE IF NOT EXISTS user_ranks (
    guild_id INTEGER NOT NULL,
    discord_user_id INTEGER NOT NULL,
    role_ids TEXT NOT NULL,
    PRIMARY KEY (guild_id, discord_user_id)
);"""

GET_USER_ROLES_QUERY = """
SELECT role_ids FROM user_ranks
WHERE guild_id = ? AND discord_user_id = ?;"""

SAVE_USER_ROLE_QUERY = """
INSERT OR REPLACE INTO user_ranks (guild_id, discord_user_id, role_ids)
VALUES (?, ?, ?);"""


class RankSaver(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        """Mempersiapkan tabel penyimpanan peran di database SQLite saat modul dimuat."""
        await self.bot.RUN(CREATE_USER_RANKS_TABLE)

    @commands.Cog.listener()
    async def on_ready(self):
        """Memulai tugas harian pelacak dan penyimpan kasta jika belum berjalan."""
        if not self.rank_saver.is_running():
            _log.info("Starting rank saver task.")
            self.rank_saver.start()

    @tasks.loop(minutes=10.0)
    async def rank_saver(self):
        """Menyimpan seluruh data peran warga secara berkala (setiap 10 menit)."""
        all_role_ids_to_ignore = ranksaver_settings.get("role_ids_to_ignore", [])
        rows = []
        
        for guild in self.bot.guilds:
            # Saring warga asli yang bukan bot untuk disimpan perannya
            all_members = [member for member in guild.members if not member.bot]
            for member in all_members:
                # Kumpulkan peran yang bisa disematkan dan bukan peran yang diabaikan (seperti mute/event khusus)
                member_role_ids = [
                    str(role.id) for role in member.roles 
                    if role.is_assignable() and role.id not in all_role_ids_to_ignore
                ]
                role_ids_str = ",".join(member_role_ids)
                rows.append((guild.id, member.id, role_ids_str))

        if rows:
            await self.bot.RUN_MANY(SAVE_USER_ROLE_QUERY, rows)
            _log.info(f"💾 Berhasil mencadangkan gelar untuk {len(rows)} warga di {len(self.bot.guilds)} server.")

    @commands.Cog.listener(name="on_member_join")
    async def rank_restorer(self, member: discord.Member):
        """Otomatis memulihkan seluruh kasta dan gelar kehormatan warga saat masuk kembali ke server."""
        result = await self.bot.GET(GET_USER_ROLES_QUERY, (member.guild.id, member.id))
        
        if result:
            role_ids_str = result[0][0]
            role_ids = role_ids_str.split(",") if role_ids_str else []
            
            # Konversi ID teks ke objek Role Discord asli
            roles_to_restore = [
                discord.utils.get(member.guild.roles, id=int(role_id)) 
                for role_id in role_ids if discord.utils.get(member.guild.roles, id=int(role_id))
            ]
            
            all_role_ids_to_ignore = ranksaver_settings.get("role_ids_to_ignore", [])
            roles_to_restore = [role for role in roles_to_restore if role.id not in all_role_ids_to_ignore]
            
            if roles_to_restore:
                _log.info(f"Mengembalikan gelar warga {member.name} di server {member.guild.name}.")
                assignable_roles = [role for role in roles_to_restore if role.is_assignable()]
                await member.add_roles(*assignable_roles)

                # Ambil ID saluran join_log dinamis berdasarkan server_map Level 0
                join_log_channel_id = get_channel_id(member.guild.id, "join_log")
                to_restore_channel = member.guild.get_channel(join_log_channel_id)
                
                if not to_restore_channel:
                    to_restore_channel = member.guild.system_channel
                    if not to_restore_channel:
                        return

                # Desain visual pesan penyambutan kembali yang estetik dan ramah
                roles_mention_str = ", ".join([role.mention for role in assignable_roles])
                embed = discord.Embed(
                    title="⛵ Warga Kehormatan Berlabuh Kembali!",
                    description=(
                        f"Selamat datang kembali, {member.mention}!\n\n"
                        f"Sistem Kerajaan Kotabi telah memulihkan seluruh gelar kehormatan lama Anda:\n"
                        f"✨ {roles_mention_str}"
                    ),
                    color=discord.Color.gold(),
                    timestamp=utcnow()
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"ID Warga: {member.id}")

                await to_restore_channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none()
                )


async def setup(bot):
    await bot.add_cog(RankSaver(bot))