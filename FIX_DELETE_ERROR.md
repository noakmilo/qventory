# 🔧 Fix Receipt Delete Error

## Error que estás viendo:
```
Delete failed: null value in column "receipt_id" of relation "receipt_usage"
violates not-null constraint
```

## Causa:
Las foreign keys de `receipt_usage` no tienen `ON DELETE CASCADE`, entonces cuando intentas borrar un receipt, PostgreSQL intenta poner `receipt_id = NULL` en vez de eliminar los registros relacionados.

## Solución Rápida (3 Opciones):

### 🚀 Opción 1: Script Automático (Recomendado)

En el droplet, ejecuta:
```bash
cd /var/www/qventory
./fix_cascade_quick.sh
```

---

### 💻 Opción 2: SQL Manual

Conecta a PostgreSQL y ejecuta:
```bash
sudo -u postgres psql qventory_db
```

Luego copia y pega esto:
```sql
-- Drop existing constraints
ALTER TABLE receipt_usage DROP CONSTRAINT IF EXISTS receipt_usage_receipt_id_fkey;
ALTER TABLE receipt_usage DROP CONSTRAINT IF EXISTS receipt_usage_user_id_fkey;

-- Recreate with CASCADE
ALTER TABLE receipt_usage
    ADD CONSTRAINT receipt_usage_receipt_id_fkey
    FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE;

ALTER TABLE receipt_usage
    ADD CONSTRAINT receipt_usage_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- Verify (should show CASCADE for both)
SELECT conname, confdeltype FROM pg_constraint
WHERE conname LIKE 'receipt_usage%fkey';

\q
```

---

### 📦 Opción 3: Usar Flask Migration

En el droplet:
```bash
cd /var/www/qventory
source venv/bin/activate
flask db upgrade
sudo systemctl restart qventory
```

---

## ✅ Verificación

Después de aplicar la corrección, intenta eliminar un receipt antiguo. Debería funcionar sin errores.

## 📝 Qué hace el fix:

- **Antes**: Al borrar receipt → intenta poner `receipt_id = NULL` → ❌ ERROR
- **Después**: Al borrar receipt → elimina automáticamente registros de `receipt_usage` → ✅ OK

---

## 🔍 Si sigues teniendo problemas:

Verifica que el constraint se aplicó correctamente:
```bash
sudo -u postgres psql qventory_db -c "SELECT conname, confdeltype FROM pg_constraint WHERE conname LIKE 'receipt_usage%fkey';"
```

Deberías ver:
```
           conname            | confdeltype
------------------------------+-------------
 receipt_usage_receipt_id_fkey | c
 receipt_usage_user_id_fkey    | c
```

La `c` significa CASCADE ✓
