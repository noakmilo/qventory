#!/bin/bash
# Quick fix for receipt_usage CASCADE delete issue
# Run this on the droplet to fix the foreign key constraints

echo "🔧 Fixing receipt_usage CASCADE delete constraints..."

# Execute SQL directly in PostgreSQL
sudo -u postgres psql qventory_db << 'EOF'

-- Drop existing constraints
ALTER TABLE receipt_usage DROP CONSTRAINT IF EXISTS receipt_usage_receipt_id_fkey;
ALTER TABLE receipt_usage DROP CONSTRAINT IF EXISTS receipt_usage_user_id_fkey;

-- Recreate with CASCADE
ALTER TABLE receipt_usage
    ADD CONSTRAINT receipt_usage_receipt_id_fkey
    FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE;

ALTER TABLE receipt_usage
    ADD CONSTRAINT receipt_usage_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- Verify
\echo '✅ Constraints updated:'
SELECT conname,
       CASE confdeltype
           WHEN 'c' THEN 'CASCADE ✓'
           ELSE 'NOT CASCADE ✗'
       END as delete_action
FROM pg_constraint
WHERE conname LIKE 'receipt_usage%fkey';

EOF

echo "✅ Done! You can now delete receipts without errors."
