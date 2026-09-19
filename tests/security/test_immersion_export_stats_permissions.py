"""
Reproduction tests for finding #2 (IMMERSION_SYSTEM.md §14).

/log_export, /logs, and /log_stats all claim "Khusus Staf" in their
Discord UI description for the `user` parameter, but:
  - /log_export and /logs are actually gated by @is_vip() — the WRONG
    population (any VIP, not specifically staff).
  - /log_stats has NO gate at all, at either Level A or Level B.
All three also send their successful result non-ephemeral (corrected
in IMMERSION_SYSTEM.md on 2026-09-19 — this was previously
undocumented for /log_export and /logs).

Per the locked split: authorization and visibility are tested
SEPARATELY throughout this file, so a future fix that changes WHO can
call these commands is distinguishable from a fix that changes HOW the
result is displayed — they may not be fixed by the same change.

These are reproduction tests, not acceptance tests (see tests/README.md).
Every assertion here currently PASSES because it documents CURRENT,
undesired behavior. Do not flip them to assert the desired behavior
before the corresponding fix actually lands in features/immersion/.
"""
import io
from unittest import mock

import discord
import pytest

import features.immersion.log_cog as log_cog_module
import features.immersion.stats_cog as stats_cog_module
import shared.checks as checks_module
from features.immersion.log_cog import ImmersionLog, CREATE_LOGS_TABLE, CREATE_LOG_QUERY
from features.immersion.stats_cog import ImmersionStats

FAKE_STAFF_ROLE_ID = 777
FAKE_VIP_ROLE_ID = 555
TARGET_USER_ID = 99999


@pytest.fixture(autouse=True)
def isolated_role_config(monkeypatch):
    """@is_vip() (from shared/checks.py) calls get_staff_role_ids()/
    get_vip_role_ids(), which by default read real YAML off disk
    (shared/server_map.yml, membership_settings.yml). Patch both to a
    small, test-controlled mapping so this test never depends on (or
    could be silently broken by someone editing) the real config.
    """
    monkeypatch.setattr(
        checks_module, "get_staff_role_ids", lambda gid: {"royal_guard": FAKE_STAFF_ROLE_ID}
    )
    monkeypatch.setattr(
        checks_module, "get_vip_role_ids", lambda gid: {"traveler": FAKE_VIP_ROLE_ID}
    )


@pytest.fixture(autouse=True)
def bypass_channel_gate(monkeypatch):
    """is_valid_channel() is a separate concern (PERMISSION_MATRIX.md
    territory) from the authorization/visibility finding under test
    here — always allow, so it never masks the assertions below."""

    async def _always_valid(interaction):
        return True

    monkeypatch.setattr(log_cog_module, "is_valid_channel", _always_valid)
    monkeypatch.setattr(stats_cog_module, "is_valid_channel", _always_valid)


def _make_role(role_id):
    role = mock.MagicMock(spec=discord.Role)
    role.id = role_id
    return role


def _make_target_user():
    user = mock.MagicMock(spec=discord.User)
    user.id = TARGET_USER_ID
    return user


@pytest.fixture
async def seeded_log(bot):
    """One immersion log row for TARGET_USER_ID, dated "now" so it
    falls inside /log_stats's default (current month) query window,
    plus a cached username row so get_username_db() (used by
    /log_stats) never falls through to a real bot.fetch_user() network
    call — that path would otherwise try to hit Discord's live API.
    """
    import datetime

    await bot.RUN(CREATE_LOGS_TABLE)
    log_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await bot.RUN(
        CREATE_LOG_QUERY,
        (TARGET_USER_ID, "Book", "Some Book", None, 10, 10.0, log_date, "Reading"),
    )
    await bot.RUN(
        "INSERT INTO users (discord_user_id, user_name) VALUES (?, ?) "
        "ON CONFLICT(discord_user_id) DO UPDATE SET user_name = excluded.user_name;",
        (TARGET_USER_ID, "TargetUser"),
    )


class TestLogExportAuthorization:
    """Actor: VIP, but explicitly NOT holding the staff role.
    Resource: another user's (TARGET_USER_ID) immersion log history.
    Action: /log_export.
    """

    async def test_level_b_vip_non_staff_passes_the_check(
        self, interaction_factory, run_checks
    ):
        interaction = interaction_factory(
            user_id=1, is_admin=False, roles=(_make_role(FAKE_VIP_ROLE_ID),)
        )

        allowed = await run_checks(ImmersionLog.log_export, interaction)

        assert allowed is True, (
            "Documented finding: /log_export's UI says 'Khusus Staf', "
            "but the actual gate is @is_vip() — a VIP member who does "
            "NOT hold the staff role passes anyway."
        )

    async def test_level_b_non_vip_is_still_rejected(self, interaction_factory, run_checks):
        """Sanity check the OTHER direction, so this finding isn't
        overstated as 'zero gate' — @is_vip() does exist and does
        block a plain member with no VIP role at all. The finding is
        specifically a wrong-population mismatch, not a missing gate.
        """
        interaction = interaction_factory(user_id=2, is_admin=False, roles=())

        allowed = await run_checks(ImmersionLog.log_export, interaction)

        assert allowed is False

    async def test_level_a_export_is_produced_for_non_staff_vip(
        self, bot, interaction_factory, seeded_log
    ):
        cog = ImmersionLog(bot)
        interaction = interaction_factory(
            user_id=1, is_admin=False, roles=(_make_role(FAKE_VIP_ROLE_ID),)
        )

        await ImmersionLog.log_export.callback(cog, interaction, user=_make_target_user())

        assert interaction.response.send_message.await_count == 1
        _, kwargs = interaction.response.send_message.call_args
        assert "file" in kwargs, (
            "Current (vulnerable) behavior: a CSV export of another "
            "user's log history IS produced and sent for a caller who "
            "is VIP but not staff."
        )


