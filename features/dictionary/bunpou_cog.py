"""
features/dictionary/bunpou_cog.py — Kamus Grammar Jepang versi ringkas (/bunpou)
=================================================================================
Menggantikan features/dictionary/grammar_cog.py (format 15-bagian ①-⑮, 4 CSV
relasional) SEPENUHNYA. /bunpou memakai format flat/ringkas, 1 CSV datar:
    grammar-notes-master.csv   (91 kolom, key field NoteID)

Mengikuti "Panduan Membuat Entri Kamus Grammar Bahasa Jepang (Versi Ringkas)"
(panduan-kamus-grammar-versi-ringkas.md), khususnya bagian 8 (Rencana Tampilan
Discord) dan bagian 4 (Checklist Kualitas, lihat support/grammar_validator.py
untuk versi otomatisnya).

SKEMA: FIELD_NAMES / KEY_FIELD / CATEGORY_FIELDS diimpor LANGSUNG dari
grammar_fields.py (bukan diduplikasi) — kalau skema field berubah di masa
depan, cukup edit grammar_fields.py, cog ini otomatis ikut menyesuaikan
kolom tabel SQLite & rendering kategori (lihat _slot_group() & render_category()
di bawah, keduanya generik berbasis CATEGORY_FIELDS, tidak hardcode jumlah
halaman atau jumlah slot).

--------------------------------------------------------------------
KEAMANAN SQL
--------------------------------------------------------------------
- CREATE TABLE & ALTER TABLE (migration guard) memakai nama kolom dari
  FIELD_NAMES — konstanta tetap di grammar_fields.py, bukan dari CSV atau
  input pengguna, jadi f-string di situ aman.
- Semua query yang menyentuh data dari CSV/input pengguna memakai
  parameter binding ("?"), tidak pernah string-interpolation langsung
  dari nilai data.
- Insert baris CSV memakai bot.RUN_MANY() (executemany), bukan bot.RUN().

--------------------------------------------------------------------
LOADER CSV (FULL REPLACE, BUKAN UPSERT PARSIAL)
--------------------------------------------------------------------
Sumber CSV ini FLAT (bukan relasional seperti grammar_entries lama), jadi
tidak ada tabel anak yang perlu diselaraskan terpisah — setiap cog_load()
/ /bunpou_reload menjalankan full replace: DELETE semua baris di
bunpou_entries, lalu INSERT ulang semua baris dari CSV. Ini lebih
sederhana & lebih aman daripada upsert+stale-cleanup partial ala
/grammar lama, karena satu-satunya sumber data memang cuma 1 tabel datar.

Format CSV: tab-delimited, baris pertama adalah metadata Anki
`#separator:Tab` (bukan header asli) — dilewati. Baris kedua barulah
header kolom asli yang harus PERSIS cocok dengan FIELD_NAMES (urutan &
nama). Baris data pakai \r\n (hasil ekspor Anki di Windows).
"""

import csv
import logging
import os
import re
from typing import Optional

import discord
from discord.ext import commands

from core.bot import KotabiBot
from shared.checks import is_dic_access

from .grammar_fields import FIELD_NAMES, KEY_FIELD, CATEGORY_FIELDS

_log = logging.getLogger("bot.bunpou")

# ============================================================================
# PATH & SKEMA
# ============================================================================

CSV_PATH = os.getenv("ALT_BUNPOU_CSV_PATH") or "features/dictionary/grammar-notes-master.csv"

TABLE_NAME = "bunpou_entries"

# Semua kolom disimpan sebagai TEXT — skema sumber flat ini murni string
# (termasuk angka seperti Sort/GrammarStar yang dipakai sebagai label
# tampilan, bukan dihitung matematis), sesuai grammar_fields.py yang juga
# tidak mendeklarasikan tipe per-kolom.
_COLUMN_DEFS = ", ".join(
    f"{col} TEXT PRIMARY KEY" if col == KEY_FIELD else f"{col} TEXT"
    for col in FIELD_NAMES
)
CREATE_TABLE = f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} ({_COLUMN_DEFS});"

