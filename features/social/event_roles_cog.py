import discord
from discord.ext import commands, tasks
import logging

# Inisialisasi logger untuk melacak aktivitas manajemen peran event
logger = logging.getLogger("bot.event_roles")

# --- QUERY DATABASE SQLITE --- #

CREATE_EVENT_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS event_roles (
    guild_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, event_id)
);"""

INSERT_EVENT_ROLE = """
INSERT OR REPLACE INTO event_roles (guild_id, event_id, role_id)
VALUES (?, ?, ?);"""

GET_ALL_EVENT_ROLES = """
SELECT guild_id, event_id, role_id FROM event_roles;"""

DELETE_EVENT_ROLE = """
DELETE FROM event_roles WHERE guild_id = ? AND event_id = ?;"""


class EventRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Inisialisasi tabel database saat modul pertama kali dimuat."""
        await self.bot.RUN(CREATE_EVENT_ROLES_TABLE)
        self.sync_event_roles.start()

    def cog_unload(self):
        """Menghentikan task loop saat modul dinonaktifkan."""
        self.sync_event_roles.cancel()

    async def create_event_role(self, event: discord.ScheduledEvent) -> discord.Role:
        """Membuat peran khusus untuk event terjadwal dan menempelkannya ke pengguna yang tertarik."""
        role_name = f"Event: {event.name}"
        try:
            # Membuat peran baru di server Discord
            role = await event.guild.create_role(
                name=role_name,
                mentionable=True,
                reason="Pembuatan peran otomatis untuk event baru"
            )
            # Simpan relasi ke database
            await self.bot.RUN(INSERT_EVENT_ROLE, (event.guild.id, event.id, role.id))

            # Berikan peran tersebut ke setiap pengguna yang sudah menekan tombol 'Interested'
            async for user in event.users():
                member = event.guild.get_member(user.id)
                if member:
                    try:
                        await member.add_roles(role, reason="Pengguna tertarik dengan event")
                    except discord.Forbidden:
                        logger.warning(f"⚠️ Izin tidak cukup untuk memberikan peran event kepada {member.name}")
            
            logger.info(f"✅ Berhasil membuat peran event '{role_name}' di guild {event.guild.id}")
            return role
        except discord.Forbidden:
            logger.error(f"❌ Tidak memiliki izin 'Manage Roles' untuk membuat peran di guild {event.guild.id}")
            return None

    async def cleanup_role(self, guild_id: int, role_id: int, event_id: int):
        """Menghapus peran fisik dari Discord dan membersihkan datanya dari SQLite."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            await self.bot.RUN(DELETE_EVENT_ROLE, (guild_id, event_id))
            return

        role = guild.get_role(role_id)
        if role:
            try:
                await role.delete(reason="Event telah selesai atau dibatalkan")
                logger.info(f"🧹 Berhasil menghapus peran fisik event {role_id} di guild {guild_id}")
            except discord.Forbidden:
                logger.warning(f"⚠️ Gagal menghapus peran event {role_id} di guild {guild_id} karena masalah izin")

        await self.bot.RUN(DELETE_EVENT_ROLE, (guild_id, event_id))

    @tasks.loop(minutes=5)
    async def sync_event_roles(self):
        """Mengecek kelayakan peran event secara berkala setiap 5 menit."""
        event_roles = await self.bot.GET(GET_ALL_EVENT_ROLES)

        # 1. Bersihkan peran dari event yang sudah selesai/dibatalkan
        for guild_id, event_id, role_id in event_roles:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            event = guild.get_scheduled_event(event_id)
            if not event:
                await self.cleanup_role(guild_id, role_id, event_id)
                continue

            if event.status in [
                discord.EventStatus.ended, 
                discord.EventStatus.completed,
                discord.EventStatus.cancelled, 
                discord.EventStatus.canceled
            ]:
                await self.cleanup_role(guild_id, role_id, event_id)
                continue

            role = guild.get_role(role_id)
            if not role:
                # Jika peran terhapus manual di Discord tapi status event aktif, buat ulang
                await self.create_event_role(event)

        # 2. Daftarkan event aktif baru yang belum tercatat di database
        for guild in self.bot.guilds:
            for event in guild.scheduled_events:
                if event.status not in [discord.EventStatus.scheduled, discord.EventStatus.active]:
                    continue

                exists = any(er[0] == guild.id and er[1] == event.id for er in event_roles)
                if not exists:
                    await self.create_event_role(event)

    @sync_event_roles.before_loop
    async def before_sync_event_roles(self):
        """Menunda jalannya sinkronisasi sampai bot benar-benar terhubung ke Discord."""
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_scheduled_event_create(self, event: discord.ScheduledEvent):
        """Dipicu saat admin membuat jadwal event baru."""
        await self.create_event_role(event)

    @commands.Cog.listener()
    async def on_scheduled_event_delete(self, event: discord.ScheduledEvent):
        """Dipicu saat admin membatalkan atau menghapus jadwal event."""
        role_data = await self.bot.GET_ONE(
            "SELECT role_id FROM event_roles WHERE guild_id = ? AND event_id = ?",
            (event.guild.id, event.id)
        )
        if role_data:
            await self.cleanup_role(event.guild.id, role_data[0], event.id)

    @commands.Cog.listener()
    async def on_scheduled_event_user_add(self, event: discord.ScheduledEvent, user: discord.User):
        """Dipicu saat warga menekan tombol tertarik (Interested) pada event."""
        role_data = await self.bot.GET_ONE(
            "SELECT role_id FROM event_roles WHERE guild_id = ? AND event_id = ?",
            (event.guild.id, event.id)
        )
        if role_data:
            role = event.guild.get_role(role_data[0])
            if role:
                member = event.guild.get_member(user.id)
                if member:
                    try:
                        await member.add_roles(role, reason="Warga tertarik dengan event")
                    except discord.Forbidden:
                        logger.warning(f"⚠️ Gagal memberikan peran event kepada {member.name}")

    @commands.Cog.listener()
    async def on_scheduled_event_user_remove(self, event: discord.ScheduledEvent, user: discord.User):
        """Dipicu saat warga membatalkan status tertarik pada event."""
        role_data = await self.bot.GET_ONE(
            "SELECT role_id FROM event_roles WHERE guild_id = ? AND event_id = ?",
            (event.guild.id, event.id)
        )
        if role_data:
            role = event.guild.get_role(role_data[0])
            if role:
                member = event.guild.get_member(user.id)
                if member:
                    try:
                        await member.remove_roles(role, reason="Warga batal tertarik dengan event")
                    except discord.Forbidden:
                        logger.warning(f"⚠️ Gagal mencabut peran event dari {member.name}")

    @commands.Cog.listener()
    async def on_scheduled_event_update(self, before: discord.ScheduledEvent, after: discord.ScheduledEvent):
        """Memantau perubahan status event, bersihkan peran jika event selesai."""
        if before.status != after.status:
            if after.status in [
                discord.EventStatus.ended, 
                discord.EventStatus.completed,
                discord.EventStatus.cancelled, 
                discord.EventStatus.canceled
            ]:
                role_data = await self.bot.GET_ONE(
                    "SELECT role_id FROM event_roles WHERE guild_id = ? AND event_id = ?",
                    (after.guild.id, after.id)
                )
                if role_data:
                    await self.cleanup_role(after.guild.id, role_data[0], after.id)


async def setup(bot):
    await bot.add_cog(EventRoles(bot))