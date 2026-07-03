-- ============================================================
-- Kotabi Bot — Migration v3: Practice Threads (Grup D)
-- ============================================================
-- Menyimpan thread latihan reusable per user di quiz-public-forum.
-- Berbeda dari `user_threads` (bilik ujian rank yang di-lock) —
-- practice_threads dipakai fitur "Mulai Latihan" yang PUBLIK
-- (features/gatekeeper/practice_cog.py).
--
-- SAFE TO RUN BERKALI-KALI (idempotent, pakai IF NOT EXISTS).
-- Catatan: tabel ini juga dibuat otomatis oleh
-- PracticeThreads.cog_load() saat bot start, jadi menjalankan file
-- ini manual sifatnya opsional — hanya untuk konsistensi dengan
-- migrations/ yang sudah ada (v1, v2).
-- ============================================================

CREATE TABLE IF NOT EXISTS practice_threads (
    user_id   INTEGER NOT NULL PRIMARY KEY,
    thread_id INTEGER NOT NULL
);