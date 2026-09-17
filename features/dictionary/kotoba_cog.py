"""
features/dictionary/kotoba_cog.py — Kamus Kosakata Jepang versi ringkas (/kotoba)
==================================================================================
Command baru untuk kamus kosakata (単語), format flat/ringkas 1 CSV datar:
    kotoba-notes-master.csv   (34 kolom, key field NoteID)

Meniru arsitektur `/bunpou` (features/dictionary/bunpou_cog.py) sepersis
mungkin: HTML->Markdown sanitizer yang sama, parser notasi furigana
`kanji[bacaan]` yang sama, migration-safe full-replace CSV loader, gating
akses lewat shared.checks.has_dic_access(), dan pola "mode list gratis,
mode detail terkunci Trial+" yang sama (lihat bagian 3.1/3.2 di panduan).

SKEMA: FIELD_NAMES / KEY_FIELD / CATEGORY_FIELDS diimpor LANGSUNG dari
kotoba_fields.py (bukan diduplikasi) — kalau skema field berubah, cukup edit
kotoba_fields.py, cog ini otomatis ikut menyesuaikan kolom tabel SQLite &
rendering kategori.

PERBEDAAN UTAMA DENGAN /bunpou:
- Kotoba cuma py 1 field makna (VocabDefID) dan 1 field catatan bebas
  (VocabPlus), TIDAK ada slot catatan berulang (GrammarNoteJP/ID1-7) seperti
  grammar — jadi tidak butuh logika _group_by_slot untuk kategori Makna atau
  Catatan.
- Cuma py 4 slot kalimat contoh (bukan 11), jadi seluruh detail entri MUAT
  di 1 halaman embed saja — TIDAK perlu pagination 2-halaman seperti
  /bunpou. Kalau suatu saat kontennya kepanjangan, _add_long_field() sudah
  otomatis memecah jadi beberapa field embed (bukan beberapa halaman).
- Audio (VocabAudio/SentAudio1-4) SENGAJA TIDAK dirender sama sekali untuk
  saat ini (lihat DISPLAYED_CATEGORIES) — kolomnya tetap ada di skema
  (kotoba_fields.py) untuk dipakai nanti. Kotoba tidak punya kolom gambar
  sama sekali di sumbernya (beda dari grammar).

--------------------------------------------------------------------
KEAMANAN SQL
--------------------------------------------------------------------
- CREATE TABLE memakai nama kolom dari FIELD_NAMES — konstanta tetap di
  kotoba_fields.py, bukan dari CSV atau input pengguna, jadi f-string di
  situ aman.
- Semua query yang menyentuh data dari CSV/input pengguna memakai
  parameter binding ("?"), tidak pernah string-interpolation langsung dari
  nilai data.
- Insert baris CSV memakai bot.RUN_MANY() (executemany), bukan bot.RUN().

--------------------------------------------------------------------
LOADER CSV (FULL REPLACE, BUKAN UPSERT PARSIAL)
--------------------------------------------------------------------
Sama seperti /bunpou: sumber CSV ini FLAT, jadi setiap cog_load() /
/kotoba_reload menjalankan full replace — DELETE semua baris di
kotoba_entries, lalu INSERT ulang semua baris dari CSV.

Format CSV: tab-delimited. Baris pertama BOLEH berupa metadata Anki
`#separator:Tab` (opsional, dilewati kalau ada) — kalau tidak ada, baris
pertama langsung dianggap header dan harus PERSIS cocok dengan FIELD_NAMES
(urutan & nama).

--------------------------------------------------------------------
RENDERING TEKS: HTML -> MARKDOWN & NOTASI FURIGANA
--------------------------------------------------------------------
Sama seperti /bunpou — lihat bunpou_cog.py untuk penjelasan lengkap kenapa
transformasi ini terjadi di layer render, bukan mengubah CSV:
- <b>...</b>  -> **...**  (bold pola/kata target di kalimat contoh)
- <s>...</s>  -> ~~...~~  (strikethrough)
- <br>        -> newline literal
- 'kanji[bacaan]' -> bacaan disembunyikan di balik spoiler Discord ||...||
  sebagai legenda terpisah, kalimat utama tampil bersih tanpa notasi bracket.
"""

