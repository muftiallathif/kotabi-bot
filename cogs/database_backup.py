"""Cog yang berfungsi mengompresi file database SQLite menjadi format Gzip (.gz) dan mengirimkannya ke channel Discord sebagai cadangan (Backup) — BAGIAN 1.""" 

import asyncio
import gzip
import os
import shutil
import tempfile
import discord
from discord.ext import commands
from lib.bot import KotabiBot

# Keterangan: Mengambil jalur tempat file database SQLite disimpan di VPS Anda dari variabel lingkungan (environment variable).
# Jika variabel "PATH_TO_DB" tidak ditemukan di VPS, maka sistem secara otomatis akan menggunakan jalur bawaan yaitu "data/db.sqlite3".
PATH_TO_DB = os.getenv("PATH_TO_DB", "data/db.sqlite3")


def create_temporary_gzip_file():
    """Fungsi sinkronus (Blocking Function) untuk menyalin data biner database asli dan mengompresinya menjadi format file .gz."""
    # Membuat jalur lokasi file sementara (Temporary File) bernama "db.sqlite3.gz" di dalam folder temp sistem operasi VPS.
    temp_file_path = os.path.join(tempfile.gettempdir(), "db.sqlite3.gz")
    
    # Membuka file database asli dalam mode membaca biner ('rb')
    with open(PATH_TO_DB, 'rb') as f_in:
        # Membuka/membuat file sementara dalam mode menulis biner terkompresi Gzip ('wb')
        with gzip.open(temp_file_path, 'wb') as f_out:
            # Menyalin seluruh isi data objek dari file database asli langsung ke dalam file kompresi Gzip
            shutil.copyfileobj(f_in, f_out)
            
    return temp_file_path  # Mengembalikan jalur lokasi file sementara yang sudah sukses dikompresi


class DatabasePoster(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    @discord.app_commands.command(name="post_db", description="Gzip the database file and post it to the channel.")
    async def post_db(self, interaction: discord.Interaction):
        """Slash Command khusus yang digunakan untuk memicu pengiriman file cadangan (backup) database terkompresi ke Discord."""
        # Menunda respon Discord (defer) agar interaksi perintah tidak hang/timeout jika ukuran file database Anda sangat besar
        await interaction.response.defer()
        
        try:
            # Keterangan: Menggunakan 'asyncio.to_thread' untuk mengalihkan proses kompresi file (I/O heavy) ke thread pekerja terpisah.
            # Langkah ini sangat krusial agar Bot Kotabi Anda tidak mengalami "Freeze" (macet/silent) saat proses kompresi database sedang berlangsung.
            temp_file_path = await asyncio.to_thread(create_temporary_gzip_file)
            
            # Mengirimkan file sementara hasil kompresi tersebut ke dalam channel Discord tempat perintah dipicu
            await interaction.followup.send(file=discord.File(temp_file_path, filename="db.sqlite3.gz"))
            
        except Exception as e:
            # Jika terjadi kegagalan sistem internal, lemparkan pesan error ke sistem logging utama bot Anda
            raise
            
        finally:
            # Keterangan: Blok 'finally' dijamin akan selalu berjalan di akhir proses, baik perintahnya sukses maupun terjadi error.
            # Tujuannya adalah untuk menghapus file sementara (.gz) dari disk VPS Anda agar ruang penyimpanan penyimpanan server tidak penuh oleh file sampah.
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)


async def setup(bot: KotabiBot):
    """Fungsi standar dari arsitektur discord.py untuk mendaftarkan modul Cog DatabasePoster ini ke sistem utama Bot Kotabi."""
    await bot.add_cog(DatabasePoster(bot))
