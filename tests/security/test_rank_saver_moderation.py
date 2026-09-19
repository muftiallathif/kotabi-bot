"""
Level C reproduction test for finding #4 (MODERATION_SYSTEM.md §4):
rank_saver_cog.py's stale pre-mute snapshot can defeat an active
/selfmute when the muted member leaves and rejoins before rank_saver's
next 10-minute snapshot captures the muted state.

Deliberately a SEPARATE test file from test_rank_saver_authorization.py
even though the root cause is the same rank_saver_cog.py behavior — per
the locked classification, this is "moderation enforcement integrity"
(a sanction gets undone), not "authorization integrity" (privilege gets
restored). A fix for #3 does not automatically fix this.
"""
from unittest import mock

import discord
import pytest

import features.social.rank_saver_cog as rank_saver_module
from features.social.rank_saver_cog import RankSaver, CREATE_USER_RANKS_TABLE, SAVE_USER_ROLE_QUERY
from features.moderation.selfmute_cog import CREATE_ACTIVE_MUTES_TABLE, STORE_MUTE_QUERY, GET_USER_MUTE_QUERY

GUILD_ID = 999
USER_ID = 42
NORMAL_ROLE_ID = 200  # role(s) the member held BEFORE the mute
MUTE_ROLE_ID = 300


@pytest.fixture(autouse=True)
def isolated_ignore_list(monkeypatch):
    monkeypatch.setattr(rank_saver_module, "ranksaver_settings", {"role_ids_to_ignore": []})


@pytest.fixture(autouse=True)
def bypass_join_log_lookup(monkeypatch):
    monkeypatch.setattr(rank_saver_module, "get_channel_id", lambda gid, name: 0)


def _role(role_id):
    role = mock.MagicMock(spec=discord.Role)
    role.id = role_id
    role.is_assignable = mock.Mock(return_value=True)
    role.mention = f"@Role{role_id}"
    return role


async def test_stale_pre_mute_snapshot_omits_the_mute_role_on_rejoin(bot):
    """
    Actor: a user who ran /selfmute on themselves, then left and
    rejoined within the ~10-minute window before rank_saver's next
    snapshot tick captured their muted state (SOCIAL_SYSTEM.md §10.3 /
    MODERATION_SYSTEM.md §4).
    Resource: their own mute state.
    Action: rejoin (on_member_join -> rank_restorer).
    Expected (current, buggy): the restored role set comes from BEFORE
    the mute was applied, so it does not include the mute role — the
    member ends up unmuted in practice while an active_mutes row with
    a future end_time still exists untouched.
    """
    cog = RankSaver(bot)
    await bot.RUN(CREATE_USER_RANKS_TABLE)
    await bot.RUN(CREATE_ACTIVE_MUTES_TABLE)

    # rank_saver's last snapshot BEFORE /selfmute was ever called --
    # this is what makes it stale: it predates the mute entirely.
    await bot.RUN(SAVE_USER_ROLE_QUERY, (GUILD_ID, USER_ID, str(NORMAL_ROLE_ID)))

    # selfmute_cog's own record of the active mute, independent of
    # rank_saver -- this row is NEVER touched by leave/rejoin (no code
    # path deletes it), so it stays exactly as selfmute_cog.py left it.
    future_end_time = "2099-01-01 00:00:00"
    await bot.RUN(
        STORE_MUTE_QUERY,
        (GUILD_ID, USER_ID, MUTE_ROLE_ID, str(NORMAL_ROLE_ID), future_end_time),
    )

    normal_role = _role(NORMAL_ROLE_ID)
    mute_role = _role(MUTE_ROLE_ID)
    member = mock.MagicMock(spec=discord.Member)
    member.id = USER_ID
    member.name = "MutedUser"
    member.guild = mock.MagicMock(spec=discord.Guild)
    member.guild.id = GUILD_ID
    member.guild.name = "TestGuild"
    member.guild.roles = [normal_role, mute_role]
    member.guild.get_channel = mock.Mock(return_value=None)
    member.guild.system_channel = None
    member.add_roles = mock.AsyncMock()

    await RankSaver.rank_restorer(cog, member)

    member.add_roles.assert_awaited_once()
    restored_ids = {r.id for r in member.add_roles.await_args.args}

    assert NORMAL_ROLE_ID in restored_ids, "sanity check: the stale (pre-mute) role set is what gets restored"
    assert MUTE_ROLE_ID not in restored_ids, (
        "Documented finding (MODERATION_SYSTEM.md §4): rank_saver "
        "restores the PRE-MUTE role set, which never included the mute "
        "role in the first place -- the member is effectively unmuted "
        "by leaving and rejoining, no admin action required."
    )

    # The active_mutes row is untouched by any of this -- selfmute_cog
    # still believes the member is muted until end_time (2099) or until
    # /check_mute or clear_mutes() eventually processes it as a no-op.
    mute_row = await bot.GET(GET_USER_MUTE_QUERY, (GUILD_ID, USER_ID))
    assert mute_row and mute_row[0][4] == future_end_time, (
        "Documented finding: leave/rejoin never touches active_mutes -- "
        "the mute 'exists' in selfmute_cog.py's own bookkeeping the "
        "entire time, even though the member's real Discord roles no "
        "longer reflect it."
    )
