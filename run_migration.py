#!/usr/bin/env python3
"""
Database migration runner for Qventory
Executes SQL migration files with rollback support
"""
import os
import sys
from datetime import datetime
from qventory import create_app, db

def run_migration(migration_file):
    """Execute a SQL migration file"""
    separator = "=" * 60
    print(f"\n{separator}")
    print(f"Running migration: {migration_file}")
    print(f"{separator}\n")

    if not os.path.exists(migration_file):
        print(f"❌ Migration file not found: {migration_file}")
        return False

    # Read migration SQL
    with open(migration_file, 'r') as f:
        sql_content = f.read()

    app = create_app()

    with app.app_context():
        try:
            # Split by semicolons but preserve them for execution
            statements = [s.strip() + ';' for s in sql_content.split(';') if s.strip()]

            print(f"📋 Found {len(statements)} SQL statements to execute\n")

            # Execute each statement
            for i, statement in enumerate(statements, 1):
                # Skip comments and empty statements
                if statement.strip().startswith('--') or statement.strip() == ';':
                    continue

                # Show abbreviated statement
                preview = statement[:80].replace('\n', ' ')
                if len(statement) > 80:
                    preview += '...'
                print(f"  [{i}/{len(statements)}] {preview}")

                try:
                    db.session.execute(db.text(statement))
                except Exception as e:
                    # If it's an "already exists" error, it's safe to continue
                    error_msg = str(e).lower()
                    if 'already exists' in error_msg or 'duplicate column' in error_msg:
                        print(f"      ⚠️  Skipped (already exists)")
                        continue
                    else:
                        raise

            # Commit all changes
            db.session.commit()

            separator = "=" * 60
            print(f"\n{separator}")
            print(f"✅ Migration completed successfully!")
            print(f"{separator}\n")
            return True

        except Exception as e:
            db.session.rollback()
            separator = "=" * 60
            print(f"\n{separator}")
            print(f"❌ Migration failed: {str(e)}")
            print(f"{separator}\n")
            print("🔄 All changes have been rolled back.")
            return False

def main():
    """Main entry point"""
    if len(sys.argv) > 1:
        migration_file = sys.argv[1]
    else:
        # Default to the first migration
        migration_file = 'migrations/001_prepare_for_api_integrations.sql'

    print(f"\n🚀 Qventory Database Migration Tool")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    success = run_migration(migration_file)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
