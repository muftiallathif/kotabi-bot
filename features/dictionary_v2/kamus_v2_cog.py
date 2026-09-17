"""kamus_v2_cog.py — dictionary berbasis database_nihongo, MATI secara bawaan.

Kenapa opt-in dan bukan mengganti cog lama
------------------------------------------
`features/dictionary/` sudah punya /kanji, /kotoba, /bunpou yang **jalan dan
dipakai**. Modul ini menawarkan /kanji, /word, /bunpou dari sumber berbeda
(database_nihongo, bukan CSV). Namanya bertabrakan di dua tempat.

Mengganti kode yang bekerja dengan kode yang belum pernah jalan di Discord itu
arah yang salah — berapa pun banyaknya contract test yang lolos. Jadi:

    KOTABI_KAMUS_V2=0   (bawaan)  -> cog ini TIDAK dimuat, tidak ada yang berubah
    KOTABI_KAMUS_V2=1             -> /kanji2 /kotoba2 /bunpou2 (berdampingan)
    KOTABI_KAMUS_V2=takeover      -> /kanji /kotoba /bunpou.
                                     HANYA setelah cog lama dinonaktifkan,
                                     kalau tidak Discord menolak sync-nya.

Kenapa `/kotoba`, bukan `/word`
-------------------------------
言葉 mencakup kata, frasa, DAN ungkapan — dan itu memang isi datanya:
猫, 走る, 妨げる, お元気ですか, 〜に違いない. `/word` akan membuat user mengira
isinya cuma kosakata satu kata. Sekaligus menjaga identitas Kotabi tetap satu
bahasa: kanji / kotoba / bunpou, bukan campuran Inggris-Jepang.

Nama internal domain tetap `kata` (resolver, adapter, tes) — itu urusan kode,
bukan urusan user, dan menggantinya cuma menambah diff tanpa menambah nilai.

Butuh `data/kamus_nihongo/` (folder hasil ekstrak database_nihongo.zip) —
lihat database/README.md dan scripts/verifikasi_artefak.py.

Yang diuji sebelum modul ini masuk repo: 28 golden case -> 97 payload Discord,
231 tombol. Lihat BUKTI_KONTRAK_UX.txt di folder ini.
"""
import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands

_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_dir, 'support'))

_log = logging.getLogger('bot.kamus_v2')

MODE = os.getenv('KOTABI_KAMUS_V2', '0').lower()
AKAR_DB = os.getenv('KOTABI_DB_NIHONGO', 'data/kamus_nihongo')

# Awalan aman supaya bisa berjalan berdampingan dengan cog lama saat dibandingkan
NAMA = ({'kanji': 'kanji', 'kata': 'kotoba', 'bunpou': 'bunpou'} if MODE == 'takeover'
        else {'kanji': 'kanji2', 'kata': 'kotoba2', 'bunpou': 'bunpou2'})


class KamusV2(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rsv = None
        self.A = None

    async def cog_load(self):
        if not os.path.isdir(AKAR_DB):
            _log.error('❌ %s tidak ada — kamus v2 tidak dimuat. '
                       'Ekstrak database_nihongo.zip ke sana, lalu jalankan '
                       'scripts/verifikasi_artefak.py.', AKAR_DB)
            raise commands.ExtensionFailed('kamus_v2', FileNotFoundError(AKAR_DB))
        import adapter3
        from resolver import Resolver
        self.A = adapter3
        self.rsv = Resolver(AKAR_DB)
        _log.info('✅ kamus v2 aktif (mode=%s, perintah: /%s /%s /%s)',
                  MODE, NAMA['kanji'], NAMA['kata'], NAMA['bunpou'])

    async def _kirim(self, inter, domain, kunci):
        await inter.response.defer()
        s = self.A.Sesi(self.rsv, domain, kunci)
        h = s.render(1)
        v = self.A.TingkatView(s, h, inter.user.id) if h['tombol'] else None
        await inter.followup.send(embed=self.A.ke_embed(h['embed']), view=v)

    @app_commands.command(name=NAMA['kanji'], description='Cari kanji (database_nihongo)')
    async def kanji(self, inter: discord.Interaction, karakter: str):
        await self._kirim(inter, 'kanji', karakter.strip()[:1])

    @app_commands.command(name=NAMA['kata'], description='Cari kotoba — kata, frasa, ungkapan (database_nihongo)')
    async def kata(self, inter: discord.Interaction, kata: str):
        await self._kirim(inter, 'kata', kata.strip())

    @app_commands.command(name=NAMA['bunpou'], description='Cari pola tata bahasa (database_nihongo)')
    async def bunpou(self, inter: discord.Interaction, pola: str):
        await self._kirim(inter, 'bunpou', pola.strip())


async def setup(bot):
    if MODE in ('0', 'false', 'off', ''):
        _log.info('kamus v2 dilewati (KOTABI_KAMUS_V2=%s). Cog dictionary lama '
                  'tetap dipakai, tidak ada yang berubah.', MODE or '0')
        return
    await bot.add_cog(KamusV2(bot))
