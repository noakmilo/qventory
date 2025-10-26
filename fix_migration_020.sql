-- Fix Migration 020: Mark as applied without executing
-- Run this if the receipts tables already exist

-- Check current migration version
SELECT version_num FROM alembic_version;

-- Update to migration 020 (mark as applied)
UPDATE alembic_version SET version_num = '020_add_receipts';

-- Verify
SELECT version_num FROM alembic_version;

-- Check that tables exist
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('receipts', 'receipt_items')
ORDER BY table_name;
