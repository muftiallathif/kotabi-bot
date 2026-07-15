"""
Skema field untuk entri Kamus Kotoba (単語 -> kosakata) Bahasa Jepang, versi
RINGKAS/FLAT — dwibahasa Jepang + Indonesia saja, mengikuti filosofi yang sama
dengan grammar_fields.py (`/bunpou`): key stabil `NoteID`, slot bernomor untuk
hal yang berulang, kategori diff datar.

Dipetakan dari struktur Anki deck sumber vocab (deck-source/notes.csv, lihat
repo), yang aslinya multi-bahasa (VocabDefSC/VocabDefTC untuk Mandarin
Sederhana/Tradisional). Disederhanakan di sini:
    VocabDefSC + VocabDefTC          -> VocabDefID
    SentDefSC{n} + SentDefTC{n}      -> SentDefID{n}
Field lain (VocabKanji, VocabPitch, VocabPoS, VocabFurigana, VocabPlus,
VocabAudio, SentType/SentKanji/SentFurigana/SentAudio, Sort, Alt1, Alt2, Tags)
dipertahankan apa adanya dari skema sumber.

CATATAN JUMLAH SLOT KALIMAT CONTOH (4):
Beda dengan grammar_fields.py yang perlu 11 slot (sumbernya memang punya 11
slot Sentence/SentenceAudio), deck sumber vocab ini hanya menyediakan 4 slot
kalimat (Sentence1-4 / SentenceAudio1-4) — jadi FIELD_NAMES di bawah cukup
SentType/SentKanji/SentFurigana/SentDefID/SentAudio 1-4, TIDAK dipangkas dari
pengamatan pemakaian, tapi memang cuma segitu yang ada di sumber.

CATATAN AUDIO (belum dirender, TAPI kolomnya TETAP dipertahankan):
`VocabAudio` dan `SentAudio1-4` disimpan di skema ini supaya data sumber tidak
hilang, dan suatu saat bisa dipakai kalau file audio sudah di-hosting di
tempat yang bisa dirujuk Discord (CDN/URL publik). Untuk saat ini,
`features/dictionary/kotoba_cog.py` TIDAK merender kolom ini sama sekali
(lihat DISPLAYED_CATEGORIES di sana — "Audio" sengaja tidak disertakan),
persis seperti alasan yang sama kenapa grammar_fields.py/bunpou_cog.py juga
tidak merender GrammarImage/SentAudio-nya sendiri.

Deck sumber vocab ini TIDAK punya kolom gambar sama sekali (beda dengan
grammar yang punya GrammarImage1-5), jadi tidak ada field gambar di skema
kotoba ini.
"""

FIELD_NAMES = [
    "level",
    "frequency",
    "NoteID",
    "VocabKanji",
    "VocabPitch",
    "VocabPoS",
    "VocabFurigana",
    "VocabDefID",
    "VocabPlus",
    "VocabAudio",
    "SentType1",
    "SentKanji1",
    "SentFurigana1",
    "SentDefID1",
    "SentAudio1",
    "SentType2",
    "SentKanji2",
    "SentFurigana2",
    "SentDefID2",
    "SentAudio2",
    "SentType3",
    "SentKanji3",
    "SentFurigana3",
    "SentDefID3",
    "SentAudio3",
    "SentType4",
    "SentKanji4",
    "SentFurigana4",
    "SentDefID4",
    "SentAudio4",
    "Sort",
    "Alt1",
    "Alt2",
    "Tags",
]
KEY_FIELD = "NoteID"
CATEGORY_FIELDS = {
    "Info Kosakata": ["VocabKanji", "VocabPitch", "VocabPoS", "VocabFurigana"],
    "Makna": ["VocabDefID"],
    "Catatan Tambahan": ["VocabPlus"],
    "Contoh Kalimat": [
        "SentType1", "SentType2", "SentType3", "SentType4",
        "SentKanji1", "SentKanji2", "SentKanji3", "SentKanji4",
        "SentFurigana1", "SentFurigana2", "SentFurigana3", "SentFurigana4",
        "SentDefID1", "SentDefID2", "SentDefID3", "SentDefID4",
    ],
    # Belum dirender oleh kotoba_cog.py (lihat DISPLAYED_CATEGORIES), tapi
    # kolomnya tetap disimpan untuk kebutuhan masa depan.
    "Audio": ["VocabAudio", "SentAudio1", "SentAudio2", "SentAudio3", "SentAudio4"],
    "Pengelompokan/Tag": ["Sort", "Tags", "frequency", "level"],
    "Template Toggle": ["Alt1", "Alt2"],
}
