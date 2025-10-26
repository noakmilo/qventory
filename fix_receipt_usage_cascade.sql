-- Fix receipt_usage foreign keys to use CASCADE on delete
-- This fixes the error: "null value in column receipt_id violates not-null constraint"
-- when trying to delete receipts

-- Step 1: Drop existing foreign key constraints
ALTER TABLE receipt_usage
    DROP CONSTRAINT IF EXISTS receipt_usage_receipt_id_fkey;

ALTER TABLE receipt_usage
    DROP CONSTRAINT IF EXISTS receipt_usage_user_id_fkey;

-- Step 2: Recreate foreign keys with ON DELETE CASCADE
ALTER TABLE receipt_usage
    ADD CONSTRAINT receipt_usage_receipt_id_fkey
    FOREIGN KEY (receipt_id)
    REFERENCES receipts(id)
    ON DELETE CASCADE;

ALTER TABLE receipt_usage
    ADD CONSTRAINT receipt_usage_user_id_fkey
    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE CASCADE;

-- Verify the constraints were created correctly
SELECT
    conname AS constraint_name,
    confdeltype AS delete_action,
    CASE confdeltype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
    END AS delete_action_readable
FROM pg_constraint
WHERE conname IN ('receipt_usage_receipt_id_fkey', 'receipt_usage_user_id_fkey')
ORDER BY conname;

-- Expected output:
-- Both constraints should show 'c' and 'CASCADE'
