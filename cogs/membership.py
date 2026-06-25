"""
Membership System Cog — Kotabi Japanese (June 2026)
===================================================

Tier system:
- trial      -> 7 hari, 0 poin
- traveler   -> 30 hari, +1 poin
- companion  -> 30 hari, +2 poin, auto include traveler
- intensive  -> 30 hari, +2 poin, auto include companion + traveler
- lifetime   -> otomatis saat point_count >= 26

Catatan desain:
- point_count menggantikan payment_count sebagai progres lifetime
- payment_count tetap disimpan untuk histori transaksi mentah
- lifetime member tidak pernah di-auto-revoke
- trial tidak pernah dapat warning H-3; langsung expire & revoke
- saat lifetime tercapai:
    * role Patron ditambahkan
    * role Traveler + Companion dicabut
    * role Intensive/Scholar dipertahankan jika aktif
- grant trial diblok jika user masih punya membership aktif / lifetime
- grant paid tier akan extend dari expiry lama jika membership lama masih aktif
- saat grant tier baru, role membership lama dibersihkan dulu agar tidak nyisa
- /admin grant-batch mendukung trial
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Iterable

import discord
import yaml
from discord.ext import commands, tasks
from discord.utils import utcnow

from lib.bot import KotabiBot

_log = logging.getLogger(__name__)

MEMBERSHIP_SETTINGS_PATH = (
    os.getenv("ALT_MEMBERSHIP_SETTINGS_PATH")
    or "config/membership_settings.yml"
)

with open(MEMBERSHIP_SETTINGS_PATH, "r", encoding="utf-8") as f:
    membership_settings = yaml.safe_load(f)

MEMBERSHIP_LOCK = asyncio.Lock()


# ============================================================================
# SETTINGS / CONSTANTS
# ============================================================================

MEMBERSHIP_CFG = membership_settings["membership"]
ROLE_CFG = MEMBERSHIP_CFG["roles"]

LIFETIME_THRESHOLD = ROLE_CFG["lifetime"]["point_threshold"]

TRIAL_RESET_MONTH_DAYS = [
    tuple(x) for x in MEMBERSHIP_CFG.get("trial", {}).get(
        "reset_month_days",
        [(1, 10), (9, 10)]
    )
]

ALL_MEMBERSHIP_ROLE_KEYS = ["trial", "traveler", "companion", "intensive"]


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
    point_count     INTEGER NOT NULL DEFAULT 0,
    is_lifetime     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
"""

ADD_PAYMENT_COUNT_COLUMN = """
ALTER TABLE memberships ADD COLUMN payment_count INTEGER NOT NULL DEFAULT 0;
"""

ADD_POINT_COUNT_COLUMN = """
ALTER TABLE memberships ADD COLUMN point_count INTEGER NOT NULL DEFAULT 0;
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

# Upsert membership.
# - payment_count hanya naik kalau tier bukan trial
# - point_count naik sesuai points tier, tapi kalau sudah lifetime -> tidak bertambah
# - expires_at lifetime tidak boleh tertimpa
INSERT_MEMBERSHIP = """
INSERT INTO memberships (
    guild_id, user_id, tier, granted_at, expires_at,
    active, granted_by, payment_count, point_count, is_lifetime
)
VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 0)
ON CONFLICT (guild_id, user_id) DO UPDATE SET
    tier = excluded.tier,
    granted_at = excluded.granted_at,
    expires_at = CASE
        WHEN memberships.is_lifetime = 1 THEN memberships.expires_at
        ELSE excluded.expires_at
    END,
    active = 1,
    granted_by = excluded.granted_by,
    payment_count = memberships.payment_count + excluded.payment_count,
    point_count = CASE
        WHEN memberships.is_lifetime = 1 THEN memberships.point_count
        ELSE memberships.point_count + excluded.point_count
    END;
"""

GET_MEMBERSHIP = """
SELECT
    user_id, tier, granted_at, expires_at, active, granted_by,
    payment_count, point_count, is_lifetime
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

# Warning H-3 untuk member berbayar saja (exclude trial)
GET_EXPIRING_MEMBERSHIPS = """
SELECT user_id, tier, expires_at
FROM memberships
WHERE guild_id = ?
  AND active = 1
  AND is_lifetime = 0
  AND tier != 'trial'
  AND expires_at <= ?
  AND expires_at > ?;
"""

# Expired paid member (exclude trial)
GET_EXPIRED_MEMBERSHIPS = """
SELECT user_id, tier, expires_at
FROM memberships
WHERE guild_id = ?
  AND active = 1
  AND is_lifetime = 0
  AND tier != 'trial'
  AND expires_at <= ?;
"""

# Expired trial
GET_EXPIRED_TRIALS = """
SELECT user_id, tier, expires_at
FROM memberships
WHERE guild_id = ?
  AND active = 1
  AND is_lifetime = 0
  AND tier = 'trial'
  AND expires_at <= ?;
"""

