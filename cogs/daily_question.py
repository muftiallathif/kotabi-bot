"""Cog yang otomatis menghasilkan dan mengirimkan pertanyaan harian (Daily Question) berbahasa Jepang menggunakan OpenAI API — BAGIAN 1."""

import os
import aiohttp
import discord
import yaml
from discord.ext import commands, tasks
from discord.utils import utcnow
from lib.bot import KotabiBot

# --- QUERY DATABASE SQLITE --- #

# Keterangan: Pembuatan tabel untuk mencatat riwayat pertanyaan harian yang sudah pernah dikirimkan oleh bot di setiap channel server.
DAILY_QUESTIONS_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS daily_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);"""

# Keterangan: Query SQL untuk menarik 10 teks pertanyaan terakhir yang pernah diajukan agar tidak terjadi pengulangan topik kuis.
GET_RECENT_QUESTIONS = """
SELECT question FROM daily_questions 
WHERE guild_id = ? AND channel_id = ?
ORDER BY created_at DESC LIMIT 10;"""

# Keterangan: Query SQL untuk memeriksa apakah server terkait sudah mengirimkan pertanyaan harian untuk hari ini atau belum.
GET_TODAYS_QUESTION = """
SELECT question FROM daily_questions 
WHERE guild_id = ? AND channel_id = ? 
AND date(created_at) = date('now')
LIMIT 1;"""

# Keterangan: Query SQL untuk memasukkan riwayat pertanyaan baru beserta waktu pengirimannya ke dalam tabel database.
INSERT_QUESTION = """
INSERT INTO daily_questions (guild_id, channel_id, question, created_at)
VALUES (?, ?, ?, ?);"""

# --- PROMPT AI (GPT SYSTEM) --- #

# Keterangan: Teks instruksi (Prompt) yang akan dikirimkan ke kecerdasan buatan OpenAI untuk merakit pertanyaan bahasa Jepang yang interaktif.
PROMPT = """Create a daily question in Japanese that is interesting and original and will spark discussion.
The question should be challenging but not too difficult, and should encourage conversation.
Here are the last questions that were asked (avoid similar topics):

{recent_questions_str}

