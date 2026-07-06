"""
features/dictionary/grammar_cog.py — Kamus Grammar Jepang (/grammar)
=====================================================================
Sumber data: 4 CSV relational (Opsi B) di features/dictionary/:
    grammar_entries.csv        (identitas + metadata + ①②③④⑤⑥⑧⑪⑫⑬⑭⑮)
    grammar_translations.csv   (⑦ Translations, per makna)
    grammar_key_sentences.csv  (⑨ Key Sentences, per pola)
    grammar_examples.csv       (⑩ Examples, per fungsi)

Mengikuti "Panduan Membuat Entri Kamus Grammar Bahasa Jepang" (Kotabi
Style Guide, 15 bagian ①–⑮) bagian 7 (Opsi B — relational) dan bagian 10
(Rencana Implementasi Command Discord /grammar):

  - Tiga parameter opsional & independen: pola (autocomplete), jlpt
    (pilihan N5-N1), huruf_awal (romaji ATAU hiragana). Kalau `pola`
    diisi, `jlpt` dan `huruf_awal` diabaikan (10.2).
  - Mode "1 entri detail" dipecah 6 halaman mengikuti pengelompokan 15
    bagian format Kotabi (10.3):
      1. ①②③④⑤   — Grammar Entry, Reading, JLPT, Part of Speech, Register
      2. ⑥⑦       — Meaning/Function + Translations
      3. ⑧⑨       — Formation + Key Sentences
      4. ⑩         — Examples
      5. ⑪⑫       — Nuance + Common Mistakes
      6. ⑬⑭⑮     — Related Expressions + Comparison + Notes
  - Mode "list/browse" (jlpt / huruf_awal / kosong) TERPAGINASI, dengan
    dropdown per halaman untuk loncat langsung ke mode detail.
  - Semua respons ephemeral, plus pagination sebagai proteksi anti-copy
    tambahan (10.4).
  - Setiap embed menampilkan info pemohon (foto profil, nama tampilan,
    username) di author/footer.
  - Gating akses via shared/checks.py::is_dic_access() — Trial dapat,
    Traveler TIDAK dapat, Companion/Patron dapat, staff & admin selalu
    dapat (10.5). Trial mengikuti masa berlaku trial 5 hari biasa, TIDAK
    ada limiter jumlah pencarian terpisah.

CSV adalah sumber kebenaran: setiap cog_load(), isi keempat CSV
di-upsert ulang ke 4 tabel SQLite bernama sama (aman dijalankan berkali-
kali). Kalau mau menambah/mengubah entri, cukup edit CSV lalu
restart/reload cog ini (atau /grammar_reload) — tidak perlu query
manual ke database.

Path CSV bisa dioverride lewat env var ALT_GRAMMAR_*_CSV_PATH, mengikuti
pola ALT_*_PATH yang sudah dipakai cog lain di project ini.

--------------------------------------------------------------------
AUTO SCHEMA MIGRATION (FIX):
--------------------------------------------------------------------
`CREATE TABLE IF NOT EXISTS` HANYA membuat tabel kalau belum ada sama
sekali. Kalau tabel sudah pernah dibuat oleh versi kode LAMA (sebelum
sebuah kolom baru ditambahkan ke skema, mis. `reading_secondary`),
statement itu tidak berbuat apa-apa lagi — kolom baru tidak pernah
benar-benar tercermin ke database fisik (data/db.sqlite3, yang persist
lewat bind mount Docker). Akibatnya UPSERT saat load_csv() gagal dengan
`OperationalError: table X has no column named Y`.

Untuk mencegah ini terulang tiap kali skema CSV/kolom baru ditambahkan,
cog_load() sekarang menjalankan _ensure_columns() untuk keempat tabel:
mengecek kolom yang benar-benar ada di database (lewat PRAGMA
table_info), lalu menjalankan `ALTER TABLE ... ADD COLUMN ...` untuk
kolom yang didefinisikan di kode tapi belum ada di database. Ini aman
dijalankan berkali-kali (idempotent) dan tidak pernah menghapus data.
"""

import csv
import logging
import os
from typing import Optional

