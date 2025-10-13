# 🚀 Pasos para Desplegar la Corrección de Importación de Analytics

## ✅ Cambios Realizados

Se corrigió el problema donde la importación de analytics solo traía 90 días de historial en lugar del historial completo.

### Archivos Modificados:
1. `qventory/tasks.py` - Función `import_ebay_sales`
2. `qventory/helpers/ebay_inventory.py` - Función `fetch_ebay_sold_orders`
3. `qventory/routes/main.py` - Endpoint de importación

## 📋 Pasos para Desplegar en el Servidor

### 1. Conectar al servidor
```bash
ssh root@your-server-ip
cd /opt/qventory/qventory
```

### 2. Hacer pull de los cambios
```bash
git pull origin main
```

### 3. Reiniciar Celery (IMPORTANTE)
```bash
sudo systemctl restart celery
sudo systemctl status celery
```

### 4. Verificar logs de Celery
```bash
sudo journalctl -u celery -f
```

### 5. (Opcional) Reiniciar la aplicación web
```bash
sudo systemctl restart qventory
sudo systemctl status qventory
```

## 🧪 Cómo Probar

1. Ve a tu aplicación: `https://your-domain.com`
2. Navega a: **Dashboard → Import from eBay**
3. En el dropdown **"Sales History"**, selecciona **"All Time (Lifetime Sales)"**
4. Haz clic en **"Start Import"**
5. Observa los logs en el servidor:
   ```bash
   sudo journalctl -u celery -f
   ```

## 📊 Logs Esperados

Deberías ver algo como:

```
[CELERY_TASK] Starting eBay sales import for user X, ALL TIME (full history)
📅 Scanning historical window: 2025-07-15 to 2025-10-13 (≈0.0 years back)
   Progress: 0 orders collected so far, iteration 0/500
📅 Scanning historical window: 2025-04-16 to 2025-07-15 (≈0.2 years back)
   Progress: 45 orders collected so far, iteration 5/500
📅 Scanning historical window: 2024-01-17 to 2024-04-16 (≈1.5 years back)
   Progress: 120 orders collected so far, iteration 10/500
...
```

## 🎯 Qué Cambió

### Antes:
- ❌ Solo importaba últimos 90 días por limitación de la API
- ❌ No iteraba hacia atrás en el tiempo
- ❌ Máximo 5,000 orders

### Después:
- ✅ Itera en ventanas de 90 días hacia atrás
- ✅ Busca hasta 20 años de historial (7,300 días)
- ✅ Máximo 10,000 orders
- ✅ Hasta 500 iteraciones (≈123 años teóricos)
- ✅ Se detiene automáticamente si encuentra 2 ventanas vacías consecutivas
- ✅ Logs de progreso cada 5 iteraciones

## ⚠️ Notas Importantes

1. **La primera importación completa puede tomar varios minutos** dependiendo de cuántos años de historial tengas.
2. Los **logs de progreso** te mostrarán cuántos años atrás está escaneando.
3. El sistema se **detendrá automáticamente** cuando ya no haya más orders históricos.
4. **Reiniciar Celery es CRÍTICO** - sin esto, los cambios no tomarán efecto.

## 🐛 Solución de Problemas

### Si ves el error: `'<=' not supported between instances of 'str' and 'int'`
- Significa que Celery no se reinició correctamente
- Ejecuta: `sudo systemctl restart celery`
- Verifica: `sudo systemctl status celery`

### Si la importación no avanza:
- Revisa los logs: `sudo journalctl -u celery -f`
- Verifica que tu token de eBay no haya expirado
- Confirma que tienes ventas históricas en eBay

### Si quieres reiniciar todo:
```bash
sudo systemctl restart celery
sudo systemctl restart qventory
```

## 📞 Contacto

Si tienes problemas con el despliegue, revisa los logs de Celery y la aplicación.
