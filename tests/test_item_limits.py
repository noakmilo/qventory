import sys
from types import ModuleType, SimpleNamespace

if "stripe" not in sys.modules:
    sys.modules["stripe"] = ModuleType("stripe")
if "markdown2" not in sys.modules:
    sys.modules["markdown2"] = ModuleType("markdown2")

from qventory.helpers import item_limits


class _DummyQuery:
    def __init__(self, obj):
        self._obj = obj

    def filter_by(self, **kwargs):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self._obj


class _DummyScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _DummyNoAutoflush:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummySession:
    def __init__(self, count):
        self._count = count
        self.no_autoflush = _DummyNoAutoflush()

    def execute(self, *args, **kwargs):
        return _DummyScalarResult(self._count)


def test_item_limit_status_blocks_at_free_limit(monkeypatch):
    dummy_user = SimpleNamespace(id=1, role="free", is_god_mode=False)
    dummy_subscription = SimpleNamespace(plan="free")
    dummy_plan_limit = SimpleNamespace(max_items=25)

    monkeypatch.setattr(item_limits.db, "session", _DummySession(count=25))
    monkeypatch.setattr("qventory.models.user.User", SimpleNamespace(query=_DummyQuery(dummy_user)))
    monkeypatch.setattr(
        "qventory.models.subscription.Subscription",
        SimpleNamespace(query=_DummyQuery(dummy_subscription)),
    )
    monkeypatch.setattr(
        "qventory.models.subscription.PlanLimit",
        SimpleNamespace(query=_DummyQuery(dummy_plan_limit)),
    )

    status = item_limits.get_item_limit_status(1, lock=True)

    assert status.allowed is False
    assert status.current_count == 25
    assert status.max_items == 25
    assert status.remaining == 0


def test_item_limit_status_allows_god_mode_without_counting(monkeypatch):
    dummy_user = SimpleNamespace(id=2, role="god", is_god_mode=True)

    monkeypatch.setattr(item_limits.db, "session", _DummySession(count=999))
    monkeypatch.setattr("qventory.models.user.User", SimpleNamespace(query=_DummyQuery(dummy_user)))

    status = item_limits.get_item_limit_status(2, lock=True)

    assert status.allowed is True
    assert status.max_items is None
    assert status.remaining is None
