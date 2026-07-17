"""
features/dictionary/kanji_cog.py — Kamus Kanji Bahasa Jepang (/kanji)
=========================================================================
Beda dengan bunpou_cog.py/kotoba_cog.py: data kanji SUDAH LENGKAP (hasil
gabungan 4 sumber terbuka, lihat README.md database gabungan kanji),
bukan hasil authoring manual satu-per-satu. Effort di sini sepenuhnya di
pemetaan skema -> kategori tampilan, bukan pengisian data.

Detail keputusan desain lengkap ada di panduan-kamus-kanji-versi-ringkas.md
(termasuk kenapa TIDAK JOIN ke radikal_master.csv di v1, dan kenapa
struktur_dekomposisi_kanjivg tidak pernah dirender sebagai pohon utuh).
Ringkasnya:

- Sumber utama: kanji_master.csv (13.141 baris, 41 kolom, CSV standar
  koma+quote RFC4180 -- BEDA dari bunpou/kotoba yang tab-delimited ekspor
  Anki). Beberapa kolom isinya TEKS JSON di dalam satu sel (list/object) --
  lihat kanji_fields.py LIST_JSON_FIELDS/OBJECT_JSON_FIELDS, di-json.loads()
  saat render, disimpan TEXT apa adanya di SQLite (tidak dinormalisasi ke
  tabel anak).
- Overlay tambahan: kanji_meanings_id.csv (2 kolom: kanji, arti_id) --
  terjemahan Bahasa Indonesia, sengaja file TERPISAH dari kanji_master.csv
  (supaya tidak fork master data hasil gabungan 4 sumber), BOLEH KOSONG,
  diisi bertahap. LEFT JOIN saat query detail. Kalau arti_id kosong,
  fallback ke meanings_en/meaning_jp TANPA placeholder "belum
  diterjemahkan" ke user.
- TIDAK JOIN ke radikal_master.csv -- radikal Kanken sudah ter-embed
  penuh di kolom radikal_info_kanken (object: nomor, strokes, kategori,
  arti_en, cara_baca_jp, cara_baca_romaji), tidak perlu lookup tambahan.
- radikal_kanken (1 karakter, skema Kanken) BUKAN hal yang sama dengan
  radikal_kanjivg (list beberapa karakter, skema KanjiVG, elemen
  struktural 1-level -- BUKAN pohon dekomposisi penuh, itu tugas
  struktur_dekomposisi_kanjivg yang nested dan sengaja tidak dirender
  utuh di sini). Keduanya ditampilkan sebagai baris terpisah, bukan
  dibandingkan satu-satu.
- Pagination DINAMIS (1-3 halaman tergantung isi), bukan jumlah tetap:
    Halaman 1 (selalu ada): Info Dasar + Bacaan + Arti + Radikal ringkas
    Halaman 2 (kalau jukugo_contoh terisi): Jukugo dikelompokkan per
      kategori 小/中/高/外
    Halaman 3 (kalau ada salah satu dari: elemen_kanjivg, kanji terkait,
      link referensi): Dekomposisi + Kanji Terkait + Referensi
- Gating akses IDENTIK /bunpou & /kotoba: has_dic_access() dari
  shared/checks.py, mode list gratis untuk semua role (arti dikunci utk
  non-akses), mode detail penuh butuh Trial/Companion/Patron/staff.

--------------------------------------------------------------------
KEAMANAN SQL
--------------------------------------------------------------------
CREATE TABLE memakai nama kolom dari FIELD_NAMES (kanji_fields.py) --
konstanta tetap, bukan dari CSV/input pengguna. Semua query yang
menyentuh input pengguna pakai parameter binding ("?"). Insert baris CSV
lewat bot.RUN_MANY() (executemany).

--------------------------------------------------------------------
LOADER CSV (FULL REPLACE)
--------------------------------------------------------------------
Sama seperti bunpou_cog.py/kotoba_cog.py: setiap cog_load() / /kanji_reload
menjalankan full replace (DELETE semua baris, INSERT ulang dari CSV).
kanji_master.csv DAN kanji_meanings_id.csv masing-masing dimuat penuh
setiap kali -- overlay terjemahan yang diedit manual otomatis kepakai
begitu /kanji_reload dijalankan, tidak perlu proses upsert rumit.

Format kanji_master.csv: CSV standar (koma, quote RFC4180 ganda ""), TIDAK
ada baris metadata #separator seperti ekspor Anki -- header ada di baris
pertama langsung. Ini beda penting dari bunpou-notes-master.csv/
kotoba-notes-master.csv yang tab-delimited dan punya baris #separator:Tab
opsional.
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
    LIST_JSON_FIELDS,
    OBJECT_JSON_FIELDS,
    HIDDEN_FIELDS,
    JUKUGO_KATEGORI_LABEL,
)

_log = logging.getLogger("bot.kanji")

# ============================================================================
# PATH & SKEMA
# ============================================================================

CSV_PATH = os.getenv("ALT_KANJI_CSV_PATH") or "features/dictionary/kanji_master.csv"
MEANINGS_CSV_PATH = (
    os.getenv("ALT_KANJI_MEANINGS_ID_CSV_PATH") or "features/dictionary/kanji_meanings_id.csv"
)

TABLE_NAME = "kanji_entries"
MEANINGS_TABLE = "kanji_meanings_id"

_COLUMN_DEFS = ", ".join(
    f"{col} TEXT PRIMARY KEY" if col == KEY_FIELD else f"{col} TEXT"
    for col in FIELD_NAMES
)
CREATE_TABLE = f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} ({_COLUMN_DEFS});"
CREATE_MEANINGS_TABLE = (
    f"CREATE TABLE IF NOT EXISTS {MEANINGS_TABLE} (kanji TEXT PRIMARY KEY, arti_id TEXT);"
)

DELETE_ALL = f"DELETE FROM {TABLE_NAME};"
DELETE_ALL_MEANINGS = f"DELETE FROM {MEANINGS_TABLE};"

INSERT_ENTRY = (
    f"INSERT INTO {TABLE_NAME} ({', '.join(FIELD_NAMES)}) "
    f"VALUES ({', '.join(['?'] * len(FIELD_NAMES))});"
)
INSERT_MEANING = f"INSERT INTO {MEANINGS_TABLE} (kanji, arti_id) VALUES (?, ?);"

GET_ENTRY = f"SELECT {', '.join(FIELD_NAMES)} FROM {TABLE_NAME} WHERE {KEY_FIELD} = ?;"
GET_ARTI_ID = f"SELECT arti_id FROM {MEANINGS_TABLE} WHERE kanji = ?;"

GET_ALL_FOR_LIST_BASE = (
    f"SELECT kanji, meanings_en, jlpt_baru, joyo_status, kyouiku_kelas_sd, kanken_kyu_resmi "
    f"FROM {TABLE_NAME}"
)

SEARCH_QUERY = f"""
SELECT kanji, meanings_en, jlpt_baru, joyo_status, kyouiku_kelas_sd, kanken_kyu_resmi
FROM {TABLE_NAME}
WHERE kanji = ?
   OR on_yomi LIKE '%' || ? || '%'
   OR kun_yomi LIKE '%' || ? || '%'
   OR meanings_en LIKE '%' || ? || '%'
