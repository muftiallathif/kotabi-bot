"""
Reproduction test for finding #7 (SERVER_ADMIN_SYSTEM.md §4.4):
/say's optional `channel` parameter lets a staff member direct the bot
to post/edit/delete in ANY channel, without ever checking whether that
staff member personally has permission to act in that specific channel
— only the bot's own permission matters (found reactively via
discord.Forbidden). This is permission laundering through the bot's
broader access.

Only /say message is covered here (the pattern — target_channel =
channel or interaction.channel, no permissions_for() check anywhere —
is identical across message/embed/edit/delete per the audit; one
command is enough to reproduce the class of bug, per the "don't
over-analyze, keep moving" pace for #3-7).

Level A only: @is_staff() itself is already confirmed correctly
enforced elsewhere (SERVER_ADMIN_SYSTEM.md §4.1) — this test assumes
the actor already passed that gate and focuses purely on what happens
inside the callback body once they have.
"""
from unittest import mock

import discord
import pytest

from features.server_admin.say_cog import Say


async def test_target_channel_permission_is_never_consulted():
    """
    Actor: staff member (passes @is_staff() — not re-tested here).
    Resource: a channel the actor does NOT personally have Send
    Messages permission in (only the bot does).
    Action: /say message channel=<that channel>.
    """
    target_channel = mock.MagicMock(spec=discord.TextChannel)
    target_channel.mention = "#restricted-channel"
    target_channel.send = mock.AsyncMock()
    # Explicitly wired to say "no" if the command ever asked — the
    # assertion below confirms it never does.
    target_channel.permissions_for = mock.Mock(
        return_value=discord.Permissions(send_messages=False)
    )

    staff_actor = mock.MagicMock(spec=discord.Member)

    interaction = mock.MagicMock(spec=discord.Interaction)
    interaction.user = staff_actor
    interaction.channel = mock.MagicMock(spec=discord.TextChannel)  # "current" channel, unused here
    interaction.response = mock.AsyncMock()
    interaction.followup = mock.AsyncMock()

    cog = Say(mock.MagicMock())

    await Say.say_message.callback(
        cog, interaction, message="pengumuman resmi", channel=target_channel, reply_to=None
    )

    target_channel.send.assert_awaited_once_with("pengumuman resmi", reference=None)
    target_channel.permissions_for.assert_not_called(), (
        "Documented finding: the command never calls "
        "target_channel.permissions_for(interaction.user) — the "
        "invoking staff member's own Discord permission in the target "
        "channel is never consulted, only the bot's own (reactively, "
        "via discord.Forbidden). A staff member can post into a "
        "channel they personally cannot access, laundered through the "
        "bot's broader permissions."
    )
