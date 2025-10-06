# 🚨 Emergency Rollback Guide

## Migración Rompió la App

### Síntomas:
- App no arranca después de deploy
- Error 500 en todas las páginas
- Logs muestran: `OperationalError` o `ProgrammingError`

### Solución Rápida (5 minutos):

```bash
ssh root@droplet
cd /opt/qventory/qventory

# 1. Para servicio
sudo systemctl stop qventory

# 2. Encuentra backup más reciente
ls -lt /opt/qventory/backups/app.db.*.bak | head -1

# 3. Restaura backup
cp /opt/qventory/backups/app.db.YYYYMMDD-HHMMSS.bak \
   /opt/qventory/data/app.db

# 4. Revierte migración en código
export FLASK_APP=wsgi:app
source qventory/bin/activate
flask db downgrade  # Revierte última migración

# 5. Reinicia
sudo systemctl start qventory

# 6. Verifica
curl https://qventory.com
sudo journalctl -u qventory -n 50
```

---

## Migración No Se Aplica

### Error: "Can't locate revision"

```bash
# La DB tiene versión que no existe en código

# 1. Resetear tabla alembic_version
sqlite3 /opt/qventory/data/app.db
> DELETE FROM alembic_version;
> .quit

# 2. Marcar como actualizada
flask db stamp head

# 3. Reiniciar
sudo systemctl restart qventory
```

---

## Deploy Falló a Medias

### Git pull funcionó pero migración falló

```bash
# 1. Revertir código
git reset --hard HEAD~1

# 2. Restaurar backup
cp /opt/qventory/backups/app.db.[último].bak \
   /opt/qventory/data/app.db

# 3. Reiniciar
sudo systemctl restart qventory
```

---

## DB Corrupta

### Síntomas:
- `sqlite3.DatabaseError: database disk image is malformed`

```bash
# 1. Para servicio
sudo systemctl stop qventory

# 2. Intenta reparar
sqlite3 /opt/qventory/data/app.db
> PRAGMA integrity_check;
> .quit

# Si falla:
# 3. Restaura backup
cp /opt/qventory/backups/app.db.[último].bak \
   /opt/qventory/data/app.db

# 4. Reinicia
sudo systemctl start qventory
```

---

## Olvidaste Hacer Backup

### Crear backup manual antes de deploy arriesgado:

```bash
cd /opt/qventory/data

# Backup completo (DB + WAL + SHM)
timestamp=$(date +%Y%m%d-%H%M%S)
cp app.db "/opt/qventory/backups/app.db.${timestamp}.manual.bak"
cp app.db-wal "/opt/qventory/backups/app.db.${timestamp}.manual.bak-wal" 2>/dev/null || true
cp app.db-shm "/opt/qventory/backups/app.db.${timestamp}.manual.bak-shm" 2>/dev/null || true

echo "Backup manual creado: app.db.${timestamp}.manual.bak"
```

---

## Migración Generó SQL Incorrecto

### Ver SQL que se va a ejecutar:

```bash
# Generar migración
flask db migrate -m "test"

# Ver archivo generado
cat migrations/versions/[último_archivo].py

# Si está mal, edítalo manualmente:
vim migrations/versions/[último_archivo].py

# O bórralo y regenera:
rm migrations/versions/[último_archivo].py
flask db migrate -m "test corregido"
```

---

## Servicio No Arranca

### Checklist:

```bash
# 1. Ver logs completos
sudo journalctl -u qventory -n 100 --no-pager

# 2. Verificar permisos DB
ls -la /opt/qventory/data/app.db
# Debe ser: -rw-r--r-- root root

# 3. Test import manual
cd /opt/qventory/qventory
source qventory/bin/activate
python -c "from wsgi import app; print('OK')"

# 4. Ver estado servicio
sudo systemctl status qventory

# 5. Reiniciar forzado
sudo systemctl daemon-reload
sudo systemctl restart qventory
```

---

## Listar Todos los Backups

```bash
ls -lth /opt/qventory/backups/
```

Formato: `app.db.YYYYMMDD-HHMMSS.bak`

Ejemplo:
```
app.db.20250106-143000.bak      # 2:30 PM hoy
app.db.20250106-120000.bak      # 12:00 PM hoy
app.db.20250105-180000.bak      # 6:00 PM ayer
```

---

## Restaurar Backup Específico

```bash
# 1. Para servicio
sudo systemctl stop qventory

# 2. Lista backups
ls -lt /opt/qventory/backups/app.db.*.bak

# 3. Copia el que quieras
BACKUP_FILE="/opt/qventory/backups/app.db.20250106-120000.bak"
cp "${BACKUP_FILE}" /opt/qventory/data/app.db
cp "${BACKUP_FILE}-wal" /opt/qventory/data/app.db-wal 2>/dev/null || true
cp "${BACKUP_FILE}-shm" /opt/qventory/data/app.db-shm 2>/dev/null || true

# 4. Reinicia
sudo systemctl start qventory

# 5. Verifica versión de migración
source /opt/qventory/qventory/qventory/bin/activate
export FLASK_APP=wsgi:app
flask db current
```

---

## Resetear Migraciones Completamente (Nuclear Option)

### ⚠️ SOLO SI TODO FALLÓ - Pierdes historial de migraciones

```bash
# 1. Backup completo
cp /opt/qventory/data/app.db /opt/qventory/backups/app.db.NUCLEAR.bak

# 2. Borra carpeta migrations
rm -rf migrations/

# 3. Reinicializa
export FLASK_APP=wsgi:app
flask db init

# 4. Genera migración inicial desde schema actual de DB
flask db migrate -m "reset initial migration"

# 5. Marca como aplicada (no la apliques, ya está en la DB)
flask db stamp head

# 6. Commit
git add migrations/
git commit -m "reset migrations"
git push
```

---

## Contactos de Emergencia

### Logs en tiempo real:
```bash
sudo journalctl -u qventory -f
```

### Estado del sistema:
```bash
sudo systemctl status qventory
df -h  # Espacio en disco
free -h  # Memoria
top  # Procesos
```

### Ver usuarios afectados:
```bash
sqlite3 /opt/qventory/data/app.db
> SELECT count(*) FROM users;
> SELECT count(*) FROM items;
> .quit
```

---

## Prevención

### Antes de deploy arriesgado:

```bash
# 1. Backup manual
./deploy.sh  # Ya incluye backup automático, pero por si acaso:
timestamp=$(date +%Y%m%d-%H%M%S)
cp /opt/qventory/data/app.db \
   "/opt/qventory/backups/app.db.${timestamp}.pre-deploy.bak"

# 2. Test en branch separado
git checkout -b test-migration
# ... hacer cambios ...
./migrate_and_deploy.sh "test"
# Si funciona:
git checkout main
git merge test-migration

# 3. Notificar usuarios
# (si tienes sistema de notificaciones)
```

---

## Recovery Checklist

- [ ] Servicio parado
- [ ] Backup restaurado
- [ ] Migración revertida (si aplica)
- [ ] Código revertido (si aplica)
- [ ] Servicio reiniciado
- [ ] App responde (curl https://qventory.com)
- [ ] Logs limpios (journalctl)
- [ ] Usuarios pueden login
- [ ] Items se muestran correctamente
- [ ] Investigar causa raíz
- [ ] Documentar en GitHub issue