GET_WARNING_SENT = """
SELECT user_id
FROM membership_history
WHERE guild_id = ?
  AND user_id = ?
  AND action = 'warned_expiry'
  AND timestamp > ?;
"""

# History grant trial untuk validasi reset
GET_TRIAL_GRANTS = """
SELECT timestamp
FROM membership_history
WHERE guild_id = ?
  AND user_id = ?
  AND action = 'grant'
  AND tier = 'trial'
ORDER BY timestamp DESC;
"""


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_tier_info(tier: str) -> dict:
    return ROLE_CFG.get(tier, {})


def get_announcement_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    channel_id = MEMBERSHIP_CFG["announcement_channel_id"]
    return guild.get_channel(channel_id)


def get_role(guild: discord.Guild, tier: str) -> Optional[discord.Role]:
    tier_info = get_tier_info(tier)
    role_id = tier_info.get("role_id")
    return guild.get_role(role_id) if role_id else None


def get_lifetime_role(guild: discord.Guild) -> Optional[discord.Role]:
    lifetime_role_id = ROLE_CFG["lifetime"]["role_id"]
    return guild.get_role(lifetime_role_id)


def fmt_progress(point_count: int) -> str:
    remaining = max(0, LIFETIME_THRESHOLD - point_count)
    return f"{point_count}/{LIFETIME_THRESHOLD} poin ({remaining} poin lagi)"


def fmt_progress_short(point_count: int) -> str:
    remaining = max(0, LIFETIME_THRESHOLD - point_count)
    return f"{point_count}/{LIFETIME_THRESHOLD} poin ({remaining} lagi)"


def tier_points(tier: str) -> int:
    return int(get_tier_info(tier).get("points", 0))


def tier_duration_days(tier: str) -> int:
    return int(get_tier_info(tier).get("duration_days", 30))


def is_paid_tier(tier: str) -> bool:
    return tier in {"traveler", "companion", "intensive"}


def parse_dt(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str)


def membership_is_currently_active(row: tuple) -> bool:
    """
    row format:
    (
        user_id, tier, granted_at, expires_at, active, granted_by,
        payment_count, point_count, is_lifetime
    )
    """
    if not row:
        return False

    active = bool(row[4])
    expires_at = parse_dt(row[3])
    is_lifetime = bool(row[8])

    if is_lifetime:
        return True

    now = utcnow().replace(tzinfo=None)
    return active and expires_at > now


def role_chain_for_tier(tier: str) -> list[str]:
    """
    Role chain yang HARUS dimiliki saat tier aktif.
    Trial      -> trial
    Traveler   -> traveler
    Companion  -> companion + traveler
    Intensive  -> intensive + companion + traveler
    Lifetime tidak dipakai sebagai tier grant biasa.
    """
    if tier == "trial":
        return ["trial"]
    if tier == "traveler":
        return ["traveler"]
    if tier == "companion":
        return ["companion", "traveler"]
    if tier == "intensive":
        return ["intensive", "companion", "traveler"]
    return []


def roles_to_remove_on_revoke(tier: str) -> list[str]:
    """
    Saat revoke manual/expired:
    - trial      -> trial
    - traveler   -> traveler
    - companion  -> companion + traveler
    - intensive  -> intensive + companion + traveler
    """
    return role_chain_for_tier(tier)


def trial_reset_anchors_for_year(year: int) -> list[datetime]:
    return [datetime(year, month, day) for month, day in TRIAL_RESET_MONTH_DAYS]


def latest_trial_reset_before(dt: datetime) -> Optional[datetime]:
    """
    Ambil anchor reset trial terbaru yang <= dt.
    """
    anchors = []
    for year in (dt.year - 1, dt.year, dt.year + 1):
        anchors.extend(trial_reset_anchors_for_year(year))
    anchors = sorted(a for a in anchors if a <= dt)
    return anchors[-1] if anchors else None


async def send_dm_safe(user_id: int, bot: KotabiBot, embed: discord.Embed) -> bool:
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if not user.dm_channel:
            await user.create_dm()
        await user.send(embed=embed)
        return True
    except (discord.Forbidden, discord.NotFound):
        _log.warning("Could not DM user %s", user_id)
        return False


async def _try_add_column(bot: KotabiBot, sql: str):
    try:
        await bot.RUN(sql)
    except Exception:
        pass  # kemungkinan kolom sudah ada


async def add_roles_for_tier(member: discord.Member, tier: str):
    """
    Assign semua role chain yang dibutuhkan oleh tier.
    """
    role_names = role_chain_for_tier(tier)
    to_add = []
    guild = member.guild

    for role_key in role_names:
        role = get_role(guild, role_key)
        if role and role not in member.roles:
            to_add.append(role)

    if to_add:
        await member.add_roles(*to_add)


async def remove_roles_by_keys(member: discord.Member, role_keys: Iterable[str]):
    guild = member.guild
    to_remove = []

    for role_key in role_keys:
        role = get_role(guild, role_key)
        if role and role in member.roles:
            to_remove.append(role)

    if to_remove:
        await member.remove_roles(*to_remove)