import csv
import logging
import os
import re
from typing import Optional

import discord
from discord.ext import commands

from core.bot import KotabiBot
from shared.checks import has_dic_access, MSG_DIC_DETAIL_ONLY

from .kotoba_fields import FIELD_NAMES, KEY_FIELD, CATEGORY_FIELDS

_log = logging.getLogger("bot.kotoba")

# ============================================================================
# PATH & SKEMA
# ============================================================================

CSV_PATH = os.getenv("ALT_KOTOBA_CSV_PATH") or "features/dictionary/kotoba-notes-master.csv"

TABLE_NAME = "kotoba_entries"

_COLUMN_DEFS = ", ".join(
    f"{col} TEXT PRIMARY KEY" if col == KEY_FIELD else f"{col} TEXT"
    for col in FIELD_NAMES
)
CREATE_TABLE = f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} ({_COLUMN_DEFS});"

# NoteID = key internal, Sort = urutan tampilan internal — bukan info
# linguistik, jadi tidak pernah ditampilkan langsung ke user.
HIDDEN_FIELDS = {"NoteID", "Sort"}

DELETE_ALL = f"DELETE FROM {TABLE_NAME};"
INSERT_ENTRY = (
    f"INSERT INTO {TABLE_NAME} ({', '.join(FIELD_NAMES)}) "
    f"VALUES ({', '.join(['?'] * len(FIELD_NAMES))});"
)
GET_ENTRY = f"SELECT {', '.join(FIELD_NAMES)} FROM {TABLE_NAME} WHERE {KEY_FIELD} = ?;"
GET_ALL_FOR_LIST = f"SELECT {KEY_FIELD}, VocabKanji, VocabFurigana, VocabDefID, level FROM {TABLE_NAME}"

SEARCH_QUERY = f"""
SELECT {KEY_FIELD}, VocabKanji, VocabFurigana, VocabDefID, level FROM {TABLE_NAME}
WHERE VocabKanji LIKE '%' || ? || '%'
   OR VocabFurigana LIKE '%' || ? || '%'
   OR {KEY_FIELD} LIKE '%' || ? || '%'
ORDER BY CAST(Sort AS INTEGER) ASC, VocabKanji ASC
LIMIT 25;
"""

