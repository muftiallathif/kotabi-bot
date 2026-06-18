"""Cog that allows admins/moderators to send messages as the bot."""
import discord
import logging
from discord.ext import commands
from typing import Optional
from lib.bot import KotabiBot

_log = logging.getLogger(__name__)


class Say(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    say_group = discord.app_commands.Group(
        name="say",
        description="Kirim pesan sebagai bot.",
        default_permissions=discord.Permissions(manage_messages=True)
    )

    @say_group.command(name="message", description="Kirim pesan teks biasa sebagai bot.")
    @discord.app_commands.describe(
        message="Pesan yang ingin dikirim.",
        channel="Channel tujuan (opsional, default: channel saat ini).",
        reply_to="ID pesan yang ingin di-reply (opsional).",
    )
    @discord.app_commands.guild_only()
    async def say_message(
        self,
        interaction: discord.Interaction,
        message: str,
        channel: Optional[discord.TextChannel] = None,
        reply_to: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel

        reference = None
        if reply_to:
            if not reply_to.isdigit():
                return await interaction.followup.send("ID pesan tidak valid.", ephemeral=True)
            try:
                ref_message = await target_channel.fetch_message(int(reply_to))
                reference = ref_message.to_reference()
            except discord.NotFound:
                return await interaction.followup.send("Pesan yang ingin di-reply tidak ditemukan.", ephemeral=True)

        try:
            await target_channel.send(message, reference=reference)
            await interaction.followup.send(
                f"✅ Pesan berhasil dikirim ke {target_channel.mention}.", ephemeral=True
            )
            _log.info(f"{interaction.user} sent a message to {target_channel} via /say message")
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak punya izin untuk mengirim pesan di channel itu.", ephemeral=True)

    @say_group.command(name="embed", description="Kirim pesan dalam bentuk embed sebagai bot.")
    @discord.app_commands.describe(
        title="Judul embed.",
        description="Isi/deskripsi embed.",
        color="Warna embed dalam hex (contoh: #c92a2a). Default: biru.",
        channel="Channel tujuan (opsional, default: channel saat ini).",
        footer="Teks footer embed (opsional).",
        image_url="URL gambar untuk ditampilkan di embed (opsional).",
        thumbnail_url="URL thumbnail kecil di pojok kanan embed (opsional).",
    )
    @discord.app_commands.guild_only()
    async def say_embed(
        self,
        interaction: discord.Interaction,
        description: str,
        title: Optional[str] = None,
        color: Optional[str] = None,
        channel: Optional[discord.TextChannel] = None,
        footer: Optional[str] = None,
        image_url: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel

        # Parse color
        embed_color = discord.Color.blue()
        if color:
            try:
                color = color.strip().lstrip("#")
                embed_color = discord.Color(int(color, 16))
            except ValueError:
                return await interaction.followup.send(
                    "❌ Format warna tidak valid. Gunakan hex seperti `#c92a2a`.", ephemeral=True
                )

        embed = discord.Embed(
            title=title,
            description=description,
            color=embed_color
        )

        if footer:
            embed.set_footer(text=footer)
        if image_url:
            embed.set_image(url=image_url)
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)

        try:
            await target_channel.send(embed=embed)
            await interaction.followup.send(
                f"✅ Embed berhasil dikirim ke {target_channel.mention}.", ephemeral=True
            )
            _log.info(f"{interaction.user} sent an embed to {target_channel} via /say embed")
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak punya izin untuk mengirim pesan di channel itu.", ephemeral=True)

    @say_group.command(name="edit", description="Edit pesan bot yang sudah dikirim sebelumnya.")
    @discord.app_commands.describe(
        message_id="ID pesan bot yang ingin diedit.",
        new_content="Konten baru untuk pesan tersebut (untuk pesan biasa).",
        new_description="Deskripsi baru (untuk embed).",
        new_title="Judul baru (untuk embed).",
        channel="Channel tempat pesan berada (opsional, default: channel saat ini).",
    )
    @discord.app_commands.guild_only()
    async def say_edit(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: Optional[discord.TextChannel] = None,
        new_content: Optional[str] = None,
        new_description: Optional[str] = None,
        new_title: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel

        if not message_id.isdigit():
            return await interaction.followup.send("❌ ID pesan tidak valid.", ephemeral=True)

        try:
            target_message = await target_channel.fetch_message(int(message_id))
        except discord.NotFound:
            return await interaction.followup.send("❌ Pesan tidak ditemukan.", ephemeral=True)

        if target_message.author != self.bot.user:
            return await interaction.followup.send("❌ Hanya bisa mengedit pesan yang dikirim oleh bot.", ephemeral=True)

        try:
            # Edit embed
            if target_message.embeds:
                old_embed = target_message.embeds[0]
                new_embed = old_embed.copy()
                if new_title is not None:
                    new_embed.title = new_title
                if new_description is not None:
                    new_embed.description = new_description
                await target_message.edit(embed=new_embed)
            # Edit plain text
            elif new_content:
                await target_message.edit(content=new_content)
            else:
                return await interaction.followup.send(
                    "❌ Berikan `new_content` untuk pesan biasa, atau `new_description`/`new_title` untuk embed.",
                    ephemeral=True
                )

            await interaction.followup.send("✅ Pesan berhasil diedit.", ephemeral=True)
            _log.info(f"{interaction.user} edited message {message_id} in {target_channel} via /say edit")
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak punya izin untuk mengedit pesan itu.", ephemeral=True)

    @say_group.command(name="delete", description="Hapus pesan bot yang sudah dikirim.")
    @discord.app_commands.describe(
        message_id="ID pesan bot yang ingin dihapus.",
        channel="Channel tempat pesan berada (opsional, default: channel saat ini).",
    )
    @discord.app_commands.guild_only()
    async def say_delete(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: Optional[discord.TextChannel] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel

        if not message_id.isdigit():
            return await interaction.followup.send("❌ ID pesan tidak valid.", ephemeral=True)

        try:
            target_message = await target_channel.fetch_message(int(message_id))
        except discord.NotFound:
            return await interaction.followup.send("❌ Pesan tidak ditemukan.", ephemeral=True)

        if target_message.author != self.bot.user:
            return await interaction.followup.send("❌ Hanya bisa menghapus pesan yang dikirim oleh bot.", ephemeral=True)

        try:
            await target_message.delete()
            await interaction.followup.send("✅ Pesan berhasil dihapus.", ephemeral=True)
            _log.info(f"{interaction.user} deleted message {message_id} in {target_channel} via /say delete")
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak punya izin untuk menghapus pesan itu.", ephemeral=True)


async def setup(bot: KotabiBot):
    await bot.add_cog(Say(bot))
