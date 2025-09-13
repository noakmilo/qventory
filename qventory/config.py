import os, pathlib
class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    _db_path = os.environ.get("QVENTORY_DB_PATH")
    if _db_path:
        p = pathlib.Path(_db_path)
        SQLALCHEMY_DATABASE_URI = f"sqlite:////{p.as_posix().lstrip('/')}"
    else:
        SQLALCHEMY_DATABASE_URI = "sqlite:///app.db"
