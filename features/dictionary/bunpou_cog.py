"""
features/dictionary/bunpou_cog.py — Kamus Grammar Jepang versi ringkas (/bunpou)
=================================================================================
Menggantikan features/dictionary/grammar_cog.py (format 15-bagian ①-⑮, 4 CSV
relasional) SEPENUHNYA. /bunpou memakai format flat/ringkas, 1 CSV datar:
    bunpou-notes-master.csv   (91 kolom, key field NoteID)

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

--------------------------------------------------------------------
RENDERING TEKS: HTML -> MARKDOWN & NOTASI FURIGANA (§ baru)
--------------------------------------------------------------------
CSV sumber (ekspor Anki) memakai markup HTML (<b>, <s>, <br>) dan notasi
furigana ala Anki 'kanji[bacaan]' yang TIDAK di-render Discord apa adanya.
Transformasi ini SEMUA terjadi di layer render (lihat _sanitize_html() &
_parse_furigana_sentence() di bawah) — CSV sendiri TIDAK PERNAH diubah,
supaya tetap jadi satu-satunya sumber kebenaran yang bisa disinkronkan
ulang dari Anki tanpa kehilangan hasil edit manual.

- <b>...</b>  -> **...**  (bold pola target di kalimat contoh)
- <s>...</s>  -> ~~...~~  (strikethrough, notasi textbook standar utk
  menunjukkan bagian yang dibuang, mis. ~~ます~~ pada V-masu)
- <br>        -> newline literal
- 'kanji[bacaan]' pada SentFurigana -> bacaan disembunyikan di balik
  spoiler Discord ||...|| sebagai "legenda" terpisah, sementara kalimat
  utama ditampilkan bersih tanpa notasi bracket (lihat
  _parse_furigana_sentence()).
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

from .bunpou_fields import FIELD_NAMES, KEY_FIELD, CATEGORY_FIELDS

_log = logging.getLogger("bot.bunpou")

# ============================================================================
# PATH & SKEMA
# ============================================================================

CSV_PATH = os.getenv("ALT_BUNPOU_CSV_PATH") or "features/dictionary/bunpou-notes-master.csv"

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

# Field individual yang tidak ditampilkan walau kategorinya ditampilkan
# (NoteID = key internal, Sort = urutan tampilan internal, bukan info
# linguistik — lihat panduan §7).
HIDDEN_FIELDS = {"NoteID", "Sort"}

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


# ----------------------------------------------------------------------------
# HTML -> Discord markdown sanitizer
# ----------------------------------------------------------------------------
# Diverifikasi terhadap SEMUA 632 baris / semua field teks: cuma 3 tag yang
# pernah muncul di dataset ini — <br>, <b>, <s>. <b> membold pola target di
# kalimat contoh; <s> notasi textbook standar (mis. ~~ます~~ untuk
# menunjukkan "buang akhiran -masu"); <br> baris baru literal di field
# catatan multi-baris.
_HTML_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_B_RE = re.compile(r"<b>(.*?)</b>", re.IGNORECASE | re.DOTALL)
_HTML_S_RE = re.compile(r"<s>(.*?)</s>", re.IGNORECASE | re.DOTALL)


def _sanitize_html(text: Optional[str]) -> str:
    """Konversi markup HTML ala Anki di dataset ini jadi markdown Discord.
    Aman dipanggil di field teks manapun (no-op kalau tidak ada 1 dari 3
    tag di atas). Dipanggil di layer render saja — CSV TIDAK diubah."""
    if not text:
        return text or ""
    text = _HTML_BR_RE.sub("\n", text)
    text = _HTML_B_RE.sub(r"**\1**", text)
    text = _HTML_S_RE.sub(r"~~\1~~", text)
    return text


# ----------------------------------------------------------------------------
# Parser notasi furigana (field SentFurigana)
# ----------------------------------------------------------------------------
# Satu token = satu/lebih karakter kanji/angka yang langsung diikuti
# [bacaan] — mis. "北[ほっ]", "今日[きょう]", "10[じっ]", "8日[ようか]",
# "人々[びと]". Kelas karakter sebelum bracket SENGAJA dibatasi ke ideograf
# CJK + tanda pengulangan kanji (々, U+3005) + digit ASCII/fullwidth —
# diverifikasi ini SATU-SATUNYA jenis karakter yang pernah muncul tepat
# sebelum bracket di 632 baris SentFurigana dataset ini. Membatasi kelas
# ini (bukan "semua karakter selain bracket") mencegah regex "serakah"
# menelan teks biasa/markdown di depannya ke dalam legenda.
_FURIGANA_TOKEN_RE = re.compile(r"([\u3005\u4e00-\u9fff0-9\uff10-\uff19]+)\[([^\[\]]*)\]")


def _parse_furigana_sentence(raw: Optional[str]) -> tuple[str, list[tuple[str, str]]]:
    """Parse notasi furigana Anki jadi (teks_tampil, legenda).
    - teks_tampil: kalimat dengan notasi bracket dibuang jadi kata polos,
      spasi artifak dari tokenizer ikut dibuang.
    - legenda: [(kata, bacaan), ...] berurutan sesuai kemunculan, dipakai
      untuk legenda bacaan yang disembunyikan di balik spoiler.
    Panggil _sanitize_html() pada `raw` DULU (supaya <b>/<s>/<br> sudah
    dikonversi) — kedua tag itu tidak pernah bersinggungan dengan token
    bracket di dataset ini jadi urutannya aman.
    """
    if not raw:
        return raw or "", []

    legend: list[tuple[str, str]] = []

    def _replace(m: re.Match) -> str:
        word, reading = m.group(1), m.group(2)
        legend.append((word, reading))
        return word

    display = _FURIGANA_TOKEN_RE.sub(_replace, raw)
    # Tokenizer sumber selalu menyisipkan 1 spasi literal sebelum tiap token
    # bracket sebagai kemudahan parsing, BUKAN spasi ortografis asli bahasa
    # Jepang (dikonfirmasi: tidak ada spasi asli lain di field SentFurigana)
    # — aman dibuang secara global.
    display = display.replace(" ", "")
    return display, legend


def _build_furigana_legend(legend: list[tuple[str, str]]) -> str:
    if not legend:
        return ""
    return "・".join(f"{w}={r}" for w, r in legend)


def _render_jp_text(raw: Optional[str]) -> str:
    """Sanitizer + parser gabungan untuk field BAHASA JEPANG mana pun yang
    bisa mengandung notasi furigana 'kanji[bacaan]' — bukan cuma
    SentFurigana. Diverifikasi: notasi ini juga muncul luas di
    GrammarNoteJP{n} (632/632 baris), GrammarMeaningJP (245/632), dan
    GrammarFormation{n} (176/632) — jadi field manapun yang isinya bahasa
    Jepang perlu dilewatkan lewat fungsi ini, bukan cuma _sanitize_html().
    Field BAHASA INDONESIA (GrammarNoteID/GrammarMeaningID/SentDefID)
    dikonfirmasi TIDAK PERNAH memuat notasi ini, jadi cukup _sanitize_html()
    biasa untuk field-field itu."""
    if not _has_content(raw):
        return raw or ""
    sanitized = _sanitize_html(raw)
    display, legend = _parse_furigana_sentence(sanitized)
    legend_text = _build_furigana_legend(legend)
    if legend_text:
        return f"{display} ||{legend_text}||"
    return display


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
        lines.append(f"🇯🇵 {_render_jp_text(jp)}")
    if _has_content(idn):
        lines.append(f"🇮🇩 {_sanitize_html(idn)}")
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
    # dipakai sebagai baris utama (dibersihkan lewat sanitizer + parser di
    # bawah); SentKanji polos hanya fallback kalau furigana kosong.
    if _has_content(furigana):
        sanitized = _sanitize_html(furigana)
        display, legend = _parse_furigana_sentence(sanitized)
        lines.append(display)
        legend_text = _build_furigana_legend(legend)
        if legend_text:
            # Bacaan disembunyikan di balik spoiler Discord (opt-in klik) —
            # sesuai keputusan: "Pakai spoiler - bacaan ketutup, klik dulu
            # buat buka."
            lines.append(f"||{legend_text}||")
    elif _has_content(kanji):
        lines.append(_sanitize_html(kanji))

    if _has_content(def_id):
        lines.append(f"🇮🇩 {_sanitize_html(def_id)}")
    return "\n".join(lines)


def _render_formation(values: list[str]) -> Optional[str]:
    if not values:
        return None
    return "\n".join(f"{i}. {_render_jp_text(v)}" for i, v in enumerate(values, start=1))


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
                lines.append(f"{i}. {_sanitize_html(m)}")
        else:
            lines.append(_sanitize_html(meaning_id))
    if _has_content(meaning_jp):
        lines.append(f"🇯🇵 {_render_jp_text(meaning_jp)}")
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


# Kategori yang benar-benar ditampilkan ke user, dalam urutan tampil
# (§8 panduan ringkas: 接続 → 意味 → 備考 → 例文). "Audio & Gambar" sengaja
# TIDAK dimasukkan — field-nya cuma berisi nama file mentah dari Anki
# (mis. "[sound:...]", "<img src=...>"), bukan URL yang bisa diakses/
# diputar di Discord. Aktifkan lagi kalau nanti file-file itu sudah
# benar-benar di-hosting di tempat yang bisa dirujuk Discord (CDN/URL
# publik) — tinggal tambahkan "Audio & Gambar" kembali ke list ini dan
# pasang lagi rendering slot Audio/Gambar (lihat git history cog ini).
DISPLAYED_CATEGORIES = ["Cara Penyambungan", "Makna", "Catatan Penjelasan", "Contoh Kalimat"]


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
            output.append(("使用域 (Register)", _sanitize_html(register)))

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

    # "Pengelompokan/Tag" sengaja tidak dirender di sini — dipakai untuk
    # footer lewat _entry_footer(), bukan halaman/body (lihat FOOTER_CATEGORY).

    return output


def _sentence_slot_count(entry: dict) -> int:
    """Hitung berapa slot 例文 (Contoh Kalimat) yang benar-benar terisi."""
    _, slotted = _group_by_slot(CATEGORY_FIELDS["Contoh Kalimat"], entry)
    return len(slotted)


def build_detail_pages(entry: dict) -> list[discord.Embed]:
    """Bangun halaman detail: SELALU 2 halaman kalau ada kalimat contoh —
    halaman 1 berisi 接続+意味+備考 (+ penunjuk singkat ke halaman 2),
    halaman 2 khusus 例文 (Contoh Kalimat) lengkap. Kalau entri kebetulan
    tidak punya kalimat contoh sama sekali (seharusnya tidak terjadi kalau
    validator dijalankan, karena minimal 1 kalimat wajib), fallback ke 1
    halaman tunggal. Audio & Gambar tidak pernah dirender (lihat
    DISPLAYED_CATEGORIES)."""
    color = LEVEL_COLOR.get(entry.get("level"), discord.Color.blurple())
    title = f"📖 {_entry_title(entry)}"
    footer_text = _entry_footer(entry)

    sentence_count = _sentence_slot_count(entry)

    main_categories = [c for c in DISPLAYED_CATEGORIES if c != "Contoh Kalimat"]
    main_fields: list[tuple[str, str]] = []
    for category_name in main_categories:
        main_fields += render_category(entry, category_name, CATEGORY_FIELDS[category_name])

    sentence_fields = render_category(entry, "Contoh Kalimat", CATEGORY_FIELDS["Contoh Kalimat"])

    pages: list[discord.Embed] = []

    if sentence_fields:
        # Halaman 1: info pola + makna + catatan, + penunjuk ke halaman 2.
        page1 = discord.Embed(title=title, color=color)
        for name, value in main_fields:
            _add_long_field(page1, name, [value])
        page1.add_field(
            name="例文 (Contoh)",
            value=f"{sentence_count} kalimat, lihat halaman berikutnya ➡️",
            inline=False,
        )
        pages.append(page1)

        # Halaman 2: 例文 lengkap.
        page2 = discord.Embed(title=title, color=color)
        for name, value in sentence_fields:
            _add_long_field(page2, name, [value])
        pages.append(page2)
    elif main_fields:
        # Tidak ada kalimat contoh sama sekali — 1 halaman tunggal saja,
        # tidak ada gunanya bikin halaman 2 kosong.
        embed = discord.Embed(title=title, color=color)
        for name, value in main_fields:
            _add_long_field(embed, name, [value])
        pages.append(embed)

    if not pages:
        # Fallback kalau entri kosong total selain Info Pola (seharusnya
        # tidak terjadi kalau validator dijalankan, tapi tetap dijaga).
        pages.append(discord.Embed(title=title, description="Tidak ada detail tambahan untuk entri ini.", color=color))

    total = len(pages)
    for idx, page in enumerate(pages, start=1):
        parts = []
        if total > 1:
            parts.append(f"Halaman {idx}/{total}")
        if footer_text:
            parts.append(footer_text)
        if parts:
            page.set_footer(text=" • ".join(parts))

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


def build_list_pages(
    entries: list[dict], level: Optional[str], show_meaning: bool = True
) -> tuple[list[discord.Embed], list[list[dict]]]:
    """Kolom arti HANYA ditampilkan kalau show_meaning=True (Companion ke
    atas) — sesuai bagian 3.1: mode list tetap terbuka penuh untuk semua
    role (nama pola + level), tapi payoff (artinya) khusus yang bayar."""
    title = _list_title(level)
    chunks = [entries[i:i + LIST_PAGE_SIZE] for i in range(0, len(entries), LIST_PAGE_SIZE)] or [[]]
    total_pages = len(chunks)

    pages = []
    for idx, chunk in enumerate(chunks, start=1):
        lines = []
        for e in chunk:
            pattern = e["GrammarPattern"]
            furigana = e["GrammarFurigana"]
            # Kalau pola sudah murni kana, furigana identik dengan pattern
            # (§3.1) — jangan diulang tampilkannya (mis. "あいだ（あいだ）").
            # Hanya tampilkan furigana kalau memang beda (pola pakai kanji).
            name_part = pattern if furigana == pattern else f"{pattern}（{furigana}）"
            level_tag = f"`{e['level']}`" if e["level"] else ""
            header_line = f"**{name_part}** {level_tag}".rstrip()

            if show_meaning:
                meaning = (e["GrammarMeaningID"] or "—").split(";")[0].strip()
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
        # bukan cuma diwariskan dari sini. show_meaning di sini cuma dipakai
        # untuk teks deskripsi dropdown.
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
                label=f"{e['GrammarPattern']} ({e['GrammarFurigana']})"[:100],
                description=(
                    (e["GrammarMeaningID"] or "—").split(";")[0].strip()[:100]
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

        # Celah arsitektur (bagian 3.2 strategi): dropdown ini interaksi
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
    @discord.app_commands.guild_only()
    async def bunpou(
        self,
        interaction: discord.Interaction,
        pola: Optional[str] = None,
        level: Optional[str] = None,
    ):
        # Command TIDAK di-gate akses lagi — mode list terbuka untuk semua
        # role (termasuk Drifter tanpa membership sama sekali). Access check
        # detail dicek eksplisit di sini DAN di BunpouListView._on_select
        # (celah dropdown — lihat bagian 3.2 strategi).
        await interaction.response.defer(ephemeral=True)

        # Mode detail: pola diisi.
        if pola:
            if not has_dic_access(interaction.user, interaction.guild_id):
                await interaction.followup.send(MSG_DIC_DETAIL_ONLY, ephemeral=True)
                return

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
        show_meaning = has_dic_access(interaction.user, interaction.guild_id)
        pages, page_entries = build_list_pages(entries, level, show_meaning=show_meaning)
        for p in pages:
            _add_requester_info(p, interaction.user)

        view = BunpouListView(interaction.user.id, pages, page_entries, show_meaning=show_meaning)
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