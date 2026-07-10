"""
Skema field untuk entri Kamus Grammar (単語 -> 文法) Bahasa Jepang, versi RINGKAS/FLAT
(gaya kotoba, bukan gaya Kotabi 15-bagian ①-⑮).

Dipetakan dari struktur Anki deck sumber (multi-bahasa: JP/EN/CN/KR/CHT/CN),
disederhanakan jadi dwibahasa saja (Jepang + Indonesia) sesuai permintaan.
Meniru pola FIELD_NAMES / KEY_FIELD / CATEGORY_FIELDS di kotoba_fields.py.

CATATAN VALIDASI (dicek langsung dari 632 baris data mentah asli, bukan cuma 1 contoh):
- GrammarBracket: label pembeda makna/fungsi untuk pola yang berbagi bentuk & bacaan
  yang sama (format '〈...〉'), terisi di 185/632 baris, mis. 'させる' muncul 5x dengan
  Bracket beda-beda.
- GrammarStar: skalanya ★1-★5, terkonfirmasi bersih di semua 632 baris -- TIDAK ada
  anomali nilai gabungan seperti '★4★3'. (Catatan lama yang menyebut entry_link-424
  'ところだ' punya nilai ganda itu KELIRU -- baris itu isinya cuma '★4' biasa, sudah
  dicek ulang langsung ke data mentah.)
- GrammarRegister: menggabungkan 3 field terpisah di sumber asli (FormalForm/
  WrittenForm/SpokenForm, masing-masing cuma pernah berisi flag literal 'F'/'W'/'S',
  tidak pernah berisi nilai lain) jadi satu field flat: Formal, Tertulis, Lisan, atau
  Tidak ada.
- GrammarFormationGakko DIHAPUS dari skema ini -- dicek di semua 632 baris data asli,
  field ini (GakkoConnective1-10) SELALU kosong (0/632 terisi), jadi tidak perlu
  dipertahankan.
- 'Connective' (field statis berisi literal '接続' di sumber) DIHAPUS dari skema --
  cuma label tampilan, bukan data.
- level: field 'deck' di sumber Anki punya pola '...::文法カード::N4' -- level bisa
  diambil otomatis dari situ.
- Slot berulang JUMLAHNYA DISAMAKAN DENGAN JUMLAH SLOT ASLI DI SUMBER (bukan dipangkas
  berdasarkan pemakaian tipikal), supaya entri masa depan yang butuh slot lebih banyak
  tidak kehabisan tempat:
    * GrammarNoteJP/ID{1..7} -- sumber asli JNote1-7 (dan ENote/CNote/KNote1-7
      yang paralel, tapi cuma JP yang dipertahankan + terjemahan ID baru). Pemakaian nyata
      di data cuma sampai 6 (mis. entry 'ばいい'/entry_link-473), tapi tetap dibulatkan ke
      7 slot mengikuti jumlah slot asli di sumber, bukan jumlah pemakaian maksimum yang
      teramati.
    * SentType/SentKanji/SentFurigana/SentDefID/SentAudio{1..11} -- sumber asli
      Sentence1-11 & SentenceAudio1-11. Pemakaian nyata mayoritas 2-6 kalimat, tapi
      entri 'ところだ' (entry_link-424) pakai sampai 11 kalimat -- jadi tetap 11 slot.
    * GrammarImage{1..5} -- sumber asli Image1-5. Kebanyakan entri (609/632) tidak
      pakai gambar sama sekali, tapi 'あげる'/'くれる'/'もらう' masing-masing pakai semua 5 slot.
- SentKanji tidak ada field terpisah di sumber -- diturunkan dari 'Sentence' (yang sudah
  berisi notasi furigana '漢字[かな]') dengan membuang notasi bracket-nya, dipetakan ke
  SentFurigana apa adanya dan SentKanji versi bersihnya (pola sama seperti GrammarPattern
  vs GrammarFurigana dari 'Card').
"""