import discord
from discord.ext import commands

from core.bot import KotabiBot
from shared.checks import is_dic_access

_log = logging.getLogger("bot.grammar")

# ============================================================================
# PATH & SKEMA
# ============================================================================

ENTRIES_CSV_PATH = os.getenv("ALT_GRAMMAR_ENTRIES_CSV_PATH") or "features/dictionary/grammar_entries.csv"
TRANSLATIONS_CSV_PATH = os.getenv("ALT_GRAMMAR_TRANSLATIONS_CSV_PATH") or "features/dictionary/grammar_translations.csv"
KEY_SENTENCES_CSV_PATH = os.getenv("ALT_GRAMMAR_KEY_SENTENCES_CSV_PATH") or "features/dictionary/grammar_key_sentences.csv"
EXAMPLES_CSV_PATH = os.getenv("ALT_GRAMMAR_EXAMPLES_CSV_PATH") or "features/dictionary/grammar_examples.csv"

ENTRIES_COLUMNS = [
    "id", "romaji", "kana", "reading_secondary", "kanji", "jlpt", "jlpt_order",
    "part_of_speech", "part_of_speech_subtype", "usage_register", "frequency",
    "meaning_en", "meaning_id", "formation", "nuance", "common_mistakes",
    "related_expression", "related_expression_detail", "notes_en", "notes_id",
    "tags", "rujukan_silang", "status",
]
TRANSLATIONS_COLUMNS = ["entry_id", "meaning_label", "language", "term", "urutan"]
KEY_SENTENCES_COLUMNS = ["entry_id", "pattern_name", "jp", "id_terjemahan", "urutan"]
EXAMPLES_COLUMNS = ["entry_id", "function_label", "jp", "en", "id_terjemahan", "urutan"]

CREATE_TABLES = [
    """CREATE TABLE IF NOT EXISTS grammar_entries (
        id TEXT PRIMARY KEY,
        romaji TEXT, kana TEXT, reading_secondary TEXT, kanji TEXT,
        jlpt TEXT, jlpt_order INTEGER,
        part_of_speech TEXT, part_of_speech_subtype TEXT,
        usage_register TEXT, frequency TEXT,
        meaning_en TEXT, meaning_id TEXT,
        formation TEXT, nuance TEXT, common_mistakes TEXT,
        related_expression TEXT, related_expression_detail TEXT,
        notes_en TEXT, notes_id TEXT,
        tags TEXT, rujukan_silang TEXT, status TEXT
    );""",
    """CREATE TABLE IF NOT EXISTS grammar_translations (
        entry_id TEXT, meaning_label TEXT, language TEXT, term TEXT, urutan INTEGER,
        FOREIGN KEY(entry_id) REFERENCES grammar_entries(id)
    );""",
    """CREATE TABLE IF NOT EXISTS grammar_key_sentences (
        entry_id TEXT, pattern_name TEXT, jp TEXT, id_terjemahan TEXT, urutan INTEGER,
        FOREIGN KEY(entry_id) REFERENCES grammar_entries(id)
    );""",
    """CREATE TABLE IF NOT EXISTS grammar_examples (
        entry_id TEXT, function_label TEXT, jp TEXT, en TEXT, id_terjemahan TEXT, urutan INTEGER,
        FOREIGN KEY(entry_id) REFERENCES grammar_entries(id)
    );""",
]

# ----------------------------------------------------------------------------
# AUTO SCHEMA MIGRATION — daftar kolom + tipe SQL untuk tiap tabel.
# Dipakai oleh _ensure_columns() untuk ALTER TABLE ADD COLUMN kalau ada
# kolom yang didefinisikan di sini tapi belum ada di database fisik.
# Kalau menambah kolom baru ke skema di masa depan, CUKUP tambahkan di
# sini (dan di *_COLUMNS list + CSV terkait) — tidak perlu drop table lagi.
# ----------------------------------------------------------------------------

