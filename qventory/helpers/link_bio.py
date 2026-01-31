import json

from qventory.models.setting import Setting


def remove_featured_items_for_user(user_id, item_ids):
    """
    Remove item IDs from a user's featured list.
    Returns True if an update was made; caller should commit.
    """
    if not item_ids:
        return False

    settings = Setting.query.filter_by(user_id=user_id).first()
    if not settings or not settings.link_bio_featured_json:
        return False

    try:
        featured_ids = json.loads(settings.link_bio_featured_json) or []
    except Exception:
        return False

    try:
        remove_ids = {int(item_id) for item_id in item_ids if item_id is not None}
    except (TypeError, ValueError):
        remove_ids = {item_id for item_id in item_ids if isinstance(item_id, int)}

    if not remove_ids:
        return False

    updated = [item_id for item_id in featured_ids if item_id not in remove_ids]
    if updated == featured_ids:
        return False

    settings.link_bio_featured_json = json.dumps(updated)
    return True
