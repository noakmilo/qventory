# Fix Migration 020 - Tablas ya existen

## Problema
Las tablas `receipts` y `receipt_items` ya existen en la base de datos, pero la migración no está marcada como aplicada.

## Solución Rápida

Ejecutar en el servidor de producción:

```bash
# 1. Conectarse a la base de datos
sudo -u postgres psql qventory_db

# 2. Verificar que las tablas existen
\dt receipts
\dt receipt_items

# 3. Verificar qué migración está aplicada actualmente
SELECT * FROM alembic_version;

# 4. Marcar la migración 020 como aplicada SIN ejecutarla
UPDATE alembic_version SET version_num = '020_add_receipts';

# 5. Verificar
SELECT * FROM alembic_version;

# 6. Salir
\q
```

## Alternativa: Si las tablas NO tienen la estructura correcta

Si las tablas existen pero están incompletas:

```bash
# 1. Eliminar las tablas existentes
sudo -u postgres psql qventory_db -c "DROP TABLE IF EXISTS receipt_items CASCADE;"
sudo -u postgres psql qventory_db -c "DROP TABLE IF EXISTS receipts CASCADE;"

# 2. Ejecutar la migración normalmente
cd /opt/qventory/qventory
source qventory/bin/activate
export FLASK_APP=wsgi:app
flask db upgrade
```

## Verificación Final

```bash
# Verificar que las tablas existen con la estructura correcta
sudo -u postgres psql qventory_db -c "\d receipts"
sudo -u postgres psql qventory_db -c "\d receipt_items"

# Verificar migración aplicada
sudo -u postgres psql qventory_db -c "SELECT * FROM alembic_version;"
```

## Después de Aplicar el Fix

```bash
# Reiniciar servicios
sudo systemctl restart qventory
sudo systemctl restart celery-qventory

# Verificar que funciona
curl -I https://tu-dominio.com/receipts/upload
```
