from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands

from core.bot import KotabiBot
from lib.media_types import LOG_CHOICES, MEDIA_TYPES
from lib.immersion_helpers import is_valid_channel
from lib.checks import is_vip
from lib.messages import Msg
from typing import Optional

# --- QUERY DATABASE SQLITE --- #

CREATE_USER_GOALS_TABLE = """
CREATE TABLE IF NOT EXISTS user_goals (
    goal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    goal_type TEXT NOT NULL CHECK(goal_type IN ('points', 'amount')),
    goal_value INTEGER NOT NULL,
    end_date TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);"""

CREATE_GOAL_QUERY = """
INSERT INTO user_goals (user_id, media_type, goal_type, goal_value, end_date, created_at)
VALUES (?, ?, ?, ?, ?, ?);"""

CREATE_GOAL_QUERY_DEFAULT = """
INSERT INTO user_goals (user_id, media_type, goal_type, goal_value, end_date)
VALUES (?, ?, ?, ?, ?);"""

GET_USER_GOALS_QUERY = """
SELECT goal_id, media_type, goal_type, goal_value, end_date
FROM user_goals
WHERE user_id = ?;"""

DELETE_GOAL_QUERY = """
DELETE FROM user_goals
WHERE goal_id = ? AND user_id = ?;"""

GET_GOAL_STATUS_QUERY = """
SELECT goal_id, goal_type, goal_value, end_date, created_at,
CASE
    WHEN goal_type = 'points' THEN (
        SELECT COALESCE(SUM(points_received), 0)
        FROM logs
        WHERE user_id = ?
        AND media_type = ?
        AND log_date BETWEEN user_goals.created_at AND user_goals.end_date)
    WHEN goal_type = 'amount' THEN (
        SELECT COALESCE(SUM(amount_logged), 0)
        FROM logs
        WHERE user_id = ?
        AND media_type = ?
        AND log_date BETWEEN user_goals.created_at AND user_goals.end_date)
END as progress
FROM user_goals
WHERE user_id = ?
AND media_type = ?;"""

GET_EXPIRED_GOALS_QUERY = """
SELECT goal_id, media_type, goal_type, goal_value, end_date
FROM user_goals
WHERE user_id = ? AND end_date < ?;"""

DELETE_ALL_EXPIRED_GOALS_QUERY = """
DELETE FROM user_goals
WHERE user_id = ? AND end_date < ?;"""


async def goal_undo_autocomplete(interaction: discord.Interaction, current_input: str):
    """Menyediakan daftar pilihan target kustom untuk dihapus pengguna secara otomatis."""
    current_input = current_input.strip()
    kotabi_bot = interaction.client
    kotabi_bot: KotabiBot
    user_goals = await kotabi_bot.GET(GET_USER_GOALS_QUERY, (interaction.user.id,))
    choices = []

    for goal_id, media_type, goal_type, goal_value, end_date in user_goals:
        end_date_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        end_date_str = end_date_dt.strftime('%Y-%m-%d %H:%M UTC')
        goal_type_id = "Poin" if goal_type == "points" else "Jumlah"
        goal_entry = f"Target {goal_type_id} {goal_value} ({media_type}) s.d. {end_date_str}"
        if current_input.lower() in goal_entry.lower():
            choices.append(discord.app_commands.Choice(name=goal_entry[:100], value=str(goal_id)))

    return choices[:10]


