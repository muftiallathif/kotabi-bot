import discord
import os
import random
import csv
import humanize
from typing import Optional
from datetime import timedelta, datetime, timezone
from discord.ext import commands

from core.bot import KotabiBot
from features.immersion.support.autocomplete.anilist import (
    CACHED_ANILIST_RESULTS_CREATE_TABLE_QUERY, CACHED_ANILIST_THUMBNAIL_QUERY, 
    CACHED_ANILIST_TITLE_QUERY, CREATE_ANILIST_FTS5_TABLE_QUERY, 
    CREATE_ANILIST_TRIGGER_DELETE, CREATE_ANILIST_TRIGGER_INSERT, CREATE_ANILIST_TRIGGER_UPDATE
)
from features.immersion.support.autocomplete.vndb import (
    CACHED_VNDB_RESULTS_CREATE_TABLE_QUERY, CACHED_VNDB_THUMBNAIL_QUERY, 
    CACHED_VNDB_TITLE_QUERY, CREATE_VNDB_FTS5_TABLE_QUERY, 
    CREATE_VNDB_TRIGGER_DELETE, CREATE_VNDB_TRIGGER_INSERT, CREATE_VNDB_TRIGGER_UPDATE
)
from features.immersion.support.autocomplete.tmdb import (
    CACHED_TMDB_RESULTS_CREATE_TABLE_QUERY, CACHED_TMDB_THUMBNAIL_QUERY, 
    CACHED_TMDB_TITLE_QUERY, CREATE_TMDB_FTS5_TABLE_QUERY, 
    CREATE_TMDB_TRIGGER_DELETE, CREATE_TMDB_TRIGGER_INSERT, CREATE_TMDB_TRIGGER_UPDATE, 
    CACHED_TMDB_GET_MEDIA_TYPE_QUERY
)
from features.immersion.support.media_types import MEDIA_TYPES, LOG_CHOICES
from features.immersion.support.helpers import is_valid_channel, get_achievement_reached_info, get_current_and_next_achievement
from shared.checks import is_vip
from shared.messages import Msg
from features.immersion.goals_cog import check_goal_status
from shared.username_cache import get_username_db

CREATE_LOGS_TABLE = """
CREATE TABLE IF NOT EXISTS logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    media_name TEXT,
    comment TEXT,
    amount_logged INTEGER NOT NULL,
    points_received REAL NOT NULL,
    log_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    achievement_group TEXT
);"""

CREATE_LOG_QUERY = """
INSERT INTO logs (user_id, media_type, media_name, comment, amount_logged, points_received, log_date, achievement_group)
VALUES (?, ?, ?, ?, ?, ?, ?, ?);"""

GET_CONSECUTIVE_DAYS_QUERY = """
SELECT DISTINCT(DATE(log_date)) AS log_date
FROM logs
WHERE user_id = ?
GROUP BY DATE(log_date)
ORDER BY log_date DESC;"""

GET_POINTS_FOR_CURRENT_MONTH_QUERY = """
SELECT SUM(points_received) AS total_points
FROM logs
WHERE user_id = ? AND strftime('%Y-%m', log_date) = strftime('%Y-%m', 'now');"""

GET_USER_LOGS_QUERY = """
SELECT log_id, media_type, media_name, amount_logged, log_date
FROM logs
WHERE user_id = ?
ORDER BY log_date DESC;"""

GET_TO_BE_DELETED_LOG_QUERY = """
SELECT log_id, media_type, media_name, amount_logged, log_date
FROM logs
WHERE user_id = ? AND log_id = ?;"""

DELETE_LOG_QUERY = """
DELETE FROM logs
WHERE log_id = ? AND user_id = ?;"""

GET_TOTAL_POINTS_FOR_ACHIEVEMENT_GROUP_QUERY = """
SELECT SUM(points_received) AS total_points
FROM logs
WHERE user_id = ? AND achievement_group = ?;"""

GET_USER_LOGS_FOR_EXPORT_QUERY = """
SELECT log_id, media_type, media_name, comment, amount_logged, points_received, log_date
FROM logs
WHERE user_id = ?
ORDER BY log_date DESC;"""