ENTRIES_COLUMN_TYPES = {
    "romaji": "TEXT",
    "kana": "TEXT",
    "reading_secondary": "TEXT",
    "kanji": "TEXT",
    "jlpt": "TEXT",
    "jlpt_order": "INTEGER",
    "part_of_speech": "TEXT",
    "part_of_speech_subtype": "TEXT",
    "usage_register": "TEXT",
    "frequency": "TEXT",
    "meaning_en": "TEXT",
    "meaning_id": "TEXT",
    "formation": "TEXT",
    "nuance": "TEXT",
    "common_mistakes": "TEXT",
    "related_expression": "TEXT",
    "related_expression_detail": "TEXT",
    "notes_en": "TEXT",
    "notes_id": "TEXT",
    "tags": "TEXT",
    "rujukan_silang": "TEXT",
    "status": "TEXT",
}

TRANSLATIONS_COLUMN_TYPES = {
    "entry_id": "TEXT",
    "meaning_label": "TEXT",
    "language": "TEXT",
    "term": "TEXT",
    "urutan": "INTEGER",
}

KEY_SENTENCES_COLUMN_TYPES = {
    "entry_id": "TEXT",
    "pattern_name": "TEXT",
    "jp": "TEXT",
    "id_terjemahan": "TEXT",
    "urutan": "INTEGER",
}

EXAMPLES_COLUMN_TYPES = {
    "entry_id": "TEXT",
    "function_label": "TEXT",
    "jp": "TEXT",
    "en": "TEXT",
    "id_terjemahan": "TEXT",
    "urutan": "INTEGER",
}

# Daftar (nama_tabel, dict_kolom_tipe) yang di-scan tiap cog_load().
SCHEMA_MIGRATIONS = [
    ("grammar_entries", ENTRIES_COLUMN_TYPES),
    ("grammar_translations", TRANSLATIONS_COLUMN_TYPES),
    ("grammar_key_sentences", KEY_SENTENCES_COLUMN_TYPES),
    ("grammar_examples", EXAMPLES_COLUMN_TYPES),
]


async def _ensure_columns(bot: KotabiBot, table_name: str, expected_columns: dict[str, str]):
    """
    Bandingkan kolom yang seharusnya ada (expected_columns) dengan kolom
    yang benar-benar ada di tabel `table_name` (lewat PRAGMA table_info),
    lalu ALTER TABLE ADD COLUMN untuk kolom yang hilang.

    Aman dijalankan berkali-kali — kalau semua kolom sudah lengkap, tidak
    melakukan apa-apa. Tidak pernah menghapus atau mengubah data yang
    sudah ada.
    """
    try:
        existing_rows = await bot.GET(f"PRAGMA table_info({table_name});")
    except Exception as e:
        _log.error("❌ Gagal membaca skema tabel %s: %s", table_name, e)
        return

    # PRAGMA table_info mengembalikan baris: (cid, name, type, notnull, dflt_value, pk)
    existing_columns = {row[1] for row in existing_rows}

    for column_name, column_type in expected_columns.items():
        if column_name in existing_columns:
            continue
        try:
            await bot.RUN(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type};")
            _log.info(
                "✅ Auto-migrasi: kolom '%s' (%s) berhasil ditambahkan ke tabel '%s'.",
                column_name, column_type, table_name,
            )
        except Exception as e:
            _log.error(
                "❌ Auto-migrasi GAGAL menambahkan kolom '%s' ke tabel '%s': %s",
                column_name, table_name, e,
            )


UPSERT_ENTRY = f"""
INSERT INTO grammar_entries ({', '.join(ENTRIES_COLUMNS)})
VALUES ({', '.join(['?'] * len(ENTRIES_COLUMNS))})
ON CONFLICT(id) DO UPDATE SET {', '.join(f"{c}=excluded.{c}" for c in ENTRIES_COLUMNS if c != 'id')};
"""

DELETE_CHILD_ROWS = [
    "DELETE FROM grammar_translations WHERE entry_id = ?;",
    "DELETE FROM grammar_key_sentences WHERE entry_id = ?;",
    "DELETE FROM grammar_examples WHERE entry_id = ?;",
]

