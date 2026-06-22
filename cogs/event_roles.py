"""Cog yang berfungsi mengelola peran otomatis berbasis acara terjadwal (Scheduled Event) di Discord — BAGIAN 1.""" 

import discord
from discord.ext import commands, tasks
from lib.bot import KotabiBot

# --- QUERY DATABASE SQLITE --- #

# Keterangan: Pembuatan tabel untuk menyimpan relasi data antara ID Server, ID Event Terjadwal, dan ID Peran Khusus Event.
CREATE_EVENT_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS event_roles (
    guild_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, event_id)
);"""

# Keterangan: Query SQL untuk memasukkan atau memperbarui data pendaftaran peran khusus event baru.
INSERT_EVENT_ROLE = """
INSERT OR REPLACE INTO event_roles (guild_id, event_id, role_id)
VALUES (?, ?, ?);"""

# Keterangan: Query SQL untuk menarik seluruh data relasi peran event yang tersimpan di dalam database.
GET_ALL_EVENT_ROLES = """
SELECT guild_id, event_id, role_id FROM event_roles;"""

# Keterangan: Query SQL untuk menghapus baris data relasi peran event dari database ketika event selesai/dihapus.
DELETE_EVENT_ROLE = """
DELETE FROM event_roles WHERE guild_id = ? AND event_id = ?;"""


class EventRoles(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    def cog_unload(self):
        """Fungsi otomatis yang dipicu jika modul file Cog ini dimatikan atau di-reload oleh sistem utama bot."""
        self.sync_event_roles.cancel()  # Menghentikan paksa tugas perulangan waktu agar memori VPS bersih

    async def cog_load(self):
        """Fungsi otomatis dari ekosistem discord.py yang dipicu saat file Cog ini pertama kali dimuat oleh bot."""
        # Membuat tabel database event_roles jika tabel tersebut belum tersedia di database SQLite Anda
        await self.bot.RUN(CREATE_EVENT_ROLES_TABLE)
        # Memulai tugas pengecekan waktu berulang otomatis (task loop)
        self.sync_event_roles.start()

    async def create_event_role(self, event: discord.ScheduledEvent) -> discord.Role:
        """Fungsi internal untuk merakit peran fisik baru di Discord dengan format nama 'Event: [Nama Event]'."""
        role_name = f"Event: {event.name}"
        try:
            # Membuat objek role baru di server Discord asli dengan opsi mentionable diaktifkan
            role = await event.guild.create_role(
                name=role_name,
                mentionable=True,
                reason="Event role creation"
            )
            # Mencatat riwayat sukses pembuatan peran tersebut ke dalam tabel database SQLite Anda
            await self.bot.RUN(INSERT_EVENT_ROLE, (event.guild.id, event.id, role.id))

            # Melakukan perulangan asinkronus untuk menjaring semua member yang mengeklik tombol 'Interested' di event terkait
            async for user in event.users():
                member = event.guild.get_member(user.id)
                if member:
                    try:
                        # Masukkan role event tersebut ke profil member
                        await member.add_roles(role, reason="User interested in event")
                    except discord.Forbidden:
                        # Terjadi jika posisi hierarki role bot kalah tinggi dari role member target
                        print(f"Cannot add role to user {user.id} in guild {event.guild.id}")

            return role
        except discord.Forbidden:
            # Terjadi jika bot Anda tidak memiliki permission 'Manage Roles' yang aktif di Discord
            print(f"Missing permissions to create/manage roles in guild {event.guild.id}")
            return None

    async def cleanup_role(self, guild_id: int, role_id: int, event_id: int):
        """Fungsi internal untuk menghapus objek peran fisik dari server Discord sekaligus membersihkan baris datanya di SQLite ketika event berakhir."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            # Jika bot ternyata sudah keluar dari server tersebut, langsung bersihkan datanya di database
            await self.bot.RUN(DELETE_EVENT_ROLE, (guild_id, event_id))
            return

        role = guild.get_role(role_id)
        if role:
            try:
                # Hapus objek peran fisik dari pengaturan peran server Discord
                await role.delete(reason="Event ended or cancelled")
            except discord.Forbidden:
                print(f"Cannot delete role {role_id} in guild {guild_id}")

        # Hapus catatan riwayat peran terkait dari tabel database SQLite Anda
        await self.bot.RUN(DELETE_EVENT_ROLE, (guild_id, event_id))

    @tasks.loop(minutes=5)
    async def sync_event_roles(self):
        """Tugas otomatis (Background Task) yang berulang setiap 5 menit sekali untuk menyinkronkan status peran event di semua server."""
        event_roles = await self.bot.GET(GET_ALL_EVENT_ROLES)

        # LOGIKA SINKRONISASI 1: Membersihkan role jika event aslinya sudah selesai atau dibatalkan
        for guild_id, event_id, role_id in event_roles:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            event = guild.get_scheduled_event(event_id)
            if not event:
                await self.cleanup_role(guild_id, role_id, event_id)
                continue

            # Memeriksa jika status event sudah berstatus: ended, completed, atau cancelled
            if event.status in [discord.EventStatus.ended, discord.EventStatus.completed,
                                discord.EventStatus.cancelled, discord.EventStatus.canceled]:
                await self.cleanup_role(guild_id, role_id, event_id)
                continue

            role = guild.get_role(role_id)
            if not role:
                # Jaring pengaman: Jika data di DB ada tapi rolenya tidak sengaja terhapus manual di Discord, buat ulang
                await self.create_event_role(event)

        # LOGIKA SINKRONISASI 2: Membuat role otomatis jika ada event baru yang belum tercatat di database
        for guild in self.bot.guilds:
            for event in guild.scheduled_events:
                if event.status not in [discord.EventStatus.scheduled, discord.EventStatus.active]:
                    continue

                exists = any(event_role[0] == guild.id and event_role[1] == event.id for event_role in event_roles)
                if not exists:
                    await self.create_event_role(event)

    @commands.Cog.listener()
    async def on_scheduled_event_create(self, event: discord.ScheduledEvent):
        """Listener otomatis yang dipicu langsung oleh Discord tepat ketika admin membuat jadwal event baru."""
        await self.create_event_role(event)

    @commands.Cog.listener()
    async def on_scheduled_event_delete(self, event: discord.ScheduledEvent):
        """Listener otomatis yang dipicu langsung ketika admin membatalkan atau menghapus jadwal event."""
        role_data = await self.bot.GET_ONE("SELECT role_id FROM event_roles WHERE guild_id = ? AND event_id = ?",
                                           (event.guild.id, event.id))
        if role_data:
            await self.cleanup_role(event.guild.id, role_data[0], event.id)

    @commands.Cog.listener()
    async def on_scheduled_event_user_add(self, event: discord.ScheduledEvent, user: discord.User):
        """Listener otomatis yang dipicu langsung ketika ada member mengeklik tombol 'Interested' (Tertarik) pada event."""
        role_data = await self.bot.GET_ONE("SELECT role_id FROM event_roles WHERE guild_id = ? AND event_id = ?",
                                           (event.guild.id, event.id))
        if role_data:
            role = event.guild.get_role(role_data[0])
            if role:
                member = event.guild.get_member(user.id)
                if member:
                    try:
                        # Otomatis tempelkan role event ke profil member tersebut
                        await member.add_roles(role, reason="User interested in event")
                    except discord.Forbidden:
                        print(f"Cannot add role to user {user.id} in guild {event.guild.id}")

    @commands.Cog.listener()
    async def on_scheduled_event_user_remove(self, event: discord.ScheduledEvent, user: discord.User):
        """Listener otomatis yang dipicu langsung ketika member membatalkan tombol ketertarikan mereka pada event."""
        role_data = await self.bot.GET_ONE("SELECT role_id FROM event_roles WHERE guild_id = ? AND event_id = ?",
                                           (event.guild.id, event.id))
        if role_data:
            role = event.guild.get_role(role_data[0])
            if role:
                member = event.guild.get_member(user.id)
                if member:
                    try:
                        # Otomatis cabut kembali role event dari profil member tersebut
                        await member.remove_roles(role, reason="User no longer interested in event")
                    except discord.Forbidden:
                        print(f"Cannot remove role from user {user.id} in guild {event.guild.id}")

    @commands.Cog.listener()
    async def on_scheduled_event_update(self, before: discord.ScheduledEvent, after: discord.ScheduledEvent):
        """Listener otomatis yang memantau jika ada perubahan data atau status pada event terjadwal."""
        if before.status != after.status:
            # Jika status event berubah menjadi selesai atau dibatalkan, picu fungsi pembersihan role
            if after.status in [discord.EventStatus.ended, discord.EventStatus.completed,
                                discord.EventStatus.cancelled, discord.EventStatus.canceled]:
                role_data = await self.bot.GET_ONE("SELECT role_id FROM event_roles WHERE guild_id = ? AND event_id = ?",
                                                   (after.guild.id, after.id))
                if role_data:
                    role = after.guild.get_role(role_data[0])
                    if role:
                        await self.cleanup_role(after.guild.id, role.id, after.id)


async def setup(bot):
    """Fungsi utama untuk mendaftarkan modul Cog EventRoles ini ke sistem inti Bot Kotabi."""
    await bot.add_cog(EventRoles(bot))
