import discord
from discord.ext import commands, tasks
from discord.utils import utcnow
import re
import aiohttp
import asyncio
import yaml
import os
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone

# Impor pembaca konfigurasi Level 0
from lib.config import get_role_id, get_channel_id
from lib.checks import has_vip_role           # ← BARU: helper VIP check
from lib.messages import Msg                   # ← BARU: teks terpusat
from core.bot import KotabiBot

_log = logging.getLogger("bot.gatekeeper")

KOTOBA_BOT_ID = 251239170058616833

# Memuat konfigurasi kuis dengan aman (fail-safe)
GATEKEEPER_SETTINGS_PATH = os.getenv("ALT_GATEKEEPER_SETTINGS_PATH") or "config/gatekeeper_settings.yml"
gatekeeper_settings = {}

if os.path.exists(GATEKEEPER_SETTINGS_PATH):
    try:
        with open(GATEKEEPER_SETTINGS_PATH, "r", encoding="utf-8") as f:
            gatekeeper_settings = yaml.safe_load(f) or {}
    except Exception as e:
        _log.error(f"❌ Gagal memuat file konfigurasi gatekeeper: {e}")
else:
    _log.warning(f"⚠️ File konfigurasi {GATEKEEPER_SETTINGS_PATH} tidak ditemukan. Menggunakan konfigurasi kosong.")

# --- QUERY DATABASE SQLITE (Asynchronous Wrapper) --- #

CREATE_QUIZ_ATTEMPTS_TABLE = """
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    quiz_name TEXT NOT NULL,
    created_at TIMESTAMP
);"""

CREATE_PASSED_QUIZZES_TABLE = """
CREATE TABLE IF NOT EXISTS passed_quizzes (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    quiz_name TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id, quiz_name)
);"""

CREATE_USER_THREADS_TABLE = """
CREATE TABLE IF NOT EXISTS user_threads (
    user_id INTEGER NOT NULL,
    thread_id INTEGER NOT NULL,
    PRIMARY KEY (user_id)
);"""

ADD_QUIZ_ATTEMPT = """INSERT INTO quiz_attempts (guild_id, user_id, quiz_name, created_at) VALUES (?,?,?,?);"""

GET_LAST_QUIZ_ATTEMPT = """SELECT quiz_name, created_at FROM quiz_attempts
WHERE guild_id = ? AND user_id = ? AND quiz_name = ? ORDER BY created_at DESC LIMIT 1;"""

RESET_ALL_QUIZ_ATTEMPTS = """DELETE FROM quiz_attempts WHERE guild_id = ? AND user_id = ?"""

RESET_SPECIFIC_QUIZ_ATTEMPTS = """DELETE FROM quiz_attempts WHERE guild_id = ? AND user_id = ? AND quiz_name = ?"""

ADD_PASSED_QUIZ = """INSERT INTO passed_quizzes (guild_id, user_id, quiz_name) VALUES (?,?,?)
ON CONFLICT(guild_id, user_id, quiz_name) DO NOTHING;"""

GET_PASSED_QUIZZES = """SELECT quiz_name FROM passed_quizzes WHERE guild_id = ? AND user_id = ?;"""

ADD_USER_THREAD = """INSERT INTO user_threads (user_id, thread_id) VALUES (?, ?)
ON CONFLICT(user_id) DO UPDATE SET thread_id = excluded.thread_id;"""

GET_USER_THREAD = """SELECT thread_id FROM user_threads WHERE user_id = ?;"""


def _get_rank_structure(guild_id: int) -> list:
    """
    Ambil rank_structure dari config dengan aman.
    Coba int key dulu, fallback ke str key (YAML kadang load sebagai str).
    """
    rank_map = gatekeeper_settings.get("rank_structure", {})
    return rank_map.get(guild_id) or rank_map.get(str(guild_id)) or []


async def quiz_autocomplete(interaction: discord.Interaction, current_input: str):
    """Menyediakan daftar nama kuis otomatis untuk perintah Slash Command."""
    guild_id = interaction.guild.id
    rank_structure = _get_rank_structure(guild_id)

    rank_names = [
        quiz["name"] for quiz in rank_structure
        if quiz.get("combination_rank") is False and quiz.get("no_timeout") is False
    ]
    possible_choices = [discord.app_commands.Choice(name=rank_name, value=rank_name) for rank_name in rank_names]
    return possible_choices[0:25]