# Kategori yang TIDAK ditampilkan ke user sama sekali (§8: "Template Toggle").
HIDDEN_CATEGORIES = {"Template Toggle"}
# Field individual yang tidak ditampilkan walau kategorinya ditampilkan
# (NoteID = key internal, Sort = urutan tampilan internal, bukan info
# linguistik — lihat panduan §7).
HIDDEN_FIELDS = {"NoteID", "Sort"}
# Kategori yang dipakai untuk membangun JUDUL embed, bukan body halaman
# (§8: GrammarPattern + GrammarFurigana + GrammarStar, + GrammarBracket
# kalau terisi).
TITLE_CATEGORY = "Info Pola"
# Kategori yang dilipat jadi footer (level/frequency/Tags), bukan halaman
# tersendiri — Sort tetap disembunyikan walau ada di kategori yang sama.
FOOTER_CATEGORY = "Pengelompokan/Tag"

DELETE_ALL = f"DELETE FROM {TABLE_NAME};"
INSERT_ENTRY = (
    f"INSERT INTO {TABLE_NAME} ({', '.join(FIELD_NAMES)}) "
    f"VALUES ({', '.join(['?'] * len(FIELD_NAMES))});"
)
GET_ENTRY = f"SELECT {', '.join(FIELD_NAMES)} FROM {TABLE_NAME} WHERE {KEY_FIELD} = ?;"
GET_ALL_FOR_LIST = f"SELECT {KEY_FIELD}, GrammarPattern, GrammarFurigana, GrammarMeaningID, level FROM {TABLE_NAME}"

SEARCH_QUERY = f"""
SELECT {KEY_FIELD}, GrammarPattern, GrammarFurigana, GrammarMeaningID, level FROM {TABLE_NAME}
WHERE GrammarPattern LIKE '%' || ? || '%'
   OR GrammarFurigana LIKE '%' || ? || '%'
   OR {KEY_FIELD} LIKE '%' || ? || '%'
ORDER BY CAST(Sort AS INTEGER) ASC, GrammarPattern ASC
LIMIT 25;
"""

SEARCH_QUERY_LEVEL = f"""
SELECT {KEY_FIELD}, GrammarPattern, GrammarFurigana, GrammarMeaningID, level FROM {TABLE_NAME}
WHERE level = ?
AND (GrammarPattern LIKE '%' || ? || '%' OR GrammarFurigana LIKE '%' || ? || '%' OR {KEY_FIELD} LIKE '%' || ? || '%')
ORDER BY CAST(Sort AS INTEGER) ASC, GrammarPattern ASC
LIMIT 25;
"""

LEVEL_CHOICES = ["N5", "N4", "N3", "N2", "N1"]

LEVEL_COLOR = {
    "N5": discord.Color.green(),
    "N4": discord.Color.blue(),
    "N3": discord.Color.gold(),
    "N2": discord.Color.orange(),
    "N1": discord.Color.red(),
}

LIST_PAGE_SIZE = 10
# Token interaksi ephemeral kedaluwarsa ~15 menit — timeout view dipasang
# sedikit di bawah itu (sama seperti /grammar lama).
PAGINATOR_TIMEOUT_SECONDS = 800

MAX_FIELD_LENGTH = 1024
MAX_FIELDS_PER_EMBED = 25


# ============================================================================
# AUTOCOMPLETE
# ============================================================================

async def bunpou_autocomplete(interaction: discord.Interaction, current_input: str):
    """Saran pola berdasarkan GrammarPattern/GrammarFurigana/NoteID. Ikut
    difilter oleh parameter `level` kalau user sudah mengisinya duluan."""
    bot: KotabiBot = interaction.client
    current_input = current_input.strip()
    level = getattr(interaction.namespace, "level", None)

    if level:
        rows = await bot.GET(SEARCH_QUERY_LEVEL, (level, current_input, current_input, current_input))
    else:
        rows = await bot.GET(SEARCH_QUERY, (current_input, current_input, current_input))

    choices = []
    for note_id, pattern, furigana, meaning_id, _level in rows:
        meaning_preview = (meaning_id or "—").split(";")[0].strip()
        label = f"{pattern} ({furigana}) — {meaning_preview}"[:100]
        choices.append(discord.app_commands.Choice(name=label, value=note_id))
    return choices[:25]


