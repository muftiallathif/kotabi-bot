"""
Reproduction test for finding #6 (SOCIAL_SYSTEM.md §3):
/kneelderboard's optional `guild_id` parameter lets a caller query ANY
guild's kneel leaderboard (usernames + scores), with no check that they
belong to that guild. Real temp SQLite (this finding is fundamentally
a cross-guild DB query, not just a static permission check) + mocked
Discord boundary.

Not "authorization gap" in the classic sense (no restriction is
promised anywhere -- the describe text openly advertises cross-guild
lookup), so this is documented as a design gap. Whether it should be
blocked, staff-gated, or redacted is still an open design question
(SOCIAL_SYSTEM.md §14) -- this test only reproduces the CURRENT
behavior, it does not assert what the fix should look like.
"""
from unittest import mock

import discord
import pytest

from features.social.kneel_leaderboard_cog import Kneels, CREATE_KNEELS_TABLE, UPDATE_KNEEL_SCORE_QUERY

CALLER_GUILD_ID = 111
FOREIGN_GUILD_ID = 222
FOREIGN_USER_ID = 555


@pytest.fixture
async def seeded_foreign_kneels(bot):
    """Kneel data belonging entirely to a guild the caller is not a
    member of."""
    await bot.RUN(CREATE_KNEELS_TABLE)
    await bot.RUN(
        UPDATE_KNEEL_SCORE_QUERY,
        (FOREIGN_GUILD_ID, 12345, FOREIGN_USER_ID, 42, "ForeignUser"),
    )


async def test_caller_outside_target_guild_still_gets_the_leaderboard(
    bot, interaction_factory, seeded_foreign_kneels
):
    """
    Actor: member of CALLER_GUILD_ID only.
    Resource: FOREIGN_GUILD_ID's kneel leaderboard (usernames + scores).
    Action: /kneelderboard guild_id=<FOREIGN_GUILD_ID>.
    """
    cog = Kneels(bot)
    cog.update_user_name = mock.AsyncMock(side_effect=lambda uid, uname: uname)

    interaction = interaction_factory(user_id=1, is_admin=False, roles=(), guild_id=CALLER_GUILD_ID)
    interaction.guild = mock.MagicMock(spec=discord.Guild)
    interaction.guild.id = CALLER_GUILD_ID
    interaction.guild.emojis = []

    await Kneels.kneel_leaderboard.callback(cog, interaction, guild_id=str(FOREIGN_GUILD_ID))

    interaction.followup.send.assert_awaited_once()
    _, kwargs = interaction.followup.send.call_args
    embed = kwargs["embed"]
    field_names = [f.name for f in embed.fields]

    assert any("ForeignUser" in name for name in field_names), (
        "Documented finding (SOCIAL_SYSTEM.md §3): a caller who only "
        "belongs to CALLER_GUILD_ID successfully retrieved another "
        "guild's per-user kneel data -- no guild-membership check "
        "exists on the `guild_id` parameter."
    )
    assert kwargs.get("ephemeral") is not True, (
        "Documented finding: the cross-guild result is posted "
        "non-ephemerally, visible to the whole channel."
    )
