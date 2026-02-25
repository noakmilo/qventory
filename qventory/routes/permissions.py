from functools import wraps
from flask import current_app, jsonify, request, Response
from flask_login import current_user


def require_role(role_name: str):
    """Require a specific role (case-insensitive). Returns 403 JSON or plain response."""
    role_name = (role_name or "").strip().lower()

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return _forbidden("unauthorized")
            if (current_user.role or "").strip().lower() != role_name:
                return _forbidden("forbidden")
            return f(*args, **kwargs)

        return wrapper

    return decorator


def require_feature_flag(flag_key: str):
    """Require a feature flag to be enabled; returns 403 when disabled."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if flag_key == "FEATURE_EBAY_LISTING_CREATE_ENABLED":
                from qventory.models.system_setting import SystemSetting
                enabled = SystemSetting.get_int("feature_ebay_listing_create_enabled", None)
                if enabled is None:
                    enabled = 1 if current_app.config.get(flag_key, False) else 0
                if not enabled:
                    return _forbidden("feature_disabled")
                return f(*args, **kwargs)
            if not current_app.config.get(flag_key, False):
                return _forbidden("feature_disabled")
            return f(*args, **kwargs)

        return wrapper

    return decorator


def _forbidden(reason: str):
    if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
        return jsonify({"ok": False, "error": reason}), 403
    return Response("Forbidden", status=403)


def require_plan_feature(feature_name: str):
    """Require plan-level feature flag (PlanLimit)."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return _forbidden("unauthorized")
            try:
                limits = current_user.get_plan_limits()
                allowed = bool(getattr(limits, f"can_{feature_name}", False))
            except Exception:
                allowed = False
            if not allowed:
                return _forbidden("forbidden")
            return f(*args, **kwargs)

        return wrapper

    return decorator
