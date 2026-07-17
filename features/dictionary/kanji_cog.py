"""
features/dictionary/kanji_cog.py — Kamus Kanji Bahasa Jepang (/kanji)
========================================================================
Mengikuti arsitektur `/bunpou` dan `/kotoba` (bunpou_cog.py/kotoba_cog.py)
sedapat mungkin: gating lewat shared.checks.has_dic_access(), mode
detail + mode list/browse, dropdown "pilih untuk detail" dengan access
check ulang di callback, loader full-replace tiap cog_load()/reload.

BEDA UTAMA dengan /bunpou & /kotoba (lihat panduan-kamus-kanji-versi-ringkas.md
untuk rasional lengkap tiap keputusan di bawah ini — SEMUA keputusan di sana
final, tidak didiskusikan ulang di sini):

- Data sumber `kanji_master.csv` SUDAH LENGKAP (bukan hasil authoring
  manual) — tidak ada validator seperti grammar_validator.py.
- `kanji_master.csv` adalah CSV comma-delimited BIASA (bukan tab-delimited
  ala ekspor Anki seperti bunpou/kotoba), dan TIDAK punya baris metadata
  `#separator:Tab` yang perlu dilewati.
- 13 kolom sumber berisi JSON-in-cell (list atau object) — lihat
  kanji_fields.py (LIST_JSON_FIELDS/OBJECT_JSON_FIELDS). Kolom-kolom ini
  disimpan APA ADANYA sebagai TEXT di SQLite; `json.loads()` dipanggil
  HANYA saat render (bukan saat load), persis pola yang sudah dipakai
  bunpou_cog.py/kotoba_cog.py untuk field JSON kompleks mereka sendiri.
- Ada file overlay TERPISAH `kanji_meanings_id.csv` (2 kolom: kanji,
  arti_id) untuk terjemahan Bahasa Indonesia — LEFT JOIN saat query detail.
  File ini BOLEH kosong; fallback ke meanings_en/meaning_jp kalau arti_id
  belum diisi, TANPA placeholder "belum diterjemahkan" ke user.
- Pagination DINAMIS 1–3 halaman (bukan selalu 1 atau selalu 2 seperti
  /kotoba dan /bunpou) — tergantung isi jukugo_contoh dan
  dekomposisi/kanji-terkait.
- Filter tambahan di command: jlpt, joyo, kelas_sd (bukan cuma level
  seperti /bunpou/kotoba).
- TIDAK ada JOIN ke radikal_master.csv di v1 (lihat §10 panduan) — radikal
  Kanken diambil dari `radikal_info_kanken` yang sudah ter-embed sebagai
  object JSON di kanji_master.csv sendiri.
"""

import csv
import json
import logging
import os
from typing import Optional

import discord
from discord.ext import commands

from core.bot import KotabiBot
from shared.checks import has_dic_access, MSG_DIC_DETAIL_ONLY

from .kanji_fields import (
    FIELD_NAMES,
    KEY_FIELD,
    CATEGORY_FIELDS,
    LIST_JSON_FIELDS,
    OBJECT_JSON_FIELDS,
)

_log = logging.getLogger("bot.kanji")

# ============================================================================
# PATH & SKEMA
# ============================================================================

CSV_PATH = os.getenv("ALT_KANJI_CSV_PATH") or "features/dictionary/kanji_master.csv"
MEANINGS_ID_CSV_PATH = (
    os.getenv("ALT_KANJI_MEANINGS_ID_CSV_PATH") or "features/dictionary/kanji_meanings_id.csv"
)

TABLE_NAME = "kanji_entries"
MEANINGS_TABLE = "kanji_meanings_id"

_COLUMN_DEFS = ", ".join(
    f"{col} TEXT PRIMARY KEY" if col == KEY_FIELD else f"{col} TEXT"
    for col in FIELD_NAMES
)
CREATE_TABLE = f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} ({_COLUMN_DEFS});"

