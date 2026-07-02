"""
features/gatekeeper/support/journey_service.py
================================================
Facade untuk Journey system.
Orchestrate journey_queries.py + journey_rules.py.
Tidak ada SQL langsung.

Dipakai oleh:
- features/gatekeeper/gatekeeper_cog.py

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

from features.gatekeeper.support import journey_queries as q
from features.gatekeeper.support.journey_models import (
    AttemptEvent,
    JourneyStatus,
    NextAction,
    NextActionType,
    QuizAvailability,
    QuizInfo,
)
from features.gatekeeper.support.journey_rules import (
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


# Urutan tier grup untuk roadmap — sesuai urutan progression di gatekeeper_settings.yml
_TIER_GROUPS = [
    ("Dasar",   ["【平民】Commoner", "【騎士】Knight"]),
    ("N5",      ["【N5・従男爵】Baronet", "【N5・男爵】Baron"]),
    ("N4",      ["【N4・従子爵】Junior Viscount", "【N4・子爵】Viscount"]),
    ("N3",      ["【N3・従伯爵】Junior Count", "【N3・伯爵】Count"]),
    ("N2",      ["【N2・従侯爵】Junior Marquess", "【N2・侯爵】Marquess"]),
    ("N1",      ["【N1・従公爵】Junior Duke", "【N1・公爵】Duke"]),
    ("Puncak",  [
        "【選帝侯】Prince Elector",
        "【国王】High King",
        "【覇王】Overlord",
        "【皇帝】Emperor",
    ]),
]


class JourneyService:
    def __init__(self, bot: "KotabiBot", gatekeeper_settings: dict):
        self.bot      = bot
        self.settings = gatekeeper_settings

    def _build_guild_role_map(self, guild: discord.Guild) -> dict[int, str]:
        """Map role_id -> role name untuk display di NextAction."""
        return {role.id: role.name for role in guild.roles}

    # ============================================================
    # DATA LAYER
    # ============================================================

    async def get_status(
        self,
        guild_id:        int,
        user_id:         int,
        member_role_ids: set[int],
        guild:           Optional[discord.Guild] = None,
    ) -> JourneyStatus:
        """Ambil snapshot lengkap kondisi journey user."""
        now            = datetime.now(timezone.utc)
        rank_structure = _get_rank_structure(self.settings, guild_id)

        passed_names  = await q.get_passed_quiz_names(self.bot, guild_id, user_id)
        last_attempts = await q.get_last_attempt_per_quiz(self.bot, guild_id, user_id)
        raw_history   = await q.get_attempt_history(self.bot, guild_id, user_id)

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

        # Kuis no_timeout yang lulus first-try tidak tercatat di quiz_attempts,
        # sehingga timeline kosong walau user sudah lulus. Fallback di sini
        # menyisipkan event dari passed_quizzes yang tidak punya riwayat attempt.
        history = self._build_history_with_fallback(raw_history, passed_names, quizzes)

        return JourneyStatus(
            guild_id=guild_id,
            user_id=user_id,
            quizzes=quizzes,
            history=history,
        )

    def _build_history_with_fallback(
        self,
        raw_history:  list[tuple[str, datetime]],
        passed_names: set[str],
        quizzes:      list[QuizInfo],
    ) -> list[AttemptEvent]:
        """
        Kuis no_timeout yang lulus first-try tidak punya baris di quiz_attempts,
        jadi tidak ada timestamp asli. Daripada memalsukan now() (yang merusak
        urutan kronologis), event ini ditandai timestamp=None dan SELALU
        ditampilkan di akhir daftar, bukan diselipkan seolah baru terjadi.
        """
        events  = build_attempt_events(raw_history, passed_names)
        covered = {e.quiz_name for e in events}

        unknown_time_events = [
            AttemptEvent(quiz_name=quiz.name, timestamp=None, passed=True)
            for quiz in quizzes
            if quiz.is_passed and quiz.name not in covered
        ]

        # events sudah terurut terbaru dulu (dari query DESC); unknown di akhir.
        return events + unknown_time_events

    async def get_next_action(
        self,
        guild_id:        int,
        user_id:         int,
        member_role_ids: set[int],
        guild:           Optional[discord.Guild] = None,
    ) -> NextAction:
        """Tentukan satu hal yang harus dilakukan user sekarang."""
        status = await self.get_status(guild_id, user_id, member_role_ids, guild)

        role_map = {}
        if guild:
            role_map = self._build_guild_role_map(guild)

        return calculate_next_action(status.quizzes, role_map)

    # ============================================================
    # EMBED: /journey
    # ============================================================

    def build_journey_embed(
        self,
        status: JourneyStatus,
        action: NextAction,
        member: discord.Member,
        color:  Optional[discord.Color] = None,
    ) -> discord.Embed:
        """
        Embed /journey. Tiga blok:
          1. Progress bar ringkas
          2. Langkah sekarang (satu kalimat)
          3. Peta kasta dikelompokkan per tier
        """
        passed, total = calculate_progress(status.quizzes)
        bar     = build_progress_bar(passed, total)
        percent = round((passed / total) * 100) if total else 0

        embed = discord.Embed(
            title=f"Perjalanan Kasta — {member.display_name}",
            color=color or discord.Color.blurple(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(
            name="Progress",
            value=f"`{bar}`  {passed}/{total} selesai ({percent}%)",
            inline=False,
        )

        embed.add_field(
            name="Langkah sekarang",
            value=self._format_next_action(action, compact=True),
            inline=False,
        )

        roadmap = self._build_grouped_roadmap(status.quizzes)
        if roadmap:
            embed.add_field(name="Peta kasta", value=roadmap, inline=False)

        combo = self._build_combo_summary(status)
        if combo:
            embed.add_field(name="Gelar kombinasi", value=combo, inline=False)

        embed.set_footer(text="Gunakan tombol di bawah untuk melihat riwayat ujian.")
        return embed

    def _build_grouped_roadmap(self, quizzes: list[QuizInfo]) -> str:
        """
        Kelompokkan kuis per tier. Tier yang sudah selesai semua -> satu baris ringkas.
        Tier aktif dan ke depan -> tampilkan per kuis dengan status.
        """
        by_name = {quiz.name: quiz for quiz in quizzes if not quiz.is_combination}
        lines   = []

        for label, names in _TIER_GROUPS:
            group = [by_name[n] for n in names if n in by_name]
            if not group:
                continue

            if all(quiz.is_passed for quiz in group):
                lines.append(f"✅ **{label}** — selesai")
                continue

            parts = []
            for quiz in group:
                short = quiz.name.split("】")[-1].strip() if "】" in quiz.name else quiz.name

                if quiz.availability == QuizAvailability.PASSED:
                    parts.append(f"✅ {short}")
                elif quiz.availability in (QuizAvailability.AVAILABLE, QuizAvailability.NO_TIMEOUT):
                    parts.append(f"**> {short}**")   # posisi aktif
                elif quiz.availability == QuizAvailability.ON_COOLDOWN:
                    parts.append(f"⏳ {short}")
                else:
                    parts.append(f"— {short}")        # locked

            lines.append(f"**{label}**\n" + "  ·  ".join(parts))

        return "\n".join(lines)

    def _build_combo_summary(self, status: JourneyStatus) -> str:
        combo_quizzes = [quiz for quiz in status.quizzes if quiz.is_combination]
        if not combo_quizzes:
            return ""

        passed_names = {quiz.name for quiz in status.passed_quizzes}
        lines = []
        for quiz in combo_quizzes:
            icon  = "✅" if quiz.is_passed else "—"
            done  = [n for n in quiz.quizzes_required if n in passed_names]
            total = len(quiz.quizzes_required)
            lines.append(f"{icon} **{quiz.name}** — {len(done)}/{total} syarat terpenuhi")
        return "\n".join(lines)

    # ============================================================
    # EMBED: setelah lulus kuis
    # ============================================================

    def build_reward_embed(
        self,
        member:          discord.Member,
        quiz_name:       str,
        role:            Optional[discord.Role],
        action:          NextAction,
        quiz_channel_id: Optional[int] = None,
    ) -> discord.Embed:
        """
        Embed setelah user lulus kuis.
        Satu pandangan cukup: apa yang didapat -> apa yang harus dilakukan selanjutnya.
        """
        embed = discord.Embed(
            title=f"Lulus — {quiz_name}",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        if role:
            embed.add_field(name="Kasta baru", value=role.mention, inline=True)

        if action.type == NextActionType.TAKE_QUIZ:
            channel_mention = f"<#{quiz_channel_id}>" if quiz_channel_id else "#quiz-rank-up"
            embed.add_field(
                name="Lanjut ke",
                value=f"**{action.quiz_name}** — buka {channel_mention} dan pilih dari menu kuis.",
                inline=False,
            )
        elif action.type == NextActionType.WAIT and action.cooldown_until:
            embed.add_field(
                name="Kuis berikutnya",
                value=f"Tersedia <t:{action.cooldown_until}:R>.",
                inline=False,
            )
        elif action.type == NextActionType.LOCKED:
            roles = ", ".join(f"`{r}`" for r in action.missing_roles) if action.missing_roles else "syarat tertentu"
            embed.add_field(
                name="Kuis berikutnya",
                value=f"Butuh {roles} sebelum bisa lanjut ke **{action.quiz_name or action.title}**.",
                inline=False,
            )
        elif action.type == NextActionType.COMPLETE:
            embed.add_field(
                name="Status",
                value="Semua kuis yang tersedia sudah selesai.",
                inline=False,
            )

        return embed

    # ============================================================
    # EMBED: setelah gagal kuis
    # ============================================================

    def build_failure_embed(
        self,
        member:        discord.Member,
        quiz_name:     str,
        reason:        str,
        action:        NextAction,
        wrong_indices: Optional[list[int]] = None,
    ) -> discord.Embed:
        """Embed setelah user gagal kuis."""
        embed = discord.Embed(
            title=f"Belum lulus — {quiz_name}",
            description=reason,
            color=discord.Color.red(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        if wrong_indices:
            indices_str = ", ".join(f"no. {i}" for i in wrong_indices[:10])
            if len(wrong_indices) > 10:
                indices_str += f" (+{len(wrong_indices) - 10} lainnya)"
            embed.add_field(name="Soal yang perlu diulang", value=indices_str, inline=False)

        if action.type == NextActionType.WAIT and action.cooldown_until:
            embed.add_field(
                name="Coba lagi",
                value=f"<t:{action.cooldown_until}:R> (<t:{action.cooldown_until}:F>)",
                inline=False,
            )
        else:
            embed.add_field(
                name="Langkah selanjutnya",
                value=self._format_next_action(action, compact=True),
                inline=False,
            )

        return embed

    # ============================================================
    # EMBED: timeline (/journey -> tombol "Lihat Timeline")
    # ============================================================

    def build_timeline_embed(
        self,
        status: JourneyStatus,
        member: discord.Member,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"Riwayat Ujian — {member.display_name}",
            color=discord.Color.blurple(),
        )

        if not status.history:
            embed.description = "Belum ada riwayat ujian. Mulai dari menu kuis di #quiz-rank-up."
            return embed

        lines = []
        for event in status.history[:20]:
            mark = "✅" if event.passed else "✗"
            if event.timestamp is not None:
                date = event.timestamp.strftime("%d %b %Y")
                lines.append(f"`{date}`  {mark}  {event.quiz_name}")
            else:
                lines.append(f"`tanggal tidak tercatat`  {mark}  {event.quiz_name}")

        embed.description = "\n".join(lines)
        shown = min(len(status.history), 20)
        embed.set_footer(text=f"{shown} dari {len(status.history)} percobaan")
        return embed

    # ============================================================
    # PRIVATE HELPERS
    # ============================================================

    def _format_next_action(self, action: NextAction, compact: bool = False) -> str:
        if action.type == NextActionType.TAKE_QUIZ:
            if compact:
                return f"**{action.quiz_name}** — siap diambil sekarang."
            return f"**{action.title}**\n{action.description}\n\nGunakan tombol di menu kuis untuk memulai."

        if action.type == NextActionType.WAIT:
            ts   = action.cooldown_until
            when = f"<t:{ts}:R>" if ts else "sebentar lagi"
            if compact:
                return f"**{action.quiz_name}** sedang cooldown. Coba lagi {when}."
            text = f"**{action.title}**\n{action.description}"
            return text + (f"\n\nCoba lagi: {when}" if ts else "")

        if action.type == NextActionType.LOCKED:
            roles = ", ".join(f"`{r}`" for r in action.missing_roles) if action.missing_roles else "syarat tertentu"
            if compact:
                return f"Butuh {roles} sebelum bisa lanjut ke **{action.quiz_name or action.title}**."
            return f"**{action.title}**\n{action.description}\n\nSyarat: {roles}"

        if action.type == NextActionType.COMPLETE:
            return "Semua kuis selesai."

        return action.description

    def _availability_icon(self, quiz: QuizInfo) -> str:
        icons = {
            QuizAvailability.PASSED:      "✅",
            QuizAvailability.AVAILABLE:   ">",
            QuizAvailability.ON_COOLDOWN: "⏳",
            QuizAvailability.LOCKED:      "—",
            QuizAvailability.NO_TIMEOUT:  ">",
        }
        return icons.get(quiz.availability, "?")