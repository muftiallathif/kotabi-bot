"""
lib/journey/queries.py
======================
Semua database query untuk Journey system.
Tidak ada business logic di sini.
Dipanggil hanya oleh JourneyService.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.bot import KotabiBot


# ============================================================
# SQL
# ============================================================

_GET_PASSED_QUIZZES = """
SELECT quiz_name FROM passed_quizzes
WHERE guild_id = ? AND user_id = ?;
"""

_GET_COOLDOWNS = """
SELECT quiz_name, created_at
FROM quiz_attempts
WHERE guild_id = ? AND user_id = ?
ORDER BY created_at DESC;
"""

_GET_ATTEMPT_HISTORY = """
SELECT quiz_name, created_at
FROM quiz_attempts
WHERE guild_id = ? AND user_id = ?
ORDER BY created_at DESC
LIMIT 50;
"""

_GET_LAST_ATTEMPT_PER_QUIZ = """
SELECT quiz_name, MAX(created_at) as last_attempt
FROM quiz_attempts
WHERE guild_id = ? AND user_id = ?
GROUP BY quiz_name;
"""


# ============================================================
# QUERY FUNCTIONS
# ============================================================

async def get_passed_quiz_names(
    bot: "KotabiBot",
    guild_id: int,
    user_id: int,
) -> set[str]:
    """Return set nama kuis yang sudah lulus."""
    rows = await bot.GET(_GET_PASSED_QUIZZES, (guild_id, user_id))
    return {row[0] for row in rows}


async def get_last_attempt_per_quiz(
    bot: "KotabiBot",
    guild_id: int,
    user_id: int,
) -> dict[str, datetime]:
    """
    Return dict quiz_name → datetime attempt terakhir.
    Dipakai oleh rules untuk cek cooldown.
    """
    rows = await bot.GET(_GET_LAST_ATTEMPT_PER_QUIZ, (guild_id, user_id))
    result = {}
    for quiz_name, last_attempt_str in rows:
        try:
            dt = datetime.fromisoformat(
                last_attempt_str.replace("Z", "+00:00")
            )
            result[quiz_name] = dt
        except (ValueError, AttributeError):
            pass
    return result


async def get_attempt_history(
    bot: "KotabiBot",
    guild_id: int,
    user_id: int,
) -> list[tuple[str, datetime]]:
    """
    Return list (quiz_name, timestamp) untuk timeline.
    Urutan: terbaru dulu.
    """
    rows = await bot.GET(_GET_ATTEMPT_HISTORY, (guild_id, user_id))
    result = []
    for quiz_name, created_at_str in rows:
        try:
            dt = datetime.fromisoformat(
                created_at_str.replace("Z", "+00:00")
            )
            result.append((quiz_name, dt))
        except (ValueError, AttributeError):
            pass
    return result
