import os, pathlib
class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Support both PostgreSQL (DATABASE_URL) and SQLite (QVENTORY_DB_PATH)
    # PostgreSQL takes priority if both are set
    _database_url = os.environ.get("DATABASE_URL")
    _db_path = os.environ.get("QVENTORY_DB_PATH")

    if _database_url:
        # Use PostgreSQL or other database URL
        SQLALCHEMY_DATABASE_URI = _database_url
    elif _db_path:
        # Use SQLite with custom path
        p = pathlib.Path(_db_path)
        SQLALCHEMY_DATABASE_URI = f"sqlite:////{p.as_posix().lstrip('/')}"
    else:
        # Default to SQLite
        SQLALCHEMY_DATABASE_URI = "sqlite:////opt/qventory/data/app.db"

