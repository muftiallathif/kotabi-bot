"""
features/grammar/grammar_cog.py — Kamus Grammar Jepang (/grammar)
=====================================================================
Membaca entri dari features/grammar/grammar_entries.csv (format 26 kolom
sesuai "Panduan Membuat Entri Kamus Grammar Bahasa Jepang"), memuatnya ke
tabel SQLite grammar_entries, lalu menyediakan slash command /grammar
dengan autocomplete (cari lewat romaji, kana, atau id) yang menampilkan
entri sebagai embed terstruktur mengikuti 11 bagian ①–⑪ dari panduan.

CSV adalah sumber kebenaran: setiap cog_load(), isi CSV di-upsert ulang ke
database (aman dijalankan berkali-kali). Kalau mau menambah/mengubah
entri, cukup edit grammar_entries.csv lalu restart/reload cog ini —
tidak perlu query manual ke database.

Path CSV bisa dioverride lewat env var ALT_GRAMMAR_CSV_PATH, mengikuti
pola ALT_*_PATH yang sudah dipakai cog lain di project ini (mis.
gatekeeper_cog.py, practice_cog.py).
"""

import csv
import logging
import os

import discord
from discord.ext import commands

from core.bot import KotabiBot

_log = logging.getLogger("bot.grammar")

GRAMMAR_CSV_PATH = os.getenv("ALT_GRAMMAR_CSV_PATH") or "features/grammar/grammar_entries.csv"

# Kolom CSV, urut sesuai "Referensi Cepat: Daftar Final Kolom" di panduan.
CSV_COLUMNS = [
    "id", "romaji", "kana", "kanji", "jlpt", "jlpt_order",
    "part_of_speech", "usage_restriction", "meaning_en", "meaning_id",
    "counterpart_en", "counterpart_id", "related_expression",
    "key_sentence_pola", "key_sentence_contoh", "key_sentence_id",
    "formation", "examples_jp", "examples_en", "examples_id",
    "notes_en", "notes_id", "related_expression_detail",
    "tags", "rujukan_silang", "status",
]

CREATE_GRAMMAR_TABLE = """
CREATE TABLE IF NOT EXISTS grammar_entries (
    id TEXT PRIMARY KEY,
    romaji TEXT, kana TEXT, kanji TEXT,
    jlpt TEXT, jlpt_order INTEGER,
    part_of_speech TEXT, usage_restriction TEXT,
    meaning_en TEXT, meaning_id TEXT,
    counterpart_en TEXT, counterpart_id TEXT,
    related_expression TEXT,
    key_sentence_pola TEXT, key_sentence_contoh TEXT, key_sentence_id TEXT,
    formation TEXT,
    examples_jp TEXT, examples_en TEXT, examples_id TEXT,
    notes_en TEXT, notes_id TEXT, related_expression_detail TEXT,
    tags TEXT, rujukan_silang TEXT, status TEXT
);"""

UPSERT_ENTRY = f"""
INSERT INTO grammar_entries ({', '.join(CSV_COLUMNS)})
VALUES ({', '.join(['?'] * len(CSV_COLUMNS))})
ON CONFLICT(id) DO UPDATE SET {', '.join(f"{c}=excluded.{c}" for c in CSV_COLUMNS if c != 'id')};
"""

SEARCH_QUERY = """
SELECT id, romaji, kana, meaning_id, jlpt FROM grammar_entries
WHERE romaji LIKE '%' || ? || '%'
   OR kana LIKE '%' || ? || '%'
   OR id LIKE '%' || ? || '%'
ORDER BY jlpt_order ASC, romaji ASC
LIMIT 25;
"""

GET_ENTRY = f"SELECT {', '.join(CSV_COLUMNS)} FROM grammar_entries WHERE id = ?;"

JLPT_COLOR = {
    "N5": discord.Color.green(),
    "N4": discord.Color.blue(),
    "N3": discord.Color.gold(),
    "N2": discord.Color.orange(),
    "N1": discord.Color.red(),
}


async def grammar_autocomplete(interaction: discord.Interaction, current_input: str):
    """Menyediakan daftar pola grammar secara otomatis berdasarkan romaji/kana/id."""
    bot: KotabiBot = interaction.client
    current_input = current_input.strip()
    rows = await bot.GET(SEARCH_QUERY, (current_input, current_input, current_input))

    choices = []
    for entry_id, romaji, kana, meaning_id, jlpt in rows:
        label = f"{romaji} ({kana}) — {meaning_id}"[:100]
        choices.append(discord.app_commands.Choice(name=label, value=entry_id))
    return choices[:25]


def _row_to_dict(row: tuple) -> dict:
    return dict(zip(CSV_COLUMNS, row))


