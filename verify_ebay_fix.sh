#!/bin/bash

# Script de Verificación de Fixes de eBay
# Ejecutar en el servidor de producción después del deploy

echo "============================================================"
echo "🔍 VERIFICACIÓN DE FIXES DE EBAY"
echo "============================================================"
echo ""

# Colores para output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Verificar que los cambios están desplegados
echo "📝 1. Verificando que los fixes están aplicados..."
echo ""

FIX_LINE=$(grep -n "credential.get_access_token()" /opt/qventory/qventory/qventory/helpers/webhook_auto_setup.py | head -1)

if [[ $FIX_LINE == *"credential.get_access_token()"* ]]; then
    echo -e "${GREEN}✓${NC} Fix del token encontrado en webhook_auto_setup.py"
    echo "  $FIX_LINE"
else
    echo -e "${RED}✗${NC} Fix del token NO encontrado - el código no está actualizado"
    exit 1
fi

echo ""

# 2. Verificar servicios
echo "🔧 2. Verificando servicios..."
echo ""

for service in qventory celery-qventory celerybeat-qventory; do
    if systemctl is-active --quiet $service; then
        echo -e "${GREEN}✓${NC} $service está activo"
    else
        echo -e "${RED}✗${NC} $service NO está activo"
    fi
done

echo ""

# 3. Verificar errores recientes
echo "⚠️  3. Verificando errores recientes (últimas 24 horas)..."
echo ""

ERROR_COUNT=$(journalctl -u qventory --since "24 hours ago" -p err | grep -i ebay | wc -l)

if [ $ERROR_COUNT -eq 0 ]; then
    echo -e "${GREEN}✓${NC} No hay errores de eBay en las últimas 24 horas"
else
    echo -e "${YELLOW}⚠${NC} Se encontraron $ERROR_COUNT errores de eBay en las últimas 24 horas"
    echo "  Ejecuta: sudo journalctl -u qventory --since '24 hours ago' -p err | grep -i ebay"
fi

echo ""

# 4. Ver suscripciones activas
echo "📊 4. Suscripciones de webhooks activas..."
echo ""

sudo -u postgres psql qventory_db -c "
SELECT
    u.username,
    ws.topic,
    ws.status,
    ws.event_count,
    CASE
        WHEN ws.expires_at < NOW() THEN 'EXPIRADO'
        WHEN ws.expires_at < NOW() + INTERVAL '2 days' THEN 'EXPIRA PRONTO'
        ELSE 'ACTIVO'
    END as estado,
    ws.expires_at
FROM webhook_subscriptions ws
JOIN users u ON ws.user_id = u.id
ORDER BY ws.created_at DESC;
" 2>/dev/null

echo ""

# 5. Ver usuarios con eBay conectado
echo "👤 5. Usuarios con cuentas eBay conectadas..."
echo ""

sudo -u postgres psql qventory_db -c "
SELECT
    u.username,
    mc.created_at as conectado_desde,
    mc.token_expires_at as token_expira,
    COUNT(ws.id) as webhooks_activos
FROM users u
JOIN marketplace_credentials mc ON u.id = mc.user_id
LEFT JOIN webhook_subscriptions ws ON u.id = ws.user_id
WHERE mc.marketplace = 'ebay'
GROUP BY u.id, u.username, mc.created_at, mc.token_expires_at
ORDER BY mc.created_at DESC;
" 2>/dev/null

echo ""

# 6. Probar endpoint de webhook
echo "🌐 6. Probando endpoint de webhook..."
echo ""

RESPONSE=$(curl -s "https://qventory.com/webhooks/ebay?challenge_code=test123")

if [[ $RESPONSE == *"challengeResponse"* ]] && [[ $RESPONSE == *"test123"* ]]; then
    echo -e "${GREEN}✓${NC} Endpoint de webhook responde correctamente"
    echo "  Respuesta: $RESPONSE"
else
    echo -e "${RED}✗${NC} Endpoint de webhook NO responde correctamente"
    echo "  Respuesta: $RESPONSE"
fi

echo ""

# 7. Ver eventos recientes en logs
echo "📋 7. Últimos eventos de eBay en logs (últimas 50 líneas)..."
echo ""

journalctl -u qventory -n 50 --no-pager | grep -E "EBAY|WEBHOOK|Platform" | tail -10

echo ""
echo "============================================================"
echo "✅ VERIFICACIÓN COMPLETADA"
echo "============================================================"
echo ""
echo "PRÓXIMOS PASOS:"
echo "1. Si todo está OK arriba, prueba desconectar/reconectar una cuenta eBay"
echo "2. Monitorea los logs durante la reconexión:"
echo "   sudo journalctl -u qventory -f | grep -E 'EBAY|WEBHOOK|Platform'"
echo "3. Busca el mensaje crítico:"
echo "   [WEBHOOK_AUTO_SETUP] ✓ Platform Notifications enabled successfully"
echo ""
echo "Para más detalles, consulta: EBAY_FIX_VERIFICATION.md"
echo ""
