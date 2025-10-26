"""
Seed Plan Limits
Initialize or update plan limits in database
"""
from qventory.extensions import db
from qventory.models.subscription import PlanLimit


def seed_plan_limits():
    """
    Create or update plan limits with default values
    Called automatically on app startup
    """
    # Check if the table has the new columns (migration might not have run yet)
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)

    try:
        columns = [col['name'] for col in inspector.get_columns('plan_limits')]
    except Exception as e:
        print(f"Warning: Could not inspect plan_limits table: {e}")
        return

    # Skip receipt OCR fields if they don't exist yet (pre-migration)
    has_receipt_limits = 'max_receipt_ocr_per_month' in columns

    plans_config = [
        {
            'plan': 'free',
            'max_items': 100,
            'max_images_per_item': 1,
            'max_marketplace_integrations': 1,
            'can_use_ai_research': False,
            'can_bulk_operations': False,
            'can_export_csv': True,
            'can_import_csv': True,
            'can_use_analytics': False,
            'can_create_listings': False,
            'support_level': 'community'
        },
        {
            'plan': 'early_adopter',
            'max_items': 200,
            'max_images_per_item': 3,
            'max_marketplace_integrations': 2,
            'can_use_ai_research': True,
            'can_bulk_operations': True,
            'can_export_csv': True,
            'can_import_csv': True,
            'can_use_analytics': True,
            'can_create_listings': True,
            'support_level': 'email'
        },
        {
            'plan': 'premium',
            'max_items': 500,
            'max_images_per_item': 5,
            'max_marketplace_integrations': 3,
            'can_use_ai_research': True,
            'can_bulk_operations': True,
            'can_export_csv': True,
            'can_import_csv': True,
            'can_use_analytics': True,
            'can_create_listings': True,
            'support_level': 'email'
        },
        {
            'plan': 'pro',
            'max_items': None,  # Unlimited
            'max_images_per_item': 10,
            'max_marketplace_integrations': 10,
            'can_use_ai_research': True,
            'can_bulk_operations': True,
            'can_export_csv': True,
            'can_import_csv': True,
            'can_use_analytics': True,
            'can_create_listings': True,
            'support_level': 'priority'
        },
        {
            'plan': 'god',
            'max_items': None,  # Unlimited (bypassed in code anyway)
            'max_images_per_item': 999,
            'max_marketplace_integrations': 999,
            'can_use_ai_research': True,
            'can_bulk_operations': True,
            'can_export_csv': True,
            'can_import_csv': True,
            'can_use_analytics': True,
            'can_create_listings': True,
            'support_level': 'priority'
        }
    ]

    # Add receipt OCR limits if the columns exist
    if has_receipt_limits:
        plans_config[0]['max_receipt_ocr_per_month'] = None
        plans_config[0]['max_receipt_ocr_per_day'] = 1  # free: 1/day

        plans_config[1]['max_receipt_ocr_per_month'] = 10  # early_adopter: 10/month
        plans_config[1]['max_receipt_ocr_per_day'] = None

        plans_config[2]['max_receipt_ocr_per_month'] = 50  # premium: 50/month
        plans_config[2]['max_receipt_ocr_per_day'] = None

        plans_config[3]['max_receipt_ocr_per_month'] = 200  # pro: 200/month
        plans_config[3]['max_receipt_ocr_per_day'] = None

        plans_config[4]['max_receipt_ocr_per_month'] = None  # god: unlimited
        plans_config[4]['max_receipt_ocr_per_day'] = None

    for plan_data in plans_config:
        plan_name = plan_data['plan']

        # Use raw SQL to avoid SQLAlchemy trying to select non-existent columns
        try:
            result = db.session.execute(
                text("SELECT id FROM plan_limits WHERE plan = :plan"),
                {"plan": plan_name}
            ).fetchone()

            if result:
                # Plan exists - update using raw SQL to avoid column issues
                plan_id = result[0]

                # Build UPDATE statement dynamically based on available columns
                update_parts = []
                update_values = {"plan_id": plan_id}

                for key, value in plan_data.items():
                    if key == 'plan':
                        continue
                    if key in columns:  # Only update if column exists
                        update_parts.append(f"{key} = :{key}")
                        update_values[key] = value

                if update_parts:
                    update_sql = f"UPDATE plan_limits SET {', '.join(update_parts)} WHERE id = :plan_id"
                    db.session.execute(text(update_sql), update_values)
                    print(f"Updated plan limits for: {plan_name}")
                else:
                    print(f"Preserved custom plan limits for: {plan_name}")
            else:
                # Create new plan - only include columns that exist
                insert_cols = []
                insert_vals = []
                insert_placeholders = []
                insert_values = {}

                for key, value in plan_data.items():
                    if key in columns:
                        insert_cols.append(key)
                        insert_placeholders.append(f":{key}")
                        insert_values[key] = value

                if insert_cols:
                    insert_sql = f"INSERT INTO plan_limits ({', '.join(insert_cols)}) VALUES ({', '.join(insert_placeholders)})"
                    db.session.execute(text(insert_sql), insert_values)
                    print(f"Created plan limits for: {plan_name}")

        except Exception as e:
            print(f"Error processing plan {plan_name}: {e}")
            continue

    try:
        db.session.commit()
        print("✅ Plan limits seeded successfully")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error seeding plan limits: {e}")
