"""
tests/conftest.py — Fixture primitives shared across the whole suite.

Design principles (see tests/README.md for the full rationale, derived
from a joint audit+harness-design pass on 2026-09-19):

- Fixtures here are PRIMITIVES (make_interaction(user=..., roles=...)),
  never pre-baked business decisions (no `staff_interaction` /
  `admin_interaction` fixtures) — different findings need different
  actor/resource combinations, and baking a decision in here would
  silently encode an assumption a specific test should state itself.
- DB layer uses a REAL temporary SQLite file, never `:memory:`.
  core/bot.py opens a fresh `aiosqlite.connect(self.db_path)` per call
  (see RUN/GET/GET_ONE) rather than holding one persistent connection —
  `:memory:` is destroyed when its connection closes, so state written
  by one RUN() would not be visible to a later GET() call. Confirmed
  empirically before writing this file.
- The bot fixture instantiates the REAL `KotabiBot` class, not a stub —
  confirmed empirically that its constructor does no network/login
  (that only happens in .start()/.run(), which tests never call).
- Level A vs Level B are two different, deliberately separate things:
    Level A = call `command.callback(cog, interaction, ...)` directly.
              This bypasses discord.py's own check-running machinery
              entirely — it tells you ONLY what the function body does.
    Level B = evaluate `command.checks` the way discord.py's real
              dispatch would, via `run_checks()` below, WITHOUT running
              the callback body. This is necessary because some Kotabi
              checks are registered decorators (e.g. `@is_staff()`,
              `@app_commands.checks.has_permissions(...)`) that Level A
              silently skips — conflating the two would let a real
              check look broken just because the test never ran it.
  A finding is only "no backend enforcement anywhere" once BOTH layers
  show no rejection (see tests/security/test_backup_database_permissions.py).
"""
import asyncio
import os
import sys
from unittest import mock

import discord
import pytest
from discord import app_commands

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.bot import KotabiBot  # noqa: E402


@pytest.fixture
def tmp_db_path(tmp_path):
    """A real SQLite file on disk. Never `:memory:` — see module docstring."""
    return str(tmp_path / "test_kotabi.sqlite3")


@pytest.fixture
async def bot(tmp_db_path):
    """Real KotabiBot instance, database-only. Never calls .start()/.run()
    or .login(), so no gateway/network connection is ever attempted."""
    instance = KotabiBot(command_prefix="!", path_to_db=tmp_db_path)
    await instance.init_shared_tables()
    yield instance
    await instance.close()


def _make_interaction(*, user_id=1, is_admin=False, roles=(), guild_id=999):
    """Primitive factory. Callers decide what 'admin' or 'roles' means
    for their scenario — this makes no business-logic assumptions about
    what those combinations represent (e.g. it does not know what
    "staff" means; a test that needs a staff actor passes the actual
    staff role id in `roles`)."""
    interaction = mock.MagicMock(spec=discord.Interaction)
    member = mock.MagicMock(spec=discord.Member)
    member.id = user_id
    member.guild_permissions = mock.MagicMock()
    member.guild_permissions.administrator = is_admin
    member.roles = list(roles)
    member.guild = mock.MagicMock()
    member.guild.id = guild_id
    interaction.user = member
    interaction.guild_id = guild_id
    interaction.guild = member.guild
    # Explicitly AsyncMock, not the default MagicMock spec would give —
    # confirmed via the discord.py 2.7.1 probe that is_staff() really
    # calls interaction.response.send_message(...) as a side effect on
    # denial, so this needs to be awaitable and call-inspectable.
    interaction.response = mock.AsyncMock()
    interaction.followup = mock.AsyncMock()
    return interaction


@pytest.fixture
def interaction_factory():
    return _make_interaction


async def run_registered_checks(command, interaction) -> bool:
    """Level B. Replicates discord.py's own check-evaluation contract,
    confirmed empirically against two different Kotabi/discord.py check
    styles before this was written:
      - shared/checks.py's is_staff() etc.: async, returns False on
        denial (and sends a response as a side effect).
      - app_commands.checks.has_permissions(): sync, RAISES
        app_commands.MissingPermissions (a CheckFailure subclass) on
        denial instead of returning False.
    Both must be treated as "denied". Any OTHER exception is a bug in
    the check itself and must propagate — it is not an authorization
    decision, and swallowing it here would hide a real bug behind a
    false "denied" result.
    """
    for check in command.checks:
        try:
            result = check(interaction)
            if asyncio.iscoroutine(result):
                result = await result
            if not result:
                return False
        except app_commands.CheckFailure:
            return False
    return True


@pytest.fixture
def run_checks():
    return run_registered_checks
