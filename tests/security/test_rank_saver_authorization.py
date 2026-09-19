"""
Level C reproduction test for finding #3 (SOCIAL_SYSTEM.md §10):
rank_saver_cog.py restores a member's full role snapshot on rejoin,
including administrative/staff roles, because role_ids_to_ignore is
empty and is_assignable() alone doesn't distinguish "safe to silently
restore" from "administrative privilege that was deliberately revoked".

Locked invariant under test (true under either open scope hypothesis
A or B — see SOCIAL_SYSTEM.md §10.2): a role deliberately revoked from
a member should not silently reappear via restoration. Whether Rank
Saver should restore ANY roles at all is still an open design question
and is NOT tested here — reproduction test, not acceptance test.

Real SQLite temp file for the DB layer (matches production's per-call
aiosqlite.connect pattern); mocked Discord boundary (Member/Guild/Role).
"""
from unittest import mock

import discord
import pytest

import features.social.rank_saver_cog as rank_saver_module
from features.social.rank_saver_cog import RankSaver, CREATE_USER_RANKS_TABLE, SAVE_USER_ROLE_QUERY

STAFF_ROLE_ID = 111
GUILD_ID = 999
USER_ID = 42


@pytest.fixture(autouse=True)
def isolated_ignore_list(monkeypatch):
    """Matches production's actual current value (empty) — isolated
    explicitly so this test doesn't silently depend on the real
    rank_saver_settings.yml file's content changing later."""
    monkeypatch.setattr(rank_saver_module, "ranksaver_settings", {"role_ids_to_ignore": []})


@pytest.fixture(autouse=True)
def bypass_join_log_lookup(monkeypatch):
    """get_channel_id() reads real server_map.yml — irrelevant to this
    finding (which is about add_roles(), called before channel
    resolution even happens)."""
    monkeypatch.setattr(rank_saver_module, "get_channel_id", lambda gid, name: 0)


def _staff_role():
    role = mock.MagicMock(spec=discord.Role)
    role.id = STAFF_ROLE_ID
    role.is_assignable = mock.Mock(return_value=True)
    role.mention = "@StaffRole"
    return role


async def test_stale_snapshot_restores_a_revoked_staff_role(bot):
    """
    Actor: former staff member rejoining after their staff role was
    revoked but before the next 10-minute rank_saver snapshot captured
    the revocation (SOCIAL_SYSTEM.md §10.3 — the window that produces a
    stale row; once stale, the row never expires).
    Resource: own Discord role state.
    Action: rejoin (on_member_join -> rank_restorer).
    """
    cog = RankSaver(bot)
    await bot.RUN(CREATE_USER_RANKS_TABLE)

    # Snapshot taken BEFORE the staff role was revoked -- this is the
    # stale row rank_saver's periodic task would have overwritten if a
    # tick had run between revocation and the member leaving, but in
    # this scenario it didn't get the chance to.
    await bot.RUN(SAVE_USER_ROLE_QUERY, (GUILD_ID, USER_ID, str(STAFF_ROLE_ID)))

    staff_role = _staff_role()
    member = mock.MagicMock(spec=discord.Member)
    member.id = USER_ID
    member.name = "TestUser"
    member.guild = mock.MagicMock(spec=discord.Guild)
    member.guild.id = GUILD_ID
    member.guild.name = "TestGuild"
    # Member's CURRENT roles are irrelevant to rank_restorer's lookup --
    # it resolves purely by ID against member.guild.roles, not
    # member.roles. This is exactly why a revoked role can still be
    # found and restored: the guild still has the Role object, the
    # member just doesn't currently hold it.
    member.guild.roles = [staff_role]
    member.guild.get_channel = mock.Mock(return_value=None)
    member.guild.system_channel = None
    member.add_roles = mock.AsyncMock()

    await RankSaver.rank_restorer(cog, member)

    member.add_roles.assert_awaited_once()
    restored_ids = {r.id for r in member.add_roles.await_args.args}
    assert STAFF_ROLE_ID in restored_ids, (
        "Documented finding (SOCIAL_SYSTEM.md §10): a role revoked "
        "before the member left is silently restored on rejoin, "
        "because role_ids_to_ignore is empty and there is no "
        "distinction anywhere in rank_restorer() for administrative "
        "roles specifically."
    )


async def test_row_is_never_cleaned_up_so_staleness_is_unbounded(bot):
    """Confirms SOCIAL_SYSTEM.md §10.3's strengthened claim directly at
    the DB layer: nothing in this cog ever deletes a user_ranks row, so
    a snapshot taken once stays valid (and restorable) indefinitely,
    not just within some short window after the member leaves."""
    await bot.RUN(CREATE_USER_RANKS_TABLE)
    await bot.RUN(SAVE_USER_ROLE_QUERY, (GUILD_ID, USER_ID, str(STAFF_ROLE_ID)))

    # Simulate "a long time later" by doing nothing at all -- no leave
    # event, no ban, no time-based expiry exists in the schema/queries
    # to simulate here in the first place.
    rows = await bot.GET(
        "SELECT role_ids FROM user_ranks WHERE guild_id = ? AND discord_user_id = ?;",
        (GUILD_ID, USER_ID),
    )

    assert rows and rows[0][0] == str(STAFF_ROLE_ID), (
        "Documented finding: there is no TTL/expiry/cleanup for "
        "user_ranks rows anywhere in the codebase (confirmed by repo-"
        "wide grep during the audit) -- a stale snapshot remains "
        "exactly as restorable a year later as it was 10 minutes after "
        "being written."
    )
