import os, pathlib

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # DO/Heroku a veces dan postgres://, SQLAlchemy quiere postgresql://
        SQLALCHEMY_DATABASE_URI = db_url.replace("postgres://", "postgresql://")
    else:
        # Fallback local con SQLite (para dev)
        _db_path = os.environ.get("QVENTORY_DB_PATH", "app.db")
        p = pathlib.Path(_db_path)
        if p.is_absolute():
            SQLALCHEMY_DATABASE_URI = f"sqlite:////{p.as_posix().lstrip('/')}"
        else:
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{p.as_posix()}"
