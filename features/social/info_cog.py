import discord
import yaml
import os
import logging
from discord.ext import commands
from typing import Optional

logger = logging.getLogger("bot.info")
INFO_COMMANDS_PATH = "features/social/info_commands.yml"
info_commands = {}

# Memuat berkas konfigurasi YAML secara aman (fail-safe)
if os.path.exists(INFO_COMMANDS_PATH):
    try:
        with open(INFO_COMMANDS_PATH, "r", encoding="utf-8") as f:
            info_commands = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"❌ Gagal memuat berkas konfigurasi info: {e}")
else:
    logger.warning(f"⚠️ Berkas konfigurasi {INFO_COMMANDS_PATH} tidak ditemukan. Menggunakan kamus kosong.")


async def info_autocomplete(interaction: discord.Interaction, current: str):
    """Menyediakan daftar pilihan topik informasi secara otomatis saat mengetik perintah."""
    if not current:
        return [discord.app_commands.Choice(name=key, value=key) for key in info_commands.keys()][:25]
    else:
        return [
            discord.app_commands.Choice(name=key, value=key)
            for key in info_commands.keys()
            if current.lower() in key.lower()
        ][:25]


class InfoCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="info", 
        description="Dapatkan berbagai arsip informasi dan pengetahuan berharga di Kerajaan Kotabi!"
    )
    @discord.app_commands.describe(info_key="Topik atau kata kunci informasi yang ingin dicari.")
    @discord.app_commands.autocomplete(info_key=info_autocomplete)
    async def info(self, interaction: discord.Interaction, info_key: str):
        """Menampilkan kartu informasi estetik berdasarkan topik yang dipilih."""
        # Validasi apakah kunci yang dimasukkan ada di arsip data
        if info_key not in info_commands.keys():
            await interaction.response.send_message(
                "❌ Topik informasi atau kata kunci tersebut tidak ditemukan di dalam arsip kerajaan.", 
                ephemeral=True
            )
            return

        # Ambil isi teks informasi
        text_info = info_commands.get(info_key)
        
        embed = discord.Embed(
            title= f"📚 Arsip Informasi: `{info_key}`", 
            description=text_info, 
            color=discord.Color.random()
        )
        embed.set_footer(
            text=f"Diminta oleh {interaction.user.display_name}", 
            icon_url=interaction.user.display_avatar.url
        )
        
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    """Mendaftarkan modul InfoCommand ke sistem utama Bot."""
    await bot.add_cog(InfoCommand(bot))