# 🔄 Qventory Development Workflow

## Tu Setup: Desarrollo en Droplet

```
Laptop (VS Code)          Droplet (Ubuntu)
     │                         │
     │  1. Editas código       │
     │     models/*.py         │
     │     routes/*.py         │
     │                         │
     │  2. Git push      ─────>│
     │                         │
     │                         │  3. ./deploy.sh
     │                         │     - Git pull
     │                         │     - Genera migración (si no existe)
     │                         │     - Aplica migración
     │                         │     - Reinicia servicio
     │                         │
     │  4. Test            <────│  App actualizada
     │     qventory.com        │
```

---

## 📝 Respuesta a Tu Pregunta

> ¿Tengo que correr la migración localmente antes de commit?

**NO.** Tienes dos opciones:

### Opción 1: Generar en laptop (sin aplicar)
```bash
# Laptop:
./migrate.sh create "add field"  # Solo GENERA archivo
git push

# Droplet:
./deploy.sh  # APLICA migración
```

### Opción 2: Todo en droplet
```bash
# Laptop:
git push  # Solo código

# Droplet:
./migrate_and_deploy.sh "add field"  # Genera + aplica + commit
```

**Clave:** `flask db migrate` solo necesita:
- ✅ Acceso a tus modelos (models/*.py)
- ❌ NO necesita DB local
- ❌ NO necesita aplicar la migración

---

## 🎯 Workflow Recomendado (Tu Caso)

```bash
# === LAPTOP (VS Code) ===

# 1. Modificas código
vim qventory/models/item.py
# Agregas: notes = db.Column(db.Text)

# 2. Commit solo código
git add .
git commit -m "add notes field to item model"
git push

# === DROPLET (SSH) ===

# 3. Un solo comando
ssh root@droplet
cd /opt/qventory/qventory
./migrate_and_deploy.sh "add notes field"

# Esto hace:
# ✅ Git pull
# ✅ flask db migrate (genera migración)
# ✅ Te muestra archivo para revisar
# ✅ Git commit + push (vuelve a GitHub)
# ✅ flask db upgrade (aplica)
# ✅ systemctl restart (reinicia)

# 4. Listo!
# Migración aplicada, servicio corriendo, código en GitHub
```

---

## 🔍 ¿Qué Hace `flask db migrate`?

```python
# NO necesita DB real, solo compara:

# Estado A: Modelos actuales
class Item(db.Model):
    id = db.Column(db.Integer)
    title = db.Column(db.String)
    notes = db.Column(db.Text)  # ← NUEVO

# Estado B: Última migración guardada
# migrations/versions/001_last.py dice:
# - Item tiene: id, title

# Resultado: Genera archivo nuevo
# migrations/versions/002_add_notes.py:
def upgrade():
    op.add_column('items', sa.Column('notes', sa.Text()))
```

**Por eso funciona sin DB local:** Solo lee archivos Python.

---

## 📦 Archivos Importantes

```
qventory/
├── deploy.sh                    # Deploy automático
├── migrate.sh                   # Helper local (opcional)
├── migrate_and_deploy.sh        # Todo-en-uno para droplet
│
├── migrations/                  # ← Versionado en Git
│   ├── versions/
│   │   └── 001_initial.py      # Migraciones
│   └── env.py
│
└── instance/                    # ← NO en Git
    └── app.db                   # Datos de usuarios
```

**Regla:**
- `migrations/` → Git ✅
- `instance/app.db` → NO Git ❌

---

## 🚀 Scripts Disponibles

### En Laptop (opcional):
```bash
./migrate.sh create "mensaje"   # Genera migración
./migrate.sh status              # Ver estado
```

### En Droplet:
```bash
./deploy.sh                      # Deploy completo (pull + migrate + restart)
./migrate_and_deploy.sh "msg"   # Genera + commit + aplica + restart
```

---

## 🎓 Ejemplo Completo

### Escenario: Agregar campo "ebay_sync_enabled"

```bash
# === LAPTOP ===
cd ~/Documents/GitHub/qventory

# Editas modelo
echo 'ebay_sync_enabled = db.Column(db.Boolean, default=True)' >> qventory/models/item.py

# Commit
git add .
git commit -m "add ebay sync toggle"
git push

# === DROPLET ===
ssh root@droplet
cd /opt/qventory/qventory

# Un comando hace todo
./migrate_and_deploy.sh "add ebay sync toggle"

# Salida:
# ==> Generando migración: add ebay sync toggle
# Created migration: 002_add_ebay_sync_toggle.py
#
# ==> Migración generada. Revisa el archivo:
# migrations/versions/002_add_ebay_sync_toggle.py
#
# ¿Se ve correcta la migración? (y/N): y
#
# ==> Commiting migración a Git
# [main abc123] migration: add ebay sync toggle
#
# ¿Hacer push a GitHub? (y/N): y
#
# ==> Aplicando migración a base de datos
# INFO  [alembic.runtime.migration] Running upgrade 001 -> 002
#
# ==> Reiniciando servicio qventory
# ✅ Migración aplicada y servicio reiniciado

# Verificas
curl https://qventory.com  # ✅ App funcionando
```

---

## ✅ Resumen

| Pregunta | Respuesta |
|----------|-----------|
| ¿Necesito DB local? | ❌ No |
| ¿Necesito aplicar migración en laptop? | ❌ No |
| ¿Necesito generar migración en laptop? | 🤷 Opcional (puedes hacerlo en droplet) |
| ¿Qué hace `deploy.sh`? | Git pull + Aplica migraciones + Restart |
| ¿Qué hace `migrate_and_deploy.sh`? | Genera + Commit + Aplica + Restart |
| ¿Se pierden datos? | ❌ Nunca (backups automáticos) |

**Flujo más simple para ti:**
1. Laptop: Edita código → Push
2. Droplet: `./migrate_and_deploy.sh "mensaje"`
3. Listo ✅