# ============================================================================
# HELPERS
# ============================================================================

def _row_to_dict(row: tuple) -> dict:
    return dict(zip(FIELD_NAMES, row))


def _has_content(value: Optional[str]) -> bool:
    return bool(value) and value.strip() not in ("", "—")


def _add_requester_info(embed: discord.Embed, user: discord.User) -> discord.Embed:
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.set_footer(text=f"Diminta oleh @{user.name}")
    return embed


# Regex generik untuk memisahkan nama field berulang jadi (base, nomor_slot).
# Dipakai supaya rendering per-kategori tidak perlu tahu di muka field mana
# saja yang berulang & berapa banyak slotnya — semua diturunkan dari nama
# field di CATEGORY_FIELDS/FIELD_NAMES saat runtime.
_SLOT_RE = re.compile(r"^([A-Za-z]+?)(\d+)$")


def _split_base_slot(field_name: str) -> tuple[str, Optional[int]]:
    m = _SLOT_RE.match(field_name)
    if m:
        return m.group(1), int(m.group(2))
    return field_name, None


def _add_long_field(embed: discord.Embed, base_name: str, blocks: list[str]):
    """Gabungkan `blocks` (dipisah baris kosong) jadi satu/lebih field embed,
    otomatis dipecah kalau melebihi batas 1024 karakter atau 25 field
    per embed Discord."""
    if not blocks:
        return

    current = ""
    first = True
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > MAX_FIELD_LENGTH:
            name = base_name if first else f"{base_name} (lanjutan)"
            embed.add_field(name=name, value=current, inline=False)
            first = False
            current = block
        else:
            current = candidate

    if current:
        name = base_name if first else f"{base_name} (lanjutan)"
        embed.add_field(name=name, value=current, inline=False)


def _entry_title(entry: dict) -> str:
    """Judul embed dari kategori 'Info Pola': pola〈bracket kalau ada〉
    （furigana）★bintang — sesuai contoh やら di §8 panduan ringkas."""
    pattern = entry.get("GrammarPattern") or "—"
    furigana = entry.get("GrammarFurigana") or "—"
    star = entry.get("GrammarStar") or ""
    bracket = entry.get("GrammarBracket") or ""

    title = pattern
    if _has_content(bracket):
        title += bracket
    title += f"（{furigana}）"
    if _has_content(star):
        title += f" {star}"
    return title


def _entry_footer(entry: dict) -> str:
    """Footer dari kategori 'Pengelompokan/Tag' (minus Sort, yang selalu
    disembunyikan) — meniru pola 'Level: N2 · Ragam: Lisan' di §8."""
    parts = []
    level = entry.get("level")
    if _has_content(level):
        parts.append(f"Level: {level}")
    register = entry.get("GrammarRegister")
    if _has_content(register):
        parts.append(f"Ragam: {register}")
    frequency = entry.get("frequency")
    if _has_content(frequency):
        parts.append(f"Frekuensi: {frequency}")
    tags = entry.get("Tags")
    if _has_content(tags):
        parts.append(f"Tags: {tags}")
    return " · ".join(parts)


# ----------------------------------------------------------------------------
# Rendering per-slot untuk kelompok field berulang yang dikenal. Dispatch
# berdasarkan SET nama-base yang muncul di satu slot kategori, bukan
# berdasarkan nama kategori — supaya kalau grammar_fields.py menambah slot
# baru (mis. GrammarNoteJP8), kode ini otomatis ikut, tidak perlu diedit.
# ----------------------------------------------------------------------------

