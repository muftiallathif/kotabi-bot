"""Cog yang memungkinkan admin/moderator mengirim pesan atas nama bot."""
import discord
import logging
from discord.ext import commands
from typing import Optional
from core.bot import KotabiBot
from shared.checks import is_staff
from shared.messages import Msg

_log = logging.getLogger(__name__)


class Say(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    say_group = discord.app_commands.Group(
        name="say",
        description="Fasilitas administrasi untuk mengirim pesan resmi melalui bot.",
        default_permissions=discord.Permissions(administrator=True),
    )

    @say_group.command(name="message", description="Kirim pesan teks melalui bot.")
    @discord.app_commands.describe(
        message="Isi pesan yang ingin dikirim.",
        channel="Saluran tujuan (opsional, default: saluran saat ini).",
        reply_to="ID pesan yang ingin dibalas (opsional).",
    )
    @discord.app_commands.guild_only()
    @is_staff()
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
                return await interaction.followup.send("❌ ID pesan yang Anda berikan tidak sah.", ephemeral=True)
            try:
                ref_message = await target_channel.fetch_message(int(reply_to))
                reference = ref_message.to_reference()
            except discord.NotFound:
                return await interaction.followup.send("❌ Pesan yang ingin dibalas (reply) tidak ditemukan.", ephemeral=True)

        try:
            await target_channel.send(message, reference=reference)
            await interaction.followup.send(
                f"✅ Pesan berhasil dikirim ke {target_channel.mention}.", ephemeral=True
            )
            _log.info("%s mengirim pesan ke %s via /say message", interaction.user, target_channel)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak memiliki izin untuk mengirim pesan di saluran tersebut.", ephemeral=True)

    @say_group.command(name="embed", description="Kirim pesan visual (Embed) melalui bot.")
    @discord.app_commands.describe(
        title="Judul Embed (opsional).",
        description="Isi deskripsi Embed.",
        color="Warna Embed dalam format Hex (contoh: #c92a2a). Default: Biru.",
        channel="Saluran tujuan (opsional, default: saluran saat ini).",
        footer="Teks catatan kaki (footer) Embed (opsional).",
        image_url="URL gambar besar untuk ditampilkan di Embed (opsional).",
        thumbnail_url="URL gambar kecil di pojok kanan Embed (opsional).",
    )
    @discord.app_commands.guild_only()
    @is_staff()
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

        embed_color = discord.Color.blue()
        if color:
            try:
                color = color.strip().lstrip("#")
                embed_color = discord.Color(int(color, 16))
            except ValueError:
                return await interaction.followup.send(
                    "❌ Format kode warna tidak valid. Mohon gunakan format Hex seperti `#c92a2a`.", ephemeral=True
                )

        embed = discord.Embed(title=title, description=description, color=embed_color)

        if footer:
            embed.set_footer(text=footer)
        if image_url:
            embed.set_image(url=image_url)
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)

        try:
            await target_channel.send(embed=embed)
            await interaction.followup.send(
                f"✅ Pesan Embed berhasil dikirim ke {target_channel.mention}.", ephemeral=True
            )
            _log.info("%s mengirim Embed ke %s via /say embed", interaction.user, target_channel)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak memiliki izin untuk mengirim pesan di saluran tersebut.", ephemeral=True)

    @say_group.command(name="edit", description="Ubah isi pesan bot yang telah dikirim sebelumnya.")
    @discord.app_commands.describe(
        message_id="ID pesan bot yang ingin diubah.",
        new_content="Isi konten baru (untuk pesan teks biasa).",
        new_description="Deskripsi baru (untuk pesan Embed).",
        new_title="Judul baru (untuk pesan Embed).",
        channel="Saluran tempat pesan berada (opsional, default: saluran saat ini).",
    )
    @discord.app_commands.guild_only()
    @is_staff()
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
            return await interaction.followup.send("❌ ID pesan tidak sah.", ephemeral=True)

        try:
            target_message = await target_channel.fetch_message(int(message_id))
        except discord.NotFound:
            return await interaction.followup.send("❌ Pesan tersebut tidak ditemukan.", ephemeral=True)

        if target_message.author != self.bot.user:
            return await interaction.followup.send("❌ Maaf, hanya pesan yang dikirim oleh bot ini yang dapat diubah.", ephemeral=True)

        try:
            if target_message.embeds:
                old_embed = target_message.embeds[0]
                new_embed = old_embed.copy()
                if new_title is not None:
                    new_embed.title = new_title
                if new_description is not None:
                    new_embed.description = new_description
                await target_message.edit(embed=new_embed)
            elif new_content:
                await target_message.edit(content=new_content)
            else:
                return await interaction.followup.send(
                    "❌ Mohon berikan `new_content` untuk pesan teks, atau `new_description`/`new_title` untuk pesan Embed.",
                    ephemeral=True
                )

            await interaction.followup.send("✅ Pesan berhasil diperbarui.", ephemeral=True)
            _log.info("%s mengubah pesan %s di %s via /say edit", interaction.user, message_id, target_channel)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak memiliki izin untuk mengubah pesan tersebut.", ephemeral=True)

    @say_group.command(name="delete", description="Hapus pesan bot yang sudah dikirim sebelumnya.")
    @discord.app_commands.describe(
        message_id="ID pesan bot yang ingin dihapus.",
        channel="Saluran tempat pesan berada (opsional, default: saluran saat ini).",
    )
    @discord.app_commands.guild_only()
    @is_staff()
    async def say_delete(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: Optional[discord.TextChannel] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel

        if not message_id.isdigit():
            return await interaction.followup.send("❌ ID pesan tidak sah.", ephemeral=True)

        try:
            target_message = await target_channel.fetch_message(int(message_id))
        except discord.NotFound:
            return await interaction.followup.send("❌ Pesan tidak ditemukan.", ephemeral=True)

        if target_message.author != self.bot.user:
            return await interaction.followup.send("❌ Maaf, hanya pesan yang dikirim oleh bot ini yang dapat dihapus.", ephemeral=True)

        try:
            await target_message.delete()
            await interaction.followup.send("✅ Pesan berhasil dihapus.", ephemeral=True)
            _log.info("%s menghapus pesan %s di %s via /say delete", interaction.user, message_id, target_channel)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak memiliki izin untuk menghapus pesan tersebut.", ephemeral=True)


async def setup(bot: KotabiBot):
    await bot.add_cog(Say(bot))