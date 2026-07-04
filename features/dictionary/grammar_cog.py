"""
features/grammar/grammar_cog.py — Kamus Grammar Jepang (/grammar)
=====================================================================
Membaca entri dari features/grammar/grammar_entries.csv (format 26 kolom
sesuai "Panduan Membuat Entri Kamus Grammar Bahasa Jepang", bagian 7 —
Opsi A), memuatnya ke tabel SQLite grammar_entries, lalu menyediakan
slash command /grammar sesuai rencana implementasi di bagian 10 panduan:

  - Tiga parameter opsional & independen: pola (autocomplete), jlpt
    (pilihan N5-N1), huruf_awal (romaji ATAU hiragana). Kalau `pola`
    diisi, `jlpt` dan `huruf_awal` diabaikan (10.2).
  - Mode "1 entri detail" dipecah 4 halaman dengan tombol Prev/Next
    (10.3).
  - Mode "list/browse" (jlpt / huruf_awal / kosong) menampilkan daftar
    ringkas TERPAGINASI, dengan dropdown per halaman untuk loncat
    langsung ke mode detail satu entri tanpa perlu mengetik ulang.
  - Semua respons ephemeral, plus pagination sebagai proteksi anti-copy
    tambahan (10.4).
  - Setiap embed hasil pencarian menampilkan info pemohon (foto profil,
    nama tampilan, dan username) di author/footer.
  - Gating akses: Trial dapat, Traveler TIDAK dapat, Companion/Patron
    dapat, staff & admin selalu dapat — beda dari has_vip_role() biasa
    (10.5). Lihat shared/checks.py::is_grammar_dic().
    Trial mengikuti masa berlaku trial 5 hari yang sudah ada di sistem
    membership — TIDAK ada limiter jumlah pencarian terpisah untuk
    kamus ini.

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
from typing import Optional

import discord
from discord.ext import commands

from core.bot import KotabiBot
from shared.checks import is_dic_access

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

# Pencarian umum (tanpa filter jlpt) — dipakai autocomplete saat parameter
# jlpt belum/tidak diisi.
SEARCH_QUERY = """
SELECT id, romaji, kana, meaning_id, jlpt FROM grammar_entries
WHERE romaji LIKE '%' || ? || '%'
   OR kana LIKE '%' || ? || '%'
   OR id LIKE '%' || ? || '%'