async def remove_all_membership_roles(member: discord.Member):
    await remove_roles_by_keys(member, ALL_MEMBERSHIP_ROLE_KEYS)


async def apply_lifetime_role_transition(
    bot: KotabiBot,
    guild: discord.Guild,
    user_id: int,
    tier: str,
):
    """
    Saat user unlock lifetime:
    - add Patron
    - cabut Traveler + Companion
    - Scholar/intensive tetap dipertahankan jika tier aktif intensive
    - trial role kalau somehow ada, cabut juga
    """
    member = guild.get_member(user_id)
    if not member:
        return

    lifetime_role = get_lifetime_role(guild)
    if lifetime_role and lifetime_role not in member.roles:
        await member.add_roles(lifetime_role)

    # Cabut role transisional
    to_remove = ["trial", "traveler", "companion"]

    # intensive tetap dipertahankan
    await remove_roles_by_keys(member, to_remove)


async def can_take_trial(bot: KotabiBot, guild_id: int, user_id: int) -> tuple[bool, Optional[str]]:
    """
    Rule:
    - Kalau belum pernah trial -> boleh
    - Kalau sudah pernah, boleh lagi HANYA jika trial terakhir < reset anchor terbaru
      (reset tiap 10 Jan & 10 Sep)
    """
    rows = await bot.GET(GET_TRIAL_GRANTS, (guild_id, user_id))
    if not rows:
        return True, None

    latest_grant_ts = rows[0][0]
    latest_grant_dt = datetime.fromisoformat(latest_grant_ts)
    now = utcnow().replace(tzinfo=None)

    reset_anchor = latest_trial_reset_before(now)
    if reset_anchor and latest_grant_dt < reset_anchor:
        return True, None

    # cari next reset
    candidates = []
    for year in (now.year, now.year + 1):
        for month, day in TRIAL_RESET_MONTH_DAYS:
            candidates.append(datetime(year, month, day))
    future_resets = sorted(dt for dt in candidates if dt > now)
    next_reset = future_resets[0] if future_resets else None

    if next_reset:
        next_reset_str = next_reset.strftime("%d %B %Y")
        return False, (
            "Kamu sudah pernah menggunakan Trial.\n"
            f"Trial berikutnya tersedia pada **{next_reset_str}**."
        )

    return False, "Kamu sudah pernah menggunakan Trial."


async def _do_grant(
    bot: KotabiBot,
    guild: discord.Guild,
    user: discord.User,
    tier: str,
    granted_by_id: int,
) -> dict:
    """
    Core grant logic untuk single/batch.
    Return:
    {
        success,
        payment_count,
        point_count,
        is_lifetime,
        expires_at,
        tier_info,
        just_unlocked_lifetime,
    }
    """
    tier_info = get_tier_info(tier)
    if not tier_info:
        raise ValueError(f"Tier tidak valid: {tier}")

    now = utcnow().replace(tzinfo=None)

    # Ambil membership lama dulu
    old_row = await bot.GET_ONE(GET_MEMBERSHIP, (guild.id, user.id))

    old_tier = None
    old_active = False
    old_is_lifetime = False
    old_expires_at = None

    if old_row:
        old_tier = old_row[1]
        old_active = bool(old_row[4])
        old_expires_at = datetime.fromisoformat(old_row[3])
        old_is_lifetime = bool(old_row[8])

    # ============================================================
    # RULE 1 — TRIAL TIDAK BOLEH MENIMPA MEMBERSHIP AKTIF / LIFETIME
    # ============================================================
    if tier == "trial" and old_row:
        if old_is_lifetime:
            raise ValueError("User sudah Lifetime Member, tidak bisa diberi trial.")
        if old_active and old_expires_at and old_expires_at > now:
            raise ValueError("User masih punya membership aktif, trial tidak bisa diberikan.")

    # ============================================================
    # RULE 2 — RENEWAL PAID TIER EXTEND DARI EXPIRY LAMA JIKA MASIH AKTIF
    # ============================================================
    duration_days = tier_duration_days(tier)

    if tier != "trial" and old_row and old_active and old_expires_at and old_expires_at > now:
        # extend dari expiry lama
        expires_at = old_expires_at + timedelta(days=duration_days)
    else:
        # normal: mulai dari sekarang
        expires_at = now + timedelta(days=duration_days)

    payment_increment = 1 if is_paid_tier(tier) else 0
    point_increment = tier_points(tier)

    # Upsert ke DB
    await bot.RUN(
        INSERT_MEMBERSHIP,
        (
            guild.id,
            user.id,
            tier,
            now.isoformat(),
            expires_at.isoformat(),
            granted_by_id,
            payment_increment,
            point_increment,
        )
    )

    # Ambil row terbaru
    row = await bot.GET_ONE(GET_MEMBERSHIP, (guild.id, user.id))
    if not row:
        raise RuntimeError("Membership row not found after upsert")

    (
        _user_id,
        current_tier,
        _granted_at,
        db_expires_at,
        _active,
        _granted_by,
        payment_count,
        point_count,
        is_lifetime,
    ) = row

    target_member = guild.get_member(user.id)
    if target_member:
        # ========================================================
        # RULE 3 — RESET ROLE MEMBERSHIP LAMA DULU
        # ========================================================
        await remove_all_membership_roles(target_member)

        # lalu apply role chain tier baru
        await add_roles_for_tier(target_member, tier)

    just_unlocked_lifetime = False

    if not is_lifetime and point_count >= LIFETIME_THRESHOLD:
        await bot.RUN(SET_LIFETIME, (guild.id, user.id))
        is_lifetime = 1
        just_unlocked_lifetime = True

        await apply_lifetime_role_transition(bot, guild, user.id, tier)

        await bot.RUN(
            INSERT_HISTORY,
            (
                guild.id,
                user.id,
                "lifetime_unlocked",
                tier,
                granted_by_id,
                now.isoformat(),
                f"Reached {LIFETIME_THRESHOLD} points",
            ),
        )
        _log.info("User %s unlocked lifetime membership (%s points)", user.id, point_count)

    await bot.RUN(
        INSERT_HISTORY,
        (guild.id, user.id, "grant", tier, granted_by_id, now.isoformat(), None)
    )

    return {
        "success": True,
        "payment_count": payment_count,
        "point_count": point_count,
        "is_lifetime": bool(is_lifetime),
        "expires_at": datetime.fromisoformat(db_expires_at),
        "tier_info": tier_info,
        "just_unlocked_lifetime": just_unlocked_lifetime,
    }


