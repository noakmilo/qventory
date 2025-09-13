# Qventory

Flask app with modular structure (blueprints, models, helpers) for QR-based inventory locations with flexible A/B/S/C hierarchy and multi-marketplace links. Includes Auth (register with email validation + confirm password, login/logout).

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export FLASK_APP=wsgi.py
export SECRET_KEY='change-me'  # in production set a strong key
python wsgi.py
# open http://127.0.0.1:5000
```
First time will auto-create `app.db` and seed sample items.
