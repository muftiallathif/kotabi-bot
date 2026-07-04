"""
features/dictionary/kanji_cog.py — Kamus Kanji (/kanji)
===========================================================
Sumber data:
  - kanji_data.json       : data mentah dari github.com/davidluzgouveia/kanji-data
                            (MIT License). Boleh ditimpa ulang kapan saja untuk
                            sync ke versi upstream terbaru — TIDAK menghapus
                            terjemahan ID (lihat poin di bawah).
  - kanji_meanings_id.csv : terjemahan arti kanji ke Bahasa Indonesia, diisi
                            manual bertahap oleh owner. Kolom: kanji,meaning_id.
  - radical_names_id.csv  : terjemahan nama radikal (ala WaniKani) ke Bahasa
                            Indonesia. Kolom: radical_en,radical_id. Disimpan
                            TERPISAH dari kanji_meanings_id.csv karena satu
                            radikal dipakai ulang oleh ratusan kanji berbeda —
                            translate sekali per nama radikal, bukan per kanji.

Kenapa 3 sumber terpisah, bukan 1 file:
  JSON di-upsert ulang setiap start TANPA menyentuh kolom meaning_id (lihat
  ON CONFLICT DO UPDATE di UPSERT_KANJI_FROM_JSON), supaya redownload
  kanji_data.json versi upstream terbaru tidak pernah menghapus terjemahan
  yang sudah capek-capek diisi manual. radical_translations juga tabel
  terpisah dengan alasan yang sama plus alasan normalisasi (hemat kerja
  translate).

Command:
  /kanji         — cari 1 kanji spesifik, atau jelajahi berdasarkan level JLPT.
                   Kalau `kanji` diisi -> mode detail (satu embed).
                   Kalau `jlpt` diisi (tanpa `kanji`) -> mode browse/list,
                   terpaginasi dengan dropdown loncat ke detail.
                   Kalau dua-duanya kosong -> diminta isi salah satu (data
                   kanji terlalu banyak untuk ditampilkan semua sekaligus).
  /kanji_reload  — muat ulang JSON + kedua CSV terjemahan tanpa restart bot
                   (Khusus Admin).

Gating akses: sama seperti /grammar, lewat shared.checks.is_dic_access()
(Trial dapat, Traveler TIDAK dapat, Companion/Patron/staff/admin dapat).
"""

import csv
import json
import logging
import os
from typing import Optional

import discord
from discord.ext import commands

from core.bot import KotabiBot
from shared.checks import is_dic_access

_log = logging.getLogger("bot.kanji")

KANJI_JSON_PATH = os.getenv("ALT_KANJI_JSON_PATH") or "features/dictionary/kanji_data.json"
KANJI_TRANSLATIONS_PATH = os.getenv("ALT_KANJI_TRANSLATIONS_PATH") or "features/dictionary/kanji_meanings_id.csv"
RADICAL_TRANSLATIONS_PATH = os.getenv("ALT_RADICAL_TRANSLATIONS_PATH") or "features/dictionary/radical_names_id.csv"

JLPT_CHOICES = ["N5", "N4", "N3", "N2", "N1"]

JLPT_COLOR = {
    "N5": discord.Color.green(),
    "N4": discord.Color.blue(),
    "N3": discord.Color.gold(),
    "N2": discord.Color.orange(),
    "N1": discord.Color.red(),
}

LIST_PAGE_SIZE = 10
PAGINATOR_TIMEOUT_SECONDS = 800

JLPT_NUM_TO_LABEL = {1: "N1", 2: "N2", 3: "N3", 4: "N4", 5: "N5"}

# ============================================================================
# DATABASE
# ============================================================================

CREATE_KANJI_TABLE = """
CREATE TABLE IF NOT EXISTS kanji_entries (
    kanji TEXT PRIMARY KEY,
    strokes INTEGER,
    grade INTEGER,
    freq INTEGER,
    jlpt TEXT,
    meanings_en TEXT,
    meaning_id TEXT,
    readings_on TEXT,
    readings_kun TEXT,
    wk_radicals TEXT,
    wk_level INTEGER
);"""

