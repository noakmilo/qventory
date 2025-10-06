#!/usr/bin/env bash
# Helper script para crear y aplicar migraciones en desarrollo

set -euo pipefail

export FLASK_APP=wsgi:app

case "${1:-}" in
  create)
    if [ -z "${2:-}" ]; then
      echo "Usage: ./migrate.sh create 'mensaje descriptivo'"
      echo "Example: ./migrate.sh create 'add ebay sync field'"
      exit 1
    fi
    echo "==> Generando migración: $2"
    flask db migrate -m "$2"
    echo "✅ Migración creada en migrations/versions/"
    echo "👀 Revisa el archivo generado antes de aplicar"
    ;;

  apply)
    echo "==> Aplicando migraciones pendientes"
    flask db upgrade
    echo "✅ Migraciones aplicadas"
    ;;

  status)
    echo "==> Estado actual de migraciones"
    flask db current
    ;;

  history)
    echo "==> Historial de migraciones"
    flask db history
    ;;

  rollback)
    echo "⚠️  ROLLBACK: Revertiendo última migración"
    read -p "¿Estás seguro? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
      flask db downgrade
      echo "✅ Rollback completado"
    else
      echo "❌ Cancelado"
    fi
    ;;

  init)
    echo "==> Inicializando Flask-Migrate (solo primera vez)"
    flask db init
    echo "✅ Carpeta migrations/ creada"
    echo "➡️  Ahora ejecuta: ./migrate.sh create 'initial migration'"
    ;;

  *)
    cat <<EOF
🔄 Qventory Migration Helper

Uso:
  ./migrate.sh init                          # Primera vez: inicializar
  ./migrate.sh create "mensaje"              # Generar migración
  ./migrate.sh apply                         # Aplicar migraciones
  ./migrate.sh status                        # Ver estado actual
  ./migrate.sh history                       # Ver todas las migraciones
  ./migrate.sh rollback                      # Revertir última migración

Flujo típico:
  1. Modificas models/*.py (agregas/cambias campos)
  2. ./migrate.sh create "add new field"
  3. Revisa migrations/versions/abc123_*.py
  4. ./migrate.sh apply
  5. Git add/commit/push

EOF
    ;;
esac
