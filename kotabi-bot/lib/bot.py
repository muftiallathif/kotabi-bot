# Alias untuk kompatibilitas mundur.
# Semua cog yang masih import dari "lib.bot" tetap jalan tanpa perlu diubah.
# Kedepannya, migrasikan import ke "from core.bot import KotabiBot".

from core.bot import KotabiBot

__all__ = ["KotabiBot"]