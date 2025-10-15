from flask import Blueprint

main_bp = Blueprint("main", __name__)
auth_bp = Blueprint("auth", __name__)

from . import main, auth  # noqa: E402,F401

# Import auto_relist blueprint
from .auto_relist import auto_relist_bp  # noqa: E402,F401
