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

# Menggunakan core.bot asinkron terbaru
from core.bot import KotabiBot

_log = logging.getLogger(__name__)

# Konfigurasi pembacaan berkas pengaturan klan/membership
MEMBERSHIP_SETTINGS_PATH = (
    os.getenv("ALT_MEMBERSHIP_SETTINGS_PATH")
    or "config/membership_settings.yml"
)

with open(MEMBERSHIP_SETTINGS_PATH, "r", encoding="utf-8") as f:
    membership_settings = yaml.safe_load(f)

MEMBERSHIP_LOCK = asyncio.Lock()


# ============================================================================
# KONFIGURASI / KONSTANTA UTAMA
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
# DATABASE QUERIES (ASINKRON)
# ============================================================================

CREATE_MEMBERSHIPS_TABLE = """
CREATE TABLE IF NOT EXISTS memberships (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    tier TEXT NOT NULL,
    granted_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    granted_by INTEGER,
    payment_count INTEGER NOT NULL DEFAULT 0,
    point_count INTEGER NOT NULL DEFAULT 0,
    is_lifetime INTEGER NOT NULL DEFAULT 0,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    tier TEXT,
    granted_by INTEGER,
    timestamp TIMESTAMP NOT NULL,
    reason TEXT
);
"""

# Upsert membership
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
    expires_at = '9999-12-31 23:59:59',
    active = 1
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
WHERE guild_id = ?
  AND active = 1
  AND is_lifetime = 0
  AND tier != 'trial'
  AND expires_at <= ?
  AND expires_at > ?;
"""

GET_EXPIRED_MEMBERSHIPS = """
SELECT user_id, tier, expires_at
FROM memberships
WHERE guild_id = ?
  AND active = 1
  AND is_lifetime = 0
  AND tier != 'trial'
  AND expires_at <= ?;
