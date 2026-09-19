"""
Level A/B reproduction tests for finding #5 (MODERATION_SYSTEM.md §2):
/solved has no ownership/staff check at all, and its "solved" state is
just a `[TERSELESAIKAN]` name prefix on the live Discord thread, with
no DB-backed authority binding it to the /solved action specifically.

No DB table exists for this cog (MODERATION_SYSTEM.md §7 / §11) so
there's no Level C here -- a plain mock bot is enough, the `bot`
fixture (real SQLite) isn't needed.
"""
from unittest import mock

import discord
import pytest

import features.moderation.thread_resolver_cog as resolver_module
from features.moderation.thread_resolver_cog import Resolver

GUILD_ID = 999
FORUM_ID = 500


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.setattr(resolver_module, "thread_resolver_settings", {GUILD_ID: [FORUM_ID]})


def _forum():
    forum = mock.MagicMock(spec=discord.ForumChannel)
    forum.id = FORUM_ID
    return forum


def _cog(forum):
    fake_guild = mock.MagicMock(spec=discord.Guild)
    fake_guild.forums = [forum]
    fake_bot = mock.MagicMock()
    fake_bot.get_guild = mock.Mock(return_value=fake_guild)
    return Resolver(fake_bot)


class TestSolvedAuthorization:
    async def test_level_b_has_no_registered_checks(self):
        assert Resolver.solved.checks == [], (
            "Documented finding: /solved has no decorator-based check "
            "at all — not even a role gate, let alone thread ownership."
        )

    async def test_level_a_non_owner_non_staff_can_close_another_users_thread(self):
        """
        Actor: an ordinary member who did NOT open the thread and holds
        no staff role (the code never checks either property).
        Resource: a help thread started by a different user.
        Action: /solved.
        """
        forum = _forum()
        cog = _cog(forum)

        thread = mock.MagicMock(spec=discord.Thread)
        thread.name = "Kenapa て-form begini?"
        thread.parent = forum
        thread.archived = False
        thread.edit = mock.AsyncMock()

        actor = mock.MagicMock(spec=discord.Member)
        actor.mention = "@RandomMember"

        interaction = mock.MagicMock(spec=discord.Interaction)
        interaction.guild_id = GUILD_ID
        interaction.channel = thread
        interaction.user = actor
        interaction.response = mock.AsyncMock()

        await Resolver.solved.callback(cog, interaction)

        thread.edit.assert_awaited_once()
        _, kwargs = thread.edit.call_args
        assert kwargs.get("archived") is True
        assert "[TERSELESAIKAN]" in kwargs.get("name", ""), (
            "Documented finding: any member who can see the help forum "
            "can close/archive someone else's thread — there is no "
            "check that `interaction.user` is the thread starter or a "
            "staff member."
        )


class TestSolvedStateIntegrity:
    async def test_thread_can_be_marked_solved_by_rename_alone_bypassing_the_command(self):
        """
        Documented finding: because "solved" is read purely from the
        thread's own name string (no DB flag), the hourly background
        sweep (ask_if_solved_for_guild) will archive a thread the
        moment its name contains the marker -- even if /solved was
        never invoked. A thread's creator can rename their own thread
        without needing Manage Threads (Discord's own permission
        model), so this is a real bypass path, not just a theoretical
        one.
        """
        forum = _forum()
        cog = _cog(forum)

        thread = mock.MagicMock(spec=discord.Thread)
        thread.name = "[TERSELESAIKAN] Pertanyaan lama"  # renamed by hand, /solved never called
        thread.archived = False
        thread.edit = mock.AsyncMock()
        forum.threads = [thread]

        await cog.ask_if_solved_for_guild(mock.MagicMock(id=GUILD_ID))

        thread.edit.assert_awaited_once()
        _, kwargs = thread.edit.call_args
        assert kwargs.get("archived") is True, (
            "Documented finding: a thread gets archived purely because "
            "its NAME contains the marker string — the background sweep "
            "never checks who put it there or whether /solved ran."
        )
