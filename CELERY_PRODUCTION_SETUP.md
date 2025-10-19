# Celery Production Setup - Evitar Pérdida de Tareas

## Problema

Cuando reinicias Celery durante un deploy:
- ❌ Tareas en ejecución se pierden
- ❌ Tareas en cola pueden perderse
- ❌ Mala experiencia de usuario

## Soluciones Implementadas

### 1. Graceful Shutdown en deploy.sh ✅

El script `deploy.sh` ahora:
- Espera hasta 60 segundos para que las tareas terminen
- Solo fuerza el cierre si el timeout se cumple
- Muestra progreso durante la espera

### 2. Configurar Persistencia de Redis

Redis debe persistir las colas en disco para que sobrevivan reinicios.

#### Editar configuración de Redis:

```bash
sudo nano /etc/redis/redis.conf
```

#### Agregar/modificar estas líneas:

```bash
# Persistencia AOF (Append Only File) - más segura para colas
appendonly yes
appendfilename "appendonly.aof"

# Sincronizar a disco cada segundo (balance entre performance y seguridad)
appendfsync everysec

# Persistencia RDB (snapshot) - backup adicional
save 900 1      # Snapshot si 1 cambio en 15 minutos
save 300 10     # Snapshot si 10 cambios en 5 minutos
save 60 10000   # Snapshot si 10000 cambios en 1 minuto

# Directorio donde se guardan los archivos
dir /var/lib/redis
```

#### Reiniciar Redis:

```bash
sudo systemctl restart redis
sudo systemctl status redis
```

### 3. Configurar Celery para Reintento de Tareas

Actualizar `qventory/tasks.py` con configuración de reintento:

```python
# En la parte superior del archivo
from celery import Task

class SafeTask(Task):
    """Task base class with automatic retry on failure"""
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3, 'countdown': 60}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True

# Usar en tus tareas
@celery.task(base=SafeTask)
def mi_tarea():
    # código de la tarea
    pass
```

### 4. Monitorear Celery con Flower (Opcional)

Flower te permite ver las tareas en ejecución y en cola:

```bash
# Instalar Flower
pip install flower

# Crear servicio systemd
sudo nano /etc/systemd/system/flower.service
```

Contenido:

```ini
[Unit]
Description=Flower Celery Monitoring
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/qventory/qventory
Environment="PATH=/opt/qventory/qventory/qventory/bin"
ExecStart=/opt/qventory/qventory/qventory/bin/celery -A qventory.celery_app flower --port=5555 --broker=redis://localhost:6379/0
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable flower
sudo systemctl start flower
```

Accede a Flower en: `http://tu-servidor:5555`

### 5. Estrategia de Deploy sin Downtime

Para deploys sin perder tareas:

#### Opción A: Deploy fuera de horas pico
- Programa deploys cuando hay menos usuarios activos
- Típicamente: 2-4 AM en tu timezone

#### Opción B: Blue-Green Deployment (Avanzado)
- Mantén dos instancias de Celery
- Durante deploy, nueva instancia procesa tareas nuevas
- Instancia vieja termina tareas existentes
- Requiere load balancer y configuración adicional

#### Opción C: Mantenimiento Programado
- Notifica a usuarios con 24h de anticipación
- Usa banner en la aplicación: "Mantenimiento en 2 horas"
- Pausa la creación de nuevas tareas 10 minutos antes
- Ejecuta deploy cuando la cola esté vacía

## Verificar Estado de Celery

### Ver tareas en cola:

```bash
# Conectar a Redis CLI
redis-cli

# Ver longitud de la cola de Celery
LLEN celery

# Ver tareas pendientes
LRANGE celery 0 -1

# Salir
exit
```

### Ver workers activos:

```bash
# Ver procesos de Celery
ps aux | grep celery

# Ver logs en tiempo real
journalctl -u celery-qventory -f

# Ver estado de systemd
systemctl status celery-qventory
```

### Ver tareas programadas (beat):

```bash
# Ver tareas programadas en Redis
redis-cli

# Listar keys de celery beat
KEYS celery-beat-*

# Ver schedule
GET celery-beat-schedule
```

## Mejores Prácticas

### 1. Configurar Task Time Limits

En tu configuración de Celery:

```python
# qventory/celery_app.py
app.conf.update(
    task_time_limit=300,        # 5 minutos hard limit
    task_soft_time_limit=240,   # 4 minutos soft limit
)
```

### 2. Idempotencia de Tareas

Asegúrate de que las tareas puedan ejecutarse múltiples veces sin problemas:

```python
@celery.task
def send_verification_email(user_id, code):
    # Verificar si ya se envió
    verification = EmailVerification.query.filter_by(
        user_id=user_id,
        code=code,
        used_at=None
    ).first()

    if not verification or verification.is_expired():
        return  # Ya se usó o expiró, no reenviar

    # Enviar email...
```

### 3. Logging Detallado

```python
import logging

logger = logging.getLogger(__name__)

@celery.task
def mi_tarea():
    logger.info(f"Iniciando tarea {mi_tarea.request.id}")
    try:
        # trabajo...
        logger.info(f"Tarea {mi_tarea.request.id} completada exitosamente")
    except Exception as e:
        logger.error(f"Error en tarea {mi_tarea.request.id}: {str(e)}")
        raise
```

### 4. Monitoreo de Salud

Crear endpoint de health check:

```python
# En routes/main.py
@main_bp.route('/health/celery')
def celery_health():
    from qventory.celery_app import celery

    # Verificar que Celery está respondiendo
    try:
        celery.control.ping(timeout=1.0)
        return {'status': 'ok', 'celery': 'running'}, 200
    except:
        return {'status': 'error', 'celery': 'down'}, 503
```

## Escenarios de Emergencia

### ¿Qué hacer si Celery se cuelga?

```bash
# 1. Ver logs para identificar el problema
journalctl -u celery-qventory -n 100

# 2. Ver qué proceso está bloqueado
ps aux | grep celery

# 3. Forzar kill si es necesario
sudo pkill -9 -f "celery.*worker"

# 4. Limpiar la cola si está corrupta
redis-cli FLUSHDB  # ⚠️ ESTO BORRA TODAS LAS TAREAS

# 5. Reiniciar Celery
sudo systemctl start celery-qventory
```

### ¿Qué hacer si las tareas se acumulan?

```bash
# 1. Ver cuántas tareas hay
redis-cli LLEN celery

# 2. Agregar más workers temporalmente
sudo systemctl start celery-qventory-extra  # Si tienes configurado

# 3. Aumentar concurrency del worker existente
# Editar /etc/systemd/system/celery-qventory.service
# Cambiar --concurrency=4 a --concurrency=8

sudo systemctl daemon-reload
sudo systemctl restart celery-qventory
```

## Resumen de Mejoras

1. ✅ **Graceful shutdown** en deploy.sh (60s timeout)
2. ✅ **Persistencia de Redis** con AOF + RDB
3. ⚠️ **Reintento automático** de tareas (por implementar)
4. ⚠️ **Flower monitoring** (opcional)
5. ⚠️ **Time limits** en tareas (por implementar)
6. ⚠️ **Health checks** (por implementar)

## Próximos Pasos

1. Configura persistencia de Redis (CRÍTICO)
2. Implementa reintentos automáticos en tareas críticas
3. Considera instalar Flower para monitoreo
4. Programa deploys fuera de horas pico
5. Implementa notificaciones de mantenimiento a usuarios