Provide only the question text in Japanese, nothing else."""

# Keterangan: Mencari jalur file konfigurasi setingan kuis harian, lalu membaca data YAML tersebut ke format Python Dictionary.
DAILY_QUESTIONS_SETTINGS_PATH = os.getenv("DAILY_QUESTIONS_SETTINGS_PATH") or "config/daily_questions_settings.yml"
with open(DAILY_QUESTIONS_SETTINGS_PATH, "r", encoding="utf-8") as f:
    daily_questions_settings = yaml.safe_load(f)


class DailyQuestion(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot
        self.api_key = os.getenv("OPENAI_KEY")  # Mengambil kunci rahasia API OpenAI dari file environment VPS Anda

    async def cog_load(self):
        """Fungsi otomatis dari ekosistem discord.py yang dipicu saat file Cog ini pertama kali dimuat oleh bot."""
        # Membuat tabel database daily_questions jika tabel tersebut belum ada di database SQLite Anda
        await self.bot.RUN(DAILY_QUESTIONS_CREATE_TABLE)
        
        # Jaring pengaman: Jika kunci API OpenAI kosong/tidak ditemukan di VPS, batalkan penyalaan sistem kuis harian
        if not self.api_key:
            return
            
        # Memulai tugas pengecekan waktu berulang otomatis (task loop)
        self.check_daily_questions.start()

    def cog_unload(self):
        """Fungsi otomatis yang dipicu jika modul file Cog ini dimatikan atau di-reload oleh sistem utama bot."""
        self.check_daily_questions.cancel()  # Menghentikan paksa tugas perulangan waktu agar memori VPS bersih

    async def get_question_prompt(self, guild_id: int, channel_id: int) -> str:
        """Fungsi internal untuk menyusun prompt teks final dengan memasukkan daftar 10 riwayat pertanyaan lama dari database."""
        recent_questions = await self.bot.GET(GET_RECENT_QUESTIONS, (guild_id, channel_id))
        # Menggabungkan baris hasil query database menjadi satu teks string panjang yang dipisahkan baris baru (\n)
        recent_questions_str = "\n".join([q[0] for q in recent_questions])

        # Memasukkan string riwayat ke dalam template PROMPT utama menggunakan fitur .format() bawaan Python
        return PROMPT.format(recent_questions_str=recent_questions_str)

    async def generate_question(self, guild_id: int, channel_id: int) -> str:
        """Fungsi internal untuk melakukan request asinkronus (post data) ke API OpenAI menggunakan library aiohttp."""
        prompt = await self.get_question_prompt(guild_id, channel_id)

        # Menyusun header autentikasi pengiriman data paket
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        # Menyusun struktur isi data (payload json) mengikuti standar parameter dokumentasi resmi OpenAI
        payload = {
            "model": "gpt-4o-mini",  # Menggunakan model AI gpt-4o-mini yang sangat cepat, cerdas, dan hemat biaya token
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful assistant that creates engaging daily questions in Japanese."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.9,  # Tingkat kreativitas di-set 0.9 agar variasi pertanyaan yang dihasilkan sangat beragam
            "max_tokens": 200    # Batas maksimal panjang teks balasan dari AI
        }

        # Membuka sesi jaringan internet asinkronus untuk menembak server OpenAI API
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload) as response:
                # Jika server OpenAI mengembalikan kode status selain 200 (gagal/error), tangkap pesan errornya
                if response.status != 200:
                    error_data = await response.json()
                    raise Exception(f"OpenAI API error: {error_data}")

                # Jika sukses, ubah data respon menjadi JSON dan bersihkan spasi kosong di ujung teks kuis (.strip())
                data = await response.json()
                return data['choices'][0]['message']['content'].strip()

    async def post_daily_question(self, guild_id: int, channel_id: int):
        """Fungsi utama untuk mengeksekusi penulisan database dan memposting kotak kuis harian ke channel server Discord."""
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        # Memeriksa database terlebih dahulu untuk memastikan hari ini belum ada kuis yang terkirim di channel tersebut
        existing_question = await self.bot.GET_ONE(GET_TODAYS_QUESTION, (guild_id, channel_id))
        if existing_question:
            return  # Jika hari ini sudah pernah kirim kuis, langsung batalkan proses agar tidak terjadi pengiriman ganda

        try:
            # Memicu fungsi generate teks kuis via OpenAI gpt-4o-mini di atas
            question = await self.generate_question(guild_id, channel_id)
            current_time = utcnow()  # Mengambil waktu universal (UTC) saat ini secara akurat

            # Catat hasil teks pertanyaan sukses tersebut ke dalam tabel database SQLite server Anda
            await self.bot.RUN(INSERT_QUESTION, (guild_id, channel_id, question, current_time))

            # Merakit tampilan kotak pesan Embed biru indah untuk dikirim ke warga server
            embed = discord.Embed(title="今日の質問 / Daily Question", description=question, color=discord.Color.blue())

            # Kirim embed kuis ke target channel Discord Anda
            await channel.send(embed=embed)

        except Exception as e:
            raise

    @tasks.loop(minutes=1)
    async def check_daily_questions(self):
        """Tugas otomatis (Background Task) yang berulang setiap 1 menit sekali untuk mencocokkan jadwal pengiriman kuis harian."""
        # Melakukan perulangan data untuk membaca konfigurasi ID Server dan ID Channel yang terdaftar di file .yml Anda
        for guild_id, settings in daily_questions_settings.items():
            guild_id = int(guild_id)
            for channel_id in settings['channels']:
                channel_id = int(channel_id)
                # Picu fungsi pengecekan dan pengunggahan kuis harian di atas
                await self.post_daily_question(guild_id, channel_id)


async def setup(bot):
    """Fungsi standar dari arsitektur discord.py untuk mengaktifkan modul Cog DailyQuestion ini ke sistem utama Bot Kotabi."""
    await bot.add_cog(DailyQuestion(bot))
