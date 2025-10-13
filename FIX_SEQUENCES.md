# Fix PostgreSQL Sequences

## Problem

When creating new users from the admin dashboard, you may encounter this error:

```
sqlalchemy.exc.IntegrityError: (psycopg2.errors.UniqueViolation)
duplicate key value violates unique constraint "settings_pkey"
DETAIL: Key (id)=(1) already exists.
```

## Cause

PostgreSQL uses sequences to generate auto-increment IDs. When records are deleted, the sequences don't automatically adjust to the new max ID. This causes conflicts when trying to insert new records.

This typically happens after:
- Deleting users from admin dashboard
- Manually deleting records from database
- Restoring from a backup

## Solution

Run the sequence fix script to reset all sequences to the correct values.

### Option 1: Python Script (Recommended)

**Requirements:** Python 3 with `psycopg2` or `psycopg2-binary`

```bash
# On the server (as root)
cd /opt/qventory/qventory

# Install psycopg2-binary if not installed
pip3 install psycopg2-binary

# Run the fix script (it will read DATABASE_URL from .env)
python3 fix_sequences.py
```

**Output:**
```
================================================================================
🔧 FIXING POSTGRESQL SEQUENCES
================================================================================

📡 Connecting to: localhost/qventory_db
✅ Connected to PostgreSQL

  ✅ settings                        | max_id:     2 | seq_was:     1 | seq_now:     3
  ✅ users                           | max_id:     3 | seq_was:     2 | seq_now:     4
  ✅ items                           | max_id:  1730 | seq_was:  1500 | seq_now:  1731
  ✅ sales                           | max_id:   198 | seq_was:   150 | seq_now:   199
  ⚠️  ai_token_config                | Skipped: relation "ai_token_config" does not exist

================================================================================
✅ Fixed: 12 sequences
⚠️  Skipped: 2 sequences (table doesn't exist or no sequence)
================================================================================

🎉 All sequences fixed successfully!

You can now create new users from the admin dashboard.
```

### Option 2: Direct SQL (Alternative)

```bash
# On the server
sudo -u postgres psql qventory_db < /opt/qventory/qventory/fix_sequences.sql
```

## Verification

After running the fix, try creating a new user from the admin dashboard. It should work without errors.

You can also verify the sequences manually:

```sql
-- Check settings table
SELECT MAX(id) FROM settings;
SELECT last_value FROM settings_id_seq;

-- The sequence value should be greater than the max ID
```

## Prevention

The `admin_delete_user` function has been updated to properly delete all user data in the correct order. However, if you manually delete records from the database, you may need to run this fix script again.

## What This Script Does

For each table with an auto-increment ID:

1. Finds the maximum ID currently in the table
2. Gets the current sequence value
3. Sets the sequence to `max_id + 1`

This ensures the next INSERT will use an available ID.

## Tables Fixed

- `settings`
- `users`
- `items`
- `sales`
- `listings`
- `import_jobs`
- `failed_imports`
- `reports`
- `expenses`
- `marketplace_credentials`
- `subscriptions`
- `ai_token_usage`
- `ai_token_config`
- `plan_limits`

## Troubleshooting

### Error: "relation does not exist"

This means the table doesn't exist in your database. This is normal for optional tables. The script will skip them.

### Error: "permission denied"

Make sure you're running as the correct user with database access. Use the virtual environment:

```bash
cd /opt/qventory/qventory
source qventory/bin/activate
```

### Still Getting Duplicate Key Errors

1. Check which table is causing the error in the logs
2. Run the fix script again
3. If the problem persists, manually check the sequence:

```sql
SELECT setval('settings_id_seq', (SELECT MAX(id) FROM settings) + 1, false);
```

## Files

- `fix_sequences.py` - Python script (uses Flask app context)
- `fix_sequences.sql` - Raw SQL script (direct PostgreSQL)
- `FIX_SEQUENCES.md` - This documentation
