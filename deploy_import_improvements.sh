#!/bin/bash
# Deploy eBay Import Improvements with Failed Items Tracking

set -e  # Exit on error

echo "=========================================="
echo "eBay Import Improvements Deployment"
echo "=========================================="
echo ""

# Check if running as correct user
if [ "$EUID" -eq 0 ]; then
  echo "❌ ERROR: Do not run this script as root"
  echo "Run as the qventory application user instead"
  exit 1
fi

# Confirm deployment
echo "This will:"
echo "  1. Stop Gunicorn and Celery services"
echo "  2. Pull latest code from git"
echo "  3. Run database migration (add failed_imports table)"
echo "  4. Restart services"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Deployment cancelled"
  exit 0
fi

# Stop services
echo ""
echo "📦 Stopping services..."
sudo systemctl stop gunicorn-qventory
sudo systemctl stop celery-qventory

# Backup database (optional but recommended)
echo ""
echo "💾 Creating database backup..."
BACKUP_DIR="/var/backups/qventory"
BACKUP_FILE="$BACKUP_DIR/db_backup_$(date +%Y%m%d_%H%M%S).sql"
sudo mkdir -p "$BACKUP_DIR"

# Get database connection from environment or .env
if [ -f /var/www/qventory/.env ]; then
  source /var/www/qventory/.env
fi

if [ ! -z "$DATABASE_URL" ]; then
  # Extract database name from DATABASE_URL
  DB_NAME=$(echo $DATABASE_URL | sed 's/.*\/\([^?]*\).*/\1/')
  echo "Backing up database: $DB_NAME"
  sudo -u postgres pg_dump "$DB_NAME" > "$BACKUP_FILE"
  echo "✓ Backup saved to: $BACKUP_FILE"
else
  echo "⚠️  DATABASE_URL not found, skipping backup"
fi

# Navigate to application directory
cd /var/www/qventory

# Pull latest code (if using git)
if [ -d ".git" ]; then
  echo ""
  echo "📥 Pulling latest code..."
  git pull
else
  echo ""
  echo "⚠️  Not a git repository, skipping pull"
fi

# Activate virtual environment
echo ""
echo "🐍 Activating virtual environment..."
source venv/bin/activate

# Install any new dependencies (just in case)
echo ""
echo "📦 Checking dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Run database migration
echo ""
echo "🗄️  Running database migration..."
echo "Migration: 007_add_failed_imports_table"
flask db upgrade

if [ $? -eq 0 ]; then
  echo "✓ Migration completed successfully"
else
  echo "❌ Migration failed!"
  echo "Check logs and fix before restarting services"
  exit 1
fi

# Verify table was created
echo ""
echo "🔍 Verifying failed_imports table..."
if [ ! -z "$DATABASE_URL" ]; then
  TABLE_EXISTS=$(sudo -u postgres psql -d "$DB_NAME" -tAc "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'failed_imports');")
  if [ "$TABLE_EXISTS" = "t" ]; then
    echo "✓ Table 'failed_imports' exists"
  else
    echo "❌ Table 'failed_imports' was not created!"
    exit 1
  fi
fi

# Restart services
echo ""
echo "🚀 Starting services..."
sudo systemctl start gunicorn-qventory
sudo systemctl start celery-qventory

# Wait a moment and check status
sleep 3

echo ""
echo "📊 Service Status:"
sudo systemctl status gunicorn-qventory --no-pager -l | head -10
echo ""
sudo systemctl status celery-qventory --no-pager -l | head -10

# Check if services are running
GUNICORN_STATUS=$(sudo systemctl is-active gunicorn-qventory)
CELERY_STATUS=$(sudo systemctl is-active celery-qventory)

echo ""
echo "=========================================="
if [ "$GUNICORN_STATUS" = "active" ] && [ "$CELERY_STATUS" = "active" ]; then
  echo "✅ Deployment completed successfully!"
  echo ""
  echo "New features available:"
  echo "  • Failed imports are now tracked and stored"
  echo "  • View failed imports at: /import/failed"
  echo "  • Retry failed items individually or all at once"
  echo "  • Import notifications show failure count"
  echo ""
  echo "Next steps:"
  echo "  1. Run an eBay import to test the new functionality"
  echo "  2. Check /import/failed to see if any items failed"
  echo "  3. Monitor logs: sudo journalctl -u celery-qventory -f"
else
  echo "⚠️  Services may not be running correctly"
  echo "Gunicorn: $GUNICORN_STATUS"
  echo "Celery: $CELERY_STATUS"
  echo ""
  echo "Check logs:"
  echo "  sudo journalctl -u gunicorn-qventory -n 50"
  echo "  sudo journalctl -u celery-qventory -n 50"
fi
echo "=========================================="
