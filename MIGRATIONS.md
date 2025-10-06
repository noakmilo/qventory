# Flask-Migrate en Qventory

## 🎯 ¿Qué es Flask-Migrate?

Flask-Migrate es un sistema de **versionado de base de datos**. Funciona como Git para tu schema:

- **Git** versiona tu código
- **Flask-Migrate** versiona tu estructura de base de datos

## 📦 ¿Por qué lo necesitamos?

### Antes (sin migraciones):
```
1. Agregas campo ebay_listing_id al modelo Item
2. Git push
3. En producción: OperationalError: no such column
4. Solución: Borrar app.db y recrear
5. ❌ PIERDES TODOS LOS DATOS DE USUARIOS
```

### Ahora (con migraciones):
```
1. Agregas campo ebay_listing_id al modelo Item
2. flask db migrate -m "add ebay_listing_id"
3. Git add migrations/ && git commit && git push
4. En producción: deploy.sh ejecuta flask db upgrade
5. ✅ Campo agregado, datos de usuarios intactos
```

## 🚀 Workflow Para Qventory (Desarrollo en Droplet)

### ⚠️ TU CASO: No corres la app localmente

Ya que solo desarrollas en el droplet, tienes **dos opciones**:

---

### ✅ OPCIÓN A: Generar migración en laptop (RECOMENDADO)

```bash
# === EN LAPTOP ===
# 1. Modificas código
code qventory/models/item.py  # Agregas campo

# 2. Generas migración (sin aplicarla)
./migrate.sh create "add notes field"
# → Crea migrations/versions/abc123_*.py
# → NO necesitas aplicarla (no tienes DB local)

# 3. Commit y push
git add migrations/ models/
git commit -m "migration: add notes field"
git push

# === EN DROPLET ===
# 4. Deploy automático
./deploy.sh
# → Aplica migración automáticamente
# → Reinicia servicio
```

**Ventajas:**
- ✅ Migración versionada desde el inicio
- ✅ Un solo comando en droplet
- ✅ Historial limpio en Git

---

### ✅ OPCIÓN B: Todo en droplet

```bash
# === EN LAPTOP ===
# Solo modificas código, NO generas migración
git add models/ routes/
git commit -m "add notes field to model"
git push

# === EN DROPLET ===
# Un solo comando hace todo
./migrate_and_deploy.sh "add notes field"
# → Genera migración
# → Te muestra el archivo para revisar
# → Commit y push automático
# → Aplica migración
# → Reinicia servicio
```

**Ventajas:**
- ✅ Un solo comando
- ✅ Validación interactiva
- ✅ No necesitas Python en laptop

---

### Primera vez (solo una vez):
```bash
# En droplet:
cd /opt/qventory/qventory
export FLASK_APP=wsgi:app
flask db init  # Crea carpeta migrations/
git add migrations/ && git commit -m "init flask-migrate" && git push
```

### Comandos útiles:
```bash
flask db current   # Ver migración actual
flask db history   # Ver todas las migraciones
flask db downgrade # Revertir última migración
```

## 🏭 En Producción (Automático)

El script `deploy.sh` hace TODO automáticamente:

1. Para servicio
2. **Backup de app.db** (con timestamp)
3. Git pull (trae nuevas migraciones)
4. `flask db upgrade` (aplica migraciones pendientes)
5. Reinicia servicio

**NO necesitas hacer nada manualmente** en el droplet.

## 📁 Estructura de Archivos

```
qventory/
├── migrations/              # ← Versión controlada en Git
│   ├── versions/
│   │   ├── 001_initial.py
│   │   ├── 002_add_ebay_fields.py
│   │   └── 003_add_notes.py
│   ├── alembic.ini
│   └── env.py
├── instance/
│   └── app.db             # ← NO en Git (datos de usuarios)
└── deploy.sh              # ← Aplica migraciones automáticamente
```

## ⚠️ Casos Especiales

### Migración falla en producción:

```bash
# 1. Ver error
sudo journalctl -u qventory -n 50

# 2. Rollback con backup
sudo systemctl stop qventory
cp /opt/qventory/backups/app.db.YYYYMMDD-HHMMSS.bak /opt/qventory/data/app.db
sudo systemctl start qventory

# 3. Investigar y corregir migración
# 4. Re-deploy
```

### Migración conflictiva (dos ramas):

```bash
# Si dos personas crean migraciones en paralelo
flask db merge heads  # Fusiona branches de migración
```

## 🎓 Flujo Completo Ejemplo

### Escenario: Agregar campo "ebay_sync_enabled"

#### En desarrollo:
```bash
# 1. Modificar modelo
# qventory/models/item.py
class Item(db.Model):
    # ... campos existentes ...
    ebay_sync_enabled = db.Column(db.Boolean, default=True)

# 2. Generar migración
flask db migrate -m "add ebay_sync_enabled to item"

# 3. Revisar archivo generado
cat migrations/versions/abc123_add_ebay_sync_enabled_to_item.py
# → Verifica que el SQL sea correcto

# 4. Aplicar localmente
flask db upgrade

# 5. Probar que funciona
flask shell
>>> from qventory.models import Item
>>> Item.query.first().ebay_sync_enabled
True

# 6. Commit y push
git add migrations/
git commit -m "feat: add ebay sync toggle per item"
git push
```

#### En producción (automático):
```bash
ssh root@your-droplet
cd /opt/qventory/qventory
./deploy.sh

# El script automáticamente:
# ✅ Backup app.db
# ✅ Git pull (trae migración)
# ✅ flask db upgrade (aplica migración)
# ✅ Reinicia servicio
```

## 🔒 Seguridad de Datos

### Backups automáticos:
Cada deploy crea backup timestamped:
```
/opt/qventory/backups/
├── app.db.20250106-143022.bak
├── app.db.20250106-143022.bak-wal
└── app.db.20250106-143022.bak-shm
```

Se mantienen **últimos 10 backups** automáticamente.

### En caso de desastre:
```bash
# Restaurar backup más reciente
cd /opt/qventory/backups
ls -lt app.db.*.bak | head -1  # Ver más reciente
sudo systemctl stop qventory
cp app.db.20250106-143022.bak /opt/qventory/data/app.db
sudo systemctl start qventory
```

## 📚 Recursos

- [Flask-Migrate Docs](https://flask-migrate.readthedocs.io/)
- [Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- Cualquier duda: revisa `deploy.sh` línea 63-72
