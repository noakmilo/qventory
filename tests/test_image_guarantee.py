from types import SimpleNamespace

from qventory.helpers.image_guarantee import (
    IMAGE_STATUS_EXHAUSTED,
    IMAGE_STATUS_FAILED,
    IMAGE_STATUS_PENDING,
    IMAGE_STATUS_READY,
    apply_item_image_ready,
    ensure_item_image_pending,
    has_image,
    record_item_image_failure,
)
from qventory.helpers.inventory_queries import SOLD_ITEMS_SQL
from qventory import tasks


def _dummy_item():
    return SimpleNamespace(
        id=123,
        user_id=9,
        item_thumb=None,
        image_status=None,
        image_attempts=0,
        image_next_retry_at=None,
        image_last_error=None,
        image_pending_since=None,
        ebay_listing_id="1234567890",
    )


def test_image_status_ready_and_pending_transitions():
    item = _dummy_item()
    ensure_item_image_pending(item, error="missing")
    assert item.image_status == IMAGE_STATUS_PENDING
    assert item.image_pending_since is not None
    assert "missing" in item.image_last_error

    changed = apply_item_image_ready(item, " https://cdn.example.com/image.jpg ")
    assert changed is True
    assert has_image(item.item_thumb) is True
    assert item.image_status == IMAGE_STATUS_READY
    assert item.image_next_retry_at is None
    assert item.image_last_error is None
    assert item.image_pending_since is None


def test_image_failure_marks_exhausted_after_limit():
    item = _dummy_item()
    record_item_image_failure(item, "boom", attempt=1, max_attempts=3, jitter=0)
    assert item.image_status == IMAGE_STATUS_FAILED
    assert item.image_attempts == 1
    assert item.image_next_retry_at is not None

    record_item_image_failure(item, "boom2", attempt=3, max_attempts=3, jitter=0)
    assert item.image_status == IMAGE_STATUS_EXHAUSTED
    assert item.image_attempts == 3
    assert item.image_next_retry_at is None


def test_queue_item_hydration_enqueues_for_missing_image(monkeypatch):
    queued = []

    class DummyTask:
        @staticmethod
        def apply_async(**kwargs):
            queued.append(kwargs)

    monkeypatch.setattr(tasks, "hydrate_item_image", DummyTask)
    item = _dummy_item()

    did_queue = tasks._queue_item_image_hydration(
        item,
        reason="unit_test_missing_image",
        countdown=0,
        force=False,
    )

    assert did_queue is True
    assert item.image_status == IMAGE_STATUS_PENDING
    assert len(queued) == 1
    assert queued[0]["kwargs"]["item_id"] == item.id
    assert queued[0]["kwargs"]["user_id"] == item.user_id


def test_sold_query_prefers_sale_snapshot_thumb():
    assert "COALESCE(s.sale_item_thumb, i.item_thumb, NULL) AS item_thumb" in SOLD_ITEMS_SQL