"""

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
# FUNGSI PEMBANTU (HELPERS)
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
    return f"**{point_count}/{LIFETIME_THRESHOLD} poin** ({remaining} poin lagi menuju keanggotaan permanen)"


def fmt_progress_short(point_count: int) -> str:
    remaining = max(0, LIFETIME_THRESHOLD - point_count)
    return f"{point_count}/{LIFETIME_THRESHOLD} poin (Sisa {remaining} poin lagi)"


def tier_points(tier: str) -> int:
    return int(get_tier_info(tier).get("points", 0))


def tier_duration_days(tier: str) -> int:
    return int(get_tier_info(tier).get("duration_days", 30))


def is_paid_tier(tier: str) -> bool:
    return tier in {"traveler", "companion", "intensive"}


def parse_dt(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str)


def membership_is_currently_active(row: tuple) -> bool:
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
    Rantai peran fungsional yang wajib disematkan ketika tier aktif.
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
    return role_chain_for_tier(tier)


def trial_reset_anchors_for_year(year: int) -> list[datetime]:
    return [datetime(year, month, day) for month, day in TRIAL_RESET_MONTH_DAYS]


def latest_trial_reset_before(dt: datetime) -> Optional[datetime]:
    """Mengambil jangkar reset uji coba (Trial) terbaru."""
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
        _log.warning("Gagal mengirimkan pesan DM privat kepada pengguna %s", user_id)
        return False


async def _try_add_column(bot: KotabiBot, sql: str):
    try:
        await bot.RUN(sql)
    except Exception:
        pass


async def add_roles_for_tier(member: discord.Member, tier: str):
    """Menyematkan seluruh peran yang dipersyaratkan oleh tingkatan keanggotaan."""
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
    """Mengeksekusi penyesuaian peran saat pengguna berhasil membuka status seumur hidup (Lifetime)."""
    member = guild.get_member(user_id)
    if not member:
        return

    lifetime_role = get_lifetime_role(guild)
    if lifetime_role and lifetime_role not in member.roles:
        await member.add_roles(lifetime_role)

    # Cabut seluruh peran transisi lama
    to_remove = ["trial", "traveler", "companion"]
    await remove_roles_by_keys(member, to_remove)


async def can_take_trial(bot: KotabiBot, guild_id: int, user_id: int) -> tuple[bool, Optional[str]]:
    """Memeriksa kelayakan warga untuk mengambil masa uji coba (Trial) baru."""
    rows = await bot.GET(GET_TRIAL_GRANTS, (guild_id, user_id))
    if not rows:
        return True, None

    latest_grant_ts = rows[0][0]
    latest_grant_dt = datetime.fromisoformat(latest_grant_ts)
    now = utcnow().replace(tzinfo=None)

    reset_anchor = latest_trial_reset_before(now)
    if reset_anchor and latest_grant_dt < reset_anchor:
        return True, None

    # Cari jadwal pembukaan reset Trial berikutnya
    candidates = []
    for year in (now.year, now.year + 1):
        for month, day in TRIAL_RESET_MONTH_DAYS:
            candidates.append(datetime(year, month, day))
    future_resets = sorted(dt for dt in candidates if dt > now)
    next_reset = future_resets[0] if future_resets else None

    if next_reset:
        next_reset_str = next_reset.strftime("%d %B %Y")
        return False, (
            "Anda sudah pernah menggunakan masa uji coba (Trial) sebelumnya.\n"
            f"Kesempatan uji coba gratis berikutnya baru akan dibuka kembali pada **{next_reset_str}**."
        )

    return False, "Anda sudah pernah mengklaim hak uji coba (Trial) gratis."


async def _do_grant(
    bot: KotabiBot,
    guild: discord.Guild,
    user: discord.User,
    tier: str,
    granted_by_id: int,
) -> dict:
    """Inti dari logika pemberian hak akses keanggotaan VIP."""
    tier_info = get_tier_info(tier)
    if not tier_info:
        raise ValueError(f"Tingkatan (Tier) tidak sah: {tier}")

    now = utcnow().replace(tzinfo=None)
    old_row = await bot.GET_ONE(GET_MEMBERSHIP, (guild.id, user.id))

    old_active = False
    old_is_lifetime = False
    old_expires_at = None

    if old_row:
        old_active = bool(old_row[4])
        old_expires_at = datetime.fromisoformat(old_row[3])
        old_is_lifetime = bool(old_row[8])

    # RULE 1 — Uji coba (Trial) tidak diperbolehkan menumpuk di atas status aktif/Lifetime
    if tier == "trial" and old_row:
        if old_is_lifetime:
            raise ValueError("Warga ini sudah menyandang keanggotaan Seumur Hidup (Lifetime), tidak memerlukan uji coba gratis.")
        if old_active and old_expires_at and old_expires_at > now:
            raise ValueError("Warga ini masih memiliki masa keanggotaan VIP yang aktif. Masa uji coba tidak dapat disematkan.")

    # RULE 2 — Perpanjangan (Renewal) paid tier memperpanjang durasi kedaluwarsa lama
    duration_days = tier_duration_days(tier)

    if tier != "trial" and old_row and old_active and old_expires_at and old_expires_at > now:
        expires_at = old_expires_at + timedelta(days=duration_days)
    else:
        expires_at = now + timedelta(days=duration_days)

    payment_increment = 1 if is_paid_tier(tier) else 0
    point_increment = tier_points(tier)

    # Lakukan penyimpanan ke database
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

    row = await bot.GET_ONE(GET_MEMBERSHIP, (guild.id, user.id))
    if not row:
        raise RuntimeError("Gagal menemukan baris data mutasi keanggotaan terbaru di database.")

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
        # RULE 3 — Bersihkan peran keanggotaan lama terlebih dahulu agar tidak tumpang tindih
        await remove_all_membership_roles(target_member)
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
                f"Telah mencapai ambang batas {LIFETIME_THRESHOLD} poin",
            ),
        )
        _log.info("Warga %s telah resmi membuka keanggotaan Seumur Hidup (%s poin)", user.id, point_count)

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


class Membership(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot
        self.guild_id = MEMBERSHIP_CFG["guild_id"]

    async def cog_load(self):
        """Membuat seluruh tabel database pendukung pada saat modul dimuat."""
        await self.bot.RUN(CREATE_MEMBERSHIPS_TABLE)
        await self.bot.RUN(CREATE_MEMBERSHIP_HISTORY_TABLE)

        await _try_add_column(self.bot, ADD_PAYMENT_COUNT_COLUMN)
        await _try_add_column(self.bot, ADD_POINT_COUNT_COLUMN)
        await _try_add_column(self.bot, ADD_IS_LIFETIME_COLUMN)

        if not self.membership_expiry_check.is_running():
            self.membership_expiry_check.start()
            _log.info("Memulai tugas latar belakang pemeriksaan masa kedaluwarsa keanggotaan.")

    def cog_unload(self):
        if self.membership_expiry_check.is_running():
            self.membership_expiry_check.cancel()

    async def _check_can_manage(self, member: discord.Member) -> bool:
        """Memeriksa hak wewenang moderator/administrator pengelola."""
        if member.guild_permissions.administrator:
            return True
        mod_ids = MEMBERSHIP_CFG["moderator_role_ids"]
        return bool(mod_ids and any(r.id in mod_ids for r in member.roles))


    admin_group = discord.app_commands.Group(
        name="admin",
        description="Pusat kendali administratif pendaftaran keanggotaan premium."
    )


    @admin_group.command(name="grant-member", description="Berikan hak akses keanggotaan VIP premium kepada seorang warga.")
    @discord.app_commands.describe(
        user="Warga penerima yang ingin dianugerahi akses.",
        tier="Tingkat (tier) keanggotaan VIP."
    )
    @discord.app_commands.choices(tier=[
        discord.app_commands.Choice(name="Traveler — Rp46k / 30 Hari", value="traveler"),
        discord.app_commands.Choice(name="Companion — Rp92k / 30 Hari", value="companion"),
        discord.app_commands.Choice(name="Scholar / Intensive — Rp350k / 30 Hari", value="intensive"),
    ])
    @discord.app_commands.guild_only()
    async def grant_member(self, interaction: discord.Interaction, user: discord.User, tier: str):
        """Slash command administrator untuk memberikan hak akses premium secara manual."""
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not await self._check_can_manage(member):
            return await interaction.followup.send("❌ Anda tidak memiliki wewenang administratif yang cukup untuk menggunakan perintah ini!", ephemeral=True)

        if tier == "trial":
            return await interaction.followup.send(
                "❌ Untuk menyematkan masa uji coba, silakan gunakan perintah khusus `/admin grant-trial`.",
                ephemeral=True
            )

        if not get_tier_info(tier):
            return await interaction.followup.send(f"❌ Tingkatan (Tier) `{tier}` tidak terdaftar di sistem!", ephemeral=True)

        async with MEMBERSHIP_LOCK:
            try:
                result = await _do_grant(self.bot, interaction.guild, user, tier, interaction.user.id)
            except Exception as e:
                _log.exception("Gagal mengeksekusi pemberian keanggotaan manual")
                return await interaction.followup.send(f"❌ Kegagalan sistem: {e}", ephemeral=True)

        tier_info = result["tier_info"]
        is_lifetime = result["is_lifetime"]
        point_count = result["point_count"]
        expires_at = result["expires_at"]
        expire_ts = int(expires_at.timestamp())

        # Kirimkan pemberitahuan resmi secara pribadi ke DM penerima
        if is_lifetime:
            dm_embed = discord.Embed(
                title="👑 Keanggotaan Seumur Hidup Aktif — LIFETIME 👑",
                description=(
                    f"Selamat! Anda telah resmi mengumpulkan **{LIFETIME_THRESHOLD} poin kumulatif** "
                    f"dan dianugerahi kasta agung **{ROLE_CFG['lifetime']['name']}** secara permanen.\n\n"
                    f"Anda tidak perlu lagi memperbarui masa aktif keanggotaan premium ke depannya. Terima kasih banyak atas dukungan tulus Anda bagi Kerajaan Kotabi! 🎉"
                ),
                color=discord.Color.gold()
            )
            dm_embed.add_field(name="Tingkat (Tier) Saat Ini", value=tier_info["name"], inline=True)
            dm_embed.add_field(name="Progres Seumur Hidup", value=f"{point_count}/{LIFETIME_THRESHOLD} poin ✅", inline=True)
        else:
            dm_embed = discord.Embed(
                title="✅ Hak Akses VIP Kerajaan Berhasil Aktif",
                description=f"Selamat! Anda kini resmi menyandang status sebagai anggota premium **{tier_info['name']}**.",
                color=discord.Color.green()
            )
            dm_embed.add_field(name="Tingkat (Tier)", value=tier_info["name"], inline=True)
            dm_embed.add_field(name="Masa Berlaku Hingga", value=f"<t:{expire_ts}:F>", inline=True)
            dm_embed.add_field(
                name="Progres Seumur Hidup (Lifetime Progress)",
                value=fmt_progress(point_count),
                inline=False
            )

        await send_dm_safe(user.id, self.bot, dm_embed)


        # Kirimkan log pengumuman resmi ke saluran kehormatan istana
        ch = get_announcement_channel(interaction.guild)
        if ch:
            ann = discord.Embed(
                title="🎉 Warga Kehormatan Baru" + (" 👑 LIFETIME MEMBER" if is_lifetime else ""),
                description=f"{user.mention} kini resmi menyandang status premium sebagai **{tier_info['name']}**!",
                color=discord.Color.gold() if is_lifetime else discord.Color.green()
            )
            ann.set_thumbnail(url=user.display_avatar.url)
            if is_lifetime:
                ann.add_field(name="Status Agung", value=f"{ROLE_CFG['lifetime']['name']} ✅", inline=False)
            try:
                await ch.send(embed=ann)
            except discord.Forbidden:
                pass

        reply = (
            f"✅ Hak akses VIP berhasil disematkan kepada {user.mention} ({tier_info['name']})!\n"
            f"Progres Seumur Hidup: **{point_count}/{LIFETIME_THRESHOLD} poin**\n"
        )
        if is_lifetime:
            reply += "👑 Warga ini sekarang resmi menjadi **ANGGOTA SEUMUR HIDUP**!"
        else:
            reply += f"Masa Aktif Berakhir: <t:{expire_ts}:R>"

        await interaction.followup.send(reply, ephemeral=True)


    @admin_group.command(name="grant-trial", description="Berikan hak akses uji coba (Trial) premium selama 7 hari (0 poin).")
    @discord.app_commands.describe(user="Pilih warga yang ingin diberikan masa uji coba.")
    @discord.app_commands.guild_only()
    async def grant_trial(self, interaction: discord.Interaction, user: discord.User):
        """Slash command administrator untuk memberikan hak akses uji coba gratis."""
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not await self._check_can_manage(member):
            return await interaction.followup.send("❌ Anda tidak memiliki wewenang administratif yang cukup untuk menggunakan perintah ini!", ephemeral=True)

        existing = await self.bot.GET_ONE(GET_MEMBERSHIP, (interaction.guild_id, user.id))
        if existing:
            existing_active = bool(existing[4])
            existing_expires = datetime.fromisoformat(existing[3])
            existing_lifetime = bool(existing[8])
            now = utcnow().replace(tzinfo=None)

            if existing_lifetime:
                return await interaction.followup.send(
                    f"❌ {user.mention} sudah berstatus sebagai **Anggota Seumur Hidup (Lifetime)**.",
                    ephemeral=True
                )

            if existing_active and existing_expires > now:
                return await interaction.followup.send(
                    f"❌ {user.mention} masih memiliki masa keanggotaan aktif. Uji coba (Trial) tidak dapat diberikan.",
                    ephemeral=True
                )

        allowed, reason = await can_take_trial(self.bot, interaction.guild_id, user.id)
        if not allowed:
            return await interaction.followup.send(f"❌ {reason}", ephemeral=True)

        async with MEMBERSHIP_LOCK:
            try:
                result = await _do_grant(self.bot, interaction.guild, user, "trial", interaction.user.id)
            except Exception as e:
                _log.exception("Gagal memberikan masa uji coba manual")
                return await interaction.followup.send(f"❌ Kegagalan sistem: {e}", ephemeral=True)

        tier_info = result["tier_info"]
        expires_at = result["expires_at"]
        expire_ts = int(expires_at.timestamp())

        dm_embed = discord.Embed(
            title="🎁 Hak Uji Coba (Trial) Premium Diaktifkan",
            description=(
                f"Selamat! Anda resmi mendapatkan akses uji coba **{tier_info['name']}** gratis selama **7 hari**.\n\n"
                "Selama masa uji coba, Anda dipersilakan mencoba seluruh fitur VIP premium Kerajaan Kotabi, seperti pencatatan kemajuan (*immersion log*), "
                "ujian kenaikan kasta (*quiz rank-up*), perpustakaan, kamus pintar, dan saluran khusus member lounge!"
            ),
            color=discord.Color.blurple()
        )
        dm_embed.add_field(name="Masa Berlaku Berakhir", value=f"<t:{expire_ts}:F>", inline=True)
        dm_embed.add_field(name="Progres Seumur Hidup", value="0 poin (Kesempatan masa uji coba gratis tidak menambahkan poin seumur hidup)", inline=False)
        await send_dm_safe(user.id, self.bot, dm_embed)

        await interaction.followup.send(
            f"✅ Hak uji coba gratis (Trial) berhasil diberikan kepada {user.mention}!\nMasa berlaku berakhir pada: <t:{expire_ts}:R>",
            ephemeral=True
        )


    @admin_group.command(name="grant-batch", description="Berikan hak akses keanggotaan VIP kepada banyak warga sekaligus (massal).")
    @discord.app_commands.describe(
        users="Sebutkan (mention) warga yang ditargetkan (contoh: @Warga1 @Warga2 ...)",
        tier="Tingkat (tier) keanggotaan VIP."
    )
    @discord.app_commands.choices(tier=[
        discord.app_commands.Choice(name="Trial — Masa uji coba 7 Hari", value="trial"),
        discord.app_commands.Choice(name="Traveler — Rp46k / 30 Hari", value="traveler"),
        discord.app_commands.Choice(name="Companion — Rp92k / 30 Hari", value="companion"),
        discord.app_commands.Choice(name="Scholar / Intensive — Rp350k / 30 Hari", value="intensive"),
    ])
    @discord.app_commands.guild_only()
    async def grant_batch(self, interaction: discord.Interaction, users: str, tier: str):
        """Slash command administrator untuk memproses hak akses secara beruntun (batch)."""
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not await self._check_can_manage(member):
            return await interaction.followup.send("❌ Anda tidak memiliki wewenang administratif yang cukup untuk menggunakan perintah ini!", ephemeral=True)

        if not get_tier_info(tier):
            return await interaction.followup.send("❌ Tingkatan (Tier) yang Anda tentukan tidak sah!", ephemeral=True)

        ids = re.findall(r"<@!?(\d+)>", users)
        if not ids:
            return await interaction.followup.send("❌ Tidak ditemukan penyebutan (@User) warga yang valid di dalam parameter input!", ephemeral=True)

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
                        # Blokir penumpukan uji coba jika keanggotaan aktif/lifetime masih ada
                        existing = await self.bot.GET_ONE(GET_MEMBERSHIP, (interaction.guild_id, uid))
                        if existing:
                            existing_active = bool(existing[4])
                            existing_expires = datetime.fromisoformat(existing[3])
                            existing_lifetime = bool(existing[8])
                            now = utcnow().replace(tzinfo=None)

                            if existing_lifetime:
                                fail_list.append(f"<@{uid}> — sudah menyandang keanggotaan Seumur Hidup")
                                continue

                            if existing_active and existing_expires > now:
                                fail_list.append(f"<@{uid}> — masih memiliki masa aktif premium")
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
                            title="👑 Keanggotaan Seumur Hidup Aktif — LIFETIME 👑",
                            description=(
                                f"Selamat! Anda telah resmi mengumpulkan **{LIFETIME_THRESHOLD} poin kumulatif** "
                                f"dan sekarang berhak menyandang gelar **{ROLE_CFG['lifetime']['name']}** secara permanen! 🎉"
                            ),
                            color=discord.Color.gold()
                        )
                        dm_embed.add_field(
                            name="Progres Seumur Hidup",
                            value=f"{point_count}/{LIFETIME_THRESHOLD} poin ✅",
                            inline=True
                        )

                    elif tier == "trial":
                        dm_embed = discord.Embed(
                            title="🎁 Hak Uji Coba (Trial) Premium Diaktifkan",
                            description=(
                                f"Selamat! Anda resmi mendapatkan akses uji coba **{tier_info['name']}** gratis selama **7 hari**.\n\n"
                                "Nikmati seluruh fitur VIP premium Kerajaan Kotabi, seperti pencatatan kemajuan, kuis kenaikan pangkat, kamus pintar, dan saluran member lounge!"
                            ),
                            color=discord.Color.blurple()
                        )
                        dm_embed.add_field(name="Masa Berlaku Berakhir", value=f"<t:{expire_ts}:F>", inline=True)
                        dm_embed.add_field(
                            name="Progres Seumur Hidup",
                            value="0 poin (Kesempatan masa uji coba gratis tidak menambah poin seumur hidup)",
                            inline=False
                        )

                    else:
                        dm_embed = discord.Embed(
                            title="✅ Hak Akses VIP Kerajaan Berhasil Aktif",
                            description=f"Selamat! Anda kini resmi menyandang status sebagai anggota premium **{tier_info['name']}**.",
                            color=discord.Color.green()
                        )
                        dm_embed.add_field(name="Masa Berlaku Berakhir", value=f"<t:{expire_ts}:F>", inline=True)
                        dm_embed.add_field(
                            name="Progres Seumur Hidup",
                            value=fmt_progress_short(point_count),
                            inline=False
                        )

                    await send_dm_safe(uid, self.bot, dm_embed)

                    if is_lifetime:
                        label = f"{target.name} 👑 LIFETIME"
                    elif tier == "trial":
                        label = f"{target.name} • Trial 7 Hari"
                    else:
                        label = f"{target.name} • {point_count}/{LIFETIME_THRESHOLD} poin"

                    success_list.append(label)

                except discord.NotFound:
                    fail_list.append(f"<@{uid}> — warga tidak ditemukan")
                except Exception as e:
                    fail_list.append(f"<@{uid}> — {e}")
                    _log.exception("Kegagalan memproses pemberian hak batch pada uid %s", uid)

        tier_info = get_tier_info(tier)

        if success_list:
            ch = get_announcement_channel(interaction.guild)
            if ch:
                ann = discord.Embed(
                    title=f"🎉 {len(success_list)} Warga Kehormatan Baru",
                    color=discord.Color.blurple() if tier == "trial" else discord.Color.green()
                )
                ann.add_field(name="Tingkat (Tier)", value=tier_info["name"], inline=True)
                ann.add_field(
                    name="Daftar Warga",
                    value="\n".join(f"• {n}" for n in success_list)[:1024],
                    inline=False
                )
                try:
                    await ch.send(embed=ann)
                except discord.Forbidden:
                    pass

        summary = discord.Embed(title="✅ Proses Pemberian Hak Massal Selesai", color=discord.Color.green())
        if success_list:
            summary.add_field(
                name=f"Berhasil Disematkan ({len(success_list)})",
                value="\n".join(f"✅ {n}" for n in success_list)[:1024],
                inline=False
            )
        if fail_list:
            summary.add_field(
                name=f"Gagal Diproses ({len(fail_list)})",
                value="\n".join(f"❌ {n}" for n in fail_list)[:1024],
                inline=False
            )
        summary.add_field(name="Tingkat (Tier)", value=tier_info["name"], inline=True)
        summary.add_field(name="Rasio Penyelesaian", value=f"{len(success_list)}/{len(ids)} warga", inline=True)
        await interaction.followup.send(embed=summary, ephemeral=True)


    @admin_group.command(name="revoke-member", description="Cabut paksa hak akses VIP dari seorang warga (tidak berlaku untuk Lifetime).")
    @discord.app_commands.describe(user="Pilih warga yang ingin dicabut status premiumnya.")
    @discord.app_commands.guild_only()
    async def revoke_member(self, interaction: discord.Interaction, user: discord.User):
        """Slash command administrator untuk menonaktifkan status premium seorang warga."""
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not await self._check_can_manage(member):
            return await interaction.followup.send("❌ Anda tidak memiliki wewenang administratif yang cukup untuk menggunakan perintah ini!", ephemeral=True)

        async with MEMBERSHIP_LOCK:
            row = await self.bot.GET_ONE(GET_MEMBERSHIP, (interaction.guild_id, user.id))
            if not row:
                return await interaction.followup.send(f"❌ {user.mention} tidak terdaftar memiliki status membership aktif saat ini.", ephemeral=True)

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
                    f"❌ {user.mention} adalah **Lifetime Member** (Anggota Seumur Hidup) — status agung ini tidak dapat dicabut paksa.",
                    ephemeral=True
                )

            if not active:
                return await interaction.followup.send(
                    f"❌ Status keanggotaan {user.mention} sudah tidak aktif sebelumnya.",
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
                (interaction.guild_id, user.id, "revoke", tier, interaction.user.id, now.isoformat(), "Dicabut secara manual oleh pengelola")
            )

            embed = discord.Embed(
                title="⚠️ Status Keanggotaan VIP Dicabut",
                description="Status keanggotaan premium Anda telah resmi diakhiri dan peran khusus terkait telah dicabut dari profil Anda.",
                color=discord.Color.red()
            )
            embed.add_field(
                name="Informasi Tambahan",
                value=f"Progres keanggotaan seumur hidup Anda (**{point_count}/{LIFETIME_THRESHOLD} poin**) akan tetap tersimpan aman di arsip database kerajaan.",
                inline=False
            )
            await send_dm_safe(user.id, self.bot, embed)

            await interaction.followup.send(f"✅ Status keanggotaan {user.mention} telah berhasil dicabut secara permanen.", ephemeral=True)


    @admin_group.command(name="check-member", description="Periksa rincian kartu identitas dan masa aktif keanggotaan premium seorang warga.")
    @discord.app_commands.describe(user="Pilih warga yang ingin diperiksa rincian datanya.")
    @discord.app_commands.guild_only()
    async def check_member(self, interaction: discord.Interaction, user: discord.User):
        """Slash command administrator untuk memantau detail kepemilikan VIP warga."""
        await interaction.response.defer(ephemeral=True)

        row = await self.bot.GET_ONE(GET_MEMBERSHIP, (interaction.guild_id, user.id))
        if not row:
            return await interaction.followup.send(f"❌ {user.mention} saat ini berstatus sebagai Warga Biasa (Gratis).", ephemeral=True)

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
            status_str = "👑 LIFETIME MEMBER (Seumur Hidup)"
            color = discord.Color.gold()
        elif active:
            color = discord.Color.green()
            if expires_dt > utcnow().replace(tzinfo=None):
                status_str = "✅ Aktif"
            else:
                status_str = "⚠️ Kedaluwarsa (Menunggu penyapuan sistem latar belakang)"
        else:
            status_str = "❌ Tidak Aktif"
            color = discord.Color.red()

        embed = discord.Embed(title=f"Status Keanggotaan VIP — {user.name}", color=color)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Status Saat Ini", value=status_str, inline=False)
        embed.add_field(name="Tingkat (Tier)", value=tier_info.get("name", tier), inline=True)
        embed.add_field(name="Akses Diberikan Pada", value=f"<t:{granted_ts}:F>", inline=True)

        if is_lifetime:
            embed.add_field(name="Kedaluwarsa Pada", value="Tidak pernah berakhir ♾️", inline=True)
            embed.add_field(name="Akumulasi Poin", value=f"{point_count}/{LIFETIME_THRESHOLD} ✅", inline=True)
            embed.add_field(name="Jumlah Transaksi Terdaftar", value=f"{payment_count} kali", inline=True)
            embed.add_field(name="Peran Kehormatan", value=ROLE_CFG["lifetime"]["name"], inline=False)
        else:
            embed.add_field(name="Kedaluwarsa Pada", value=f"<t:{expires_ts}:F>", inline=True)
            embed.add_field(name="Sisa Masa Aktif", value=f"<t:{expires_ts}:R>", inline=True)
            embed.add_field(
                name="Progres Seumur Hidup",
                value=fmt_progress(point_count),
                inline=False
            )
            embed.add_field(name="Jumlah Transaksi Terdaftar", value=f"{payment_count} kali", inline=True)

        if granted_by:
            granter = self.bot.get_user(granted_by)
            embed.add_field(
                name="Diberikan Oleh",
                value=granter.mention if granter else f"User {granted_by}",
                inline=True
            )

        await interaction.followup.send(embed=embed, ephemeral=True)


    @admin_group.command(name="membership-history", description="Tampilkan arsip riwayat pemberian atau pencabutan keanggotaan VIP.")
    @discord.app_commands.describe(user="Saring pencarian arsip riwayat berdasarkan warga tertentu (opsional).")
    @discord.app_commands.guild_only()
    async def membership_history(self, interaction: discord.Interaction, user: discord.User = None):
        """Slash command administrator untuk menampilkan daftar mutasi keanggotaan."""
        await interaction.response.defer(ephemeral=True)

        uid = user.id if user else None
        results = await self.bot.GET(GET_HISTORY, (interaction.guild_id, uid, uid))

        if not results:
            return await interaction.followup.send("Arsip riwayat transaksi atau perubahan keanggotaan tidak ditemukan.", ephemeral=True)

        embed = discord.Embed(title="Arsip Riwayat Keanggotaan Kerajaan", color=discord.Color.blue())

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
                uname = f"Warga ID {user_id}"

            try:
                gu = (
                    self.bot.get_user(granted_by) or await self.bot.fetch_user(granted_by)
                    if granted_by else None
                )
                gname = gu.name if gu else "Sistem Istana"
            except Exception:
                gname = "Sistem Istana"

            tier_name = get_tier_info(tier).get("name", tier) if tier else "—"
            val = f"{emoji} **{action.upper()}** — {tier_name}\n<t:{ts}:F>\nDiproses Oleh: {gname}"
            if reason:
                val += f"\n_Keterangan: {reason}_"

            embed.add_field(name=uname, value=val, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @admin_group.command(name="membership-purge-history", description="Bersihkan seluruh arsip riwayat keanggotaan seorang warga secara permanen.")
    @discord.app_commands.describe(user="Warga yang ingin dibersihkan arsip riwayat keanggotaannya.")
    @discord.app_commands.guild_only()
    async def membership_purge_history(self, interaction: discord.Interaction, user: discord.User):
        """Slash command administrator khusus untuk menghapus data riwayat."""
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("❌ Hanya administrator utama kerajaan yang diizinkan membersihkan arsip riwayat secara permanen!", ephemeral=True)

        await self.bot.RUN(PURGE_HISTORY, (interaction.guild_id, user.id))
        await interaction.followup.send(f"🧹 Seluruh arsip riwayat keanggotaan {user.mention} telah dibersihkan secara permanen dari database.", ephemeral=True)


    @tasks.loop(hours=24)
    async def membership_expiry_check(self):
        """Tugas latar belakang asinkron harian untuk memantau status berakhirnya masa aktif VIP."""
        try:
            guild = self.bot.get_guild(self.guild_id)
            if not guild:
                return

            now = utcnow()
            grace_period = MEMBERSHIP_CFG["grace_period_days"]
            warn_threshold = (now + timedelta(days=grace_period)).isoformat()


            # ================================================================
            # FASE 0 — PENYELESAIAN MASA UJI COBA (TRIAL EXPIRED)
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
                        "Pencabutan otomatis - masa uji coba (trial) gratis selesai",
                    )
                )

                embed = discord.Embed(
                    title="⏰ Masa Uji Coba (Trial) Anda Telah Selesai",
                    description=(
                        "Masa peninjauan premium 7 hari Anda telah berakhir dan akses khusus dicabut.\n\n"
                        "Tertarik untuk melanjutkan petualangan belajar Anda di Kerajaan Kotabi? Silakan mendaftar ke kasta premium:\n"
                        "🎒 **Traveler** — Rp46.000/bulan\n"
                        "🤝 **Companion** — Rp92.000/bulan (Akses ekosistem penuh)\n"
                        "📚 **Scholar** — Rp350.000/bulan (Termasuk bimbingan belajar intensif)\n\n"
                        "Hubungi staf istana untuk melakukan pendaftaran kasta VIP! 🙇‍♂️"
                    ),
                    color=discord.Color.orange()
                )
                await send_dm_safe(user_id, self.bot, embed)
                _log.info("Berhasil mencabut otomatis masa uji coba (trial) kadaluwarsa milik %s", user_id)


            # ================================================================
            # FASE 1 — PERINGATAN H-3 SEBELUM EXPIRED (PAID MEMBER ONLY)
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
                    title="⏰ Peringatan Masa Aktif Keanggotaan",
                    description=f"Status keanggotaan premium Anda akan segera berakhir dalam waktu **{grace_period} hari**.",
                    color=discord.Color.orange()
                )
                embed.add_field(name="Tingkat (Tier)", value=tier_info.get("name", tier), inline=True)
                embed.add_field(name="Kedaluwarsa Pada", value=f"<t:{expires_ts}:F>", inline=True)
                embed.add_field(name="Tindakan Selanjutnya", value="Segera hubungi staf istana untuk memperpanjang keanggotaan Anda.", inline=False)

                row = await self.bot.GET_ONE(GET_MEMBERSHIP, (self.guild_id, user_id))
                if row:
                    point_count = row[7]
                    embed.add_field(
                        name="Progres Seumur Hidup",
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
                        f"Peringatan otomatis {grace_period} hari sebelum berakhir",
                    )
                )
                _log.info("Berhasil mengirimkan peringatan masa berakhir ke user %s", user_id)


            # ================================================================
            # FASE 2 — KEDALUWARSA TOTAL (EXPIRED PAID MEMBER)
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
                        "Pencabutan otomatis - masa aktif keanggotaan kedaluwarsa",
                    )
                )

                embed = discord.Embed(
                    title="⚠️ Masa Aktif Keanggotaan Berakhir",
                    description="Masa keanggotaan premium Anda telah berakhir dan peran khusus terkait telah dicabut.",
                    color=discord.Color.red()
                )
                embed.add_field(name="Langkah Selanjutnya", value="Silakan hubungi staf istana jika Anda ingin melakukan pembaruan masa aktif.", inline=False)

                row = await self.bot.GET_ONE(GET_MEMBERSHIP, (self.guild_id, user_id))
                if row:
                    point_count = row[7]
                    remaining = max(0, LIFETIME_THRESHOLD - point_count)
                    embed.add_field(
                        name="Progres Seumur Hidup",
                        value=f"Saat ini progres Anda telah mencapai **{point_count}/{LIFETIME_THRESHOLD} poin**. Hanya butuh **{remaining} poin** lagi untuk meraih gelar Keanggotaan Seumur Hidup!",
                        inline=False
                    )

                await send_dm_safe(user_id, self.bot, embed)
                _log.info("Berhasil menonaktifkan otomatis status keanggotaan kedaluwarsa untuk %s", user_id)

        except Exception as e:
            _log.exception("Terjadi kesalahan teknis saat menjalankan tugas asinkron pemeriksaan masa kedaluwarsa: %s", e)

    @membership_expiry_check.before_loop
    async def before_expiry_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: KotabiBot):
    await bot.add_cog(Membership(bot))