# Tabel terpisah — radikal dipakai ULANG oleh ratusan kanji berbeda, jadi
# terjemahannya disimpan sekali per nama radikal, bukan per kanji.
CREATE_RADICAL_TRANSLATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS radical_translations (
    radical_en TEXT PRIMARY KEY,
    radical_id TEXT
);"""

# SENGAJA tidak menyertakan meaning_id di kolom insert maupun ON CONFLICT
# DO UPDATE — supaya reload JSON tidak pernah menghapus terjemahan manual
# yang sudah di-patch oleh kanji_meanings_id.csv.
UPSERT_KANJI_FROM_JSON = """
INSERT INTO kanji_entries (kanji, strokes, grade, freq, jlpt, meanings_en, readings_on, readings_kun, wk_radicals, wk_level)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(kanji) DO UPDATE SET
    strokes=excluded.strokes,
    grade=excluded.grade,
    freq=excluded.freq,
    jlpt=excluded.jlpt,
    meanings_en=excluded.meanings_en,
    readings_on=excluded.readings_on,
    readings_kun=excluded.readings_kun,
    wk_radicals=excluded.wk_radicals,
    wk_level=excluded.wk_level;
"""

PATCH_MEANING_ID = "UPDATE kanji_entries SET meaning_id = ? WHERE kanji = ?;"

UPSERT_RADICAL_TRANSLATION = """
INSERT INTO radical_translations (radical_en, radical_id) VALUES (?, ?)
ON CONFLICT(radical_en) DO UPDATE SET radical_id=excluded.radical_id;
"""

GET_RADICAL_TRANSLATIONS = "SELECT radical_en, radical_id FROM radical_translations;"

GET_ENTRY = """
SELECT kanji, strokes, grade, freq, jlpt, meanings_en, meaning_id, readings_on, readings_kun, wk_radicals, wk_level
FROM kanji_entries WHERE kanji = ?;"""

SEARCH_QUERY = """
SELECT kanji, meanings_en, jlpt FROM kanji_entries
WHERE kanji LIKE '%' || ? || '%'
   OR meanings_en LIKE '%' || ? || '%'
   OR readings_on LIKE '%' || ? || '%'
   OR readings_kun LIKE '%' || ? || '%'
ORDER BY (freq IS NULL), freq ASC
LIMIT 25;"""

SEARCH_QUERY_JLPT = """
SELECT kanji, meanings_en, jlpt FROM kanji_entries
WHERE jlpt = ?
AND (kanji LIKE '%' || ? || '%' OR meanings_en LIKE '%' || ? || '%'
     OR readings_on LIKE '%' || ? || '%' OR readings_kun LIKE '%' || ? || '%')
