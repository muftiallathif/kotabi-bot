"""
features/gatekeeper/practice_cog.py — Tombol "Mulai Latihan" di Quiz Public Forum
=====================================================================================
(Grup D4 — lihat catatan restrukturisasi quiz system)

Berbeda dari bilik ujian rank (gatekeeper_cog.py -> DynamicQuizMenu), thread
yang dibuat di sini bersifat PUBLIK — siapa saja boleh melihat dan bergabung
untuk latihan bebas atau duel santai. Thread ini TIDAK di-lock
(invitable=True, default Discord), dan TIDAK PERNAH diproses sebagai
percobaan kenaikan kasta karena gatekeeper_cog.level_up_routine() sekarang
hanya memproses pesan yang berasal dari bilik ujian (tabel user_threads)
atau channel quiz_rank_up — lihat channel guard yang ditambahkan di sana
(D1). Jadi latihan bebas di forum ini aman: tidak memicu notice "belum
berhasil", tidak kena cooldown, tidak kena timeout.

Auto-cleanup thread yang lama tidak aktif sudah ditangani oleh
features/moderation/quiz_forum_cog.py (archive setelah N hari) — cog ini
tidak perlu menangani cleanup sendiri.

Command:
  /create_practice_menu — Buat POST BARU berisi tombol "🎮 Mulai Latihan"
                           di dalam forum quiz-public-forum (Khusus Admin).

    PENTING (fix dari versi sebelumnya): Forum Channel TIDAK punya kotak
    ketik biasa di level channel-nya sendiri — hanya post/thread di
    dalamnya yang punya kotak ketik. Jadi command ini SENGAJA bisa
    dijalankan dari channel MANA PUN (mis. #staff-chat), lalu memakai
    forum.create_thread() untuk membuat post baru di forum secara
    terprogram — bukan mengandalkan interaction.response.send_message()
    yang butuh channel dengan kotak ketik biasa (yang tidak dimiliki
    Forum Channel di level root-nya).

Cara pakai:
  1. Taruh file ini di features/gatekeeper/practice_cog.py
  2. Jalankan migrations/v3_practice_threads.sql (opsional — tabel juga
     dibuat otomatis oleh cog_load()) atau cukup restart bot.
  3. Panggil /create_practice_menu SATU KALI dari channel mana pun
     (tidak perlu di dalam forum). Tombolnya persistent, tidak perlu
     diposting ulang setelah bot restart.
"""

import logging

import discord
from discord.ext import commands

from core.bot import KotabiBot
from shared.config import get_channel_id

_log = logging.getLogger("bot.gatekeeper.practice")

KOTOBA_BOT_ID = 251239170058616833

CREATE_PRACTICE_THREADS_TABLE = """
CREATE TABLE IF NOT EXISTS practice_threads (
    user_id   INTEGER NOT NULL PRIMARY KEY,
    thread_id INTEGER NOT NULL
);"""

GET_PRACTICE_THREAD = """
SELECT thread_id FROM practice_threads WHERE user_id = ?;"""

UPSERT_PRACTICE_THREAD = """
INSERT INTO practice_threads (user_id, thread_id) VALUES (?, ?)
ON CONFLICT(user_id) DO UPDATE SET thread_id = excluded.thread_id;"""

PRACTICE_BUTTON_CUSTOM_ID = "gatekeeper_practice_start"

PRACTICE_MENU_POST_TITLE = "🎮 Mulai Latihan Kuis"
PRACTICE_MENU_POST_CONTENT = (
    "🎮 **RUANG LATIHAN KUIS**\n\n"
    "Klik tombol di bawah untuk membuka ruang latihan pribadimu. Ruang ini "
    "bersifat publik — siapa pun boleh bergabung untuk latihan atau duel "
    "santai. Latihan di sini **tidak memengaruhi kasta** kamu."
)


