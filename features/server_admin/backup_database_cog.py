import asyncio
import gzip
import os
import shutil
import tempfile
import logging
import discord
from discord.ext import commands
from discord import app_commands

# Menggunakan logger standar bot agar aktivitas tercatat rapi di terminal VPS
logger = logging.getLogger("bot.database_backup")

# Mengambil lokasi database dari Environment Variable VPS atau menggunakan default
PATH_TO_DB = os.getenv("PATH_TO_DB", "data/db.sqlite3")


def create_temporary_gzip_file():
    """Fungsi sinkronus untuk menyalin data biner database asli dan mengompresinya menjadi .gz."""
    # Membuat jalur lokasi file sementara (Temporary File) di folder temp sistem operasi VPS
    temp_file_path = os.path.join(tempfile.gettempdir(), "db.sqlite3.gz")

    # Membuka file database asli dalam mode membaca biner ('rb')
    with open(PATH_TO_DB, 'rb') as f_in:
        # Membuka file sementara dalam mode menulis biner terkompresi Gzip ('wb')
        with gzip.open(temp_file_path, 'wb') as f_out:
            # Menyalin seluruh data database langsung ke dalam file kompresi Gzip
            shutil.copyfileobj(f_in, f_out)

    return temp_file_path


class DatabaseBackup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="backup_database",
        description="Mengompres database SQLite ke Gzip dan mengirimkannya sebagai cadangan (Khusus Admin).",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def backup_database(self, interaction: discord.Interaction):
        """Slash Command untuk memicu pengunggahan file cadangan database terkompresi secara aman."""
        # Menunda respon dengan mode Ephemeral agar proses pengiriman aman dan tidak terlihat oleh warga biasa
        await interaction.response.defer(ephemeral=True)

        temp_file_path = None
        try:
            # Menjalankan proses kompresi file di thread terpisah agar bot tidak mengalami freeze (macet)
            temp_file_path = await asyncio.to_thread(create_temporary_gzip_file)

            # Mengirimkan file terkompresi secara privat ke admin yang meminta
            await interaction.followup.send(
                content="📦 **Cadangan database berhasil dibuat!** Silakan unduh berkas di bawah ini:",
                file=discord.File(temp_file_path, filename="db.sqlite3.gz"),
                ephemeral=True
            )
            logger.info(f"💾 Database backup berhasil diekspor oleh Administrator {interaction.user} (ID: {interaction.user.id})")

        except Exception as e:
            logger.error(f"❌ Gagal melakukan backup database: {e}")
            await interaction.followup.send(
                content=f"❌ Terjadi kesalahan internal saat mencadangkan database: `{e}`",
                ephemeral=True
            )

        finally:
            # Menghapus file sementara (.gz) dari VPS agar penyimpanan disk tidak membengkak
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception as e:
                    logger.warning(f"⚠️ Gagal menghapus file sementara backup: {e}")


async def setup(bot):
    """Mendaftarkan modul DatabaseBackup ke sistem utama Bot."""
    await bot.add_cog(DatabaseBackup(bot))