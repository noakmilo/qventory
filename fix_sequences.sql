-- Fix PostgreSQL sequences for all tables
-- This script resets sequences to the correct next value based on existing data

-- Fix settings sequence
SELECT setval(pg_get_serial_sequence('settings', 'id'),
    COALESCE((SELECT MAX(id) FROM settings), 0) + 1,
    false);

-- Fix users sequence (just in case)
SELECT setval(pg_get_serial_sequence('users', 'id'),
    COALESCE((SELECT MAX(id) FROM users), 0) + 1,
    false);

-- Fix items sequence
SELECT setval(pg_get_serial_sequence('items', 'id'),
    COALESCE((SELECT MAX(id) FROM items), 0) + 1,
    false);

-- Fix sales sequence
SELECT setval(pg_get_serial_sequence('sales', 'id'),
    COALESCE((SELECT MAX(id) FROM sales), 0) + 1,
    false);

-- Fix listings sequence
SELECT setval(pg_get_serial_sequence('listings', 'id'),
    COALESCE((SELECT MAX(id) FROM listings), 0) + 1,
    false);

-- Fix import_jobs sequence
SELECT setval(pg_get_serial_sequence('import_jobs', 'id'),
    COALESCE((SELECT MAX(id) FROM import_jobs), 0) + 1,
    false);

-- Fix failed_imports sequence
SELECT setval(pg_get_serial_sequence('failed_imports', 'id'),
    COALESCE((SELECT MAX(id) FROM failed_imports), 0) + 1,
    false);

-- Fix reports sequence
SELECT setval(pg_get_serial_sequence('reports', 'id'),
    COALESCE((SELECT MAX(id) FROM reports), 0) + 1,
    false);

-- Fix expenses sequence
SELECT setval(pg_get_serial_sequence('expenses', 'id'),
    COALESCE((SELECT MAX(id) FROM expenses), 0) + 1,
    false);

-- Fix marketplace_credentials sequence
SELECT setval(pg_get_serial_sequence('marketplace_credentials', 'id'),
    COALESCE((SELECT MAX(id) FROM marketplace_credentials), 0) + 1,
    false);

-- Fix subscriptions sequence
SELECT setval(pg_get_serial_sequence('subscriptions', 'id'),
    COALESCE((SELECT MAX(id) FROM subscriptions), 0) + 1,
    false);

-- Fix ai_token_usage sequence
SELECT setval(pg_get_serial_sequence('ai_token_usage', 'id'),
    COALESCE((SELECT MAX(id) FROM ai_token_usage), 0) + 1,
    false);

-- Show current sequence values for verification
SELECT
    'settings' as table_name,
    (SELECT MAX(id) FROM settings) as max_id,
    (SELECT last_value FROM pg_get_serial_sequence('settings', 'id')) as sequence_value
UNION ALL
SELECT
    'users',
    (SELECT MAX(id) FROM users),
    (SELECT last_value FROM settings_id_seq)
UNION ALL
SELECT
    'items',
    (SELECT MAX(id) FROM items),
    (SELECT last_value FROM items_id_seq)
UNION ALL
SELECT
    'sales',
    (SELECT MAX(id) FROM sales),
    (SELECT last_value FROM sales_id_seq);

-- Display summary
SELECT 'Sequences fixed successfully!' as status;