ORDER BY jlpt_order ASC, romaji ASC
LIMIT 25;
"""

# Pencarian yang sudah difilter jlpt — dipakai autocomplete saat parameter
# jlpt SUDAH diisi duluan oleh user, supaya daftar saran tidak menampilkan
# level lain yang tidak relevan.
SEARCH_QUERY_JLPT = """
SELECT id, romaji, kana, meaning_id, jlpt FROM grammar_entries
WHERE jlpt = ?
AND (romaji LIKE '%' || ? || '%' OR kana LIKE '%' || ? || '%' OR id LIKE '%' || ? || '%')
ORDER BY jlpt_order ASC, romaji ASC
LIMIT 25;
"""

GET_ENTRY = f"SELECT {', '.join(CSV_COLUMNS)} FROM grammar_entries WHERE id = ?;"

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
# Sesuai catatan 10.3: token interaksi ephemeral kedaluwarsa ~15 menit,
# jadi timeout view dipasang sedikit di bawah itu.
PAGINATOR_TIMEOUT_SECONDS = 800


async def grammar_autocomplete(interaction: discord.Interaction, current_input: str):
    """
    Menyediakan daftar pola grammar secara otomatis berdasarkan romaji/kana/id.
    Kalau user sudah memilih parameter `jlpt` duluan, daftar saran ikut
    difilter ke level tersebut saja — supaya tidak menampilkan level lain
    yang tidak relevan dengan pilihan user.
    """
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


def _row_to_dict(row: tuple) -> dict:
    return dict(zip(CSV_COLUMNS, row))


def _has_content(value: Optional[str]) -> bool:
    return bool(value) and value not in ("—", "")


def _add_requester_info(embed: discord.Embed, user: discord.User) -> discord.Embed:
    """Menambahkan foto profil, nama tampilan, dan username pemohon ke embed."""
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.set_footer(text=f"Diminta oleh @{user.name}")
    return embed


# ============================================================================
# MODE DETAIL — 4 halaman (10.3)
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


def build_detail_pages(entry: dict) -> list[discord.Embed]:
    """Menyusun entri database menjadi 4 embed berurutan mengikuti struktur ①–⑪ panduan."""
    pages = []

    # Halaman 1: ①②③ header + ④ Meaning/Function + ⑤ Counterpart
    p1 = _detail_base_embed(entry, "Halaman 1/4")
    jlpt_str = entry.get("jlpt") or "—"
    restriction = entry.get("usage_restriction") or "—"
    p1.description = (
        f"**JLPT:** {jlpt_str}　|　**Part of Speech:** {entry['part_of_speech']}　"
        f"|　**Restriction:** {restriction}"
    )
    p1.add_field(
        name="④ Meaning / Function",
        value=f"🇬🇧 {entry['meaning_en']}\n🇮🇩 {entry['meaning_id']}",
        inline=False,
    )
    p1.add_field(
        name="⑤ Counterpart(s)",
        value=f"🇬🇧 {entry['counterpart_en']}\n🇮🇩 {entry['counterpart_id']}",
        inline=False,
    )
    pages.append(p1)

    # Halaman 2: ⑥ Related Expression + ⑦ Key Sentence + ⑧ Formation
    p2 = _detail_base_embed(entry, "Halaman 2/4")
    if _has_content(entry.get("related_expression")):
        p2.add_field(name="⑥ Related Expression(s)", value=entry["related_expression"], inline=False)

    key_sentence = (
        f"**Pola:** {entry['key_sentence_pola']}\n"
        f"**Contoh:** {entry['key_sentence_contoh']}\n"
        f"**ID:** {entry['key_sentence_id']}"
    )
    p2.add_field(name="⑦ Key Sentence", value=key_sentence[:1024], inline=False)

    if _has_content(entry.get("formation")):
        p2.add_field(name="⑧ Formation", value=entry["formation"].replace(";", "\n"), inline=False)
    pages.append(p2)

    # Halaman 3: ⑨ Examples (semua contoh kalimat)
    p3 = _detail_base_embed(entry, "Halaman 3/4")
    jp_list = entry["examples_jp"].split(" | ")
    en_list = entry["examples_en"].split(" | ")
    id_list = entry["examples_id"].split(" | ")

    blocks = []
    for i, (jp, en, idn) in enumerate(zip(jp_list, en_list, id_list), start=1):
        blocks.append(f"**{i}.** {jp}\n　🇬🇧 {en}\n　🇮🇩 {idn}")

    # Field Discord dibatasi 1024 karakter — pecah jadi beberapa field kalau perlu
    # supaya contoh yang banyak tidak terpotong diam-diam.
    current = ""
    field_count = 0
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > 1024:
            field_count += 1
            name = "⑨ Examples" if field_count == 1 else "⑨ Examples (lanjutan)"
            p3.add_field(name=name, value=current, inline=False)
            current = block
        else:
            current = candidate
    if current:
        field_count += 1
        name = "⑨ Examples" if field_count == 1 else "⑨ Examples (lanjutan)"
        p3.add_field(name=name, value=current, inline=False)
    pages.append(p3)

    # Halaman 4: ⑩ Note(s) + ⑪ Related Expression Detail
    p4 = _detail_base_embed(entry, "Halaman 4/4")
    if _has_content(entry.get("notes_en")):
        notes = f"🇬🇧 {entry['notes_en']}\n🇮🇩 {entry['notes_id']}"
        p4.add_field(name="⑩ Note(s)", value=notes[:1024], inline=False)
    if _has_content(entry.get("related_expression_detail")):
        p4.add_field(
            name="⑪ Related Expression(s) — Detail",
            value=entry["related_expression_detail"][:1024],
            inline=False,
        )
    if _has_content(entry.get("tags")):
        p4.add_field(name="Tags", value=entry["tags"], inline=False)
    pages.append(p4)

    return pages


# ============================================================================
# MODE LIST/BROWSE — jlpt / huruf_awal / kosong (10.2)
# ============================================================================

def _build_list_query(jlpt: Optional[str], huruf_awal: Optional[str]) -> tuple[str, tuple]:
    """
    Susun query + urutan sesuai tabel kombinasi di panduan 10.2:
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
    """
    Return (pages, page_entries):
      - pages        -> list embed siap kirim, satu per halaman
      - page_entries -> list of list dict entri per halaman, dipakai untuk
                        mengisi opsi dropdown "loncat ke detail" di setiap
                        halaman (lihat GrammarListView).
    """
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
            # Baris kosong di antara entri supaya list tidak dempet dan lebih
            # enak dibaca (dibanding "\n".join sebelumnya).
            description="\n\n".join(lines) or "Tidak ada entri.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Halaman {idx}/{total_pages} • Total {len(entries)} entri")
        pages.append(embed)

    return pages, chunks


# ============================================================================
# PAGINATION VIEW — mode detail (10.3, 10.4)
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
    """
    Paginator Prev/Next untuk mode list/browse, DITAMBAH dropdown per halaman
    supaya user bisa langsung loncat ke mode detail satu entri tanpa perlu
    mengetik ulang lewat parameter `pola`.
    """

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
        """Buang dropdown lama (kalau ada) lalu pasang ulang sesuai isi halaman aktif."""
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
        detail_pages = build_detail_pages(entry)
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
        """Slash command kamus grammar — mode detail (pola) atau mode list/browse (jlpt/huruf_awal/kosong)."""
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
            pages = build_detail_pages(entry)
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
        """Slash command admin untuk memuat ulang CSV tanpa perlu restart bot."""
        await interaction.response.defer(ephemeral=True)
        await self.load_csv()
        count_row = await self.bot.GET_ONE("SELECT COUNT(*) FROM grammar_entries;")
        total = count_row[0] if count_row else 0
        await interaction.followup.send(f"✅ Kamus grammar dimuat ulang. Total entri: **{total}**.", ephemeral=True)


async def setup(bot: KotabiBot):
    await bot.add_cog(Grammar(bot))