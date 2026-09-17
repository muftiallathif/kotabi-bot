"""Ekstraktor kamus format MDict (.mdx) — dipakai untuk sumber yang tidak
tersedia dalam format Yomitan.

Masalahnya sama seperti Yomitan: isi kamus ini HTML, dan kalau tag-nya dibuang
mentah-mentah, furigana (`<ruby>`) akan meleleh ke badan kalimat persis seperti
bug yang dulu merusak ~20 berkas. Jadi ruby ditangani lebih dulu, baru tag lain
dibuang.

Butuh: pip install mdict-utils
"""
import re, html, collections

RUBY = re.compile(r'<ruby\b[^>]*>(.*?)</ruby>', re.S)
RT = re.compile(r'<rt\b[^>]*>(.*?)</rt>', re.S)
RP = re.compile(r'<rp\b[^>]*>.*?</rp>', re.S)
TAG = re.compile(r'<[^>]+>')
BLOCK = re.compile(r'</(p|div|dd|dt|li|tr|h\d|dl)\s*>|<br\s*/?>', re.I)


def _ruby(m):
    """<ruby>漢<rt>かん</rt>字<rt>じ</rt></ruby> -> 漢(かん)字(じ)"""
    isi = RP.sub('', m.group(1))
    keluar = []
    pos = 0
    for r in RT.finditer(isi):
        dasar = TAG.sub('', isi[pos:r.start()])
        bacaan = TAG.sub('', r.group(1))
        keluar.append(f'{dasar}({bacaan})' if bacaan.strip() else dasar)
        pos = r.end()
    keluar.append(TAG.sub('', isi[pos:]))
    return ''.join(keluar)


def teks(frag):
    """Fragmen HTML -> teks bersih. Ruby jadi 漢字(かんじ), blok jadi baris baru."""
    if not frag:
        return ''
    s = RUBY.sub(_ruby, frag)
    s = BLOCK.sub('\n', s)
    s = TAG.sub('', s)
    s = html.unescape(s)
    s = re.sub(r'[ \t\u3000]+', ' ', s)
    s = re.sub(r' *\n *', '\n', s)
    s = re.sub(r'\n{2,}', '\n', s)
    return s.strip()


def blok(sumber, kelas, tag='div'):
    """Ambil isi <tag class="kelas"> ... </tag> dengan menghitung kedalaman.

    `tag` boleh alternasi, mis. 'div|p' — kamus ini memakai <div class="j-honbun">
    di satu tempat dan <p class="j-honbun"> di tempat lain.
    """
    hasil = []
    for m in re.finditer(rf'<({tag})[^>]*class="{kelas}"[^>]*>', sumber):
        nama = m.group(1)
        i = m.end()
        depth = 1
        for t in re.finditer(rf'</?{nama}\b', sumber[i:], re.I):
            depth += 1 if not t.group().startswith('</') else -1
            if depth == 0:
                hasil.append(sumber[i:i + t.start()])
                break
    return hasil


def entri_donna_toki(s):
    """Satu entri どんなときどう使う日本語表現文型辞典 -> dict terstruktur."""
    h = re.search(r'<h1 class="headerL">(.*?)</h1>', s, re.S)
    if not h:
        return None
    kepala = teks(h.group(1))
    mb = re.search(r'★(\d)', kepala)
    kata = re.sub(r'★\d', '', kepala).strip()
    if not kata:
        return None

    arti = [teks(x) for x in re.findall(r'<p class="meaning">(.*?)</p>', s, re.S)]
    arti = [a for a in arti if a]

    contoh = []
    for eb in blok(s, 'exampleBlock'):
        for dd in re.findall(r'<dd[^>]*>(.*?)</dd>', eb, re.S):
            t = teks(dd)
            if t:
                contoh.append(t)

    sambung = '\n'.join(teks(x) for x in blok(s, 'connectionBlock')).strip()

    pen = {}
    for eb in blok(s, 'explanationBlock'):
        for kode, label in [('j', 'ja'), ('e', 'en')]:
            bag = blok(eb, rf'{kode}-honbun(?:-1para)?', tag='div|p')
            t = '\n'.join(teks(x) for x in bag).strip()
            if t:
                pen[label] = (pen.get(label, '') + '\n' + t).strip()

    # <p class="meaning"> muncul beberapa kali: parafrase Jepang, lalu EN, ZH, KO.
    # Dipisah berdasarkan aksaranya, bukan urutan — urutannya tidak selalu sama.
    JP = re.compile(r'[\u3040-\u30ff]')
    HANGUL = re.compile(r'[\uac00-\ud7af]')
    LATIN = re.compile(r'[A-Za-z]')
    parafrase, en = [], []
    for a in arti:
        if HANGUL.search(a):
            continue                      # Korea — tidak dipakai
        if JP.search(a):
            parafrase.append(a)           # parafrase Jepang
        elif LATIN.search(a):
            en.append(a)                  # glos Inggris
        # sisanya Mandarin — tidak dipakai

    return {'kata': kata,
            'bintang': int(mb.group(1)) if mb else None,
            'parafrase_ja': '\n'.join(parafrase) or None,
            'arti_en': '\n'.join(en) or None,
            'contoh': contoh,
            'sambungan': sambung or None,
            'penjelasan_ja': pen.get('ja'),
            'penjelasan_en': pen.get('en')}


def sebagai_teks(e):
    """Bentuk string, supaya sesuai skema `penjelasan` yang sudah ada."""
    b = [e['kata'] + (f'  ★{e["bintang"]}' if e['bintang'] else '')]
    if e.get('parafrase_ja'):
        b.append(e['parafrase_ja'])
    if e['arti_en']:
        b.append(e['arti_en'])
    if e['sambungan']:
        b.append('【接続】' + e['sambungan'])
    if e['penjelasan_ja']:
        b.append(e['penjelasan_ja'])
    if e['penjelasan_en']:
        b.append('[EN] ' + e['penjelasan_en'])
    for i, c in enumerate(e['contoh'], 1):
        b.append(f'{i}. {c}')
    return '\n'.join(b)
