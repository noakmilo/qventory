#!/usr/bin/env python3
"""
Fix PostgreSQL sequences for all tables in Qventory database.

This script resets all auto-increment sequences to the correct next value
based on existing data. This is needed when records are deleted but sequences
don't automatically adjust.

Usage:
    python fix_sequences.py
"""

import os
import sys

# Add the parent directory to the path to import qventory modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qventory import create_app
from qventory.extensions import db
from sqlalchemy import text

def fix_sequence(table_name, id_column='id'):
    """Fix a single table's sequence"""
    try:
        # Get the sequence name
        sequence_query = f"SELECT pg_get_serial_sequence('{table_name}', '{id_column}')"
        result = db.session.execute(text(sequence_query)).scalar()

        if not result:
            print(f"  ⚠️  No sequence found for {table_name}.{id_column}")
            return False

        sequence_name = result

        # Get the max ID from the table
        max_id_query = f"SELECT COALESCE(MAX({id_column}), 0) FROM {table_name}"
        max_id = db.session.execute(text(max_id_query)).scalar()

        # Get current sequence value
        current_seq = db.session.execute(text(f"SELECT last_value FROM {sequence_name}")).scalar()

        # Set the sequence to max_id + 1
        next_val = max_id + 1
        db.session.execute(text(f"SELECT setval('{sequence_name}', {next_val}, false)"))
        db.session.commit()

        print(f"  ✅ {table_name:30} | max_id: {max_id:5} | seq_was: {current_seq:5} | seq_now: {next_val}")
        return True

    except Exception as e:
        print(f"  ❌ {table_name:30} | Error: {e}")
        db.session.rollback()
        return False

def main():
    """Fix all sequences in the database"""
    app = create_app()

    with app.app_context():
        print("\n" + "="*80)
        print("🔧 FIXING POSTGRESQL SEQUENCES")
        print("="*80 + "\n")

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
        fail_count = 0

        for table in tables:
            if fix_sequence(table):
                success_count += 1
            else:
                fail_count += 1

        print("\n" + "="*80)
        print(f"✅ Fixed: {success_count} sequences")
        if fail_count > 0:
            print(f"❌ Failed: {fail_count} sequences")
        print("="*80 + "\n")

        if fail_count == 0:
            print("🎉 All sequences fixed successfully!\n")
        else:
            print("⚠️  Some sequences could not be fixed. Check errors above.\n")

if __name__ == '__main__':
    main()