FIELD_NAMES = [
    "level",
    "frequency",
    "NoteID",
    "GrammarPattern",
    "GrammarBracket",
    "GrammarFurigana",
    "GrammarStar",
    "GrammarFormation1",
    "GrammarFormation2",
    "GrammarFormation3",
    "GrammarRegister",
    "GrammarMeaningJP",
    "GrammarMeaningID",
    "GrammarNoteJP1",
    "GrammarNoteJP2",
    "GrammarNoteJP3",
    "GrammarNoteJP4",
    "GrammarNoteJP5",
    "GrammarNoteJP6",
    "GrammarNoteJP7",
    "GrammarNoteID1",
    "GrammarNoteID2",
    "GrammarNoteID3",
    "GrammarNoteID4",
    "GrammarNoteID5",
    "GrammarNoteID6",
    "GrammarNoteID7",
    "GrammarImage1",
    "GrammarImage2",
    "GrammarImage3",
    "GrammarImage4",
    "GrammarImage5",
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
    "SentType5",
    "SentKanji5",
    "SentFurigana5",
    "SentDefID5",
    "SentAudio5",
    "SentType6",
    "SentKanji6",
    "SentFurigana6",
    "SentDefID6",
    "SentAudio6",
    "SentType7",
    "SentKanji7",
    "SentFurigana7",
    "SentDefID7",
    "SentAudio7",
    "SentType8",
    "SentKanji8",
    "SentFurigana8",
    "SentDefID8",
    "SentAudio8",
    "SentType9",
    "SentKanji9",
    "SentFurigana9",
    "SentDefID9",
    "SentAudio9",
    "SentType10",
    "SentKanji10",
    "SentFurigana10",
    "SentDefID10",
    "SentAudio10",
    "SentType11",
    "SentKanji11",
    "SentFurigana11",
    "SentDefID11",
    "SentAudio11",
    "Sort",
    "Alt1",
    "Alt2",
    "Tags",
]
KEY_FIELD = "NoteID"
CATEGORY_FIELDS = {
    "Info Pola": ['GrammarPattern', 'GrammarBracket', 'GrammarFurigana', 'GrammarStar'],
    "Cara Penyambungan": ['GrammarFormation1', 'GrammarFormation2', 'GrammarFormation3', 'GrammarRegister'],
    "Makna": ['GrammarMeaningJP', 'GrammarMeaningID'],
    "Catatan Penjelasan": ['GrammarNoteJP1', 'GrammarNoteJP2', 'GrammarNoteJP3', 'GrammarNoteJP4', 'GrammarNoteJP5', 'GrammarNoteJP6', 'GrammarNoteJP7', 'GrammarNoteID1', 'GrammarNoteID2', 'GrammarNoteID3', 'GrammarNoteID4', 'GrammarNoteID5', 'GrammarNoteID6', 'GrammarNoteID7'],
    "Contoh Kalimat": ['SentType1', 'SentType2', 'SentType3', 'SentType4', 'SentType5', 'SentType6', 'SentType7', 'SentType8', 'SentType9', 'SentType10', 'SentType11', 'SentKanji1', 'SentKanji2', 'SentKanji3', 'SentKanji4', 'SentKanji5', 'SentKanji6', 'SentKanji7', 'SentKanji8', 'SentKanji9', 'SentKanji10', 'SentKanji11', 'SentFurigana1', 'SentFurigana2', 'SentFurigana3', 'SentFurigana4', 'SentFurigana5', 'SentFurigana6', 'SentFurigana7', 'SentFurigana8', 'SentFurigana9', 'SentFurigana10', 'SentFurigana11', 'SentDefID1', 'SentDefID2', 'SentDefID3', 'SentDefID4', 'SentDefID5', 'SentDefID6', 'SentDefID7', 'SentDefID8', 'SentDefID9', 'SentDefID10', 'SentDefID11'],
    "Audio & Gambar": ['SentAudio1', 'SentAudio2', 'SentAudio3', 'SentAudio4', 'SentAudio5', 'SentAudio6', 'SentAudio7', 'SentAudio8', 'SentAudio9', 'SentAudio10', 'SentAudio11', 'GrammarImage1', 'GrammarImage2', 'GrammarImage3', 'GrammarImage4', 'GrammarImage5'],
    "Pengelompokan/Tag": ['Sort', 'Tags', 'frequency', 'level'],
    "Template Toggle": ['Alt1', 'Alt2'],
}
