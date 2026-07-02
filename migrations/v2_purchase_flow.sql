-- ============================================================
-- Kotabi Membership System v2 — Purchase Flow Migration
-- ============================================================
-- Menambahkan dukungan untuk alur pembelian versi v3:
--   - status 'draft' (sebelum bukti transfer diupload) dan
--     'needs_resubmit' (setelah reject dengan alasan "bukti tidak valid")
--   - kode unik nominal (order_id mod 100)
--   - bukti transfer, bank pengirim, perceptual hash (pHash) anti-fraud
--   - draft_created_at / confirmed_at untuk keperluan draft timeout 24 jam
--
-- SQLite tidak bisa mengubah CHECK constraint lewat ALTER TABLE, jadi
-- tabel `orders` di-recreate (rename -> create baru -> copy data -> drop
-- lama). Migrasi additive: TIDAK ada data order lama yang hilang.
--
-- JALANKAN SEKALI SAJA. Tidak idempotent (sama seperti
-- migrations/v1_membership_system.sql) — kalau perlu re-run, drop dulu
-- tabel `orders_old_v1` peninggalan run sebelumnya secara manual.
-- ============================================================

BEGIN TRANSACTION;

-- ------------------------------------------------------------
-- 1. Simpan tabel orders lama
-- ------------------------------------------------------------

ALTER TABLE orders RENAME TO orders_old_v1;

-- ------------------------------------------------------------
-- 2. Buat tabel orders baru dengan schema v2
-- ------------------------------------------------------------

CREATE TABLE orders (
    order_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id            INTEGER NOT NULL,
    user_id             INTEGER NOT NULL,
    product_key         TEXT    NOT NULL,
    product_version     TEXT    NOT NULL,
    product_name        TEXT    NOT NULL,   -- snapshot, tidak berubah walau YAML ganti
    price               INTEGER NOT NULL,   -- snapshot harga saat order dibuat
    quantity            INTEGER NOT NULL DEFAULT 1,
    total_duration      INTEGER,            -- total hari, NULL jika lifetime
    grant_payload       TEXT    NOT NULL,   -- JSON, dipakai saat approve

    status              TEXT    NOT NULL DEFAULT 'draft'
                        CHECK(status IN (
                            'draft',            -- belum submit bukti transfer, hanya user yang lihat
                            'pending',          -- sudah dikonfirmasi user, menunggu review staff
                            'needs_resubmit',   -- staff reject dengan alasan "bukti tidak valid/buram"
                            'approved',
                            'rejected',
                            'cancelled'
                        )),

    -- Kode unik nominal (order_id mod 100), lihat KOTABI_MEMBERSHIP_SYSTEM_v3.md
    -- bagian "Kode Unik Nominal". Diisi begitu order_id sudah diketahui
    -- (langsung setelah INSERT pertama).
    unique_code         INTEGER,

    -- Bukti transfer & anti-fraud (lihat bagian "Anti-Fraud Bukti Transfer")
    payment_proof_url   TEXT,
    sender_bank         TEXT,
    payment_phash       TEXT,

    -- Diisi saat staff reject dengan alasan "Bukti tidak valid/buram" (jalur A).
    -- NULL untuk reject jalur "Lainnya" (final) atau order yang belum di-reject.
    reject_reason_type  TEXT CHECK(reject_reason_type IN ('invalid_proof', 'other') OR reject_reason_type IS NULL),

    notes               TEXT,

    -- draft_created_at dipakai scheduler untuk auto-expire draft > 24 jam.
    -- confirmed_at diisi saat user klik "Konfirmasi Order" (draft -> pending).
    draft_created_at    TIMESTAMP,
    confirmed_at        TIMESTAMP,

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at         TIMESTAMP,
    approved_by         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_orders_guild_user
    ON orders (guild_id, user_id);

CREATE INDEX IF NOT EXISTS idx_orders_status
    ON orders (status, created_at);

CREATE INDEX IF NOT EXISTS idx_orders_draft_created
    ON orders (status, draft_created_at);

-- ------------------------------------------------------------
-- 3. Migrasikan data lama
-- ------------------------------------------------------------
-- Order lama tidak pernah melalui state 'draft' beneran (langsung dibuat
-- sebagai 'pending' di alur v1), jadi confirmed_at diisi sama dengan
-- created_at supaya konsisten secara historis. unique_code dihitung dari
-- order_id yang sudah ada.

INSERT INTO orders (
    order_id, guild_id, user_id, product_key, product_version, product_name,
    price, quantity, total_duration, grant_payload, status, unique_code,
    notes, confirmed_at, created_at, approved_at, approved_by
)
SELECT
    order_id, guild_id, user_id, product_key, product_version, product_name,
    price, quantity, total_duration, grant_payload, status, order_id % 100,
    notes, created_at, created_at, approved_at, approved_by
FROM orders_old_v1;

-- ------------------------------------------------------------
-- 4. Bersihkan tabel lama setelah verifikasi
-- ------------------------------------------------------------
-- Sengaja TIDAK di-drop otomatis di sini. Setelah kamu cek jumlah baris
-- `orders` == jumlah baris `orders_old_v1` (dan datanya masuk akal),
-- jalankan manual:
--
--   DROP TABLE orders_old_v1;

COMMIT;

-- ============================================================
-- VERIFIKASI SETELAH MIGRASI:
--   SELECT COUNT(*) FROM orders;
--   SELECT COUNT(*) FROM orders_old_v1;
--   (dua angka di atas harus sama)
--   SELECT order_id, status, unique_code FROM orders LIMIT 5;
-- ============================================================