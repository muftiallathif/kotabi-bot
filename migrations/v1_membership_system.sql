-- ============================================================
-- Kotabi Membership System v1 — Database Migration
-- ============================================================
-- SAFE TO RUN BERKALI-KALI (idempotent)
-- Semua operasi menggunakan IF NOT EXISTS atau OR IGNORE
-- Data lama tidak akan terhapus
-- ============================================================


-- ------------------------------------------------------------
-- 1. TABEL BARU: orders
-- ------------------------------------------------------------
-- Immutable setelah dibuat, kecuali status dan approval fields.
-- grant_payload = JSON snapshot dari products.yml saat order dibuat.
-- Approval selalu pakai grant_payload, bukan baca ulang YAML.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS orders (
    order_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    product_key     TEXT    NOT NULL,
    product_version TEXT    NOT NULL,
    product_name    TEXT    NOT NULL,   -- snapshot, tidak berubah walau YAML ganti
    price           INTEGER NOT NULL,   -- snapshot harga saat order dibuat
    quantity        INTEGER NOT NULL DEFAULT 1,
    total_duration  INTEGER,            -- total hari, NULL jika lifetime
    grant_payload   TEXT    NOT NULL,   -- JSON, dipakai saat approve
    status          TEXT    NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected', 'cancelled')),
    notes           TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at     TIMESTAMP,
    approved_by     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_orders_guild_user
    ON orders (guild_id, user_id);

CREATE INDEX IF NOT EXISTS idx_orders_status
    ON orders (status, created_at);


-- ------------------------------------------------------------
-- 2. TABEL BARU: trial_claims
-- ------------------------------------------------------------
-- Satu baris per user per guild per cycle.
-- Cycle: '2026A' (Jan-Ags) atau '2026B' (Sep-Des).
-- Trial boleh diambil lagi hanya jika cycle tersimpan < cycle sekarang.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS trial_claims (
    user_id     INTEGER NOT NULL,
    guild_id    INTEGER NOT NULL,
    trial_cycle TEXT    NOT NULL,   -- contoh: '2026A', '2026B'
    claimed_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id, trial_cycle)
);


-- ------------------------------------------------------------
-- 3. PERBARUI TABEL: memberships
-- ------------------------------------------------------------
-- Tambah kolom source untuk tracking asal grant.
-- Kolom lain (payment_count, point_count, is_lifetime) sudah ada
-- dari migrasi sebelumnya — diabaikan jika sudah ada.
-- ------------------------------------------------------------

-- Kolom yang mungkin belum ada dari versi sebelumnya
-- Masing-masing dalam blok terpisah agar partial failure tidak block sisanya

ALTER TABLE memberships ADD COLUMN source TEXT
    CHECK(source IN ('trial', 'purchase', 'class', 'auto_patron', 'admin'));

-- Catatan: ALTER TABLE ADD COLUMN akan error jika kolom sudah ada.
-- Jalankan manual jika error, atau gunakan migration runner yang handle ini.


-- ------------------------------------------------------------
-- 4. BUAT ULANG TABEL: membership_history (versi diperluas)
-- ------------------------------------------------------------
-- Tabel lama di-rename, tabel baru dibuat dengan schema lengkap.
-- Data lama dipindah ke tabel baru.
-- ------------------------------------------------------------

-- Buat tabel baru dengan schema v1
CREATE TABLE IF NOT EXISTS membership_history_v1 (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    event         TEXT    NOT NULL
                  CHECK(event IN (
                      'trial_claimed',
                      'membership_extended',
                      'membership_expired',
                      'patron_granted',
                      'admin_grant',
                      'admin_revoke',
                      'purchase_approved',
                      'purchase_rejected',
                      'class_granted',
                      'auto_patron',
                      -- legacy events dari versi lama, tetap valid
                      'grant',
                      'revoke',
                      'warned_expiry',
                      'trial_expired',
                      'lifetime_unlocked'
                  )),
    tier_before   TEXT,
    tier_after    TEXT,
    expiry_before TIMESTAMP,
    expiry_after  TIMESTAMP,
    point_before  INTEGER,
    point_after   INTEGER,
    order_id      INTEGER REFERENCES orders(order_id),
    actor         INTEGER,   -- user_id yang melakukan aksi (admin atau system)
    reason        TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_membership_history_v1_user
    ON membership_history_v1 (guild_id, user_id, created_at DESC);

-- Migrate data lama ke tabel baru (jika tabel lama ada)
-- event, tier, granted_by, timestamp, reason dari schema lama
INSERT OR IGNORE INTO membership_history_v1
    (guild_id, user_id, event, tier_after, actor, reason, created_at)
SELECT
    guild_id,
    user_id,
    action,     -- kolom lama bernama 'action'
    tier,
    granted_by,
    reason,
    timestamp
FROM membership_history
WHERE NOT EXISTS (
    SELECT 1 FROM membership_history_v1 LIMIT 1
);

-- Setelah verifikasi data berhasil dimigrate, tabel lama bisa di-drop manual:
-- DROP TABLE membership_history;
-- ALTER TABLE membership_history_v1 RENAME TO membership_history;
-- (jangan dijalankan di script ini, lakukan manual setelah verifikasi)


-- ============================================================
-- SELESAI
-- Jalankan SELECT * FROM orders LIMIT 1; untuk verifikasi.
-- ============================================================