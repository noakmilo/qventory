#!/usr/bin/env python3
"""
Creates a fresh database with the complete schema
WARNING: This will DELETE your existing database!
"""
import os
import sys
from datetime import datetime

def main():
    db_path = "/opt/qventory/data/app.db"

    print("\n" + "="*60)
    print("⚠️  FRESH DATABASE CREATION")
    print("="*60)
    print(f"\nThis will DELETE: {db_path}")
    print("Make sure you have a backup!\n")

    response = input("Type 'yes' to continue: ")
    if response.lower() != 'yes':
        print("Aborted.")
        sys.exit(0)

    # Delete old database
    if os.path.exists(db_path):
        backup_path = f"{db_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"\n📦 Creating backup: {backup_path}")
        os.rename(db_path, backup_path)

    # Create new database with models
    print("\n🔨 Creating fresh database...")

    from qventory import create_app, db
    from qventory.models import (
        User, Item, Setting, Sale, Listing,
        MarketplaceCredential, Subscription, PlanLimit
    )

    app = create_app()

    with app.app_context():
        # Create all tables
        db.create_all()
        print("✅ All tables created")

        # Insert default plan limits
        print("\n📋 Creating default plan limits...")

        plans = [
            PlanLimit(
                plan='free',
                max_items=50,
                max_images_per_item=1,
                max_marketplace_integrations=0,
                can_use_ai_research=False,
                can_bulk_operations=False,
                can_export_csv=True,
                can_import_csv=True,
                can_use_analytics=False,
                can_create_listings=False,
                support_level='community'
            ),
            PlanLimit(
                plan='pro',
                max_items=None,  # Unlimited
                max_images_per_item=5,
                max_marketplace_integrations=2,
                can_use_ai_research=True,
                can_bulk_operations=True,
                can_export_csv=True,
                can_import_csv=True,
                can_use_analytics=True,
                can_create_listings=True,
                support_level='email'
            ),
            PlanLimit(
                plan='premium',
                max_items=None,  # Unlimited
                max_images_per_item=10,
                max_marketplace_integrations=10,
                can_use_ai_research=True,
                can_bulk_operations=True,
                can_export_csv=True,
                can_import_csv=True,
                can_use_analytics=True,
                can_create_listings=True,
                support_level='priority'
            )
        ]

        for plan in plans:
            db.session.add(plan)

        db.session.commit()
        print("✅ Plan limits created (free, pro, premium)")

        # List all tables created
        print("\n📊 Tables created:")
        inspector = db.inspect(db.engine)
        for table_name in inspector.get_table_names():
            print(f"  - {table_name}")

        print("\n" + "="*60)
        print("✅ Fresh database created successfully!")
        print("="*60)
        print("\nNext steps:")
        print("1. Restart qventory: sudo systemctl restart qventory")
        print("2. Create a new user account")
        print("3. Start using Qventory!\n")

if __name__ == '__main__':
    main()
