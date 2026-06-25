from core.bot import KotabiBot
import discord
import os
from discord.ext import commands

AUTHORIZED_USER_IDS = [int(uid) for uid in os.getenv("AUTHORIZED_USERS", "").split(",") if uid.strip()]

def is_authorized():
    async def predicate(ctx: commands.Context):
        return ctx.author.id in AUTHORIZED_USER_IDS
    return commands.check(predicate)

class Sync(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    @commands.command()
    @is_authorized()
    async def sync_guild(self, ctx: commands.Context):
        """Sinkronisasi perintah ke guild saat ini."""
        self.bot.tree.copy_global_to(guild=discord.Object(id=ctx.guild.id))
        self.bot.tree.clear_commands(guild=None)
        await self.bot.tree.sync(guild=discord.Object(id=ctx.guild.id))
        await ctx.send(f"Perintah berhasil disinkronisasi ke guild dengan ID {ctx.guild.id}.")

    @commands.command()
    @is_authorized()
    async def sync_global(self, ctx: commands.Context):
        """Sinkronisasi perintah secara global."""
        await self.bot.tree.sync()
        await ctx.send("Perintah berhasil disinkronisasi secara global.")

    @commands.command()
    @is_authorized()
    async def clear_global_commands(self, ctx):
        """Hapus semua perintah global."""
        self.bot.tree.clear_commands(guild=None)
        await self.bot.tree.sync()
        await ctx.send("Perintah global berhasil dihapus.")

    @commands.command()
    @is_authorized()
    async def clear_guild_commands(self, ctx):
        """Hapus semua perintah di guild saat ini."""
        self.bot.tree.clear_commands(guild=discord.Object(id=ctx.guild.id))
        await self.bot.tree.sync(guild=discord.Object(id=ctx.guild.id))
        await ctx.send(f"Perintah guild berhasil dihapus untuk ID {ctx.guild.id}.")

async def setup(bot):
    await bot.add_cog(Sync(bot))