ORDER BY (freq IS NULL), freq ASC
LIMIT 25;"""

LIST_BY_JLPT_QUERY = """
SELECT kanji, meanings_en, jlpt FROM kanji_entries
WHERE jlpt = ?
ORDER BY (freq IS NULL), freq ASC;"""


# ============================================================================
# AUTOCOMPLETE
# ============================================================================

async def kanji_autocomplete(interaction: discord.Interaction, current_input: str):
    """Cari kanji berdasarkan karakternya sendiri, arti (EN), atau cara baca."""
    bot: KotabiBot = interaction.client
    current_input = current_input.strip()
    jlpt = getattr(interaction.namespace, "jlpt", None)

    if jlpt:
        rows = await bot.GET(SEARCH_QUERY_JLPT, (jlpt, current_input, current_input, current_input, current_input))
    else:
        rows = await bot.GET(SEARCH_QUERY, (current_input, current_input, current_input, current_input))

    choices = []
    for kanji_char, meanings_en, entry_jlpt in rows:
        first_meaning = (meanings_en or "").split(" | ")[0]
        label = f"{kanji_char} — {first_meaning}"
        if entry_jlpt:
            label += f" ({entry_jlpt})"
        choices.append(discord.app_commands.Choice(name=label[:100], value=kanji_char))
    return choices[:25]


# ============================================================================
# HELPERS
# ============================================================================

def _row_to_dict(row: tuple) -> dict:
    keys = [
        "kanji", "strokes", "grade", "freq", "jlpt", "meanings_en", "meaning_id",
        "readings_on", "readings_kun", "wk_radicals", "wk_level",
    ]
    return dict(zip(keys, row))


def _add_requester_info(embed: discord.Embed, user: discord.User) -> discord.Embed:
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.set_footer(text=f"Diminta oleh @{user.name}")
    return embed


async def _format_radicals(bot: KotabiBot, wk_radicals: Optional[str]) -> Optional[str]:
    """Format 'Ground, Leaf' -> 'Ground (Tanah), Leaf' kalau ada terjemahan,
    atau apa adanya (Inggris saja) kalau terjemahan belum diisi."""
    if not wk_radicals:
        return None

    radical_list = [r.strip() for r in wk_radicals.split(",") if r.strip()]
    if not radical_list:
        return None

    translations = dict(await bot.GET(GET_RADICAL_TRANSLATIONS))

    formatted = []
    for radical in radical_list:
        translated = translations.get(radical)
        formatted.append(f"{radical} ({translated})" if translated else radical)

    return ", ".join(formatted)


async def build_kanji_detail_embed(bot: KotabiBot, entry: dict) -> discord.Embed:
    """Satu kanji cukup satu embed — datanya jauh lebih ringkas dibanding entri grammar."""
    color = JLPT_COLOR.get(entry.get("jlpt"), discord.Color.blurple())
    embed = discord.Embed(title=f"📖 {entry['kanji']}", color=color)

    info_bits = []
    if entry.get("jlpt"):
        info_bits.append(f"JLPT {entry['jlpt']}")
    if entry.get("grade"):
        info_bits.append(f"Kyōiku Grade {entry['grade']}")
    if entry.get("strokes"):
        info_bits.append(f"{entry['strokes']} goresan")
    if entry.get("wk_level"):
        info_bits.append(f"WaniKani Lv.{entry['wk_level']}")
    if info_bits:
        embed.description = " | ".join(info_bits)

    meaning_id = entry.get("meaning_id")
    meaning_value = meaning_id if meaning_id else "_Belum diterjemahkan ke Bahasa Indonesia_"
    embed.add_field(name="🇮🇩 Arti", value=meaning_value, inline=False)
    embed.add_field(name="🇬🇧 Meaning", value=entry.get("meanings_en") or "—", inline=False)

    if entry.get("readings_on"):
        embed.add_field(name="音読み (On'yomi)", value=entry["readings_on"], inline=True)
    if entry.get("readings_kun"):
        embed.add_field(name="訓読み (Kun'yomi)", value=entry["readings_kun"], inline=True)

    radicals_display = await _format_radicals(bot, entry.get("wk_radicals"))
    if radicals_display:
        embed.add_field(name="🧩 Radikal Penyusun", value=radicals_display, inline=False)

    return embed


def _list_title(jlpt: str) -> str:
    return f"📚 Kamus Kanji — Level {jlpt}"


def build_list_pages(entries: list[dict], jlpt: str) -> tuple[list[discord.Embed], list[list[dict]]]:
    title = _list_title(jlpt)
    chunks = [entries[i:i + LIST_PAGE_SIZE] for i in range(0, len(entries), LIST_PAGE_SIZE)] or [[]]
    total_pages = len(chunks)

    pages = []
    for idx, chunk in enumerate(chunks, start=1):
        lines = []
        for e in chunk:
            meaning = (e["meanings_en"] or "—").split(" | ")[0]
            if len(meaning) > 50:
                meaning = meaning[:47] + "..."
            lines.append(f"**{e['kanji']}** — {meaning}")
        embed = discord.Embed(
            title=title,
            description="\n".join(lines) or "Tidak ada entri.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Halaman {idx}/{total_pages} • Total {len(entries)} kanji")
        pages.append(embed)

    return pages, chunks


# ============================================================================
# PAGINATION VIEW
# ============================================================================

class KanjiListView(discord.ui.View):
    """Paginator Prev/Next + dropdown loncat ke detail, sama pola dengan GrammarListView."""

    def __init__(self, owner_id: int, pages: list[discord.Embed], page_entries: list[list[dict]]):
        super().__init__(timeout=PAGINATOR_TIMEOUT_SECONDS)
        self.owner_id = owner_id
        self.pages = pages
        self.page_entries = page_entries
        self.index = 0
        self.message: Optional[discord.InteractionMessage] = None
        self._sync_buttons()
        self._rebuild_select()

    def _sync_buttons(self):
        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(self.pages) - 1

    def _rebuild_select(self):
        for item in list(self.children):
            if isinstance(item, discord.ui.Select):
                self.remove_item(item)

        entries = self.page_entries[self.index]
        if not entries:
            return

        options = [
            discord.SelectOption(
                label=e["kanji"],
                description=((e["meanings_en"] or "—").split(" | ")[0])[:100],
                value=e["kanji"],
            )
            for e in entries
        ]
        select = discord.ui.Select(placeholder="Pilih kanji untuk lihat detail...", options=options, row=0)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Ini bukan pencarian kamu.", ephemeral=True)

        kanji_char = interaction.data["values"][0]
        bot: KotabiBot = interaction.client
        row = await bot.GET_ONE(GET_ENTRY, (kanji_char,))
        if not row:
            return await interaction.response.send_message("❌ Entri tidak ditemukan lagi.", ephemeral=True)

        embed = await build_kanji_detail_embed(bot, _row_to_dict(row))
        _add_requester_info(embed, interaction.user)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ini bukan pencarian kamu.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.secondary, row=1)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._sync_buttons()
        self._rebuild_select()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.secondary, row=1)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync_buttons()
        self._rebuild_select()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


# ============================================================================
# COG
# ============================================================================

class Kanji(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.RUN(CREATE_KANJI_TABLE)
        await self.bot.RUN(CREATE_RADICAL_TRANSLATIONS_TABLE)
        await self.load_json()
        await self.load_translations()
        await self.load_radical_translations()

    async def load_json(self):
        if not os.path.exists(KANJI_JSON_PATH):
            _log.warning("⚠️ File %s tidak ditemukan. Tabel kanji_entries kosong.", KANJI_JSON_PATH)
            return

        with open(KANJI_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        rows = []
        for kanji_char, info in data.items():
            jlpt_num = info.get("jlpt_new")
            jlpt_label = JLPT_NUM_TO_LABEL.get(jlpt_num)

            # FIX (TypeError: can only join an iterable):
            # `.get(key, default)` hanya memakai `default` kalau key-nya
            # TIDAK ADA sama sekali. Kalau key ADA tapi nilainya `null` di
            # JSON (mis. kanji tanpa kun'yomi, atau tanpa data wk_radicals
            # dari WaniKani), `.get()` mengembalikan None — lalu
            # `", ".join(None)` meledak dengan TypeError. Pakai
            # `.get(key) or []` supaya None juga di-fallback ke list kosong.
            meanings_en = " | ".join(info.get("meanings") or [])
            readings_on = ", ".join(info.get("readings_on") or [])
            readings_kun = ", ".join(info.get("readings_kun") or [])
            wk_radicals = ", ".join(info.get("wk_radicals") or [])

            rows.append((
                kanji_char,
                info.get("strokes"),
                info.get("grade"),
                info.get("freq"),
                jlpt_label,
                meanings_en,
                readings_on,
                readings_kun,
                wk_radicals,
                info.get("wk_level"),
            ))

        if rows:
            await self.bot.RUN_MANY(UPSERT_KANJI_FROM_JSON, rows)
            _log.info("✅ %d entri kanji dimuat dari %s", len(rows), KANJI_JSON_PATH)

    async def load_translations(self):
        if not os.path.exists(KANJI_TRANSLATIONS_PATH):
            _log.info("ℹ️ File %s tidak ditemukan, dilewati (belum ada terjemahan).", KANJI_TRANSLATIONS_PATH)
            return

        patched = 0
        with open(KANJI_TRANSLATIONS_PATH, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                kanji_char = (row.get("kanji") or "").strip()
                meaning_id = (row.get("meaning_id") or "").strip()
                if not kanji_char or not meaning_id:
                    continue
                await self.bot.RUN(PATCH_MEANING_ID, (meaning_id, kanji_char))
                patched += 1

        _log.info("✅ %d terjemahan arti kanji di-patch dari %s", patched, KANJI_TRANSLATIONS_PATH)

    async def load_radical_translations(self):
        if not os.path.exists(RADICAL_TRANSLATIONS_PATH):
            _log.info("ℹ️ File %s tidak ditemukan, dilewati (belum ada terjemahan radikal).", RADICAL_TRANSLATIONS_PATH)
            return

        patched = 0
        with open(RADICAL_TRANSLATIONS_PATH, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                radical_en = (row.get("radical_en") or "").strip()
                radical_id = (row.get("radical_id") or "").strip()
                if not radical_en or not radical_id:
                    continue
                await self.bot.RUN(UPSERT_RADICAL_TRANSLATION, (radical_en, radical_id))
                patched += 1

        _log.info("✅ %d terjemahan radikal dimuat dari %s", patched, RADICAL_TRANSLATIONS_PATH)

    @discord.app_commands.command(
        name="kanji",
        description="Cari satu kanji, atau jelajahi kanji berdasarkan level JLPT.",
    )
    @discord.app_commands.describe(
        kanji="Ketik kanji, arti (Inggris), atau cara baca. Kalau diisi, jlpt diabaikan.",
        jlpt="Jelajahi semua kanji di level JLPT ini (dipakai kalau `kanji` kosong).",
    )
    @discord.app_commands.choices(
        jlpt=[discord.app_commands.Choice(name=level, value=level) for level in JLPT_CHOICES]
    )
    @discord.app_commands.autocomplete(kanji=kanji_autocomplete)
    @is_dic_access()
    async def kanji(
        self,
        interaction: discord.Interaction,
        kanji: Optional[str] = None,
        jlpt: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        # Mode detail: kanji diisi -> jlpt diabaikan
        if kanji:
            row = await self.bot.GET_ONE(GET_ENTRY, (kanji,))
            if not row:
                return await interaction.followup.send(
                    "❌ Kanji tidak ditemukan. Gunakan menu autocomplete saat mengetik.", ephemeral=True
                )
            embed = await build_kanji_detail_embed(self.bot, _row_to_dict(row))
            _add_requester_info(embed, interaction.user)
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Mode browse: wajib isi jlpt (data kanji terlalu banyak untuk ditampilkan semua)
        if not jlpt:
            return await interaction.followup.send(
                "ℹ️ Isi parameter `kanji` untuk cari satu kanji spesifik, "
                "atau isi `jlpt` untuk menjelajahi semua kanji di level tersebut.",
                ephemeral=True,
            )

        rows = await self.bot.GET(LIST_BY_JLPT_QUERY, (jlpt,))
        if not rows:
            return await interaction.followup.send(f"❌ Tidak ada kanji terdaftar untuk level {jlpt}.", ephemeral=True)

        entries = [{"kanji": r[0], "meanings_en": r[1], "jlpt": r[2]} for r in rows]
        pages, page_entries = build_list_pages(entries, jlpt)
        for p in pages:
            _add_requester_info(p, interaction.user)

        view = KanjiListView(interaction.user.id, pages, page_entries)
        message = await interaction.followup.send(embed=pages[0], view=view, ephemeral=True, wait=True)
        view.message = message

    @discord.app_commands.command(
        name="kanji_reload",
        description="Muat ulang data kanji dari JSON + kedua CSV terjemahan (Khusus Admin).",
    )
    @discord.app_commands.default_permissions(administrator=True)
    async def kanji_reload(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.load_json()
        await self.load_translations()
        await self.load_radical_translations()

        count_row = await self.bot.GET_ONE("SELECT COUNT(*) FROM kanji_entries;")
        translated_row = await self.bot.GET_ONE("SELECT COUNT(*) FROM kanji_entries WHERE meaning_id IS NOT NULL;")
        radical_row = await self.bot.GET_ONE("SELECT COUNT(*) FROM radical_translations;")

        total = count_row[0] if count_row else 0
        translated = translated_row[0] if translated_row else 0
        radicals_translated = radical_row[0] if radical_row else 0

        await interaction.followup.send(
            f"✅ Kamus kanji dimuat ulang.\n"
            f"Total kanji: **{total}** (arti sudah diterjemahkan: **{translated}**)\n"
            f"Radikal sudah diterjemahkan: **{radicals_translated}**",
            ephemeral=True,
        )


async def setup(bot: KotabiBot):
    await bot.add_cog(Kanji(bot))