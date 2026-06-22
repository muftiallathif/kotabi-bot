"""Cog yang memungkinkan pengguna membuat peran khusus (Custom Role) mandiri dengan nama, warna, dan ikon pribadi — BAGIAN 1."""

import re
import discord
from discord.ext import commands, tasks
from lib.bot import KotabiBot

# --- QUERY DATABASE SQLITE --- #

# Keterangan: Pembuatan tabel untuk menyimpan relasi data antara member dengan ID custom role buatan mereka sendiri.
CREATE_CUSTOM_ROLE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS custom_roles (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role_id INTEGER NOT NULL,
        role_name TEXT,
        PRIMARY KEY (guild_id, user_id))"""

# Keterangan: Query untuk mengambil seluruh data daftar custom role yang aktif di satu server tertentu.
GET_CUSTOM_ROLES_SQL = "SELECT * FROM custom_roles WHERE guild_id = ?"

# Keterangan: Query untuk mencatat riwayat pendaftaran data custom role baru milik member ke dalam database.
SET_CUSTOM_ROLE_SQL = """INSERT INTO custom_roles (guild_id, user_id, role_id, role_name)
                        VALUES (?, ?, ?, ?)"""

# Keterangan: Query untuk menghapus catatan data custom role milik member tertentu dari database.
DELETE_CUSTOM_ROLE_SQL = "DELETE FROM custom_roles WHERE guild_id = ? AND user_id = ?"

# Keterangan: Pembuatan tabel konfigurasi admin (siapa saja role yang boleh membuat, dan batas posisi penempatan role di Discord).
CREATE_CUSTOM_ROLE_SETTINGS_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS custom_role_settings (
        guild_id INTEGER NOT NULL,
        allowed_roles TEXT,
        reference_role_id INTEGER,
        reference_role_name TEXT,
        PRIMARY KEY (guild_id))"""

# Keterangan: Query untuk mengambil konfigurasi pengaturan sistem custom role di satu server tertentu.
GET_CUSTOM_ROLE_SETTINGS_SQL = "SELECT * FROM custom_role_settings WHERE guild_id = ?"

# Keterangan: Query untuk menyimpan konfigurasi pengaturan sistem custom role baru untuk satu server.
SET_CUSTOM_ROLE_SETTINGS_SQL = """INSERT INTO custom_role_settings (guild_id, allowed_roles, reference_role_id, reference_role_name)
                        VALUES (?, ?, ?, ?)"""

# Keterangan: Query untuk menghapus total data konfigurasi pengaturan sistem custom role dari server terkait.
DELETE_CUSTOM_ROLE_SETTINGS_SQL = "DELETE FROM custom_role_settings WHERE guild_id = ?"


