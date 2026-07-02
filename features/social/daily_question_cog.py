import discord
import yaml
import os
import logging
import aiohttp
from discord.ext import commands, tasks
from discord.utils import utcnow

from core.bot import KotabiBot

_log = logging.getLogger("bot.daily_question")

DAILY_QUESTIONS_SETTINGS_PATH = (
    os.getenv("DAILY_QUESTIONS_SETTINGS_PATH") or "features/social/daily_questions_settings.yml"
)

daily_questions_settings: dict = {}

if os.path.exists(DAILY_QUESTIONS_SETTINGS_PATH):
    try:
        with open(DAILY_QUESTIONS_SETTINGS_PATH, "r", encoding="utf-8") as f:
            daily_questions_settings = yaml.safe_load(f) or {}
    except Exception as e:
        _log.error(f"❌ Gagal memuat daily_questions_settings.yml: {e}")
else:
    _log.warning(f"⚠️ File {DAILY_QUESTIONS_SETTINGS_PATH} tidak ditemukan.")

# --- DATABASE QUERIES ---

CREATE_DAILY_QUESTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS daily_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

GET_RECENT_QUESTIONS = """
SELECT question FROM daily_questions
WHERE guild_id = ? AND channel_id = ?
ORDER BY created_at DESC LIMIT 10;
"""

GET_TODAYS_QUESTION = """
SELECT question FROM daily_questions
WHERE guild_id = ? AND channel_id = ?
AND date(created_at) = date('now')
LIMIT 1;
"""

INSERT_QUESTION = """
INSERT INTO daily_questions (guild_id, channel_id, question, created_at)
VALUES (?, ?, ?, ?);
"""

PROMPT_TEMPLATE = """Buatlah satu pertanyaan harian dalam Bahasa Jepang yang menarik dan original untuk mendorong diskusi di komunitas belajar Bahasa Jepang.
Pertanyaan harus menantang namun tidak terlalu sulit, dan mendorong percakapan.
Berikut adalah pertanyaan-pertanyaan yang sudah pernah ditanyakan sebelumnya (hindari topik yang serupa):

{recent_questions_str}

Berikan hanya teks pertanyaannya saja dalam Bahasa Jepang, tanpa penjelasan tambahan."""


class DailyQuestion(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot
        self.api_key = os.getenv("OPENAI_KEY")

    async def cog_load(self):
        await self.bot.RUN(CREATE_DAILY_QUESTIONS_TABLE)
        if not self.api_key:
            _log.warning("⚠️ OPENAI_KEY tidak ditemukan. Fitur daily question dinonaktifkan.")
            return
        if not daily_questions_settings:
            _log.warning("⚠️ daily_questions_settings.yml kosong. Task tidak dijalankan.")
            return
        self.check_daily_questions.start()

    def cog_unload(self):
        self.check_daily_questions.cancel()

    async def get_question_prompt(self, guild_id: int, channel_id: int) -> str:
        recent_questions = await self.bot.GET(GET_RECENT_QUESTIONS, (guild_id, channel_id))
        recent_questions_str = "\n".join([q[0] for q in recent_questions]) or "(Belum ada pertanyaan sebelumnya)"
        return PROMPT_TEMPLATE.format(recent_questions_str=recent_questions_str)

    async def generate_question(self, guild_id: int, channel_id: int) -> str:
        prompt = await self.get_question_prompt(guild_id, channel_id)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": "Kamu adalah asisten yang membantu membuat pertanyaan harian menarik dalam Bahasa Jepang untuk komunitas belajar.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.9,
            "max_tokens": 200,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status != 200:
                    error_data = await response.json()
                    raise Exception(f"OpenAI API error: {error_data}")
                data = await response.json()
                return data["choices"][0]["message"]["content"].strip()

    async def post_daily_question(self, guild_id: int, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if not channel:
            _log.warning(f"⚠️ Channel ID {channel_id} tidak ditemukan di cache bot.")
            return

        # Cek apakah pertanyaan hari ini sudah pernah dikirim
        existing_question = await self.bot.GET_ONE(GET_TODAYS_QUESTION, (guild_id, channel_id))
        if existing_question:
            return

        try:
            question = await self.generate_question(guild_id, channel_id)
            current_time = utcnow()

            await self.bot.RUN(INSERT_QUESTION, (guild_id, channel_id, question, current_time))

            embed = discord.Embed(
                title="🌸 今日の質問 / Pertanyaan Hari Ini",
                description=question,
                color=discord.Color.blue(),
            )
            embed.set_footer(text="Jawab pertanyaan ini untuk berlatih Bahasa Jepang!")

            await channel.send(embed=embed)
            _log.info(f"✅ Pertanyaan harian berhasil dikirim ke channel {channel_id}")

        except Exception as e:
            _log.error(f"❌ Gagal mengirim pertanyaan harian ke channel {channel_id}: {e}")

    @tasks.loop(minutes=1)
    async def check_daily_questions(self):
        """Mengecek setiap menit apakah sudah waktunya mengirim pertanyaan harian."""
        now = utcnow()
        if now.hour != 1 or now.minute != 0:  # 01:00 UTC = 08:00 WIB
            return
        for guild_id, settings in daily_questions_settings.items():
            guild_id = int(guild_id)
            for channel_id in settings.get("channels", []):
                channel_id = int(channel_id)
                await self.post_daily_question(guild_id, channel_id)

    @check_daily_questions.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: KotabiBot):
    await bot.add_cog(DailyQuestion(bot))