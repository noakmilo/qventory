#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Qventory Production Deploy Script with Flask-Migrate + PostgreSQL
# ============================================================================
# Este script:
# 1. Hace backup automático de PostgreSQL (pg_dump)
# 2. Actualiza código (git pull)
# 3. Instala dependencias
# 4. Aplica migraciones de DB (flask db upgrade)
# 5. Reinicia servicios
#
# IMPORTANTE: Con Flask-Migrate, la DB NO se mueve ni restaura.
#             La DB persistente ES la fuente de verdad.
#             Las migraciones actualizan el schema sin perder datos.
#             El servicio NO se para durante el deploy para evitar downtime.
# ============================================================================

# === Ajustes de tu entorno ===
APP_DIR="/opt/qventory/qventory"
VENV_BIN="/opt/qventory/qventory/qventory/bin"
SERVICE_NAME="qventory"

# PostgreSQL settings
PG_DATABASE="qventory_db"
PG_USER="qventory_user"
BACKUP_DIR="/opt/qventory/backups"

# === Utilidades ===
timestamp() { date +%Y%m%d-%H%M%S; }
log() { printf "\n==> %s\n" "$*"; }

backup_postgresql() {
  local ts dst
  ts="$(timestamp)"
  dst="${BACKUP_DIR}/qventory_db_${ts}.sql"

  log "Haciendo backup de PostgreSQL: ${PG_DATABASE}"
  sudo -u postgres pg_dump "${PG_DATABASE}" > "${dst}"

  # Comprimir backup para ahorrar espacio
  gzip "${dst}"
  log "Backup creado: ${dst}.gz"
}

# === Prechecks ===
mkdir -p "${BACKUP_DIR}"
git config --global --add safe.directory "${APP_DIR}" || true
mkdir -p ~/.ssh && chmod 700 ~/.ssh
grep -q github.com ~/.ssh/known_hosts 2>/dev/null || ssh-keyscan github.com >> ~/.ssh/known_hosts

# === 1) Backup de PostgreSQL ===
log "Creando backup de base de datos PostgreSQL"
backup_postgresql

# === 2) Actualizar código ===
cd "${APP_DIR}"

# Fuerza remoto a HTTPS público
CURRENT_URL="$(git remote get-url origin || true)"
if echo "${CURRENT_URL}" | grep -qE '^git@github\.com:'; then
  log "Cambiando remoto SSH → HTTPS"
  git remote set-url origin "https://github.com/noakmilo/qventory.git"
fi

log "git fetch --all"
git fetch --all --prune

# Detecta rama upstream
UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
if [ -z "${UPSTREAM}" ]; then
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    UPSTREAM="origin/main"
  else
    UPSTREAM="origin/master"
  fi
fi

log "git reset --hard ${UPSTREAM}"
git reset --hard "${UPSTREAM}"

# === 3) Actualizar dependencias ===
log "Actualizando pip y requirements"
"${VENV_BIN}/pip" install --upgrade pip
[ -f "${APP_DIR}/requirements.txt" ] && "${VENV_BIN}/pip" install -r "${APP_DIR}/requirements.txt"

# === 4) Aplicar migraciones de base de datos ===
log "Aplicando migraciones de base de datos"

# Exportar FLASK_APP para que flask db funcione
export FLASK_APP=wsgi:app

# Verificar si existe carpeta migrations/
if [ ! -d "${APP_DIR}/migrations" ]; then
  log "Primera vez: inicializando Flask-Migrate"
  "${VENV_BIN}/flask" db init
  log "Generando migración inicial desde modelos actuales"
  "${VENV_BIN}/flask" db migrate -m "initial migration"
fi

# Aplicar migraciones pendientes
log "Ejecutando: flask db upgrade"
"${VENV_BIN}/flask" db upgrade

log "✅ Migraciones aplicadas exitosamente"

# === 5) Chequeo de import ===
log "Verificando que la aplicación importa correctamente"
"${VENV_BIN}/python" - <<'PY'
import importlib
m = importlib.import_module("wsgi")
assert hasattr(m, "app"), "No encuentro 'app' en wsgi.py"
print("✅ wsgi:app importable")
PY

# === 6) Limpiar backups antiguos (mantener últimos 10) ===
log "Limpiando backups antiguos (manteniendo últimos 10)"
cd "${BACKUP_DIR}"
ls -t qventory_db_*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm -f

# === 7) Reiniciar servicios ===
log "Reiniciando servicio ${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

log "Reiniciando Celery worker"
systemctl restart celery-qventory || log "⚠️  Celery no instalado o no configurado"

sleep 2

systemctl status "${SERVICE_NAME}" --no-pager -l | sed -n '1,25p'

log "Estado de Celery:"
systemctl status celery-qventory --no-pager -l | sed -n '1,15p' || echo "Celery worker no configurado"

log "
============================================================================
✅ Deploy completado exitosamente
============================================================================
Backup guardado en: ${BACKUP_DIR}
Base de datos: PostgreSQL - ${PG_DATABASE}
Migraciones aplicadas: $(${VENV_BIN}/flask db current 2>/dev/null || echo 'N/A')

Para ver logs en vivo:
  sudo journalctl -u ${SERVICE_NAME} -f

Para rollback de base de datos en caso de emergencia:
  # Listar backups disponibles:
  ls -lth ${BACKUP_DIR}/qventory_db_*.sql.gz | head -5

  # Restaurar backup (reemplaza TIMESTAMP con la fecha del backup):
  gunzip -c ${BACKUP_DIR}/qventory_db_TIMESTAMP.sql.gz | sudo -u postgres psql ${PG_DATABASE}

  # Reiniciar servicios:
  sudo systemctl restart ${SERVICE_NAME}
  sudo systemctl restart celery-qventory
============================================================================
"