CREATE_MEANINGS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {MEANINGS_TABLE} (
    kanji TEXT PRIMARY KEY,
    arti_id TEXT
);"""

CREATE_INDEXES = [
    f"CREATE INDEX IF NOT EXISTS idx_kanji_jlpt ON {TABLE_NAME} (jlpt_baru);",
    f"CREATE INDEX IF NOT EXISTS idx_kanji_joyo ON {TABLE_NAME} (joyo_status);",
    f"CREATE INDEX IF NOT EXISTS idx_kanji_kanken ON {TABLE_NAME} (kanken_level);",
    f"CREATE INDEX IF NOT EXISTS idx_kanji_kelas_sd ON {TABLE_NAME} (kyouiku_kelas_sd);",
]

DELETE_ALL_ENTRIES = f"DELETE FROM {TABLE_NAME};"
DELETE_ALL_MEANINGS = f"DELETE FROM {MEANINGS_TABLE};"

INSERT_ENTRY = (
    f"INSERT INTO {TABLE_NAME} ({', '.join(FIELD_NAMES)}) "
    f"VALUES ({', '.join(['?'] * len(FIELD_NAMES))});"
)
INSERT_MEANING = f"INSERT INTO {MEANINGS_TABLE} (kanji, arti_id) VALUES (?, ?);"

_ENTRY_COLS = ", ".join(f"k.{c}" for c in FIELD_NAMES)

GET_ENTRY = f"""
SELECT {_ENTRY_COLS}, m.arti_id
FROM {TABLE_NAME} k
LEFT JOIN {MEANINGS_TABLE} m ON k.kanji = m.kanji
WHERE k.kanji = ?;
"""

GET_ALL_FOR_LIST = f"""
SELECT k.kanji, k.jlpt_baru, k.joyo_status, k.kyouiku_kelas_sd, k.kanken_kyu_resmi,
       k.meanings_en, m.arti_id
FROM {TABLE_NAME} k
LEFT JOIN {MEANINGS_TABLE} m ON k.kanji = m.kanji
"""

SEARCH_QUERY = f"""
SELECT k.kanji, k.on_yomi, k.kun_yomi, k.meanings_en, k.jlpt_baru
FROM {TABLE_NAME} k
WHERE k.kanji LIKE '%' || ? || '%'
   OR k.on_yomi LIKE '%' || ? || '%'
   OR k.kun_yomi LIKE '%' || ? || '%'
   OR k.nanori LIKE '%' || ? || '%'
   OR k.meanings_en LIKE '%' || ? || '%'
   OR k.meaning_jp LIKE '%' || ? || '%'
ORDER BY (k.jlpt_baru IS NULL OR k.jlpt_baru = ''), k.jumlah_goresan ASC, k.kanji ASC
LIMIT 25;
"""

SEARCH_QUERY_JLPT = f"""
SELECT k.kanji, k.on_yomi, k.kun_yomi, k.meanings_en, k.jlpt_baru
FROM {TABLE_NAME} k
WHERE k.jlpt_baru = ?
AND (k.kanji LIKE '%' || ? || '%' OR k.on_yomi LIKE '%' || ? || '%' OR k.kun_yomi LIKE '%' || ? || '%'
     OR k.nanori LIKE '%' || ? || '%' OR k.meanings_en LIKE '%' || ? || '%' OR k.meaning_jp LIKE '%' || ? || '%')
