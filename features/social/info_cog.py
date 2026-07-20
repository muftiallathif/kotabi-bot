import discord
import yaml
import os
import logging
from discord.ext import commands
from typing import Optional

from shared.config import get_active_prices, get_lifetime_threshold
from shared.messages import Msg

logger = logging.getLogger("bot.info")
INFO_COMMANDS_PATH = "features/social/info_commands.yml"
info_commands = {}

# Memuat berkas konfigurasi YAML secara aman (fail-safe)
if os.path.exists(INFO_COMMANDS_PATH):
    try:
        with open(INFO_COMMANDS_PATH, "r", encoding="utf-8") as f:
            info_commands = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"❌ Gagal memuat berkas konfigurasi info: {e}")
else:
    logger.warning(f"⚠️ Berkas konfigurasi {INFO_COMMANDS_PATH} tidak ditemukan. Menggunakan kamus kosong.")


# ============================================================================
# KEY DINAMIS (PRICING_SYSTEM_REFACTOR.md Tahap 6)
# ============================================================================
# "member-reguler" TIDAK LAGI disimpan sebagai teks statis di
# info_commands.yml — digenerate di sini dari shared/config.py setiap kali
# command dipanggil, supaya harga & threshold poin Patron selalu ikut
# preset aktif + get_lifetime_threshold() sungguhan, bukan angka yang
# ditulis manual dan gampang basi (bug lama: teks lama bilang "60 poin",
# padahal membership_settings.yml sudah lama diisi point_threshold: 24 —
# sudah dibenarkan di sini karena sekarang narik langsung dari config,
# bukan angka hardcode kedua).

def _build_member_reguler_text() -> str:
    prices = get_active_prices()
    threshold = get_lifetime_threshold()
    return (
        "Paket Membership Kotabi Japanese\n\n"
        f"🎒 **Traveler** — {Msg._format_rp(prices['traveler']['monthly'])} / bulan\n"
        "• Akses immersion-log, quiz-rank-up, kamus bot, Member Area.\n\n"
        f"🤝 **Companion** — {Msg._format_rp(prices['companion']['monthly'])} / bulan\n"
        "• Semua keuntungan Traveler + akses ekosistem premium penuh.\n\n"
        f"👑 **Patron (Lifetime)** — Otomatis setelah **{threshold} poin kumulatif**, "
        f"atau beli langsung {Msg._format_rp(prices['patron'])}.\n"
        "• Akses permanen tanpa biaya tambahan selamanya.\n\n"
        "Hubungi admin untuk informasi lebih lanjut!"
    )


# Daftar key -> fungsi generator. Tambah key dinamis baru di sini kalau
# nanti ada info lain yang perlu ikut angka hidup (bukan teks statis).
DYNAMIC_INFO_BUILDERS = {
    "member-reguler": _build_member_reguler_text,
}


async def info_autocomplete(interaction: discord.Interaction, current: str):
    """Menyediakan daftar pilihan topik informasi secara otomatis saat mengetik perintah.
    Gabungan key statis (dari YAML) + key dinamis (DYNAMIC_INFO_BUILDERS)."""
    all_keys = list(info_commands.keys()) + list(DYNAMIC_INFO_BUILDERS.keys())

    if not current:
        return [discord.app_commands.Choice(name=key, value=key) for key in all_keys][:25]
    else:
        return [
            discord.app_commands.Choice(name=key, value=key)
            for key in all_keys
            if current.lower() in key.lower()
        ][:25]


class InfoCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="info", 
        description="Dapatkan berbagai arsip informasi dan pengetahuan berharga di Kerajaan Kotabi!"
    )
    @discord.app_commands.describe(info_key="Topik atau kata kunci informasi yang ingin dicari.")
    @discord.app_commands.autocomplete(info_key=info_autocomplete)
    async def info(self, interaction: discord.Interaction, info_key: str):
        """Menampilkan kartu informasi estetik berdasarkan topik yang dipilih.
        Cek key dinamis dulu (harga hidup), baru fallback ke YAML statis."""
        if info_key in DYNAMIC_INFO_BUILDERS:
            text_info = DYNAMIC_INFO_BUILDERS[info_key]()
        elif info_key in info_commands:
            text_info = info_commands[info_key]
        else:
            await interaction.response.send_message(
                "❌ Topik informasi atau kata kunci tersebut tidak ditemukan di dalam arsip kerajaan.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title= f"📚 Arsip Informasi: `{info_key}`", 
            description=text_info, 
            color=discord.Color.random()
        )
        embed.set_footer(
            text=f"Diminta oleh {interaction.user.display_name}", 
            icon_url=interaction.user.display_avatar.url
        )
        
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    """Mendaftarkan modul InfoCommand ke sistem utama Bot."""
    await bot.add_cog(InfoCommand(bot))