INSERT_TRANSLATION = f"INSERT INTO grammar_translations ({', '.join(TRANSLATIONS_COLUMNS)}) VALUES ({', '.join(['?'] * len(TRANSLATIONS_COLUMNS))});"
INSERT_KEY_SENTENCE = f"INSERT INTO grammar_key_sentences ({', '.join(KEY_SENTENCES_COLUMNS)}) VALUES ({', '.join(['?'] * len(KEY_SENTENCES_COLUMNS))});"
INSERT_EXAMPLE = f"INSERT INTO grammar_examples ({', '.join(EXAMPLES_COLUMNS)}) VALUES ({', '.join(['?'] * len(EXAMPLES_COLUMNS))});"

SEARCH_QUERY = """
SELECT id, romaji, kana, meaning_id, jlpt FROM grammar_entries
WHERE romaji LIKE '%' || ? || '%'
   OR kana LIKE '%' || ? || '%'
   OR id LIKE '%' || ? || '%'
ORDER BY jlpt_order ASC, romaji ASC
LIMIT 25;
"""

SEARCH_QUERY_JLPT = """
SELECT id, romaji, kana, meaning_id, jlpt FROM grammar_entries
WHERE jlpt = ?
AND (romaji LIKE '%' || ? || '%' OR kana LIKE '%' || ? || '%' OR id LIKE '%' || ? || '%')
ORDER BY jlpt_order ASC, romaji ASC
LIMIT 25;
"""

GET_ENTRY = f"SELECT {', '.join(ENTRIES_COLUMNS)} FROM grammar_entries WHERE id = ?;"
GET_TRANSLATIONS = "SELECT meaning_label, language, term, urutan FROM grammar_translations WHERE entry_id = ? ORDER BY meaning_label, language, urutan ASC;"
GET_KEY_SENTENCES = "SELECT pattern_name, jp, id_terjemahan, urutan FROM grammar_key_sentences WHERE entry_id = ? ORDER BY urutan ASC;"
GET_EXAMPLES = "SELECT function_label, jp, en, id_terjemahan, urutan FROM grammar_examples WHERE entry_id = ? ORDER BY urutan ASC;"

LIST_BASE_SELECT = "SELECT id, romaji, kana, meaning_id, jlpt FROM grammar_entries"

JLPT_CHOICES = ["N5", "N4", "N3", "N2", "N1"]

JLPT_COLOR = {
    "N5": discord.Color.green(),
    "N4": discord.Color.blue(),
    "N3": discord.Color.gold(),
    "N2": discord.Color.orange(),
    "N1": discord.Color.red(),
}

LIST_PAGE_SIZE = 10
# Token interaksi ephemeral kedaluwarsa ~15 menit (10.3) — timeout view
# dipasang sedikit di bawah itu.
PAGINATOR_TIMEOUT_SECONDS = 800


# ============================================================================
# AUTOCOMPLETE
# ============================================================================

async def grammar_autocomplete(interaction: discord.Interaction, current_input: str):
    """Saran pola grammar berdasarkan romaji/kana/id. Ikut difilter oleh
    parameter `jlpt` kalau user sudah mengisinya duluan."""
    bot: KotabiBot = interaction.client
    current_input = current_input.strip()
    jlpt = getattr(interaction.namespace, "jlpt", None)

    if jlpt:
        rows = await bot.GET(SEARCH_QUERY_JLPT, (jlpt, current_input, current_input, current_input))
    else:
        rows = await bot.GET(SEARCH_QUERY, (current_input, current_input, current_input))

    choices = []
    for entry_id, romaji, kana, meaning_id, _jlpt in rows:
        label = f"{romaji} ({kana}) — {meaning_id}"[:100]
        choices.append(discord.app_commands.Choice(name=label, value=entry_id))
    return choices[:25]


# ============================================================================
# HELPERS
# ============================================================================

def _row_to_dict(row: tuple) -> dict:
    return dict(zip(ENTRIES_COLUMNS, row))


def _has_content(value: Optional[str]) -> bool:
    return bool(value) and value not in ("—", "")


def _add_requester_info(embed: discord.Embed, user: discord.User) -> discord.Embed:
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.set_footer(text=f"Diminta oleh @{user.name}")
    return embed


