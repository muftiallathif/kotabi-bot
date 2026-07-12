"""
features/membership/purchase_cog.py — Purchase Flow v2 (rekening bank + bukti transfer)
=========================================================================================
Menangani alur pembelian membership dari sisi user dan staff.

Flow (sesuai KOTABI_MEMBERSHIP_SYSTEM_v3.md):
    User /subscribe
        ↓
    Pilih produk + quantity
        ↓
    Konfirmasi ringkasan + preview poin/expiry sebelum-sesudah
        ↓
    Order dibuat (status: draft) + kode unik nominal
        ↓
    Bot tampilkan detail rekening bank + total transfer (harga + kode unik)
        ↓
    User klik "Sudah Bayar" → isi bank pengirim → upload bukti transfer
        ↓
    Bot hitung perceptual hash (pHash) dari bukti
        ↓
    User klik "Konfirmasi Order" → draft -> pending
        ↓
    Embed review dikirim ke channel staff (+ warning anti-fraud kalau ada)
        ↓
    Admin klik Approve / Reject / Cancel
        ↓
    Reject → pilih alasan: "Bukti tidak valid/buram" (needs_resubmit, order sama,
             user upload ulang) atau "Lainnya" (rejected, final)
        ↓
    GrantEngine.apply() dipanggil (kalau Approve)
        ↓
    Discord role diupdate + DM ke user

Dipisah dari admin_cog.py supaya tidak melebihi 400 baris.
"""

import asyncio
import io
import logging
from datetime import datetime
from typing import Optional

import discord
import imagehash
from PIL import Image
from discord.ext import commands
from discord.utils import utcnow

from core.bot import KotabiBot
from features.membership.support.fraud_check import check_similar_proof
from features.membership.support.grants.engine import GrantEngine
from features.membership.support.models import Order
from features.membership.support.product_loader import ProductLoader
from features.membership.support.repository import MembershipRepository
from features.membership.support.role_resolver import RoleResolver
from features.membership.support.helpers import (
    send_dm as _send_dm,
    fmt_price as _fmt_price,
    fmt_progress as _fmt_progress,
)
from shared.config import (
    get_bank_account_info,
    get_lifetime_threshold,
    get_membership_guild_id,
    get_announcement_channel_id,
    get_order_review_channel_id,
)
from features.membership.support.service import MembershipService
from shared.messages import Msg

_log = logging.getLogger("bot.membership_purchase")

# ============================================================
# KONFIGURASI
# ============================================================
# guild_id & channel dibaca lewat shared/config.py (single source of truth
# untuk membership_settings.yml), bukan baca ulang YAML sendiri di file ini.

GUILD_ID        = get_membership_guild_id()
ANNOUNCEMENT_CH = get_announcement_channel_id()

# Channel khusus untuk embed review order (bisa sama dengan staff-chat).
# Fallback ke announcement_channel_id kalau order_review_channel_id belum
# diisi di YAML — logic fallback-nya sekarang ada di shared/config.py.
ORDER_REVIEW_CH = get_order_review_channel_id()

PURCHASE_LOCK = asyncio.Lock()


# ============================================================
# HELPER
# ============================================================

async def _compute_phash(attachment: discord.Attachment) -> Optional[str]:
    """Hitung perceptual hash dari gambar bukti transfer. Return None kalau gagal."""
    try:
        image_bytes = await attachment.read()
        img = Image.open(io.BytesIO(image_bytes))
        return str(imagehash.phash(img))
    except Exception as e:
        _log.warning("Gagal menghitung pHash bukti transfer: %s", e)
        return None


