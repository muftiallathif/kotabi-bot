"""
cogs/membership_purchase.py — Purchase Flow v1
===============================================
Menangani alur pembelian membership dari sisi user dan staff.

Flow:
    User /subscribe
        ↓
    Pilih produk + quantity
        ↓
    Konfirmasi ringkasan + harga
        ↓
    Order dibuat (status: pending)
        ↓
    Embed review dikirim ke channel staff
        ↓
    Admin klik Approve / Reject / Cancel
        ↓
    GrantEngine.apply() dipanggil
        ↓
    Discord role diupdate + DM ke user

Dipisah dari cogs/membership.py supaya tidak melebihi 400 baris.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

import discord
import yaml
from discord.ext import commands
from discord.utils import utcnow

from core.bot import KotabiBot
from lib.grants.engine import GrantEngine
from lib.membership.models import Order
from lib.membership.product_loader import ProductLoader
from lib.membership.repository import MembershipRepository
from lib.membership.role_resolver import RoleResolver
from lib.config import get_lifetime_threshold
from lib.membership.service import MembershipService

_log = logging.getLogger("bot.membership_purchase")

# ============================================================
# KONFIGURASI
# ============================================================

_MEMBERSHIP_SETTINGS_PATH = (
    os.getenv("ALT_MEMBERSHIP_SETTINGS_PATH") or "config/membership_settings.yml"
)
with open(_MEMBERSHIP_SETTINGS_PATH, "r", encoding="utf-8") as _f:
    _membership_settings = yaml.safe_load(_f)

_MEMBERSHIP_CFG  = _membership_settings["membership"]
GUILD_ID         = _MEMBERSHIP_CFG["guild_id"]
ANNOUNCEMENT_CH  = _MEMBERSHIP_CFG["announcement_channel_id"]

# Channel khusus untuk embed review order (bisa sama dengan staff-chat)
# Tambahkan ke membership_settings.yml jika perlu channel berbeda
ORDER_REVIEW_CH = _MEMBERSHIP_CFG.get(
    "order_review_channel_id",
    _MEMBERSHIP_CFG.get("announcement_channel_id")
)

PURCHASE_LOCK = asyncio.Lock()


# ============================================================
# HELPER
# ============================================================

def _fmt_price(amount: int) -> str:
    return f"Rp{amount:,}".replace(",", ".")


def _fmt_progress(point_count: int) -> str:
    threshold = get_lifetime_threshold()
    remaining = max(0, threshold - point_count)
    return f"{point_count}/{threshold} poin ({remaining} poin lagi)"


async def _send_dm(user_id: int, bot: KotabiBot, embed: discord.Embed) -> bool:
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if not user.dm_channel:
            await user.create_dm()
        await user.send(embed=embed)
        return True
    except (discord.Forbidden, discord.NotFound):
        _log.warning("Tidak bisa DM user %s", user_id)
        return False


def _build_order_embed(
    order: Order,
    user: discord.User,
    status: str = "pending",
) -> discord.Embed:
    """Buat embed untuk review order di channel staff."""
    color_map = {
        "pending":  discord.Color.yellow(),
        "approved": discord.Color.green(),
        "rejected": discord.Color.red(),
        "cancelled": discord.Color.light_grey(),
    }
    status_map = {
        "pending":   "⏳ Menunggu Persetujuan",
        "approved":  "✅ Disetujui",
        "rejected":  "❌ Ditolak",
        "cancelled": "🚫 Dibatalkan",
    }

    embed = discord.Embed(
        title=f"🛒 Order #{order.order_id} — {order.product_name}",
        color=color_map.get(status, discord.Color.blurple()),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="User",    value=f"{user.mention} (`{user.id}`)", inline=True)
    embed.add_field(name="Produk",  value=order.product_name,              inline=True)
    embed.add_field(name="Status",  value=status_map.get(status, status),  inline=True)

    if order.quantity > 1:
        embed.add_field(name="Quantity", value=f"{order.quantity}x", inline=True)

    embed.add_field(name="Total",   value=_fmt_price(order.total_price),   inline=True)

    if order.total_duration:
        embed.add_field(name="Durasi", value=f"{order.total_duration} hari", inline=True)
    else:
        embed.add_field(name="Durasi", value="Lifetime ♾️", inline=True)

    # Grant summary
    payload = order.grant_payload
    grant_lines = []
    if "membership" in payload:
        m = payload["membership"]
        if m.get("lifetime"):
            grant_lines.append(f"Tier: **{m['tier']}** (Lifetime)")
        else:
            grant_lines.append(f"Tier: **{m['tier']}** ({m.get('duration_days', '?')} hari)")
    if "point" in payload:
        grant_lines.append(f"Poin: **+{payload['point']['amount']}**")
    if grant_lines:
        embed.add_field(name="Grant", value="\n".join(grant_lines), inline=False)

    if order.notes:
        embed.add_field(name="Catatan", value=order.notes, inline=False)

    created_ts = int(order.created_at.timestamp()) if order.created_at else 0
    embed.set_footer(text=f"Order dibuat <t:{created_ts}:F>")

    return embed


# ============================================================
# APPROVAL VIEW (tombol di embed staff)
# ============================================================

class OrderApprovalView(discord.ui.View):
    """
    View dengan tombol Approve / Reject / Cancel.
    Persistent — bisa dipakai ulang setelah bot restart
    karena order_id disimpan di custom_id.
    """

    def __init__(self, order_id: int):
        super().__init__(timeout=None)
        self.order_id = order_id

        # Set custom_id supaya persistent setelah restart
        self.approve_btn.custom_id = f"order_approve_{order_id}"
        self.reject_btn.custom_id  = f"order_reject_{order_id}"
        self.cancel_btn.custom_id  = f"order_cancel_{order_id}"

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cog: MembershipPurchase = interaction.client.get_cog("MembershipPurchase")
        if not cog:
            return await interaction.followup.send("❌ Cog tidak aktif.", ephemeral=True)
        await cog.process_approval(interaction, self.order_id, "approved")

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger)
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cog: MembershipPurchase = interaction.client.get_cog("MembershipPurchase")
        if not cog:
            return await interaction.followup.send("❌ Cog tidak aktif.", ephemeral=True)
        await cog.process_approval(interaction, self.order_id, "rejected")

    @discord.ui.button(label="🚫 Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cog: MembershipPurchase = interaction.client.get_cog("MembershipPurchase")
        if not cog:
            return await interaction.followup.send("❌ Cog tidak aktif.", ephemeral=True)
        await cog.process_approval(interaction, self.order_id, "cancelled")


# ============================================================
# KONFIRMASI VIEW (tombol di /subscribe sebelum submit)
# ============================================================

class OrderConfirmView(discord.ui.View):
    def __init__(self, cog: "MembershipPurchase", product_id: str, quantity: int, user_id: int):
        super().__init__(timeout=120)
        self.cog        = cog
        self.product_id = product_id
        self.quantity   = quantity
        self.user_id    = user_id
        self.done       = False

    @discord.ui.button(label="✅ Konfirmasi", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "❌ Bukan order kamu.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        self.done = True
        self.stop()
        await self.cog.submit_order(interaction, self.product_id, self.quantity)

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "❌ Bukan order kamu.", ephemeral=True
            )
        self.done = True
        self.stop()
        await interaction.response.edit_message(
            content="🚫 Order dibatalkan.", embed=None, view=None
        )


# ============================================================
# COG
# ============================================================

class MembershipPurchase(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot    = bot
        self.svc    = MembershipService(bot)
        self.repo   = MembershipRepository(bot)
        self.engine = GrantEngine(bot)
        self.loader = ProductLoader()

    async def cog_load(self):
        # Daftarkan persistent views untuk order yang masih pending
        # supaya tombol tetap berfungsi setelah bot restart
        pending = await self.repo.get_pending_orders(GUILD_ID)
        for order in pending:
            self.bot.add_view(OrderApprovalView(order.order_id))
        _log.info("Registered %d persistent order views", len(pending))

    # ----------------------------------------------------------
    # /subscribe
    # ----------------------------------------------------------

    @discord.app_commands.command(
        name="subscribe",
        description="Beli membership Kotabi Japanese.",
    )
    @discord.app_commands.guild_only()
    async def subscribe(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Ambil semua produk yang bisa dibeli
        products = self.loader.get_subscribable()
        if not products:
            return await interaction.followup.send(
                "❌ Tidak ada produk tersedia saat ini.", ephemeral=True
            )

        # Buat dropdown produk
        options = []
        for p in products:
            label = p.name
            if p.grant_membership and p.grant_membership.lifetime:
                desc = f"{_fmt_price(p.price)} — Lifetime"
            elif p.quantity_label:
                desc = f"{_fmt_price(p.price)}/{p.quantity_label}"
            else:
                desc = _fmt_price(p.price)
            options.append(discord.SelectOption(label=label[:100], value=p.id, description=desc[:100]))

        view     = discord.ui.View(timeout=120)
        selected = {}

        product_select = discord.ui.Select(
            placeholder="Pilih produk...",
            options=options,
        )

        async def product_callback(inter: discord.Interaction):
            if inter.user.id != interaction.user.id:
                return await inter.response.send_message("❌ Bukan order kamu.", ephemeral=True)

            product_id = product_select.values[0]
            product    = self.loader.get(product_id)
            selected["product_id"] = product_id

            # Kalau produk punya quantity, tanya quantity
            if product.quantity_label and product.max_quantity > 1:
                qty_options = [
                    discord.SelectOption(
                        label=f"{i} {product.quantity_label}",
                        value=str(i),
                        description=_fmt_price(product.price * i),
                    )
                    for i in range(product.min_quantity, product.max_quantity + 1)
                ]

                qty_select = discord.ui.Select(
                    placeholder="Pilih jumlah bulan...",
                    options=qty_options,
                )

                async def qty_callback(inter2: discord.Interaction):
                    if inter2.user.id != interaction.user.id:
                        return await inter2.response.send_message("❌ Bukan order kamu.", ephemeral=True)

                    quantity = int(qty_select.values[0])
                    await inter2.response.defer(ephemeral=True)
                    await self.show_confirmation(inter2, product_id, quantity)

                qty_select.callback = qty_callback
                qty_view = discord.ui.View(timeout=120)
                qty_view.add_item(qty_select)

                await inter.response.edit_message(
                    content=f"**{product.name}** — pilih jumlah bulan:",
                    view=qty_view,
                )
            else:
                await inter.response.defer(ephemeral=True)
                await self.show_confirmation(inter, product_id, 1)

        product_select.callback = product_callback
        view.add_item(product_select)

        await interaction.followup.send(
            "Pilih produk membership yang ingin dibeli:",
            view=view,
            ephemeral=True,
        )

    async def show_confirmation(
        self,
        interaction: discord.Interaction,
        product_id: str,
        quantity: int,
    ):
        """Tampilkan ringkasan order sebelum konfirmasi."""
        product = self.loader.get(product_id)
        if not product:
            return await interaction.followup.send(
                "❌ Produk tidak ditemukan.", ephemeral=True
            )

        payload  = product.build_grant_payload(quantity)
        duration = product.calculate_total_duration(quantity)

        embed = discord.Embed(
            title="🛒 Konfirmasi Order",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Produk",   value=product.name,           inline=True)
        embed.add_field(name="Total",    value=_fmt_price(product.price * quantity), inline=True)

        if duration:
            embed.add_field(name="Durasi", value=f"{duration} hari",  inline=True)
        else:
            embed.add_field(name="Durasi", value="Lifetime ♾️",       inline=True)

        if quantity > 1:
            embed.add_field(name="Quantity", value=f"{quantity}x {product.quantity_label}", inline=True)

        # Grant summary
        grant_lines = []
        if "membership" in payload:
            m = payload["membership"]
            if m.get("lifetime"):
                grant_lines.append(f"✅ Tier **{m['tier']}** (Lifetime)")
            else:
                grant_lines.append(f"✅ Tier **{m['tier']}** ({m.get('duration_days', '?')} hari)")
        if "point" in payload:
            grant_lines.append(f"✅ **+{payload['point']['amount']} poin** progress Patron")
        if grant_lines:
            embed.add_field(name="Yang Kamu Dapat", value="\n".join(grant_lines), inline=False)

        embed.set_footer(text="Setelah konfirmasi, order akan diproses oleh admin.")

        view = OrderConfirmView(self, product_id, quantity, interaction.user.id)

        try:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except discord.NotFound:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def submit_order(
        self,
        interaction: discord.Interaction,
        product_id: str,
        quantity: int,
    ):
        """Simpan order ke database dan kirim embed ke channel staff."""
        product = self.loader.get(product_id)
        if not product:
            return await interaction.followup.send(
                "❌ Produk tidak ditemukan.", ephemeral=True
            )

        grant_payload = product.build_grant_payload(quantity)
        total_duration = product.calculate_total_duration(quantity)

        async with PURCHASE_LOCK:
            order_id = await self.repo.create_order(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                product_key=product.id,
                product_version=product.version,
                product_name=product.name,
                price=product.price,
                quantity=quantity,
                total_duration=total_duration,
                grant_payload=grant_payload,
            )

        order = await self.repo.get_order(order_id)
        if not order:
            return await interaction.followup.send(
                "❌ Gagal membuat order. Coba lagi.", ephemeral=True
            )

        # Kirim embed ke channel staff
        guild        = interaction.guild
        review_ch    = guild.get_channel(ORDER_REVIEW_CH)
        user         = interaction.user
        order_embed  = _build_order_embed(order, user, status="pending")
        approval_view = OrderApprovalView(order_id)

        if review_ch:
            try:
                await review_ch.send(embed=order_embed, view=approval_view)
                self.bot.add_view(approval_view)
            except discord.Forbidden:
                _log.error("Tidak bisa kirim order embed ke channel %d", ORDER_REVIEW_CH)

        # Konfirmasi ke user
        await interaction.followup.send(
            f"✅ **Order #{order_id} berhasil dibuat!**\n\n"
            f"Order kamu sedang menunggu persetujuan admin.\n"
            f"Kamu akan mendapat DM setelah order diproses.\n\n"
            f"**{product.name}** — {_fmt_price(product.price * quantity)}",
            ephemeral=True,
        )

        _log.info(
            "Order #%d dibuat: user=%d product=%s qty=%d",
            order_id, interaction.user.id, product_id, quantity
        )

    # ----------------------------------------------------------
    # PROCESS APPROVAL (dipanggil dari OrderApprovalView)
    # ----------------------------------------------------------

    async def process_approval(
        self,
        interaction: discord.Interaction,
        order_id: int,
        action: str,   # approved | rejected | cancelled
    ):
        """Proses tombol approve/reject/cancel dari staff."""
        # Cek izin
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.guild_permissions.manage_guild:
            return await interaction.followup.send(
                "❌ Kamu tidak punya izin untuk ini.", ephemeral=True
            )

        order = await self.repo.get_order(order_id)
        if not order:
            return await interaction.followup.send(
                f"❌ Order #{order_id} tidak ditemukan.", ephemeral=True
            )

        if order.status != "pending":
            return await interaction.followup.send(
                f"❌ Order #{order_id} sudah berstatus **{order.status}**.", ephemeral=True
            )

        async with PURCHASE_LOCK:
            # Update status order
            await self.repo.update_order_status(
                order_id=order_id,
                status=action,
                approved_by=interaction.user.id,
            )

            if action == "approved":
                # Jalankan grant engine
                result = await self.engine.apply(
                    guild_id=order.guild_id,
                    user_id=order.user_id,
                    grant_payload=order.grant_payload,
                    actor=interaction.user.id,
                    source="purchase",
                    order_id=order_id,
                )

                if not result.success:
                    # Rollback status order
                    await self.repo.update_order_status(order_id, "pending")
                    return await interaction.followup.send(
                        f"❌ Grant gagal: {result.errors}\nOrder dikembalikan ke pending.",
                        ephemeral=True,
                    )

                # Update Discord role
                guild  = interaction.guild
                member_target = guild.get_member(order.user_id)
                if member_target and result.tier:
                    resolver = RoleResolver(guild)
                    try:
                        await resolver.apply_tier(member_target, result.tier)
                    except Exception as e:
                        _log.error("Gagal apply role ke %d: %s", order.user_id, e)

                # Announcement
                ann_ch = guild.get_channel(ANNOUNCEMENT_CH)
                if ann_ch:
                    try:
                        user_obj = self.bot.get_user(order.user_id) or await self.bot.fetch_user(order.user_id)
                        ann = discord.Embed(
                            title="🎉 Member Baru" + (" 👑 LIFETIME" if result.is_lifetime else ""),
                            description=f"{user_obj.mention} mendapat **{order.product_name}**",
                            color=discord.Color.gold() if result.is_lifetime else discord.Color.green(),
                        )
                        ann.set_thumbnail(url=user_obj.display_avatar.url)
                        await ann_ch.send(embed=ann)
                    except Exception:
                        pass

                # DM ke user
                user_obj = self.bot.get_user(order.user_id) or await self.bot.fetch_user(order.user_id)
                if result.just_became_lifetime:
                    dm_embed = discord.Embed(
                        title="✅ Order Disetujui — LIFETIME 👑",
                        description=(
                            f"Order **{order.product_name}** kamu telah disetujui!\n\n"
                            f"Selamat! Kamu telah mencapai **{get_lifetime_threshold()} poin** "
                            f"dan sekarang menjadi **Patron** selamanya! 🎉"
                        ),
                        color=discord.Color.gold(),
                    )
                else:
                    expires_ts = int(result.membership.expires_at.timestamp()) if (result.membership and result.membership.expires_at) else 0
                    dm_embed = discord.Embed(
                        title="✅ Order Disetujui",
                        description=f"Order **{order.product_name}** kamu telah disetujui!",
                        color=discord.Color.green(),
                    )
                    if expires_ts:
                        dm_embed.add_field(name="Aktif hingga", value=f"<t:{expires_ts}:F>", inline=True)
                    dm_embed.add_field(
                        name="Progress Patron",
                        value=_fmt_progress(result.point_after),
                        inline=False,
                    )
                dm_embed.add_field(name="Order ID", value=f"#{order_id}", inline=True)
                await _send_dm(order.user_id, self.bot, dm_embed)

            elif action == "rejected":
                # DM ke user
                dm_embed = discord.Embed(
                    title="❌ Order Ditolak",
                    description=f"Order **{order.product_name}** kamu ditolak oleh admin.",
                    color=discord.Color.red(),
                )
                dm_embed.add_field(name="Order ID", value=f"#{order_id}", inline=True)
                dm_embed.add_field(
                    name="Info",
                    value="Hubungi admin jika ada pertanyaan.",
                    inline=False,
                )
                await _send_dm(order.user_id, self.bot, dm_embed)

            elif action == "cancelled":
                # DM ke user
                dm_embed = discord.Embed(
                    title="🚫 Order Dibatalkan",
                    description=f"Order **{order.product_name}** kamu telah dibatalkan.",
                    color=discord.Color.light_grey(),
                )
                dm_embed.add_field(name="Order ID", value=f"#{order_id}", inline=True)
                await _send_dm(order.user_id, self.bot, dm_embed)

        # Update embed di channel staff
        try:
            user_obj   = self.bot.get_user(order.user_id) or await self.bot.fetch_user(order.user_id)
            new_embed  = _build_order_embed(order, user_obj, status=action)
            # Disable semua tombol
            disabled_view = discord.ui.View()
            await interaction.message.edit(embed=new_embed, view=disabled_view)
        except Exception as e:
            _log.error("Gagal update embed order #%d: %s", order_id, e)

        action_str = {"approved": "✅ Disetujui", "rejected": "❌ Ditolak", "cancelled": "🚫 Dibatalkan"}
        await interaction.followup.send(
            f"Order #{order_id} — **{action_str.get(action, action)}**",
            ephemeral=True,
        )

        _log.info(
            "Order #%d %s oleh %s (%d)",
            order_id, action, interaction.user.name, interaction.user.id
        )

    # ----------------------------------------------------------
    # /orders — lihat daftar order pending (staff)
    # ----------------------------------------------------------

    @discord.app_commands.command(
        name="orders",
        description="Lihat daftar order membership yang menunggu persetujuan (Staff).",
    )
    @discord.app_commands.default_permissions(manage_guild=True)
    @discord.app_commands.guild_only()
    async def orders(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        pending = await self.repo.get_pending_orders(interaction.guild_id)
        if not pending:
            return await interaction.followup.send(
                "✅ Tidak ada order yang menunggu persetujuan.", ephemeral=True
            )

        embed = discord.Embed(
            title=f"📋 Order Pending ({len(pending)})",
            color=discord.Color.yellow(),
        )
        for order in pending[:10]:
            created_ts = int(order.created_at.timestamp()) if order.created_at else 0
            embed.add_field(
                name=f"#{order.order_id} — {order.product_name}",
                value=(
                    f"User: <@{order.user_id}>\n"
                    f"Total: {_fmt_price(order.total_price)}\n"
                    f"Dibuat: <t:{created_ts}:R>"
                ),
                inline=False,
            )

        if len(pending) > 10:
            embed.set_footer(text=f"Menampilkan 10 dari {len(pending)} order.")

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ----------------------------------------------------------
    # /my_orders — user lihat order sendiri
    # ----------------------------------------------------------

    @discord.app_commands.command(
        name="my_orders",
        description="Lihat riwayat order membership kamu.",
    )
    @discord.app_commands.guild_only()
    async def my_orders(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        orders = await self.repo.get_user_orders(
            interaction.guild_id, interaction.user.id, limit=5
        )
        if not orders:
            return await interaction.followup.send(
                "Kamu belum pernah membuat order.", ephemeral=True
            )

        embed = discord.Embed(
            title="📋 Riwayat Order Kamu",
            color=discord.Color.blurple(),
        )
        status_emoji = {
            "pending":   "⏳",
            "approved":  "✅",
            "rejected":  "❌",
            "cancelled": "🚫",
        }
        for order in orders:
            created_ts = int(order.created_at.timestamp()) if order.created_at else 0
            emoji      = status_emoji.get(order.status, "•")
            embed.add_field(
                name=f"#{order.order_id} — {order.product_name}",
                value=(
                    f"{emoji} **{order.status.capitalize()}**\n"
                    f"Total: {_fmt_price(order.total_price)}\n"
                    f"<t:{created_ts}:R>"
                ),
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)


# ============================================================
# SETUP
# ============================================================

async def setup(bot: KotabiBot):
    await bot.add_cog(MembershipPurchase(bot))