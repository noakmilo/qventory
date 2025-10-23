# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Common commands

- Setup
  - python3 -m venv .venv && source .venv/bin/activate
  - pip install -r requirements.txt
  - cp .env.example .env  # then edit values as needed

- Run the web app (development)
  - python wsgi.py  # loads .env(.local) and starts Flask dev server on :5000

- Run the web app (production-like)
  - gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app

- Database (Flask-Migrate/Alembic)
  - FLASK_APP=wsgi.py flask db upgrade  # apply migrations
  - FLASK_APP=wsgi.py flask db migrate -m "msg"  # generate new migration

- Celery (background workers and scheduler)
  - celery -A qventory.celery_app worker --loglevel=info
  - celery -A qventory.celery_app beat --loglevel=info

- “Tests” in this repo are executable scripts; run them directly
  - Single test: python test_webhook.py http://localhost:5000/webhooks/ebay {{EBAY_CLIENT_SECRET}}
  - Platform notifications: python test_platform_notifications.py
  - Processor simulations: python test_webhook_processors.py
  - Webhook renewal: python test_webhook_renewal.py

Notes
- DATABASE_URL (PostgreSQL) takes precedence over QVENTORY_DB_PATH (SQLite). On first run without DATABASE_URL/QVENTORY_DB_PATH, the app creates an SQLite DB at /opt/qventory/data/app.db and seeds defaults.
- Many features (eBay imports, webhook processing, auto-relist, renewals) require the Celery worker (and optionally Beat) to be running.

## High-level architecture

- App factory and boot
  - qventory/__init__.py defines create_app(), configures SQLAlchemy, Flask-Login, Flask-Migrate, registers blueprints, sets template filters and error handlers, and seeds defaults (plan limits, AI token configs, optional demo data via QVENTORY_SEED_DEMO=1). DB tables are ensured on boot (db.create_all()).
  - wsgi.py loads .env.local or .env (repo root) and exposes app for Gunicorn.

- Web layer (Flask blueprints)
  - qventory/routes/ contains modular blueprints for main UI and features:
    - main.py: dashboard, inventory views with pagination/filters, CSV export/import, fulfillment views, eBay browse helpers, Cloudinary upload API, eBay import/sync endpoints.
    - auth.py, ebay_auth.py, expenses.py, reports.py, auto_relist.py, admin_webhooks.py, webhooks.py (eBay Commerce webhooks), webhooks_platform.py (eBay Trading SOAP/XML platform notifications).
  - templates/ and static/ back the UI; base.html, dashboard*, inventory_list.html, etc.

- Data layer
  - qventory/models/ defines core entities: User, Item, Sale, Listing, Subscription/PlanLimit, MarketplaceCredential, ImportJob, FailedImport, Notification, WebhookEvent/WebhookSubscription, AutoRelistRule/AutoRelistHistory, etc.
  - Flask-SQLAlchemy for ORM; Alembic/Flask-Migrate migrations in migrations/ (alembic.ini, versions/*).

- Background processing (Celery)
  - qventory/celery_app.py configures Celery with Redis broker/backend (REDIS_URL) and Beat schedules.
  - qventory/tasks.py implements tasks:
    - import_ebay_inventory/import_ebay_sales/import_ebay_complete: sync inventory and sales.
    - process_webhook_event/process_platform_notification and topic-specific processors (ITEM_SOLD, ITEM_ENDED, ITEM_OUT_OF_STOCK).
    - auto_relist_offers: scheduled relist engine (supports manual/auto modes and price decrease strategies).
    - renew_expiring_webhooks: daily renewal of expiring eBay subscriptions.
    - retry_failed_imports/rematch_sales_to_items utilities.

- Integrations and helpers
  - qventory/helpers/* contains eBay API clients (inventory, orders, relist, webhooks), scraping utilities, image processing (Cloudinary), email sending, dashboard/inventory queries, OAuth helpers, webhook setup.
  - routes/main.py also wires Cloudinary (CLOUDINARY_* env vars) and some marketplace URL parsing endpoints.

- Configuration and environment
  - qventory/config.py centralizes config: SECRET_KEY, SQLALCHEMY_DATABASE_URI (from DATABASE_URL or QVENTORY_DB_PATH), session/cookie settings, SHIPPO_API_KEY; defaults to SQLite when unset.
  - Key env vars used across the app (see .env.example):
    - Database: DATABASE_URL or QVENTORY_DB_PATH
    - Flask: SECRET_KEY
    - Redis/Celery: REDIS_URL
    - eBay: EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_ENV, WEBHOOK_BASE_URL, EBAY_VERIFICATION_TOKEN
    - Cloudinary: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET, CLOUDINARY_UPLOAD_FOLDER
    - Email: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_FROM_NAME
    - Optional: QVENTORY_SEED_DEMO=1 to create demo user/items

- Data flows (big picture)
  - eBay OAuth → marketplace credentials saved → webhook auto-setup targets /webhooks/ebay (Commerce) and /webhooks/ebay-platform (Trading) → inbound events are stored and processed asynchronously by Celery → inventory/sales updated and notifications created.
  - Scheduled jobs (Beat) keep data fresh: auto relist cadence, webhook renewals, polling for listing changes.
