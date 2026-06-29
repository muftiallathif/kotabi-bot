"""
lib/journey/service.py
======================
Facade untuk Journey system.
Orchestrate queries.py + rules.py.
Tidak ada SQL langsung. Tidak ada Discord embed.

Dipakai oleh:
- cogs/gatekeeper.py (setelah refactor)
- Fitur lain yang butuh data journey user

Penggunaan:
    svc = JourneyService(bot, gatekeeper_settings)

    status = await svc.get_status(guild_id, user_id, member_role_ids)
    action = await svc.get_next_action(guild_id, user_id, member_role_ids)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord

from lib.journey import queries as q
from lib.journey.models import (
    JourneyStatus,
    NextAction,
    NextActionType,
    QuizInfo,
)
from lib.journey.rules import (
    build_attempt_events,
    build_progress_bar,
    build_quiz_info,
    calculate_next_action,
    calculate_progress,
)

if TYPE_CHECKING:
    from core.bot import KotabiBot

_log = logging.getLogger("bot.journey.service")


def _get_rank_structure(settings: dict, guild_id: int) -> list:
    """Helper ambil rank_structure dari settings, coba int key dulu lalu str."""
    rank_map = settings.get("rank_structure", {})
    return rank_map.get(guild_id) or rank_map.get(str(guild_id)) or []


class JourneyService:
    def __init__(self, bot: "KotabiBot", gatekeeper_settings: dict):
        self.bot      = bot
        self.settings = gatekeeper_settings

    def _build_guild_role_map(self, guild: discord.Guild) -> dict[int, str]:
        """Map role_id → role name untuk display di NextAction."""
        return {role.id: role.name for role in guild.roles}

    async def get_status(
        self,
        guild_id:        int,
        user_id:         int,
        member_role_ids: set[int],
        guild:           Optional[discord.Guild] = None,
    ) -> JourneyStatus:
        """
        Ambil snapshot lengkap kondisi journey user.

        Parameter:
            guild_id        — ID server
            user_id         — ID user
            member_role_ids — set role ID yang dimiliki member sekarang
            guild           — discord.Guild object (untuk role map, opsional)
        """
        now            = datetime.now(timezone.utc)
        rank_structure = _get_rank_structure(self.settings, guild_id)

        # Fetch data dari DB (semua query paralel lebih baik,
        # tapi KotabiBot pakai lock jadi sequential untuk safety)
        passed_names  = await q.get_passed_quiz_names(self.bot, guild_id, user_id)
        last_attempts = await q.get_last_attempt_per_quiz(self.bot, guild_id, user_id)
        raw_history   = await q.get_attempt_history(self.bot, guild_id, user_id)

        # Build QuizInfo untuk setiap kuis
        quizzes: list[QuizInfo] = []
        for quiz_config in rank_structure:
            try:
                quiz_info = build_quiz_info(
                    quiz_config=quiz_config,
                    passed_names=passed_names,
                    last_attempts=last_attempts,
                    member_role_ids=member_role_ids,
                    now=now,
                )
                quizzes.append(quiz_info)
            except Exception as e:
                _log.warning(
                    "Gagal build QuizInfo untuk '%s' guild %d: %s",
                    quiz_config.get("name", "?"), guild_id, e
                )

        # Build attempt history events
        history = build_attempt_events(raw_history, passed_names)

        return JourneyStatus(
            guild_id=guild_id,
            user_id=user_id,
            quizzes=quizzes,
            history=history,
        )

    async def get_next_action(
        self,
        guild_id:        int,
        user_id:         int,
        member_role_ids: set[int],
        guild:           Optional[discord.Guild] = None,
    ) -> NextAction:
        """
        Tentukan satu hal yang harus dilakukan user sekarang.
        Ini output utama yang dipakai di semua embed.
        """
        status = await self.get_status(guild_id, user_id, member_role_ids, guild)

        role_map = {}
        if guild:
            role_map = self._build_guild_role_map(guild)

        return calculate_next_action(status.quizzes, role_map)

    def build_journey_embed(
        self,
        status:    JourneyStatus,
        action:    NextAction,
        member:    discord.Member,
        color:     Optional[discord.Color] = None,
    ) -> discord.Embed:
        """
        Buat embed /journey lengkap.
        Dipakai oleh gatekeeper.py untuk command /journey.
        """
        passed, total = calculate_progress(status.quizzes)
        progress_bar  = build_progress_bar(passed, total)

        embed = discord.Embed(
            title=f"📜 Journey Kasta — {member.display_name}",
            color=color or discord.Color.blurple(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        # Progress bar
        embed.add_field(
            name="Progress Keseluruhan",
            value=f"`{progress_bar}`",
            inline=False,
        )

        # Next Action — bagian paling penting
        action_text = self._format_next_action(action)
        embed.add_field(
            name="🎯 Yang Harus Kamu Lakukan Sekarang",
            value=action_text,
            inline=False,
        )

        # Status per kuis (ringkas)
        quiz_lines = []
        for quiz in status.quizzes:
            if quiz.is_combination:
                continue  # combination rank ditampilkan terpisah
            icon = self._availability_icon(quiz)
            quiz_lines.append(f"{icon} {quiz.name}")

        if quiz_lines:
            # Batasi supaya embed tidak terlalu panjang
            display = quiz_lines[:15]
            if len(quiz_lines) > 15:
                display.append(f"... dan {len(quiz_lines) - 15} lainnya")
            embed.add_field(
                name="Daftar Kuis",
                value="\n".join(display),
                inline=False,
            )

        # Combination ranks
        combo_quizzes = [q for q in status.quizzes if q.is_combination]
        if combo_quizzes:
            combo_lines = []
            for quiz in combo_quizzes:
                icon = self._availability_icon(quiz)
                needed = quiz.quizzes_required
                done   = [n for n in needed if n in {q.name for q in status.passed_quizzes}]
                combo_lines.append(
                    f"{icon} {quiz.name} ({len(done)}/{len(needed)} syarat)"
                )
            embed.add_field(
                name="Gelar Kombinasi",
                value="\n".join(combo_lines),
                inline=False,
            )

        embed.set_footer(text=f"Total lulus: {status.total_passed} kuis")
        return embed

    def build_reward_embed(
        self,
        member: discord.Member,
        quiz_name: str,
        role: Optional[discord.Role],
        action: NextAction,
        quiz_channel_id: Optional[int] = None,   # tambah parameter ini
) -> discord.Embed:
        """
        Embed setelah user LULUS kuis.
        Menampilkan reward + next action langsung.
        """
        embed = discord.Embed(
            title=f"🏆 Selamat, {member.display_name}!",
            description=f"Kamu berhasil lulus ujian **{quiz_name}**.",
            color=discord.Color.gold(),
        )

        if role:
            embed.add_field(name="Kasta Baru", value=role.mention, inline=True)

        # Next step langsung di embed reward
        embed.add_field(
            name="━━━━━━━━━━━━━━",
            value=self._format_next_action(action),
            inline=False,
        )

        from lib.journey.models import NextActionType
        if action.type == NextActionType.TAKE_QUIZ:
            channel_mention = f"<#{quiz_channel_id}>" if quiz_channel_id else "saluran quiz-rank-up"
            embed.add_field(
                name="🎯 Mulai Kuis Berikutnya",
                value=(
                    f"Pergi ke {channel_mention} dan pilih **{action.quiz_name}** "
                    f"dari menu kuis yang tersedia."
                ),
                inline=False,
            )

        embed.set_thumbnail(url=member.display_avatar.url)
        return embed

    def build_failure_embed(
        self,
        member:         discord.Member,
        quiz_name:      str,
        reason:         str,
        action:         NextAction,
        wrong_indices:  Optional[list[int]] = None,
    ) -> discord.Embed:
        """
        Embed setelah user GAGAL kuis.
        Menampilkan alasan + soal yang salah + next action.
        """
        embed = discord.Embed(
            title=f"❌ Belum Lulus — {quiz_name}",
            description=reason,
            color=discord.Color.red(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        # Soal yang salah (kalau tersedia dari Kotoba API)
        if wrong_indices:
            indices_str = ", ".join(f"no. {i}" for i in wrong_indices[:10])
            if len(wrong_indices) > 10:
                indices_str += f" ... (+{len(wrong_indices) - 10} lagi)"
            embed.add_field(
                name="📝 Soal yang Perlu Diulang",
                value=indices_str,
                inline=False,
            )

        # Next action (biasanya WAIT dengan cooldown)
        embed.add_field(
            name="━━━━━━━━━━━━━━",
            value=self._format_next_action(action),
            inline=False,
        )

        return embed

    def build_timeline_embed(
        self,
        status: JourneyStatus,
        member: discord.Member,
    ) -> discord.Embed:
        """
        Embed timeline attempt history user.
        Dipakai di /journey dengan button "Lihat Timeline".
        """
        embed = discord.Embed(
            title=f"📜 Timeline Journey — {member.display_name}",
            color=discord.Color.blurple(),
        )

        if not status.history:
            embed.description = "Belum ada riwayat ujian."
            return embed

        lines = []
        for event in status.history[:20]:  # maksimal 20 event
            date_str  = event.timestamp.strftime("%d %b %Y")
            icon      = "✅" if event.passed else "❌"
            lines.append(f"`{date_str}` {icon} **{event.quiz_name}**")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Menampilkan {len(lines)} dari {len(status.history)} percobaan")
        return embed

    # ============================================================
    # PRIVATE HELPERS
    # ============================================================

    def _format_next_action(self, action: NextAction) -> str:
        if action.type == NextActionType.TAKE_QUIZ:
            text = f"**{action.title}**\n{action.description}"
            if action.command:
                text += f"\n\n> Gunakan tombol di menu kuis untuk memulai."
            return text

        if action.type == NextActionType.WAIT:
            ts   = action.cooldown_until
            text = f"**⏳ {action.title}**\n{action.description}"
            if ts:
                text += f"\n\nBisa coba lagi: <t:{ts}:R> (<t:{ts}:F>)"
            return text

        if action.type == NextActionType.LOCKED:
            text = f"**🔒 {action.title}**\n{action.description}"
            if action.missing_roles:
                roles_str = ", ".join(f"`{r}`" for r in action.missing_roles)
                text += f"\n\nSyarat yang belum terpenuhi: {roles_str}"
            return text

        if action.type == NextActionType.COMPLETE:
            return f"**🎉 {action.title}**\n{action.description}"

        return action.description

    def _availability_icon(self, quiz: QuizInfo) -> str:
        from lib.journey.models import QuizAvailability
        icons = {
            QuizAvailability.PASSED:      "✅",
            QuizAvailability.AVAILABLE:   "🎯",
            QuizAvailability.ON_COOLDOWN: "⏳",
            QuizAvailability.LOCKED:      "🔒",
            QuizAvailability.NO_TIMEOUT:  "🎯",
        }
        return icons.get(quiz.availability, "❓")
