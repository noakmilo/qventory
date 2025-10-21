# Verificación de Fixes de eBay - Guía de Monitoreo

## Cambios Desplegados

### 1. Fix de Token Encriptado (CRÍTICO)
- **Archivo**: `qventory/helpers/webhook_auto_setup.py`
- **Líneas**: 230, 304
- **Problema resuelto**: eBay ahora recibe el token desencriptado correctamente
- **Impacto**: Platform Notifications ahora deben registrarse exitosamente

### 2. Limpieza de Suscripciones al Desconectar
- **Archivo**: `qventory/routes/ebay_auth.py`
- **Líneas**: 244-311
- **Problema resuelto**: Las suscripciones se eliminan de eBay antes de desconectar
- **Impacto**: No más webhooks duplicados al reconectar

---

## Plan de Verificación en Producción

### Paso 1: Verificar Servicios Activos

```bash
# Ver estado de servicios
sudo systemctl status qventory
sudo systemctl status celery-qventory
sudo systemctl status celerybeat-qventory

# Verificar últimas líneas de log para errores
sudo journalctl -u qventory -n 50 --no-pager
```

**Resultado esperado**: Todos los servicios en estado "active (running)", sin errores críticos.

---

### Paso 2: Monitorear Logs en Tiempo Real

```bash
# Terminal 1: Monitorear eventos de eBay
sudo journalctl -u qventory -f | grep -E "EBAY|WEBHOOK|Platform"

# Terminal 2 (opcional): Monitorear todos los logs
sudo journalctl -u qventory -f
```

---

### Paso 3: Probar Desconexión de Cuenta eBay

**Desde la UI:**
1. Ir a Settings → eBay
2. Click en "Disconnect eBay Account"

**Verificar en logs:**
```bash
sudo journalctl -u qventory -f | grep -E "DISCONNECT|subscription|webhook"
```

**Resultados esperados en logs:**
```
[EBAY_AUTH] === DISCONNECT ROUTE CALLED ===
[EBAY_AUTH] User: <user_id> (<username>)
[EBAY_AUTH] Found credential ID: <id>
[EBAY_AUTH] Found N webhook subscriptions to delete
[EBAY_AUTH] Deleting subscription <subscription_id> from eBay
[EBAY_AUTH] ✓ Deleted subscription <subscription_id> from eBay
[EBAY_AUTH] ✓ Deleted subscription <subscription_id> from database
[EBAY_AUTH] ✓ Cleaned up N webhook subscriptions
[EBAY_AUTH] Credential deleted successfully
```

**Si hay errores:**
- `⚠ Failed to delete subscription`: Posiblemente ya expirada en eBay (7 días), es normal
- Continúa con la eliminación de la base de datos

---

### Paso 4: Probar Reconexión de Cuenta eBay

**Desde la UI:**
1. Ir a Settings → eBay
2. Click en "Connect eBay Account"
3. Autorizar en eBay
4. Esperar redirección de vuelta

**Verificar en logs:**
```bash
sudo journalctl -u qventory -f | grep -E "CALLBACK|WEBHOOK|Platform|SetNotification"
```

**Resultados esperados en logs:**

#### A) OAuth y credenciales:
```
[EBAY_AUTH] === CALLBACK ROUTE CALLED ===
[EBAY_AUTH] Exchanging code for token...
[EBAY_AUTH] ✓ Token exchange successful
[EBAY_AUTH] ✓ Got eBay user info: <username>
[EBAY_AUTH] ✓ Credentials saved successfully
```

#### B) Webhooks de Commerce API (JSON):
```
[WEBHOOK_AUTO_SETUP] === Starting Webhook Auto-Setup ===
[WEBHOOK_AUTO_SETUP] Setting up Commerce API webhooks...
[EBAY_WEBHOOK_API] Creating webhook subscription for topic: ITEM_SOLD
[EBAY_WEBHOOK_API] Creating webhook destination...
[EBAY_WEBHOOK_API] ✓ Destination created: <destination_id>
[EBAY_WEBHOOK_API] Creating subscription...
[EBAY_WEBHOOK_API] ✓ Subscription created: <subscription_id>
...
[WEBHOOK_AUTO_SETUP] ✓ Created 5 webhook subscriptions successfully
```

#### C) **Platform Notifications (ANTES FALLABA, AHORA DEBE FUNCIONAR):**
```
[WEBHOOK_AUTO_SETUP] Setting up Platform Notifications (Trading API)...
[WEBHOOK_AUTO_SETUP] Application URL: https://qventory.com/webhooks/ebay-platform
[WEBHOOK_AUTO_SETUP] Calling SetNotificationPreferences...
[WEBHOOK_AUTO_SETUP] ✓ Platform Notifications enabled successfully
```

**🚨 SI VES ESTO, EL FIX FALLÓ:**
```
[WEBHOOK_AUTO_SETUP] ✗ Missing Trading API credentials
[WEBHOOK_AUTO_SETUP] ✗ Failed to enable Platform Notifications: <error>
```

---

### Paso 5: Verificar Suscripciones en Base de Datos

```bash
# Conectar a PostgreSQL
sudo -u postgres psql qventory_db

# Ver suscripciones activas (todas son de eBay)
SELECT
    ws.id,
    ws.user_id,
    u.username,
    ws.topic,
    ws.subscription_id,
    ws.status,
    ws.created_at,
    ws.expires_at,
    ws.event_count,
    ws.last_event_at
FROM webhook_subscriptions ws
JOIN users u ON ws.user_id = u.id
ORDER BY ws.created_at DESC;

# Salir
\q
```

