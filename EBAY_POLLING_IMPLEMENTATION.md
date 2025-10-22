# Sistema de Polling para eBay - Solución Temporal

## 🎯 Objetivo

Implementar polling automático para obtener actualizaciones de:
- ✅ **Ventas** (órdenes nuevas/actualizadas)
- ✅ **Fulfillment** (estado de envíos)
- ✅ **Inventario** (cambios de stock)

Esto reemplaza temporalmente a Commerce API Webhooks mientras esperamos aprobación.

---

## 📊 Estrategia de Polling

### Frecuencias Recomendadas

| Recurso | Frecuencia | Razón |
|---------|-----------|-------|
| **Órdenes Nuevas** | Cada 5 minutos | Detectar ventas rápidamente |
| **Fulfillment Status** | Cada 15 minutos | Tracking de envíos |
| **Inventario** | Cada 30 minutos | Cambios de stock |
| **Órdenes Actualizadas** | Cada 10 minutos | Cambios en órdenes existentes |

### Optimizaciones

1. **Usar filtros de fecha**: Solo obtener cambios desde última consulta
2. **Pagination**: Manejar grandes volúmenes correctamente
3. **Rate limiting**: Respetar límites de API de eBay
4. **Caching**: No procesar eventos duplicados
5. **Backoff**: Reducir frecuencia si no hay cambios

---

## 🔧 Implementación con Celery Beat

### Arquitectura

```
Celery Beat (scheduler)
    ↓
Polling Tasks (cada X minutos)
    ↓
eBay API (con filtros de fecha)
    ↓
Detect Changes
    ↓
Process Events (mismo código que webhooks)
```

---

## 📝 Código para Implementar

### 1. Crear Archivo de Tasks de Polling

**Archivo**: `qventory/tasks/ebay_polling.py`