class PracticeMenuView(discord.ui.View):
    """View persistent — custom_id tetap supaya tombol tahan restart bot."""

    def __init__(self, cog: "PracticeThreads"):
        super().__init__(timeout=None)
        self.cog = cog
        self.start_practice.custom_id = PRACTICE_BUTTON_CUSTOM_ID

    @discord.ui.button(label="🎮 Mulai Latihan", style=discord.ButtonStyle.success)
    async def start_practice(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_start_practice(interaction)


class PracticeThreads(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        """Inisialisasi tabel database dan daftarkan ulang view persistent."""
        await self.bot.RUN(CREATE_PRACTICE_THREADS_TABLE)
        self.bot.add_view(PracticeMenuView(self))

    async def handle_start_practice(self, interaction: discord.Interaction):
        """Cari thread latihan aktif milik user, atau buat baru kalau belum ada."""
        await interaction.response.defer(ephemeral=True)

        # Tombol ini SELALU dipencet dari dalam sebuah post forum (Thread),
        # bukan dari root forum. interaction.channel di sini adalah Thread
        # milik siapa pun yang membuat post "Mulai Latihan Kuis" itu, jadi
        # kita ambil forum induknya lewat channel.parent, bukan channel itu
        # sendiri.
        thread_channel = interaction.channel
        forum = thread_channel.parent if isinstance(thread_channel, discord.Thread) else None

        if not isinstance(forum, discord.ForumChannel):
            return await interaction.followup.send(
                "❌ Tombol ini hanya dapat digunakan di dalam post forum latihan.",
                ephemeral=True,
            )

        record = await self.bot.GET_ONE(GET_PRACTICE_THREAD, (interaction.user.id,))
        thread = None

        if record:
            thread_id = record[0]
            thread = interaction.guild.get_thread(thread_id)
            if not thread:
                try:
                    thread = await interaction.guild.fetch_channel(thread_id)
                except (discord.NotFound, discord.Forbidden):
                    thread = None
                except Exception as e:
                    _log.warning(
                        "Gagal fetch thread latihan lama %s untuk user %s: %s",
                        thread_id, interaction.user.id, e
                    )
                    thread = None

        if not thread:
            try:
                thread_with_message = await forum.create_thread(
                    name=f"🎮 Latihan — {interaction.user.display_name}"[:100],
                    content=(
                        f"🎮 Selamat datang di ruang latihan {interaction.user.mention}!\n\n"
                        f"Thread ini bersifat **publik** — siapa saja boleh bergabung untuk "
                        f"latihan bebas atau duel santai. Ketik perintah kuis Bot Kotoba "
                        f"(`k!q ...`) di sini kapan saja.\n\n"
                        f"⚠️ Latihan di sini **tidak** akan menaikkan kasta. Untuk ujian "
                        f"kenaikan kasta resmi, gunakan menu di channel quiz-rank-up."
                    ),
                )
                thread = thread_with_message.thread
                await self.bot.RUN(UPSERT_PRACTICE_THREAD, (interaction.user.id, thread.id))
                _log.info(
                    "Thread latihan baru dibuat untuk %s (%d): %s",
                    interaction.user, interaction.user.id, thread.name
                )

                kotoba = interaction.guild.get_member(KOTOBA_BOT_ID)
                if not kotoba:
                    try:
                        kotoba = await interaction.guild.fetch_member(KOTOBA_BOT_ID)
                    except discord.NotFound:
                        kotoba = None
                if kotoba and kotoba not in thread.members:
                    await thread.add_user(kotoba)

            except discord.Forbidden:
                return await interaction.followup.send(
                    "❌ Bot tidak memiliki izin untuk membuat thread di forum ini.",
                    ephemeral=True,
                )
            except Exception as e:
                _log.error("Gagal membuat thread latihan untuk %s: %s", interaction.user.id, e)
                return await interaction.followup.send(
                    "❌ Terjadi kesalahan saat membuat ruang latihan. Coba lagi nanti.",
                    ephemeral=True,
                )

        if thread.locked or thread.archived:
            try:
                await thread.edit(locked=False, archived=False)
            except discord.Forbidden:
                pass

        if interaction.user not in thread.members:
            try:
                await thread.add_user(interaction.user)
            except discord.Forbidden:
                pass

        jump_view = discord.ui.View()
        jump_view.add_item(
            discord.ui.Button(
                label="Masuk ke Ruang Latihan",
                style=discord.ButtonStyle.link,
                url=thread.jump_url,
                emoji="🎮",
            )
        )
        await interaction.followup.send(
            "✅ Ruang latihanmu sudah siap! Silakan klik tombol di bawah untuk masuk.",
            view=jump_view,
            ephemeral=True,
        )

    @discord.app_commands.command(
        name="create_practice_menu",
        description="Buat post baru berisi tombol 'Mulai Latihan' di forum quiz-public (Khusus Admin).",
    )
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(administrator=True)
    async def create_practice_menu(self, interaction: discord.Interaction):
        """
        Slash command admin untuk membuat post menu latihan di forum.

        SENGAJA bisa dijalankan dari channel mana pun (bukan hanya di dalam
        forum) — lihat penjelasan di docstring modul soal kenapa Forum
        Channel tidak bisa jadi lokasi mengetik command secara langsung.
        """
        await interaction.response.defer(ephemeral=True)

        forum_id = get_channel_id(interaction.guild_id, "quiz_public_forum")
        forum = interaction.guild.get_channel(forum_id) if forum_id else None

        if not isinstance(forum, discord.ForumChannel):
            return await interaction.followup.send(
                "❌ Channel `quiz_public_forum` tidak ditemukan atau bukan Forum Channel. "
                "Cek key `quiz_public_forum` di shared/server_map.yml.",
                ephemeral=True,
            )

        try:
            thread_with_message = await forum.create_thread(
                name=PRACTICE_MENU_POST_TITLE,
                content=PRACTICE_MENU_POST_CONTENT,
                view=PracticeMenuView(self),
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ Bot tidak memiliki izin untuk membuat post di forum ini.", ephemeral=True
            )
        except Exception as e:
            _log.error("Gagal membuat post menu latihan: %s", e)
            return await interaction.followup.send(
                f"❌ Terjadi kesalahan saat membuat post menu: `{e}`", ephemeral=True
            )

        await interaction.followup.send(
            f"✅ Post menu latihan berhasil dibuat: {thread_with_message.thread.jump_url}\n"
            f"_(Tombolnya persistent — tidak perlu dijalankan ulang setelah bot restart.)_",
            ephemeral=True,
        )


async def setup(bot: KotabiBot):
    await bot.add_cog(PracticeThreads(bot))