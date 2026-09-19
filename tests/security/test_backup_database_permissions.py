"""
Reproduction test for the /backup_database authorization regression
documented in SERVER_ADMIN_SYSTEM.md §2 (locked finding, 2026-09-19).

This is deliberately a REPRODUCTION test, not an acceptance test: as of
now the command has no enforcement backstop at either layer (Level A —
the callback body itself, or Level B — command.checks), so the
assertions below describe and lock in the CURRENT, vulnerable behavior.
That is the point — once a fix is decided and implemented, these exact
assertions are expected to start failing, which is how this test proves
the fix actually closed the gap instead of just looking fixed. Do not
"fix" this file to assert the desired behavior before the fix itself
lands in features/server_admin/backup_database_cog.py — that would
silently make the regression test stop testing anything.

Actor: non-administrator, non-staff member (id=42, no roles).
Resource: the entire SQLite database (features/server_admin/backup_database_cog.py
reads its own module-level PATH_TO_DB, independent of bot.db_path — see
the fake_source_db fixture below).
Action: /backup_database.
"""
import pytest

import features.server_admin.backup_database_cog as backup_database_cog
from features.server_admin.backup_database_cog import DatabaseBackup


@pytest.fixture
def cog(bot):
    return DatabaseBackup(bot)


@pytest.fixture
def fake_source_db(tmp_path, monkeypatch):
    """backup_database_cog.py reads PATH_TO_DB — its own module-level
    constant from the PATH_TO_DB env var at import time — NOT
    `bot.db_path`. That's a real, independent piece of state, so it
    needs its own fixture rather than reusing tmp_db_path. Points it at
    a throwaway file so this test never touches (or depends on) the
    real repo database.
    """
    fake_db = tmp_path / "fake_source.sqlite3"
    fake_db.write_bytes(b"not a real sqlite file, just needs to exist as bytes")
    monkeypatch.setattr(backup_database_cog, "PATH_TO_DB", str(fake_db))
    return str(fake_db)


class TestBackupDatabaseAuthorization:
    async def test_level_a_callback_does_not_reject_non_admin(
        self, cog, interaction_factory, fake_source_db
    ):
        """Level A: call the command body directly. This bypasses
        discord.py's own check-running machinery entirely, so it can
        only ever tell us what the function body itself does — see
        test_level_b below for the complementary check.
        """
        interaction = interaction_factory(user_id=42, is_admin=False)

        await DatabaseBackup.backup_database.callback(cog, interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        assert interaction.followup.send.await_count == 1, (
            "Expected exactly one response sent to the caller."
        )
        _, kwargs = interaction.followup.send.await_args
        assert "file" in kwargs, (
            "This assertion documents the CURRENT (vulnerable) behavior: "
            "a database backup file IS produced and sent to a non-admin "
            "caller, because backup_database_cog.py has no authorization "
            "check anywhere in its call chain (SERVER_ADMIN_SYSTEM.md §2). "
            "If this assertion starts failing, a check may have been "
            "added — update this test (and confirm SERVER_ADMIN_SYSTEM.md "
            "is updated too) to assert the new, correct contract instead "
            "of loosening this assertion to make it pass."
        )

    async def test_level_b_registered_checks_do_not_reject_non_admin(
        self, interaction_factory, run_checks
    ):
        """Level B: evaluate command.checks the way discord.py's real
        dispatch would, without running the callback body at all. This
        rules out "we just forgot to exercise the checks" as an
        alternative explanation for test_level_a's result above — the
        gap exists even when checks ARE actually run, because there are
        none registered.
        """
        interaction = interaction_factory(user_id=42, is_admin=False)

        allowed = await run_checks(DatabaseBackup.backup_database, interaction)

        assert allowed is True, (
            "Documented finding: command.checks is empty for "
            "/backup_database. @app_commands.default_permissions(...) "
            "sets registration metadata only (confirmed empirically "
            "against discord.py 2.7.1 — it does not append anything to "
            "command.checks), unlike its predecessor "
            "@app_commands.checks.has_permissions(administrator=True) "
            "(removed in commit bb3b698), which DOES register a real "
            "predicate. A non-admin is therefore never denied at this "
            "layer either."
        )
        assert DatabaseBackup.backup_database.checks == [], (
            "If this list is no longer empty, a check has been added "
            "back to the command — this test needs to be revisited "
            "together with SERVER_ADMIN_SYSTEM.md §2, not just patched "
            "to keep passing."
        )