**Resultado esperado:**
- 5 suscripciones de Commerce API (ITEM_SOLD, ITEM_ENDED, etc.)
- Posiblemente 1 entrada de Platform Notifications
- Todas con `expires_at` ~7 días en el futuro

---

### Paso 6: Verificar Endpoint de Webhooks

```bash
# Probar que el endpoint responde al challenge de eBay
curl "https://qventory.com/webhooks/ebay?challenge_code=test123"
```

**Resultado esperado:**
```json
{"challengeResponse": "test123"}
```

**Verificar en logs:**
```
[WEBHOOK] ============================================================
[WEBHOOK] EBAY CHALLENGE REQUEST RECEIVED
[WEBHOOK]   Method: GET
[WEBHOOK]   Query params: {'challenge_code': 'test123'}
[WEBHOOK] ✓ Received eBay challenge code: test123...
[WEBHOOK] ✓ Sending challenge response: {'challengeResponse': 'test123'}
```

---

### Paso 7: Probar Webhook Real (Opcional pero Recomendado)

**Hacer un cambio en eBay:**
1. Ir a eBay Seller Hub
2. Cambiar el precio de un producto
3. Esperar 30-60 segundos

**Verificar en logs:**
```bash
sudo journalctl -u qventory -f | grep -E "WEBHOOK.*ITEM_PRICE_CHANGE|Processing webhook"
```

**Resultado esperado:**
```
[WEBHOOK] Received eBay webhook event
[WEBHOOK] Topic: MARKETPLACE_ACCOUNT_DELETION.ITEM_PRICE_CHANGE
[WEBHOOK] Processing webhook...
[WEBHOOK] ✓ Webhook processed successfully
```

---

## Comandos Útiles de Monitoreo

### Ver logs de las últimas 24 horas relacionados con eBay
```bash
sudo journalctl -u qventory --since "24 hours ago" | grep -E "EBAY|WEBHOOK" | less
```

### Ver solo errores de eBay
```bash
sudo journalctl -u qventory -p err | grep -i ebay
```

### Contar webhooks recibidos hoy
```bash
sudo journalctl -u qventory --since today | grep "WEBHOOK.*EBAY.*REQUEST" | wc -l
```

### Ver usuarios con cuentas eBay conectadas
```bash
sudo -u postgres psql qventory_db -c "
SELECT
    u.id,
    u.username,
    u.email,
    mc.created_at as ebay_connected_at,
    mc.token_expires_at,
    COUNT(ws.id) as active_webhooks
FROM users u
JOIN marketplace_credentials mc ON u.id = mc.user_id
LEFT JOIN webhook_subscriptions ws ON u.id = ws.user_id
WHERE mc.marketplace = 'ebay'
GROUP BY u.id, u.username, u.email, mc.created_at, mc.token_expires_at
ORDER BY mc.created_at DESC;
"
```

---

## Checklist de Validación

### ✅ Verificación Inicial
- [ ] Servicios activos (qventory, celery, celerybeat)
- [ ] No hay errores críticos en logs recientes
- [ ] Endpoint de webhook responde correctamente

### ✅ Prueba de Desconexión
- [ ] Logs muestran limpieza de suscripciones
- [ ] Suscripciones eliminadas de eBay (o warnings esperados si expiraron)
- [ ] Suscripciones eliminadas de base de datos local
- [ ] Credenciales eliminadas correctamente

### ✅ Prueba de Reconexión
- [ ] OAuth flow completa exitosamente
- [ ] Credenciales guardadas en base de datos
- [ ] Commerce API webhooks creados (5 suscripciones)
- [ ] **Platform Notifications habilitadas** ← **CRÍTICO: Antes fallaba**
- [ ] Suscripciones guardadas en base de datos

### ✅ Verificación de Funcionamiento
- [ ] Endpoint responde a challenges
- [ ] Webhooks reales son recibidos y procesados
- [ ] No hay tokens encriptados en logs de error
- [ ] No hay mensajes "Invalid Token" de eBay

---

## Problemas Conocidos y Soluciones

### Problema: "Token is corrupted or decryption failed"
**Causa**: La ENCRYPTION_KEY cambió en el servidor
**Solución**: Usuario debe desconectar y reconectar cuenta de eBay

### Problema: "⚠ Failed to delete subscription from eBay"
**Causa**: Suscripción ya expiró (7 días) o fue eliminada manualmente
**Solución**: No es un error crítico, continúa normalmente

### Problema: Webhooks duplicados
**Causa**: Suscripciones viejas no limpiadas antes del fix
**Solución**:
1. Desconectar cuenta
2. Verificar limpieza en logs
3. Reconectar cuenta

---

## Próximos Pasos Recomendados

1. **Monitoreo durante 24-48 horas**
   - Verificar que no haya errores nuevos
   - Confirmar que webhooks se reciben correctamente

2. **Comunicar a usuarios afectados**
   - Si tenían problemas, pedir que desconecten/reconecten

3. **Implementar renovación automática** (futuro)
   - Task de Celery para renovar suscripciones antes de 7 días
   - Alertas si renovación falla

4. **Mejorar logging** (futuro)
   - Dashboard de suscripciones activas
   - Métricas de webhooks recibidos/procesados

---

## Contacto para Soporte

Si encuentras algún problema:
1. Captura los logs relevantes
2. Nota el user_id afectado
3. Revisa esta guía para diagnóstico
4. Documenta el caso específico
