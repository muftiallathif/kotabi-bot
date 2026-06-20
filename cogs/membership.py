"""
Membership System Cog
- Dual-tier: reguler (Rp100k) dan intensive (Rp300k)
- Lifetime system: 12x pembayaran kumulatif (reguler + intensive keduanya dihitung)
- Intensive tidak punya lifetime — per-bulan on-demand
- Auto-expiry dengan 3-hari warning, lifetime member tidak di-revoke
- Dual role saat lifetime: メンバー + ライフタイムメンバー
- History tracking semua grant/revoke
- DM notifications
"""
import discord
import asyncio
import os
import yaml
import logging
from datetime import datetime, timedelta, timezone
from discord.ext import commands, tasks
from discord.utils import utcnow
from lib.bot import KotabiBot

_log = logging.getLogger(__name__)

MEMBERSHIP_SETTINGS_PATH = os.getenv("ALT_MEMBERSHIP_SETTINGS_PATH") or "config/membership_settings.yml"
with open(MEMBERSHIP_SETTINGS_PATH, "r", encoding="utf-8") as f:
    membership_settings = yaml.safe_load(f)

# ============================================================================
# DATABASE QUERIES
# ============================================================================

CREATE_MEMBERSHIPS_TABLE = """
CREATE TABLE IF NOT EXISTS memberships (
    guild_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    tier            TEXT NOT NULL,
    granted_at      TIMESTAMP NOT NULL,
    expires_at      TIMESTAMP NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    granted_by      INTEGER,
    payment_count   INTEGER NOT NULL DEFAULT 0,
    is_lifetime     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
"""

# Migrasi aman kalau tabel lama belum punya kolom baru
ADD_PAYMENT_COUNT_COLUMN = """
ALTER TABLE memberships ADD COLUMN payment_count INTEGER NOT NULL DEFAULT 0;
"""

ADD_IS_LIFETIME_COLUMN = """
ALTER TABLE memberships ADD COLUMN is_lifetime INTEGER NOT NULL DEFAULT 0;
"""

CREATE_MEMBERSHIP_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS membership_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    action      TEXT NOT NULL,
    tier        TEXT,
    granted_by  INTEGER,
    timestamp   TIMESTAMP NOT NULL,
    reason      TEXT
);
"""

# Upsert — kalau user sudah ada, update tier/expiry/granter tapi INCREMENT payment_count
INSERT_MEMBERSHIP = """
INSERT INTO memberships (guild_id, user_id, tier, granted_at, expires_at, active, granted_by, payment_count, is_lifetime)
VALUES (?, ?, ?, ?, ?, 1, ?, 1, 0)
ON CONFLICT (guild_id, user_id) DO UPDATE SET
    tier          = excluded.tier,
    granted_at    = excluded.granted_at,
    expires_at    = CASE
                        WHEN is_lifetime = 1 THEN expires_at  -- lifetime: jangan ubah expiry
                        ELSE excluded.expires_at
                    END,
    active        = 1,
    granted_by    = excluded.granted_by,
    payment_count = payment_count + 1;
"""

GET_MEMBERSHIP = """
SELECT user_id, tier, granted_at, expires_at, active, granted_by, payment_count, is_lifetime
FROM memberships
WHERE guild_id = ? AND user_id = ?;
"""

SET_LIFETIME = """
UPDATE memberships
SET is_lifetime = 1,
    expires_at  = '9999-12-31 23:59:59',
    active      = 1
WHERE guild_id = ? AND user_id = ?;
"""

REVOKE_MEMBERSHIP = """
UPDATE memberships
SET active = 0
WHERE guild_id = ? AND user_id = ? AND is_lifetime = 0;
"""

INSERT_HISTORY = """
INSERT INTO membership_history (guild_id, user_id, action, tier, granted_by, timestamp, reason)
VALUES (?, ?, ?, ?, ?, ?, ?);
"""

GET_HISTORY = """
SELECT user_id, action, tier, granted_by, timestamp, reason
FROM membership_history
WHERE guild_id = ? AND (? IS NULL OR user_id = ?)
ORDER BY timestamp DESC
LIMIT 50;
"""

PURGE_HISTORY = """
DELETE FROM membership_history
WHERE guild_id = ? AND user_id = ?;
"""

GET_EXPIRING_MEMBERSHIPS = """
SELECT user_id, tier, expires_at
FROM memberships
WHERE guild_id = ? AND active = 1 AND is_lifetime = 0
  AND expires_at <= ? AND expires_at > ?;
