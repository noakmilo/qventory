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

    for plan_data in plans_config:
        plan_name = plan_data['plan']
        existing = PlanLimit.query.filter_by(plan=plan_name).first()

        if existing:
            # Update existing plan limits
            for key, value in plan_data.items():
                if key != 'plan':  # Don't update the plan name itself
                    setattr(existing, key, value)
            print(f"Updated plan limits for: {plan_name}")
        else:
            # Create new plan
            new_plan = PlanLimit(**plan_data)
            db.session.add(new_plan)
            print(f"Created plan limits for: {plan_name}")

    db.session.commit()
    print("✅ Plan limits seeded successfully")