def build_grammar_embed(entry: dict) -> discord.Embed:
    """Menyusun entri database menjadi embed mengikuti struktur ①–⑪ panduan."""
    title = f"{entry['romaji']}"
    if entry.get("kanji") and entry["kanji"] not in ("—", ""):
        title += f"（{entry['kanji']}）"
    elif entry.get("kana"):
        title += f"（{entry['kana']}）"

    color = JLPT_COLOR.get(entry.get("jlpt"), discord.Color.blurple())
    embed = discord.Embed(title=f"📖 {title}", color=color)

    jlpt_str = entry.get("jlpt") or "—"
    restriction = entry.get("usage_restriction") or "—"
    embed.description = f"**JLPT:** {jlpt_str}　|　**Part of Speech:** {entry['part_of_speech']}　|　**Restriction:** {restriction}"

    embed.add_field(
        name="④ Meaning / Function",
        value=f"🇬🇧 {entry['meaning_en']}\n🇮🇩 {entry['meaning_id']}",
        inline=False,
    )
    embed.add_field(
        name="⑤ Counterpart(s)",
        value=f"🇬🇧 {entry['counterpart_en']}\n🇮🇩 {entry['counterpart_id']}",
        inline=False,
    )

    if entry.get("related_expression") and entry["related_expression"] not in ("—", ""):
        embed.add_field(name="⑥ Related Expression(s)", value=entry["related_expression"], inline=True)
    if entry.get("formation") and entry["formation"] not in ("—", ""):
        embed.add_field(name="⑧ Formation", value=entry["formation"].replace(";", "\n"), inline=True)

    key_sentence = (
        f"**Pola:** {entry['key_sentence_pola']}\n"
        f"**Contoh:** {entry['key_sentence_contoh']}\n"
        f"**ID:** {entry['key_sentence_id']}"
    )
    embed.add_field(name="⑦ Key Sentence", value=key_sentence[:1024], inline=False)

    jp_list = entry["examples_jp"].split(" | ")
    en_list = entry["examples_en"].split(" | ")
    id_list = entry["examples_id"].split(" | ")
    example_lines = []
    for i, (jp, en, idn) in enumerate(zip(jp_list, en_list, id_list), start=1):
        example_lines.append(f"**{i}.** {jp}\n　🇬🇧 {en}\n　🇮🇩 {idn}")
    embed.add_field(name="⑨ Examples", value="\n\n".join(example_lines)[:1024], inline=False)

    if entry.get("notes_en") and entry["notes_en"] not in ("—", ""):
        notes = f"🇬🇧 {entry['notes_en']}\n🇮🇩 {entry['notes_id']}"
        embed.add_field(name="⑩ Note(s)", value=notes[:1024], inline=False)

    if entry.get("related_expression_detail") and entry["related_expression_detail"] not in ("—", ""):
        embed.add_field(name="⑪ Related Expression(s) — Detail", value=entry["related_expression_detail"][:1024], inline=False)

    footer_bits = []
    if entry.get("tags") and entry["tags"] not in ("—", ""):
        footer_bits.append(f"Tags: {entry['tags']}")
    if entry.get("id"):
        footer_bits.append(f"ID: {entry['id']}")
    if footer_bits:
        embed.set_footer(text=" | ".join(footer_bits))

    return embed


class Grammar(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        """Membuat tabel (jika belum ada) lalu memuat/upsert seluruh isi CSV."""
        await self.bot.RUN(CREATE_GRAMMAR_TABLE)
        await self.load_csv()

    async def load_csv(self):
        if not os.path.exists(GRAMMAR_CSV_PATH):
            _log.warning("⚠️ File %s tidak ditemukan. Tabel grammar_entries kosong.", GRAMMAR_CSV_PATH)
            return

        rows_to_upsert = []
        with open(GRAMMAR_CSV_PATH, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows_to_upsert.append(tuple(row.get(col, "") for col in CSV_COLUMNS))

        if rows_to_upsert:
            await self.bot.RUN_MANY(UPSERT_ENTRY, rows_to_upsert)
            _log.info("✅ %d entri grammar dimuat dari %s", len(rows_to_upsert), GRAMMAR_CSV_PATH)

    @discord.app_commands.command(name="grammar", description="Cari pola grammar Jepang di kamus (cari lewat romaji/kana).")
    @discord.app_commands.describe(pola="Ketik romaji, kana, atau ID pola grammar yang dicari.")
    @discord.app_commands.autocomplete(pola=grammar_autocomplete)
    async def grammar(self, interaction: discord.Interaction, pola: str):
        """Slash command untuk menampilkan satu entri kamus grammar sebagai embed."""
        row = await self.bot.GET_ONE(GET_ENTRY, (pola,))
        if not row:
            await interaction.response.send_message(
                "❌ Entri grammar tidak ditemukan. Gunakan menu autocomplete saat mengetik.",
                ephemeral=True,
            )
            return

        entry = _row_to_dict(row)
        embed = build_grammar_embed(entry)
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name="grammar_reload", description="Muat ulang kamus grammar dari CSV (Khusus Admin).")
    @discord.app_commands.default_permissions(administrator=True)
    async def grammar_reload(self, interaction: discord.Interaction):
        """Slash command admin untuk memuat ulang CSV tanpa perlu restart bot."""
        await interaction.response.defer(ephemeral=True)
        await self.load_csv()
        count_row = await self.bot.GET_ONE("SELECT COUNT(*) FROM grammar_entries;")
        total = count_row[0] if count_row else 0
        await interaction.followup.send(f"✅ Kamus grammar dimuat ulang. Total entri: **{total}**.", ephemeral=True)


async def setup(bot: KotabiBot):
    await bot.add_cog(Grammar(bot))
