#!/usr/bin/env python3
"""adapter3.py — state tingkat + interaksi. TIDAK menentukan isi tampilan.

Batas tanggung jawab:
    renderer3.py  -> satu-satunya sumber kebenaran isi L1/L2/L3
    adapter3.py   -> state, tombol, edit pesan, buang metadata internal
    discord.py    -> hanya disentuh di bagian paling bawah berkas ini

Yang dijaga:
  1. Entri di-resolve SEKALI saat command dipanggil, lalu disimpan di objek
     sesi. Klik tombol memakai objek yang SAMA — bukan mencari ulang "妨".
     Kalau tombol memicu pencarian baru, tingkat berhenti jadi state UI dan
     berubah jadi tiga command yang kebetulan tampil beda.
  2. Pindah tingkat = EDIT pesan yang ada, bukan kirim pesan baru.
  3. `_tingkat` dan `_domain` dibuang sebelum payload menyentuh Discord.
  4. Bolak-balik L1→L2→L3→L1 harus menghasilkan L1 yang IDENTIK dengan awal.

Bagian di atas `ke_embed()` bisa diuji tanpa discord.py — lihat uji_adapter.py.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import renderer3 as R
import kartu_bunpou

INTERNAL = ('_tingkat', '_domain')


def bersihkan(e):
    """Buang metadata internal sebelum payload dikirim ke Discord."""
    return {k: v for k, v in e.items() if k not in INTERNAL}


class Sesi:
    """Satu hasil pencarian + tingkat yang sedang ditampilkan.

    Data di-resolve SEKALI di __init__. Tombol hanya mengubah `tingkat`,
    tidak pernah memanggil resolver lagi dengan teks dari tombol.
    """

    def __init__(self, rsv, domain, kunci):
        self.rsv = rsv
        self.domain = domain
        self.kunci = kunci
        self.tingkat = 1
        self.ada = True
        if domain == 'kanji':
            self.data = rsv.kanji(kunci)
            self.ada = self.data is not None
            self._freq = self._aksen = None
        elif domain == 'kata':
            r = rsv.kata(kunci)
            self.ada = r is not None
            if r:
                self.data, self._freq, self._aksen = r
                self.kunci = self.data['kata']       # 走った -> 走る
        else:
            r = rsv.bunpou(kunci)
            self.ada = r is not None
            self.data = r

    def _lazy_kuantitatif(self):
        """Frekuensi & aksen baru dibaca kalau tingkat yang butuh dibuka.

        Berkas ini ratusan MB; jangan dibaca untuk L1 yang tidak memakainya.
        """
        if self._freq is None:
            self._freq = self.rsv._freq(self.kunci)
            self._aksen = self.rsv._aksen(self.kunci)
        return self._freq, self._aksen

    def render(self, tingkat=None):
        if tingkat is not None:
            self.tingkat = tingkat
        t = self.tingkat
        if not self.ada:
            return R.tidak_ada(self.kunci, self.domain)
        # Kartu PENGALIHAN (mis. ⽉ -> 月) tidak punya tingkat 2/3: isinya cuma
        # penunjuk, bukan entri kanji. Tanpa penjagaan ini, render(2) akan
        # meledak KeyError karena dict pengalihan tidak punya field struktural.
        # Ditemukan uji_jalur_produksi.py — tiga tes sebelumnya melewatkannya
        # karena tombol UI memang tidak pernah mengarah ke sana.
        if self.domain == 'kanji' and self.data.get('_pengalihan'):
            self.tingkat = 1
            return R.kanji_l1(self.data)
        if self.domain == 'kanji':
            if t == 1:
                return R.kanji_l1(self.data)
            if t == 2:
                return R.kanji_l2(self.data)
            return R.kanji_l3(self.data, *self._lazy_kuantitatif())
        if self.domain == 'kata':
            if t == 1:
                return R.kata_l1(self.data)
            if t == 2:
                return R.kata_l2(self.data, self._freq)
            return R.kata_l3(self.data)
        m, rf, en = self.data
        B = kartu_bunpou.bersih
        if t == 1:
            return R.bunpou_l1(self.kunci, m, rf, en, B)
        if t == 2:
            return R.bunpou_l2(self.kunci, m, rf, en, B)
        return R.bunpou_l3(self.kunci, m, rf, en, B)


def rute(custom_id):
    """`k2:妨` -> ('kanji', 2, '妨'). Mengembalikan None untuk aksi non-tingkat."""
    aksi, _, sisa = custom_id.partition(':')
    if len(aksi) == 2 and aksi[0] in 'kwb' and aksi[1] in '123':
        return {'k': 'kanji', 'w': 'kata', 'b': 'bunpou'}[aksi[0]], int(aksi[1]), sisa
    return None


# ───────────────────────────────────────────────────────── bagian Discord ──
try:
    import discord
    from discord import app_commands
except ImportError:
    discord = None

GAYA = {'primary': 1, 'secondary': 2, 'success': 3, 'danger': 4}


def ke_embed(d):
    d = bersihkan(d)
    e = discord.Embed(title=d.get('title'), description=d.get('description'),
                      color=d.get('color', 0x2B2D31))
    for f in d.get('fields', []):
        e.add_field(name=f['name'], value=f['value'], inline=f['inline'])
    if d.get('footer'):
        e.set_footer(text=d['footer']['text'])
    return e


# Kelas View hanya didefinisikan kalau discord.py terpasang — supaya berkas ini
# tetap bisa diimpor oleh uji_adapter.py tanpa discord.py sama sekali.
_Basis = discord.ui.View if discord else object


class TingkatView(_Basis):
    """Menyimpan Sesi. Klik tombol EDIT pesan, tidak mengirim yang baru."""

    def __init__(self, sesi, hasil, pemilik_id):
        super().__init__(timeout=300)
        self.sesi = sesi
        self.pemilik_id = pemilik_id
        self._isi(hasil)

    def _isi(self, hasil):
        self.clear_items()
        for t in hasil['tombol'][:5]:
            b = discord.ui.Button(label=t['label'][:80], custom_id=t['id'][:100],
                                  style=discord.ButtonStyle(GAYA.get(t['gaya'], 2)))
            b.callback = self._klik
            self.add_item(b)

    async def interaction_check(self, inter):
        if inter.user.id != self.pemilik_id:
            await inter.response.send_message('Kartu ini milik orang lain — '
                                              'panggil perintahnya sendiri.', ephemeral=True)
            return False
        return True

    async def _klik(self, inter):
        cid = inter.data['custom_id']
        r = rute(cid)
        if r:
            _, tingkat, _ = r
            hasil = self.sesi.render(tingkat)      # objek SAMA, tanpa cari ulang
            self._isi(hasil)
            return await inter.response.edit_message(embed=ke_embed(hasil['embed']), view=self)
        aksi, _, sisa = cid.partition(':')
        if aksi == 'kn':
            # navigasi ke entri LAIN -> sesi baru, lalu edit pesan yang sama
            self.sesi = Sesi(self.sesi.rsv, 'kanji', sisa)
            hasil = self.sesi.render(1)
            self._isi(hasil)
            return await inter.response.edit_message(embed=ke_embed(hasil['embed']), view=self)
        # aksi non-tingkat lain -> balasan ephemeral, kartu utama tidak diganggu
        if aksi == 'kg':
            p = self.sesi.rsv.svg_goresan(sisa)
            if not p:
                return await inter.response.send_message('Urutan goresan tidak ada.', ephemeral=True)
            return await inter.response.send_message(file=discord.File(p, filename=f'{sisa}.svg'),
                                                     ephemeral=True)
        if aksi == 'kd':
            k, _, nm = sisa.partition(':')
            t = self.sesi.rsv.kamus_kanji(k, nm)
            return await inter.response.send_message(
                embed=ke_embed(R.embed(f'{k} — {nm}', (t or '')[:3500])), ephemeral=True)
        if aksi == 'bs':
            p, _, s = sisa.partition(':')
            t = self.sesi.rsv.sumber_bunpou(p, s)
            return await inter.response.send_message(
                embed=ke_embed(R.embed(f'{p} — {s}', kartu_bunpou.bersih(t or '')[:3500])),
                ephemeral=True)
        await inter.response.send_message('Belum tersedia.', ephemeral=True)


def buat_bot(root):
    from resolver import Resolver
    rsv = Resolver(root)
    bot = discord.Client(intents=discord.Intents.default())
    tree = app_commands.CommandTree(bot)

    async def _kirim(inter, domain, kunci):
        await inter.response.defer()
        s = Sesi(rsv, domain, kunci)
        h = s.render(1)
        await inter.followup.send(embed=ke_embed(h['embed']),
                                  view=TingkatView(s, h, inter.user.id) if h['tombol'] else None)

    @tree.command(name='kanji', description='Cari kanji')
    async def _k(inter, karakter: str):
        await _kirim(inter, 'kanji', karakter.strip()[:1])

    @tree.command(name='word', description='Cari kosakata')
    async def _w(inter, kata: str):
        await _kirim(inter, 'kata', kata.strip())

    @tree.command(name='bunpou', description='Cari pola tata bahasa')
    async def _b(inter, pola: str):
        await _kirim(inter, 'bunpou', pola.strip())

    @bot.event
    async def on_ready():
        await tree.sync()
        print(f'siap: {bot.user}')

    return bot


if __name__ == '__main__':
    if discord is None:
        sys.exit('pip install discord.py')
    tok = os.environ.get('DISCORD_TOKEN')
    if not tok:
        sys.exit('set DISCORD_TOKEN')
    buat_bot(sys.argv[1] if len(sys.argv) > 1 else '.').run(tok)
