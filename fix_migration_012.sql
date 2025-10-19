-- Fix migration 012: Add missing columns to auto_relist_rules
-- Run this if flask db upgrade didn't create the columns

ALTER TABLE auto_relist_rules
ADD COLUMN IF NOT EXISTS enable_price_decrease BOOLEAN DEFAULT FALSE;

ALTER TABLE auto_relist_rules
ADD COLUMN IF NOT EXISTS price_decrease_type VARCHAR(20);

ALTER TABLE auto_relist_rules
ADD COLUMN IF NOT EXISTS price_decrease_amount FLOAT;

ALTER TABLE auto_relist_rules
ADD COLUMN IF NOT EXISTS min_price FLOAT;

ALTER TABLE auto_relist_rules
ADD COLUMN IF NOT EXISTS run_first_relist_immediately BOOLEAN DEFAULT FALSE;

-- Verify columns were created
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'auto_relist_rules'
  AND column_name IN ('enable_price_decrease', 'price_decrease_type', 'price_decrease_amount', 'min_price', 'run_first_relist_immediately')
ORDER BY column_name;
