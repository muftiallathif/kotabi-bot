"""
lib/journey/rules.py
====================
Pure business logic untuk Journey system.
Tidak ada database. Tidak ada Discord API.
Semua input adalah Python objects, semua output adalah Python objects.

Ini yang paling mudah di-unit test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from lib.journey.models import (
    AttemptEvent,
    NextAction,
    NextActionType,
    QuizAvailability,
    QuizInfo,
)


# ============================================================
# CONSTANTS
# ============================================================

# Cooldown reset setiap Minggu tengah malam UTC
# (sama dengan logika di gatekeeper.py yang sudah ada)


def _get_next_sunday_midnight(dt: datetime) -> datetime:
    """Sama persis dengan get_next_sunday_midnight_from di gatekeeper.py."""
    days_until_sunday = (6 - dt.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7
    next_sunday = dt + timedelta(days=days_until_sunday)
    return datetime(
        next_sunday.year, next_sunday.month, next_sunday.day,
        0, 0, 0, tzinfo=timezone.utc
    )


# ============================================================
# AVAILABILITY RULES
# ============================================================

def calculate_quiz_availability(
    quiz_config:      dict,
    passed_names:     set[str],
    last_attempts:    dict[str, datetime],
    member_role_ids:  set[int],
    now:              datetime,
) -> QuizAvailability:
    """
    Hitung status availability satu kuis untuk satu user.

    Parameter:
        quiz_config     — satu entry dari rank_structure di gatekeeper_settings.yml
        passed_names    — set nama kuis yang sudah lulus (dari DB)
        last_attempts   — dict quiz_name → datetime attempt terakhir (dari DB)
        member_role_ids — set role ID yang dimiliki member (dari Discord)
        now             — waktu sekarang (UTC)

    Return: QuizAvailability
    """
    name = quiz_config["name"]

    # Sudah lulus
    if name in passed_names:
        return QuizAvailability.PASSED

    # Kuis tanpa timeout (no_timeout=True) — selalu available
    if quiz_config.get("no_timeout", False):
        return QuizAvailability.NO_TIMEOUT

    # Cek require_role
    require_role = quiz_config.get("require_role")
    if require_role:
        required_ids = (
            require_role if isinstance(require_role, list) else [require_role]
        )
        if not any(rid in member_role_ids for rid in required_ids):
            return QuizAvailability.LOCKED

    # Cek cooldown
    last_attempt = last_attempts.get(name)
    if last_attempt:
        # Pastikan timezone-aware
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        next_sunday = _get_next_sunday_midnight(last_attempt)
        if now < next_sunday:
            return QuizAvailability.ON_COOLDOWN

    return QuizAvailability.AVAILABLE


def build_quiz_info(
    quiz_config:      dict,
    passed_names:     set[str],
    last_attempts:    dict[str, datetime],
    member_role_ids:  set[int],
    now:              datetime,
) -> QuizInfo:
    """
    Bangun QuizInfo lengkap dari satu entry rank_structure.
    """
    name = quiz_config["name"]
    availability = calculate_quiz_availability(
        quiz_config, passed_names, last_attempts, member_role_ids, now
    )

    # Hitung cooldown_until kalau sedang ON_COOLDOWN
    cooldown_until = None
    if availability == QuizAvailability.ON_COOLDOWN:
        last_attempt = last_attempts.get(name)
        if last_attempt:
            if last_attempt.tzinfo is None:
                last_attempt = last_attempt.replace(tzinfo=timezone.utc)
            next_sunday = _get_next_sunday_midnight(last_attempt)
            cooldown_until = int(next_sunday.timestamp())

    # require_role
    require_role_raw = quiz_config.get("require_role") or []
    require_role_ids = (
        require_role_raw if isinstance(require_role_raw, list)
        else [require_role_raw]
    )

    return QuizInfo(
        name=name,
        availability=availability,
        command=quiz_config.get("command"),
        rank_to_get=quiz_config.get("rank_to_get"),
        cooldown_until=cooldown_until,
        require_role=require_role_ids,
        emoji=quiz_config.get("emoji"),
        is_combination=bool(quiz_config.get("combination_rank", False)),
        quizzes_required=quiz_config.get("quizzes_required", []),
    )


# ============================================================
# NEXT ACTION RULE
# ============================================================

def calculate_next_action(
    quizzes:         list[QuizInfo],
    guild_role_map:  dict[int, str],   # role_id → role name, untuk display
) -> NextAction:
    """
    Dari list QuizInfo, tentukan satu NextAction yang paling relevan.

    Priority:
    1. AVAILABLE — ada kuis yang bisa diambil sekarang
    2. ON_COOLDOWN — semua kuis sedang cooldown
    3. LOCKED — butuh role yang belum dimiliki
    4. COMPLETE — semua sudah lulus
    """
    available = [q for q in quizzes if q.is_available]
    if available:
        # Ambil yang pertama (urutan di rank_structure = urutan progression)
        next_quiz = available[0]
        return NextAction(
            type=NextActionType.TAKE_QUIZ,
            title=next_quiz.name,
            description=f"Kuis berikutnya dalam perjalananmu.",
            quiz_name=next_quiz.name,
            command=next_quiz.command,
            reward_role_id=next_quiz.rank_to_get,
        )

    on_cooldown = [q for q in quizzes
                   if q.availability == QuizAvailability.ON_COOLDOWN]
    if on_cooldown:
        # Cooldown yang paling cepat selesai
        soonest = min(
            on_cooldown,
            key=lambda q: q.cooldown_until or 0
        )
        return NextAction(
            type=NextActionType.WAIT,
            title=f"Cooldown: {soonest.name}",
            description="Kamu masih dalam masa tunggu setelah percobaan sebelumnya.",
            quiz_name=soonest.name,
            cooldown_until=soonest.cooldown_until,
        )

    locked = [q for q in quizzes
              if q.availability == QuizAvailability.LOCKED]
    if locked:
        next_locked = locked[0]
        missing_names = [
            guild_role_map.get(rid, f"Role {rid}")
            for rid in next_locked.require_role
        ]
        return NextAction(
            type=NextActionType.LOCKED,
            title=f"Terkunci: {next_locked.name}",
            description="Kamu perlu memenuhi syarat sebelum bisa mengambil kuis ini.",
            quiz_name=next_locked.name,
            missing_roles=missing_names,
            reward_role_id=next_locked.rank_to_get,
        )

    return NextAction(
        type=NextActionType.COMPLETE,
        title="Journey Selesai",
        description="Kamu telah menyelesaikan semua kuis yang tersedia. 🎉",
    )


# ============================================================
# PROGRESS CALCULATION
# ============================================================

def calculate_progress(quizzes: list[QuizInfo]) -> tuple[int, int]:
    """
    Return (passed_count, total_count) untuk progress bar.
    Hanya hitung kuis non-combination yang punya command.
    """
    countable = [
        q for q in quizzes
        if not q.is_combination and q.command
    ]
    passed = sum(1 for q in countable if q.is_passed)
    return passed, len(countable)


def build_progress_bar(passed: int, total: int, length: int = 10) -> str:
    """
    Buat progress bar visual.
    Contoh output: ████████░░ (8/10)
    """
    if total == 0:
        return "░" * length + " (0/0)"
    filled = round((passed / total) * length)
    bar = "█" * filled + "░" * (length - filled)
    return f"{bar} ({passed}/{total})"


def build_attempt_events(
    attempt_history:  list[tuple[str, datetime]],
    passed_names:     set[str],
) -> list[AttemptEvent]:
    """
    Konversi raw attempt history ke list AttemptEvent.
    passed=True kalau nama kuis ada di passed_names DAN
    ini adalah attempt terakhir untuk kuis tersebut.
    """
    events = []
    # Track kuis mana yang sudah "diklaim" sebagai passed
    claimed_passed = set()

    for quiz_name, timestamp in attempt_history:
        is_passed = (
            quiz_name in passed_names
            and quiz_name not in claimed_passed
        )
        if is_passed:
            claimed_passed.add(quiz_name)

        events.append(AttemptEvent(
            quiz_name=quiz_name,
            timestamp=timestamp,
            passed=is_passed,
        ))

    return events