class TestLogExportVisibility:
    """Separate from authorization on purpose — a fix that adds a real
    staff check does not automatically fix this, and vice versa."""

    async def test_result_is_not_ephemeral(self, bot, interaction_factory, seeded_log):
        cog = ImmersionLog(bot)
        interaction = interaction_factory(
            user_id=1, is_admin=False, roles=(_make_role(FAKE_VIP_ROLE_ID),)
        )

        await ImmersionLog.log_export.callback(cog, interaction, user=_make_target_user())

        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is not True, (
            "Documented finding (IMMERSION_SYSTEM.md §14): the exported "
            "CSV is sent non-ephemeral — visible to the whole channel, "
            "not just the caller. log_cog.py:472 has no ephemeral=True."
        )


class TestLogsAuthorization:
    """Same shape as /log_export — separate command, separate file
    format (.txt), same @is_vip() gate."""

    async def test_level_b_vip_non_staff_passes_the_check(
        self, interaction_factory, run_checks
    ):
        interaction = interaction_factory(
            user_id=1, is_admin=False, roles=(_make_role(FAKE_VIP_ROLE_ID),)
        )

        allowed = await run_checks(ImmersionLog.logs, interaction)

        assert allowed is True, (
            "Documented finding: /logs' UI says 'Khusus Staf', but the "
            "actual gate is @is_vip() — same mismatch as /log_export."
        )

    async def test_level_a_export_is_produced_for_non_staff_vip(
        self, bot, interaction_factory, seeded_log
    ):
        cog = ImmersionLog(bot)
        interaction = interaction_factory(
            user_id=1, is_admin=False, roles=(_make_role(FAKE_VIP_ROLE_ID),)
        )

        await ImmersionLog.logs.callback(cog, interaction, user=_make_target_user())

        assert interaction.followup.send.await_count == 1
        _, kwargs = interaction.followup.send.call_args
        assert "file" in kwargs, (
            "Current (vulnerable) behavior: a .txt export of another "
            "user's log history IS produced and sent for a caller who "
            "is VIP but not staff."
        )


class TestLogsVisibility:
    async def test_result_is_not_ephemeral(self, bot, interaction_factory, seeded_log):
        cog = ImmersionLog(bot)
        interaction = interaction_factory(
            user_id=1, is_admin=False, roles=(_make_role(FAKE_VIP_ROLE_ID),)
        )

        await ImmersionLog.logs.callback(cog, interaction, user=_make_target_user())

        _, kwargs = interaction.followup.send.call_args
        assert kwargs.get("ephemeral") is not True, (
            "Documented finding (IMMERSION_SYSTEM.md §14): the exported "
            ".txt file is sent non-ephemeral. log_cog.py:508 has no "
            "ephemeral=True."
        )


@pytest.fixture(autouse=True)
def mocked_chart_rendering(monkeypatch):
    """/log_stats's chart generation (matplotlib/seaborn) is incidental
    machinery, not the subject of this finding — mock it so these tests
    stay fast/deterministic and don't depend on font availability in
    whatever environment runs them. The DB layer stays real (see
    tests/README.md's Level A/B/C philosophy); only this rendering step
    is mocked."""
    monkeypatch.setattr(stats_cog_module, "generate_bar_chart", lambda *a, **k: io.BytesIO(b"fake-png"))
    monkeypatch.setattr(stats_cog_module, "generate_heatmap", lambda *a, **k: io.BytesIO(b"fake-png"))
    monkeypatch.setattr(stats_cog_module, "embedded_info", lambda *a, **k: ("dummy breakdown", 10.0))


class TestLogStatsAuthorization:
    """Actor: zero privilege at all — not VIP, not staff, not admin.
    Resource: another user's immersion stats.
    Action: /log_stats.
    """

    async def test_level_b_has_no_registered_checks(self):
        assert ImmersionStats.log_stats.checks == [], (
            "Documented finding: /log_stats has no decorator-based "
            "check at all — unlike /log_export and /logs, there isn't "
            "even a wrong-population gate here, there is nothing."
        )

    async def test_level_a_stats_are_produced_for_unprivileged_actor(
        self, bot, interaction_factory, seeded_log
    ):
        cog = ImmersionStats(bot)
        interaction = interaction_factory(user_id=3, is_admin=False, roles=())

        await ImmersionStats.log_stats.callback(cog, interaction, user=_make_target_user())

        assert interaction.followup.send.await_count == 2, (
            "Current (vulnerable) behavior: both chart messages are "
            "sent for a completely unprivileged caller viewing another "
            "user's stats."
        )


class TestLogStatsVisibility:
    async def test_result_is_not_ephemeral(self, bot, interaction_factory, seeded_log):
        cog = ImmersionStats(bot)
        interaction = interaction_factory(user_id=3, is_admin=False, roles=())

        await ImmersionStats.log_stats.callback(cog, interaction, user=_make_target_user())

        for call in interaction.followup.send.call_args_list:
            _, kwargs = call
            assert kwargs.get("ephemeral") is not True, (
                "Documented finding (IMMERSION_SYSTEM.md §14): "
                "/log_stats results are sent non-ephemeral. "
                "stats_cog.py:303-304 has no ephemeral=True on either "
                "followup.send() call."
            )