SEARCH_QUERY_LEVEL = f"""
SELECT {KEY_FIELD}, VocabKanji, VocabFurigana, VocabDefID, level FROM {TABLE_NAME}
WHERE level = ?
AND (VocabKanji LIKE '%' || ? || '%' OR VocabFurigana LIKE '%' || ? || '%' OR {KEY_FIELD} LIKE '%' || ? || '%')
ORDER BY CAST(Sort AS INTEGER) ASC, VocabKanji ASC
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
PAGINATOR_TIMEOUT_SECONDS = 800

MAX_FIELD_LENGTH = 1024

# Kategori yang benar-benar ditampilkan ke user, dalam urutan tampil.
# "Audio" sengaja TIDAK dimasukkan (lihat catatan di kotoba_fields.py) —
# aktifkan lagi kalau nanti file audio sudah di-hosting di tempat yang bisa
# dirujuk Discord (CDN/URL publik).
DISPLAYED_CATEGORIES = ["Info Kosakata", "Makna", "Catatan Tambahan", "Contoh Kalimat"]


# ============================================================================
# AUTOCOMPLETE
# ============================================================================

async def kotoba_autocomplete(interaction: discord.Interaction, current_input: str):
    """Saran kosakata berdasarkan VocabKanji/VocabFurigana/NoteID. Ikut
    difilter oleh parameter `level` kalau user sudah mengisinya duluan."""
    bot: KotabiBot = interaction.client
    current_input = current_input.strip()
    level = getattr(interaction.namespace, "level", None)

    if level:
        rows = await bot.GET(SEARCH_QUERY_LEVEL, (level, current_input, current_input, current_input))
    else:
        rows = await bot.GET(SEARCH_QUERY, (current_input, current_input, current_input))

    choices = []
    for note_id, kanji, furigana, def_id, _level in rows:
        meaning_preview = (def_id or "—").split(";")[0].strip()
        label = f"{kanji} ({furigana}) — {meaning_preview}"[:100]
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


# ----------------------------------------------------------------------------
# HTML -> Discord markdown sanitizer (identik dengan bunpou_cog.py)
# ----------------------------------------------------------------------------
_HTML_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_B_RE = re.compile(r"<b>(.*?)</b>", re.IGNORECASE | re.DOTALL)
_HTML_S_RE = re.compile(r"<s>(.*?)</s>", re.IGNORECASE | re.DOTALL)


def _sanitize_html(text: Optional[str]) -> str:
    """Konversi markup HTML ala Anki jadi markdown Discord. Aman dipanggil
    di field teks manapun (no-op kalau tidak ada 1 dari 3 tag di atas)."""
    if not text:
        return text or ""
    text = _HTML_BR_RE.sub("\n", text)
    text = _HTML_B_RE.sub(r"**\1**", text)
    text = _HTML_S_RE.sub(r"~~\1~~", text)
    return text


# ----------------------------------------------------------------------------
# Parser notasi furigana (field SentFurigana / VocabFurigana bila perlu)
# ----------------------------------------------------------------------------
_FURIGANA_TOKEN_RE = re.compile(r"([\u3005\u4e00-\u9fff0-9\uff10-\uff19]+)\[([^\[\]]*)\]")


def _parse_furigana_sentence(raw: Optional[str]) -> tuple[str, list[tuple[str, str]]]:
    """Parse notasi furigana Anki jadi (teks_tampil, legenda). Sama persis
    dengan versi di bunpou_cog.py — lihat komentar di sana untuk detail."""
    if not raw:
        return raw or "", []

    legend: list[tuple[str, str]] = []

    def _replace(m: re.Match) -> str:
        word, reading = m.group(1), m.group(2)
        legend.append((word, reading))
        return word

    display = _FURIGANA_TOKEN_RE.sub(_replace, raw)
    display = display.replace(" ", "")
    return display, legend


def _build_furigana_legend(legend: list[tuple[str, str]]) -> str:
    if not legend:
        return ""
    return "・".join(f"{w}={r}" for w, r in legend)


def _render_jp_text(raw: Optional[str]) -> str:
    """Sanitizer + parser gabungan untuk field bahasa Jepang mana pun yang
    bisa mengandung notasi furigana 'kanji[bacaan]'."""
    if not _has_content(raw):
        return raw or ""
    sanitized = _sanitize_html(raw)
    display, legend = _parse_furigana_sentence(sanitized)
    legend_text = _build_furigana_legend(legend)
    if legend_text:
        return f"{display} ||{legend_text}||"
    return display


def _add_long_field(embed: discord.Embed, base_name: str, blocks: list[str]):
    """Gabungkan `blocks` (dipisah baris kosong) jadi satu/lebih field embed,
    otomatis dipecah kalau melebihi batas 1024 karakter Discord."""
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
    """Judul embed dari kategori 'Info Kosakata': kanji（furigana）｟pitch｠ pos."""
    kanji = entry.get("VocabKanji") or "—"
    furigana = entry.get("VocabFurigana") or "—"
    pitch = entry.get("VocabPitch") or ""
    pos = entry.get("VocabPoS") or ""

    title = kanji
    if furigana != kanji:
        title += f"（{furigana}）"
    if _has_content(pitch):
        title += f" {pitch}"
    if _has_content(pos):
        title += f" ・{pos}"
    return title


def _entry_footer(entry: dict) -> str:
    """Footer dari kategori 'Pengelompokan/Tag' (minus Sort, selalu
    disembunyikan)."""
    parts = []
    level = entry.get("level")
    if _has_content(level):
        parts.append(f"Level: {level}")
    frequency = entry.get("frequency")
    if _has_content(frequency):
        parts.append(f"Frekuensi: {frequency}")
    tags = entry.get("Tags")
    if _has_content(tags):
        parts.append(f"Tags: {tags}")
    return " · ".join(parts)


def _render_meaning(entry: dict) -> Optional[str]:
    def_id = entry.get("VocabDefID")
    if not _has_content(def_id):
        return None
    # Split ";" = makna berbeda, "," = sinonim dalam makna yang sama —
    # delimiter sama seperti VocabDefID di /bunpou (GrammarMeaningID).
    meanings = [m.strip() for m in def_id.split(";") if m.strip()]
    if len(meanings) > 1:
        return "\n".join(f"{i}. {_sanitize_html(m)}" for i, m in enumerate(meanings, start=1))
    return _sanitize_html(def_id)


def _render_note(entry: dict) -> Optional[str]:
    plus = entry.get("VocabPlus")
    if not _has_content(plus):
        return None
    return _render_jp_text(plus)


def _render_sentence_slot(entry: dict, slot_num: int) -> Optional[str]:
    kanji = entry.get(f"SentKanji{slot_num}")
    furigana = entry.get(f"SentFurigana{slot_num}")
    def_id = entry.get(f"SentDefID{slot_num}")
    sent_type = entry.get(f"SentType{slot_num}")
    if not _has_content(kanji) and not _has_content(furigana) and not _has_content(def_id):
        return None

    lines = []
    header = f"**Kalimat {slot_num}"
    if _has_content(sent_type):
        header += f" — {sent_type}"
    header += "**"
    lines.append(header)

    # Furigana sudah mengandung notasi kanji[bacaan] + <b>kata</b>, dipakai
    # sebagai baris utama; SentKanji polos hanya fallback kalau kosong.
    if _has_content(furigana):
        sanitized = _sanitize_html(furigana)
        display, legend = _parse_furigana_sentence(sanitized)
        lines.append(display)
        legend_text = _build_furigana_legend(legend)
        if legend_text:
            lines.append(f"||{legend_text}||")
    elif _has_content(kanji):
        lines.append(_sanitize_html(kanji))

    if _has_content(def_id):
        lines.append(f"🇮🇩 {_sanitize_html(def_id)}")
    return "\n".join(lines)


def render_category(entry: dict, category_name: str) -> list[tuple[str, str]]:
    """Render satu kategori jadi list (nama_field_embed, isi) siap ditaruh
    sebagai embed field."""
    output: list[tuple[str, str]] = []

    if category_name == "Makna":
        meaning_block = _render_meaning(entry)
        if meaning_block:
            output.append(("意味 (Makna)", meaning_block))

    elif category_name == "Catatan Tambahan":
        note_block = _render_note(entry)
        if note_block:
            output.append(("備考 (Catatan Tambahan)", note_block))

    elif category_name == "Contoh Kalimat":
        blocks = []
        for slot_num in range(1, 5):
            block = _render_sentence_slot(entry, slot_num)
            if block:
                blocks.append(block)
        if blocks:
            output.append(("例文 (Contoh Kalimat)", "\n\n".join(blocks)))

    return output


def build_detail_embed(entry: dict) -> discord.Embed:
    """Bangun 1 embed detail lengkap. Berbeda dari /bunpou, kotoba TIDAK
    butuh pagination 2-halaman karena cuma py 4 slot kalimat contoh — semua
    muat dalam 1 embed (dengan _add_long_field otomatis memecah field kalau
    kepanjangan, bukan memecah halaman)."""
    color = LEVEL_COLOR.get(entry.get("level"), discord.Color.blurple())
    title = f"📖 {_entry_title(entry)}"
    footer_text = _entry_footer(entry)

    embed = discord.Embed(title=title, color=color)

    has_any = False
    for category_name in DISPLAYED_CATEGORIES:
        if category_name == "Info Kosakata":
            # Sudah masuk ke judul embed, tidak perlu field terpisah.
            continue
        for name, value in render_category(entry, category_name):
            _add_long_field(embed, name, [value])
            has_any = True

    if not has_any:
        embed.description = "Tidak ada detail tambahan untuk entri ini."

    if footer_text:
        embed.set_footer(text=footer_text)

    return embed


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
        return f"📚 Kamus Kotoba (Ringkas) — Level {level}"
    return "📚 Semua Entri Kamus Kotoba (Ringkas)"


def build_list_pages(
    entries: list[dict], level: Optional[str], show_meaning: bool = True
) -> tuple[list[discord.Embed], list[list[dict]]]:
    """Kolom arti HANYA ditampilkan kalau show_meaning=True (Companion ke
    atas) — sesuai pola yang sama dengan /bunpou: mode list tetap terbuka
    penuh untuk semua role (nama kata + level), payoff (artinya) khusus
    yang bayar."""
    title = _list_title(level)
    chunks = [entries[i:i + LIST_PAGE_SIZE] for i in range(0, len(entries), LIST_PAGE_SIZE)] or [[]]
    total_pages = len(chunks)

    pages = []
    for idx, chunk in enumerate(chunks, start=1):
        lines = []
        for e in chunk:
            kanji = e["VocabKanji"]
            furigana = e["VocabFurigana"]
            name_part = kanji if furigana == kanji else f"{kanji}（{furigana}）"
            level_tag = f"`{e['level']}`" if e["level"] else ""
            header_line = f"**{name_part}** {level_tag}".rstrip()

            if show_meaning:
                meaning = (e["VocabDefID"] or "—").split(";")[0].strip()
                if len(meaning) > 60:
                    meaning = meaning[:57] + "..."
                lines.append(f"{header_line}\n{meaning}")
            else:
                lines.append(header_line)

        embed = discord.Embed(
            title=title,
            description="\n\n".join(lines) or "Tidak ada entri.",
            color=discord.Color.blurple(),
        )
        footer = f"Halaman {idx}/{total_pages} • Total {len(entries)} entri"
        if not show_meaning:
            footer += " • Arti terkunci, upgrade Companion untuk lihat detail"
        embed.set_footer(text=footer)
        pages.append(embed)

    return pages, chunks


# ============================================================================
# PAGINATION VIEWS
# ============================================================================

class KotobaListView(discord.ui.View):
    def __init__(
        self,
        owner_id: int,
        pages: list[discord.Embed],
        page_entries: list[list[dict]],
        show_meaning: bool = True,
    ):
        super().__init__(timeout=PAGINATOR_TIMEOUT_SECONDS)
        self.owner_id = owner_id
        self.pages = pages
        self.page_entries = page_entries
        # Dropdown "pilih untuk detail" adalah titik masuk detail TERPISAH
        # dari command awal — akses detail dicek ULANG di _on_select(),
        # bukan cuma diwariskan dari sini.
        self.show_meaning = show_meaning
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
                label=f"{e['VocabKanji']} ({e['VocabFurigana']})"[:100],
                description=(
                    (e["VocabDefID"] or "—").split(";")[0].strip()[:100]
                    if self.show_meaning else "🔒 Upgrade Companion untuk lihat arti & detail"
                ),
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

        # Celah arsitektur (sama seperti /bunpou): dropdown ini interaksi
        # komponen, bukan slash command baru — access check WAJIB dicek
        # ulang di sini, bukan cuma diwariskan dari command awal.
        if not has_dic_access(interaction.user, interaction.guild_id):
            return await interaction.response.send_message(MSG_DIC_DETAIL_ONLY, ephemeral=True)

        note_id = interaction.data["values"][0]
        bot: KotabiBot = interaction.client
        row = await bot.GET_ONE(GET_ENTRY, (note_id,))
        if not row:
            return await interaction.response.send_message("❌ Entri tidak ditemukan lagi.", ephemeral=True)

        entry = _row_to_dict(row)
        embed = build_detail_embed(entry)
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

class Kotoba(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.RUN(CREATE_TABLE)
        await self.load_csv()

    async def load_csv(self):
        """CSV adalah sumber kebenaran PENUH — full replace tiap reload,
        sama seperti /bunpou (sumbernya flat, tidak ada relasi anak-tabel
        yang perlu diselaraskan terpisah)."""
        if not os.path.exists(CSV_PATH):
            _log.warning("⚠️ File %s tidak ditemukan. Kamus kotoba kosong.", CSV_PATH)
            return

        with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
            first_line = f.readline()
            if not first_line.lower().startswith(("#separator", "sep=")):
                # Bukan baris metadata Anki — baris pertama ini sebenarnya
                # header, kembalikan ke awal.
                f.seek(0)

            reader = csv.DictReader(f, delimiter="\t")
            header = reader.fieldnames or []
            if header != FIELD_NAMES:
                _log.error(
                    "❌ Header %s TIDAK cocok dengan FIELD_NAMES di kotoba_fields.py "
                    "— pemuatan dibatalkan supaya tidak salah petakan kolom diam-diam. "
                    "Header ditemukan: %s",
                    CSV_PATH, header,
                )
                return

            rows = []
            for row in reader:
                rows.append(tuple(row.get(col, "") for col in FIELD_NAMES))

        # atomik -- lihat core/bot.py TRANSAKSI()
        async with self.bot.TRANSAKSI() as db:
            await db.execute(DELETE_ALL)
            if rows:
                await db.executemany(INSERT_ENTRY, rows)

        _log.info("✅ %d entri kotoba dimuat dari %s.", len(rows), CSV_PATH)

    @discord.app_commands.command(
        name="kotoba",
        description="Cari kosakata Jepang (versi ringkas) di kamus, atau jelajahi berdasarkan level JLPT.",
    )
    @discord.app_commands.describe(
        kata="Ketik kata, furigana, atau NoteID. Kalau diisi, level diabaikan untuk mode detail.",
        level="Filter berdasarkan level JLPT (opsional).",
    )
    @discord.app_commands.choices(
        level=[discord.app_commands.Choice(name=lvl, value=lvl) for lvl in LEVEL_CHOICES]
    )
    @discord.app_commands.autocomplete(kata=kotoba_autocomplete)
    @discord.app_commands.guild_only()
    async def kotoba(
        self,
        interaction: discord.Interaction,
        kata: Optional[str] = None,
        level: Optional[str] = None,
    ):
        # Command TIDAK di-gate akses — mode list terbuka untuk semua role
        # (termasuk Drifter tanpa membership sama sekali). Access check
        # detail dicek eksplisit di sini DAN di KotobaListView._on_select
        # (celah dropdown).
        await interaction.response.defer(ephemeral=True)

        # Mode detail: kata diisi.
        if kata:
            if not has_dic_access(interaction.user, interaction.guild_id):
                await interaction.followup.send(MSG_DIC_DETAIL_ONLY, ephemeral=True)
                return

            row = await self.bot.GET_ONE(GET_ENTRY, (kata,))
            if not row:
                await interaction.followup.send(
                    "❌ Entri kosakata tidak ditemukan. Gunakan menu autocomplete saat mengetik.",
                    ephemeral=True,
                )
                return

            entry = _row_to_dict(row)
            embed = build_detail_embed(entry)
            _add_requester_info(embed, interaction.user)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Mode list/browse: level / kosong.
        query, params = _build_list_query(level)
        rows = await self.bot.GET(query, params)

        if not rows:
            await interaction.followup.send(
                "❌ Tidak ada entri kosakata yang cocok dengan filter tersebut.", ephemeral=True
            )
            return

        entries = [
            {"NoteID": r[0], "VocabKanji": r[1], "VocabFurigana": r[2], "VocabDefID": r[3], "level": r[4]}
            for r in rows
        ]
        show_meaning = has_dic_access(interaction.user, interaction.guild_id)
        pages, page_entries = build_list_pages(entries, level, show_meaning=show_meaning)
        for p in pages:
            _add_requester_info(p, interaction.user)

        view = KotobaListView(interaction.user.id, pages, page_entries, show_meaning=show_meaning)
        message = await interaction.followup.send(embed=pages[0], view=view, ephemeral=True, wait=True)
        view.message = message

    @discord.app_commands.command(name="kotoba_reload", description="Muat ulang kamus kotoba dari CSV (Khusus Admin).")
    @discord.app_commands.default_permissions(administrator=True)
    async def kotoba_reload(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.load_csv()
        count_row = await self.bot.GET_ONE(f"SELECT COUNT(*) FROM {TABLE_NAME};")
        total = count_row[0] if count_row else 0
        await interaction.followup.send(f"✅ Kamus kotoba dimuat ulang. Total entri: **{total}**.", ephemeral=True)


async def setup(bot: KotabiBot):
    await bot.add_cog(Kotoba(bot))
