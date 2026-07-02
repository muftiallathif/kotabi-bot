"""
features/gatekeeper/support/journey_models.py
================================================
Data models untuk Journey system.
Tidak ada logic, tidak ada DB, tidak ada Discord.
Hanya struktur data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ============================================================
# ENUMS
# ============================================================

class QuizAvailability(Enum):
    PASSED       = "passed"        # sudah lulus
    AVAILABLE    = "available"     # bisa diambil sekarang
    ON_COOLDOWN  = "on_cooldown"   # lulus tapi masih cooldown
    LOCKED       = "locked"        # require_role belum terpenuhi
    NO_TIMEOUT   = "no_timeout"    # kuis tanpa cooldown (commoner/knight)


class NextActionType(Enum):
    TAKE_QUIZ    = "take_quiz"     # ada kuis yang bisa diambil sekarang
    WAIT         = "wait"          # sedang cooldown
    LOCKED       = "locked"        # belum memenuhi syarat
    COMPLETE     = "complete"      # semua kuis sudah lulus


# ============================================================
# MODELS
# ============================================================

@dataclass
class QuizInfo:
    """
    Representasi satu kuis dalam konteks Journey user.
    Dibuat oleh journey_rules, dipakai oleh journey_service.
    """
    name:         str
    availability: QuizAvailability
    command:      Optional[str]        = None
    rank_to_get:  Optional[int]        = None   # role ID yang didapat kalau lulus
    cooldown_until: Optional[int]      = None   # unix timestamp, None kalau tidak cooldown
    require_role: list[int]            = field(default_factory=list)
    emoji:        Optional[str]        = None
    is_combination: bool               = False
    quizzes_required: list[str]        = field(default_factory=list)

    @property
    def is_available(self) -> bool:
        return self.availability == QuizAvailability.AVAILABLE

    @property
    def is_passed(self) -> bool:
        return self.availability == QuizAvailability.PASSED


@dataclass
class AttemptEvent:
    quiz_name:  str
    timestamp:  Optional[datetime]   # None = waktu tidak diketahui (no_timeout, lulus first-try)
    passed:     bool
    score:      Optional[int] = None
    max_score:  Optional[int] = None


@dataclass
class JourneyStatus:
    """
    Snapshot lengkap kondisi journey seorang user.
    Output dari JourneyService.get_status().
    """
    guild_id:   int
    user_id:    int

    # Semua kuis dengan status masing-masing
    quizzes:    list[QuizInfo]         = field(default_factory=list)

    # History attempt (untuk timeline)
    history:    list[AttemptEvent]     = field(default_factory=list)

    @property
    def passed_quizzes(self) -> list[QuizInfo]:
        return [q for q in self.quizzes if q.is_passed]

    @property
    def available_quizzes(self) -> list[QuizInfo]:
        return [q for q in self.quizzes if q.is_available]

    @property
    def locked_quizzes(self) -> list[QuizInfo]:
        return [q for q in self.quizzes
                if q.availability == QuizAvailability.LOCKED]

    @property
    def cooldown_quizzes(self) -> list[QuizInfo]:
        return [q for q in self.quizzes
                if q.availability == QuizAvailability.ON_COOLDOWN]

    @property
    def total_passed(self) -> int:
        return len(self.passed_quizzes)


@dataclass
class NextAction:
    """
    Satu-satunya hal yang perlu ditampilkan ke user:
    "Apa yang harus kamu lakukan sekarang?"

    Dipakai di:
    - /journey command
    - embed setelah lulus
    - embed setelah gagal
    - DM reminder cooldown
    """
    type:        NextActionType
    title:       str
    description: str

    # Untuk TAKE_QUIZ
    quiz_name:   Optional[str]  = None
    command:     Optional[str]  = None

    # Untuk WAIT
    cooldown_until: Optional[int] = None   # unix timestamp

    # Untuk LOCKED
    missing_roles:  list[str]   = field(default_factory=list)

    # Untuk semua type: preview reward
    reward_role_id: Optional[int] = None