class CustomRole(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        """Fungsi otomatis dari ekosistem discord.py yang dipicu saat file Cog ini pertama kali dimuat oleh bot."""
        # Menjalankan query pembuatan tabel database jika tabel belum tersedia saat bot dinyalakan
        await self.bot.RUN(CREATE_CUSTOM_ROLE_TABLE_SQL)
        await self.bot.RUN(CREATE_CUSTOM_ROLE_SETTINGS_TABLE_SQL)
        # Memulai tugas berulang otomatis (task loop) untuk memeriksa masa aktif/syarat role member
        self.strip_roles.start()

    async def get_custom_roles(self, guild_id):
        """Fungsi pembantu internal untuk menarik daftar seluruh data custom role di server dari database SQLite."""
        data = await self.bot.GET(GET_CUSTOM_ROLES_SQL, (guild_id,))
        if data:
            # Mengubah hasil mentah baris tabel database menjadi format struktur List Dictionary Python
            return [{"user_id": row[1], "role_id": row[2], "role_name": row[3]} for row in data]
        return []

    async def get_custom_role_settings(self, guild_id):
        """Fungsi pembantu internal untuk menarik data pengaturan administrasi sistem custom role dari server."""
        data = await self.bot.GET(GET_CUSTOM_ROLE_SETTINGS_SQL, (guild_id,))
        if data:
            # Mengubah baris pertama data menjadi format objek konfigurasi Dictionary Python
            return {"allowed_roles": data[0][1], "reference_role_id": data[0][2], "reference_role_name": data[0][3]}
        return []

    async def check_if_allowed(self, member: discord.Member, allowed_roles: str):
        """Fungsi internal untuk memeriksa apakah member yang mengetik perintah memiliki salah satu dari role syarat donatur/izin."""
        # Memecah string teks ID role (dipisah koma) dari database menjadi baris daftar angka Integer asli
        allowed_role_ids = [int(role_id) for role_id in allowed_roles.split(",")]
        # Mengembalikan nilai True jika ada salah satu ID role member yang cocok dengan daftar izin
        if any(role.id in allowed_role_ids for role in member.roles):
            return True
        return False

    async def clear_custom_role_data(self, guild: discord.Guild, member_id: int, role_id: int):
        """Fungsi internal untuk menghapus objek peran fisik dari server Discord sekaligus membersihkan baris datanya di SQLite."""
        custom_role = guild.get_role(role_id)
        if custom_role:
            await custom_role.delete()  # Menghapus paksa role dari server Discord asli
        # Menghapus catatan riwayat kepemilikan lama dari tabel database
        await self.bot.RUN(DELETE_CUSTOM_ROLE_SQL, (guild.id, member_id))

    @discord.app_commands.command(name="make_custom_role", description="Create a custom role for yourself.")
    @discord.app_commands.guild_only()
    @discord.app_commands.describe(
        role_name="Role name. Maximum of 14 symbols.",
        color_code="Hex color code. Example: #A47267",
        role_icon="Image that should be used.",
    )
    async def make_custom_role(self, interaction: discord.Interaction, role_name: str, color_code: str, role_icon: discord.Attachment = None):
        """Slash Command bagi pengguna berizin untuk merakit dan membakar custom role pribadi mereka ke profil server."""
        await interaction.response.defer()
        
        # LOGIKA 1: Validasi keberadaan data konfigurasi utama dari sistem kustomisasi server
        custom_role_settings = await self.get_custom_role_settings(interaction.guild.id)
        if not custom_role_settings:
            await interaction.followup.send("Custom role settings are missing. Please ask an admin to set them up.")
            return

        # LOGIKA 2: Memvalidasi objek reference role (Anchor Posisi). Penting agar posisi kustomisasi tidak melompati hak staf
        reference_role = interaction.guild.get_role(custom_role_settings["reference_role_id"])
        if not reference_role:
            await interaction.followup.send("The reference role for custom roles is missing.")
            return

        # LOGIKA 3: Validasi apakah pengguna yang memicu perintah memiliki izin (misal status Donatur VIP)
        allowed = await self.check_if_allowed(interaction.user, custom_role_settings["allowed_roles"])
        if not allowed:
            await interaction.followup.send("You are not allowed to create a custom role.")
            return

        # LOGIKA 4: Validasi batas panjang karakter teks agar nama role tidak merusak tata letak visual chat
        if len(role_name) > 14:
            await interaction.followup.send("Please use a shorter role name. Restrict yourself to 14 symbols.")
            return

        # LOGIKA 5: Validasi format kode warna Hex menggunakan rumus Regular Expression (RegEx)
        color_match = re.search(r"^#(?:[0-9a-fA-F]{3}){1,2}$", color_code)
        if not color_match:
            await interaction.followup.send("Please enter a valid hex color code. Example: `#A47267` ")
            return

        # LOGIKA 6: Memeriksa database. Jika pengguna sudah memiliki custom role lama, bersihkan data lamanya terlebih dahulu
        custom_role_data = await self.get_custom_roles(interaction.guild.id)
        for user_data in custom_role_data:
            if user_data["user_id"] == interaction.user.id:
                await self.clear_custom_role_data(interaction.guild, interaction.user.id, user_data["role_id"])

        # LOGIKA 7: Mencegah duplikasi nama role agar tidak mengacaukan penamaan sistem peran yang sudah ada di server
        if role_name in [role.name for role in interaction.guild.roles]:
            await interaction.followup.send("You can't use this role name. Try another one.")
            return

        # LOGIKA 8: Mengonversi string kode warna Hex (misal #A47267) menjadi angka berbasis 16 (Hexadecimal Integer) asli untuk Discord
        actual_color_code = int(re.findall(r"^#((?:[0-9a-fA-F]{3}){1,2})$", color_code)[0], base=16)
        discord_colour = discord.Colour(actual_color_code)

        # LOGIKA 9: Proses pembuatan objek role fisik di Discord (membedakan apakah memakai ikon gambar atau tidak)
        if role_icon:
            # Memastikan server memiliki jumlah Nitro Boost yang cukup untuk menyalakan fitur Ikon Peran (Role Icons)
            if not "ROLE_ICONS" in interaction.guild.features:
                await interaction.followup.send("This server doesn't have enough boosts to use custom role icons.")
                return
            display_icon = await role_icon.read()
            custom_role = await interaction.guild.create_role(name=role_name, colour=discord_colour, display_icon=display_icon)
        else:
            custom_role = await interaction.guild.create_role(name=role_name, colour=discord_colour)

        # LOGIKA 10: Mengunci penempatan posisi (Anchor). Custom role diletakkan tepat 1 tingkat di bawah role referensi (staf)
        positions = {custom_role: reference_role.position - 1}
        await interaction.guild.edit_role_positions(positions)
        
        # LOGIKA 11: Memberikan role baru tersebut ke profil pengguna dan mencatat riwayat suksesnya ke database SQLite
        await interaction.user.add_roles(custom_role)
        await self.bot.RUN(SET_CUSTOM_ROLE_SQL, (interaction.guild.id, interaction.user.id, custom_role.id, role_name))
        await interaction.followup.send(f"Created your custom role: {custom_role.mention}")

    @discord.app_commands.command(name="delete_custom_role", description="Remove a custom role from yourself.")
    @discord.app_commands.guild_only()
    async def delete_custom_role(self, interaction: discord.Interaction):
        """Slash Command bagi pengguna untuk menghapus custom role pribadi mereka secara mandiri."""
        await interaction.response.defer()
        custom_role_data = await self.get_custom_roles(interaction.guild.id)
        
        # Mencari ID pengguna di database, jika ditemukan langsung jalankan fungsi hapus bersih
        for user_data in custom_role_data:
            if user_data["user_id"] == interaction.user.id:
                await self.clear_custom_role_data(interaction.guild, interaction.user.id, user_data["role_id"])
                await interaction.followup.send("Deleted your custom role.")
                return

        await interaction.followup.send("You don't seem to have a custom role.")

    @discord.app_commands.command(name="_create_custom_role_settings", description="Set up custom role settings.")
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def create_custom_role_settings(self, interaction: discord.Interaction, reference_role: discord.Role):
        """Slash Command khusus Administrator untuk memunculkan menu interaktif (Dropdown Select) konfigurasi izin sistem."""
        await interaction.response.defer(ephemeral=True)
        view_object = discord.ui.View()
        # Membuat menu pilihan dropdown role di mana admin bisa memilih minimal 1 hingga maksimal 10 role donatur
        role_select = discord.ui.RoleSelect(min_values=1, max_values=10)

        async def role_select_callback(select_interaction: discord.Interaction):
            """Fungsi respon balik (Callback) setelah Administrator selesai memilih daftar role donatur di menu dropdown."""
            await select_interaction.response.defer()
            allowed_roles = [select_interaction.guild.get_role(
                int(role_id)) for role_id in select_interaction.data["values"]]
            # Menggabungkan daftar ID role yang dipilih menjadi satu baris teks string dipisah koma
            allowed_role_string = ",".join(select_interaction.data["values"])

            # Jika konfigurasi lama server sudah ada di database, hapus data lama terlebih dahulu sebelum ditimpa data baru
            custom_role_settings = await self.get_custom_role_settings(select_interaction.guild.id)
            if custom_role_settings:
                await self.bot.RUN(DELETE_CUSTOM_ROLE_SETTINGS_SQL, (select_interaction.guild.id,))
                
            # Simpan baris data konfigurasi administrasi terbaru ke tabel database SQLite
            await self.bot.RUN(SET_CUSTOM_ROLE_SETTINGS_SQL, (select_interaction.guild.id, allowed_role_string, reference_role.id, reference_role.name))
            await select_interaction.followup.send(f"Set up custom roles.\nRoles allowed: {', '.join([role.mention for role in allowed_roles])}\nReference role: {reference_role.mention}")

        role_select.callback = role_select_callback
        view_object.add_item(role_select)
        await interaction.followup.send("Select the roles that are allowed to create custom roles.", view=view_object)

    @tasks.loop(minutes=200)
    async def strip_roles(self):
        """Tugas otomatis (Background Task) yang berulang setiap 200 menit untuk menyapu dan membersihkan role ilegal."""
        for guild in self.bot.guilds:
            custom_role_settings = await self.get_custom_role_settings(guild.id)

            if not custom_role_settings:
                continue

            allowed_role_ids = [int(role_id) for role_id in custom_role_settings["allowed_roles"].split(",")]
            custom_role_data = await self.get_custom_roles(guild.id)

            for user_data in custom_role_data:
                member = guild.get_member(user_data["user_id"])
                
                # KONDISI A: Jika member ternyata sudah keluar dari server (Leave), langsung cabut data & hapus rolenya
                if not member:
                    await self.clear_custom_role_data(guild, user_data["user_id"], user_data["role_id"])
                    print(f"CUSTOM ROLE: Removed custom role from {str(member)}.")
                    continue

                # KONDISI B: Jika masa berlaku donatur habis (Member sudah tidak punya role syarat lagi), sita rolenya
                if not any(role.id in allowed_role_ids for role in member.roles):
                    await self.clear_custom_role_data(guild, user_data["user_id"], user_data["role_id"])
                    print(f"CUSTOM ROLE: Removed custom role from {str(member)}.")
                    continue

                role = guild.get_role(user_data["role_id"])

                # KONDISI C: Jika data peran fisik sudah tidak ditemukan di Discord (dihapus manual), hapus baris di SQLite
                if not role:
                    await self.clear_custom_role_data(guild, user_data["user_id"], user_data["role_id"])
                    print(f"CUSTOM ROLE: Removed custom role from {str(member)}.")
                    continue

                # KONDISI D: Jaring pengaman, jika role tersebut kosong tidak ada anggotanya sama sekali, hapus permanen
                if not role.members:
                    role_name = user_data["role_name"]
                    # Memperbaiki argumen: harus menyertakan member_id yang mengambil role tersebut
                    await self.clear_custom_role_data(guild, user_data["user_id"], user_data["role_id"])
                    print(f"CUSTOM ROLE: Deleted role {role_name} for user {user_data['user_id']}.")
                    continue


async def setup(bot):
    """Fungsi utama untuk mendaftarkan modul Cog CustomRole ini ke sistem inti Bot Kotabi."""
    await bot.add_cog(CustomRole(bot))