#!/usr/bin/env python3
"""
grammar_validator.py — Validator Checklist Kualitas Kamus Grammar (Kotabi Style Guide)
========================================================================================
Scan 4 CSV master (grammar_entries.csv, grammar_translations.csv,
grammar_key_sentences.csv, grammar_examples.csv) dan laporkan pelanggaran
terhadap "4. Checklist Kualitas" di panduan.

Pemakaian:
    python3 grammar_validator.py [folder_csv]

    Kalau `folder_csv` tidak diisi, default ke folder kerja saat ini (".").
    Nama file CSV yang dicari harus persis: grammar_entries.csv,
    grammar_translations.csv, grammar_key_sentences.csv, grammar_examples.csv
    (nama sama seperti yang dipakai grammar_cog.py).

Exit code: 0 kalau tidak ada pelanggaran ERROR, 1 kalau ada minimal satu
ERROR (berguna untuk dipasang di CI/pre-commit kalau mau).

Catatan: script ini HANYA membaca CSV, tidak pernah menulis/mengubahnya.
"""

import csv
import os
import re
import sys
from collections import defaultdict

# ============================================================================
# DAFTAR NILAI BAKU (sesuai Lampiran & badan panduan)
# ============================================================================

USAGE_REGISTER_VALUES = {
    "Kasual", "Percakapan", "Formal", "Bisnis", "Akademis", "Tulisan",
    "Sastra", "Klasik", "Surat Kabar", "Hukum", "Hormat (Sonkeigo)",
    "Merendah (Kenjōgo)", "Dialek", "Tidak ada",
}

NUANCE_VALUES = {
    "Netral", "Halus", "Kuat", "Tegas/Emfatik", "Positif", "Negatif",
    "Subjektif", "Objektif",
}

FORMATION_TOKENS = {
    # Shorthand baru (per keputusan di sesi lanjutan): V + akhiran, menggantikan
    # label verbose lama ("Verb (Dictionary Form)" dst). Konvensi ini sengaja
    # scalable — pola turunan baru (Vておく, Vてしまう, Vてみる, dst) otomatis
    # valid tanpa perlu menambah entri baru ke set ini, SELAMA polanya memang
    # diawali salah satu token dasar berikut (lihat _extract_leading_token()).
    "V",         # Dictionary Form / bentuk kamus
    "Vます",      # ます Stem
    "Vて",        # て-form
    "Vている",     # ekstensi: bentuk kontinuatif/stative (て-form + いる)
    "Vない",      # ない Form
    "Vた",        # た Form
    "Vば",        # ば Form
    "Vよう",      # Volitional
    "V命令形",     # Imperative (akhiran beda tiap golongan verba, jadi label utuh)
    "N",         # Noun
    "Adj-na",    # Na-adjective
    "Adj-i",     # I-adjective
    "Num",       # Number
}

# Karakter yang dianggap "batas" akhir token label (spasi, kurung, tanda +).
_TOKEN_BOUNDARY_RE = re.compile(r"^([^\s\(（\+＋]+)")


def _extract_leading_token(pattern: str) -> str:
    """Ambil token label di depan pattern formation, mis. 'Vた（普通形）+ 上に' -> 'Vた'."""
    match = _TOKEN_BOUNDARY_RE.match(pattern.strip())
    return match.group(1) if match else pattern.strip()

JLPT_ORDER_MAP = {"N5": "1", "N4": "2", "N3": "3", "N2": "4", "N1": "5"}

EMPTY_MARKERS = {"", "—", "-", "–"}

# Regex kasar: ada tanda pisah gloss (— atau -) diikuti setidaknya satu kata
# berhuruf Latin — dipakai untuk memastikan ④ Part of Speech tidak ditulis
# istilah Jepang polos tanpa gloss Indonesia (lihat §3.④ + Tahap 2 roadmap).
GLOSS_PATTERN = re.compile(r"[—-]\s*[A-Za-z]")


def _is_empty(value):
    return (value or "").strip() in EMPTY_MARKERS


def _split_list(value, sep=","):
    if _is_empty(value):
        return []
    return [v.strip() for v in value.split(sep) if v.strip()]


# ============================================================================
# LOADER
# ============================================================================