async def check_goal_status(bot: KotabiBot, user_id: int, media_type: str):
    """Menghitung progres pencapaian target immersion dan merender progress bar visual."""
    result = await bot.GET(GET_GOAL_STATUS_QUERY, (user_id, media_type, user_id, media_type, user_id, media_type))
    goal_statuses = []

    for goal_id, goal_type, goal_value, end_date, created_at, progress in result:
        end_date_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        created_at_dt = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        current_time = discord.utils.utcnow()
        timestamp_end = int(end_date_dt.timestamp())
        timestamp_created = int(created_at_dt.timestamp())

        if goal_type == 'amount':
            unit_name = MEDIA_TYPES[media_type]['unit_name']
        else:
            unit_name = 'poin'

        percentage = min(int((progress / goal_value) * 100), 100)
        bar_filled = "🟩" * (percentage // 10)
        bar_empty = "⬜" * (10 - (percentage // 10))
        progress_bar = f"{bar_filled}{bar_empty} ({percentage}%)"

        if (created_at_dt <= current_time <= end_date_dt) and progress < goal_value:
            goal_status = f"🎯 Target sedang berjalan: `{progress}`/`{goal_value}` {unit_name} untuk `{media_type}` - Berakhir <t:{timestamp_end}:R>.\n{progress_bar}"
        elif progress >= goal_value:
            goal_status = f"🎉 Selamat! Kamu telah mencapai targetmu sebesar `{goal_value}` {unit_name} untuk `{media_type}` di antara <t:{timestamp_created}:D> dan <t:{timestamp_end}:D>."
        else:
            goal_status = f"⚠️ Target gagal dicapai: `{progress}`/`{goal_value}` {unit_name} untuk `{media_type}` pada <t:{timestamp_end}:R>.\n{progress_bar}"

        goal_statuses.append(goal_status)

    return goal_statuses


class GoalsCog(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        """Membuat tabel database target pengguna saat modul dimuat."""
        await self.bot.RUN(CREATE_USER_GOALS_TABLE)

    @discord.app_commands.command(name='log_set_goal', description='Pasang target belajar (immersion) untuk dirimu sendiri!')
    @discord.app_commands.describe(
        media_type='Tipe media yang ingin kamu pasang target belajarnya.',
        goal_type='Tipe target, bisa berupa poin atau jumlah (amount).',
        goal_value='Nilai target yang ingin kamu capai.',
        end_date_or_hours='Tanggal batas pencapaian target (format YYYY-MM-DD) atau jumlah jam dari sekarang.',
        start_date='Tanggal mulai pelacakan target (format YYYY-MM-DD atau YYYY-MM-DD HH:MM).'
    )
    @discord.app_commands.command(name='log_set_goal', description='Pasang target belajar (immersion) untuk dirimu sendiri!')
    @discord.app_commands.describe(
        media_type='Tipe media yang ingin kamu pasang target belajarnya.',
        goal_type='Tipe target, bisa berupa poin atau jumlah (amount).',
        goal_value='Nilai target yang ingin kamu capai.',
        end_date_or_hours='Tanggal batas pencapaian target (format YYYY-MM-DD) atau jumlah jam dari sekarang.',
        start_date='Tanggal mulai pelacakan target (format YYYY-MM-DD atau YYYY-MM-DD HH:MM).'
    )
    @discord.app_commands.choices(goal_type=[
        discord.app_commands.Choice(name='Poin', value='points'),
        discord.app_commands.Choice(name='Jumlah (Amount)', value='amount')],
        media_type=LOG_CHOICES)
    @is_vip()
    async def log_set_goal(
        self,
        interaction: discord.Interaction,
        media_type: str,
        goal_type: str,
        goal_value: int,
        end_date_or_hours: str,
        start_date: Optional[str] = None
    ):
        """Slash command untuk membuat target personal (goals) belajar baru."""
        if not await is_valid_channel(interaction):
            return await interaction.response.send_message(Msg.INVALID_CHANNEL, ephemeral=True)

        if goal_value <= 0:
            return await interaction.response.send_message(Msg.GOAL_INVALID_VALUE, ephemeral=True)

        try:
            if end_date_or_hours.isdigit():
                hours = int(end_date_or_hours)
                end_date_dt = (discord.utils.utcnow() + timedelta(hours=hours))
            else:
                end_date_dt = datetime.strptime(end_date_or_hours, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                if end_date_dt < discord.utils.utcnow().replace(minute=0, second=0, microsecond=0):
                    return await interaction.response.send_message(Msg.GOAL_END_DATE_PAST, ephemeral=True)
        except ValueError:
            return await interaction.response.send_message(Msg.GOAL_INVALID_DATE, ephemeral=True)

        # ... sisanya tidak berubah

        if start_date:
            try:
                try:
                    start_date_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
                except ValueError:
                    start_date_dt = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                if start_date_dt > end_date_dt:
                    return await interaction.response.send_message(Msg.GOAL_START_AFTER_END, ephemeral=True)
            except ValueError:
                return await interaction.response.send_message(Msg.GOAL_INVALID_START_DATE_FORMAT, ephemeral=True)
        else:
            start_date_dt = None

        if start_date_dt is None:
            await self.bot.RUN(CREATE_GOAL_QUERY_DEFAULT, (interaction.user.id, media_type, goal_type, goal_value, end_date_dt.strftime('%Y-%m-%d %H:%M:%S')))
        else:
            await self.bot.RUN(CREATE_GOAL_QUERY, (interaction.user.id, media_type, goal_type, goal_value, end_date_dt.strftime('%Y-%m-%d %H:%M:%S'), start_date_dt.strftime('%Y-%m-%d %H:%M:%S')))

        unit_name = MEDIA_TYPES[media_type]['unit_name'] if goal_type == 'amount' else 'poin'
        timestamp = int(end_date_dt.timestamp())

        embed = discord.Embed(title="Target Berhasil Dipasang!", color=discord.Color.green())
        embed.add_field(name="Tipe Media", value=media_type, inline=True)

        goal_type_display = "Poin" if goal_type == "points" else "Jumlah (Amount)"
        embed.add_field(name="Tipe Target", value=goal_type_display, inline=True)
        embed.add_field(name="Nilai Target", value=f"{goal_value} {unit_name}", inline=True)
        if start_date_dt:
            embed.add_field(name="Tanggal Mulai", value=f"<t:{int(start_date_dt.timestamp())}:R>", inline=True)
        embed.add_field(name="Tanggal Berakhir", value=f"<t:{timestamp}:R>", inline=True)
        embed.set_footer(text=f"Target dipasang oleh {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name='log_remove_goal', description='Hapus salah satu target belajarmu.')
    @discord.app_commands.describe(goal_entry='Pilih target belajar yang ingin kamu hapus.')
    @discord.app_commands.autocomplete(goal_entry=goal_undo_autocomplete)
    @is_vip()
    async def log_remove_goal(self, interaction: discord.Interaction, goal_entry: str):
        """Slash command untuk membatalkan atau menghapus target belajar aktif milik pribadi."""
        if not goal_entry.isdigit():
            return await interaction.response.send_message(Msg.GOAL_INVALID_CHOICE, ephemeral=True)

        goal_id = int(goal_entry)
        user_goals = await self.bot.GET(GET_USER_GOALS_QUERY, (interaction.user.id,))
        goal_ids = [goal[0] for goal in user_goals]

        if goal_id not in goal_ids:
            return await interaction.response.send_message(Msg.GOAL_NOT_OWNED, ephemeral=True)

        goal_to_remove = next(goal for goal in user_goals if goal[0] == goal_id)
        goal_type, goal_value, media_type = goal_to_remove[2], goal_to_remove[3], goal_to_remove[1]
        unit_name = MEDIA_TYPES[media_type]['unit_name'] if goal_type == 'amount' else 'poin'

        await self.bot.RUN(DELETE_GOAL_QUERY, (goal_id, interaction.user.id))
        goal_type_display = "Poin" if goal_type == "points" else "Jumlah"
        await interaction.response.send_message(
            Msg.goal_removed(interaction.user.mention, goal_type_display, goal_value, unit_name, media_type)
        )

    @discord.app_commands.command(name='log_view_goals', description='Lihat target belajarmu saat ini atau target milik warga lain.')
    @discord.app_commands.describe(member='Warga yang ingin kamu lihat target belajarnya (opsional).')
    @is_vip()
    async def log_view_goals(self, interaction: discord.Interaction, member: Optional[discord.User] = None):
        """Slash command untuk memonitor daftar target belajar aktif di profil."""
        member = member or interaction.user
        user_goals = await self.bot.GET(GET_USER_GOALS_QUERY, (member.id,))

        if not user_goals:
            return await interaction.response.send_message(Msg.goal_no_active(member.display_name), ephemeral=True)

        embed = discord.Embed(title=f"Target Belajar {member.display_name}", color=discord.Color.blue())
        fields_added = 0

        for media_type in MEDIA_TYPES.keys():
            goal_statuses = await check_goal_status(self.bot, member.id, media_type)
            for goal_status in goal_statuses:
                if fields_added < 24:
                    embed.add_field(name=f"Target {fields_added + 1}", value=goal_status, inline=False)
                    fields_added += 1
                else:
                    embed.add_field(name="Pemberitahuan", value="Kamu telah mencapai batas maksimal tampilan target. Harap bersihkan beberapa target lamamu untuk melihat lebih banyak.", inline=False)
                    break
            if fields_added >= 24:
                break

        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name='log_clear_goals', description='Bersihkan semua target belajar yang telah kedaluwarsa.')
    @is_vip()
    async def log_clear_goals(self, interaction: discord.Interaction):
        """Slash command untuk membersihkan database dari riwayat target kustom yang telah kedaluwarsa."""
        current_time = discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        expired_goals = await self.bot.GET(GET_EXPIRED_GOALS_QUERY, (interaction.user.id, current_time))

        if not expired_goals:
            return await interaction.response.send_message(Msg.GOAL_NONE_EXPIRED, ephemeral=True)

        await self.bot.RUN(DELETE_ALL_EXPIRED_GOALS_QUERY, (interaction.user.id, current_time))

        removed_goals = []
        for _, media_type, goal_type, goal_value, end_date in expired_goals:
            end_time_int = int(datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp())
            goal_type_display = "Poin" if goal_type == "points" else "Jumlah"
            removed_goals.append(f"- Target `{goal_type_display}` sebesar `{goal_value}` untuk `{media_type}` (berakhir <t:{end_time_int}:R>)")

        removed_goals_str = "\n".join(removed_goals)
        await interaction.response.send_message(f"Target kedaluwarsa berikut telah berhasil dibersihkan:\n{removed_goals_str}")


async def setup(bot):
    await bot.add_cog(GoalsCog(bot))