ORDER BY (jlpt_baru IS NULL), jlpt_baru ASC, jumlah_goresan ASC
LIMIT 25;
"""

JLPT_CHOICES = ["N5", "N4", "N3", "N2", "N1"]
KELAS_SD_CHOICES = ["1", "2", "3", "4", "5", "6"]

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
JUKUGO_CAP_PER_KATEGORI = 15


# ============================================================================
# HELPERS -- JSON-in-cell parsing (BEDA dari bunpou/kotoba, lihat modul docstring)
# ============================================================================

def _row_to_dict(row: tuple) -> dict:
    return dict(zip(FIELD_NAMES, row))


def _has_content(value: Optional[str]) -> bool:
    return bool(value) and value.strip() not in ("", "—", "null")


def _parse_list(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_object(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


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
    # Potong aman di batas kalimat/koma terdekat, bukan di tengah karakter.
    truncated = value[: MAX_FIELD_LENGTH - 20].rsplit("\n", 1)[0]
    embed.add_field(name=name, value=truncated + "\n…(dipotong)", inline=False)


# ============================================================================
# RENDERING PER KATEGORI
# ============================================================================

def _entry_title(entry: dict) -> str:
    kanji = entry.get("kanji", "?")
    goresan = entry.get("jumlah_goresan")
    title = f"{kanji}"
    if _has_content(goresan):
        title += f" （{goresan} goresan）"
    return title


def _level_badges(entry: dict) -> str:
    parts = []
    if entry.get("joyo_status") == "TRUE":
        urutan = entry.get("joyo_urutan")
        parts.append(f"Jōyō #{urutan}" if _has_content(urutan) else "Jōyō")
    if _has_content(entry.get("jlpt_baru")):
        parts.append(f"JLPT {entry['jlpt_baru']}")
    if _has_content(entry.get("kyouiku_kelas_sd")):
        parts.append(f"Kyōiku Kelas {entry['kyouiku_kelas_sd']} SD")
    if _has_content(entry.get("kanken_kyu_resmi")):
        parts.append(f"Kanken {entry['kanken_kyu_resmi']}")
    if _has_content(entry.get("freq_rank_mainichi_shinbun")):
        parts.append(f"Frekuensi #{entry['freq_rank_mainichi_shinbun']} (Mainichi Shinbun)")
    return " · ".join(parts) if parts else "Belum terklasifikasi (di luar Jōyō/JLPT/Kanken resmi)"


def _render_bacaan(entry: dict) -> Optional[str]:
    on_yomi = _parse_list(entry.get("on_yomi"))
    kun_yomi = _parse_list(entry.get("kun_yomi"))
    nanori = _parse_list(entry.get("nanori"))
    if not (on_yomi or kun_yomi or nanori):
        return None
    lines = []
    if on_yomi:
        lines.append(f"**On'yomi**: {'、'.join(on_yomi)}")
    if kun_yomi:
        lines.append(f"**Kun'yomi**: {'、'.join(kun_yomi)}")
    if nanori:
        lines.append(f"**Nanori** (bacaan nama): {'、'.join(nanori)}")
    return "\n".join(lines)


def _render_arti(entry: dict, arti_id: Optional[str]) -> Optional[str]:
    meanings_en = _parse_list(entry.get("meanings_en"))
    meaning_jp = entry.get("meaning_jp")
    lines = []
    if _has_content(arti_id):
        # arti_id sudah diisi manual -> section utama, EN/JP tetap ditampilkan
        # sebagai pelengkap di bawahnya (BUKAN digantikan), lihat panduan §3.3a.
        lines.append(f"🇮🇩 {arti_id}")
        if meanings_en:
            lines.append(f"🇬🇧 {', '.join(meanings_en)}")
        if _has_content(meaning_jp):
            lines.append(f"🇯🇵 {meaning_jp}")
    else:
        # arti_id belum diisi -> fallback EN/JP, TANPA placeholder "belum
        # diterjemahkan" (lihat panduan §3.3a, ini akan jadi mayoritas kanji
        # di rilis awal, jangan sampai mengganggu tampilan).
        if meanings_en:
            lines.append(f"🇬🇧 {', '.join(meanings_en)}")
        if _has_content(meaning_jp):
            lines.append(f"🇯🇵 {meaning_jp}")
    return "\n".join(lines) if lines else None


def _render_radikal(entry: dict) -> Optional[str]:
    radikal_kanken = entry.get("radikal_kanken")
    info = _parse_object(entry.get("radikal_info_kanken"))
    radikal_kanjivg = _parse_list(entry.get("radikal_kanjivg"))

    lines = []
    if _has_content(radikal_kanken):
        line = f"**Radikal (Kanken)**: {radikal_kanken}"
        if info:
            detail_parts = []
            if info.get("cara_baca_jp"):
                detail_parts.append(f"{info['cara_baca_jp']} ({info.get('cara_baca_romaji', '')})".strip())
            if info.get("arti_en"):
                detail_parts.append(info["arti_en"])
            if info.get("kategori"):
                detail_parts.append(f"kategori {info['kategori']}")
            if detail_parts:
                line += f" — {', '.join(detail_parts)}"
        lines.append(line)

    # radikal_kanjivg BUKAN radikal tunggal alternatif -- daftar beberapa
    # elemen struktural versi KanjiVG, ditampilkan terpisah (lihat catatan
    # penting di kanji_fields.py, jangan disamakan dengan radikal_kanken).
    if radikal_kanjivg:
        lines.append(f"**Elemen KanjiVG**: {'、'.join(radikal_kanjivg)}")

    return "\n".join(lines) if lines else None


def _render_jukugo(entry: dict) -> Optional[str]:
    jukugo = _parse_list(entry.get("jukugo_contoh"))
    if not jukugo:
        return None

    grouped: dict[str, list[str]] = {}
    for item in jukugo:
        if not isinstance(item, dict):
            continue
        kategori = item.get("kategori", "外")
        kata = item.get("kata")
        if kata:
            grouped.setdefault(kategori, []).append(kata)

    lines = []
    # Urutan tampil: 小 -> 中 -> 高 -> 外 (mudah ke sulit), sesuai urutan
    # JUKUGO_KATEGORI_LABEL di kanji_fields.py.
    for kategori in ["小", "中", "高", "外"]:
        kata_list = grouped.get(kategori)
        if not kata_list:
            continue
        label = JUKUGO_KATEGORI_LABEL.get(kategori, kategori)
        shown = kata_list[:JUKUGO_CAP_PER_KATEGORI]
        line = f"**{label}**: {'、'.join(shown)}"
        if len(kata_list) > JUKUGO_CAP_PER_KATEGORI:
            line += f" (+{len(kata_list) - JUKUGO_CAP_PER_KATEGORI} lainnya)"
        lines.append(line)

    return "\n".join(lines) if lines else None


def _render_dekomposisi(entry: dict) -> Optional[str]:
    # struktur_dekomposisi_kanjivg SENGAJA tidak dirender (pohon nested,
    # bisa >5 level dalam -- lihat modul docstring). Cukup elemen_kanjivg
    # (list flat, superset semua komponen).
    elemen = _parse_list(entry.get("elemen_kanjivg"))
    if not elemen:
        return None
    return f"**Komponen Penyusun**: {'、'.join(elemen)}"


def _render_kanji_terkait(entry: dict) -> Optional[str]:
    antonim = _parse_list(entry.get("antonim"))
    sinonim = _parse_list(entry.get("sinonim"))
    mirip = _parse_list(entry.get("mirip_bentuk"))
    varian = _parse_list(entry.get("varian"))
    kyuujitai = entry.get("bentuk_lama_kyuujitai")

    lines = []
    if antonim:
        lines.append(f"**Antonim**: {'、'.join(antonim)}")
    if sinonim:
        lines.append(f"**Sinonim**: {'、'.join(sinonim)}")
    if mirip:
        lines.append(f"**Mirip Bentuk**: {'、'.join(mirip)}")
    if varian:
        lines.append(f"**Varian**: {'、'.join(varian)}")
    if _has_content(kyuujitai):
        lines.append(f"**Bentuk Lama (旧字体)**: {kyuujitai}")

    return "\n".join(lines) if lines else None


def _render_referensi(entry: dict) -> Optional[str]:
    lines = []
    jumlah_kosakata = entry.get("jumlah_kosakata_terkait")
    if _has_content(jumlah_kosakata) and jumlah_kosakata != "0":
        lines.append(f"📚 Dipakai di **{jumlah_kosakata}** entri kosakata")
    if _has_content(entry.get("kanjipedia_url")):
        lines.append(f"[Kanjipedia]({entry['kanjipedia_url']})")
    if _has_content(entry.get("kanken_url")):
        lines.append(f"[jitenon.jp]({entry['kanken_url']})")
    return "\n".join(lines) if lines else None


def build_detail_pages(entry: dict, arti_id: Optional[str]) -> list[discord.Embed]:
    """Pagination DINAMIS -- lihat modul docstring untuk aturan tiap halaman."""
    color = LEVEL_COLOR.get(entry.get("jlpt_baru"), discord.Color.blurple())
    title = f"📖 {_entry_title(entry)}"
    footer = _level_badges(entry)

    pages: list[discord.Embed] = []

    # Halaman 1 -- selalu ada.
    page1 = discord.Embed(title=title, color=color)
    bacaan = _render_bacaan(entry)
    arti = _render_arti(entry, arti_id)
    radikal = _render_radikal(entry)
    if bacaan:
        _add_long_field(page1, "🔤 Bacaan", bacaan)
    if arti:
        _add_long_field(page1, "💬 Arti", arti)
    if radikal:
        _add_long_field(page1, "🧩 Radikal", radikal)
    if not (bacaan or arti or radikal):
        page1.description = "Belum ada detail bacaan/arti/radikal untuk kanji ini di sumber data."
    pages.append(page1)

    # Halaman 2 -- hanya kalau jukugo_contoh terisi.
    jukugo = _render_jukugo(entry)
    if jukugo:
        page2 = discord.Embed(title=title, color=color)
        _add_long_field(page2, "📝 Jukugo Contoh", jukugo)
        pages.append(page2)

    # Halaman 3 -- hanya kalau minimal salah satu bagian ini terisi.
    dekomposisi = _render_dekomposisi(entry)
    terkait = _render_kanji_terkait(entry)
    referensi = _render_referensi(entry)
    if dekomposisi or terkait or referensi:
        page3 = discord.Embed(title=title, color=color)
        if dekomposisi:
            _add_long_field(page3, "🔩 Dekomposisi Grafis", dekomposisi)
        if terkait:
            _add_long_field(page3, "🔗 Kanji Terkait", terkait)
        if referensi:
            _add_long_field(page3, "📎 Referensi", referensi)
        pages.append(page3)

    total = len(pages)
    for idx, page in enumerate(pages, start=1):
        parts = []
        if total > 1:
            parts.append(f"Halaman {idx}/{total}")
        if footer:
            parts.append(footer)
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
        clauses.append("jlpt_baru = ?")
        params.append(jlpt)
    if joyo:
        clauses.append("joyo_status = ?")
        params.append("TRUE" if joyo == "ya" else "FALSE")
    if kelas_sd:
        clauses.append("kyouiku_kelas_sd = ?")
        params.append(kelas_sd)

    query = GET_ALL_FOR_LIST_BASE
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY (jlpt_baru IS NULL), jlpt_baru ASC, jumlah_goresan ASC;"
    return query, tuple(params)


def _list_title(jlpt: Optional[str], joyo: Optional[str], kelas_sd: Optional[str]) -> str:
    filters = []
    if jlpt:
        filters.append(f"JLPT {jlpt}")
    if joyo == "ya":
        filters.append("Jōyō")
    elif joyo == "tidak":
        filters.append("Non-Jōyō")
    if kelas_sd:
        filters.append(f"Kelas {kelas_sd} SD")
    if filters:
        return f"📚 Kamus Kanji — {' · '.join(filters)}"
    return "📚 Semua Entri Kamus Kanji"


def build_list_pages(
    entries: list[dict], jlpt: Optional[str], joyo: Optional[str], kelas_sd: Optional[str],
    show_meaning: bool = True,
) -> tuple[list[discord.Embed], list[list[dict]]]:
    title = _list_title(jlpt, joyo, kelas_sd)
    chunks = [entries[i:i + LIST_PAGE_SIZE] for i in range(0, len(entries), LIST_PAGE_SIZE)] or [[]]
    total_pages = len(chunks)

    pages = []
    for idx, chunk in enumerate(chunks, start=1):
        lines = []
        for e in chunk:
            kanji = e["kanji"]
            tags = []
            if e.get("jlpt_baru"):
                tags.append(e["jlpt_baru"])
            if e.get("joyo_status") == "TRUE":
                tags.append("Jōyō")
            tag_str = f" `{' '.join(tags)}`" if tags else ""
            header_line = f"**{kanji}**{tag_str}"

            if show_meaning:
                meanings = _parse_list(e.get("meanings_en"))
                meaning_preview = ", ".join(meanings[:3]) if meanings else "—"
                lines.append(f"{header_line}\n{meaning_preview}")
            else:
                lines.append(header_line)

        embed = discord.Embed(
            title=title,
            description="\n\n".join(lines) or "Tidak ada entri.",
            color=discord.Color.blurple(),
        )
        footer = f"Halaman {idx}/{total_pages} • Total {len(entries)} kanji"
        if not show_meaning:
            footer += " • Arti terkunci, upgrade Companion untuk lihat detail"
        embed.set_footer(text=footer)
        pages.append(embed)

    return pages, chunks


# ============================================================================
# AUTOCOMPLETE
# ============================================================================

async def kanji_autocomplete(interaction: discord.Interaction, current_input: str):
    bot: KotabiBot = interaction.client
    current_input = current_input.strip()
    if not current_input:
        return []

    rows = await bot.GET(SEARCH_QUERY, (current_input, current_input, current_input, current_input))
    choices = []
    for kanji, meanings_en_raw, jlpt_baru, joyo_status, _kelas, kanken in rows:
        meanings = _parse_list(meanings_en_raw)
        meaning_preview = meanings[0] if meanings else "—"
        tag = jlpt_baru or ("Jōyō" if joyo_status == "TRUE" else "")
        label = f"{kanji} ({tag}) — {meaning_preview}" if tag else f"{kanji} — {meaning_preview}"
        choices.append(discord.app_commands.Choice(name=label[:100], value=kanji))
    return choices[:25]


# ============================================================================
# PAGINATION VIEWS
# ============================================================================

class KanjiPaginatorView(discord.ui.View):
    """View Prev/Next untuk mode detail (1-3 halaman dinamis)."""

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
        # Kalau cuma 1 halaman (kanji minim data), sembunyikan tombol sama sekali.
        self.prev_button.style = discord.ButtonStyle.secondary
        if len(self.pages) <= 1:
            self.clear_items()

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
            meanings = _parse_list(e.get("meanings_en"))
            desc = (
                ", ".join(meanings[:3]) if (self.show_meaning and meanings)
                else "🔒 Upgrade Companion untuk lihat arti & detail" if not self.show_meaning
                else "—"
            )
            options.append(
                discord.SelectOption(label=e["kanji"][:100], description=desc[:100], value=e["kanji"])
            )

        select = discord.ui.Select(
            placeholder="Pilih kanji untuk lihat detail lengkap...", options=options, row=0,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Ini bukan pencarian kamu.", ephemeral=True)

        # Celah arsitektur yang sama seperti /bunpou & /kotoba: dropdown ini
        # interaksi komponen, bukan slash command baru -- access check WAJIB
        # dicek ulang di sini, bukan cuma diwariskan dari command awal.
        if not has_dic_access(interaction.user, interaction.guild_id):
            return await interaction.response.send_message(MSG_DIC_DETAIL_ONLY, ephemeral=True)

        kanji = interaction.data["values"][0]
        bot: KotabiBot = interaction.client
        row = await bot.GET_ONE(GET_ENTRY, (kanji,))
        if not row:
            return await interaction.response.send_message("❌ Entri tidak ditemukan lagi.", ephemeral=True)

        entry = _row_to_dict(row)
        arti_row = await bot.GET_ONE(GET_ARTI_ID, (kanji,))
        arti_id = arti_row[0] if arti_row else None

        detail_pages = build_detail_pages(entry, arti_id)
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
        await self.load_csv()
        await self.load_meanings_csv()

    async def load_csv(self):
        """kanji_master.csv -- CSV standar koma+quote RFC4180, header baris
        pertama langsung (BEDA dari bunpou/kotoba yang tab-delimited & bisa
        punya baris #separator:Tab opsional -- lihat modul docstring)."""
        if not os.path.exists(CSV_PATH):
            _log.warning("⚠️ File %s tidak ditemukan. Kamus kanji kosong.", CSV_PATH)
            return

        with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)  # delimiter default koma
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

        await self.bot.RUN(DELETE_ALL)
        if rows:
            await self.bot.RUN_MANY(INSERT_ENTRY, rows)

        _log.info("✅ %d entri kanji dimuat dari %s.", len(rows), CSV_PATH)

    async def load_meanings_csv(self):
        """kanji_meanings_id.csv -- overlay terjemahan Indonesia, BOLEH KOSONG
        (cuma header). Full replace juga, supaya edit manual langsung kepakai
        setelah /kanji_reload."""
        if not os.path.exists(MEANINGS_CSV_PATH):
            _log.warning(
                "⚠️ File %s tidak ditemukan. Arti Bahasa Indonesia akan fallback "
                "ke meanings_en/meaning_jp untuk semua kanji.", MEANINGS_CSV_PATH,
            )
            return

        with open(MEANINGS_CSV_PATH, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            if header != ["kanji", "arti_id"]:
                _log.error(
                    "❌ Header %s harus persis 'kanji,arti_id' — pemuatan overlay "
                    "terjemahan dibatalkan. Header ditemukan: %s",
                    MEANINGS_CSV_PATH, header,
                )
                return

            rows = [
                (row.get("kanji", ""), row.get("arti_id", ""))
                for row in reader
                if row.get("kanji") and row.get("arti_id")
            ]

        await self.bot.RUN(DELETE_ALL_MEANINGS)
        if rows:
            await self.bot.RUN_MANY(INSERT_MEANING, rows)

        _log.info(
            "✅ %d terjemahan Indonesia dimuat dari %s (dari total kanji di database).",
            len(rows), MEANINGS_CSV_PATH,
        )

    @discord.app_commands.command(
        name="kanji",
        description="Cari kanji di kamus, atau jelajahi berdasarkan level JLPT/Jōyō/kelas SD.",
    )
    @discord.app_commands.describe(
        kanji="Ketik karakter kanji, bacaan on/kun, atau arti Inggris. Kalau diisi, filter lain diabaikan untuk mode detail.",
        jlpt="Filter berdasarkan level JLPT (opsional).",
        joyo="Filter berdasarkan status Jōyō Kanji resmi (opsional).",
        kelas_sd="Filter berdasarkan kelas SD Kyōiku Kanji (opsional).",
    )
    @discord.app_commands.choices(
        jlpt=[discord.app_commands.Choice(name=lvl, value=lvl) for lvl in JLPT_CHOICES],
        joyo=[
            discord.app_commands.Choice(name="Ya (Jōyō)", value="ya"),
            discord.app_commands.Choice(name="Tidak (Non-Jōyō)", value="tidak"),
        ],
        kelas_sd=[discord.app_commands.Choice(name=f"Kelas {k} SD", value=k) for k in KELAS_SD_CHOICES],
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
        # Mode list terbuka untuk semua role (termasuk Drifter) -- access
        # check detail dicek eksplisit di sini DAN di KanjiListView._on_select
        # (celah dropdown, sama seperti /bunpou & /kotoba).
        await interaction.response.defer(ephemeral=True)

        # Mode detail: kanji diisi.
        if kanji:
            if not has_dic_access(interaction.user, interaction.guild_id):
                await interaction.followup.send(MSG_DIC_DETAIL_ONLY, ephemeral=True)
                return

            row = await self.bot.GET_ONE(GET_ENTRY, (kanji,))
            if not row:
                await interaction.followup.send(
                    "❌ Kanji tidak ditemukan. Gunakan menu autocomplete saat mengetik.",
                    ephemeral=True,
                )
                return

            entry = _row_to_dict(row)
            arti_row = await self.bot.GET_ONE(GET_ARTI_ID, (kanji,))
            arti_id = arti_row[0] if arti_row else None

            pages = build_detail_pages(entry, arti_id)
            for p in pages:
                _add_requester_info(p, interaction.user)

            view = KanjiPaginatorView(interaction.user.id, pages)
            message = await interaction.followup.send(embed=pages[0], view=view, ephemeral=True, wait=True)
            view.message = message
            return

        # Mode list/browse: filter jlpt/joyo/kelas_sd / kosong semua.
        query, params = _build_list_query(jlpt, joyo, kelas_sd)
        rows = await self.bot.GET(query, params)

        if not rows:
            await interaction.followup.send(
                "❌ Tidak ada kanji yang cocok dengan filter tersebut.", ephemeral=True
            )
            return

        entries = [
            {
                "kanji": r[0], "meanings_en": r[1], "jlpt_baru": r[2],
                "joyo_status": r[3], "kyouiku_kelas_sd": r[4], "kanken_kyu_resmi": r[5],
            }
            for r in rows
        ]
        show_meaning = has_dic_access(interaction.user, interaction.guild_id)
        pages, page_entries = build_list_pages(entries, jlpt, joyo, kelas_sd, show_meaning=show_meaning)
        for p in pages:
            _add_requester_info(p, interaction.user)

        view = KanjiListView(interaction.user.id, pages, page_entries, show_meaning=show_meaning)
        message = await interaction.followup.send(embed=pages[0], view=view, ephemeral=True, wait=True)
        view.message = message

    @discord.app_commands.command(
        name="kanji_reload",
        description="Muat ulang kamus kanji (kanji_master.csv + kanji_meanings_id.csv) dari CSV (Khusus Admin).",
    )
    @discord.app_commands.default_permissions(administrator=True)
    async def kanji_reload(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.load_csv()
        await self.load_meanings_csv()

        total_row = await self.bot.GET_ONE(f"SELECT COUNT(*) FROM {TABLE_NAME};")
        total_arti_row = await self.bot.GET_ONE(f"SELECT COUNT(*) FROM {MEANINGS_TABLE};")
        total = total_row[0] if total_row else 0
        total_arti = total_arti_row[0] if total_arti_row else 0

        await interaction.followup.send(
            f"✅ Kamus kanji dimuat ulang. Total entri: **{total}** "
            f"(**{total_arti}** sudah punya terjemahan Indonesia).",
            ephemeral=True,
        )


async def setup(bot: KotabiBot):
    await bot.add_cog(Kanji(bot))