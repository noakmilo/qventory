from qventory import create_app
from qventory.extensions import db
from qventory.models.subscription import Subscription
from qventory.models.user import User


SKIP_ROLES = {"god", "early_adopter"}


def main():
    app = create_app()
    with app.app_context():
        updated = 0
        skipped = 0

        subscriptions = Subscription.query.all()
        for sub in subscriptions:
            user = User.query.filter_by(id=sub.user_id).first()
            if not user:
                continue
            if user.role in SKIP_ROLES:
                skipped += 1
                continue
            if not sub.plan or sub.plan == "free":
                # No downgrades in this backfill.
                continue
            if sub.plan in SKIP_ROLES:
                continue
            if user.role != sub.plan:
                user.role = sub.plan
                updated += 1

        if updated:
            db.session.commit()
        else:
            db.session.rollback()

        print(f"Backfill complete. Updated: {updated}, Skipped (protected): {skipped}")


if __name__ == "__main__":
    main()
