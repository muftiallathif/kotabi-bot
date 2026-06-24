import discord
import json
from discord.ext import commands
from core.bot import KotabiBot


class ExportServer(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    @discord.app_commands.command(name="export_server", description="Export semua data server ke JSON (Khusus Admin).")
    @discord.app_commands.default_permissions(administrator=True)
    @discord.app_commands.guild_only()
    async def export_server(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        data = {
            "guild_name": guild.name,
            "guild_id": guild.id,
            "roles": [],
            "categories": [],
        }

        # Export roles
        for role in guild.roles:
            if role.is_default():
                continue
            data["roles"].append({
                "id": role.id,
                "name": role.name,
                "color": str(role.color),
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "position": role.position,
                "permissions": role.permissions.value,
            })

        # Export categories & channels
        for category in guild.categories:
            cat_data = {
                "id": category.id,
                "name": category.name,
                "position": category.position,
                "permissions": [],
                "channels": [],
            }

            # Category permissions
            for target, overwrite in category.overwrites.items():
                allow, deny = overwrite.pair()
                cat_data["permissions"].append({
                    "id": target.id,
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value,
                })

            # Channels dalam category
            for channel in category.channels:
                ch_data = {
                    "id": channel.id,
                    "name": channel.name,
                    "type": str(channel.type),
                    "position": channel.position,
                    "topic": getattr(channel, "topic", None),
                    "permissions": [],
                }

                # Channel permissions
                for target, overwrite in channel.overwrites.items():
                    allow, deny = overwrite.pair()
                    ch_data["permissions"].append({
                        "id": target.id,
                        "type": "role" if isinstance(target, discord.Role) else "member",
                        "allow": allow.value,
                        "deny": deny.value,
                    })

                cat_data["channels"].append(ch_data)

            data["categories"].append(cat_data)

        # Channels tanpa category
        no_category = {
            "id": None,
            "name": "no_category",
            "position": -1,
            "permissions": [],
            "channels": [],
        }
        for channel in guild.channels:
            if channel.category is None and not isinstance(channel, discord.CategoryChannel):
                ch_data = {
                    "id": channel.id,
                    "name": channel.name,
                    "type": str(channel.type),
                    "position": channel.position,
                    "topic": getattr(channel, "topic", None),
                    "permissions": [],
                }
                for target, overwrite in channel.overwrites.items():
                    allow, deny = overwrite.pair()
                    ch_data["permissions"].append({
                        "id": target.id,
                        "type": "role" if isinstance(target, discord.Role) else "member",
                        "allow": allow.value,
                        "deny": deny.value,
                    })
                no_category["channels"].append(ch_data)

        if no_category["channels"]:
            data["categories"].append(no_category)

        # Simpan ke file JSON
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        json_bytes = json_str.encode("utf-8")

        import io
        file = discord.File(io.BytesIO(json_bytes), filename=f"server_backup_{guild.id}.json")
        await interaction.followup.send(
            "✅ Export berhasil! Simpan file ini untuk restore nanti.",
            file=file,
            ephemeral=True
        )


async def setup(bot: KotabiBot):
    await bot.add_cog(ExportServer(bot))