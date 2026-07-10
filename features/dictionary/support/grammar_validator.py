"""
features/dictionary/support/grammar_validator.py — Validator Kamus Grammar (Ringkas)
=====================================================================================
Menggantikan grammar_validator.py versi lama (aturan 15-bagian ①-⑮). Validator
ini mengikuti "Checklist Kualitas" (bagian 4) di
panduan-kamus-grammar-versi-ringkas.md, dicek terhadap skema flat
grammar_fields.py (FIELD_NAMES/KEY_FIELD/CATEGORY_FIELDS) — BUKAN aturan
grammar 15-bagian yang lama.

Bukan Cog (tidak ada `_cog.py` di nama file) — logic pendukung murni, jadi
ditaruh di features/dictionary/support/ sesuai konvensi penamaan project
(lihat DEVELOPMENT_GUIDE.md §2).

CARA PAKAI (CLI, sebelum commit CSV baru):
    python3 features/dictionary/support/grammar_validator.py \
        features/dictionary/grammar-notes-master.csv

Keluar dengan exit code 1 kalau ada ERROR (bukan cuma WARNING), supaya bisa
dipasang di pre-push check (lihat DEVELOPMENT_GUIDE.md §7).

CARA PAKAI (import, mis. dari bunpou_cog.py sebelum load_csv() production):
    from features.dictionary.support.grammar_validator import validate_rows
    errors, warnings = validate_rows(rows)  # rows: list[dict] kolom FIELD_NAMES
"""

import csv
import re
import sys
from typing import NamedTuple

try:
    from features.dictionary.grammar_fields import FIELD_NAMES, KEY_FIELD
except ImportError:
    # Fallback kalau dijalankan langsung (mis. `python3 grammar_validator.py`)
    # tanpa PYTHONPATH di-set ke root repo — tambahkan root repo secara manual
    # (features/dictionary/support/ -> naik 3 level ke root).
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
    from features.dictionary.grammar_fields import FIELD_NAMES, KEY_FIELD


class Issue(NamedTuple):
    level: str  # "ERROR" | "WARNING"
    note_id: str
    pattern: str
    message: str

    def __str__(self):
        label = self.pattern or "(?)"
        return f"[{self.level}] {label} ({self.note_id or '?'}): {self.message}"


_HIRAGANA_RE = re.compile(r"^[\u3040-\u309F\u30FCー～]*$")  # hiragana + chōonpu + tilde
_STAR_RE = re.compile(r"^★[1-5]$")

NOTE_SLOTS = range(1, 8)      # GrammarNoteJP/ID1-7
SENTENCE_SLOTS = range(1, 12)  # SentKanji/Furigana/DefID1-11
FORMATION_SLOTS = range(1, 4)  # GrammarFormation1-3


def _empty(value: str) -> bool:
    return not value or value.strip() in ("", "—")


def validate_header(header: list[str]) -> list[Issue]:
    """Cek drift kecil nama/urutan kolom sebelum apa pun lagi divalidasi —
    ini yang paling penting untuk dicek duluan, karena loader memetakan
    kolom berdasarkan POSISI (lihat catatan di permintaan awal)."""
    if header == FIELD_NAMES:
        return []
    issues = [Issue("ERROR", "", "", "Header CSV TIDAK cocok persis dengan FIELD_NAMES di grammar_fields.py.")]
    max_len = max(len(header), len(FIELD_NAMES))
    for i in range(max_len):
        h = header[i] if i < len(header) else "<HILANG>"
        f = FIELD_NAMES[i] if i < len(FIELD_NAMES) else "<HILANG>"
        if h != f:
            issues.append(Issue("ERROR", "", "", f"  kolom idx {i}: CSV='{h}' vs FIELD_NAMES='{f}'"))
    return issues


def _validate_note_id(row: dict, seen_ids: set) -> list[Issue]:
    issues = []
    note_id = row.get(KEY_FIELD, "")
    pattern = row.get("GrammarPattern", "")
    if _empty(note_id):
        issues.append(Issue("ERROR", note_id, pattern, "NoteID kosong atau '—' — wajib diisi UUID unik."))
    elif note_id in seen_ids:
        issues.append(Issue("ERROR", note_id, pattern, "NoteID duplikat — harus unik per entri."))
    return issues