# ============================================================================
# MEMBERSHIP COG
# ============================================================================

class Membership(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot
        self.guild_id = MEMBERSHIP_CFG["guild_id"]

    async def cog_load(self):
        await self.bot.RUN(CREATE_MEMBERSHIPS_TABLE)
        await self.bot.RUN(CREATE_MEMBERSHIP_HISTORY_TABLE)

        await _try_add_column(self.bot, ADD_PAYMENT_COUNT_COLUMN)
        await _try_add_column(self.bot, ADD_POINT_COUNT_COLUMN)
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
        mod_ids = MEMBERSHIP_CFG["moderator_role_ids"]
        return bool(mod_ids and any(r.id in mod_ids for r in member.roles))

    # ========================================================================
    # COMMAND GROUP
    # ========================================================================

    admin_group = discord.app_commands.Group(
        name="admin",
        description="Admin commands"
    )

    # ========================================================================
    # GRANT MEMBER
    # ========================================================================

    @admin_group.command(name="grant-member", description="Grant membership ke satu user.")
    @discord.app_commands.describe(
        user="User yang mau dikasih membership.",
        tier="Tier membership."
    )
    @discord.app_commands.choices(tier=[
        discord.app_commands.Choice(name="Traveler — Rp46k / 30 hari", value="traveler"),
        discord.app_commands.Choice(name="Companion — Rp92k / 30 hari", value="companion"),
        discord.app_commands.Choice(name="Scholar / Intensive — Rp350k / 30 hari", value="intensive"),
    ])
    @discord.app_commands.guild_only()
    async def grant_member(self, interaction: discord.Interaction, user: discord.User, tier: str):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not await self._check_can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        if tier == "trial":
            return await interaction.followup.send(
                "❌ Trial harus lewat command `/admin grant-trial`.",
                ephemeral=True
            )

        if not get_tier_info(tier):
            return await interaction.followup.send(f"❌ Tier `{tier}` tidak valid.", ephemeral=True)

        async with MEMBERSHIP_LOCK:
            try:
                result = await _do_grant(self.bot, interaction.guild, user, tier, interaction.user.id)
            except Exception as e:
                _log.exception("grant_member error")
                return await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

        tier_info = result["tier_info"]
        is_lifetime = result["is_lifetime"]
        point_count = result["point_count"]
        expires_at = result["expires_at"]
        expire_ts = int(expires_at.timestamp())

        if is_lifetime:
            dm_embed = discord.Embed(
                title="✅ Membership Granted — LIFETIME 👑",
                description=(
                    f"Selamat! Kamu telah mencapai **{LIFETIME_THRESHOLD} poin kumulatif** "
                    f"dan sekarang menjadi **{ROLE_CFG['lifetime']['name']}** secara permanen.\n\n"
                    f"Kamu tidak perlu membayar membership lagi. Terima kasih atas dukunganmu! 🎉"
                ),
                color=discord.Color.gold()
            )
            dm_embed.add_field(name="Tier saat ini", value=tier_info["name"], inline=True)
            dm_embed.add_field(name="Progress Lifetime", value=f"{point_count}/{LIFETIME_THRESHOLD} poin ✅", inline=True)
        else:
            dm_embed = discord.Embed(
                title="✅ Membership Granted",
                description=f"Selamat! Kamu sekarang memiliki membership **{tier_info['name']}**.",
                color=discord.Color.green()
            )
            dm_embed.add_field(name="Tier", value=tier_info["name"], inline=True)
            dm_embed.add_field(name="Expires", value=f"<t:{expire_ts}:F>", inline=True)
            dm_embed.add_field(
                name="Progress Lifetime",
                value=fmt_progress(point_count),
                inline=False
            )

        await send_dm_safe(user.id, self.bot, dm_embed)

        ch = get_announcement_channel(interaction.guild)
        if ch:
            ann = discord.Embed(
                title="🎉 Member Baru" + (" 👑 LIFETIME" if is_lifetime else ""),
                description=f"{user.mention} telah mendapatkan membership **{tier_info['name']}**",
                color=discord.Color.gold() if is_lifetime else discord.Color.green()
            )
            ann.set_thumbnail(url=user.display_avatar.url)
            if is_lifetime:
                ann.add_field(name="Status", value=f"{ROLE_CFG['lifetime']['name']} ✅", inline=False)
            try:
                await ch.send(embed=ann)
            except discord.Forbidden:
                pass

        reply = (
            f"✅ Membership granted → {user.mention} ({tier_info['name']})\n"
            f"Progress Lifetime: **{point_count}/{LIFETIME_THRESHOLD} poin**\n"
        )
        if is_lifetime:
            reply += "🎉 User sekarang **LIFETIME MEMBER**!"
        else:
            reply += f"Expires: <t:{expire_ts}:R>"

        await interaction.followup.send(reply, ephemeral=True)

    # ========================================================================
    # GRANT TRIAL
    # ========================================================================

    @admin_group.command(name="grant-trial", description="Grant trial 7 hari (0 poin).")
    @discord.app_commands.describe(user="User yang mau dikasih trial.")
    @discord.app_commands.guild_only()
    async def grant_trial(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not await self._check_can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        existing = await self.bot.GET_ONE(GET_MEMBERSHIP, (interaction.guild_id, user.id))
        if existing:
            existing_active = bool(existing[4])
            existing_expires = datetime.fromisoformat(existing[3])
            existing_lifetime = bool(existing[8])
            now = utcnow().replace(tzinfo=None)

            if existing_lifetime:
                return await interaction.followup.send(
                    f"❌ {user.mention} sudah **Lifetime Member**.",
                    ephemeral=True
                )

            if existing_active and existing_expires > now:
                return await interaction.followup.send(
                    f"❌ {user.mention} masih punya membership aktif, jadi trial tidak bisa diberikan.",
                    ephemeral=True
                )

        allowed, reason = await can_take_trial(self.bot, interaction.guild_id, user.id)
        if not allowed:
            return await interaction.followup.send(f"❌ {reason}", ephemeral=True)

        async with MEMBERSHIP_LOCK:
            try:
                result = await _do_grant(self.bot, interaction.guild, user, "trial", interaction.user.id)
            except Exception as e:
                _log.exception("grant_trial error")
                return await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

        tier_info = result["tier_info"]
        expires_at = result["expires_at"]
        expire_ts = int(expires_at.timestamp())

        dm_embed = discord.Embed(
            title="🎁 Trial Membership Activated",
            description=(
                f"Kamu mendapat akses **{tier_info['name']}** selama **7 hari**.\n\n"
                "Selama trial kamu bisa mencoba fitur premium seperti immersion log, quiz rank-up, "
                "kamus bot, dan member area."
            ),
            color=discord.Color.blurple()
        )
        dm_embed.add_field(name="Expires", value=f"<t:{expire_ts}:F>", inline=True)
        dm_embed.add_field(name="Progress Lifetime", value="0 poin — trial tidak menambah lifetime", inline=False)
        await send_dm_safe(user.id, self.bot, dm_embed)

        await interaction.followup.send(
            f"✅ Trial granted → {user.mention}\nExpires: <t:{expire_ts}:R>",
            ephemeral=True
        )

    # ========================================================================
    # GRANT BATCH
    # ========================================================================

    @admin_group.command(name="grant-batch", description="Grant membership ke banyak user sekaligus.")
    @discord.app_commands.describe(users="Mention user (@User1 @User2 ...)", tier="Tier membership.")
    @discord.app_commands.choices(tier=[
        discord.app_commands.Choice(name="Trial — 7 hari", value="trial"),
        discord.app_commands.Choice(name="Traveler — Rp46k / 30 hari", value="traveler"),
        discord.app_commands.Choice(name="Companion — Rp92k / 30 hari", value="companion"),
        discord.app_commands.Choice(name="Scholar / Intensive — Rp350k / 30 hari", value="intensive"),
    ])
    @discord.app_commands.guild_only()
    async def grant_batch(self, interaction: discord.Interaction, users: str, tier: str):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not await self._check_can_manage(member):
            return await interaction.followup.send("❌ Kamu tidak punya izin.", ephemeral=True)

        if not get_tier_info(tier):
            return await interaction.followup.send("❌ Tier batch tidak valid.", ephemeral=True)

        ids = re.findall(r"<@!?(\d+)>", users)
        if not ids:
            return await interaction.followup.send("❌ Tidak ada mention valid. Gunakan @User.", ephemeral=True)

        success_list = []
        fail_list = []

        async with MEMBERSHIP_LOCK:
            for uid_str in ids:
                uid = int(uid_str)
                try:
                    target = interaction.guild.get_member(uid)
                    if not target:
                        target = await interaction.guild.fetch_member(uid)

                    user_obj = target._user if hasattr(target, "_user") else target

                    if tier == "trial":
                        # blok trial kalau membership aktif / lifetime
                        existing = await self.bot.GET_ONE(GET_MEMBERSHIP, (interaction.guild_id, uid))
                        if existing:
                            existing_active = bool(existing[4])
                            existing_expires = datetime.fromisoformat(existing[3])
                            existing_lifetime = bool(existing[8])
                            now = utcnow().replace(tzinfo=None)

                            if existing_lifetime:
                                fail_list.append(f"<@{uid}> — sudah Lifetime Member")
                                continue

                            if existing_active and existing_expires > now:
                                fail_list.append(f"<@{uid}> — masih punya membership aktif")
                                continue

                        allowed, reason = await can_take_trial(self.bot, interaction.guild_id, uid)
                        if not allowed:
                            fail_list.append(f"<@{uid}> — {reason}")
                            continue

                    result = await _do_grant(self.bot, interaction.guild, user_obj, tier, interaction.user.id)

                    tier_info = result["tier_info"]
                    is_lifetime = result["is_lifetime"]
                    point_count = result["point_count"]
                    expires_at = result["expires_at"]
                    expire_ts = int(expires_at.timestamp())

                    if is_lifetime:
                        dm_embed = discord.Embed(
                            title="✅ Membership Granted — LIFETIME 👑",
                            description=(
                                f"Kamu telah mencapai **{LIFETIME_THRESHOLD} poin kumulatif** "
                                f"dan sekarang menjadi **{ROLE_CFG['lifetime']['name']}** secara permanen! 🎉"
                            ),
                            color=discord.Color.gold()
                        )
                        dm_embed.add_field(
                            name="Progress Lifetime",
                            value=f"{point_count}/{LIFETIME_THRESHOLD} poin ✅",
                            inline=True
                        )

                    elif tier == "trial":
                        dm_embed = discord.Embed(
                            title="🎁 Trial Membership Activated",
                            description=(
                                f"Kamu mendapat akses **{tier_info['name']}** selama **7 hari**.\n\n"
                                "Selama trial kamu bisa mencoba fitur premium seperti immersion log, "
                                "quiz rank-up, kamus bot, dan member area."
                            ),
                            color=discord.Color.blurple()
                        )
                        dm_embed.add_field(name="Expires", value=f"<t:{expire_ts}:F>", inline=True)
                        dm_embed.add_field(
                            name="Progress Lifetime",
                            value="0 poin — trial tidak menambah lifetime",
                            inline=False
                        )

                    else:
                        dm_embed = discord.Embed(
                            title="✅ Membership Granted",
                            description=f"Selamat! Kamu sekarang memiliki membership **{tier_info['name']}**.",
                            color=discord.Color.green()
                        )
                        dm_embed.add_field(name="Expires", value=f"<t:{expire_ts}:F>", inline=True)
                        dm_embed.add_field(
                            name="Progress Lifetime",
                            value=fmt_progress_short(point_count),
                            inline=False
                        )

                    await send_dm_safe(uid, self.bot, dm_embed)

                    if is_lifetime:
                        label = f"{target.name} 👑 LIFETIME"
                    elif tier == "trial":
                        label = f"{target.name} • trial 7 hari"
                    else:
                        label = f"{target.name} • {point_count}/{LIFETIME_THRESHOLD} poin"

                    success_list.append(label)

                except discord.NotFound:
                    fail_list.append(f"<@{uid}> — member not found")
                except Exception as e:
                    fail_list.append(f"<@{uid}> — {e}")
                    _log.exception("Batch grant error uid %s", uid)

        tier_info = get_tier_info(tier)

        if success_list:
            ch = get_announcement_channel(interaction.guild)
            if ch:
                ann = discord.Embed(
                    title=f"🎉 {len(success_list)} Member Baru",
                    color=discord.Color.blurple() if tier == "trial" else discord.Color.green()
                )
                ann.add_field(name="Tier", value=tier_info["name"], inline=True)
                ann.add_field(
                    name="Daftar",
                    value="\n".join(f"• {n}" for n in success_list)[:1024],
                    inline=False
                )
                try:
                    await ch.send(embed=ann)
                except discord.Forbidden:
                    pass

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
        summary.add_field(name="Tier", value=tier_info["name"], inline=True)
        summary.add_field(name="Total", value=f"{len(success_list)}/{len(ids)}", inline=True)
        await interaction.followup.send(embed=summary, ephemeral=True)

    # ========================================================================
    # REVOKE MEMBER
    # ========================================================================

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

            (
                _uid,
                tier,
                _granted_at,
                _expires_at,
                active,
                _granted_by,
                _payment_count,
                point_count,
                is_lifetime,
            ) = row

            if is_lifetime:
                return await interaction.followup.send(
                    f"❌ {user.mention} adalah **Lifetime Member** — tidak bisa di-revoke.",
                    ephemeral=True
                )

            if not active:
                return await interaction.followup.send(
                    f"❌ Membership {user.mention} sudah inactive.",
                    ephemeral=True
                )

            await self.bot.RUN(REVOKE_MEMBERSHIP, (interaction.guild_id, user.id))

            target_member = interaction.guild.get_member(user.id)
            if target_member:
                try:
                    await remove_roles_by_keys(target_member, roles_to_remove_on_revoke(tier))
                except discord.Forbidden:
                    pass

            now = utcnow()
            await self.bot.RUN(
                INSERT_HISTORY,
                (interaction.guild_id, user.id, "revoke", tier, interaction.user.id, now.isoformat(), "Manual revoke")
            )

            embed = discord.Embed(
                title="⚠️ Membership Revoked",
                description="Membership kamu telah dihapus dan role dicabut.",
                color=discord.Color.red()
            )
            embed.add_field(
                name="Info",
                value=f"Progress lifetime kamu (**{point_count}/{LIFETIME_THRESHOLD} poin**) tetap tersimpan.",
                inline=False
            )
            await send_dm_safe(user.id, self.bot, embed)

        await interaction.followup.send(f"✅ Membership revoked → {user.mention}", ephemeral=True)

    # ========================================================================
    # CHECK MEMBER
    # ========================================================================

    @admin_group.command(name="check-member", description="Cek status membership user.")
    @discord.app_commands.describe(user="User yang mau dicek.")
    @discord.app_commands.guild_only()
    async def check_member(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)

        row = await self.bot.GET_ONE(GET_MEMBERSHIP, (interaction.guild_id, user.id))
        if not row:
            return await interaction.followup.send(f"❌ {user.mention} tidak punya membership.", ephemeral=True)

        (
            _uid,
            tier,
            granted_at,
            expires_at,
            active,
            granted_by,
            payment_count,
            point_count,
            is_lifetime,
        ) = row

        granted_ts = int(datetime.fromisoformat(granted_at).timestamp())
        expires_dt = datetime.fromisoformat(expires_at)
        expires_ts = int(expires_dt.timestamp())
        tier_info = get_tier_info(tier)

        if is_lifetime:
            status_str = "👑 LIFETIME MEMBER"
            color = discord.Color.gold()
        elif active:
            color = discord.Color.green()
            if expires_dt > utcnow().replace(tzinfo=None):
                status_str = "✅ Active"
            else:
                status_str = "⚠️ Expired (belum tersapu task)"
        else:
            status_str = "❌ Inactive"
            color = discord.Color.red()

        embed = discord.Embed(title=f"Membership Status — {user.name}", color=color)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Status", value=status_str, inline=False)
        embed.add_field(name="Tier", value=tier_info.get("name", tier), inline=True)
        embed.add_field(name="Granted", value=f"<t:{granted_ts}:F>", inline=True)

        if is_lifetime:
            embed.add_field(name="Expires", value="Tidak pernah ♾️", inline=True)
            embed.add_field(name="Point Count", value=f"{point_count}/{LIFETIME_THRESHOLD} ✅", inline=True)
            embed.add_field(name="Payment Count", value=str(payment_count), inline=True)
            embed.add_field(name="Lifetime Role", value=ROLE_CFG["lifetime"]["name"], inline=False)
        else:
            embed.add_field(name="Expires", value=f"<t:{expires_ts}:F>", inline=True)
            embed.add_field(name="Time Remaining", value=f"<t:{expires_ts}:R>", inline=True)
            embed.add_field(
                name="Progress Lifetime",
                value=fmt_progress(point_count),
                inline=False
            )
            embed.add_field(name="Payment Count", value=str(payment_count), inline=True)

        if granted_by:
            granter = self.bot.get_user(granted_by)
            embed.add_field(
                name="Granted By",
                value=granter.mention if granter else f"User {granted_by}",
                inline=True
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ========================================================================
    # HISTORY
    # ========================================================================

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

        emoji_map = {
            "grant": "✅",
            "revoke": "❌",
            "warned_expiry": "⚠️",
            "trial_expired": "⌛",
            "lifetime_unlocked": "👑",
        }

        for user_id, action, tier, granted_by, timestamp, reason in results[:25]:
            ts = int(datetime.fromisoformat(timestamp).timestamp())
            emoji = emoji_map.get(action, "•")

            try:
                tu = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                uname = tu.name
            except Exception:
                uname = f"User {user_id}"

            try:
                gu = (
                    self.bot.get_user(granted_by) or await self.bot.fetch_user(granted_by)
                    if granted_by else None
                )
                gname = gu.name if gu else "System"
            except Exception:
                gname = "System"

            tier_name = get_tier_info(tier).get("name", tier) if tier else "—"
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

            now = utcnow()
            grace_period = MEMBERSHIP_CFG["grace_period_days"]
            warn_threshold = (now + timedelta(days=grace_period)).isoformat()

            # ================================================================
            # FASE 0 — TRIAL EXPIRED
            # ================================================================
            expired_trials = await self.bot.GET(GET_EXPIRED_TRIALS, (self.guild_id, now.isoformat()))

            for user_id, tier, _ in (expired_trials or []):
                await self.bot.RUN(REVOKE_MEMBERSHIP, (self.guild_id, user_id))

                member = guild.get_member(user_id)
                if member:
                    try:
                        await remove_roles_by_keys(member, ["trial"])
                    except discord.Forbidden:
                        pass

                await self.bot.RUN(
                    INSERT_HISTORY,
                    (
                        self.guild_id,
                        user_id,
                        "trial_expired",
                        tier,
                        None,
                        now.isoformat(),
                        "Auto revoke - trial expired",
                    )
                )

                embed = discord.Embed(
                    title="⏰ Trial Guest Kamu Sudah Berakhir",
                    description=(
                        "Masa preview 7 hari kamu sudah selesai dan akses premium sudah dicabut.\n\n"
                        "Suka dengan fiturnya? Lanjutkan dengan:\n"
                        "🎒 Traveler — Rp46.000/bulan\n"
                        "🤝 Companion — Rp92.000/bulan (full ecosystem)\n"
                        "📚 Scholar — Rp350.000/bulan (+ kelas intensif)\n\n"
                        "Hubungi admin untuk upgrade!"
                    ),
                    color=discord.Color.orange()
                )
                await send_dm_safe(user_id, self.bot, embed)
                _log.info("Auto-revoked expired trial for %s", user_id)

            # ================================================================
            # FASE 1 — WARNING 3 HARI (PAID MEMBER)
            # ================================================================
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
                tier_info = get_tier_info(tier)

                embed = discord.Embed(
                    title="⏰ Membership Expiry Warning",
                    description=f"Membership kamu akan expired dalam **{grace_period} hari**.",
                    color=discord.Color.orange()
                )
                embed.add_field(name="Tier", value=tier_info.get("name", tier), inline=True)
                embed.add_field(name="Expires", value=f"<t:{expires_ts}:F>", inline=True)
                embed.add_field(name="Action", value="Hubungi admin untuk renewal.", inline=False)

                row = await self.bot.GET_ONE(GET_MEMBERSHIP, (self.guild_id, user_id))
                if row:
                    point_count = row[7]
                    embed.add_field(
                        name="Progress Lifetime",
                        value=fmt_progress(point_count),
                        inline=False
                    )

                await send_dm_safe(user_id, self.bot, embed)
                await self.bot.RUN(
                    INSERT_HISTORY,
                    (
                        self.guild_id,
                        user_id,
                        "warned_expiry",
                        tier,
                        None,
                        now.isoformat(),
                        f"Auto warning {grace_period} days before expiry",
                    )
                )
                _log.info("Sent expiry warning to %s", user_id)

            # ================================================================
            # FASE 2 — EXPIRED PAID MEMBER
            # ================================================================
            expired = await self.bot.GET(GET_EXPIRED_MEMBERSHIPS, (self.guild_id, now.isoformat()))

            for user_id, tier, _ in (expired or []):
                await self.bot.RUN(REVOKE_MEMBERSHIP, (self.guild_id, user_id))

                member = guild.get_member(user_id)
                if member:
                    try:
                        await remove_roles_by_keys(member, roles_to_remove_on_revoke(tier))
                    except discord.Forbidden:
                        pass

                await self.bot.RUN(
                    INSERT_HISTORY,
                    (
                        self.guild_id,
                        user_id,
                        "revoke",
                        tier,
                        None,
                        now.isoformat(),
                        "Auto revoke - membership expired",
                    )
                )

                embed = discord.Embed(
                    title="⚠️ Membership Expired",
                    description="Membership kamu telah berakhir dan role sudah dicabut.",
                    color=discord.Color.red()
                )
                embed.add_field(name="Next Steps", value="Hubungi admin jika ingin renewal.", inline=False)

                row = await self.bot.GET_ONE(GET_MEMBERSHIP, (self.guild_id, user_id))
                if row:
                    point_count = row[7]
                    remaining = max(0, LIFETIME_THRESHOLD - point_count)
                    embed.add_field(
                        name="Progress Lifetime",
                        value=f"Kamu sudah {point_count}/{LIFETIME_THRESHOLD} poin. {remaining} lagi untuk lifetime!",
                        inline=False
                    )

                await send_dm_safe(user_id, self.bot, embed)
                _log.info("Auto-revoked expired membership for %s", user_id)

        except Exception as e:
            _log.exception("Error in membership expiry check: %s", e)

    @membership_expiry_check.before_loop
    async def before_expiry_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: KotabiBot):
    await bot.add_cog(Membership(bot))