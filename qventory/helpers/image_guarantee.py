from datetime import datetime, timedelta

IMAGE_STATUS_PENDING = "pending"
IMAGE_STATUS_READY = "ready"
IMAGE_STATUS_FAILED = "failed"
IMAGE_STATUS_EXHAUSTED = "exhausted"

DEFAULT_RETRY_SCHEDULE = (0, 60, 300, 900, 3600, 21600, 86400)


def normalize_image_url(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"none", "null"}:
        return None
    return text


def has_image(value):
    return bool(normalize_image_url(value))


def next_retry_seconds(attempt, schedule=None, jitter=0):
    retry_schedule = schedule or DEFAULT_RETRY_SCHEDULE
    idx = max(0, min(int(attempt), len(retry_schedule) - 1))
    base = int(retry_schedule[idx])
    return base + max(0, int(jitter))


def apply_item_image_ready(item, image_url):
    normalized = normalize_image_url(image_url)
    if not normalized:
        return False

    changed = normalize_image_url(getattr(item, "item_thumb", None)) != normalized
    item.item_thumb = normalized
    item.image_status = IMAGE_STATUS_READY
    item.image_last_error = None
    item.image_next_retry_at = None
    item.image_pending_since = None
    if getattr(item, "image_attempts", None) is None:
        item.image_attempts = 0
    return changed


def ensure_item_image_pending(item, error=None, now=None):
    if has_image(getattr(item, "item_thumb", None)):
        apply_item_image_ready(item, item.item_thumb)
        return

    ts = now or datetime.utcnow()
    item.image_status = IMAGE_STATUS_PENDING
    if not getattr(item, "image_pending_since", None):
        item.image_pending_since = ts
    if error:
        item.image_last_error = str(error)[:2000]


def record_item_image_failure(
    item,
    error,
    attempt,
    *,
    max_attempts=8,
    now=None,
    retry_schedule=None,
    jitter=0
):
    ts = now or datetime.utcnow()
    attempt_num = max(1, int(attempt))

    item.image_attempts = attempt_num
    if not getattr(item, "image_pending_since", None):
        item.image_pending_since = ts
    if error:
        item.image_last_error = str(error)[:2000]

    if attempt_num >= int(max_attempts):
        item.image_status = IMAGE_STATUS_EXHAUSTED
        item.image_next_retry_at = None
        return

    item.image_status = IMAGE_STATUS_FAILED
    delay_seconds = next_retry_seconds(attempt_num, schedule=retry_schedule, jitter=jitter)
    item.image_next_retry_at = ts + timedelta(seconds=delay_seconds)