def _translations_by_meaning(rows: list[tuple]) -> dict[str, dict[str, list[str]]]:
    """rows -> {meaning_label: {"en": [...], "id": [...]}}"""
    grouped: dict[str, dict[str, list[str]]] = {}
    for meaning_label, language, term, _urutan in rows:
        grouped.setdefault(meaning_label, {"en": [], "id": []})
        grouped[meaning_label][language].append(term)
    return grouped


# ============================================================================
# MODE DETAIL — 6 halaman (10.3)
# ============================================================================

def _detail_base_embed(entry: dict, page_label: str) -> discord.Embed:
    title = entry["romaji"]
    if _has_content(entry.get("kanji")):
        title += f"（{entry['kanji']}）"
    elif entry.get("kana"):
        title += f"（{entry['kana']}）"

    color = JLPT_COLOR.get(entry.get("jlpt"), discord.Color.blurple())
    embed = discord.Embed(title=f"📖 {title}", color=color)

    footer_bits = [page_label]
    if entry.get("id"):
        footer_bits.append(f"ID: {entry['id']}")
    embed.set_footer(text=" | ".join(footer_bits))
    return embed


def build_detail_pages(
    entry: dict,
    translation_rows: list[tuple],
    key_sentence_rows: list[tuple],
    example_rows: list[tuple],
) -> list[discord.Embed]:
    """Menyusun data dari 4 tabel jadi 6 embed berurutan sesuai §10.3."""
    pages = []

    # Halaman 1: ①②③④⑤
    p1 = _detail_base_embed(entry, "Halaman 1/6")
    reading = entry["kana"]
    if _has_content(entry.get("reading_secondary")):
        reading += f"　(varian lisan: {entry['reading_secondary']})"
    pos = entry["part_of_speech"]
    if _has_content(entry.get("part_of_speech_subtype")):
        pos += f" ({entry['part_of_speech_subtype']})"
    register = entry.get("usage_register") or "—"
    if _has_content(entry.get("frequency")):
        register += f"　{entry['frequency']}"
    p1.description = (
        f"**② 読み方:** {reading}\n"
        f"**③ JLPT:** {entry.get('jlpt') or '—'}\n"
        f"**④ 品詞:** {pos}\n"
        f"**⑤ 使用域:** {register}"
    )
    pages.append(p1)

    # Halaman 2: ⑥⑦
    p2 = _detail_base_embed(entry, "Halaman 2/6")
    p2.add_field(
        name="⑥ 意味・機能 (Meaning / Function)",
        value=f"🇬🇧 {entry['meaning_en']}\n🇮🇩 {entry['meaning_id']}",
        inline=False,
    )
    grouped = _translations_by_meaning(translation_rows)
    if grouped:
        blocks = []
        for meaning_label, langs in grouped.items():
            lines = []
            if meaning_label and meaning_label != "utama":
                lines.append(f"_{meaning_label}_")
            if langs["en"]:
                lines.append("🇬🇧 " + "; ".join(langs["en"]))
            if langs["id"]:
                lines.append("🇮🇩 " + "; ".join(langs["id"]))
            blocks.append("\n".join(lines))
        p2.add_field(name="⑦ 多言語対訳 (Translations)", value="\n\n".join(blocks)[:1024], inline=False)
    pages.append(p2)

    # Halaman 3: ⑧⑨
    p3 = _detail_base_embed(entry, "Halaman 3/6")
    if _has_content(entry.get("formation")):
        p3.add_field(name="⑧ 接続形式 (Formation)", value=entry["formation"].replace(";", "\n"), inline=False)
    for pattern_name, jp, id_terjemahan, _urutan in key_sentence_rows:
        value = f"{jp}\nTerjemahan ID: {id_terjemahan}"
        p3.add_field(name=f"⑨ {pattern_name}", value=value[:1024], inline=False)
    pages.append(p3)

    # Halaman 4: ⑩ Examples
    p4 = _detail_base_embed(entry, "Halaman 4/6")
    current = ""
    field_count = 0
    for function_label, jp, en, id_terjemahan, _urutan in example_rows:
        block = f"**{function_label}**\n{jp}\n　🇬🇧 {en}\n　🇮🇩 {id_terjemahan}"
        candidate = f"{current}\n\n{block}" if current else block
        # Field Discord dibatasi 1024 karakter — pecah kalau perlu, supaya
        # contoh yang banyak tidak terpotong diam-diam.
        if len(candidate) > 1024:
            field_count += 1
            name = "⑩ 例文 (Examples)" if field_count == 1 else "⑩ Examples (lanjutan)"
            p4.add_field(name=name, value=current, inline=False)
            current = block
        else:
            current = candidate
    if current:
        field_count += 1
        name = "⑩ 例文 (Examples)" if field_count == 1 else "⑩ Examples (lanjutan)"
        p4.add_field(name=name, value=current, inline=False)
    if not example_rows:
        p4.description = "Tidak ada contoh tambahan untuk entri ini."
    pages.append(p4)

    # Halaman 5: ⑪⑫
    p5 = _detail_base_embed(entry, "Halaman 5/6")
    p5.add_field(name="⑪ ニュアンス (Nuance)", value=entry.get("nuance") or "—", inline=False)
    p5.add_field(
        name="⑫ よくある間違い (Common Mistakes)",
        value=(entry.get("common_mistakes") or "—")[:1024],
        inline=False,
    )
    pages.append(p5)

    # Halaman 6: ⑬⑭⑮
    p6 = _detail_base_embed(entry, "Halaman 6/6")
    if _has_content(entry.get("related_expression")):
        p6.add_field(name="⑬ 関連表現 (Related Expressions)", value=f"[REL. {entry['related_expression']}]", inline=False)
    if _has_content(entry.get("related_expression_detail")):
        p6.add_field(
            name="⑭ 類似表現との比較 (Comparison)",
            value=entry["related_expression_detail"][:1024],
            inline=False,
        )
    if _has_content(entry.get("notes_en")):
        notes = f"🇬🇧 {entry['notes_en']}\n🇮🇩 {entry['notes_id']}"
        p6.add_field(name="⑮ 備考 (Notes)", value=notes[:1024], inline=False)
    if _has_content(entry.get("tags")):
        p6.add_field(name="Tags", value=entry["tags"], inline=False)
    if _has_content(entry.get("rujukan_silang")):
        p6.add_field(name="Rujukan Silang", value=entry["rujukan_silang"], inline=False)
    pages.append(p6)

    return pages


