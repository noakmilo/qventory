#!/usr/bin/env bash
# Script para droplet: Genera migración, commit, aplica, y reinicia
# Uso: ./migrate_and_deploy.sh "mensaje de migración"

set -euo pipefail

VENV_BIN="/opt/qventory/qventory/qventory/bin"
SERVICE_NAME="qventory"

export FLASK_APP=wsgi:app

if [ -z "${1:-}" ]; then
  echo "❌ Error: Proporciona un mensaje para la migración"
  echo "Uso: $0 'add new field to item'"
  exit 1
fi

MIGRATION_MSG="$1"

echo "==> Generando migración: ${MIGRATION_MSG}"
"${VENV_BIN}/flask" db migrate -m "${MIGRATION_MSG}"

echo ""
echo "==> Migración generada. Revisa el archivo:"
ls -t migrations/versions/*.py | head -1

echo ""
read -p "¿Se ve correcta la migración? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "❌ Cancelado. Puedes editar manualmente o borrar:"
  ls -t migrations/versions/*.py | head -1
  exit 1
fi

echo ""
echo "==> Commiting migración a Git"
git add migrations/
git commit -m "migration: ${MIGRATION_MSG}"

echo ""
read -p "¿Hacer push a GitHub? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  git push
  echo "✅ Pushed to GitHub"
fi

echo ""
echo "==> Aplicando migración a base de datos"
"${VENV_BIN}/flask" db upgrade

echo ""
echo "==> Reiniciando servicio ${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

sleep 2
systemctl status "${SERVICE_NAME}" --no-pager -l | head -20

echo ""
echo "============================================"
echo "✅ Migración aplicada y servicio reiniciado"
echo "============================================"
echo "Migración: ${MIGRATION_MSG}"
echo "Archivo: $(ls -t migrations/versions/*.py | head -1)"
echo ""
echo "Para verificar en la app:"
echo "  curl -I https://qventory.com"
echo ""
echo "Para ver logs:"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
echo "============================================"
