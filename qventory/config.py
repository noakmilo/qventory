# qventory/config.py
import os, pathlib

class Config:
    # Si no está definida en el entorno, usa un fallback seguro en dev
    SECRET_KEY = os.environ.get("SECRET_KEY", "c3f9a4b8e7d12f4a9b6d8c3e5a2f7b1c")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Si Render inyecta QVENTORY_DB_PATH=/var/data/app.db → úsalo
    _db_path = os.environ.get("QVENTORY_DB_PATH")
    if _db_path:
        p = pathlib.Path(_db_path)
        # Ruta absoluta para SQLite: 4 barras después de sqlite:
        SQLALCHEMY_DATABASE_URI = f"sqlite:////{p.as_posix().lstrip('/')}"
    else:
        # Dev local por defecto (archivo en el proyecto)
        SQLALCHEMY_DATABASE_URI = "sqlite:///app.db"