def _validate_furigana(row: dict) -> list[Issue]:
    issues = []
    pattern = row.get("GrammarPattern", "")
    furigana = row.get("GrammarFurigana", "")
    note_id = row.get(KEY_FIELD, "")

    if _empty(furigana):
        issues.append(Issue("ERROR", note_id, pattern, "GrammarFurigana kosong."))
        return issues

    if pattern and _HIRAGANA_RE.match(pattern) and pattern != furigana:
        issues.append(Issue(
            "WARNING", note_id, pattern,
            f"GrammarPattern sudah murni kana tapi GrammarFurigana ('{furigana}') berbeda — cek kembali.",
        ))
    return issues


def _validate_star_frequency(row: dict) -> list[Issue]:
    issues = []
    note_id = row.get(KEY_FIELD, "")
    pattern = row.get("GrammarPattern", "")
    star = row.get("GrammarStar", "")
    frequency = row.get("frequency", "")

    if not _empty(star) and not _STAR_RE.match(star):
        issues.append(Issue("ERROR", note_id, pattern, f"GrammarStar '{star}' bukan format ★1-★5 yang valid."))
    if "★" in frequency:
        issues.append(Issue(
            "ERROR", note_id, pattern,
            "frequency mengandung notasi ★ — sepertinya tertukar dengan GrammarStar (§3.3, dua konsep berbeda).",
        ))
    return issues


def _validate_minimum_content(row: dict) -> list[Issue]:
    issues = []
    note_id = row.get(KEY_FIELD, "")
    pattern = row.get("GrammarPattern", "")

    has_formation = any(not _empty(row.get(f"GrammarFormation{n}", "")) for n in FORMATION_SLOTS)
    if not has_formation:
        issues.append(Issue("ERROR", note_id, pattern, "Tidak ada GrammarFormation1-3 yang terisi (minimal 1 wajib)."))

    has_sentence = not _empty(row.get("SentKanji1", ""))
    if not has_sentence:
        issues.append(Issue("ERROR", note_id, pattern, "SentKanji1 kosong — minimal 1 contoh kalimat wajib terisi."))
    return issues


def _validate_note_slot_pairing(row: dict) -> list[Issue]:
    """GrammarNoteJP{n} & GrammarNoteID{n} harus selaras: sama-sama kosong
    atau sama-sama terisi untuk tiap slot n. Juga cek tidak ada 'lubang'
    (slot n kosong tapi slot n+1 terisi) supaya urutan tetap rapi."""
    issues = []
    note_id = row.get(KEY_FIELD, "")
    pattern = row.get("GrammarPattern", "")

    seen_gap = False
    for n in NOTE_SLOTS:
        jp = row.get(f"GrammarNoteJP{n}", "")
        idn = row.get(f"GrammarNoteID{n}", "")
        jp_filled, id_filled = not _empty(jp), not _empty(idn)

        if jp_filled != id_filled:
            issues.append(Issue(
                "ERROR", note_id, pattern,
                f"GrammarNoteJP{n}/GrammarNoteID{n} tidak selaras — satu terisi, satu kosong.",
            ))

        if not (jp_filled or id_filled):
            seen_gap = True
        elif seen_gap:
            issues.append(Issue(
                "WARNING", note_id, pattern,
                f"GrammarNoteJP/ID{n} terisi setelah slot sebelumnya kosong — ada 'lubang' di urutan slot catatan.",
            ))
    return issues


def _validate_sentence_slots(row: dict) -> list[Issue]:
    """Tidak boleh ada slot kalimat 'setengah terisi' — SentKanji, SentFurigana,
    SentDefID untuk slot n yang sama harus sama-sama kosong atau sama-sama
    terisi (SentType & SentAudio memang opsional, tidak dicek di sini)."""
    issues = []
    note_id = row.get(KEY_FIELD, "")
    pattern = row.get("GrammarPattern", "")

    seen_gap = False
    for n in SENTENCE_SLOTS:
        kanji = row.get(f"SentKanji{n}", "")
        furigana = row.get(f"SentFurigana{n}", "")
        def_id = row.get(f"SentDefID{n}", "")
        filled = [not _empty(kanji), not _empty(furigana), not _empty(def_id)]

        if any(filled) and not all(filled):
            issues.append(Issue(
                "ERROR", note_id, pattern,
                f"Slot kalimat {n} setengah terisi (SentKanji{n}/SentFurigana{n}/SentDefID{n} tidak konsisten).",
            ))

        if not any(filled):
            seen_gap = True
        elif seen_gap:
            issues.append(Issue(
                "WARNING", note_id, pattern,
                f"Slot kalimat {n} terisi setelah slot sebelumnya kosong — ada 'lubang' di urutan kalimat contoh.",
            ))
    return issues