async def verify_quiz_settings(quiz_data, quiz_result, member: discord.Member):
    """Memverifikasi pengaturan kuis secara ketat untuk mencegah kecurangan."""
    answer_count = quiz_data["score_limit"]
    answer_time_limit = quiz_data["time_limit"]
    font = quiz_data["font"]
    font_size = quiz_data["font_size"]
    fail_count = quiz_data["max_missed"]

    foreground_color = quiz_data["foreground"]
    effect = quiz_data["effect"]

    if quiz_data.get("deck_range"):
        start_index, end_index = quiz_data["deck_range"]
        index_specified = True
    else:
        index_specified = False

    user_count = len(quiz_result["participants"])
    if user_count > 1:
        return False, "Kuis gagal karena ada lebih dari satu peserta yang berpartisipasi."

    shuffle = quiz_result["settings"]["shuffle"]
    if not shuffle:
        return False, "Kuis gagal karena pengaturan pengocokan (shuffle) dinonaktifkan."

    is_loaded = quiz_result["isLoaded"]
    if is_loaded:
        return False, "Kuis gagal karena menggunakan deck yang sudah di-load sebelumnya."

    for deck in quiz_result["decks"]:
        if deck["mc"]:
            return False, "Kuis gagal karena tipe kuis disetel ke pilihan ganda (multiple choice)."

    if index_specified:
        for deck in quiz_result["decks"]:
            try:
                if deck["startIndex"] != start_index:
                    return False, "Kuis gagal karena menggunakan indeks awal (start index) yang salah."
                if deck["endIndex"] != end_index:
                    return False, "Kuis gagal karena menggunakan indeks akhir (end index) yang salah."
            except KeyError:
                return False, "Kuis gagal karena tidak menentukan batasan indeks kuis."
    else:
        for deck in quiz_result["decks"]:
            try:
                if deck.get("startIndex"):
                    return False, "Kuis gagal karena terdeteksi memakai indeks awal."
            except KeyError:
                pass
            try:
                if deck.get("endIndex"):
                    return False, "Kuis gagal karena terdeteksi memakai indeks akhir."
            except KeyError:
                pass

    if foreground_color:
        if quiz_result["settings"]["fontColor"] != foreground_color:
            return False, "Warna latar depan huruf (foreground color) tidak cocok dengan ketentuan."

    if effect:
        if quiz_result["settings"]["effect"] != effect:
            return False, "Efek huruf tidak cocok dengan efek yang ditentukan."

    if answer_count != quiz_result["settings"]["scoreLimit"]:
        return False, "Target batas nilai kuis tidak sesuai dengan ketentuan ujian kasta."

    if answer_time_limit < quiz_result["settings"]["answerTimeLimitInMs"]:
        return False, "Batas waktu jawab yang diberikan melebihi batas waktu maksimal."

    if font and font != quiz_result["settings"]["font"]:
        return False, "Jenis font yang digunakan tidak cocok dengan ketentuan."

    if font_size and font_size != quiz_result["settings"]["fontSize"]:
        return False, "Ukuran font yang digunakan tidak cocok dengan ketentuan."

    failed_question_count = len(quiz_result["questions"]) - quiz_result["scores"][0]["score"]
    if failed_question_count >= fail_count:
        return False, f"Terlalu banyak salah menjawab. Skor: {quiz_result['scores'][0]['score']} dari {answer_count}."

    if answer_count != quiz_result["scores"][0]["score"]:
        return False, f"Jumlah soal yang dijawab benar tidak mencukupi. Skor: {quiz_result['scores'][0]['score']} dari {answer_count}."

    return True, f"{member.mention} telah berhasil lulus ujian kuis kasta **{quiz_data['name']}**!"


async def get_quiz_id(message: discord.Message):
    """Mengekstrak ID laporan kuis dari embed hasil kuis Bot Kotoba."""
    try:
        if "Ended" in message.embeds[0].title:
            return re.findall(r"game_reports/([\da-z]*)", message.embeds[0].fields[-1].value)[0]
    except (IndexError, TypeError):
        return False
    return False


kotoba_request_lock = asyncio.Lock()
thread_deletion_lock = asyncio.Lock()


async def extract_quiz_result_from_id(quiz_id):
    """Menghubungi web API Kotoba secara asinkron untuk mengambil detail laporan kuis."""
    jsonurl = f"https://kotobaweb.com/api/game_reports/{quiz_id}"
    async with kotoba_request_lock:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(jsonurl) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            _log.warning(f"⚠️ Gagal terhubung ke Kotoba API untuk ID kuis {quiz_id}: {e}")
            return None
    return None


async def timeout_member(member: discord.Member, duration_in_minutes: int, reason: str):
    """Memberikan sangsi waktu bisu (timeout) sementara kepada member jika melanggar ketentuan."""
    try:
        await member.timeout(utcnow() + timedelta(minutes=duration_in_minutes), reason=reason)
    except discord.Forbidden:
        pass