def _build_order_embed(
    order: Order,
    user: discord.User,
    status: str = "pending",
    fraud_matches: Optional[list[tuple[int, int]]] = None,
) -> discord.Embed:
    """Buat embed untuk review order di channel staff."""
    color_map = {
        "pending":        discord.Color.yellow(),
        "approved":       discord.Color.green(),
        "rejected":       discord.Color.red(),
        "cancelled":      discord.Color.light_grey(),
        "needs_resubmit": discord.Color.orange(),
    }
    status_map = {
        "pending":        "⏳ Menunggu Persetujuan",
        "approved":       "✅ Disetujui",
        "rejected":       "❌ Ditolak",
        "cancelled":      "🚫 Dibatalkan",
        "needs_resubmit": "🔁 Menunggu Upload Ulang",
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

    embed.add_field(name="Harga", value=_fmt_price(order.total_price), inline=True)

    if order.unique_code is not None:
        embed.add_field(name="Kode Unik", value=f"+{order.unique_code}", inline=True)

    embed.add_field(
        name="💰 Total Seharusnya",
        value=f"**{_fmt_price(order.total_price_with_unique_code)}**",
        inline=True,
    )

    if order.sender_bank:
        embed.add_field(name="Bank Pengirim", value=order.sender_bank, inline=True)

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

    if fraud_matches:
        warn_lines = [f"⚠️ Mirip dengan Order #{oid} (jarak: {dist})" for oid, dist in fraud_matches]
        embed.add_field(
            name="⚠️ Peringatan Anti-Fraud",
            value="\n".join(warn_lines) + "\n_Cek manual sebelum approve — ini bukan auto-reject._",
            inline=False,
        )

    if order.payment_proof_url:
        embed.set_image(url=order.payment_proof_url)

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
        cog: MembershipPurchase = interaction.client.get_cog("MembershipPurchase")
        if not cog:
            return await interaction.response.send_message("❌ Cog tidak aktif.", ephemeral=True)
        await interaction.response.send_message(
            f"Pilih alasan penolakan untuk Order #{self.order_id}:",
            view=RejectReasonView(cog, self.order_id),
            ephemeral=True,
        )

    @discord.ui.button(label="🚫 Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cog: MembershipPurchase = interaction.client.get_cog("MembershipPurchase")
        if not cog:
            return await interaction.followup.send("❌ Cog tidak aktif.", ephemeral=True)
        await cog.process_approval(interaction, self.order_id, "cancelled")


# ============================================================
# REJECT REASON VIEW — dropdown alasan penolakan (dua jalur)
# ============================================================

class RejectReasonView(discord.ui.View):
    def __init__(self, cog: "MembershipPurchase", order_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.order_id = order_id

    @discord.ui.select(
        placeholder="Pilih alasan penolakan...",
        options=[
            discord.SelectOption(
                label="Bukti tidak valid/buram",
                value="invalid_proof",
                description="Order TIDAK final — user diminta upload ulang bukti (kode unik sama).",
                emoji="🔁",
            ),
            discord.SelectOption(
                label="Lainnya (final)",
                value="other",
                description="Order ditolak permanen. User harus /subscribe baru kalau mau lanjut.",
                emoji="❌",
            ),
        ],
    )
    async def select_reason(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.defer(ephemeral=True)
        await self.cog.process_reject(interaction, self.order_id, select.values[0])
        self.stop()


# ============================================================
# RESUBMIT VIEW — tombol "Upload Ulang Bukti" di DM needs_resubmit
# ============================================================

class ResubmitView(discord.ui.View):
    """
    Dikirim ke DM user saat order masuk status needs_resubmit.
    Persistent (custom_id dari order_id) supaya tetap berfungsi setelah
    bot restart — didaftarkan ulang di MembershipPurchase.cog_load().
    """

    def __init__(self, cog: "MembershipPurchase", order_id: int, user_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.order_id = order_id
        self.user_id = user_id
        self.reupload.custom_id = f"order_resubmit_{order_id}"

    @discord.ui.button(label="🔄 Upload Ulang Bukti", style=discord.ButtonStyle.success)
    async def reupload(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Bukan order kamu.", ephemeral=True)
        await interaction.response.send_modal(SenderBankModal(self.cog, self.order_id))


# ============================================================
# KONFIRMASI VIEW (tombol di /subscribe sebelum lanjut ke rekening bank)
# ============================================================

class OrderConfirmView(discord.ui.View):
    def __init__(self, cog: "MembershipPurchase", product_id: str, quantity: int, user_id: int):
        super().__init__(timeout=120)
        self.cog        = cog
        self.product_id = product_id
        self.quantity   = quantity
        self.user_id    = user_id
        self.done       = False

    @discord.ui.button(label="✅ Lanjutkan", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "❌ Bukan order kamu.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        self.done = True
        self.stop()
        await self.cog.create_draft_and_show_bank_info(interaction, self.product_id, self.quantity)

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
# PAYMENT DETAIL VIEW (step rekening bank, sebelum bukti diupload)
# ============================================================

class PaymentDetailView(discord.ui.View):
    """View di step 'rekening bank' — sebelum bukti transfer diupload."""

    def __init__(self, cog: "MembershipPurchase", order_id: int, user_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.order_id = order_id
        self.user_id = user_id

    @discord.ui.button(label="✅ Sudah Bayar", style=discord.ButtonStyle.success)
    async def sudah_bayar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Bukan order kamu.", ephemeral=True)
        await interaction.response.send_modal(SenderBankModal(self.cog, self.order_id))

    @discord.ui.button(label="🚫 Batalkan", style=discord.ButtonStyle.secondary)
    async def batalkan(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Bukan order kamu.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.cog.repo.update_order_status(self.order_id, "cancelled")
        await interaction.followup.send("🚫 Order dibatalkan.", ephemeral=True)
        self.stop()


# ============================================================
# MODAL — tanya bank/e-wallet pengirim sebelum upload bukti
# ============================================================

class SenderBankModal(discord.ui.Modal, title="Info Bukti Transfer"):
    bank_name = discord.ui.TextInput(
        label="Transfer dari Bank/E-wallet apa?",
        placeholder="Contoh: BCA, Gopay, Mandiri, OVO...",
        max_length=50,
        required=True,
    )

    def __init__(self, cog: "MembershipPurchase", order_id: int):
        super().__init__()
        self.cog = cog
        self.order_id = order_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog.request_proof_upload(interaction, self.order_id, str(self.bank_name))


# ============================================================
# CONFIRM ORDER VIEW — setelah bukti transfer diupload
# ============================================================

class ConfirmOrderView(discord.ui.View):
    def __init__(self, cog: "MembershipPurchase", order_id: int, user_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.order_id = order_id
        self.user_id = user_id

    @discord.ui.button(label="✅ Konfirmasi Order", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Bukan order kamu.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.cog.finalize_order(interaction, self.order_id)
        self.stop()

    @discord.ui.button(label="📎 Upload Ulang", style=discord.ButtonStyle.secondary)
    async def reupload(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Bukan order kamu.", ephemeral=True)
        await interaction.response.send_modal(SenderBankModal(self.cog, self.order_id))
        self.stop()

    @discord.ui.button(label="🚫 Batalkan", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Bukan order kamu.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.cog.repo.update_order_status(self.order_id, "cancelled")
        await interaction.followup.send("🚫 Order dibatalkan.", ephemeral=True)
        self.stop()


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

        # Daftarkan juga ResubmitView untuk order yang masih menunggu
        # upload ulang bukti (needs_resubmit), supaya tombol "Upload Ulang
        # Bukti" di DM lama tetap berfungsi setelah bot restart.
        needs_resubmit = await self.repo.get_needs_resubmit_orders(GUILD_ID)
        for order in needs_resubmit:
            self.bot.add_view(ResubmitView(self, order.order_id, order.user_id))

        _log.info(
            "Registered %d persistent order views (%d pending, %d needs_resubmit)",
            len(pending) + len(needs_resubmit), len(pending), len(needs_resubmit)
        )

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

        existing = await self.svc.get_membership(interaction.guild_id, interaction.user.id)
        if existing and existing.is_lifetime:
            return await interaction.followup.send(Msg.PATRON_ALREADY_LIFETIME, ephemeral=True)

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
                    try:
                        await inter2.response.defer(ephemeral=True)
                    except discord.NotFound:
                        _log.warning(
                            "Interaction kedaluwarsa saat memilih quantity (user=%d, product=%s) — dilewati.",
                            inter2.user.id, product_id
                        )
                        return
                    await self.show_confirmation(inter2, product_id, quantity)

                qty_select.callback = qty_callback
                qty_view = discord.ui.View(timeout=120)
                qty_view.add_item(qty_select)

                try:
                    await inter.response.edit_message(
                        content=f"**{product.name}** — pilih jumlah bulan:",
                        view=qty_view,
                    )
                except discord.NotFound:
                    _log.warning(
                        "Interaction kedaluwarsa saat memilih produk (user=%d, product=%s) — dilewati.",
                        inter.user.id, product_id
                    )
            else:
                try:
                    await inter.response.defer(ephemeral=True)
                except discord.NotFound:
                    _log.warning(
                        "Interaction kedaluwarsa saat memilih produk (user=%d, product=%s) — dilewati.",
                        inter.user.id, product_id
                    )
                    return
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
        """Tampilkan ringkasan order + preview poin/expiry sebelum lanjut ke rekening bank."""
        product = self.loader.get(product_id)
        if not product:
            return await interaction.followup.send(
                "❌ Produk tidak ditemukan.", ephemeral=True
            )

        payload  = product.build_grant_payload(quantity)
        duration = product.calculate_total_duration(quantity)

        preview = await self.svc.preview_grant_payload(
            interaction.guild_id, interaction.user.id, payload
        )

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

        # Preview poin
        point_line = f"{preview['point_before']} → **{preview['point_after']}**"
        if preview["will_become_lifetime"]:
            point_line += " 👑 (Auto jadi Patron!)"
        embed.add_field(name="Progress Lifetime", value=point_line, inline=False)

        # Preview masa aktif
        if preview["is_lifetime"]:
            embed.add_field(name="Masa Aktif", value="♾️ Lifetime — tidak ada expiry", inline=False)
        else:
            before_str = (
                f"<t:{int(preview['expiry_before'].timestamp())}:D>"
                if preview["expiry_before"] else "—"
            )
            after_str = (
                f"<t:{int(preview['expiry_after'].timestamp())}:D>"
                if preview["expiry_after"] else "—"
            )
            embed.add_field(name="Masa Aktif", value=f"{before_str} → **{after_str}**", inline=False)

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

        embed.set_footer(text="Setelah lanjut, kamu akan diarahkan ke detail rekening pembayaran.")

        view = OrderConfirmView(self, product_id, quantity, interaction.user.id)

        try:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except discord.NotFound:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def create_draft_and_show_bank_info(
        self,
        interaction: discord.Interaction,
        product_id: str,
        quantity: int,
    ):
        """Buat order berstatus draft (atau lanjutkan draft lama), lalu tampilkan
        detail rekening + kode unik nominal."""
        product = self.loader.get(product_id)
        if not product:
            return await interaction.followup.send(
                "❌ Produk tidak ditemukan.", ephemeral=True
            )

        # Kalau user masih punya draft aktif, lanjutkan draft itu alih-alih bikin baru
        existing_draft = await self.repo.get_user_draft_order(
            interaction.guild_id, interaction.user.id
        )

        if existing_draft:
            order = existing_draft
            order_id = order.order_id
            _log.info(
                "Melanjutkan draft order lama #%d untuk user=%d",
                order_id, interaction.user.id
            )
        else:
            grant_payload = product.build_grant_payload(quantity)
            total_duration = product.calculate_total_duration(quantity)

            async with PURCHASE_LOCK:
                order_id = await self.repo.create_draft_order(
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

            _log.info(
                "Draft order #%d dibuat: user=%d product=%s qty=%d",
                order_id, interaction.user.id, product_id, quantity
            )

        bank_info = get_bank_account_info()

        embed = discord.Embed(title="🏦 Detail Rekening Pembayaran", color=discord.Color.gold())
        embed.add_field(name="Nama Penerima", value=bank_info.get("holder", "-"), inline=False)
        embed.add_field(name="Bank", value=bank_info.get("bank_name", "-"), inline=True)
        embed.add_field(name="No. Rekening", value=bank_info.get("account_number", "-"), inline=True)
        embed.add_field(name="Harga", value=_fmt_price(order.total_price), inline=True)
        embed.add_field(name="Kode Unik", value=f"+{order.unique_code}", inline=True)
        embed.add_field(
            name="Total Transfer",
            value=f"**{_fmt_price(order.total_price_with_unique_code)}**",
            inline=True,
        )
        embed.add_field(
            name="Saran",
            value="Isi keterangan transfer dengan nama Discord-mu kalau bisa.",
            inline=False,
        )
        embed.set_footer(text=f"Order #{order_id} — Draft ini kedaluwarsa otomatis dalam 24 jam.")

        await interaction.followup.send(
            embed=embed,
            view=PaymentDetailView(self, order_id, interaction.user.id),
            ephemeral=True,
        )

    async def request_proof_upload(self, interaction, order_id, sender_bank):
        try:
            dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
            await dm_channel.send(
                "📎 Silakan **kirim foto/screenshot bukti transfer** sebagai pesan **di DM ini** "
                "dalam **5 menit**.\n\n"
                "_(Kami minta lewat DM, bukan channel publik, supaya nominal/rekening di buktimu "
                "tidak terlihat warga lain.)_"
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ Bot tidak bisa DM kamu. Aktifkan \"Allow direct messages from server members\" "
                "di pengaturan privasi Discord, lalu klik **Sudah Bayar** lagi.",
                ephemeral=True,
            )

        await interaction.followup.send("📬 Cek DM kamu untuk lanjut upload bukti.", ephemeral=True)

        def check(m):
            return m.author.id == interaction.user.id and m.channel.id == dm_channel.id and m.attachments

        try:
            message = await self.bot.wait_for("message", check=check, timeout=300)
        except asyncio.TimeoutError:
            return await dm_channel.send("⏳ Waktu habis. Klik **Sudah Bayar** lagi di server untuk ulang.")

        attachment = message.attachments[0]
        if not (attachment.content_type or "").startswith("image/"):
            return await dm_channel.send("❌ Bukan gambar. Klik **Sudah Bayar** lagi untuk ulang.")

        phash = await _compute_phash(attachment)
        await self.repo.attach_payment_proof(order_id, attachment.url, sender_bank, phash)
        try:
            await message.add_reaction("✅")
        except discord.Forbidden:
            pass

        order = await self.repo.get_order(order_id)
        embed = discord.Embed(
            title="📎 Bukti Transfer Diterima",
            description=f"Order **#{order_id} — {order.product_name}**\nBank pengirim: **{sender_bank}**\n\n"
                        "Periksa gambar, lalu klik **Konfirmasi Order**.",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=attachment.url)
        await dm_channel.send(embed=embed, view=ConfirmOrderView(self, order_id, interaction.user.id))

    async def finalize_order(self, interaction: discord.Interaction, order_id: int):
        """draft/needs_resubmit -> pending, cek fraud, kirim embed review ke channel staff."""
        async with PURCHASE_LOCK:
            await self.repo.confirm_order(order_id)

        order = await self.repo.get_order(order_id)
        if not order:
            return await interaction.followup.send("❌ Order tidak ditemukan.", ephemeral=True)

        fraud_matches = []
        if order.payment_phash:
            fraud_matches = await check_similar_proof(
                self.repo, order.guild_id, order_id, order.payment_phash
            )

        guild        = self.bot.get_guild(order.guild_id)
        review_ch    = guild.get_channel(ORDER_REVIEW_CH) if guild else None
        user         = interaction.user
        order_embed  = _build_order_embed(order, user, status="pending", fraud_matches=fraud_matches)
        approval_view = OrderApprovalView(order_id)

        if review_ch:
            try:
                await review_ch.send(embed=order_embed, view=approval_view)
                self.bot.add_view(approval_view)
            except discord.Forbidden:
                _log.error("Tidak bisa kirim order embed ke channel %d", ORDER_REVIEW_CH)

        # Konfirmasi ke user
        await interaction.followup.send(
            f"✅ **Order #{order_id} dikonfirmasi!**\n\n"
            f"Order kamu sedang menunggu persetujuan admin.\n"
            f"Kamu akan mendapat DM setelah order diproses.\n\n"
            f"**{order.product_name}** — {_fmt_price(order.total_price)}",
            ephemeral=True,
        )

        _log.info(
            "Order #%d dikonfirmasi (->pending): user=%d product=%s",
            order_id, interaction.user.id, order.product_key
        )

    # ----------------------------------------------------------
    # PROCESS APPROVAL (dipanggil dari OrderApprovalView — approve/cancel)
    # ----------------------------------------------------------

    async def process_approval(
        self,
        interaction: discord.Interaction,
        order_id: int,
        action: str,   # approved | cancelled
    ):
        """Proses tombol approve/cancel dari staff. Reject ditangani terpisah
        lewat process_reject() karena punya dua jalur (needs_resubmit vs final)."""
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
            order      = await self.repo.get_order(order_id)  # refresh state
            new_embed  = _build_order_embed(order, user_obj, status=action)
            # Disable semua tombol
            disabled_view = discord.ui.View()
            await interaction.message.edit(embed=new_embed, view=disabled_view)
        except Exception as e:
            _log.error("Gagal update embed order #%d: %s", order_id, e)

        action_str = {"approved": "✅ Disetujui", "cancelled": "🚫 Dibatalkan"}
        await interaction.followup.send(
            f"Order #{order_id} — **{action_str.get(action, action)}**",
            ephemeral=True,
        )

        _log.info(
            "Order #%d %s oleh %s (%d)",
            order_id, action, interaction.user.name, interaction.user.id
        )

    # ----------------------------------------------------------
    # PROCESS REJECT (dua jalur — dipanggil dari RejectReasonView)
    # ----------------------------------------------------------

    async def process_reject(
        self,
        interaction: discord.Interaction,
        order_id: int,
        reason_type: str,   # invalid_proof | other
    ):
        """
        Jalur A ("invalid_proof"): order TIDAK final ditolak — status jadi
        needs_resubmit, user diberi tombol "Upload Ulang Bukti" (nominal &
        kode unik tetap sama, tidak perlu transfer ulang).

        Jalur B ("other"): order final ditolak (rejected). Order immutable
        setelahnya — user harus /subscribe baru kalau masih mau lanjut.
        """
        member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
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
            if reason_type == "invalid_proof":
                await self.repo.mark_needs_resubmit(
                    order_id,
                    "Bukti transfer tidak valid/buram — menunggu upload ulang dari user.",
                )
            else:
                await self.repo.update_order_status(
                    order_id=order_id,
                    status="rejected",
                    approved_by=interaction.user.id,
                    reject_reason_type="other",
                )

        order = await self.repo.get_order(order_id)  # refresh state

        if reason_type == "invalid_proof":
            dm_embed = discord.Embed(
                title="🔁 Bukti Transfer Perlu Diupload Ulang",
                description=(
                    f"Order **{order.product_name}** (#{order_id}) kamu ditolak sementara "
                    f"karena bukti transfer tidak valid/buram.\n\n"
                    f"Kamu **tidak perlu transfer ulang** — nominal dan kode unik tetap sama. "
                    f"Klik tombol di bawah untuk upload bukti yang lebih jelas."
                ),
                color=discord.Color.orange(),
            )
            dm_embed.add_field(name="Total Transfer", value=_fmt_price(order.total_price_with_unique_code), inline=True)
            dm_embed.add_field(name="Kode Unik", value=f"+{order.unique_code}", inline=True)

            try:
                user_obj = self.bot.get_user(order.user_id) or await self.bot.fetch_user(order.user_id)
                if not user_obj.dm_channel:
                    await user_obj.create_dm()
                view = ResubmitView(self, order_id, order.user_id)
                await user_obj.send(embed=dm_embed, view=view)
                self.bot.add_view(view)
            except (discord.Forbidden, discord.NotFound):
                _log.warning("Tidak bisa DM user %s untuk resubmit order #%d", order.user_id, order_id)

            status_for_embed = "needs_resubmit"
            status_label = "🔁 Perlu Upload Ulang"
        else:
            dm_embed = discord.Embed(
                title="❌ Order Ditolak",
                description=f"Order **{order.product_name}** (#{order_id}) kamu ditolak oleh admin.",
                color=discord.Color.red(),
            )
            dm_embed.add_field(
                name="Info",
                value="Hubungi admin jika ada pertanyaan, atau buat order baru lewat `/subscribe`.",
                inline=False,
            )
            await _send_dm(order.user_id, self.bot, dm_embed)

            status_for_embed = "rejected"
            status_label = "❌ Ditolak (Final)"

        # Update embed di channel staff
        try:
            user_obj = self.bot.get_user(order.user_id) or await self.bot.fetch_user(order.user_id)
            new_embed = _build_order_embed(order, user_obj, status=status_for_embed)
            disabled_view = discord.ui.View()
            await interaction.message.edit(embed=new_embed, view=disabled_view)
        except Exception as e:
            _log.error("Gagal update embed order #%d: %s", order_id, e)

        await interaction.followup.send(
            f"Order #{order_id} — **{status_label}**", ephemeral=True
        )

        _log.info(
            "Order #%d reject (%s) oleh %s (%d)",
            order_id, reason_type, interaction.user.name, interaction.user.id
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
                    f"Total Seharusnya: {_fmt_price(order.total_price_with_unique_code)}\n"
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
            "draft":           "📝",
            "pending":         "⏳",
            "needs_resubmit":  "🔁",
            "approved":        "✅",
            "rejected":        "❌",
            "cancelled":       "🚫",
        }
        for order in orders:
            created_ts = int(order.created_at.timestamp()) if order.created_at else 0
            emoji      = status_emoji.get(order.status, "•")
            embed.add_field(
                name=f"#{order.order_id} — {order.product_name}",
                value=(
                    f"{emoji} **{order.status.capitalize()}**\n"
                    f"Total: {_fmt_price(order.total_price_with_unique_code)}\n"
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