ORDER BY k.jumlah_goresan ASC, k.kanji ASC
LIMIT 25;
"""

JLPT_CHOICES = ["N5", "N4", "N3", "N2", "N1"]
JOYO_CHOICES = [("Ya", "TRUE"), ("Tidak", "FALSE")]
KELAS_SD_CHOICES = ["1", "2", "3", "4", "5", "6"]

LIST_PAGE_SIZE = 10
PAGINATOR_TIMEOUT_SECONDS = 800
MAX_FIELD_LENGTH = 1024

JUKUGO_KATEGORI_LABEL = {
    "小": "🟢 SD",
    "中": "🟡 SMP",
    "高": "🔴 SMA",
    "外": "⚪ Luar Kurikulum",
}
JUKUGO_KATEGORI_ORDER = ["小", "中", "高", "外"]
JUKUGO_MAX_PER_KATEGORI = 15

# Field teknis yang TIDAK PERNAH dirender ke user (§3.8/§9). kanken_url,
# kanjipedia_url, dan jumlah_kosakata_terkait SENGAJA tidak masuk sini —
# tiga field itu tetap dirender (link referensi & statistik kecil).
HIDDEN_TECHNICAL_FIELDS = {
    "unicode", "jis_menkuten", "jis_unicode", "jis_level",
    "kategori_nama_anak", "kanken_zititai_kubun", "kanken_dict_page", "sumber",
}


# ============================================================================
# HELPERS
# ============================================================================

def _has_content(value: Optional[str]) -> bool:
    return bool(value) and value.strip() not in ("", "—")


def _load_list(raw: Optional[str]) -> list:
    if not _has_content(raw):
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _load_object(raw: Optional[str]) -> Optional[dict]:
    if not _has_content(raw):
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _row_to_dict(row: tuple) -> dict:
    """Baris dari GET_ENTRY (semua FIELD_NAMES + arti_id di kolom terakhir)."""
    d = dict(zip(FIELD_NAMES, row[:-1]))
    d["arti_id"] = row[-1]
    return d


def _add_requester_info(embed: discord.Embed, user: discord.User) -> discord.Embed:
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.set_footer(text=f"Diminta oleh @{user.name}")
    return embed


def _add_long_field(embed: discord.Embed, name: str, value: str):
    if not value:
        return
    if len(value) <= MAX_FIELD_LENGTH:
        embed.add_field(name=name, value=value, inline=False)
        return
    first = True
    remaining = value
    while remaining:
        chunk, remaining = remaining[:MAX_FIELD_LENGTH], remaining[MAX_FIELD_LENGTH:]
        embed.add_field(name=name if first else f"{name} (lanjutan)", value=chunk, inline=False)
        first = False


# ============================================================================
# AUTOCOMPLETE
# ============================================================================

async def kanji_autocomplete(interaction: discord.Interaction, current_input: str):
    """Autocomplete gabungan: kanji itu sendiri, on_yomi/kun_yomi/nanori,
    meanings_en/meaning_jp. Difilter oleh parameter `jlpt` kalau sudah diisi."""
    bot: KotabiBot = interaction.client
    current_input = current_input.strip()
    jlpt = getattr(interaction.namespace, "jlpt", None)

    if jlpt:
        rows = await bot.GET(SEARCH_QUERY_JLPT, (jlpt, current_input, current_input, current_input, current_input, current_input, current_input))
    else:
        rows = await bot.GET(SEARCH_QUERY, (current_input, current_input, current_input, current_input, current_input, current_input))

    choices = []
    for kanji, on_yomi, kun_yomi, meanings_en, jlpt_baru in rows:
        meanings = _load_list(meanings_en)
        meaning_preview = meanings[0] if meanings else "—"
        level_tag = f" [{jlpt_baru}]" if jlpt_baru else ""
        label = f"{kanji} — {meaning_preview}{level_tag}"[:100]
        choices.append(discord.app_commands.Choice(name=label, value=kanji))
    return choices[:25]


# ============================================================================
# RENDERING — MODE DETAIL
# ============================================================================

def _entry_title(entry: dict) -> str:
    return f"📖 {entry.get('kanji', '?')}"


def _entry_footer(entry: dict) -> str:
    parts = []
    jlpt = entry.get("jlpt_baru")
    if _has_content(jlpt):
        parts.append(f"JLPT {jlpt}")
    if entry.get("joyo_status") == "TRUE":
        urutan = entry.get("joyo_urutan")
        parts.append(f"Jōyō #{urutan}" if _has_content(urutan) else "Jōyō Kanji")
    kanken_label = entry.get("kanken_kyu_resmi") or entry.get("kanken_level")
    if _has_content(kanken_label):
        parts.append(f"Kanken {kanken_label}")
    kosakata = entry.get("jumlah_kosakata_terkait")
    if _has_content(kosakata) and kosakata != "0":
        parts.append(f"Dipakai di {kosakata} entri kosakata")
    return " · ".join(parts)


def _render_info_dasar(entry: dict) -> str:
    lines = []
    goresan = entry.get("jumlah_goresan")
    if _has_content(goresan):
        lines.append(f"**Jumlah Goresan:** {goresan}")

    if entry.get("joyo_status") == "TRUE":
        urutan = entry.get("joyo_urutan")
        badge = f"🏅 Jōyō Kanji (#{urutan})" if _has_content(urutan) else "🏅 Jōyō Kanji"
        lines.append(badge)

    kelas_sd = entry.get("kyouiku_kelas_sd")
    if _has_content(kelas_sd):
        lines.append(f"**Kelas SD:** {kelas_sd}")

    jlpt = entry.get("jlpt_baru")
    if _has_content(jlpt):
        lines.append(f"**JLPT:** {jlpt}")

    kanken_label = entry.get("kanken_kyu_resmi")
    kanken_fallback = entry.get("kanken_level")
    if _has_content(kanken_label):
        lines.append(f"**Kanken:** {kanken_label}")
    elif _has_content(kanken_fallback):
        lines.append(f"**Kanken:** {kanken_fallback}")

    freq = entry.get("freq_rank_mainichi_shinbun")
    if _has_content(freq):
        lines.append(f"**Peringkat Frekuensi** (Mainichi Shinbun): #{freq}")

    return "\n".join(lines)


def _render_bacaan(entry: dict) -> Optional[str]:
    on_yomi = _load_list(entry.get("on_yomi"))
    kun_yomi = _load_list(entry.get("kun_yomi"))
    nanori = _load_list(entry.get("nanori"))

    if not on_yomi and not kun_yomi and not nanori:
        return None

    lines = []
    if on_yomi:
        lines.append(f"**On'yomi:** {'、'.join(on_yomi)}")
    if kun_yomi:
        lines.append(f"**Kun'yomi:** {'、'.join(kun_yomi)}")
    if nanori:
        lines.append(f"**Nanori:** {'、'.join(nanori)}")
    return "\n".join(lines)


def _render_arti(entry: dict) -> Optional[str]:
    """Fallback rendering sesuai §3.3a: arti_id jadi section utama kalau
    terisi (meanings_en/meaning_jp tetap tampil sebagai pelengkap di
    bawahnya), TANPA placeholder kalau arti_id kosong."""
    arti_id = entry.get("arti_id")
    meanings_en = _load_list(entry.get("meanings_en"))
    meaning_jp = entry.get("meaning_jp")

    lines = []
    if _has_content(arti_id):
        lines.append(f"🇮🇩 {arti_id}")
    if meanings_en:
        en_text = ", ".join(meanings_en) if len(meanings_en) <= 3 else \
            "\n".join(f"{i}. {m}" for i, m in enumerate(meanings_en, start=1))
        lines.append(f"🇬🇧 {en_text}")
    if _has_content(meaning_jp):
        # meaning_jp sudah terformat ①②③ dari sumber, tampil apa adanya.
        lines.append(f"🇯🇵 {meaning_jp}")

    return "\n".join(lines) if lines else None


def _render_radikal_ringkas(entry: dict) -> Optional[str]:
    radikal_kanken = entry.get("radikal_kanken")
    info = _load_object(entry.get("radikal_info_kanken"))
    radikal_kanjivg = _load_list(entry.get("radikal_kanjivg"))

    if not _has_content(radikal_kanken) and not info:
        return None

    lines = []
    if _has_content(radikal_kanken):
        main_line = f"**{radikal_kanken}**"
        if info:
            detail_parts = []
            if info.get("cara_baca_jp"):
                romaji = info.get("cara_baca_romaji")
                detail_parts.append(f"{info['cara_baca_jp']}" + (f" ({romaji})" if romaji else ""))
            if info.get("arti_en"):
                detail_parts.append(info["arti_en"])
            if info.get("kategori"):
                detail_parts.append(f"kategori: {info['kategori']}")
            if detail_parts:
                main_line += " — " + ", ".join(detail_parts)
        lines.append(main_line)
    elif info:
        detail_parts = []
        if info.get("arti_en"):
            detail_parts.append(info["arti_en"])
        if info.get("kategori"):
            detail_parts.append(f"kategori: {info['kategori']}")
        if detail_parts:
            lines.append(", ".join(detail_parts))

    # radikal_kanjivg hanya ditampilkan kalau beda dari radikal_kanken
    # (metodologi KanjiVG vs Kanken bisa beda — §9).
    if radikal_kanjivg and radikal_kanjivg != [radikal_kanken]:
        lines.append(f"_KanjiVG:_ {'、'.join(radikal_kanjivg)}")

    return "\n".join(lines) if lines else None


def _render_jukugo(entry: dict) -> Optional[str]:
    jukugo = _load_list(entry.get("jukugo_contoh"))
    if not jukugo:
        return None

    by_kategori: dict[str, list[str]] = {}
    for item in jukugo:
        if not isinstance(item, dict):
            continue
        kategori = item.get("kategori", "外")
        kata = item.get("kata")
        if kata:
            by_kategori.setdefault(kategori, []).append(kata)

    blocks = []
    for kategori in JUKUGO_KATEGORI_ORDER:
        words = by_kategori.get(kategori)
        if not words:
            continue
        label = JUKUGO_KATEGORI_LABEL.get(kategori, kategori)
        shown = words[:JUKUGO_MAX_PER_KATEGORI]
        text = "、".join(shown)
        if len(words) > JUKUGO_MAX_PER_KATEGORI:
            text += f" (+{len(words) - JUKUGO_MAX_PER_KATEGORI} lainnya)"
        blocks.append(f"**{label}**\n{text}")

    return "\n\n".join(blocks) if blocks else None


def _render_dekomposisi(entry: dict) -> Optional[str]:
    """Pakai elemen_kanjivg (list flat) — struktur_dekomposisi_kanjivg
    (pohon nested) SENGAJA tidak pernah dirender (§9)."""
    elemen = _load_list(entry.get("elemen_kanjivg"))
    if not elemen:
        return None
    return "、".join(elemen)


def _render_kanji_terkait(entry: dict) -> Optional[str]:
    antonim = _load_list(entry.get("antonim"))
    sinonim = _load_list(entry.get("sinonim"))
    mirip = _load_list(entry.get("mirip_bentuk"))
    varian = _load_list(entry.get("varian"))

    if not (antonim or sinonim or mirip or varian):
        return None

    lines = []
    if antonim:
        lines.append(f"**Antonim:** {'、'.join(antonim)}")
    if sinonim:
        lines.append(f"**Sinonim:** {'、'.join(sinonim)}")
    if mirip:
        lines.append(f"**Mirip Bentuk:** {'、'.join(mirip)}")
    if varian:
        lines.append(f"**Varian:** {'、'.join(varian)}")

    bentuk_lama = entry.get("bentuk_lama_kyuujitai")
    if _has_content(bentuk_lama):
        lines.append(f"_Bentuk lama (旧字体): {bentuk_lama}_")

    return "\n".join(lines)


def _render_referensi(entry: dict) -> Optional[str]:
    kanjipedia = entry.get("kanjipedia_url")
    kanken_url = entry.get("kanken_url")
    links = []
    if _has_content(kanjipedia):
        links.append(f"[Kanjipedia]({kanjipedia})")
    if _has_content(kanken_url):
        links.append(f"[Kanken]({kanken_url})")
    return " · ".join(links) if links else None


def build_detail_pages(entry: dict, show_meaning: bool = True) -> list[discord.Embed]:
    """Pagination dinamis 1–3 halaman sesuai §7:
    - Hal.1: SELALU ada (info dasar + bacaan + arti + radikal ringkas)
    - Hal.2: jukugo_contoh, hanya kalau terisi
    - Hal.3: dekomposisi + kanji terkait + link referensi, kalau minimal
      salah satu terisi
    """
    title = _entry_title(entry)
    footer_text = _entry_footer(entry)
    color = discord.Color.blurple()
    if entry.get("joyo_status") == "TRUE":
        color = discord.Color.gold()

    pages: list[discord.Embed] = []

    # --- Halaman 1: selalu ada ---
    page1 = discord.Embed(title=title, color=color)
    info_dasar = _render_info_dasar(entry)
    if info_dasar:
        _add_long_field(page1, "ℹ️ Info Dasar", info_dasar)

    bacaan = _render_bacaan(entry)
    if bacaan:
        _add_long_field(page1, "🔤 Bacaan", bacaan)

    if show_meaning:
        arti = _render_arti(entry)
        if arti:
            _add_long_field(page1, "📚 Arti", arti)
    else:
        page1.add_field(
            name="📚 Arti",
            value="🔒 Upgrade Trial/Companion/Patron untuk lihat arti & detail lengkap.",
            inline=False,
        )

    radikal = _render_radikal_ringkas(entry)
    if radikal:
        _add_long_field(page1, "🧩 Radikal", radikal)

    pages.append(page1)

    # --- Halaman 2: jukugo, kalau terisi ---
    jukugo = _render_jukugo(entry) if show_meaning else None
    if jukugo:
        page2 = discord.Embed(title=title, color=color)
        _add_long_field(page2, "📝 Jukugo Contoh", jukugo)
        pages.append(page2)

    # --- Halaman 3: dekomposisi + kanji terkait + referensi ---
    if show_meaning:
        dekomposisi = _render_dekomposisi(entry)
        terkait = _render_kanji_terkait(entry)
        referensi = _render_referensi(entry)

        if dekomposisi or terkait or referensi:
            page3 = discord.Embed(title=title, color=color)
            if dekomposisi:
                _add_long_field(page3, "🧱 Komponen Penyusun", dekomposisi)
            if terkait:
                _add_long_field(page3, "🔗 Kanji Terkait", terkait)
            if referensi:
                page3.add_field(name="🌐 Referensi", value=referensi, inline=False)
            pages.append(page3)

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

def _build_list_query(jlpt: Optional[str], joyo: Optional[str], kelas_sd: Optional[str]) -> tuple[str, tuple]:
    clauses = []
    params: list = []
    if jlpt:
        clauses.append("k.jlpt_baru = ?")
        params.append(jlpt)
    if joyo:
        clauses.append("k.joyo_status = ?")
        params.append(joyo)
    if kelas_sd:
        clauses.append("k.kyouiku_kelas_sd = ?")
        params.append(kelas_sd)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    order = " ORDER BY (k.jlpt_baru IS NULL OR k.jlpt_baru = ''), k.jumlah_goresan ASC, k.kanji ASC;"
    return GET_ALL_FOR_LIST + where + order, tuple(params)


def _list_title(jlpt: Optional[str], joyo: Optional[str], kelas_sd: Optional[str]) -> str:
    parts = []
    if jlpt:
        parts.append(f"JLPT {jlpt}")
    if joyo:
        parts.append("Jōyō" if joyo == "TRUE" else "Non-Jōyō")
    if kelas_sd:
        parts.append(f"Kelas SD {kelas_sd}")
    suffix = f" — {', '.join(parts)}" if parts else ""
    return f"📖 Kamus Kanji{suffix}"


def build_list_pages(
    entries: list[dict], title: str, show_meaning: bool = True
) -> tuple[list[discord.Embed], list[list[dict]]]:
    chunks = [entries[i:i + LIST_PAGE_SIZE] for i in range(0, len(entries), LIST_PAGE_SIZE)] or [[]]
    total_pages = len(chunks)

    pages = []
    for idx, chunk in enumerate(chunks, start=1):
        lines = []
        for e in chunk:
            tags = []
            if e["jlpt_baru"]:
                tags.append(e["jlpt_baru"])
            if e["joyo_status"] == "TRUE":
                tags.append("Jōyō")
            if e["kyouiku_kelas_sd"]:
                tags.append(f"SD{e['kyouiku_kelas_sd']}")
            tag_str = f" `{' '.join(tags)}`" if tags else ""
            header = f"**{e['kanji']}**{tag_str}"

            if show_meaning:
                meaning = e.get("arti_id")
                if not _has_content(meaning):
                    en_list = _load_list(e.get("meanings_en"))
                    meaning = en_list[0] if en_list else "—"
                if len(meaning) > 60:
                    meaning = meaning[:57] + "..."
                lines.append(f"{header}\n{meaning}")
            else:
                lines.append(header)

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

class KanjiPaginatorView(discord.ui.View):
    """View Prev/Next generik untuk mode detail (1–3 halaman dinamis)."""

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
        # Kalau cuma 1 halaman, tombol tidak perlu ditampilkan sama sekali.
        self.prev_button.disabled = self.prev_button.disabled or len(self.pages) <= 1
        self.next_button.disabled = self.next_button.disabled or len(self.pages) <= 1

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


class KanjiListView(discord.ui.View):
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

        options = []
        for e in entries:
            desc = "🔒 Upgrade Companion untuk lihat arti & detail"
            if self.show_meaning:
                meaning = e.get("arti_id")
                if not _has_content(meaning):
                    en_list = _load_list(e.get("meanings_en"))
                    meaning = en_list[0] if en_list else "—"
                desc = meaning[:100]
            options.append(discord.SelectOption(label=e["kanji"][:100], description=desc, value=e["kanji"]))

        select = discord.ui.Select(
            placeholder="Pilih kanji untuk lihat detail lengkap...",
            options=options,
            row=0,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Ini bukan pencarian kamu.", ephemeral=True)

        # Celah arsitektur yang sama seperti /bunpou & /kotoba: dropdown ini
        # interaksi komponen, bukan slash command baru — access check WAJIB
        # dicek ulang di sini.
        if not has_dic_access(interaction.user, interaction.guild_id):
            return await interaction.response.send_message(MSG_DIC_DETAIL_ONLY, ephemeral=True)

        kanji = interaction.data["values"][0]
        bot: KotabiBot = interaction.client
        row = await bot.GET_ONE(GET_ENTRY, (kanji,))
        if not row:
            return await interaction.response.send_message("❌ Entri tidak ditemukan lagi.", ephemeral=True)

        entry = _row_to_dict(row)
        detail_pages = build_detail_pages(entry, show_meaning=True)
        for p in detail_pages:
            _add_requester_info(p, interaction.user)

        detail_view = KanjiPaginatorView(interaction.user.id, detail_pages)
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

class Kanji(commands.Cog):
    def __init__(self, bot: KotabiBot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.RUN(CREATE_TABLE)
        await self.bot.RUN(CREATE_MEANINGS_TABLE)
        for index_query in CREATE_INDEXES:
            await self.bot.RUN(index_query)
        await self.load_csv()

    async def load_csv(self):
        """Full-replace kanji_entries dari kanji_master.csv DAN kanji_meanings_id
        dari kanji_meanings_id.csv — keduanya sumber kebenaran penuh tiap
        reload (§5), bukan upsert parsial.

        kanji_master.csv adalah CSV comma-delimited BIASA (bukan format Anki
        tab-delimited seperti bunpou/kotoba) — TIDAK ada baris #separator
        yang perlu dilewati.
        """
        await self._load_kanji_master()
        await self._load_meanings_id()

    async def _load_kanji_master(self):
        if not os.path.exists(CSV_PATH):
            _log.warning("⚠️ File %s tidak ditemukan. Kamus kanji kosong.", CSV_PATH)
            return

        with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            if header != FIELD_NAMES:
                _log.error(
                    "❌ Header %s TIDAK cocok dengan FIELD_NAMES di kanji_fields.py "
                    "— pemuatan dibatalkan supaya tidak salah petakan kolom diam-diam. "
                    "Header ditemukan: %s",
                    CSV_PATH, header,
                )
                return

            rows = [tuple(row.get(col, "") for col in FIELD_NAMES) for row in reader]

        await self.bot.RUN(DELETE_ALL_ENTRIES)
        if rows:
            await self.bot.RUN_MANY(INSERT_ENTRY, rows)

        _log.info("✅ %d entri kanji dimuat dari %s.", len(rows), CSV_PATH)

    async def _load_meanings_id(self):
        if not os.path.exists(MEANINGS_ID_CSV_PATH):
            _log.warning(
                "⚠️ File %s tidak ditemukan. Overlay arti_id kosong (fallback ke EN/JP).",
                MEANINGS_ID_CSV_PATH,
            )
            await self.bot.RUN(DELETE_ALL_MEANINGS)
            return

        with open(MEANINGS_ID_CSV_PATH, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            if header != ["kanji", "arti_id"]:
                _log.error(
                    "❌ Header %s harus persis 'kanji,arti_id' — pemuatan overlay dibatalkan. "
                    "Header ditemukan: %s",
                    MEANINGS_ID_CSV_PATH, header,
                )
                return

            rows = [
                (row.get("kanji", "").strip(), row.get("arti_id", ""))
                for row in reader
                if row.get("kanji", "").strip()
            ]

        await self.bot.RUN(DELETE_ALL_MEANINGS)
        if rows:
            await self.bot.RUN_MANY(INSERT_MEANING, rows)

        _log.info("✅ %d overlay arti_id dimuat dari %s.", len(rows), MEANINGS_ID_CSV_PATH)

    @discord.app_commands.command(
        name="kanji",
        description="Cari kanji di kamus, atau jelajahi berdasarkan JLPT/Jōyō/kelas SD.",
    )
    @discord.app_commands.describe(
        kanji="Ketik karakter kanji, bacaan, atau arti. Kalau diisi, filter lain diabaikan untuk mode detail.",
        jlpt="Filter berdasarkan level JLPT (opsional).",
        joyo="Filter berdasarkan status Jōyō Kanji (opsional).",
        kelas_sd="Filter berdasarkan kelas SD (opsional).",
    )
    @discord.app_commands.choices(
        jlpt=[discord.app_commands.Choice(name=lvl, value=lvl) for lvl in JLPT_CHOICES],
        joyo=[discord.app_commands.Choice(name=name, value=value) for name, value in JOYO_CHOICES],
        kelas_sd=[discord.app_commands.Choice(name=f"Kelas {k}", value=k) for k in KELAS_SD_CHOICES],
    )
    @discord.app_commands.autocomplete(kanji=kanji_autocomplete)
    @discord.app_commands.guild_only()
    async def kanji_command(
        self,
        interaction: discord.Interaction,
        kanji: Optional[str] = None,
        jlpt: Optional[str] = None,
        joyo: Optional[str] = None,
        kelas_sd: Optional[str] = None,
    ):
        # Command TIDAK di-gate akses secara keseluruhan — mode list terbuka
        # untuk semua role (termasuk Drifter). Access check detail dicek
        # eksplisit di sini DAN di KanjiListView._on_select (celah dropdown).
        await interaction.response.defer(ephemeral=True)

        # Mode detail: kanji diisi.
        if kanji:
            has_access = has_dic_access(interaction.user, interaction.guild_id)
            if not has_access:
                await interaction.followup.send(MSG_DIC_DETAIL_ONLY, ephemeral=True)
                return

            row = await self.bot.GET_ONE(GET_ENTRY, (kanji,))
            if not row:
                await interaction.followup.send(
                    "❌ Kanji tidak ditemukan di kamus. Gunakan menu autocomplete saat mengetik.",
                    ephemeral=True,
                )
                return

            entry = _row_to_dict(row)
            pages = build_detail_pages(entry, show_meaning=True)
            for p in pages:
                _add_requester_info(p, interaction.user)

            view = KanjiPaginatorView(interaction.user.id, pages)
            message = await interaction.followup.send(embed=pages[0], view=view, ephemeral=True, wait=True)
            view.message = message
            return

        # Mode list/browse: kombinasi filter jlpt/joyo/kelas_sd, atau kosong.
        query, params = _build_list_query(jlpt, joyo, kelas_sd)
        rows = await self.bot.GET(query, params)

        if not rows:
            await interaction.followup.send(
                "❌ Tidak ada kanji yang cocok dengan filter tersebut.", ephemeral=True
            )
            return

        entries = [
            {
                "kanji": r[0], "jlpt_baru": r[1], "joyo_status": r[2],
                "kyouiku_kelas_sd": r[3], "kanken_kyu_resmi": r[4],
                "meanings_en": r[5], "arti_id": r[6],
            }
            for r in rows
        ]
        show_meaning = has_dic_access(interaction.user, interaction.guild_id)
        title = _list_title(jlpt, joyo, kelas_sd)
        pages, page_entries = build_list_pages(entries, title, show_meaning=show_meaning)
        for p in pages:
            _add_requester_info(p, interaction.user)

        view = KanjiListView(interaction.user.id, pages, page_entries, show_meaning=show_meaning)
        message = await interaction.followup.send(embed=pages[0], view=view, ephemeral=True, wait=True)
        view.message = message

    @discord.app_commands.command(name="kanji_reload", description="Muat ulang kamus kanji dari CSV (Khusus Admin).")
    @discord.app_commands.default_permissions(administrator=True)
    async def kanji_reload(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.load_csv()
        count_row = await self.bot.GET_ONE(f"SELECT COUNT(*) FROM {TABLE_NAME};")
        total = count_row[0] if count_row else 0
        meanings_row = await self.bot.GET_ONE(f"SELECT COUNT(*) FROM {MEANINGS_TABLE};")
        total_meanings = meanings_row[0] if meanings_row else 0
        await interaction.followup.send(
            f"✅ Kamus kanji dimuat ulang. Total entri: **{total}** "
            f"(overlay arti_id terisi: **{total_meanings}**).",
            ephemeral=True,
        )


async def setup(bot: KotabiBot):
    await bot.add_cog(Kanji(bot))