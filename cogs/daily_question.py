import discord
from discord.ext import commands
from discord import app_commands
import re
import logging

from lib.config import get_role_id

logger = logging.getLogger("bot.custom_role")

class CustomRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Inisialisasi tabel database peran kustom milik pengguna secara asinkron."""
        await self.bot.RUN("""
            CREATE TABLE IF NOT EXISTS custom_roles (
                guild_id INTEGER,
                user_id INTEGER,
                role_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

    async def get_user_custom_role(self, guild_id: int, user_id: int) -> int:
        """Mengambil ID peran kustom milik pengguna dari database secara asinkron."""
        row = await self.bot.GET_ONE(
            "SELECT role_id FROM custom_roles WHERE guild_id = ? AND user_id = ?", 
            (guild_id, user_id)
        )
        return row[0] if row else None

    async def save_custom_role(self, guild_id: int, user_id: int, role_id: int):
        """Menyimpan atau memperbarui data peran kustom milik pengguna di database secara asinkron."""
        await self.bot.RUN(
            "INSERT OR REPLACE INTO custom_roles (guild_id, user_id, role_id) VALUES (?, ?, ?)", 
            (guild_id, user_id, role_id)
        )

    async def delete_custom_role_db(self, guild_id: int, user_id: int):
        """Menghapus data peran kustom milik pengguna dari database secara asinkron."""
        await self.bot.RUN(
            "DELETE FROM custom_roles WHERE guild_id = ? AND user_id = ?", 
            (guild_id, user_id)
        )

    def has_premium_access(self, member: discord.Member) -> bool:
        """Memeriksa kelayakan warga berdasarkan peran donatur aktif di config."""
        guild_id = member.guild.id
        premium_roles = ["patron", "scholar", "companion"]
        for role_name in premium_roles:
            role_id = get_role_id(guild_id, role_name)
            role = member.guild.get_role(role_id)
            if role and role in member.roles:
                return True
        return False

    @app_commands.command(name="create_role", description="Membuat peran kustom estetik Anda sendiri (Khusus Donatur VIP).")
    @app_commands.describe(name="Nama peran kustom pilihan Anda", color_hex="Kode warna Hex (contoh: #ff0055)")
    async def create_role(self, interaction: discord.Interaction, name: str, color_hex: str):
        """Membuat peran baru dengan warna unik untuk donatur VIP."""
        guild_id = interaction.guild_id
        member = interaction.user

        # Validasi hak istimewa donatur premium
        if not self.has_premium_access(member):
            await interaction.response.send_message(
                "❌ Fitur kustomisasi peran hanya tersedia bagi donatur aktif (**Patron**, **Scholar**, atau **Companion**)! Dukung server kami untuk membuka akses.", 
                ephemeral=True
            )
            return

        # Validasi kecocokan format kode warna Hex
        if not re.match(r"^#[0-9a-fA-F]{6}$", color_hex):
            await interaction.response.send_message(
                "❌ Format kode warna Hex salah! Gunakan format standar seperti `#ff0055`.", 
                ephemeral=True
            )
            return

        existing_role_id = await self.get_user_custom_role(guild_id, member.id)
        color = discord.Color(int(color_hex.lstrip('#'), 16))

        if existing_role_id:
            existing_role = interaction.guild.get_role(existing_role_id)
            if existing_role:
                try:
                    await existing_role.edit(name=name, color=color)
                    await interaction.response.send_message(
                        f"✨ Berhasil memperbarui peran kustom Anda menjadi **{name}** dengan warna baru `{color_hex}`!", 
                        ephemeral=True
                    )
                    return
                except discord.Forbidden:
                    logger.warning(f"⚠️ Izin tidak cukup untuk mengedit peran {existing_role_id}")

        try:
            # Buat peran baru di server Discord
            new_role = await interaction.guild.create_role(
                name=name, 
                color=color, 
                reason=f"Peran kustom atas permintaan {member.name}"
            )

            # Sematkan peran tersebut ke sang donatur
            await member.add_roles(new_role)
            await self.save_custom_role(guild_id, member.id, new_role.id)

            await interaction.response.send_message(
                f"🎨 Sukses! Peran estetik **{name}** telah diciptakan dan disematkan di profil Anda!", 
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"❌ Gagal membuat peran kustom: {e}")
            await interaction.response.send_message(
                "❌ Terjadi kegagalan sistem saat membuat peran baru. Pastikan posisi bot berada di atas kasta target.", 
                ephemeral=True
            )

    @app_commands.command(name="delete_role", description="Menghapus peran kustom estetik Anda.")
    async def delete_role(self, interaction: discord.Interaction):
        """Menghapus peran kustom milik donatur."""
        guild_id = interaction.guild_id
        member = interaction.user

        role_id = await self.get_user_custom_role(guild_id, member.id)
        if not role_id:
            await interaction.response.send_message(
                "❌ Anda belum memiliki peran kustom di server ini.", 
                ephemeral=True
            )
            return

        role = interaction.guild.get_role(role_id)
        if role:
            try:
                await role.delete(reason="Dihapus secara mandiri oleh pemilik")
                await self.delete_custom_role_db(guild_id, member.id)
                await interaction.response.send_message(
                    "🧹 Peran kustom Anda berhasil dihapus dari sistem kerajaan.", 
                    ephemeral=True
                )
            except Exception as e:
                logger.error(f"❌ Gagal menghapus peran kustom: {e}")
                await interaction.response.send_message(
                    "❌ Terjadi masalah teknis saat menghapus peran kustom Anda.", 
                    ephemeral=True
                )
        else:
            await self.delete_custom_role_db(guild_id, member.id)
            await interaction.response.send_message(
                "🧹 Peran kustom Anda telah dibersihkan dari database kerajaan.", 
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(CustomRole(bot))