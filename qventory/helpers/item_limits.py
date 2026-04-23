"""Shared helpers for enforcing item limits."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os

from sqlalchemy import text

from qventory.extensions import db

LOGGER = logging.getLogger(__name__)


def _env_positive_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        LOGGER.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default
    if value <= 0:
        LOGGER.warning("Non-positive %s=%r; using default %s", name, raw, default)
        return default
    return value


FREE_PLAN_FALLBACK_MAX_ITEMS = _env_positive_int("FREE_PLAN_FALLBACK_MAX_ITEMS", 100)


@dataclass(frozen=True)
class ItemLimitStatus:
    allowed: bool
    current_count: int
    max_items: int | None
    remaining: int | None
    plan_name: str


def get_item_limit_status(user_id: int, requested: int = 1, *, lock: bool = False) -> ItemLimitStatus:
    """Return the current item-limit state for a user."""
    if requested <= 0:
        requested = 1

    from qventory.models.subscription import PlanLimit, Subscription
    from qventory.models.user import User

    user_query = User.query.filter_by(id=user_id)
    if lock:
        user_query = user_query.with_for_update()
    user = user_query.first()
    if not user:
        return ItemLimitStatus(
            allowed=False,
            current_count=0,
            max_items=0,
            remaining=0,
            plan_name="missing_user",
        )

    if user.is_god_mode:
        return ItemLimitStatus(
            allowed=True,
            current_count=0,
            max_items=None,
            remaining=None,
            plan_name="god",
        )

    subscription = Subscription.query.filter_by(user_id=user_id).first()
    plan_name = (subscription.plan if subscription else user.role) or "free"

    plan_limits = PlanLimit.query.filter_by(plan=plan_name).first()
    if not plan_limits:
        plan_limits = PlanLimit.query.filter_by(plan="free").first()

    max_items = plan_limits.max_items if plan_limits else None
    if plan_name == "free" and max_items is None:
        LOGGER.error(
            "Invalid free-plan limit for user_id=%s; falling back to %s items",
            user_id,
            FREE_PLAN_FALLBACK_MAX_ITEMS,
        )
        max_items = FREE_PLAN_FALLBACK_MAX_ITEMS

    if max_items is None:
        return ItemLimitStatus(
            allowed=True,
            current_count=0,
            max_items=None,
            remaining=None,
            plan_name=plan_name,
        )

    with db.session.no_autoflush:
        current_count = db.session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM items
                WHERE user_id = :user_id
                  AND is_active = true
                  AND COALESCE(inactive_by_user, FALSE) = FALSE
                """
            ),
            {"user_id": user_id},
        ).scalar() or 0

    remaining = max(0, max_items - current_count)
    return ItemLimitStatus(
        allowed=remaining >= requested,
        current_count=current_count,
        max_items=max_items,
        remaining=remaining,
        plan_name=plan_name,
    )


def can_create_item(user_id: int, requested: int = 1, *, lock: bool = False) -> bool:
    """Return True if the user has space for the requested number of items."""
    return get_item_limit_status(user_id, requested=requested, lock=lock).allowed