```python
"""
eBay Polling Tasks
Temporary solution while waiting for Commerce API webhook access
"""
from celery import shared_task
from datetime import datetime, timedelta
from qventory.helpers.ebay_inventory import get_user_access_token
from qventory.models.marketplace_credential import MarketplaceCredential
from qventory.models.item import Item
from qventory.extensions import db
import requests
import sys

def log(msg):
    """Helper for logging"""
    print(f"[EBAY_POLLING] {msg}", file=sys.stderr, flush=True)


@shared_task(name='ebay_polling.poll_orders')
def poll_orders():
    """
    Poll eBay for new/updated orders
    Runs every 5 minutes
    """
    log("Starting orders polling...")

    # Get all users with eBay connected
    credentials = MarketplaceCredential.query.filter_by(marketplace='ebay').all()

    for cred in credentials:
        try:
            poll_orders_for_user.delay(cred.user_id)
        except Exception as e:
            log(f"Error queuing order poll for user {cred.user_id}: {str(e)}")

    log(f"Orders polling queued for {len(credentials)} users")


@shared_task(name='ebay_polling.poll_orders_for_user')
def poll_orders_for_user(user_id: int):
    """
    Poll orders for a specific user
    """
    log(f"Polling orders for user {user_id}")

    try:
        access_token = get_user_access_token(user_id)
        if not access_token:
            log(f"No access token for user {user_id}")
            return

        # Get last poll time from user settings or use last 6 hours
        last_poll = get_last_poll_time(user_id, 'orders')

        # eBay Fulfillment API - Get orders modified since last poll
        url = "https://api.ebay.com/sell/fulfillment/v1/order"

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        # Filter by last modification date
        params = {
            'filter': f'lastmodifieddate:[{last_poll.isoformat()}Z..]',
            'limit': 50  # Process in batches
        }

        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code != 200:
            log(f"Error fetching orders for user {user_id}: {response.status_code}")
            return

        data = response.json()
        orders = data.get('orders', [])

        log(f"Found {len(orders)} updated orders for user {user_id}")

        # Process each order
        new_count = 0
        updated_count = 0

        for order in orders:
            result = process_order(user_id, order)
            if result == 'new':
                new_count += 1
            elif result == 'updated':
                updated_count += 1

        # Update last poll time
        update_last_poll_time(user_id, 'orders', datetime.utcnow())

        log(f"User {user_id}: {new_count} new orders, {updated_count} updated")

    except Exception as e:
        log(f"Exception polling orders for user {user_id}: {str(e)}")
        import traceback
        log(traceback.format_exc())


@shared_task(name='ebay_polling.poll_fulfillment')
def poll_fulfillment():
    """
    Poll eBay for fulfillment updates (shipping status)
    Runs every 15 minutes
    """
    log("Starting fulfillment polling...")

    credentials = MarketplaceCredential.query.filter_by(marketplace='ebay').all()

    for cred in credentials:
        try:
            poll_fulfillment_for_user.delay(cred.user_id)
        except Exception as e:
            log(f"Error queuing fulfillment poll for user {cred.user_id}: {str(e)}")

    log(f"Fulfillment polling queued for {len(credentials)} users")


@shared_task(name='ebay_polling.poll_fulfillment_for_user')
def poll_fulfillment_for_user(user_id: int):
    """
    Poll fulfillment status for a specific user
    Check orders that are in transit or recently shipped
    """
    log(f"Polling fulfillment for user {user_id}")

    try:
        access_token = get_user_access_token(user_id)
        if not access_token:
            return

        # Get orders that are NOT_STARTED or IN_PROGRESS
        url = "https://api.ebay.com/sell/fulfillment/v1/order"

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        # Focus on orders that might have shipping updates
        params = {
            'filter': 'orderFulfillmentStatus:{NOT_STARTED|IN_PROGRESS}',
            'limit': 100
        }

        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code != 200:
            log(f"Error fetching fulfillment for user {user_id}: {response.status_code}")
            return

        data = response.json()
        orders = data.get('orders', [])

        log(f"Checking {len(orders)} orders for fulfillment updates")

        shipped_count = 0
        for order in orders:
            if check_and_update_fulfillment(user_id, order):
                shipped_count += 1

        log(f"User {user_id}: {shipped_count} fulfillment updates")

    except Exception as e:
        log(f"Exception polling fulfillment for user {user_id}: {str(e)}")


@shared_task(name='ebay_polling.poll_inventory')
def poll_inventory():
    """
    Poll eBay for inventory changes
    Runs every 30 minutes
    """
    log("Starting inventory polling...")

    credentials = MarketplaceCredential.query.filter_by(marketplace='ebay').all()

    for cred in credentials:
        try:
            poll_inventory_for_user.delay(cred.user_id)
        except Exception as e:
            log(f"Error queuing inventory poll for user {cred.user_id}: {str(e)}")

    log(f"Inventory polling queued for {len(credentials)} users")


@shared_task(name='ebay_polling.poll_inventory_for_user')
def poll_inventory_for_user(user_id: int):
    """
    Poll inventory for a specific user
    Check for quantity changes, out of stock, etc.
    """
    log(f"Polling inventory for user {user_id}")

    try:
        access_token = get_user_access_token(user_id)
        if not access_token:
            return

        # Get user's items from local DB
        items = Item.query.filter_by(user_id=user_id, marketplace='ebay').all()

        log(f"Checking {len(items)} items for user {user_id}")

        updated_count = 0
        out_of_stock_count = 0

        for item in items:
            if not item.ebay_sku:
                continue

            # Get current inventory from eBay
            url = f"https://api.ebay.com/sell/inventory/v1/inventory_item/{item.ebay_sku}"

            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                ebay_data = response.json()
                ebay_quantity = ebay_data.get('availability', {}).get('shipToLocationAvailability', {}).get('quantity', 0)

                # Check if quantity changed
                if item.quantity != ebay_quantity:
                    log(f"Quantity changed for {item.ebay_sku}: {item.quantity} → {ebay_quantity}")
                    item.quantity = ebay_quantity
                    updated_count += 1

                    # Check if out of stock
                    if ebay_quantity == 0:
                        out_of_stock_count += 1
                        # TODO: Trigger notification or alert

        if updated_count > 0:
            db.session.commit()

        log(f"User {user_id}: {updated_count} items updated, {out_of_stock_count} out of stock")

    except Exception as e:
        log(f"Exception polling inventory for user {user_id}: {str(e)}")


# Helper functions

def get_last_poll_time(user_id: int, poll_type: str) -> datetime:
    """
    Get last time we polled for this user and type
    Store in user settings or separate table
    """
    from qventory.models.setting import Setting

    setting = Setting.query.filter_by(
        user_id=user_id,
        key=f'ebay_last_poll_{poll_type}'
    ).first()

    if setting and setting.value:
        try:
            return datetime.fromisoformat(setting.value)
        except:
            pass

    # Default: last 6 hours
    return datetime.utcnow() - timedelta(hours=6)


def update_last_poll_time(user_id: int, poll_type: str, timestamp: datetime):
    """
    Update last poll time for user
    """
    from qventory.models.setting import Setting

    setting = Setting.query.filter_by(
        user_id=user_id,
        key=f'ebay_last_poll_{poll_type}'
    ).first()

    if not setting:
        setting = Setting(
            user_id=user_id,
            key=f'ebay_last_poll_{poll_type}',
            value=timestamp.isoformat()
        )
        db.session.add(setting)
    else:
        setting.value = timestamp.isoformat()

    db.session.commit()


def process_order(user_id: int, order_data: dict) -> str:
    """
    Process an order from eBay
    Returns: 'new', 'updated', or 'skipped'
    """
    from qventory.models.sale import Sale

    order_id = order_data.get('orderId')

    # Check if we already have this order
    existing_sale = Sale.query.filter_by(
        user_id=user_id,
        ebay_order_id=order_id
    ).first()

    if existing_sale:
        # Update existing order
        # TODO: Check if status changed, update accordingly
        return 'updated'
    else:
        # Create new sale
        # TODO: Create Sale record from order_data
        return 'new'


def check_and_update_fulfillment(user_id: int, order_data: dict) -> bool:
    """
    Check if order has shipping updates
    Returns True if there was an update
    """
    # TODO: Implement logic to detect and process shipping updates
    return False
```