# ============================================================================
# MODE LIST/BROWSE — jlpt / huruf_awal / kosong (10.2)
# ============================================================================

def _build_list_query(jlpt: Optional[str], huruf_awal: Optional[str]) -> tuple[str, tuple]:
    """
    Sesuai tabel kombinasi §10.2:
      - jlpt + huruf_awal -> level tsb, diawali huruf tsb
      - jlpt saja         -> semua entri level tsb, urut kana (あ→ん)
      - huruf_awal saja   -> semua level, diawali huruf tsb, urut jlpt_order
      - kosong            -> semua entri, urut jlpt_order (mudah -> sulit)
    """
    where_clauses = []
    params: list = []

    if jlpt:
        where_clauses.append("jlpt = ?")
        params.append(jlpt)
    if huruf_awal:
        # Terima romaji ATAU hiragana — dicek ke kolom romaji dan kana sekaligus.
        where_clauses.append("(romaji LIKE ? OR kana LIKE ?)")
        params.append(f"{huruf_awal}%")
        params.append(f"{huruf_awal}%")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    if jlpt and not huruf_awal:
        order_sql = "ORDER BY kana ASC"
    else:
        order_sql = "ORDER BY jlpt_order ASC, kana ASC"

    query = f"{LIST_BASE_SELECT} {where_sql} {order_sql};"
    return query, tuple(params)


def _list_title(jlpt: Optional[str], huruf_awal: Optional[str]) -> str:
    parts = []
    if jlpt:
        parts.append(f"Level {jlpt}")
    if huruf_awal:
        parts.append(f"Huruf Awal '{huruf_awal}'")
    if not parts:
        return "📚 Semua Entri Kamus Grammar"
    return "📚 Kamus Grammar — " + " & ".join(parts)


