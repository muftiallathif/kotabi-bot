"""
features/dictionary/grammar_cog.py — Kamus Grammar Jepang (/grammar)
=====================================================================
Sumber data: 4 CSV relational (Opsi B) di features/dictionary/:
    grammar_entries.csv        (identitas + metadata + ①②③④⑤⑥⑧⑪⑫⑬⑭⑮)
    grammar_translations.csv   (⑦ Translations, per makna)
    grammar_key_sentences.csv  (⑨ Key Sentences, per pola — JP/Romaji/EN/ID)
    grammar_examples.csv       (⑩ Examples, per fungsi — JP/Romaji/EN/ID)

Mengikuti "Panduan Membuat Entri Kamus Grammar Bahasa Jepang" (Kotabi
Style Guide, 15 bagian ①–⑮), khususnya bagian 6 (Opsi B — relational),
bagian 9.3 (Pagination) dan aturan format tampilan di bagian tersebut:

  - Tiga parameter opsional & independen: pola (autocomplete), jlpt
    (pilihan N5-N1), huruf_awal (romaji ATAU hiragana). Kalau `pola`
    diisi, `jlpt` dan `huruf_awal` diabaikan (§9.2).
  - Mode "1 entri detail" dipecah **3 halaman** (dipadatkan dari versi
    4/6 halaman sebelumnya), mengikuti pengelompokan §9.3:
      1. ①②③④⑤⑥⑦ — Grammar Entry, Reading, JLPT, Part of Speech,
                        Usage/Register, Meaning/Function, Translations
      2. ⑧⑨⑩       — Formation, Key Sentences, Examples
      3. ⑪⑫⑬⑭⑮   — Nuance, Common Mistakes, Related Expressions,
                        Comparison, Notes (+ Tags & Rujukan Silang)
  - Mode "list/browse" (jlpt / huruf_awal / kosong) TERPAGINASI, dengan
    dropdown per halaman untuk loncat langsung ke mode detail.
  - Aturan format tampilan (§9.3):
      * Metadata ID, Romaji (field sortir), JLPT_Order, Status TIDAK
        ditampilkan sama sekali — murni internal untuk sortir/database.
        Tags & Rujukan Silang TETAP ditampilkan (di halaman terakhir).
      * Judul embed = ①+② digabung format "Nama（Bacaan）". ①② tetap
        ditampilkan lagi sebagai section di body.
      * Simbol lingkaran ①–⑮ TIDAK ditampilkan di body sama sekali.
      * Label section: nama Jepang + gloss Inggris di baris tersendiri
        (mis. "読み方 (Reading)"), tanpa romanisasi Hepburn di tengah.
      * Bagian dwibahasa (⑥⑦⑨⑩⑮) pakai bendera 🇬🇧/🇮🇩 per baris.
      * Romaji di ⑨/⑩ ditulis miring, satu baris di bawah kalimat JP.
      * Item dalam satu baris (mis. daftar translations) dipisah "·".
      * Nama pola (⑨) & label fungsi (⑩) ditulis **bold**.
  - Entri redirect (Status: redirect) ditampilkan sebagai SATU embed
    statis, TANPA tombol Prev/Next dan TANPA footer "Halaman X/Y" —
    lihat build_redirect_embed().
  - Semua respons ephemeral, plus pagination sebagai proteksi anti-copy
    tambahan (§9.4). Setiap embed menampilkan info pemohon (avatar, nama
    tampilan, username) di author/footer.
  - Gating akses via shared/checks.py::is_dic_access() — Trial dapat,
    Traveler TIDAK dapat, Companion/Patron dapat, staff & admin selalu
    dapat (§9.5).

CSV adalah sumber kebenaran: setiap cog_load(), isi keempat CSV
di-upsert ulang ke 4 tabel SQLite bernama sama (aman dijalankan berkali-
kali). Kalau mau menambah/mengubah entri, cukup edit CSV lalu
restart/reload cog ini (atau /grammar_reload) — tidak perlu query
manual ke database.

Path CSV bisa dioverride lewat env var ALT_GRAMMAR_*_CSV_PATH, mengikuti
pola ALT_*_PATH yang sudah dipakai cog lain di project ini.

--------------------------------------------------------------------
KEAMANAN SQL
--------------------------------------------------------------------
- Seluruh query yang menyentuh data dari luar (CSV, input pengguna)
  memakai parameter binding ("?"), tidak pernah string-interpolation
  langsung dari nilai data. Satu-satunya f-string dalam SQL adalah
  untuk NAMA KOLOM/TABEL yang berasal dari konstanta tetap di kode ini
  (ENTRIES_COLUMNS dkk, SCHEMA_MIGRATIONS) — bukan dari CSV atau input
  pengguna — sehingga aman dari SQL injection.
- Auto schema migration (_ensure_columns) hanya menambah kolom dari
  daftar tetap di kode (ENTRIES_COLUMN_TYPES dkk), tidak pernah dari
  input dinamis, dan tidak pernah menghapus/mengubah data yang sudah ada.

--------------------------------------------------------------------
AUTO SCHEMA MIGRATION:
--------------------------------------------------------------------
`CREATE TABLE IF NOT EXISTS` HANYA membuat tabel kalau belum ada sama
sekali. Kalau tabel sudah pernah dibuat oleh versi kode LAMA (sebelum
sebuah kolom baru ditambahkan ke skema, mis. `romaji`/`en` pada
grammar_key_sentences dan grammar_examples), statement itu tidak
berbuat apa-apa lagi — kolom baru tidak pernah benar-benar tercermin ke
database fisik (data/db.sqlite3, yang persist lewat bind mount Docker).
Akibatnya UPSERT/INSERT saat load_csv() bisa gagal dengan
`OperationalError: table X has no column named Y`.

Untuk mencegah ini terulang tiap kali skema CSV/kolom baru ditambahkan,
cog_load() menjalankan _ensure_columns() untuk keempat tabel: mengecek
kolom yang benar-benar ada di database (lewat PRAGMA table_info), lalu
menjalankan `ALTER TABLE ... ADD COLUMN ...` untuk kolom yang
didefinisikan di kode tapi belum ada di database. Ini aman dijalankan
berkali-kali (idempotent) dan tidak pernah menghapus data.
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
# NB: romaji & en ditambahkan supaya sesuai wajib ⑨ Key Sentences di panduan
# (kalimat JP + baris Romaji + Terjemahan EN + Terjemahan ID).
KEY_SENTENCES_COLUMNS = ["entry_id", "pattern_name", "jp", "romaji", "en", "id_terjemahan", "urutan"]
# NB: romaji ditambahkan supaya sesuai wajib ⑩ Examples (empat baris:
# JP -> Romaji -> EN -> ID).
EXAMPLES_COLUMNS = ["entry_id", "function_label", "jp", "romaji", "en", "id_terjemahan", "urutan"]

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
        entry_id TEXT, pattern_name TEXT, jp TEXT, romaji TEXT, en TEXT,
        id_terjemahan TEXT, urutan INTEGER,
        FOREIGN KEY(entry_id) REFERENCES grammar_entries(id)
    );""",
    """CREATE TABLE IF NOT EXISTS grammar_examples (
        entry_id TEXT, function_label TEXT, jp TEXT, romaji TEXT, en TEXT,
        id_terjemahan TEXT, urutan INTEGER,
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
    "romaji": "TEXT",
    "en": "TEXT",
    "id_terjemahan": "TEXT",
    "urutan": "INTEGER",
}

EXAMPLES_COLUMN_TYPES = {
    "entry_id": "TEXT",
    "function_label": "TEXT",
    "jp": "TEXT",
    "romaji": "TEXT",
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
    sudah ada. table_name & expected_columns SELALU berasal dari
    konstanta tetap di modul ini (SCHEMA_MIGRATIONS), tidak pernah dari
    input pengguna, sehingga f-string di bawah aman dipakai.
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
GET_KEY_SENTENCES = "SELECT pattern_name, jp, romaji, en, id_terjemahan, urutan FROM grammar_key_sentences WHERE entry_id = ? ORDER BY urutan ASC;"
GET_EXAMPLES = "SELECT function_label, jp, romaji, en, id_terjemahan, urutan FROM grammar_examples WHERE entry_id = ? ORDER BY urutan ASC;"

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
# Token interaksi ephemeral kedaluwarsa ~15 menit (§9.3) — timeout view
# dipasang sedikit di bawah itu.
PAGINATOR_TIMEOUT_SECONDS = 800

# Field embed dibatasi 1024 karakter oleh Discord.
MAX_FIELD_LENGTH = 1024


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


def _entry_display_name(entry: dict) -> str:
    """Nama tampilan ① — pakai kanji kalau ada, kalau tidak pakai kana."""
    return entry["kanji"] if _has_content(entry.get("kanji")) else entry["kana"]


def _entry_title(entry: dict) -> str:
    """Format judul 'Nama（Bacaan）' sesuai §9.3 — bukan romaji."""
    return f"{_entry_display_name(entry)}（{entry['kana']}）"


def _translations_by_meaning(rows: list[tuple]) -> dict[str, dict[str, list[str]]]:
    """rows -> {meaning_label: {"en": [...], "id": [...]}}"""
    grouped: dict[str, dict[str, list[str]]] = {}
    for meaning_label, language, term, _urutan in rows:
        grouped.setdefault(meaning_label, {"en": [], "id": []})
        grouped[meaning_label][language].append(term)
    return grouped


def _add_long_field(embed: discord.Embed, base_name: str, blocks: list[str], empty_text: Optional[str] = None):
    """Gabungkan `blocks` (dipisah baris kosong) jadi satu/lebih field embed,
    otomatis dipecah kalau melebihi batas 1024 karakter per field Discord."""
    if not blocks:
        if empty_text:
            embed.add_field(name=base_name, value=empty_text, inline=False)
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


# ============================================================================
# MODE DETAIL — 3 halaman (§9.3)
# ============================================================================

def _new_detail_embed(entry: dict) -> discord.Embed:
    color = JLPT_COLOR.get(entry.get("jlpt"), discord.Color.blurple())
    return discord.Embed(title=f"📖 {_entry_title(entry)}", color=color)


def _build_page1(entry: dict) -> discord.Embed:
    """①②③④⑤⑥⑦ — Grammar Entry, Reading, JLPT, Part of Speech, Register,
    Meaning/Function, Translations."""
    embed = _new_detail_embed(entry)

    embed.add_field(name="文法項目 (Grammar Entry)", value=_entry_display_name(entry), inline=False)

    reading = entry["kana"]
    if _has_content(entry.get("reading_secondary")):
        reading += f"\n(varian lisan: {entry['reading_secondary']})"
    embed.add_field(name="読み方 (Reading)", value=reading, inline=False)

    embed.add_field(name="JLPTレベル (JLPT Level)", value=entry.get("jlpt") or "—", inline=False)

    pos = entry.get("part_of_speech") or "—"
    if _has_content(entry.get("part_of_speech_subtype")):
        pos += f" ({entry['part_of_speech_subtype']})"
    embed.add_field(name="品詞 (Part of Speech)", value=pos, inline=False)

    register_lines = [f"Ragam: {entry.get('usage_register') or '—'}"]
    if _has_content(entry.get("frequency")):
        register_lines.append(f"Frekuensi: {entry['frequency']}")
    embed.add_field(name="使用域 (Usage / Register)", value="\n".join(register_lines), inline=False)

    embed.add_field(
        name="意味・機能 (Meaning & Function)",
        value=f"🇬🇧 {entry['meaning_en']}\n🇮🇩 {entry['meaning_id']}",
        inline=False,
    )

    return embed


def _build_page1_with_translations(entry: dict, translation_rows: list[tuple]) -> discord.Embed:
    embed = _build_page1(entry)

    grouped = _translations_by_meaning(translation_rows)
    if grouped:
        blocks = []
        for meaning_label, langs in grouped.items():
            lines = []
            if meaning_label and meaning_label not in ("utama", "—"):
                lines.append(f"_{meaning_label}_")
            if langs["en"]:
                lines.append("🇬🇧 " + " · ".join(langs["en"]))
            if langs["id"]:
                lines.append("🇮🇩 " + " · ".join(langs["id"]))
            blocks.append("\n".join(lines))
        _add_long_field(embed, "多言語対訳 (Translations)", blocks)

    return embed


def _build_page2(entry: dict, key_sentence_rows: list[tuple], example_rows: list[tuple]) -> discord.Embed:
    """⑧⑨⑩ — Formation, Key Sentences, Examples."""
    embed = _new_detail_embed(entry)

    if _has_content(entry.get("formation")):
        embed.add_field(
            name="接続形式 (Formation)",
            value=entry["formation"].replace(";", "\n")[:MAX_FIELD_LENGTH],
            inline=False,
        )

    key_sentence_blocks = []
    for pattern_name, jp, romaji, en, id_terjemahan, _urutan in key_sentence_rows:
        block = f"**{pattern_name}**\n{jp}\n_{romaji}_\n🇬🇧 {en}\n🇮🇩 {id_terjemahan}"
        key_sentence_blocks.append(block)
    _add_long_field(embed, "基本文 (Key Sentences)", key_sentence_blocks, empty_text="—")

    example_blocks = []
    for function_label, jp, romaji, en, id_terjemahan, _urutan in example_rows:
        block = f"**{function_label}**\n{jp}\n_{romaji}_\n🇬🇧 {en}\n🇮🇩 {id_terjemahan}"
        example_blocks.append(block)
    _add_long_field(embed, "例文 (Examples)", example_blocks, empty_text="Tidak ada contoh tambahan untuk entri ini.")

    return embed


def _build_page3(entry: dict) -> discord.Embed:
    """⑪⑫⑬⑭⑮ — Nuance, Common Mistakes, Related Expressions, Comparison,
    Notes, ditambah Tags & Rujukan Silang (bukan bagian 15-poin, tapi tetap
    berguna untuk pembaca sesuai §9.3)."""
    embed = _new_detail_embed(entry)

    embed.add_field(name="ニュアンス (Nuance)", value=entry.get("nuance") or "—", inline=False)

    if _has_content(entry.get("common_mistakes")):
        embed.add_field(
            name="よくある間違い (Common Mistakes)",
            value=entry["common_mistakes"][:MAX_FIELD_LENGTH],
            inline=False,
        )

    if _has_content(entry.get("related_expression")):
        embed.add_field(name="関連表現 (Related Expressions)", value=entry["related_expression"], inline=False)

    if _has_content(entry.get("related_expression_detail")):
        embed.add_field(
            name="類似表現との比較 (Comparison)",
            value=entry["related_expression_detail"][:MAX_FIELD_LENGTH],
            inline=False,
        )

    if _has_content(entry.get("notes_en")):
        notes = f"🇬🇧 {entry['notes_en']}\n🇮🇩 {entry['notes_id']}"
        embed.add_field(name="備考 (Notes)", value=notes[:MAX_FIELD_LENGTH], inline=False)

    if _has_content(entry.get("tags")):
        embed.add_field(name="Tags", value=entry["tags"], inline=False)
    if _has_content(entry.get("rujukan_silang")):
        embed.add_field(name="Rujukan Silang", value=entry["rujukan_silang"], inline=False)

    return embed


def build_detail_pages(
    entry: dict,
    translation_rows: list[tuple],
    key_sentence_rows: list[tuple],
    example_rows: list[tuple],
) -> list[discord.Embed]:
    """Menyusun data dari 4 tabel jadi 3 embed berurutan sesuai §9.3."""
    pages = [
        _build_page1_with_translations(entry, translation_rows),
        _build_page2(entry, key_sentence_rows, example_rows),
        _build_page3(entry),
    ]
    total = len(pages)
    for idx, page in enumerate(pages, start=1):
        page.set_footer(text=f"Halaman {idx}/{total}")
    return pages


def build_redirect_embed(entry: dict) -> discord.Embed:
    """
    Tampilan khusus untuk entri Status: redirect (lihat "Entri
    Redirect/Alias" di panduan). SATU embed statis — TIDAK dipaginate,
    TANPA tombol Prev/Next dan TANPA footer "Halaman X/Y".
    """
    embed = _new_detail_embed(entry)

    if _has_content(entry.get("jlpt")):
        embed.add_field(name="JLPTレベル (JLPT Level)", value=entry["jlpt"], inline=False)

    if _has_content(entry.get("part_of_speech")):
        pos = entry["part_of_speech"]
        if _has_content(entry.get("part_of_speech_subtype")):
            pos += f" ({entry['part_of_speech_subtype']})"
        embed.add_field(name="品詞 (Part of Speech)", value=pos, inline=False)

    target = entry.get("related_expression") or "—"
    redirect_message = entry.get("meaning_id") or f"Lihat **{target}** untuk penjelasan lengkap."
    embed.add_field(name="\u200b", value=f"🔀 Entri ini redirect. {redirect_message}", inline=False)

    return embed


# ============================================================================
# MODE LIST/BROWSE — jlpt / huruf_awal / kosong (§9.2)
# ============================================================================

def _build_list_query(jlpt: Optional[str], huruf_awal: Optional[str]) -> tuple[str, tuple]:
    """
    Sesuai tabel kombinasi §9.2:
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

        # Entri redirect: 1 embed statis, tanpa pagination (lihat build_redirect_embed).
        if entry.get("status") == "redirect":
            embed = build_redirect_embed(entry)
            _add_requester_info(embed, interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

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
        # kolom baru, mis. romaji/en di key_sentences & examples) tetap
        # kompatibel tanpa perlu drop table manual.
        for table_name, expected_columns in SCHEMA_MIGRATIONS:
            await _ensure_columns(self.bot, table_name, expected_columns)

        await self.load_csv()

    async def load_csv(self):
        """CSV adalah sumber kebenaran: upsert entries, lalu ganti total
        anak-tabel (translations/key_sentences/examples) per entri, supaya
        baris yang dihapus dari CSV juga hilang dari database. Full replace
        per entri ini dijalankan dalam satu proses linear (bukan multi-user
        concurrent), dan semua nilai memakai parameter binding — aman dari
        SQL injection walau isi CSV berubah-ubah."""
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

        # Mode detail: pola diisi -> jlpt & huruf_awal diabaikan (§9.2)
        if pola:
            row = await self.bot.GET_ONE(GET_ENTRY, (pola,))
            if not row:
                await interaction.followup.send(
                    "❌ Entri grammar tidak ditemukan. Gunakan menu autocomplete saat mengetik.",
                    ephemeral=True,
                )
                return

            entry = _row_to_dict(row)

            # Entri redirect: 1 embed statis, tanpa pagination.
            if entry.get("status") == "redirect":
                embed = build_redirect_embed(entry)
                _add_requester_info(embed, interaction.user)
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

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

        # Mode list/browse: jlpt / huruf_awal / kosong (§9.2)
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