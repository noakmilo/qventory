# Celery Beat Setup for Auto-Relist

Este documento describe cómo actualizar el servicio de Celery en el servidor para incluir Celery Beat (scheduler).

## ¿Qué es Celery Beat?

Celery Beat es el scheduler que ejecuta tareas periódicas. En nuestro caso:
- **Auto-relist task**: Se ejecuta cada 15 minutos para procesar reglas de auto-relist

## Actualizar Servicio en el Servidor

### Opción 1: Comando Inline (Recomendado)

Si el servicio de Celery ya está configurado en `/etc/systemd/system/celery-qventory.service`, solo necesitas agregar el flag `--beat`:

```bash
# Conectar al servidor
ssh root@qventory-server

# Editar el servicio
sudo nano /etc/systemd/system/celery-qventory.service
```

Busca la línea `ExecStart=` y asegúrate de que incluya `--beat`:

```ini
ExecStart=/opt/qventory/qventory/qventory/bin/celery -A qventory.celery_app worker --beat --loglevel=info
```

Luego recargar y reiniciar:

```bash
sudo systemctl daemon-reload
sudo systemctl restart celery-qventory
sudo systemctl status celery-qventory
```

### Opción 2: Servicio Separado (Producción Avanzada)

Para entornos de producción más grandes, es recomendable separar Beat en su propio servicio:

#### Archivo: `/etc/systemd/system/celery-beat-qventory.service`

```ini
[Unit]
Description=Celery Beat Scheduler for Qventory
After=network.target redis.service

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=/opt/qventory/qventory
Environment="PATH=/opt/qventory/qventory/qventory/bin"
Environment="REDIS_URL=redis://localhost:6379/0"
ExecStart=/opt/qventory/qventory/qventory/bin/celery -A qventory.celery_app beat --loglevel=info --pidfile=/tmp/celerybeat.pid
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Luego:

```bash
sudo systemctl daemon-reload
sudo systemctl enable celery-beat-qventory
sudo systemctl start celery-beat-qventory
sudo systemctl status celery-beat-qventory
```

## Verificar que Funciona

### 1. Ver logs de Celery

```bash
sudo journalctl -u celery-qventory -f
```

Deberías ver mensajes como:

```
[2025-10-15 12:00:00,123: INFO/MainProcess] beat: Starting...
[2025-10-15 12:00:00,456: INFO/MainProcess] Scheduler: Sending due task auto-relist-every-15-minutes
```

### 2. Ver tareas programadas

Desde Python:

```python
from qventory.celery_app import celery

# Ver schedule
print(celery.conf.beat_schedule)
```

### 3. Ver estado de Beat

```bash
# Si usaste Opción 1 (inline)
sudo systemctl status celery-qventory | grep -i beat

# Si usaste Opción 2 (separado)
sudo systemctl status celery-beat-qventory
```

## Troubleshooting

### Beat no se ejecuta

1. Verificar que Redis está corriendo:
   ```bash
   sudo systemctl status redis
   ```

2. Verificar permisos del archivo PID:
   ```bash
   ls -la /tmp/celerybeat.pid
   ```

3. Eliminar archivo PID antiguo:
   ```bash
   sudo rm /tmp/celerybeat.pid
   sudo systemctl restart celery-qventory
   ```

### Tareas no se ejecutan

1. Verificar que las reglas existen en la DB:
   ```sql
   SELECT id, mode, enabled, next_run_at FROM auto_relist_rules;
   ```

2. Verificar logs de la tarea:
   ```bash
   sudo journalctl -u celery-qventory | grep auto_relist
   ```

3. Ejecutar manualmente para testing:
   ```python
   from qventory.tasks import auto_relist_offers
   result = auto_relist_offers.delay()
   print(result.get())
   ```

## Configuración en deploy.sh

El script `deploy.sh` ya está configurado para reiniciar el servicio de Celery:

```bash
systemctl restart celery-qventory || log "⚠️  Celery no instalado o no configurado"
```

No requiere cambios adicionales.

## Configuración Local (Desarrollo)

Para desarrollo local, usa el script actualizado:

```bash
./start_celery.sh
```

Este script ahora incluye automáticamente el flag `--beat`.
