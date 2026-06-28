import discord

from lib.media_types import immersion_log_settings


async def is_valid_channel(interaction: discord.Interaction) -> bool:
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True
    if interaction.channel.id in immersion_log_settings.get('immersion_bot', {}).get('allowed_log_channels', []):
        return True
    if not interaction.user.dm_channel:
        await interaction.client.create_dm(interaction.user)
    if interaction.channel == interaction.user.dm_channel:
        return True
    return False


async def get_achievement_reached_info(achievement_group: str, points_before: int, points_after: int):
    achievement_group_settings = immersion_log_settings.get('achievements', {}).get(achievement_group, [])
    current_achievement = None
    next_achievement = None
    achievement_reached = False

    for achievement in achievement_group_settings:
        if achievement['points'] <= points_before:
            current_achievement = achievement
        if points_before < achievement['points'] <= points_after:
            achievement_reached = True
            current_achievement = achievement
        elif points_after < achievement['points']:
            next_achievement = achievement
            break

    return achievement_reached, current_achievement, next_achievement


async def get_current_and_next_achievement(achievement_group: str, points: int):
    achievement_group_settings = immersion_log_settings.get('achievements', {}).get(achievement_group, [])
    current_achievement = None
    next_achievement = None

    for achievement in achievement_group_settings:
        if achievement['points'] <= points:
            current_achievement = achievement
        if points < achievement['points']:
            next_achievement = achievement
            break

    return current_achievement, next_achievement