"""

GET_EXPIRED_MEMBERSHIPS = """
SELECT user_id, tier, expires_at
FROM memberships
WHERE guild_id = ? AND active = 1 AND is_lifetime = 0 AND expires_at <= ?;
"""

GET_WARNING_SENT = """
SELECT user_id FROM membership_history
WHERE guild_id = ? AND user_id = ? AND action = 'warned_expiry' AND timestamp > ?;
"""

MEMBERSHIP_LOCK = asyncio.Lock()

LIFETIME_THRESHOLD = membership_settings['membership']['roles']['lifetime']['payment_threshold']


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def send_dm_safe(user_id: int, bot: KotabiBot, embed: discord.Embed) -> bool:
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if not user.dm_channel:
            await user.create_dm()
        await user.send(embed=embed)
        return True
    except (discord.Forbidden, discord.NotFound):
        _log.warning(f"Could not DM user {user_id}")
        return False


def get_tier_info(tier: str) -> dict:
    return membership_settings['membership']['roles'].get(tier, {})


def get_announcement_channel(guild: discord.Guild) -> discord.TextChannel:
    channel_id = membership_settings['membership']['announcement_channel_id']
    return guild.get_channel(channel_id)


def get_lifetime_role(guild: discord.Guild) -> discord.Role:
    lifetime_role_id = membership_settings['membership']['roles']['lifetime']['role_id']
    return guild.get_role(lifetime_role_id)


async def _try_add_column(bot: KotabiBot, sql: str):
    """Jalankan ALTER TABLE, abaikan error kalau kolom sudah ada."""
    try:
        await bot.RUN(sql)
    except Exception:
        pass  # kolom sudah ada


async def _do_grant(
    bot: KotabiBot,
    guild: discord.Guild,
    user: discord.User,
    tier: str,
    granted_by_id: int,
) -> dict:
    """
    Core grant logic — dipanggil dari grant_member dan grant_batch.
    Return dict: { success, payment_count, is_lifetime, expires_at, tier_info }
    """
    tier_info = get_tier_info(tier)
    now       = utcnow()
    expires_at = now + timedelta(days=tier_info['duration_days'])

    # Upsert ke DB (payment_count di-increment di SQL)
    await bot.RUN(
        INSERT_MEMBERSHIP,
        (
            guild.id,
            user.id,
            tier,
            now.isoformat(),
            expires_at.isoformat(),
            granted_by_id,
        )
    )

    # Ambil payment_count terbaru
    row = await bot.GET_ONE(GET_MEMBERSHIP, (guild.id, user.id))
    _, _, _, _, _, _, payment_count, is_lifetime = row

    # Assign role tier (reguler atau intensive)
    target_member = guild.get_member(user.id)
    if target_member:
        role = guild.get_role(tier_info['role_id'])
        if role and role not in target_member.roles:
            await target_member.add_roles(role)

        # Pastikan reguler role juga ada kalau intensive (intensive include member)
        if tier == 'intensive':
            reguler_role = guild.get_role(get_tier_info('reguler')['role_id'])
            if reguler_role and reguler_role not in target_member.roles:
                await target_member.add_roles(reguler_role)

    # Cek apakah sudah layak lifetime
    if not is_lifetime and payment_count >= LIFETIME_THRESHOLD:
        await bot.RUN(SET_LIFETIME, (guild.id, user.id))
        is_lifetime = True

        # Kasih lifetime role
        if target_member:
            lifetime_role = get_lifetime_role(guild)
            if lifetime_role and lifetime_role not in target_member.roles:
                await target_member.add_roles(lifetime_role)

        await bot.RUN(
            INSERT_HISTORY,
            (guild.id, user.id, 'lifetime_unlocked', tier, granted_by_id, now.isoformat(), 'Reached 12 payments')
        )
        _log.info(f"User {user.id} unlocked lifetime membership ({payment_count} payments)")

    # Log grant ke history
    await bot.RUN(
        INSERT_HISTORY,
        (guild.id, user.id, 'grant', tier, granted_by_id, now.isoformat(), None)
    )

    return {
        'success'       : True,
        'payment_count' : payment_count,
        'is_lifetime'   : bool(is_lifetime),
        'expires_at'    : expires_at,
        'tier_info'     : tier_info,
    }


# ============================================================================
# MEMBERSHIP COG
# ============================================================================

class Membership(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot     = bot
        self.guild_id = membership_settings['membership']['guild_id']

    async def cog_load(self):
        await self.bot.RUN(CREATE_MEMBERSHIPS_TABLE)
        await self.bot.RUN(CREATE_MEMBERSHIP_HISTORY_TABLE)
        # Migrasi aman untuk kolom baru
        await _try_add_column(self.bot, ADD_PAYMENT_COUNT_COLUMN)
        await _try_add_column(self.bot, ADD_IS_LIFETIME_COLUMN)

        if not self.membership_expiry_check.is_running():
            self.membership_expiry_check.start()
            _log.info("Started membership expiry check task")

    def cog_unload(self):
        if self.membership_expiry_check.is_running():
            self.membership_expiry_check.cancel()

    # ========================================================================
    # PERMISSION CHECK
    # ========================================================================

    async def _check_can_manage(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        mod_ids = membership_settings['membership']['moderator_role_ids']
        return bool(mod_ids and any(r.id in mod_ids for r in member.roles))

    # ========================================================================
    # COMMANDS
    # ========================================================================

    admin_group = discord.app_commands.Group(name="admin", description="Admin commands")

    @admin_group.command(name="grant-member", description="Grant membership ke satu user.")
    @discord.app_commands.describe(user="User yang mau dikasih membership.", tier="Tier membership.")
    @discord.app_commands.choices(tier=[
        discord.app_commands.Choice(name="Member Reguler (Rp100k) - 30 hari", value="reguler"),
        discord.app_commands.Choice(name="Intensive Student (Rp300k) - 30 hari", value="intensive"),
    ])
    @discord.app_commands.guild_only()
    async def grant_member(self, interaction: discord.Interaction, user: discord.User, tier: str):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not await self._check_can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        if not get_tier_info(tier):
            return await interaction.followup.send(f"❌ Tier `{tier}` tidak valid.", ephemeral=True)

        async with MEMBERSHIP_LOCK:
            try:
                result = await _do_grant(self.bot, interaction.guild, user, tier, interaction.user.id)
            except Exception as e:
                _log.error(f"grant_member error: {e}")
                return await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

        tier_info     = result['tier_info']
        is_lifetime   = result['is_lifetime']
        payment_count = result['payment_count']
        expires_at    = result['expires_at']
        expire_ts     = int(expires_at.timestamp())

        # DM ke user
        if is_lifetime:
            dm_embed = discord.Embed(
                title="✅ Membership Granted — LIFETIME 👑",
                description=(
                    f"Selamat! Kamu telah mencapai **12 pembayaran kumulatif** dan sekarang "
                    f"menjadi **ライフタイムメンバー / Lifetime Member** secara permanen.\n\n"
                    f"Kamu tidak perlu membayar membership lagi. Terima kasih atas dukunganmu! 🎉"
                ),
                color=discord.Color.gold()
            )
            dm_embed.add_field(name="Tier saat ini", value=tier_info['name'], inline=True)
            dm_embed.add_field(name="Payment count", value=f"{payment_count}/12 ✅", inline=True)
        else:
            dm_embed = discord.Embed(
                title="✅ Membership Granted",
                description=f"Selamat! Kamu sekarang memiliki membership **{tier_info['name']}**.",
                color=discord.Color.green()
            )
            dm_embed.add_field(name="Tier", value=tier_info['name'], inline=True)
            dm_embed.add_field(name="Expires", value=f"<t:{expire_ts}:F>", inline=True)
            dm_embed.add_field(
                name="Progress Lifetime",
                value=f"{payment_count}/{LIFETIME_THRESHOLD} pembayaran ({LIFETIME_THRESHOLD - payment_count} lagi)",
                inline=False
            )
        await send_dm_safe(user.id, self.bot, dm_embed)

        # Announce
        ch = get_announcement_channel(interaction.guild)
        if ch:
            ann = discord.Embed(
                title="🎉 Member Baru" + (" 👑 LIFETIME" if is_lifetime else ""),
                description=f"{user.mention} telah mendapatkan membership **{tier_info['name']}**",
                color=discord.Color.gold()
            )
            ann.set_thumbnail(url=user.display_avatar.url)
            if is_lifetime:
                ann.add_field(name="Status", value="ライフタイムメンバー / Lifetime Member ✅", inline=False)
            try:
                await ch.send(embed=ann)
            except discord.Forbidden:
                pass

        # Reply ke admin
        reply = (
            f"✅ Membership granted → {user.mention} ({tier_info['name']})\n"
            f"Payment count: **{payment_count}/{LIFETIME_THRESHOLD}**\n"
        )
        if is_lifetime:
            reply += "🎉 User sekarang **LIFETIME MEMBER**!"
        else:
            reply += f"Expires: <t:{expire_ts}:R>"
        await interaction.followup.send(reply, ephemeral=True)

    @admin_group.command(name="grant-batch", description="Grant membership ke banyak user sekaligus.")
    @discord.app_commands.describe(users="Mention user (@User1 @User2 ...)", tier="Tier membership.")
    @discord.app_commands.choices(tier=[
        discord.app_commands.Choice(name="Member Reguler (Rp100k) - 30 hari", value="reguler"),
        discord.app_commands.Choice(name="Intensive Student (Rp300k) - 30 hari", value="intensive"),
    ])
    @discord.app_commands.guild_only()
    async def grant_batch(self, interaction: discord.Interaction, users: str, tier: str):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not await self._check_can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        if not get_tier_info(tier):
            return await interaction.followup.send(f"❌ Tier `{tier}` tidak valid.", ephemeral=True)

        import re
        ids = re.findall(r'<@(\d+)>', users)
        if not ids:
            return await interaction.followup.send("❌ Tidak ada mention valid. Gunakan @User.", ephemeral=True)

        success_list = []
        fail_list    = []

        async with MEMBERSHIP_LOCK:
            for uid_str in ids:
                uid = int(uid_str)
                try:
                    target = interaction.guild.get_member(uid)
                    if not target:
                        target = await interaction.guild.fetch_member(uid)
                    user_obj = target._user if hasattr(target, '_user') else target

                    result = await _do_grant(self.bot, interaction.guild, user_obj, tier, interaction.user.id)

                    tier_info     = result['tier_info']
                    is_lifetime   = result['is_lifetime']
                    payment_count = result['payment_count']
                    expires_at    = result['expires_at']
                    expire_ts     = int(expires_at.timestamp())

                    # DM
                    if is_lifetime:
                        dm_embed = discord.Embed(
                            title="✅ Membership Granted — LIFETIME 👑",
                            description=(
                                "Kamu telah mencapai 12 pembayaran kumulatif dan sekarang menjadi "
                                "**ライフタイムメンバー / Lifetime Member** secara permanen! 🎉"
                            ),
                            color=discord.Color.gold()
                        )
                        dm_embed.add_field(name="Payment count", value=f"{payment_count}/12 ✅", inline=True)
                    else:
                        dm_embed = discord.Embed(
                            title="✅ Membership Granted",
                            description=f"Selamat! Kamu sekarang memiliki membership **{tier_info['name']}**.",
                            color=discord.Color.green()
                        )
                        dm_embed.add_field(name="Expires", value=f"<t:{expire_ts}:F>", inline=True)
                        dm_embed.add_field(
                            name="Progress Lifetime",
                            value=f"{payment_count}/{LIFETIME_THRESHOLD} ({LIFETIME_THRESHOLD - payment_count} lagi)",
                            inline=False
                        )
                    await send_dm_safe(uid, self.bot, dm_embed)

                    label = f"{target.name}" + (" 👑 LIFETIME" if is_lifetime else f" <t:{expire_ts}:R>")
                    success_list.append(label)

                except discord.NotFound:
                    fail_list.append(f"<@{uid}> — member not found")
                except Exception as e:
                    fail_list.append(f"<@{uid}> — {e}")
                    _log.error(f"Batch grant error uid {uid}: {e}")

        tier_info = get_tier_info(tier)

        # Announce batch
        if success_list:
            ch = get_announcement_channel(interaction.guild)
            if ch:
                ann = discord.Embed(
                    title=f"🎉 {len(success_list)} Member Baru",
                    color=discord.Color.gold()
                )
                ann.add_field(name="Tier", value=tier_info['name'], inline=True)
                ann.add_field(name="Daftar", value="\n".join(f"• {n}" for n in success_list)[:1024], inline=False)
                try:
                    await ch.send(embed=ann)
                except discord.Forbidden:
                    pass

        # Summary
        summary = discord.Embed(title="✅ Batch Grant Complete", color=discord.Color.green())
        if success_list:
            summary.add_field(
                name=f"Berhasil ({len(success_list)})",
                value="\n".join(f"✅ {n}" for n in success_list)[:1024],
                inline=False
            )
        if fail_list:
            summary.add_field(
                name=f"Gagal ({len(fail_list)})",
                value="\n".join(f"❌ {n}" for n in fail_list)[:1024],
                inline=False
            )
        summary.add_field(name="Tier", value=tier_info['name'], inline=True)
        summary.add_field(name="Total", value=f"{len(success_list)}/{len(ids)}", inline=True)
        await interaction.followup.send(embed=summary, ephemeral=True)

    @admin_group.command(name="revoke-member", description="Cabut membership dari user (tidak berlaku untuk lifetime).")
    @discord.app_commands.describe(user="User yang mau di-revoke.")
    @discord.app_commands.guild_only()
    async def revoke_member(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not await self._check_can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        async with MEMBERSHIP_LOCK:
            row = await self.bot.GET_ONE(GET_MEMBERSHIP, (interaction.guild_id, user.id))
            if not row:
                return await interaction.followup.send(f"❌ {user.mention} tidak punya membership.", ephemeral=True)

            _, tier, _, _, active, _, payment_count, is_lifetime = row

            if is_lifetime:
                return await interaction.followup.send(
                    f"❌ {user.mention} adalah **Lifetime Member** — tidak bisa di-revoke.\n"
                    f"Hubungi developer kalau ini darurat.",
                    ephemeral=True
                )
            if not active:
                return await interaction.followup.send(f"❌ Membership {user.mention} sudah inactive.", ephemeral=True)

            await self.bot.RUN(REVOKE_MEMBERSHIP, (interaction.guild_id, user.id))

            target_member = interaction.guild.get_member(user.id)
            if target_member:
                tier_info = get_tier_info(tier)
                role = interaction.guild.get_role(tier_info['role_id'])
                if role and role in target_member.roles:
                    await target_member.remove_roles(role)
                # Kalau revoke intensive, cabut juga reguler role (karena intensive include reguler)
                if tier == 'intensive':
                    reguler_role = interaction.guild.get_role(get_tier_info('reguler')['role_id'])
                    if reguler_role and reguler_role in target_member.roles:
                        await target_member.remove_roles(reguler_role)

            now = utcnow()
            await self.bot.RUN(
                INSERT_HISTORY,
                (interaction.guild_id, user.id, 'revoke', tier, interaction.user.id, now.isoformat(), "Manual revoke")
            )

            embed = discord.Embed(
                title="⚠️ Membership Revoked",
                description="Membership kamu telah dihapus dan role dicabut.",
                color=discord.Color.red()
            )
            embed.add_field(
                name="Info",
                value=f"Progress lifetime kamu (**{payment_count}/{LIFETIME_THRESHOLD}**) tetap tersimpan.",
                inline=False
            )
            await send_dm_safe(user.id, self.bot, embed)

        await interaction.followup.send(f"✅ Membership revoked → {user.mention}", ephemeral=True)

    @admin_group.command(name="check-member", description="Cek status membership user.")
    @discord.app_commands.describe(user="User yang mau dicek.")
    @discord.app_commands.guild_only()
    async def check_member(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)

        row = await self.bot.GET_ONE(GET_MEMBERSHIP, (interaction.guild_id, user.id))
        if not row:
            return await interaction.followup.send(f"❌ {user.mention} tidak punya membership.", ephemeral=True)

        _, tier, granted_at, expires_at, active, granted_by, payment_count, is_lifetime = row

        granted_ts = int(datetime.fromisoformat(granted_at).timestamp())
        expires_ts = int(datetime.fromisoformat(expires_at).timestamp())
        tier_info  = get_tier_info(tier)

        if is_lifetime:
            status_str = "👑 LIFETIME MEMBER"
            color      = discord.Color.gold()
        elif active:
            status_str = "✅ Active"
            color      = discord.Color.green()
        else:
            status_str = "❌ Inactive"
            color      = discord.Color.red()

        embed = discord.Embed(title=f"Membership Status — {user.name}", color=color)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Status",   value=status_str,                    inline=False)
        embed.add_field(name="Tier",     value=tier_info.get('name', tier),   inline=True)
        embed.add_field(name="Granted",  value=f"<t:{granted_ts}:F>",         inline=True)

        if is_lifetime:
            embed.add_field(name="Expires",          value="Tidak pernah ♾️",          inline=True)
            embed.add_field(name="Payment Count",    value=f"{payment_count}/{LIFETIME_THRESHOLD} ✅", inline=True)
            embed.add_field(name="Lifetime Role",    value="ライフタイムメンバー / Lifetime Member 👑", inline=False)
        else:
            embed.add_field(name="Expires",       value=f"<t:{expires_ts}:F>",          inline=True)
            embed.add_field(name="Time Remaining",value=f"<t:{expires_ts}:R>",          inline=True)
            remaining = LIFETIME_THRESHOLD - payment_count
            embed.add_field(
                name="Progress Lifetime",
                value=f"{payment_count}/{LIFETIME_THRESHOLD} ({remaining} pembayaran lagi)",
                inline=False
            )

        if granted_by:
            granter = self.bot.get_user(granted_by)
            embed.add_field(
                name="Granted By",
                value=granter.mention if granter else f"User {granted_by}",
                inline=True
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @admin_group.command(name="membership-history", description="Lihat history grant/revoke membership.")
    @discord.app_commands.describe(user="Filter berdasarkan user (opsional).")
    @discord.app_commands.guild_only()
    async def membership_history(self, interaction: discord.Interaction, user: discord.User = None):
        await interaction.response.defer(ephemeral=True)

        uid = user.id if user else None
        results = await self.bot.GET(GET_HISTORY, (interaction.guild_id, uid, uid))

        if not results:
            return await interaction.followup.send("Tidak ada history membership.", ephemeral=True)

        embed = discord.Embed(title="Membership History", color=discord.Color.blue())

        for user_id, action, tier, granted_by, timestamp, reason in results[:25]:
            ts = int(datetime.fromisoformat(timestamp).timestamp())

            emoji = {"grant": "✅", "revoke": "❌", "warned_expiry": "⚠️", "lifetime_unlocked": "👑"}.get(action, "•")

            try:
                tu = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                uname = tu.name
            except Exception:
                uname = f"User {user_id}"

            try:
                gu = self.bot.get_user(granted_by) or await self.bot.fetch_user(granted_by) if granted_by else None
                gname = gu.name if gu else "System"
            except Exception:
                gname = "System"

            tier_name = get_tier_info(tier).get('name', tier) if tier else "—"
            val = f"{emoji} **{action.upper()}** — {tier_name}\n<t:{ts}:F>\nBy: {gname}"
            if reason:
                val += f"\n_{reason}_"
            embed.add_field(name=uname, value=val, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @admin_group.command(name="membership-purge-history", description="Hapus history membership user (admin only).")
    @discord.app_commands.describe(user="User yang history-nya mau dihapus.")
    @discord.app_commands.guild_only()
    async def membership_purge_history(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("❌ Hanya admin yang bisa purge history.", ephemeral=True)

        await self.bot.RUN(PURGE_HISTORY, (interaction.guild_id, user.id))
        await interaction.followup.send(f"✅ History membership {user.mention} telah dihapus.", ephemeral=True)

    # ========================================================================
    # BACKGROUND TASK — EXPIRY CHECK
    # ========================================================================

    @tasks.loop(hours=24)
    async def membership_expiry_check(self):
        try:
            guild = self.bot.get_guild(self.guild_id)
            if not guild:
                return

            now           = utcnow()
            grace_period  = membership_settings['membership']['grace_period_days']
            warn_threshold = (now + timedelta(days=grace_period)).isoformat()

            # Warning DM (3 hari sebelum expiry) — lifetime otomatis skip karena query filter is_lifetime=0
            expiring = await self.bot.GET(
                GET_EXPIRING_MEMBERSHIPS,
                (self.guild_id, warn_threshold, now.isoformat())
            )

            for user_id, tier, expires_at in (expiring or []):
                already_warned = await self.bot.GET_ONE(
                    GET_WARNING_SENT,
                    (self.guild_id, user_id, (now - timedelta(hours=23)).isoformat())
                )
                if already_warned:
                    continue

                expires_ts = int(datetime.fromisoformat(expires_at).timestamp())
                tier_info  = get_tier_info(tier)

                embed = discord.Embed(
                    title="⏰ Membership Expiry Warning",
                    description=f"Membership kamu akan expired dalam **{grace_period} hari**.",
                    color=discord.Color.orange()
                )
                embed.add_field(name="Tier",       value=tier_info.get('name', tier), inline=True)
                embed.add_field(name="Expires",    value=f"<t:{expires_ts}:F>",       inline=True)
                embed.add_field(name="Action",     value="Hubungi admin untuk renewal.", inline=False)

                row = await self.bot.GET_ONE(GET_MEMBERSHIP, (self.guild_id, user_id))
                if row:
                    payment_count = row[6]
                    remaining     = LIFETIME_THRESHOLD - payment_count
                    embed.add_field(
                        name="Progress Lifetime",
                        value=f"{payment_count}/{LIFETIME_THRESHOLD} ({remaining} pembayaran lagi untuk lifetime)",
                        inline=False
                    )

                await send_dm_safe(user_id, self.bot, embed)
                await self.bot.RUN(
                    INSERT_HISTORY,
                    (self.guild_id, user_id, 'warned_expiry', tier, None, now.isoformat(),
                     f"Auto warning {grace_period} days before expiry")
                )
                _log.info(f"Sent expiry warning to {user_id}")

            # Auto-revoke expired — lifetime skip via is_lifetime=0 di query
            expired = await self.bot.GET(GET_EXPIRED_MEMBERSHIPS, (self.guild_id, now.isoformat()))

            for user_id, tier, _ in (expired or []):
                await self.bot.RUN(REVOKE_MEMBERSHIP, (self.guild_id, user_id))

                member = guild.get_member(user_id)
                if member:
                    tier_info = get_tier_info(tier)
                    role      = guild.get_role(tier_info['role_id'])
                    if role and role in member.roles:
                        try:
                            await member.remove_roles(role)
                        except discord.Forbidden:
                            pass
                    if tier == 'intensive':
                        reguler_role = guild.get_role(get_tier_info('reguler')['role_id'])
                        if reguler_role and reguler_role in member.roles:
                            try:
                                await member.remove_roles(reguler_role)
                            except discord.Forbidden:
                                pass

                await self.bot.RUN(
                    INSERT_HISTORY,
                    (self.guild_id, user_id, 'revoke', tier, None, now.isoformat(), "Auto revoke - membership expired")
                )

                embed = discord.Embed(
                    title="⚠️ Membership Expired",
                    description="Membership kamu telah berakhir dan role sudah dicabut.",
                    color=discord.Color.red()
                )
                embed.add_field(name="Next Steps", value="Hubungi admin jika ingin renewal.", inline=False)

                row = await self.bot.GET_ONE(GET_MEMBERSHIP, (self.guild_id, user_id))
                if row:
                    payment_count = row[6]
                    remaining     = LIFETIME_THRESHOLD - payment_count
                    embed.add_field(
                        name="Progress Lifetime",
                        value=f"Kamu sudah {payment_count}/{LIFETIME_THRESHOLD} pembayaran. {remaining} lagi untuk lifetime!",
                        inline=False
                    )
                await send_dm_safe(user_id, self.bot, embed)
                _log.info(f"Auto-revoked expired membership for {user_id}")

        except Exception as e:
            _log.error(f"Error in membership expiry check: {e}")

    @membership_expiry_check.before_loop
    async def before_expiry_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: KotabiBot):
    await bot.add_cog(Membership(bot))
