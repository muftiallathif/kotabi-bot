import discord
from discord.ext import commands
from discord import app_commands
import re
import logging

from lib.checks import has_premium_role
from lib.messages import Msg

logger = logging.getLogger("bot.custom_role")

CREATE_CUSTOM_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS custom_roles (
    guild_id INTEGER,
    user_id INTEGER,
    role_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
)
"""

GET_CUSTOM_ROLE_QUERY = """
SELECT role_id FROM custom_roles WHERE guild_id = ? AND user_id = ?
"""

SAVE_CUSTOM_ROLE_QUERY = """
INSERT OR REPLACE INTO custom_roles (guild_id, user_id, role_id) VALUES (?, ?, ?)
"""

DELETE_CUSTOM_ROLE_QUERY = """
DELETE FROM custom_roles WHERE guild_id = ? AND user_id = ?
"""


class CustomRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Inisialisasi tabel database peran kustom milik pengguna secara asinkron."""
        await self.bot.RUN(CREATE_CUSTOM_ROLES_TABLE)

    async def get_user_custom_role(self, guild_id: int, user_id: int) -> int:
        """Mengambil ID peran kustom milik pengguna dari database secara asinkron."""
        row = await self.bot.GET_ONE(GET_CUSTOM_ROLE_QUERY, (guild_id, user_id))
        return row[0] if row else None

    async def save_custom_role(self, guild_id: int, user_id: int, role_id: int):
        """Menyimpan atau memperbarui data peran kustom milik pengguna di database secara asinkron."""
        await self.bot.RUN(SAVE_CUSTOM_ROLE_QUERY, (guild_id, user_id, role_id))

    async def delete_custom_role_db(self, guild_id: int, user_id: int):
        """Menghapus data peran kustom milik pengguna dari database secara asinkron."""
        await self.bot.RUN(DELETE_CUSTOM_ROLE_QUERY, (guild_id, user_id))

    @app_commands.command(name="create_role", description="Membuat peran kustom estetik Anda sendiri (Khusus Donatur VIP).")
    @app_commands.describe(name="Nama peran kustom pilihan Anda", color_hex="Kode warna Hex (contoh: #ff0055)")
    async def create_role(self, interaction: discord.Interaction, name: str, color_hex: str):
        """Membuat peran baru dengan warna unik untuk donatur VIP."""
        member = interaction.user

        # ✅ Pakai has_premium_role() dari lib/checks — tidak ada hardcode role name
        if not has_premium_role(member, interaction.guild_id):
            await interaction.response.send_message(Msg.CUSTOM_ROLE_NO_PREMIUM, ephemeral=True)
            return

        # Validasi format kode warna Hex
        if not re.match(r"^#[0-9a-fA-F]{6}$", color_hex):
            await interaction.response.send_message(Msg.CUSTOM_ROLE_INVALID_HEX, ephemeral=True)
            return

        existing_role_id = await self.get_user_custom_role(interaction.guild_id, member.id)
        color = discord.Color(int(color_hex.lstrip('#'), 16))

        if existing_role_id:
            existing_role = interaction.guild.get_role(existing_role_id)
            if existing_role:
                try:
                    await existing_role.edit(name=name, color=color)
                    await interaction.response.send_message(
                        Msg.custom_role_updated(name, color_hex),
                        ephemeral=True
                    )
                    return
                except discord.Forbidden:
                    logger.warning(f"⚠️ Izin tidak cukup untuk mengedit peran {existing_role_id}")

        try:
            new_role = await interaction.guild.create_role(
                name=name,
                color=color,
                reason=f"Peran kustom atas permintaan {member.name}"
            )
            await member.add_roles(new_role)
            await self.save_custom_role(interaction.guild_id, member.id, new_role.id)

            await interaction.response.send_message(
                Msg.custom_role_created(name),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"❌ Gagal membuat peran kustom: {e}")
            await interaction.response.send_message(Msg.CUSTOM_ROLE_BOT_NO_PERMS, ephemeral=True)

    @app_commands.command(name="delete_role", description="Menghapus peran kustom estetik Anda.")
    async def delete_role(self, interaction: discord.Interaction):
        """Menghapus peran kustom milik donatur."""
        member = interaction.user

        role_id = await self.get_user_custom_role(interaction.guild_id, member.id)
        if not role_id:
            await interaction.response.send_message(Msg.CUSTOM_ROLE_NOT_FOUND, ephemeral=True)
            return

        role = interaction.guild.get_role(role_id)
        if role:
                try:
                    await role.delete(reason="Dihapus secara mandiri oleh pemilik")
                    await self.delete_custom_role_db(interaction.guild_id, member.id)
                    await interaction.response.send_message(
                        Msg.CUSTOM_ROLE_DELETED,
                        ephemeral=True
                    )
                except Exception as e:
                    logger.error(f"❌ Gagal menghapus peran kustom: {e}")
                    await interaction.response.send_message(
                        Msg.CUSTOM_ROLE_DELETE_FAILED,
                        ephemeral=True
                    )
        else:
            await self.delete_custom_role_db(interaction.guild_id, member.id)
            await interaction.response.send_message(
                Msg.CUSTOM_ROLE_DB_CLEANED,
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(CustomRole(bot))