GET_MONTHLY_LEADERBOARD_QUERY = """
SELECT user_id, SUM(points_received) AS total_points, SUM(amount_logged)
FROM logs
WHERE (? = 'ALL' OR strftime('%Y-%m', log_date) = ?)
AND (? IS NULL OR media_type = ?)
GROUP BY user_id
ORDER BY total_points DESC
LIMIT 20;"""

GET_USER_MONTHLY_POINTS_QUERY = """
SELECT SUM(points_received) AS total_points, SUM(amount_logged)
FROM logs
WHERE user_id = ? AND (? = 'ALL' OR strftime('%Y-%m', log_date) = ?)
AND (? IS NULL OR media_type = ?);"""

# Kamus terjemahan nama bulan agar representasi visual waktu lebih natural dalam Bahasa Indonesia
NAMA_BULAN_INDONESIA = {
    "January": "Januari", "February": "Februari", "March": "Maret", "April": "April",
    "May": "Mei", "June": "Juni", "July": "Juli", "August": "Agustus",
    "September": "September", "October": "Oktober", "November": "November", "December": "Desember"
}

async def log_undo_autocomplete(interaction: discord.Interaction, current_input: str):
    """Menyediakan daftar pilihan interaktif log immersion milik user yang bisa dibatalkan."""
    current_input = current_input.strip()
    kotabi_bot = interaction.client
    kotabi_bot: KotabiBot

    user_logs = await kotabi_bot.GET(GET_USER_LOGS_QUERY, (interaction.user.id,))
    choices = []

    for log_id, media_type, media_name, amount_logged, log_date in user_logs:
        unit_name = MEDIA_TYPES[media_type]['unit_name']
        log_date_str = datetime.strptime(log_date, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
        log_name = f"{media_type}: {media_name or 'Tanpa Nama'} ({amount_logged} {unit_name}) pada {log_date_str}"[:100]
        if current_input.lower() in log_name.lower():
            choices.append(discord.app_commands.Choice(name=log_name, value=str(log_id)))

    return choices[:10]


async def log_name_autocomplete(interaction: discord.Interaction, current_input: str):
    """Membantu pencarian nama media secara otomatis berdasarkan jenis media yang dipilih."""
    current_input = current_input.strip()
    if not current_input or len(current_input) <= 1:
        return []
    
    media_type = interaction.namespace['media_type']
    if media_type in MEDIA_TYPES and MEDIA_TYPES[media_type]['autocomplete']:
        result = await MEDIA_TYPES[media_type]['autocomplete'](interaction, current_input)
        return result
    return []


class ImmersionLog(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        """Mempersiapkan tabel log utama serta skema virtual FTS5 untuk pencarian pintar autocomplete."""
        await self.bot.RUN(CREATE_LOGS_TABLE)
        await self.bot.RUN(CACHED_ANILIST_RESULTS_CREATE_TABLE_QUERY)
        await self.bot.RUN(CREATE_ANILIST_FTS5_TABLE_QUERY)
        await self.bot.RUN(CREATE_ANILIST_TRIGGER_DELETE)
        await self.bot.RUN(CREATE_ANILIST_TRIGGER_INSERT)
        await self.bot.RUN(CREATE_ANILIST_TRIGGER_UPDATE)
        await self.bot.RUN(CACHED_VNDB_RESULTS_CREATE_TABLE_QUERY)
        await self.bot.RUN(CREATE_VNDB_FTS5_TABLE_QUERY)
        await self.bot.RUN(CREATE_VNDB_TRIGGER_DELETE)
        await self.bot.RUN(CREATE_VNDB_TRIGGER_INSERT)
        await self.bot.RUN(CREATE_VNDB_TRIGGER_UPDATE)
        await self.bot.RUN(CACHED_TMDB_RESULTS_CREATE_TABLE_QUERY)
        await self.bot.RUN(CREATE_TMDB_FTS5_TABLE_QUERY)
        await self.bot.RUN(CREATE_TMDB_TRIGGER_DELETE)
        await self.bot.RUN(CREATE_TMDB_TRIGGER_INSERT)
        await self.bot.RUN(CREATE_TMDB_TRIGGER_UPDATE)

    @discord.app_commands.command(name='log', description='Catat aktivitas immersion belajar Bahasa Jepang Anda!')
    @discord.app_commands.describe(
        media_type='Jenis media atau aktivitas belajar yang ingin dicatat.',
        amount='Jumlah. Untuk aktivitas berbasis waktu, masukkan durasi dalam hitungan menit.',
        name='Masukkan ID/Judul dari VNDB (VN), AniList (Anime/Manga), TMDB (Listening), atau ketik teks bebas.',
        comment='Catatan atau komentar singkat tambahan mengenai aktivitas Anda.',
        backfill_date='Tanggal log dalam format YYYY-MM-DD atau YYYY-MM-DD HH:MM (Maksimal 7 hari ke belakang).'
    )
    @discord.app_commands.choices(media_type=LOG_CHOICES)
    @discord.app_commands.autocomplete(name=log_name_autocomplete)
    @is_vip()
    async def log(
        self, 
        interaction: discord.Interaction, 
        media_type: str, 
        amount: str, 
        name: Optional[str] = None, 
        comment: Optional[str] = None, 
        backfill_date: Optional[str] = None
    ):
        """Slash Command untuk mendaftarkan riwayat log immersion baru."""
        if not await is_valid_channel(interaction):
            return await interaction.response.send_message(Msg.INVALID_CHANNEL, ephemeral=True)

        if not amount.isdigit():
            return await interaction.response.send_message(Msg.LOG_INVALID_AMOUNT, ephemeral=True)
        amount = int(amount)
        if amount < 0:
            return await interaction.response.send_message(Msg.LOG_NEGATIVE_AMOUNT, ephemeral=True)
        allowed_limit = MEDIA_TYPES[media_type]['max_logged']
        if amount > allowed_limit:
            return await interaction.response.send_message(Msg.log_amount_exceeded(allowed_limit, MEDIA_TYPES[media_type]['log_name']), ephemeral=True)

        if name and len(name) > 150:
            return await interaction.response.send_message(Msg.LOG_NAME_TOO_LONG, ephemeral=True)
        elif name:
            name = name.strip()

        if comment and len(comment) > 200:
            return await interaction.response.send_message(Msg.LOG_COMMENT_TOO_LONG, ephemeral=True)
        elif comment:
            comment = comment.strip()

        if backfill_date is None:
            log_date = discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        else:
            try:
                try:
                    log_date_parsed = datetime.strptime(backfill_date, '%Y-%m-%d %H:%M')
                except ValueError:
                    log_date_parsed = datetime.strptime(backfill_date, '%Y-%m-%d')
                today = discord.utils.utcnow().date()
                if log_date_parsed.date() > today:
                    return await interaction.response.send_message(Msg.LOG_FUTURE_DATE, ephemeral=True)
                if (today - log_date_parsed.date()).days > 7:
                    return await interaction.response.send_message(Msg.LOG_TOO_OLD, ephemeral=True)
                log_date = log_date_parsed.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                return await interaction.response.send_message(Msg.LOG_INVALID_DATE_FORMAT, ephemeral=True)

        await interaction.response.defer()

        points_received = round(amount * MEDIA_TYPES[media_type]['points_multiplier'], 2)
        achievement_group = MEDIA_TYPES[media_type]['Achievement_Group']
        total_achievement_points_before = await self.get_total_points_for_achievement_group(interaction.user.id, achievement_group)

        current_month_points_before = await self.get_points_for_current_month(interaction.user.id)

        await self.bot.RUN(
            CREATE_LOG_QUERY,
            (interaction.user.id, media_type, name, comment, amount,
             points_received, log_date, achievement_group)
        )

        current_month_points_after = await self.get_points_for_current_month(interaction.user.id)

        goal_statuses = await check_goal_status(self.bot, interaction.user.id, media_type)

        total_achievement_points_after = total_achievement_points_before + points_received
        achievement_reached, current_achievement, next_achievement = await get_achievement_reached_info(achievement_group, total_achievement_points_before, total_achievement_points_after)

        random_guild_emoji = random.choice(interaction.guild.emojis) if interaction.guild and interaction.guild.emojis else ""

        consecutive_days = await self.get_consecutive_days_logged(interaction.user.id)
        actual_title = await self.get_title(media_type, name) if name else "Tanpa Nama / Umum"
        thumbnail_url = await self.get_thumbnail_url(media_type, name) if name else None
        source_url = await self.get_source_url(media_type, name) if name else None

        multiplier = MEDIA_TYPES[media_type]['points_multiplier']
        if multiplier < 1:
            needed_for_one = round(1 / multiplier, 2)
            if needed_for_one.is_integer():
                points_received_str = f"`+{points_received}` (X/{int(needed_for_one)})"
            elif needed_for_one < 5:
                points_received_str = f"`+{points_received}` (X/{needed_for_one:.2f})"
            else:
                points_received_str = f"`+{points_received}` (X/{int(needed_for_one)})"
        else:
            received_for_one = round(multiplier, 2)
            if received_for_one.is_integer():
                points_received_str = f"`+{points_received}` (X*{int(received_for_one)})"
            elif received_for_one < 5:
                points_received_str = f"`+{points_received}` (X*{received_for_one:.2f})"
            else:
                points_received_str = f"`+{points_received}` (X*{int(received_for_one)})"

        embed_title = Msg.log_success_title(amount, MEDIA_TYPES[media_type]['unit_name'], media_type) + f" {random_guild_emoji}"

        log_embed = discord.Embed(title=embed_title, color=discord.Color.random())
        log_embed.description = f"[{actual_title}]({source_url})" if source_url else actual_title
        log_embed.add_field(name="Komentar", value=comment or "Tidak ada komentar", inline=False)
        log_embed.add_field(name="Poin Diperoleh", value=points_received_str)
        log_embed.add_field(name="Total Poin/Bulan Ini", value=f"`{current_month_points_before}` → `{current_month_points_after}`")
        log_embed.add_field(name="Streak Belajar", value=f"{consecutive_days} hari beruntun")
        
        if achievement_reached and current_achievement:
            log_embed.add_field(name=Msg.LOG_ACHIEVEMENT_UNLOCKED_FIELD, value=current_achievement["title"], inline=False)
        if next_achievement:
            next_achievement_info = Msg.log_next_achievement_info(
                next_achievement['title'], total_achievement_points_after, next_achievement['points'], achievement_group
            )
            log_embed.add_field(name=Msg.LOG_NEXT_ACHIEVEMENT_FIELD, value=next_achievement_info, inline=False)
        
        for i, goal_status in enumerate(goal_statuses, start=1):
            if len(log_embed.fields) >= 24:
                log_embed.add_field(name=Msg.LOG_FIELD_LIMIT_TITLE, value=Msg.LOG_FIELD_LIMIT_REACHED, inline=False)
                break
            log_embed.add_field(name=f"Target {i}", value=goal_status, inline=False)

        if thumbnail_url:
            log_embed.set_thumbnail(url=thumbnail_url)
        log_embed.set_footer(text=f"Dicatat oleh {interaction.user.display_name} untuk tanggal {log_date.split(' ')[0]}", icon_url=interaction.user.display_avatar.url)

        logged_message = await interaction.followup.send(embed=log_embed)

        if name and (name.startswith("http://") or name.startswith("https://")):
            await logged_message.reply(f"> {name}")
        elif comment and (comment.startswith("http://") or comment.startswith("https://")):
            await logged_message.reply(f"> {comment}")

        if achievement_reached and current_achievement:
            await logged_message.reply(Msg.log_achievement_unlocked_reply(current_achievement['title'], current_achievement['description']))
        
    async def get_consecutive_days_logged(self, user_id: int) -> int:
        """Menghitung jumlah hari beruntun (streak) pengguna melakukan pencatatan log."""
        result = await self.bot.GET(GET_CONSECUTIVE_DAYS_QUERY, (user_id,))
        if not result:
            return 0

        consecutive_days = 0
        today = discord.utils.utcnow().date()

        for row in result:
            log_date = datetime.strptime(row[0], '%Y-%m-%d').date()
            if log_date == today - timedelta(days=consecutive_days):
                consecutive_days += 1
            else:
                break

        return consecutive_days

    async def get_points_for_current_month(self, user_id: int) -> float:
        """Mengambil total poin yang dikumpulkan pengguna selama bulan aktif saat ini."""
        result = await self.bot.GET(GET_POINTS_FOR_CURRENT_MONTH_QUERY, (user_id,))
        if result and result[0] and result[0][0]:
            return round(result[0][0], 2)
        return 0.0

    async def get_thumbnail_url(self, media_type: str, name: str) -> Optional[str]:
        """Membantu resolusi alamat gambar sampul (thumbnail) dari database cache."""
        if MEDIA_TYPES[media_type]['thumbnail_query']:
            result = await self.bot.GET(MEDIA_TYPES[media_type]['thumbnail_query'], (name,))
            if result and result[0]:
                return result[0][0]
        return None

    async def get_title(self, media_type: str, name: str) -> str:
        """Mengambil nama judul media yang ramah dibaca manusia berdasarkan query jenis media."""
        if MEDIA_TYPES[media_type]['title_query']:
            result = await self.bot.GET(MEDIA_TYPES[media_type]['title_query'], (name,))
            if result and result[0]:
                return result[0][0]
        return name

    async def get_source_url(self, media_type: str, name: str) -> Optional[str]:
        """Menghasilkan tautan eksternal (VNDB/AniList/TMDB) menuju media terkait."""
        if not MEDIA_TYPES[media_type]['source_url']:
            return None
        exists_in_db = await self.bot.GET(MEDIA_TYPES[media_type]['title_query'], (name,))
        if not exists_in_db:
            return None
        if media_type == "Listening Time":
            tmdb_media_type = await self.bot.GET(CACHED_TMDB_GET_MEDIA_TYPE_QUERY, (name,))
            if tmdb_media_type and tmdb_media_type[0]:
                return MEDIA_TYPES[media_type]['source_url'].format(tmdb_media_type=tmdb_media_type[0][0]) + name
        return MEDIA_TYPES[media_type]['source_url'] + name

    @discord.app_commands.command(name='log_undo', description='Membatalkan pencatatan log immersion sebelumnya!')
    @discord.app_commands.describe(log_entry='Pilih entri catatan log yang ingin dibatalkan.')
    @discord.app_commands.autocomplete(log_entry=log_undo_autocomplete)
    @is_vip()
    async def log_undo(self, interaction: discord.Interaction, log_entry: str):
        """Memungkinkan pengguna membatalkan dan menghapus catatan log yang salah input."""
        if not await is_valid_channel(interaction):
            return await interaction.response.send_message(Msg.INVALID_CHANNEL, ephemeral=True)

        if not log_entry.isdigit():
            return await interaction.response.send_message(Msg.LOG_INVALID_CHOICE, ephemeral=True)

        log_id = int(log_entry)
        user_logs = await self.bot.GET(GET_USER_LOGS_QUERY, (interaction.user.id,))
        log_ids = [log[0] for log in user_logs]

        if log_id not in log_ids:
            return await interaction.response.send_message(Msg.LOG_NOT_FOUND, ephemeral=True)

        deleted_log_info = await self.bot.GET(GET_TO_BE_DELETED_LOG_QUERY, (interaction.user.id, log_id))
        _, media_type, media_name, amount_logged, log_date = deleted_log_info[0]
        log_date_str = datetime.strptime(log_date, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
        await self.bot.RUN(DELETE_LOG_QUERY, (log_id, interaction.user.id))
        await interaction.response.send_message(
            Msg.log_undo_success(
                interaction.user.mention,
                amount_logged,
                MEDIA_TYPES[media_type]['unit_name'],
                media_type,
                media_name or 'Tanpa Nama',
                log_date_str
            )
        )

    async def get_total_points_for_achievement_group(self, user_id: int, achievement_group: str) -> float:
        """Menghitung jumlah total poin kumulatif yang didapat berdasarkan kelompok pencapaian."""
        result = await self.bot.GET(GET_TOTAL_POINTS_FOR_ACHIEVEMENT_GROUP_QUERY, (user_id, achievement_group))
        if result and result[0] and result[0][0] is not None:
            return result[0][0]
        return 0.0

    @discord.app_commands.command(name='log_achievements', description='Menampilkan semua pencapaian lencana (achievements) Anda!')
    @is_vip()
    async def log_achievements(self, interaction: discord.Interaction):
        """Membaca data poin lalu merender daftar milestone pencapaian yang telah diraih."""
        if not await is_valid_channel(interaction):
            return await interaction.response.send_message(Msg.INVALID_CHANNEL, ephemeral=True)

        user_id = interaction.user.id
        achievements_list = []

        achievement_groups = set(settings_group['Achievement_Group'] for settings_group in MEDIA_TYPES.values())
        for achievement_group in achievement_groups:
            total_points = await self.get_total_points_for_achievement_group(user_id, achievement_group)
            if total_points == 0:
                continue
            achievements_list.append(f"\n**----- {achievement_group.upper()} -----**\n")
            current_achievement, next_achievement = await get_current_and_next_achievement(achievement_group, total_points)
            if current_achievement:
                current_achievement_info = f"**Berhasil Meraih {current_achievement['title']} (`{current_achievement['points']}` poin)**"
                current_achievement_info += f"\n`{current_achievement['description']}`"
                achievements_list.append(current_achievement_info)
            if next_achievement:
                next_achievement_info = f"\n➤ Target Berikutnya: {next_achievement['title']} (`{int(total_points)}/{next_achievement['points']}` poin {achievement_group})"
                achievements_list.append(next_achievement_info)

        if achievements_list:
            achievements_str = "\n".join(achievements_list)
        else:
            achievements_str = Msg.LOG_NO_ACHIEVEMENTS_YET

        embed = discord.Embed(
            title=f"Lencana Pencapaian {interaction.user.display_name}",
            description=achievements_str, 
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name='log_export', description='Ekspor seluruh riwayat log aktivitas immersion Anda sebagai berkas CSV!')
    @discord.app_commands.describe(user='Pilih warga yang ingin diekspor riwayat lognya (Khusus Staf).')
    @is_vip()
    async def log_export(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        """Mengekspor riwayat log ke format .csv tabel data biner."""
        if not await is_valid_channel(interaction):
            return await interaction.response.send_message(Msg.INVALID_CHANNEL, ephemeral=True)

        user_id = user.id if user else interaction.user.id
        user_logs = await self.bot.GET(GET_USER_LOGS_FOR_EXPORT_QUERY, (user_id,))

        if not user_logs:
            return await interaction.response.send_message(Msg.LOG_NO_HISTORY, ephemeral=True)

        csv_filename = f"immersion_logs_{user_id}.csv"
        csv_filepath = os.path.join("/tmp", csv_filename)

        with open(csv_filepath, mode='w', newline='', encoding='utf-8') as csv_file:
            fieldnames = ['ID Log', 'Jenis Media', 'Nama Media', 'Komentar', 'Jumlah Dicatat', 'Poin Diperoleh', 'Tanggal Log']
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            for log in user_logs:
                writer.writerow({
                    'ID Log': log[0],
                    'Jenis Media': log[1],
                    'Nama Media': log[2] or 'Tanpa Nama / Umum',
                    'Komentar': log[3] or 'Tidak ada komentar',
                    'Jumlah Dicatat': log[4],
                    'Poin Diperoleh': log[5],
                    'Tanggal Log': log[6]
                })

        await interaction.response.send_message(Msg.LOG_EXPORT_CSV_READY, file=discord.File(csv_filepath))
        os.remove(csv_filepath)

    @discord.app_commands.command(name='logs', description='Ekspor riwayat log aktivitas Anda dalam bentuk dokumen teks (.txt)!')
    @discord.app_commands.describe(user='Pilih warga yang ingin diekspor riwayat lognya (Khusus Staf).')
    @is_vip()
    async def logs(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        """Mengekspor riwayat belajar pengguna ke format teks baris yang ringkas."""
        if not await is_valid_channel(interaction):
            return await interaction.response.send_message(Msg.INVALID_CHANNEL, ephemeral=True)

        await interaction.response.defer()
        user_id = user.id if user else interaction.user.id
        user_logs = await self.bot.GET(GET_USER_LOGS_FOR_EXPORT_QUERY, (user_id,))

        if not user_logs:
            return await interaction.followup.send(Msg.LOG_NO_HISTORY, ephemeral=True)

        log_filename = f"immersion_logs_{user_id}.txt"
        log_filepath = os.path.join("/tmp", log_filename)
        
        with open(log_filepath, mode='w', encoding='utf-8') as log_file:
            for log in user_logs:
                log_date = datetime.strptime(log[6], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
                media_type = log[1]
                media_name = log[2] or 'Tanpa Nama / Umum'
                amount_logged = log[4]
                unit_name = MEDIA_TYPES[media_type]['unit_name']
                comment = log[3] or 'Tidak ada komentar'

                log_entry = f"{log_date}: {media_type} ({media_name}) -> {amount_logged} {unit_name} | {comment}\n"
                log_file.write(log_entry)

        await interaction.followup.send(Msg.LOG_EXPORT_TXT_READY, file=discord.File(log_filepath))
        os.remove(log_filepath)

    @discord.app_commands.command(name='log_leaderboard', description='Tampilkan papan peringkat (leaderboard) keaktifan belajar bulan ini!')
    @discord.app_commands.describe(
        media_type='Filter papan peringkat berdasarkan jenis media tertentu (opsional).',
        month='Filter berdasarkan bulan tertentu (format YYYY-MM) atau pilih "ALL" untuk sepanjang masa (opsional).'
    )
    @discord.app_commands.choices(media_type=LOG_CHOICES)
    @is_vip()
    async def log_leaderboard(self, interaction: discord.Interaction, media_type: Optional[str] = None, month: Optional[str] = None):
        """Menyusun data statistik poin server dan merender visualisasi peringkat keaktifan teratas."""
        if not await is_valid_channel(interaction):
            return await interaction.response.send_message(Msg.INVALID_CHANNEL, ephemeral=True)

        await interaction.response.defer()

        if not month:
            month = discord.utils.utcnow().strftime('%Y-%m')
        elif month != 'ALL':
            try:
                month = datetime.strptime(month, '%Y-%m').strftime('%Y-%m')
            except ValueError:
                return await interaction.followup.send(Msg.LOG_INVALID_MONTH_FORMAT, ephemeral=True)

        leaderboard_data = await self.bot.GET(GET_MONTHLY_LEADERBOARD_QUERY, (month, month, media_type, media_type))
        user_data = await self.bot.GET(GET_USER_MONTHLY_POINTS_QUERY, (interaction.user.id, month, month, media_type, media_type))

        def human_readable_number(value):
            value = int(value)
            if value < 1000:
                return str(value)
            for unit in ['k', 'jt', 'm', 't']:
                value /= 1000.0
                if value < 1000:
                    return f"{value:.1f}{unit}"
            return f"{value:.1f}P"

        # Lokalisasi nama bulan dari format bahasa Inggris ke nama bulan Bahasa Indonesia
        if month != 'ALL':
            month_obj = datetime.strptime(month, '%Y-%m')
            nama_bulan_en = month_obj.strftime('%B')
            nama_bulan_id = NAMA_BULAN_INDONESIA.get(nama_bulan_en, nama_bulan_en)
            format_bulan_display = f"{nama_bulan_id} {month_obj.year}"
        else:
            format_bulan_display = "Sepanjang Masa"

        embed_title = f"Papan Peringkat Immersion - {format_bulan_display}"
        if media_type:
            embed_title += f" ({media_type})"
            
        embed = discord.Embed(title=embed_title, color=discord.Color.blue())
        unit_name = MEDIA_TYPES[media_type]['unit_name'] if media_type else None
        user_in_top_20 = False

        description = ""

        if leaderboard_data:
            for rank, (user_id, total_points, total_logged) in enumerate(leaderboard_data, start=1):
                user_name = await get_username_db(self.bot, user_id)
                total_points_humanized = human_readable_number(total_points)
                total_logged_humanized = human_readable_number(total_logged)

                # Format ordinal peringkat dalam Bahasa Indonesia
                rank_str = f"Ke-{rank}"

                if interaction.user.id == user_id:
                    description += f"**🥇 {rank_str} (ANDA) {user_name}**: **{total_points_humanized} pts**"
                    if unit_name:
                        description += f" | **{total_logged_humanized} {unit_name}**"
                    description += "\n"
                    user_in_top_20 = True
                else:
                    description += f"**🔹 {rank_str} {user_name}**: {total_points_humanized} pts"
                    if unit_name:
                        description += f" | {total_logged_humanized} {unit_name}"
                    description += "\n"
        else:
            description = Msg.LOG_LEADERBOARD_EMPTY

        if not user_in_top_20 and user_data and user_data[0] and user_data[0][0]:
            user_points = human_readable_number(user_data[0][0])
            user_logged = human_readable_number(user_data[0][1])
            description += f"\n**Anda**: **{user_points} pts**"
            if unit_name:
                description += f" | **{user_logged} {unit_name}**"
        elif not user_in_top_20:
            description += f"\n**Anda**: **0 pts**"

        embed.description = description
        await interaction.followup.send(embed=embed)


async def setup(bot):
    """Mendaftarkan modul utama ImmersionLog ke core bot launcher."""
    await bot.add_cog(ImmersionLog(bot))