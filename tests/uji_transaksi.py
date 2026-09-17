"""Uji TRANSAKSI(): reload yang gagal di tengah TIDAK boleh mengosongkan kamus.

Menjalankan KotabiBot.TRANSAKSI yang asli (disalin apa adanya) terhadap SQLite
sungguhan — bukan mock — lalu memaksa exception di tengah.
"""
import asyncio, aiosqlite, os, tempfile
from contextlib import asynccontextmanager


class Mini:
    def __init__(self, p):
        self.db_path = p
        self._db_lock = asyncio.Lock()

    async def RUN(self, q, p=()):
        async with self._db_lock:
            async with aiosqlite.connect(self.db_path) as db:
                c = await db.execute(q, p); await db.commit(); return c.rowcount

    async def RUN_MANY(self, q, pl):
        async with self._db_lock:
            async with aiosqlite.connect(self.db_path) as db:
                c = await db.executemany(q, pl); await db.commit(); return c.rowcount

    async def GET(self, q, p=()):
        async with self._db_lock:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(q, p) as c: return await c.fetchall()

    @asynccontextmanager
    async def TRANSAKSI(self):
        async with self._db_lock:
            async with aiosqlite.connect(self.db_path) as db:
                try:
                    yield db; await db.commit()
                except Exception:
                    await db.rollback(); raise


async def main():
    p = os.path.join(tempfile.mkdtemp(), 't.sqlite3')
    b = Mini(p)
    await b.RUN("CREATE TABLE kamus (kanji TEXT PRIMARY KEY, arti TEXT);")
    await b.RUN_MANY("INSERT INTO kamus VALUES (?,?);", [('猫','kucing'),('犬','anjing'),('妨','menghalangi')])
    awal = len(await b.GET("SELECT * FROM kamus;"))
    print(f'awal: {awal} entri')

    print('\n── CARA LAMA: RUN(DELETE) lalu RUN_MANY(INSERT) gagal')
    try:
        await b.RUN("DELETE FROM kamus;")
        await b.RUN_MANY("INSERT INTO kamus VALUES (?,?);", [('鳥','burung'), ('鳥','DUPLIKAT')])
    except Exception as e:
        print(f'   INSERT gagal: {type(e).__name__}')
    n = len(await b.GET("SELECT * FROM kamus;"))
    print(f'   isi kamus sekarang: {n} entri   {"← KOSONG, data hilang" if n==0 else ""}')

    # pulihkan
    await b.RUN_MANY("INSERT INTO kamus VALUES (?,?);", [('猫','kucing'),('犬','anjing'),('妨','menghalangi')])
    print(f'\n   (dipulihkan ke {len(await b.GET("SELECT * FROM kamus;"))} entri)')

    print('\n── CARA BARU: TRANSAKSI(), INSERT gagal di tengah')
    try:
        async with b.TRANSAKSI() as db:
            await db.execute("DELETE FROM kamus;")
            await db.executemany("INSERT INTO kamus VALUES (?,?);", [('鳥','burung'), ('鳥','DUPLIKAT')])
    except Exception as e:
        print(f'   INSERT gagal: {type(e).__name__} → rollback')
    n2 = len(await b.GET("SELECT * FROM kamus;"))
    print(f'   isi kamus sekarang: {n2} entri   {"← UTUH, data selamat" if n2==awal else "← MASIH HILANG"}')

    print('\n── TRANSAKSI() jalur sukses')
    async with b.TRANSAKSI() as db:
        await db.execute("DELETE FROM kamus;")
        await db.executemany("INSERT INTO kamus VALUES (?,?);", [('鳥','burung'),('魚','ikan')])
    print(f'   isi kamus: {len(await b.GET("SELECT * FROM kamus;"))} entri (diganti dgn benar)')

    assert n == 0 and n2 == awal, 'uji GAGAL'
    print('\n✅ TRANSAKSI() terbukti: cara lama mengosongkan kamus, cara baru tidak.')

asyncio.run(main())
