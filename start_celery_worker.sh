#!/usr/bin/env bash
#
# Start Celery Worker for Qventory
# This script starts the background task worker
#

set -e

# Navigate to app directory
cd "$(dirname "$0")"

# Activate virtual environment
source ../venv/bin/activate

# Set Flask app
export FLASK_APP=wsgi:app

# Start Celery worker
echo "Starting Celery worker..."
celery -A qventory.celery_app worker \
  --loglevel=info \
  --concurrency=2 \
  --max-tasks-per-child=50 \
  --logfile=/opt/qventory/logs/celery.log \
  --pidfile=/opt/qventory/run/celery.pid