def build_list_pages(
    entries: list[dict], jlpt: Optional[str], huruf_awal: Optional[str]
) -> tuple[list[discord.Embed], list[list[dict]]]:
    title = _list_title(jlpt, huruf_awal)
    chunks = [entries[i:i + LIST_PAGE_SIZE] for i in range(0, len(entries), LIST_PAGE_SIZE)] or [[]]
    total_pages = len(chunks)

    pages = []
    for idx, chunk in enumerate(chunks, start=1):
        lines = []
        for e in chunk:
            meaning = (e["meaning_id"] or "—").strip()
            if len(meaning) > 60:
                meaning = meaning[:57] + "..."
            lines.append(f"**{e['romaji']}** — {meaning} `{e['jlpt'] or '—'}`")

        embed = discord.Embed(
            title=title,
            description="\n\n".join(lines) or "Tidak ada entri.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Halaman {idx}/{total_pages} • Total {len(entries)} entri")
        pages.append(embed)

    return pages, chunks


# ============================================================================
# PAGINATION VIEW — mode detail
# ============================================================================

class GrammarPaginatorView(discord.ui.View):
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


# ============================================================================
# PAGINATION VIEW — mode list/browse, dengan dropdown loncat ke detail
# ============================================================================

class GrammarListView(discord.ui.View):
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
                label=e["romaji"][:100],
                description=(e["meaning_id"] or "—")[:100],
                value=e["id"],
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

        entry_id = interaction.data["values"][0]
        bot: KotabiBot = interaction.client
        row = await bot.GET_ONE(GET_ENTRY, (entry_id,))
        if not row:
            return await interaction.response.send_message("❌ Entri tidak ditemukan lagi.", ephemeral=True)

        entry = _row_to_dict(row)
        translation_rows = await bot.GET(GET_TRANSLATIONS, (entry_id,))
        key_sentence_rows = await bot.GET(GET_KEY_SENTENCES, (entry_id,))
        example_rows = await bot.GET(GET_EXAMPLES, (entry_id,))

        detail_pages = build_detail_pages(entry, translation_rows, key_sentence_rows, example_rows)
        for p in detail_pages:
            _add_requester_info(p, interaction.user)

        detail_view = GrammarPaginatorView(interaction.user.id, detail_pages)
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

