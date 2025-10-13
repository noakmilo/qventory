#!/usr/bin/env python3
"""
Fix PostgreSQL sequences for all tables in Qventory database.

This script resets all auto-increment sequences to the correct next value
based on existing data. This is needed when records are deleted but sequences
don't automatically adjust.

Usage:
    python fix_sequences.py

    Or with explicit database URI:
    DATABASE_URL="postgresql://user:pass@host/db" python fix_sequences.py
"""

import os
import sys
import psycopg2
from urllib.parse import urlparse

def get_database_url():
    """Get database URL from environment or .env file"""
    # Try to get from environment first
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        return db_url

    # Try to load from .env file
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('DATABASE_URL='):
                    db_url = line.split('=', 1)[1].strip('"').strip("'")
                    return db_url

    # Default to production settings
    print("⚠️  DATABASE_URL not found in environment or .env")
    print("Using default: postgresql://qventory:qventory@localhost/qventory_db")
    return "postgresql://qventory:qventory@localhost/qventory_db"

def connect_to_database():
    """Connect to PostgreSQL database"""
    db_url = get_database_url()
    print(f"📡 Connecting to: {db_url.split('@')[1] if '@' in db_url else db_url}")

    try:
        # Parse the database URL
        parsed = urlparse(db_url)

        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path[1:],  # Remove leading /
            user=parsed.username,
            password=parsed.password
        )
        print("✅ Connected to PostgreSQL\n")
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}\n")
        sys.exit(1)

def fix_sequence(cursor, table_name, id_column='id'):
    """Fix a single table's sequence"""
    try:
        # Get the sequence name
        cursor.execute(f"SELECT pg_get_serial_sequence('{table_name}', '{id_column}')")
        result = cursor.fetchone()

        if not result or not result[0]:
            print(f"  ⚠️  No sequence found for {table_name}.{id_column}")
            return False

        sequence_name = result[0]

        # Get the max ID from the table
        cursor.execute(f"SELECT COALESCE(MAX({id_column}), 0) FROM {table_name}")
        max_id = cursor.fetchone()[0]

        # Get current sequence value
        cursor.execute(f"SELECT last_value FROM {sequence_name}")
        current_seq = cursor.fetchone()[0]

        # Set the sequence to max_id + 1
        next_val = max_id + 1
        cursor.execute(f"SELECT setval('{sequence_name}', {next_val}, false)")

        print(f"  ✅ {table_name:30} | max_id: {max_id:5} | seq_was: {current_seq:5} | seq_now: {next_val}")
        return True

    except psycopg2.Error as e:
        print(f"  ⚠️  {table_name:30} | Skipped: {e.pgerror or str(e)}")
        return None  # None means skipped, not failed
    except Exception as e:
        print(f"  ❌ {table_name:30} | Error: {e}")
        return False

def main():
    """Fix all sequences in the database"""
    print("\n" + "="*80)
    print("🔧 FIXING POSTGRESQL SEQUENCES")
    print("="*80 + "\n")

    conn = connect_to_database()
    cursor = conn.cursor()

    # List of all tables with auto-increment IDs
    tables = [
        'settings',
        'users',
        'items',
        'sales',
        'listings',
        'import_jobs',
        'failed_imports',
        'reports',
        'expenses',
        'marketplace_credentials',
        'subscriptions',
        'ai_token_usage',
        'ai_token_config',
        'plan_limits',
    ]

    success_count = 0
    skip_count = 0
    fail_count = 0

    for table in tables:
        result = fix_sequence(cursor, table)
        if result is True:
            success_count += 1
        elif result is None:
            skip_count += 1
        else:
            fail_count += 1

    # Commit all changes
    conn.commit()

    print("\n" + "="*80)
    print(f"✅ Fixed: {success_count} sequences")
    if skip_count > 0:
        print(f"⚠️  Skipped: {skip_count} sequences (table doesn't exist or no sequence)")
    if fail_count > 0:
        print(f"❌ Failed: {fail_count} sequences")
    print("="*80 + "\n")

    # Close connection
    cursor.close()
    conn.close()

    if fail_count == 0:
        print("🎉 All sequences fixed successfully!\n")
        print("You can now create new users from the admin dashboard.\n")
    else:
        print("⚠️  Some sequences could not be fixed. Check errors above.\n")
        sys.exit(1)

if __name__ == '__main__':
    main()