def get_next_sunday_midnight_from(dt):
    """Mendapatkan waktu hari Minggu tengah malam terdekat untuk masa riset cooldown mingguan."""
    days_until_sunday = (6 - dt.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7
    next_sunday = dt + timedelta(days=days_until_sunday)
    next_sunday_midnight = datetime(next_sunday.year, next_sunday.month, next_sunday.day, 0, 0, 0, tzinfo=timezone.utc)
    return next_sunday_midnight


class DynamicQuizMenu(discord.ui.DynamicItem[discord.ui.Select[discord.ui.View]], template=r"quizmenu-guild:(?P<guild_id>\d+)"):
    def __init__(self, levelup: "LevelUp", guild_id: int):
        self.levelup = levelup
        self.guild_id = guild_id

        rank_structure = _get_rank_structure(guild_id)
        rank_names = [(quiz["name"], quiz.get("emoji")) for quiz in rank_structure if quiz.get("command")]

        super().__init__(
            discord.ui.Select(
                custom_id=f"quizmenu-guild:{guild_id}",
                options=[
                    discord.SelectOption(
                        label=name,
                        emoji=emoji,
                        description=f"Pilih untuk memulai ujian kuis {name}!",
                    )
                    for name, emoji in rank_names
                ],
                placeholder="--- Pilih Ujian Kasta Kotabi ---",
                min_values=1,
                max_values=1,
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str]) -> discord.ui.DynamicItem:
        guild_id = int(match.group("guild_id"))
        levelup = interaction.client.get_cog("LevelUp")
        if not levelup:
            raise RuntimeError("Modul LevelUp tidak ditemukan aktif.")
        return cls(levelup, guild_id)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Cek VIP lewat has_vip_role() dari lib/checks.py
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not has_vip_role(member, interaction.guild_id):
            await interaction.followup.send(Msg.GATEKEEPER_VIP_ONLY, ephemeral=True)
            return

        assert interaction.data is not None and "custom_id" in interaction.data, "Interaction data tidak valid."
        rank = self.item.values[0]
        guild_id = interaction.guild.id

        rank_structure = _get_rank_structure(guild_id)

        quiz_command = None
        for quiz in rank_structure:
            if quiz["name"].lower() == rank.lower():
                quiz_command = quiz.get("command")
                break

        if not quiz_command:
            _log.error(f"❌ quiz_command tidak ditemukan untuk rank '{rank}' di guild {guild_id}.")
            await interaction.followup.send(
                f"❌ Perintah kuis untuk kasta **{rank}** tidak ditemukan di konfigurasi. "
                f"Hubungi admin server.",
                ephemeral=True
            )
            return

        rank_has_cooldown = await self.levelup.rank_has_cooldown(interaction.guild.id, rank)
        is_on_cooldown, cooldown_message = await self.levelup.is_on_cooldown_create(interaction.user, rank, rank_has_cooldown)
        if is_on_cooldown:
            await interaction.followup.send(cooldown_message, ephemeral=True)
            return

        await interaction.followup.send(f"🔮 Sedang mempersiapkan ruang ujian kuis Anda untuk kasta **{rank}**...", ephemeral=True)

        quiz_thread_record = await self.levelup.bot.GET_ONE(GET_USER_THREAD, (interaction.user.id,))
        quiz_thread = None

        if quiz_thread_record:
            thread_id = quiz_thread_record[0]
            quiz_thread = interaction.guild.get_thread(thread_id)
            if not quiz_thread:
                try:
                    quiz_thread = await interaction.guild.fetch_channel(thread_id)
                except discord.NotFound:
                    quiz_thread = None

        if not quiz_thread:
            quiz_thread = await interaction.channel.create_thread(
                name=f"📖 Ujian {interaction.user.display_name}"[:100],
                auto_archive_duration=60,
                reason="Pembuatan Ruang Ujian Kuis Kasta"
            )
            await self.levelup.bot.RUN(ADD_USER_THREAD, (interaction.user.id, quiz_thread.id))

        if quiz_thread.locked or quiz_thread.archived:
            await quiz_thread.edit(locked=False, archived=False)

        # Tambahkan Kotoba ke thread
        kotoba = interaction.guild.get_member(KOTOBA_BOT_ID)
        if not kotoba:
            kotoba = await interaction.guild.fetch_member(KOTOBA_BOT_ID)
        if kotoba and kotoba not in quiz_thread.members:
            await quiz_thread.add_user(kotoba)

        # Tambahkan user ke thread ujian
        if interaction.user not in quiz_thread.members:
            await quiz_thread.add_user(interaction.user)

        await quiz_thread.send(
            f"🏯 {interaction.user.mention}, selamat datang di bilik ujian kasta **{rank}**!\n"
            f"Untuk memulai ujian, silakan salin dan kirim perintah di bawah ini secara presisi tanpa ada karakter tambahan:"
        )
        await quiz_thread.send(quiz_command)


class LevelUp(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        """Inisialisasi database dan dynamic item menu kuis."""
        await self.bot.RUN(CREATE_QUIZ_ATTEMPTS_TABLE)
        await self.bot.RUN(CREATE_PASSED_QUIZZES_TABLE)
        await self.bot.RUN(CREATE_USER_THREADS_TABLE)
        self.bot.add_dynamic_items(DynamicQuizMenu)

    async def is_in_levelup_channel(self, message: discord.Message):
        """Memeriksa apakah pesan dikirimkan di dalam thread ujian kuis pengguna."""
        thread_id = await self.bot.GET_ONE(GET_USER_THREAD, (message.author.id,))
        if thread_id and message.channel.id == thread_id[0]:
            return True
        return False

    async def is_restricted_quiz(self, message: discord.Message):
        """Memeriksa apakah kuis yang dipanggil merupakan kuis bertahap yang dibatasi."""
        settings = gatekeeper_settings.get("rank_settings", {}).get(message.guild.id, {})
        if not settings:
            settings = gatekeeper_settings.get("rank_settings", {}).get(str(message.guild.id), {})
        restricted_quizzes = settings.get("restricted_quiz_names", [])
        for quiz_name in restricted_quizzes:
            if quiz_name.lower() in message.content.lower():
                return quiz_name, True
        return None, False

    async def is_valid_quiz(self, message: discord.Message, rank_structure: list):
        """Mengecek keabsahan perintah kuis yang diketik pengguna."""
        for quiz in rank_structure:
            if message.content == quiz.get("command"):
                return True, quiz["name"]
        return False, None

    async def rank_has_cooldown(self, guild_id: int, rank_name: str):
        """Memeriksa apakah kasta kuis tertentu memiliki aturan pembatasan cooldown mingguan."""
        rank_structure = _get_rank_structure(guild_id)
        for rank in rank_structure:
            if rank["name"] == rank_name:
                return not rank.get("no_timeout", False)
        return True

    async def is_command_input_valid(self, message: discord.Message):
        """Mengevaluasi legalitas pengiriman perintah kuis oleh member."""
        if message.author.bot:
            return True

        guild_id = message.guild.id
        rank_structure = _get_rank_structure(guild_id)

        restricted_quiz_name, is_restricted = await self.is_restricted_quiz(message)
        is_in_levelup_channel = await self.is_in_levelup_channel(message)
        is_valid, performed_quiz_name = await self.is_valid_quiz(message, rank_structure)

        if is_valid:
            rank_has_cooldown = await self.rank_has_cooldown(guild_id, performed_quiz_name)
            is_on_cooldown = await self.is_on_cooldown(message, performed_quiz_name, rank_has_cooldown)
            if is_on_cooldown:
                await timeout_member(message.author, 2, "Melakukan spam kuis dalam masa cooldown.")
                return False

        if is_in_levelup_channel and not is_valid:
            await message.channel.send(
                f"⚠️ {message.author.mention}, demi keamanan, harap salin dan kirimkan format perintah kuis **persis secara tepat**."
            )
            await timeout_member(message.author, 2, "Mengirimkan perintah tidak valid di ruang ujian.")
            return False

        if is_restricted:
            if not is_in_levelup_channel or not is_valid:
                await message.channel.send(
                    f"⚠️ {message.author.mention}, ujian kuis kasta **{restricted_quiz_name}** sangat dilindungi.\n"
                    f"Anda hanya diperbolehkan menggunakannya di dalam bilik ujian khusus menggunakan tombol menu utama kuis."
                )
                await timeout_member(message.author, 2, "Memicu ujian kuis di luar bilik pelindung.")
                return False

        if is_valid and not is_in_levelup_channel:
            await message.channel.send(
                f"⚠️ {message.author.mention}, dilarang menggunakan perintah kuis kasta di luar bilik ujian Anda!"
            )
            await timeout_member(message.author, 2, "Mencoba memicu kuis di luar saluran.")
            return False

        return True

    async def is_on_cooldown(self, message: discord.Message, quiz_name: str, rank_has_cooldown: bool):
        """Memeriksa apakah status cooldown mingguan member masih aktif."""
        if not rank_has_cooldown:
            return False
        last_attempt = await self.bot.GET_ONE(GET_LAST_QUIZ_ATTEMPT, (message.guild.id, message.author.id, quiz_name))
        if not last_attempt:
            return False

        _, last_attempt_time = last_attempt
        if isinstance(last_attempt_time, str):
            last_attempt_time = datetime.fromisoformat(last_attempt_time.replace("Z", "+00:00"))

        next_sunday_midnight = get_next_sunday_midnight_from(last_attempt_time)
        if utcnow() < next_sunday_midnight:
            unix_timestamp = int(next_sunday_midnight.timestamp())
            await message.channel.send(
                f"⏳ {message.author.mention}, Anda hanya diperbolehkan mengulang ujian kuis ini 1 kali dalam seminggu.\n"
                f"Kesempatan Anda berikutnya akan terbuka kembali pada <t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)."
            )
            return True
        return False

    async def register_quiz_attempt(self, member: discord.Member, channel: discord.TextChannel, quiz_name: str):
        """Mendaftarkan percobaan kuis tidak sukses ke dalam basis database."""
        await self.bot.RUN(ADD_QUIZ_ATTEMPT, (member.guild.id, member.id, quiz_name, utcnow().isoformat()))
        next_sunday_midnight = get_next_sunday_midnight_from(utcnow())
        unix_timestamp = int(next_sunday_midnight.timestamp())
        await channel.send(
            f"📝 Percobaan ujian {member.mention} untuk kasta **{quiz_name}** telah resmi dicatat.\n"
            f"Anda diperbolehkan mencoba kembali pada <t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)."
        )

    async def get_corresponding_quiz_data(self, message: discord.Message, quiz_result: dict):
        """Mencocokkan data deck laporan Kotoba API dengan data kasta di setelan kerajaan."""
        rank_structure = _get_rank_structure(message.guild.id)

        if not quiz_result["decks"][0].get("shortName"):
            _log.warning(
                f"[get_corresponding_quiz_data] Quiz result dari guild {message.guild.id} "
                f"tidak memiliki shortName di deck pertama. Raw decks: {quiz_result['decks']}"
            )
            return None

        deck_names = [deck["shortName"] for deck in quiz_result["decks"]]
        index_specified = bool(quiz_result["decks"][0].get("startIndex"))

        _log.info(
            f"[get_corresponding_quiz_data] Mencari rank untuk deck_names={deck_names}, "
            f"index_specified={index_specified}, guild={message.guild.id}"
        )

        for rank in rank_structure:
            index_required = rank.get("deck_range", None) is not None
            rank_decks = set(rank["decks"]) if rank.get("decks") is not None else set()

            _log.debug(
                f"  Membandingkan dengan rank '{rank['name']}': "
                f"rank_decks={rank_decks} vs api_decks={set(deck_names)}, "
                f"index_required={index_required} vs index_specified={index_specified}"
            )

            if rank_decks == set(deck_names) and index_required == index_specified:
                _log.info(f"[get_corresponding_quiz_data] ✅ Match ditemukan: '{rank['name']}'")
                return rank

        _log.warning(
            f"[get_corresponding_quiz_data] ❌ Tidak ada rank yang cocok untuk "
            f"deck_names={deck_names}, index_specified={index_specified} di guild {message.guild.id}. "
            f"Periksa apakah nama deck di gatekeeper_settings.yml sudah persis sama dengan yang dikembalikan API Kotoba."
        )
        return None

    async def get_all_quiz_roles(self, guild: discord.Guild):
        """Mengumpulkan seluruh objek peran (Roles) kasta kuis di server."""
        rank_structure = _get_rank_structure(guild.id)
        roles_list = []
        for role_data in rank_structure:
            if role_data.get("rank_to_get"):
                role = guild.get_role(role_data["rank_to_get"])
                if role:
                    roles_list.append(role)
        return roles_list

    async def reward_user(self, member: discord.Member, quiz_data: dict):
        """Menyematkan kenaikan kasta baru kepada member dan mencatatnya ke database."""
        await self.bot.RUN(ADD_PASSED_QUIZ, (member.guild.id, member.id, quiz_data["name"]))

        if quiz_data.get("rank_to_get"):
            all_roles = await self.get_all_quiz_roles(member.guild)
            role_to_get = member.guild.get_role(quiz_data["rank_to_get"])

            _log.info(
                f"[reward_user] Member={member} ({member.id}), quiz='{quiz_data['name']}', "
                f"rank_to_get ID={quiz_data['rank_to_get']}, resolved role={role_to_get}"
            )

            if role_to_get is None:
                _log.error(
                    f"[reward_user] ❌ Role ID {quiz_data['rank_to_get']} tidak dapat di-resolve di guild "
                    f"{member.guild.id} ('{member.guild.name}'). "
                    f"Kemungkinan role sudah dihapus atau ID di gatekeeper_settings.yml salah. "
                    f"Role yang tersedia di guild: {[f'{r.name}:{r.id}' for r in member.guild.roles]}"
                )
                return None

            # Cabut semua peran kasta kuis lama agar kasta tetap rapi tunggal
            roles_to_remove = [r for r in all_roles if r in member.roles and r.id != quiz_data["rank_to_get"]]

            _log.info(
                f"[reward_user] Roles to remove: {[r.name for r in roles_to_remove]}, "
                f"role to add: {role_to_get.name}"
            )

            if roles_to_remove:
                await member.remove_roles(*roles_to_remove)

            await member.add_roles(role_to_get)
            _log.info(f"[reward_user] ✅ Berhasil memberikan role '{role_to_get.name}' ke {member}")
            return role_to_get
        else:
            await self.check_if_combination_rank_earned(member)
        return None

    async def check_if_combination_rank_earned(self, member: discord.Member):
        """Memeriksa pencapaian gelar kombinasi (misal: gabungan kelulusan beberapa kuis kasta)."""
        rank_structure = _get_rank_structure(member.guild.id)
        combination_ranks = [rank_data for rank_data in rank_structure if rank_data.get("combination_rank") is True]

        earned_records = await self.bot.GET(GET_PASSED_QUIZZES, (member.guild.id, member.id))
        earned_ranks = [rank[0] for rank in earned_records]

        combination_ranks.reverse()
        for rank in combination_ranks:
            if await self.already_owns_higher_or_same_role(rank["rank_to_get"], member):
                return

            if all(quiz_name in earned_ranks for quiz_name in rank["quizzes_required"]):
                role_to_get = await self.reward_user(member, rank)
                if role_to_get:
                    await self.send_in_announcement_channel(member, f"🎉 {member.mention} kini resmi menyandang kasta agung **{role_to_get.name}**!")

    async def send_in_announcement_channel(self, member: discord.Member, message: str):
        """Mengirimkan log pengumuman kelulusan ke saluran kehormatan (Honor Board) secara dinamis."""
        guild_id = member.guild.id
        settings = gatekeeper_settings.get("rank_settings", {}).get(guild_id) or \
                   gatekeeper_settings.get("rank_settings", {}).get(str(guild_id)) or {}
        announce_channel_id = settings.get("announce_channel") or get_channel_id(guild_id, "honor_board")

        announcement_channel = member.guild.get_channel(announce_channel_id)
        if announcement_channel:
            await announcement_channel.send(message)

    async def already_owns_higher_or_same_role(self, rank_to_get_id: int, member: discord.Member):
        """Memeriksa jika pengguna sudah memiliki jabatan/kasta peran yang setara atau lebih tinggi di hierarki."""
        role_to_get = member.guild.get_role(rank_to_get_id)
        if not role_to_get:
            return False

        all_rank_roles = await self.get_all_quiz_roles(member.guild)
        all_rank_roles_sorted = sorted(all_rank_roles, key=lambda r: r.position, reverse=True)

        for role in member.roles:
            if role in all_rank_roles_sorted and role.position >= role_to_get.position:
                return True
        return False

    async def get_next_attempt_time(self, guild_id: int, user_id: int, quiz_name: str) -> Optional[int]:
        """Mendapatkan Unix timestamp ketersediaan waktu ujian pengguna berikutnya."""
        last_attempt = await self.bot.GET_ONE(GET_LAST_QUIZ_ATTEMPT, (guild_id, user_id, quiz_name))
        if not last_attempt:
            return None

        _, last_attempt_time = last_attempt
        if isinstance(last_attempt_time, str):
            last_attempt_time = datetime.fromisoformat(last_attempt_time.replace("Z", "+00:00"))

        next_attempt_time = last_attempt_time + timedelta(days=6)
        return int(next_attempt_time.timestamp())

    @commands.Cog.listener(name="on_message")
    async def level_up_routine(self, message: discord.Message):
        """Pintu utama pemroses pesan untuk menyaring laporan kuis dari Bot Kotoba."""
        if message.author == self.bot.user:
            return

        if not message.guild:
            return

        # Hanya duga jika pesan dikirim Kotoba atau berisi pemicu k!q
        if not message.author.id == KOTOBA_BOT_ID and "k!q" not in message.content.lower():
            return

        is_valid_command = await self.is_command_input_valid(message)
        if not is_valid_command:
            return

        quiz_id = await get_quiz_id(message)
        if not quiz_id:
            return

        _log.info(f"[level_up_routine] Quiz ID ditemukan: {quiz_id}, guild={message.guild.id}")

        quiz_result = await extract_quiz_result_from_id(quiz_id)
        if not quiz_result:
            await message.channel.send(
                f"⚠️ {message.author.mention} Gagal mengambil hasil laporan dari Kotoba API. Jika Anda merasa lulus kuis, silakan hubungi Staf Kerajaan."
            )
            return

        quiz_data = await self.get_corresponding_quiz_data(message, quiz_result)
        if not quiz_data:
            return

        member_id = int(quiz_result["participants"][0]["discordUser"]["id"])
        member = message.guild.get_member(member_id)
        if not member:
            _log.warning(f"[level_up_routine] Member ID {member_id} tidak ditemukan di guild {message.guild.id}")
            return

        success, quiz_message = await verify_quiz_settings(quiz_data, quiz_result, member)

        _log.info(
            f"[level_up_routine] verify_quiz_settings → success={success}, "
            f"member={member} ({member.id}), quiz='{quiz_data['name']}', message='{quiz_message}'"
        )

        if await self.already_owns_higher_or_same_role(quiz_data["rank_to_get"], member):
            _log.info(
                f"[level_up_routine] Member {member} sudah memiliki role yang setara atau lebih tinggi "
                f"dari rank_to_get ID={quiz_data['rank_to_get']}. Proses reward dilewati."
            )
            return

        if success and quiz_data.get("require_role"):
            required_ids = quiz_data["require_role"] if isinstance(quiz_data["require_role"], list) else [quiz_data["require_role"]]
            required_roles = [message.guild.get_role(rid) for rid in required_ids if message.guild.get_role(rid)]
            if not any(role in member.roles for role in required_roles):
                mentions = ", ".join(role.mention for role in required_roles)
                await message.channel.send(
                    f"⚠️ {member.mention}, Anda membutuhkan salah satu peran berikut untuk melamar kasta ini: {mentions}",
                    allowed_mentions=discord.AllowedMentions(roles=False)
                )
                return

        if success:
            role_earned = await self.reward_user(member, quiz_data)
            await self.send_in_announcement_channel(member, quiz_message)
            try:
                role_display = role_earned.name if role_earned else quiz_data["name"]
                await member.send(f"🎉 Selamat! Anda telah berhasil melampaui ujian kuis kasta **{role_display}**!")
            except discord.Forbidden:
                pass
        else:
            if await self.rank_has_cooldown(message.guild.id, quiz_data["name"]):
                await self.register_quiz_attempt(member, message.channel, quiz_data["name"])

            next_sunday_midnight = get_next_sunday_midnight_from(utcnow())
            next_attempt = int(next_sunday_midnight.timestamp())
            try:
                await member.send(
                    f"🍂 Hasil ujian kuis **{quiz_data['name']}** Anda belum berhasil lulus: {quiz_message}\n"
                    f"Anda diizinkan mengulang kuis kembali pada <t:{next_attempt}:F> (<t:{next_attempt}:R>)."
                )
            except discord.Forbidden:
                pass

    @discord.app_commands.command(name="reset_user_cooldown", description="Menyetel ulang masa tenggang (cooldown) kuis seorang warga (Khusus Admin).")
    @discord.app_commands.guild_only()
    @discord.app_commands.describe(user="Pilih warga", quiz_to_reset="Pilih kuis yang ingin di-reset")
    @discord.app_commands.autocomplete(quiz_to_reset=quiz_autocomplete)
    @discord.app_commands.default_permissions(administrator=True)
    async def clear_user_cooldown(self, interaction: discord.Interaction, user: discord.Member, quiz_to_reset: Optional[str]):
        """Slash command khusus admin untuk membebaskan cooldown kuis member."""
        if not quiz_to_reset:
            await self.bot.RUN(RESET_ALL_QUIZ_ATTEMPTS, (interaction.guild.id, user.id))
            await interaction.response.send_message(f"🧹 Berhasil memutihkan seluruh sanksi cooldown kuis untuk {user.mention}!")
        else:
            rank_structure = _get_rank_structure(interaction.guild.id)
            if not any(quiz_to_reset in rank["name"] for rank in rank_structure):
                await interaction.response.send_message("❌ Nama kuis kasta tidak ditemukan di database server ini.", ephemeral=True)
                return
            await self.bot.RUN(RESET_SPECIFIC_QUIZ_ATTEMPTS, (interaction.guild.id, user.id, quiz_to_reset))
            await interaction.response.send_message(f"🧹 Berhasil membebaskan cooldown kuis `{quiz_to_reset}` untuk {user.mention}!")

    @discord.app_commands.command(name="ranktable", description="Menampilkan peta penyebaran warga berdasarkan kasta kuis saat ini.")
    @discord.app_commands.guild_only()
    async def ranktable(self, interaction: discord.Interaction):
        """Menampilkan bagan statistik kepemilikan kasta di server."""
        await interaction.response.defer()
        quiz_roles = await self.get_all_quiz_roles(interaction.guild)
        if not quiz_roles:
            await interaction.followup.send("❌ Tidak ada kasta kuis terdaftar di server ini.")
            return

        total_ranked_members = len(set([member for role in quiz_roles for member in role.members]))
        if total_ranked_members == 0:
            total_ranked_members = 1  # Hindari ZeroDivisionError

        description_list = []
        for role in quiz_roles:
            members_count = len(role.members)
            percentage = (members_count / total_ranked_members) * 100
            description_list.append(f"{role.mention}: **{members_count}** warga ({percentage:.2f}%)")

        description = "\n".join(description_list)
        description += f"\n\n👥 Total Warga Berpangkat: **{total_ranked_members}**"
        description += f"\n🏰 Total Populasi Server: **{interaction.guild.member_count}**"

        embed = discord.Embed(title="📊 Bagan Sebaran Kasta Kerajaan Kotabi", description=description, color=discord.Color.blurple())
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @discord.app_commands.command(name="rankusers", description="Melihat daftar warga yang menyandang kasta peran tertentu.")
    @discord.app_commands.describe(role="Pilih kasta peran")
    @discord.app_commands.guild_only()
    async def rankusers(self, interaction: discord.Interaction, role: discord.Role):
        """Menampilkan list nama user yang memiliki kasta peran yang dipilih."""
        member_count = len(role.members)
        if member_count == 0:
            await interaction.response.send_message(f"📖 Saat ini tidak ada warga yang memegang kasta {role.mention}.", allowed_mentions=discord.AllowedMentions.none())
            return

        mention_string = [member.mention for member in role.members]
        final_text = " ".join(mention_string)

        if len(final_text) < 1800:
            embed_desc = f"{final_text}\n\n👑 Sebanyak **{member_count}** warga menyandang kasta {role.mention}."
            await interaction.response.send_message(embed_desc, allowed_mentions=discord.AllowedMentions.none())
        else:
            member_string = [f"{member} (ID: {member.id})" for member in role.members]
            member_string.append(f"\nTotal: {member_count} Warga.")

            filepath = "data/rank_user_count.txt"
            os.makedirs("data", exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as text_file:
                text_file.write("\n".join(member_string))

            await interaction.response.send_message(
                f"📝 Daftar warga kasta {role.name} terlalu besar untuk pesan obrolan. Kami melampirkannya sebagai berkas biner di bawah ini:",
                file=discord.File(filepath)
            )
            os.remove(filepath)

    async def rank_to_get_mention(self, guild_id: int, rank: dict):
        """Membantu mendapatkan visualisasi mention peran kasta."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return "`Tidak Terbaca`"
        role = guild.get_role(rank["rank_to_get"])
        return role.mention if role else "`@Peran Terhapus`"

    @discord.app_commands.command(name="list_role_commands", description="Melihat seluruh perintah ujian kuis kasta beserta status kesiapan Anda.")
    @discord.app_commands.describe(guild_id="Ganti ID Server jika ingin memantau klan server lain")
    @discord.app_commands.guild_only()
    async def list_role_commands(self, interaction: discord.Interaction, guild_id: Optional[str]):
        """Menampilkan menu daftar perintah ujian kuis kerajaan secara rapi."""
        if guild_id and not guild_id.isdigit():
            await interaction.response.send_message("❌ ID Guild tidak valid.", ephemeral=True)
            return

        target_guild_id = int(guild_id) if guild_id else interaction.guild.id
        rank_structure = _get_rank_structure(target_guild_id)

        if not rank_structure:
            await interaction.response.send_message("❌ Belum ada susunan kasta yang didefinisikan untuk server ini.", ephemeral=True)
            return

        rank_command_embed = discord.Embed(
            title="📜 Buku Panduan Perintah Ujian Kasta Kotabi",
            color=discord.Color.blurple(),
            timestamp=utcnow()
        )

        for rank in rank_structure:
            if rank.get("command"):
                next_attempt_time = await self.get_next_attempt_time(target_guild_id, interaction.user.id, rank["name"])
                if next_attempt_time and next_attempt_time < int(utcnow().timestamp()):
                    next_attempt_time = None

                description = f"💻 Perintah: `{rank['command']}`\n"
                if rank.get("rank_to_get"):
                    role_mention = await self.rank_to_get_mention(target_guild_id, rank)
                    description += f"🏆 Hadiah Gelar: {role_mention}\n"

                if next_attempt_time and not rank.get("combination_rank"):
                    description += f"⏳ Cooldown: Siap digunakan kembali <t:{next_attempt_time}:R> (<t:{next_attempt_time}:F>)\n"
                else:
                    description += "✅ Cooldown: **Ujian Siap Diambil!**\n"

                if rank.get("require_role"):
                    req_ids = rank['require_role'] if isinstance(rank['require_role'], list) else [rank['require_role']]
                    req_roles = [interaction.guild.get_role(rid) for rid in req_ids if interaction.guild.get_role(rid)]
                    description += f"🔑 Syarat Awal: {', '.join([r.mention for r in req_roles if r])}"

                rank_command_embed.add_field(name=f"⚔️ {rank['name']}", value=description, inline=False)

            elif rank.get("combination_rank"):
                role_mention = await self.rank_to_get_mention(target_guild_id, rank)
                quizzes_text = ", ".join([f"`{q}`" for q in rank['quizzes_required']])
                rank_command_embed.add_field(
                    name=f"⚜️ {rank['name']} (Gelar Kombinasi)",
                    value=f"🧩 Syarat Kelulusan: {quizzes_text}\n🏆 Hadiah Gelar: {role_mention}",
                    inline=False
                )

        await interaction.response.send_message(embed=rank_command_embed, ephemeral=True)

    async def is_on_cooldown_create(self, member: discord.Member, quiz_name: str, rank_has_cooldown: bool):
        """Memeriksa cooldown secara instan sebelum thread ujian baru dilahirkan."""
        if not rank_has_cooldown:
            return False, None
        last_attempt = await self.bot.GET_ONE(GET_LAST_QUIZ_ATTEMPT, (member.guild.id, member.id, quiz_name))
        if not last_attempt:
            return False, None

        _, last_attempt_time = last_attempt
        if isinstance(last_attempt_time, str):
            last_attempt_time = datetime.fromisoformat(last_attempt_time.replace("Z", "+00:00"))

        next_sunday_midnight = get_next_sunday_midnight_from(last_attempt_time)
        if utcnow() < next_sunday_midnight:
            unix_timestamp = int(next_sunday_midnight.timestamp())
            cooldown_message = (
                f"❌ Ujian kuis untuk kasta **{quiz_name}** masih dalam masa cooldown.\n"
                f"Ujian Anda berikutnya baru akan tersedia pada <t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)."
            )
            return True, cooldown_message
        return False, None

    @discord.app_commands.command(name="create_quiz_menu", description="Melahirkan papan tombol interaktif pendaftaran ujian kuis di channel ini (Khusus Admin).")
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def create_quiz_menu(self, interaction: discord.Interaction):
        """Melahirkan menu tombol kuis interaktif di saluran kuis."""
        await interaction.response.send_message("🔮 Sedang memanggil papan tombol kuis...", ephemeral=True)

        view = discord.ui.View(timeout=None)
        view.add_item(DynamicQuizMenu(self, interaction.guild.id))

        settings = gatekeeper_settings.get("rank_settings", {}).get(interaction.guild.id) or \
                   gatekeeper_settings.get("rank_settings", {}).get(str(interaction.guild.id)) or {}
        quiz_menu_message = settings.get("quiz_menu_message") or \
            "🏰 **KOTABI QUIZ CHAMBER** 🏰\n\nSilakan pilih kasta ujian kuis bahasa Jepang Anda di bawah ini untuk mendaftarkan ruang bilik ujian privat!"

        await interaction.channel.send(quiz_menu_message, view=view)


async def setup(bot):
    await bot.add_cog(LevelUp(bot))