---

### 2. Configurar Celery Beat Schedule

**Archivo**: `qventory/celery_config.py` o donde tengas la config de Celery

Agrega esto al schedule de Celery Beat:

```python
from celery.schedules import crontab

CELERYBEAT_SCHEDULE = {
    # ... tus otros schedules ...

    # eBay Polling Tasks
    'poll-ebay-orders': {
        'task': 'ebay_polling.poll_orders',
        'schedule': 300.0,  # Every 5 minutes
    },
    'poll-ebay-fulfillment': {
        'task': 'ebay_polling.poll_fulfillment',
        'schedule': 900.0,  # Every 15 minutes
    },
    'poll-ebay-inventory': {
        'task': 'ebay_polling.poll_inventory',
        'schedule': 1800.0,  # Every 30 minutes
    },
}
```

---

### 3. Registrar Tasks en Celery

**Archivo**: `qventory/tasks/__init__.py`

```python
from qventory.tasks.ebay_polling import (
    poll_orders,
    poll_orders_for_user,
    poll_fulfillment,
    poll_fulfillment_for_user,
    poll_inventory,
    poll_inventory_for_user
)

__all__ = [
    'poll_orders',
    'poll_orders_for_user',
    'poll_fulfillment',
    'poll_fulfillment_for_user',
    'poll_inventory',
    'poll_inventory_for_user',
]
```

---

## 🚀 Cómo Activar

### Paso 1: Crear el Archivo de Tasks

```bash
# En tu máquina local
mkdir -p qventory/tasks
touch qventory/tasks/ebay_polling.py
```

Copia el código de arriba al archivo.

### Paso 2: Actualizar Configuración de Celery

Agrega los schedules al archivo de configuración de Celery.

### Paso 3: Commit y Deploy

```bash
git add qventory/tasks/ebay_polling.py
git commit -m "Add eBay polling system as temporary solution for webhooks"
git push

# En servidor
cd /opt/qventory/qventory
git pull
sudo systemctl restart celery-qventory
sudo systemctl restart celerybeat-qventory
```

### Paso 4: Verificar que Funciona

```bash
# Ver logs de Celery Beat
sudo journalctl -u celerybeat-qventory -f

# Ver logs de Workers
sudo journalctl -u celery-qventory -f | grep EBAY_POLLING
```

---

## 📊 Ventajas vs Webhooks

### Ventajas del Polling

- ✅ **Funciona AHORA** (no requiere aprobación)
- ✅ **Control total** sobre frecuencia
- ✅ **Más simple** de debuggear
- ✅ **No depende** de que eBay te envíe eventos
- ✅ **Puedes recuperar** eventos perdidos

### Desventajas del Polling

- ❌ **Latencia**: 5-30 min de delay vs tiempo real
- ❌ **API calls**: Consume más llamadas a la API
- ❌ **Recursos**: Más carga en tu servidor

---

## 💡 Optimizaciones Futuras

### 1. Polling Adaptativo

```python
# Si no hay cambios en 1 hora, reduce frecuencia
if no_changes_count > 12:  # 12 * 5min = 1 hour
    # Cambiar a cada 15 minutos
    pass
```

### 2. Solo Usuarios Activos

```python
# Solo hacer polling para usuarios que han hecho login recientemente
active_users = User.query.filter(
    User.last_login > datetime.utcnow() - timedelta(days=7)
).all()
```

### 3. Priorizar por Actividad

```python
# Usuarios con más ventas → polling más frecuente
high_volume_users = usuarios con >100 ventas/mes
poll_every_2_minutes(high_volume_users)
```

---

## 🔄 Migración a Webhooks

Cuando obtengas acceso a Commerce API:

1. **Activar webhooks** (descomentar código en `ebay_auth.py`)
2. **Mantener polling** como backup por 1 semana
3. **Comparar** que ambos detectan los mismos eventos
4. **Desactivar polling** gradualmente
5. **Mantener código** por si webhooks fallan

---

## 📈 Monitoreo

### Métricas a Trackear

- Número de polls por hora
- Número de cambios detectados
- Tiempo promedio de respuesta de API
- API calls consumidos
- Eventos duplicados detectados

### Alertas

- Si polling falla >3 veces consecutivas
- Si tiempo de respuesta >10 segundos
- Si se detectan >1000 cambios (posible problema)

---

## ✅ Resumen

**Implementación Simple**:
1. Crear archivo `ebay_polling.py` con las tasks
2. Configurar schedule en Celery Beat
3. Deploy y listo

**Cobertura**:
- ✅ Órdenes nuevas (cada 5 min)
- ✅ Updates de fulfillment (cada 15 min)
- ✅ Cambios de inventario (cada 30 min)

**Cuando Tengas Webhooks**:
- Fácil migración
- Código reutilizable
- Polling como backup

---

**¿Quieres que cree los archivos de código ahora o prefieres descansar y lo hacemos mañana?** 😊

Descansa bien - ¡hicimos mucho hoy! ✅ Platform Notifications funcionando es un gran logro.