def _render_note_slot(slot_values: dict, slot_num: int) -> Optional[str]:
    jp = slot_values.get("GrammarNoteJP")
    idn = slot_values.get("GrammarNoteID")
    if not _has_content(jp) and not _has_content(idn):
        return None
    lines = [f"**{slot_num}.**"]
    if _has_content(jp):
        lines.append(f"🇯🇵 {jp}")
    if _has_content(idn):
        lines.append(f"🇮🇩 {idn}")
    return "\n".join(lines)


def _render_sentence_slot(slot_values: dict, slot_num: int) -> Optional[str]:
    kanji = slot_values.get("SentKanji")
    furigana = slot_values.get("SentFurigana")
    def_id = slot_values.get("SentDefID")
    sent_type = slot_values.get("SentType")
    if not _has_content(kanji) and not _has_content(furigana) and not _has_content(def_id):
        return None
    lines = []
    header = f"**Kalimat {slot_num}"
    if _has_content(sent_type):
        header += f" — {sent_type}"
    header += "**"
    lines.append(header)
    # Furigana sudah mengandung notasi kanji[bacaan] + <b>pola</b>, jadi
    # dipakai sebagai baris utama; SentKanji polos hanya fallback kalau
    # furigana kosong.
    if _has_content(furigana):
        lines.append(furigana)
    elif _has_content(kanji):
        lines.append(kanji)
    if _has_content(def_id):
        lines.append(f"🇮🇩 {def_id}")
    return "\n".join(lines)


def _render_audio_image_slot(base: str, value: str, slot_num: int) -> Optional[str]:
    if not _has_content(value):
        return None
    label = "🔊 Audio" if base == "SentAudio" else "🖼️ Gambar"
    return f"{label} {slot_num}: {value}"


def _render_formation(values: list[str]) -> Optional[str]:
    if not values:
        return None
    return "\n".join(f"{i}. {v}" for i, v in enumerate(values, start=1))


def _render_meaning(entry: dict) -> Optional[str]:
    meaning_id = entry.get("GrammarMeaningID")
    meaning_jp = entry.get("GrammarMeaningJP")
    if not _has_content(meaning_id) and not _has_content(meaning_jp):
        return None
    lines = []
    if _has_content(meaning_id):
        # Split ";" = makna berbeda, "," = sinonim dalam makna yang sama
        # (§3.6) — ditampilkan bernomor kalau lebih dari 1 makna.
        meanings = [m.strip() for m in meaning_id.split(";") if m.strip()]
        if len(meanings) > 1:
            for i, m in enumerate(meanings, start=1):
                lines.append(f"{i}. {m}")
        else:
            lines.append(meaning_id)
    if _has_content(meaning_jp):
        lines.append(f"🇯🇵 {meaning_jp}")
    return "\n".join(lines)


def _group_by_slot(fields: list[str], entry: dict) -> tuple[list[tuple[str, str]], dict[int, dict[str, str]]]:
    """Pisahkan daftar field satu kategori jadi (singles, slotted):
    - singles: field yang tidak berulang (tidak berakhiran angka), dengan
      isinya, dalam urutan CATEGORY_FIELDS.
    - slotted: {nomor_slot: {base_name: value}} untuk field yang berulang,
      HANYA untuk slot yang punya minimal satu isi.
    """
    singles: list[tuple[str, str]] = []
    slotted: dict[int, dict[str, str]] = {}

    for fname in fields:
        if fname in HIDDEN_FIELDS:
            continue
        value = entry.get(fname, "")
        base, slot = _split_base_slot(fname)
        if slot is not None:
            if _has_content(value):
                slotted.setdefault(slot, {})[base] = value
            else:
                slotted.setdefault(slot, {}).setdefault(base, value)
        else:
            singles.append((fname, value))

    # Buang slot yang ternyata semua base-nya kosong.
    slotted = {n: v for n, v in slotted.items() if any(_has_content(x) for x in v.values())}
    return singles, slotted


