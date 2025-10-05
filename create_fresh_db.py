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
        MarketplaceCredential, Subscription, PlanLimit,
        Report, AITokenConfig, AITokenUsage
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

        # Initialize AI Token configs
        print("\n🤖 Creating AI Token configurations...")

        AITokenConfig.initialize_defaults()
        print("✅ AI Token configs created:")

        configs = AITokenConfig.query.all()
        for config in configs:
            print(f"  - {config.role}: {config.daily_tokens} tokens/day ({config.display_name})")

        # Create a sample god mode user (optional)
        print("\n👤 Creating sample god mode user...")
        god_user = User(
            username='admin',
            email='admin@qventory.com',
            role='god'
        )
        god_user.set_password('admin123')  # CHANGE THIS IN PRODUCTION!
        db.session.add(god_user)
        db.session.flush()  # Get the user ID

        # Create default subscription for god user
        god_subscription = Subscription(
            user_id=god_user.id,
            plan='premium',
            status='active'
        )
        db.session.add(god_subscription)

        # Create default setting for god user
        god_setting = Setting(user_id=god_user.id)
        db.session.add(god_setting)

        db.session.commit()
        print("✅ God mode user created: admin@qventory.com / admin123")
        print("   ⚠️  CHANGE PASSWORD IN PRODUCTION!")

        # List all tables created
        print("\n📊 Tables created:")
        inspector = db.inspect(db.engine)
        for table_name in sorted(inspector.get_table_names()):
            print(f"  - {table_name}")

        print("\n" + "="*60)
        print("✅ Fresh database created successfully!")
        print("="*60)
        print("\nNext steps:")
        print("1. Restart qventory: sudo systemctl restart qventory")
        print("2. Login with admin@qventory.com / admin123")
        print("3. Change admin password immediately!")
        print("4. Create regular user accounts")
        print("5. Start using Qventory!\n")

if __name__ == '__main__':
    main()