class Grammar(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        for stmt in CREATE_TABLES:
            await self.bot.RUN(stmt)

        # AUTO SCHEMA MIGRATION — lihat catatan panjang di docstring modul.
        # Menjaga supaya database lama (dibuat oleh versi kode sebelum ada
        # kolom baru) tetap kompatibel tanpa perlu drop table manual.
        for table_name, expected_columns in SCHEMA_MIGRATIONS:
            await _ensure_columns(self.bot, table_name, expected_columns)

        await self.load_csv()

    async def load_csv(self):
        """CSV adalah sumber kebenaran: upsert entries, lalu ganti total
        anak-tabel (translations/key_sentences/examples) per entri, supaya
        baris yang dihapus dari CSV juga hilang dari database."""
        if not os.path.exists(ENTRIES_CSV_PATH):
            _log.warning("⚠️ File %s tidak ditemukan. Kamus grammar kosong.", ENTRIES_CSV_PATH)
            return

        entry_rows = []
        entry_ids = []
        with open(ENTRIES_CSV_PATH, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                entry_rows.append(tuple(row.get(col, "") for col in ENTRIES_COLUMNS))
                entry_ids.append(row["id"])

        if entry_rows:
            await self.bot.RUN_MANY(UPSERT_ENTRY, entry_rows)

        for entry_id in entry_ids:
            for stmt in DELETE_CHILD_ROWS:
                await self.bot.RUN(stmt, (entry_id,))

        for path, columns, insert_stmt in (
            (TRANSLATIONS_CSV_PATH, TRANSLATIONS_COLUMNS, INSERT_TRANSLATION),
            (KEY_SENTENCES_CSV_PATH, KEY_SENTENCES_COLUMNS, INSERT_KEY_SENTENCE),
            (EXAMPLES_CSV_PATH, EXAMPLES_COLUMNS, INSERT_EXAMPLE),
        ):
            if not os.path.exists(path):
                _log.warning("⚠️ File %s tidak ditemukan, dilewati.", path)
                continue
            rows = []
            with open(path, "r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    rows.append(tuple(row.get(col, "") for col in columns))
            if rows:
                await self.bot.RUN_MANY(insert_stmt, rows)

        _log.info("✅ %d entri grammar dimuat dari %s (+ tabel anak).", len(entry_rows), ENTRIES_CSV_PATH)

    @discord.app_commands.command(
        name="grammar",
        description="Cari pola grammar Jepang di kamus, atau jelajahi berdasarkan level JLPT / huruf awal.",
    )
    @discord.app_commands.describe(
        pola="Ketik romaji, kana, atau ID pola grammar. Kalau diisi, jlpt & huruf_awal diabaikan.",
        jlpt="Filter berdasarkan level JLPT (opsional).",
        huruf_awal="Filter entri yang diawali huruf ini — romaji atau hiragana (opsional).",
    )
    @discord.app_commands.choices(
        jlpt=[discord.app_commands.Choice(name=level, value=level) for level in JLPT_CHOICES]
    )
    @discord.app_commands.autocomplete(pola=grammar_autocomplete)
    @is_dic_access()
    async def grammar(
        self,
        interaction: discord.Interaction,
        pola: Optional[str] = None,
        jlpt: Optional[str] = None,
        huruf_awal: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        # Mode detail: pola diisi -> jlpt & huruf_awal diabaikan (10.2)
        if pola:
            row = await self.bot.GET_ONE(GET_ENTRY, (pola,))
            if not row:
                await interaction.followup.send(
                    "❌ Entri grammar tidak ditemukan. Gunakan menu autocomplete saat mengetik.",
                    ephemeral=True,
                )
                return

            entry = _row_to_dict(row)
            translation_rows = await self.bot.GET(GET_TRANSLATIONS, (pola,))
            key_sentence_rows = await self.bot.GET(GET_KEY_SENTENCES, (pola,))
            example_rows = await self.bot.GET(GET_EXAMPLES, (pola,))

            pages = build_detail_pages(entry, translation_rows, key_sentence_rows, example_rows)
            for p in pages:
                _add_requester_info(p, interaction.user)

            view = GrammarPaginatorView(interaction.user.id, pages)
            message = await interaction.followup.send(embed=pages[0], view=view, ephemeral=True, wait=True)
            view.message = message
            return

        # Mode list/browse: jlpt / huruf_awal / kosong (10.2)
        if huruf_awal:
            huruf_awal = huruf_awal.strip()

        query, params = _build_list_query(jlpt, huruf_awal)
        rows = await self.bot.GET(query, params)

        if not rows:
            await interaction.followup.send(
                "❌ Tidak ada entri grammar yang cocok dengan filter tersebut.", ephemeral=True
            )
            return

        entries = [
            {"id": r[0], "romaji": r[1], "kana": r[2], "meaning_id": r[3], "jlpt": r[4]}
            for r in rows
        ]
        pages, page_entries = build_list_pages(entries, jlpt, huruf_awal)
        for p in pages:
            _add_requester_info(p, interaction.user)

        view = GrammarListView(interaction.user.id, pages, page_entries)
        message = await interaction.followup.send(embed=pages[0], view=view, ephemeral=True, wait=True)
        view.message = message

    @discord.app_commands.command(name="grammar_reload", description="Muat ulang kamus grammar dari CSV (Khusus Admin).")
    @discord.app_commands.default_permissions(administrator=True)
    async def grammar_reload(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        for table_name, expected_columns in SCHEMA_MIGRATIONS:
            await _ensure_columns(self.bot, table_name, expected_columns)
        await self.load_csv()
        count_row = await self.bot.GET_ONE("SELECT COUNT(*) FROM grammar_entries;")
        total = count_row[0] if count_row else 0
        await interaction.followup.send(f"✅ Kamus grammar dimuat ulang. Total entri: **{total}**.", ephemeral=True)


async def setup(bot: KotabiBot):
    await bot.add_cog(Grammar(bot))