def render_category(entry: dict, category_name: str, fields: list[str]) -> list[tuple[str, str]]:
    """Render satu kategori (dari CATEGORY_FIELDS) jadi list (nama_field_embed,
    isi) siap ditaruh sebagai embed field. Generik terhadap jumlah slot —
    tidak hardcode berapa banyak GrammarNoteJP/ID atau SentX yang ada,
    semua diturunkan dari data yang benar-benar terisi di `entry`."""
    singles, slotted = _group_by_slot(fields, entry)
    output: list[tuple[str, str]] = []

    if category_name == "Cara Penyambungan":
        formation_values = [
            entry[f] for f in fields
            if _split_base_slot(f)[0] == "GrammarFormation" and _has_content(entry.get(f))
        ]
        formation_block = _render_formation(formation_values)
        if formation_block:
            output.append(("接続 (Cara Penyambungan)", formation_block))
        register = entry.get("GrammarRegister")
        if _has_content(register):
            output.append(("使用域 (Register)", register))

    elif category_name == "Makna":
        meaning_block = _render_meaning(entry)
        if meaning_block:
            output.append(("意味 (Makna)", meaning_block))

    elif category_name == "Catatan Penjelasan":
        blocks = []
        for slot_num in sorted(slotted):
            block = _render_note_slot(slotted[slot_num], slot_num)
            if block:
                blocks.append(block)
        if blocks:
            output.append(("備考 (Catatan)", "\n\n".join(blocks)))

    elif category_name == "Contoh Kalimat":
        blocks = []
        for slot_num in sorted(slotted):
            block = _render_sentence_slot(slotted[slot_num], slot_num)
            if block:
                blocks.append(block)
        if blocks:
            output.append(("例文 (Contoh Kalimat)", "\n\n".join(blocks)))

    elif category_name == "Audio & Gambar":
        lines = []
        for slot_num in sorted(slotted):
            for base, value in slotted[slot_num].items():
                line = _render_audio_image_slot(base, value, slot_num)
                if line:
                    lines.append(line)
        if lines:
            output.append(("音声・画像 (Audio & Gambar)", "\n".join(lines)))

    # "Pengelompokan/Tag" sengaja tidak dirender di sini — dipakai untuk
    # footer lewat _entry_footer(), bukan halaman/body (lihat FOOTER_CATEGORY).

    return output


def build_detail_pages(entry: dict) -> list[discord.Embed]:
    """Bangun halaman detail SECARA DINAMIS dari CATEGORY_FIELDS — jumlah
    halaman = jumlah kategori yang benar-benar punya isi setelah dikurangi
    kategori tersembunyi (Template Toggle) dan kategori judul/footer
    (Info Pola, Pengelompokan/Tag). Tidak ada angka halaman hardcode."""
    color = LEVEL_COLOR.get(entry.get("level"), discord.Color.blurple())
    title = f"📖 {_entry_title(entry)}"
    footer_text = _entry_footer(entry)

    pages: list[discord.Embed] = []
    for category_name, fields in CATEGORY_FIELDS.items():
        if category_name in HIDDEN_CATEGORIES or category_name == TITLE_CATEGORY or category_name == FOOTER_CATEGORY:
            continue

        rendered_fields = render_category(entry, category_name, fields)
        if not rendered_fields:
            continue

        embed = discord.Embed(title=title, color=color)
        for name, value in rendered_fields:
            _add_long_field(embed, name, [value])
        pages.append(embed)

    if not pages:
        # Fallback kalau entri kosong total selain Info Pola (seharusnya
        # tidak terjadi kalau validator dijalankan, tapi tetap dijaga).
        pages.append(discord.Embed(title=title, description="Tidak ada detail tambahan untuk entri ini.", color=color))

    total = len(pages)
    for idx, page in enumerate(pages, start=1):
        base_footer = f"Halaman {idx}/{total}"
        page.set_footer(text=f"{base_footer} • {footer_text}" if footer_text else base_footer)

    return pages


# ============================================================================
# MODE LIST/BROWSE
# ============================================================================

def _build_list_query(level: Optional[str]) -> tuple[str, tuple]:
    if level:
        query = f"{GET_ALL_FOR_LIST} WHERE level = ? ORDER BY CAST(Sort AS INTEGER) ASC;"
        return query, (level,)
    query = f"{GET_ALL_FOR_LIST} ORDER BY CAST(Sort AS INTEGER) ASC;"
    return query, ()


