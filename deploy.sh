#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Qventory Production Deploy Script with Flask-Migrate
# ============================================================================
# Este script:
# 1. Hace backup automático de la DB (con -wal y -shm)
# 2. Actualiza código (git pull)
# 3. Instala dependencias
# 4. Aplica migraciones de DB (flask db upgrade)
# 5. Reinicia servicio
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

PERSIST_DIR="/opt/qventory/data"
PERSIST_DB="${PERSIST_DIR}/app.db"
BACKUP_DIR="/opt/qventory/backups"

# === Utilidades ===
timestamp() { date +%Y%m%d-%H%M%S; }
log() { printf "\n==> %s\n" "$*"; }

backup_sqlite_trio() {
  local src="$1" base dst ts
  [ -f "$src" ] || return 0
  ts="$(timestamp)"
  base="$(basename "$src")"
  dst="${BACKUP_DIR}/${base}.${ts}.bak"
  cp -a "$src" "$dst"
  [ -f "${src}-wal" ] && cp -a "${src}-wal" "${dst}-wal" || true
  [ -f "${src}-shm" ] && cp -a "${src}-shm" "${dst}-shm" || true
  log "Backup creado: ${dst}"
}

# === Prechecks ===
mkdir -p "${PERSIST_DIR}" "${BACKUP_DIR}"
git config --global --add safe.directory "${APP_DIR}" || true
mkdir -p ~/.ssh && chmod 700 ~/.ssh
grep -q github.com ~/.ssh/known_hosts 2>/dev/null || ssh-keyscan github.com >> ~/.ssh/known_hosts

# === 1) Backup de DB persistente ===
if [ -f "${PERSIST_DB}" ]; then
  log "Haciendo backup de base de datos"
  backup_sqlite_trio "${PERSIST_DB}"
else
  log "No existe DB persistente todavía (primer deploy)"
fi

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
ls -t app.db.*.bak 2>/dev/null | tail -n +11 | xargs -r rm -f
ls -t app.db.*.bak-wal 2>/dev/null | tail -n +11 | xargs -r rm -f
ls -t app.db.*.bak-shm 2>/dev/null | tail -n +11 | xargs -r rm -f

# === 7) Reiniciar servicio ===
log "Reiniciando servicio ${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

sleep 2

systemctl status "${SERVICE_NAME}" --no-pager -l | sed -n '1,25p'

log "
============================================================================
✅ Deploy completado exitosamente
============================================================================
Backup guardado en: ${BACKUP_DIR}
Base de datos: ${PERSIST_DB}
Migraciones aplicadas: $(${VENV_BIN}/flask db current 2>/dev/null || echo 'N/A')

Para ver logs en vivo:
  sudo journalctl -u ${SERVICE_NAME} -f

Para rollback en caso de emergencia:
  sudo systemctl stop ${SERVICE_NAME}
  cp ${BACKUP_DIR}/app.db.[timestamp].bak ${PERSIST_DB}
  sudo systemctl start ${SERVICE_NAME}
============================================================================
"