def load_csv(path):
    if not os.path.exists(path):
        return None, [f"File tidak ditemukan: {path}"]
    with open(path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows, []


# ============================================================================
# PEMERIKSAAN PER ENTRI (grammar_entries.csv)
# ============================================================================

def check_entry(entry, issues):
    """Menambahkan (severity, pesan) ke issues[entry_id] sesuai checklist Bagian 4."""
    eid = entry.get("id", "").strip() or "(id kosong)"
    is_redirect = entry.get("status", "").strip() == "redirect"

    def add(severity, msg):
        issues[eid].append((severity, msg))

    # --- ID ---
    if _is_empty(entry.get("id")):
        add("ERROR", "Kolom `id` kosong.")

    # --- Romaji & Kana ---
    if _is_empty(entry.get("romaji")):
        add("ERROR", "Kolom `romaji` kosong (dibutuhkan untuk sortir alfabet).")
    if _is_empty(entry.get("kana")):
        add("ERROR", "Kolom `kana` kosong (dibutuhkan untuk sortir gojūon & tampilan ②).")

    # --- JLPT & JLPT_Order sinkron ---
    jlpt = (entry.get("jlpt") or "").strip()
    jlpt_order = (entry.get("jlpt_order") or "").strip()
    if jlpt in EMPTY_MARKERS:
        if jlpt_order not in EMPTY_MARKERS:
            add("WARNING", f"`jlpt` kosong tapi `jlpt_order` = '{jlpt_order}' (harusnya ikut kosong).")
    elif jlpt not in JLPT_ORDER_MAP:
        add("ERROR", f"`jlpt` = '{jlpt}' bukan salah satu dari N5/N4/N3/N2/N1.")
    else:
        expected = JLPT_ORDER_MAP[jlpt]
        if jlpt_order != expected:
            add("ERROR", f"`jlpt_order` = '{jlpt_order}', seharusnya '{expected}' untuk level {jlpt}.")

    # --- ④ Part of Speech — wajib ada gloss Indonesia (termasuk entri redirect) ---
    pos = entry.get("part_of_speech", "") or ""
    subtype = entry.get("part_of_speech_subtype", "") or ""
    combined_pos = f"{pos} ({subtype})" if not _is_empty(subtype) else pos
    if _is_empty(pos):
        add("ERROR", "④ `part_of_speech` kosong.")
    elif not GLOSS_PATTERN.search(combined_pos):
        add("ERROR", "④ `part_of_speech`/`part_of_speech_subtype` belum menyertakan gloss "
                      "Indonesia (format '[istilah Jepang] — [gloss Indonesia]'), termasuk untuk entri redirect.")
    if "助詞" in pos and _is_empty(subtype):
        add("WARNING", "④ Part of speech mengandung 助詞 tapi `part_of_speech_subtype` kosong — "
                        "subtipe partikel (格助詞/接続助詞/副助詞/終助詞/並立助詞) wajib disebutkan.")

    # --- ⑤ Usage/Register — nilai baku ---
    register = (entry.get("usage_register") or "").strip()
    if _is_empty(register):
        add("ERROR", "⑤ `usage_register` kosong.")
    elif register not in USAGE_REGISTER_VALUES:
        add("WARNING", f"⑤ `usage_register` = '{register}' bukan nilai baku (lihat Lampiran daftar Ragam).")

    # --- ⑥ Meaning EN/ID ---
    if _is_empty(entry.get("meaning_en")):
        add("ERROR", "⑥ `meaning_en` kosong.")
    if _is_empty(entry.get("meaning_id")):
        add("ERROR", "⑥ `meaning_id` kosong.")

    # --- ⑧ Formation (dilewati untuk entri redirect) ---
    if not is_redirect:
        formation = entry.get("formation", "") or ""
        if _is_empty(formation):
            add("ERROR", "⑧ `formation` kosong (wajib diisi untuk entri non-redirect).")
        else:
            for pattern in _split_list(formation, ";"):
                token = _extract_leading_token(pattern)
                if token not in FORMATION_TOKENS:
                    add("WARNING", f"⑧ Formation pattern '{pattern}' tidak diawali token label standar "
                                    f"(token terbaca: '{token}'; lihat daftar token V/N/Adj-na/Adj-i/Num "
                                    f"di panduan §3.⑧).")

    # --- ⑪ Nuance — nilai baku ---
    nuance = entry.get("nuance", "") or ""
    if _is_empty(nuance):
        if not is_redirect:
            add("WARNING", "⑪ `nuance` kosong.")
    else:
        for token in _split_list(nuance, ","):
            if token not in NUANCE_VALUES:
                add("WARNING", f"⑪ Nuance token '{token}' bukan nilai baku "
                                f"(Netral/Halus/Kuat/Tegas per Emfatik/Positif/Negatif/Subjektif/Objektif).")

    # --- ⑬ terisi -> ⑭ wajib (kecuali redirect) ---
    related = entry.get("related_expression", "") or ""
    related_detail = entry.get("related_expression_detail", "") or ""
    if not is_redirect:
        if not _is_empty(related) and _is_empty(related_detail):
            add("ERROR", "⑬ `related_expression` terisi tapi ⑭ `related_expression_detail` kosong — "
                          "perbandingan WAJIB dijelaskan kalau ada related expression.")
    else:
        if _is_empty(related):
            add("WARNING", "Entri redirect sebaiknya mengisi ⑬ `related_expression` "
                            "dengan nama pola tujuan (dipakai sebagai arahan pembaca).")

    # --- Redirect-specific ---
    if is_redirect:
        tags = _split_list(entry.get("tags", ""), ",")
        if "redirect" not in [t.lower() for t in tags]:
            add("ERROR", "`status` = redirect tapi `tags` tidak mengandung 'redirect'.")
        meaning_id = entry.get("meaning_id", "") or ""
        if _is_empty(meaning_id):
            add("ERROR", "Entri redirect wajib mengisi ⑥ `meaning_id` (pesan arahan ke pola tujuan).")
    else:
        tags = _split_list(entry.get("tags", ""), ",")
        if "redirect" in [t.lower() for t in tags]:
            add("WARNING", "`tags` mengandung 'redirect' tapi `status` bukan 'redirect' — cek konsistensi.")

    # --- Rujukan Silang tidak boleh mengandung nomor halaman ---
    rujukan = entry.get("rujukan_silang", "") or ""
    if re.search(r"\bhal(\.|aman)?\s*\d", rujukan, flags=re.IGNORECASE) or re.search(r"\bp\.\s*\d", rujukan):
        add("WARNING", "`rujukan_silang` sepertinya mengandung nomor halaman — "
                        "seharusnya cuma nama sumber (lihat aturan metadata Rujukan Silang).")


# ============================================================================
# PEMERIKSAAN ANTAR-TABEL (referential integrity + aturan redirect)
# ============================================================================

def check_cross_table(entries, translations, key_sentences, examples, issues):
    entry_ids = {e.get("id", "").strip() for e in entries if not _is_empty(e.get("id"))}
    redirect_ids = {
        e.get("id", "").strip() for e in entries
        if e.get("status", "").strip() == "redirect"
    }

    def add(eid, severity, msg):
        issues[eid or "(entry_id kosong)"].append((severity, msg))

    for table_name, rows in (
        ("grammar_translations.csv", translations),
        ("grammar_key_sentences.csv", key_sentences),
        ("grammar_examples.csv", examples),
    ):
        for row in rows:
            ref_id = (row.get("entry_id") or "").strip()
            if _is_empty(ref_id):
                add(None, "ERROR", f"Baris di {table_name} punya `entry_id` kosong.")
                continue
            if ref_id not in entry_ids:
                add(ref_id, "ERROR", f"`entry_id` = '{ref_id}' di {table_name} tidak ditemukan "
                                       f"di grammar_entries.csv (kemungkinan typo atau entri terhapus).")
            if ref_id in redirect_ids:
                add(ref_id, "ERROR", f"Entri redirect '{ref_id}' punya baris di {table_name} — "
                                       f"entri redirect seharusnya TIDAK punya baris apa pun di "
                                       f"grammar_translations.csv / grammar_key_sentences.csv / grammar_examples.csv.")

    # Entri non-redirect tanpa terjemahan / key sentence sama sekali (bukan error hard, tapi worth flagging)
    translated_ids = {(r.get("entry_id") or "").strip() for r in translations}
    key_sentence_ids = {(r.get("entry_id") or "").strip() for r in key_sentences}
    for e in entries:
        eid = e.get("id", "").strip()
        if not eid or eid in redirect_ids:
            continue
        if eid not in translated_ids:
            add(eid, "WARNING", "Tidak ada baris ⑦ Translations untuk entri ini di grammar_translations.csv.")
        if eid not in key_sentence_ids:
            add(eid, "WARNING", "Tidak ada baris ⑨ Key Sentences untuk entri ini di grammar_key_sentences.csv.")


# ============================================================================
# LAPORAN
# ============================================================================

def print_report(issues):
    total_error = 0
    total_warning = 0
    ordered_ids = sorted(issues.keys())

    if not any(issues[eid] for eid in ordered_ids):
        print("✅ Tidak ada pelanggaran checklist ditemukan. Semua entri lolos validasi.")
        return 0

    for eid in ordered_ids:
        entry_issues = issues[eid]
        if not entry_issues:
            continue
        print(f"\n=== {eid} ===")
        for severity, msg in entry_issues:
            marker = "❌ ERROR  " if severity == "ERROR" else "⚠️  WARNING"
            print(f"  {marker} — {msg}")
            if severity == "ERROR":
                total_error += 1
            else:
                total_warning += 1

    print(f"\n----------------------------------------")
    print(f"Ringkasan: {total_error} ERROR, {total_warning} WARNING, "
          f"di {sum(1 for eid in ordered_ids if issues[eid])} entri bermasalah "
          f"(dari {len(ordered_ids)} entri/entry_id yang dicek).")
    return 1 if total_error else 0


# ============================================================================
# MAIN
# ============================================================================

def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."

    paths = {
        "entries": os.path.join(folder, "grammar_entries.csv"),
        "translations": os.path.join(folder, "grammar_translations.csv"),
        "key_sentences": os.path.join(folder, "grammar_key_sentences.csv"),
        "examples": os.path.join(folder, "grammar_examples.csv"),
    }

    loaded = {}
    fatal = False
    for key, path in paths.items():
        rows, errors = load_csv(path)
        if errors:
            for e in errors:
                print(f"❌ {e}")
            fatal = True
        loaded[key] = rows or []

    if fatal:
        print("\nTidak bisa lanjut validasi karena ada file yang hilang.")
        sys.exit(1)

    issues = defaultdict(list)

    for entry in loaded["entries"]:
        check_entry(entry, issues)

    check_cross_table(
        loaded["entries"], loaded["translations"], loaded["key_sentences"], loaded["examples"], issues
    )

    exit_code = print_report(issues)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()