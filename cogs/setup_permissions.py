import discord
from discord.ext import commands
from core.bot import KotabiBot

# ID Roles
ROLE_IDS = {
    "trial":     1518029306469548202,
    "traveler":  1517031166279159848,
    "companion": 1517676769954762804,
    "scholar":   1518084701431140524,
    "patron":    1517718386002628608,
    "royal_guard":     1517801101959631009,
    "prime_minister":  1517801149191819427,
}

# ID Channels existing
CHANNEL_IDS = {
    "member_lounge":  1517830303840997441,
    "deck_requests":  1517830332315996190,
    "immersion_race": 1517830350313750618,
    "grammar_dic":    1517829911031582750,
    "kotoba_dic":     1517829941268447302,
    "kanji_dic":      1517830003226574958,
    "immersion_log":  1516671526345113671,
    "quiz_rank_up":   1517023518984896564,
}

# Permission structure
# channel: [roles yang boleh akses]
CHANNEL_PERMISSIONS = {
    "member_lounge":  ["trial", "traveler", "companion", "scholar", "patron", "royal_guard", "prime_minister"],
    "immersion_log":  ["trial", "traveler", "companion", "scholar", "patron", "royal_guard", "prime_minister"],
    "quiz_rank_up":   ["trial", "traveler", "companion", "scholar", "patron", "royal_guard", "prime_minister"],
    "grammar_dic":    ["trial", "companion", "scholar", "patron", "royal_guard", "prime_minister"],
    "kotoba_dic":     ["trial", "companion", "scholar", "patron", "royal_guard", "prime_minister"],
    "kanji_dic":      ["trial", "companion", "scholar", "patron", "royal_guard", "prime_minister"],
    "anime_sentences":["trial", "companion", "scholar", "patron", "royal_guard", "prime_minister"],
    "deck_requests":  ["trial", "companion", "scholar", "patron", "royal_guard", "prime_minister"],
    "immersion_race": ["trial", "companion", "scholar", "patron", "royal_guard", "prime_minister"],
}


class SetupPermissions(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    @discord.app_commands.command(name="setup_permissions", description="Setup permission semua channel VIP (Khusus Admin).")
    @discord.app_commands.default_permissions(administrator=True)
    @discord.app_commands.guild_only()
    async def setup_permissions(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        everyone = guild.default_role
        results = []

        # Ambil roles
        roles = {}
        for key, role_id in ROLE_IDS.items():
            role = guild.get_role(role_id)
            if role:
                roles[key] = role
            else:
                results.append(f"❌ Role `{key}` tidak ditemukan!")

        # Cari category Member Area untuk anime_sentences
        member_area_category = None
        for category in guild.categories:
            if any(ch.id == 1517830303840997441 for ch in category.channels):
                member_area_category = category
                break

        # Buat channel anime_sentences jika belum ada
        anime_sentences_channel = discord.utils.get(guild.text_channels, name="anime-sentences")
        if not anime_sentences_channel:
            try:
                anime_sentences_channel = await guild.create_text_channel(
                    name="anime-sentences",
                    category=member_area_category,
                    reason="Auto-created by setup_permissions"
                )
                results.append(f"✅ Channel `anime-sentences` berhasil dibuat!")
            except Exception as e:
                results.append(f"❌ Gagal membuat channel `anime-sentences`: {e}")
                anime_sentences_channel = None

        # Gabungkan channel existing + anime_sentences
        channels = {}
        for name, channel_id in CHANNEL_IDS.items():
            ch = guild.get_channel(channel_id)
            if ch:
                channels[name] = ch
            else:
                results.append(f"❌ Channel `{name}` tidak ditemukan!")

        if anime_sentences_channel:
            channels["anime_sentences"] = anime_sentences_channel

        # Set permissions
        for ch_name, allowed_roles in CHANNEL_PERMISSIONS.items():
            channel = channels.get(ch_name)
            if not channel:
                continue

            try:
                # Deny everyone
                await channel.set_permissions(everyone, view_channel=False, send_messages=False)

                # Allow roles sesuai list
                for role_key in allowed_roles:
                    role = roles.get(role_key)
                    if role:
                        await channel.set_permissions(role, view_channel=True, send_messages=True)

                results.append(f"✅ `{ch_name}` permission berhasil diset!")
            except Exception as e:
                results.append(f"❌ `{ch_name}` gagal: {e}")

        # Update server_map.yml dengan ID anime_sentences
        if anime_sentences_channel:
            results.append(f"\n📝 Tambahkan ke server_map.yml:\n`anime_sentences: {anime_sentences_channel.id}`")

        summary = "\n".join(results)
        await interaction.followup.send(f"**Hasil Setup Permission:**\n{summary}", ephemeral=True)


async def setup(bot: KotabiBot):
    await bot.add_cog(SetupPermissions(bot))