def _list_title(level: Optional[str]) -> str:
    if level:
        return f"📚 Kamus Grammar (Ringkas) — Level {level}"
    return "📚 Semua Entri Kamus Grammar (Ringkas)"


def build_list_pages(entries: list[dict], level: Optional[str]) -> tuple[list[discord.Embed], list[list[dict]]]:
    title = _list_title(level)
    chunks = [entries[i:i + LIST_PAGE_SIZE] for i in range(0, len(entries), LIST_PAGE_SIZE)] or [[]]
    total_pages = len(chunks)

    pages = []
    for idx, chunk in enumerate(chunks, start=1):
        lines = []
        for e in chunk:
            meaning = (e["GrammarMeaningID"] or "—").split(";")[0].strip()
            if len(meaning) > 60:
                meaning = meaning[:57] + "..."
            lines.append(f"**{e['GrammarPattern']}** （{e['GrammarFurigana']}） — {meaning} `{e['level'] or '—'}`")

        embed = discord.Embed(
            title=title,
            description="\n\n".join(lines) or "Tidak ada entri.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Halaman {idx}/{total_pages} • Total {len(entries)} entri")
        pages.append(embed)

    return pages, chunks


# ============================================================================
# PAGINATION VIEWS
# ============================================================================

class BunpouPaginatorView(discord.ui.View):
    """View Prev/Next generik untuk mode detail. Hanya pemanggil command asli yang bisa klik."""

    def __init__(self, owner_id: int, pages: list[discord.Embed]):
        super().__init__(timeout=PAGINATOR_TIMEOUT_SECONDS)
        self.owner_id = owner_id
        self.pages = pages
        self.index = 0
        self.message: Optional[discord.InteractionMessage] = None
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ini bukan pencarian kamu.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


