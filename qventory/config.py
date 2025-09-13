# qventory/config.py
import os, pathlib

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "c3f9a4b8e7d12f4a9b6d8c3e5a2f7b1c")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Permite override por disco persistente (Render)
    # Ej: QVENTORY_DB_PATH=/var/data/app.db
    _db_path = os.environ.get("QVENTORY_DB_PATH")
    if _db_path:
        p = pathlib.Path(_db_path)
        # Para SQLAlchemy con ruta absoluta se requieren 4 barras: sqlite:////abs/path
        SQLALCHEMY_DATABASE_URI = f"sqlite:////{p.as_posix().lstrip('/')}"
    else:
        # dev: archivo local en el directorio del proyecto
        SQLALCHEMY_DATABASE_URI = "sqlite:///app.db"
