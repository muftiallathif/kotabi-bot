#!/usr/bin/env python3
"""build_kamus.py — database_nihongo.zip  ->  data/kamus.sqlite3

Dijalankan saat deploy, BUKAN di-commit hasilnya. Lihat database/README.md.

Prinsip:
  - kamus itu read-only setelah dibangun, jadi dipisah dari state.sqlite3
  - build ke berkas SEMENTARA lalu di-rename; kalau gagal di tengah, kamus lama
    tetap utuh (pelajaran yang sama dengan TRANSAKSI() di core/bot.py)
  - versi & checksum dicatat di dalam DB supaya bot bisa melaporkannya

    python3 scripts/build_kamus.py database_nihongo.zip data/kamus.sqlite3
"""
import hashlib, json, os, sqlite3, sys, zipfile


def sha256(p, blok=1 << 20):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(blok), b''):
            h.update(b)
    return h.hexdigest()


def main(zip_path, out):
    tmp = out + '.building'
    for f in (tmp, tmp + '-wal', tmp + '-shm'):
        if os.path.exists(f):
            os.remove(f)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    z = zipfile.ZipFile(zip_path)
    akar = 'database_nihongo/'
    db = sqlite3.connect(tmp)
    db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE meta (kunci TEXT PRIMARY KEY, nilai TEXT);
        CREATE TABLE kanji (kanji TEXT PRIMARY KEY, inti TEXT, klasifikasi TEXT);
        CREATE TABLE kotoba (kata TEXT, sumber TEXT, isi TEXT);
        CREATE TABLE bunpou (pola TEXT, sumber TEXT, isi TEXT);
        CREATE INDEX idx_kotoba_kata ON kotoba(kata);
        CREATE INDEX idx_bunpou_pola ON bunpou(pola);
    """)

    def muat(rel):
        try:
            return json.loads(z.read(akar + rel))
        except KeyError:
            return None

    inti = muat('01_kanji/kanji_inti_terstruktur.json') or {}
    kls = muat('01_kanji/kanji_klasifikasi.json') or {}
    baris = [(k, json.dumps(inti.get(k), ensure_ascii=False) if inti.get(k) else None,
              json.dumps(kls.get(k), ensure_ascii=False) if kls.get(k) else None)
             for k in set(inti) | set(kls)]
    db.executemany('INSERT INTO kanji VALUES (?,?,?);', baris)
    print(f'  kanji   : {len(baris):,}')

    kos = muat('03_kotoba/kotoba_kosakata_user.json') or []
    db.executemany('INSERT INTO kotoba VALUES (?,?,?);',
                   [(e['kata'], 'kosakata_user', json.dumps(e, ensure_ascii=False))
                    for e in kos if isinstance(e, dict) and e.get('kata')])
    print(f'  kotoba  : {len(kos):,}')

    bm = muat('04_bunpou/bunpou_master.json') or []
    db.executemany('INSERT INTO bunpou VALUES (?,?,?);',
                   [(e['pola'], 'master', json.dumps(e, ensure_ascii=False))
                    for e in bm if isinstance(e, dict) and e.get('pola')])
    print(f'  bunpou  : {len(bm):,}')

    db.executemany('INSERT INTO meta VALUES (?,?);', [
        ('sumber_zip', os.path.basename(zip_path)),
        ('sha256_zip', sha256(zip_path)),
        ('dibangun_dari', akar.rstrip('/')),
        ('n_kanji', str(len(baris))),
        ('n_kotoba', str(len(kos))),
        ('n_bunpou', str(len(bm))),
    ])
    db.commit()
    db.close()

    os.replace(tmp, out)      # atomik: kamus lama baru diganti setelah build sukses
    print(f'\n{out} siap ({os.path.getsize(out)/1e6:.1f} MB)')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