class BunpouListView(discord.ui.View):
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
                label=f"{e['GrammarPattern']} ({e['GrammarFurigana']})"[:100],
                description=(e["GrammarMeaningID"] or "—").split(";")[0].strip()[:100],
                value=e[KEY_FIELD],
            )
            for e in entries
        ]
        select = discord.ui.Select(
            placeholder="Pilih entri untuk lihat detail lengkap...",
            options=options,
            row=0,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Ini bukan pencarian kamu.", ephemeral=True)

        note_id = interaction.data["values"][0]
        bot: KotabiBot = interaction.client
        row = await bot.GET_ONE(GET_ENTRY, (note_id,))
        if not row:
            return await interaction.response.send_message("❌ Entri tidak ditemukan lagi.", ephemeral=True)

        entry = _row_to_dict(row)
        detail_pages = build_detail_pages(entry)
        for p in detail_pages:
            _add_requester_info(p, interaction.user)

        detail_view = BunpouPaginatorView(interaction.user.id, detail_pages)
        await interaction.response.send_message(embed=detail_pages[0], view=detail_view, ephemeral=True)

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

class Bunpou(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        # --- Migration guard: buang tabel-tabel dari /grammar lama (format
        # 15-bagian relasional) sekali saat startup — lihat DEVELOPMENT_GUIDE.
        # Aman dijalankan berkali-kali (IF EXISTS), tidak menyentuh
        # bunpou_entries sama sekali.
        for old_table in ("grammar_entries", "grammar_translations", "grammar_key_sentences", "grammar_examples"):
            await self.bot.RUN(f"DROP TABLE IF EXISTS {old_table};")

        await self.bot.RUN(CREATE_TABLE)
        await self.load_csv()

    async def load_csv(self):
        """CSV adalah sumber kebenaran PENUH — full replace tiap reload,
        BUKAN upsert parsial (sumbernya flat, tidak ada relasi anak-tabel
        yang perlu diselaraskan terpisah seperti di /grammar lama)."""
        if not os.path.exists(CSV_PATH):
            _log.warning("⚠️ File %s tidak ditemukan. Kamus bunpou kosong.", CSV_PATH)
            return

        with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
            first_line = f.readline()
            if not first_line.lower().startswith(("#separator", "sep=")):
                # Bukan baris metadata Anki — file sudah tanpa baris sep=,
                # jadi baris pertama ini sebenarnya header, kembalikan ke awal.
                f.seek(0)

            reader = csv.DictReader(f, delimiter="\t")
            header = reader.fieldnames or []
            if header != FIELD_NAMES:
                _log.error(
                    "❌ Header %s TIDAK cocok dengan FIELD_NAMES di grammar_fields.py "
                    "— pemuatan dibatalkan supaya tidak salah petakan kolom diam-diam. "
                    "Header ditemukan: %s",
                    CSV_PATH, header,
                )
                return

            rows = []
            for row in reader:
                rows.append(tuple(row.get(col, "") for col in FIELD_NAMES))

        await self.bot.RUN(DELETE_ALL)
        if rows:
            await self.bot.RUN_MANY(INSERT_ENTRY, rows)

        _log.info("✅ %d entri bunpou dimuat dari %s.", len(rows), CSV_PATH)

    @discord.app_commands.command(
        name="bunpou",
        description="Cari pola grammar Jepang (versi ringkas) di kamus, atau jelajahi berdasarkan level JLPT.",
    )
    @discord.app_commands.describe(
        pola="Ketik pola, furigana, atau NoteID. Kalau diisi, level diabaikan untuk mode detail.",
        level="Filter berdasarkan level JLPT (opsional).",
    )
    @discord.app_commands.choices(
        level=[discord.app_commands.Choice(name=lvl, value=lvl) for lvl in LEVEL_CHOICES]
    )
    @discord.app_commands.autocomplete(pola=bunpou_autocomplete)
    @is_dic_access()
    async def bunpou(
        self,
        interaction: discord.Interaction,
        pola: Optional[str] = None,
        level: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        # Mode detail: pola diisi.
        if pola:
            row = await self.bot.GET_ONE(GET_ENTRY, (pola,))
            if not row:
                await interaction.followup.send(
                    "❌ Entri grammar tidak ditemukan. Gunakan menu autocomplete saat mengetik.",
                    ephemeral=True,
                )
                return

            entry = _row_to_dict(row)
            pages = build_detail_pages(entry)
            for p in pages:
                _add_requester_info(p, interaction.user)

            view = BunpouPaginatorView(interaction.user.id, pages)
            message = await interaction.followup.send(embed=pages[0], view=view, ephemeral=True, wait=True)
            view.message = message
            return

        # Mode list/browse: level / kosong.
        query, params = _build_list_query(level)
        rows = await self.bot.GET(query, params)

        if not rows:
            await interaction.followup.send(
                "❌ Tidak ada entri grammar yang cocok dengan filter tersebut.", ephemeral=True
            )
            return

        entries = [
            {"NoteID": r[0], "GrammarPattern": r[1], "GrammarFurigana": r[2], "GrammarMeaningID": r[3], "level": r[4]}
            for r in rows
        ]
        pages, page_entries = build_list_pages(entries, level)
        for p in pages:
            _add_requester_info(p, interaction.user)

        view = BunpouListView(interaction.user.id, pages, page_entries)
        message = await interaction.followup.send(embed=pages[0], view=view, ephemeral=True, wait=True)
        view.message = message

    @discord.app_commands.command(name="bunpou_reload", description="Muat ulang kamus bunpou dari CSV (Khusus Admin).")
    @discord.app_commands.default_permissions(administrator=True)
    async def bunpou_reload(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.load_csv()
        count_row = await self.bot.GET_ONE(f"SELECT COUNT(*) FROM {TABLE_NAME};")
        total = count_row[0] if count_row else 0
        await interaction.followup.send(f"✅ Kamus bunpou dimuat ulang. Total entri: **{total}**.", ephemeral=True)


async def setup(bot: KotabiBot):
    await bot.add_cog(Bunpou(bot))