def _validate_multi_meaning_alignment(row: dict) -> list[Issue]:
    """Soft check (WARNING saja, bukan ERROR — tidak ada aturan tegas 1:1
    di panduan): kalau GrammarMeaningID punya >1 makna (dipisah ';'), cek
    apakah jumlah slot catatan/kalimat yang terisi masuk akal (>= jumlah
    makna), sebagai sinyal awal kalau-kalau ada makna yang belum
    dijelaskan/dicontohkan sama sekali."""
    issues = []
    note_id = row.get(KEY_FIELD, "")
    pattern = row.get("GrammarPattern", "")
    meaning_id = row.get("GrammarMeaningID", "")
    if _empty(meaning_id):
        return issues

    meanings = [m.strip() for m in meaning_id.split(";") if m.strip()]
    if len(meanings) <= 1:
        return issues

    filled_notes = sum(1 for n in NOTE_SLOTS if not _empty(row.get(f"GrammarNoteJP{n}", "")))
    filled_sentences = sum(1 for n in SENTENCE_SLOTS if not _empty(row.get(f"SentKanji{n}", "")))

    if filled_notes < len(meanings) and filled_sentences < len(meanings):
        issues.append(Issue(
            "WARNING", note_id, pattern,
            f"GrammarMeaningID punya {len(meanings)} makna, tapi hanya {filled_notes} catatan & "
            f"{filled_sentences} kalimat contoh terisi — cek lagi apakah tiap makna sudah dijelaskan/dicontohkan.",
        ))
    return issues


def _validate_bracket_homonyms(rows: list[dict]) -> list[Issue]:
    """Kalau GrammarPattern sama muncul >1 kali (pola berbagi bentuk),
    setiap barisnya WAJIB punya GrammarBracket terisi untuk pembeda
    (§3.5)."""
    issues = []
    by_pattern: dict[str, list[dict]] = {}
    for row in rows:
        pattern = row.get("GrammarPattern", "")
        if pattern:
            by_pattern.setdefault(pattern, []).append(row)

    for pattern, group in by_pattern.items():
        if len(group) <= 1:
            continue
        for row in group:
            bracket = row.get("GrammarBracket", "")
            note_id = row.get(KEY_FIELD, "")
            if _empty(bracket):
                issues.append(Issue(
                    "ERROR", note_id, pattern,
                    f"GrammarPattern '{pattern}' muncul {len(group)}x (homonim) tapi GrammarBracket kosong — "
                    "wajib diisi label pembeda (§3.5).",
                ))
    return issues


def validate_rows(rows: list[dict]) -> tuple[list[Issue], list[Issue]]:
    """Jalankan seluruh checklist bagian 4 atas satu set baris (list of
    dict, kolom = FIELD_NAMES). Mengembalikan (errors, warnings)."""
    all_issues: list[Issue] = []
    seen_ids: set[str] = set()

    for row in rows:
        all_issues += _validate_note_id(row, seen_ids)
        seen_ids.add(row.get(KEY_FIELD, ""))
        all_issues += _validate_furigana(row)
        all_issues += _validate_star_frequency(row)
        all_issues += _validate_minimum_content(row)
        all_issues += _validate_note_slot_pairing(row)
        all_issues += _validate_sentence_slots(row)
        all_issues += _validate_multi_meaning_alignment(row)

    all_issues += _validate_bracket_homonyms(rows)

    errors = [i for i in all_issues if i.level == "ERROR"]
    warnings = [i for i in all_issues if i.level == "WARNING"]
    return errors, warnings


def validate_csv_file(path: str) -> tuple[list[Issue], list[Issue]]:
    """Baca file CSV (tab-delimited, melewati baris `#separator:Tab`/`sep=`
    Anki kalau ada) dan jalankan validate_rows(). Header yang tidak cocok
    FIELD_NAMES langsung dikembalikan sebagai ERROR tunggal tanpa lanjut
    memvalidasi baris (supaya tidak salah petakan kolom diam-diam)."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        first_line = f.readline()
        if not first_line.lower().startswith(("#separator", "sep=")):
            f.seek(0)
        reader = csv.DictReader(f, delimiter="\t")
        header = reader.fieldnames or []

        header_issues = validate_header(header)
        if any(i.level == "ERROR" for i in header_issues):
            return header_issues, []

        rows = list(reader)

    errors, warnings = validate_rows(rows)
    return header_issues + errors, warnings


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Pemakaian: python3 grammar_validator.py <path-ke-grammar-notes-master.csv>")
        return 2

    errors, warnings = validate_csv_file(argv[1])

    for issue in warnings:
        print(issue)
    for issue in errors:
        print(issue)

    print(f"\n{len(errors)} error, {len(warnings)} warning.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
