#!/usr/bin/env python3
"""
Script para migrar datos de SQLite a PostgreSQL
Ejecutar DESPUÉS de hacer deploy y antes de reiniciar servicios
"""
import os
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

# Asegurarse de que dotenv se carga
from dotenv import load_dotenv
dotenv_path = Path(__file__).parent / '.env'
if dotenv_path.exists():
    load_dotenv(dotenv_path)

from qventory import create_app
from qventory.extensions import db

# Path a la base de datos SQLite
SQLITE_DB_PATH = '/opt/qventory/data/app.db'

def migrate_data():
    """Migrar todos los datos de SQLite a PostgreSQL"""

    # Verificar que estamos usando PostgreSQL
    app = create_app()
    with app.app_context():
        dialect = db.engine.dialect.name
        if dialect != 'postgresql':
            print(f"❌ ERROR: La app está usando {dialect}, no PostgreSQL")
            print(f"   Verifica que DATABASE_URL esté configurado en .env")
            sys.exit(1)

        print(f"\n✅ Conectado a PostgreSQL: {db.engine.url.database}")

        # Verificar que SQLite existe
        if not Path(SQLITE_DB_PATH).exists():
            print(f"❌ ERROR: No se encuentra SQLite en {SQLITE_DB_PATH}")
            sys.exit(1)

        print(f"✅ Encontrado SQLite: {SQLITE_DB_PATH}")

        # Conectar a SQLite
        sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
        sqlite_conn.row_factory = sqlite3.Row
        cursor = sqlite_conn.cursor()

        # Helper para obtener valores de sqlite3.Row
        def get_value(row, key, default=None):
            """Obtiene valor de sqlite3.Row con fallback"""
            try:
                return row[key] if row[key] is not None else default
            except (KeyError, IndexError):
                return default

        print("\n🔄 Iniciando migración de datos...\n")

        # Importar todos los modelos
        from qventory.models.user import User
        from qventory.models.item import Item
        from qventory.models.sale import Sale
        from qventory.models.expense import Expense
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.setting import Setting
        from qventory.models.listing import Listing
        from qventory.models.subscription import Subscription
        from qventory.models.import_job import ImportJob

        # 1. Migrar Usuarios
        print("📦 Migrando usuarios...")
        cursor.execute("SELECT * FROM users ORDER BY id")
        users_data = cursor.fetchall()
        for row in users_data:
            user = User(
                id=row['id'],
                username=row['username'],
                email=row['email'],
                password_hash=row['password_hash'],
                created_at=row['created_at']
            )
            if 'last_login' in row.keys() and row['last_login']:
                user.last_login = row['last_login']
            db.session.add(user)
        db.session.commit()
        print(f"✅ Migrados {len(users_data)} usuarios")

        # 2. Migrar Settings
        print("\n📦 Migrando configuraciones...")
        cursor.execute("SELECT * FROM settings ORDER BY id")
        settings_data = cursor.fetchall()
        for row in settings_data:
            setting = Setting(
                id=row['id'],
                user_id=row['user_id'],
                label_A=row['label_A'],
                label_B=row['label_B'],
                label_S=row['label_S'],
                label_C=row['label_C'],
                enable_A=bool(row['enable_A']),
                enable_B=bool(row['enable_B']),
                enable_S=bool(row['enable_S']),
                enable_C=bool(row['enable_C'])
            )
            # created_at y updated_at pueden no existir en versiones antiguas
            if 'created_at' in row.keys() and row['created_at']:
                setting.created_at = row['created_at']
            if 'updated_at' in row.keys() and row['updated_at']:
                setting.updated_at = row['updated_at']
            db.session.add(setting)
        db.session.commit()
        print(f"✅ Migrados {len(settings_data)} settings")

        # 3. Migrar Marketplace Credentials
        print("\n📦 Migrando credenciales de marketplace...")
        cursor.execute("SELECT * FROM marketplace_credentials ORDER BY id")
        creds_data = cursor.fetchall()
        for row in creds_data:
            cred = MarketplaceCredential(
                id=row['id'],
                user_id=row['user_id'],
                marketplace=row['marketplace'],
                ebay_user_id=get_value(row, 'ebay_user_id'),
                is_active=bool(row['is_active']),
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
            # Campos encriptados
            if get_value(row, 'access_token_encrypted'):
                cred.access_token_encrypted = row['access_token_encrypted']
            if get_value(row, 'refresh_token_encrypted'):
                cred.refresh_token_encrypted = row['refresh_token_encrypted']
            if get_value(row, 'token_expires_at'):
                cred.token_expires_at = row['token_expires_at']
            if 'ebay_store_subscription' in row.keys() and row['ebay_store_subscription']:
                cred.ebay_store_subscription = row['ebay_store_subscription']
            db.session.add(cred)
        db.session.commit()
        print(f"✅ Migrados {len(creds_data)} credenciales")

        # 4. Migrar Items
        print("\n📦 Migrando items...")
        cursor.execute("SELECT * FROM items ORDER BY id")
        items_data = cursor.fetchall()
        for row in items_data:
            item = Item(
                id=row['id'],
                user_id=row['user_id'],
                title=row['title'],
                sku=row['sku'],
                description=get_value(row, 'description'),
                upc=get_value(row, 'upc'),
                listing_link=get_value(row, 'listing_link'),
                web_url=get_value(row, 'web_url'),
                ebay_url=get_value(row, 'ebay_url'),
                amazon_url=get_value(row, 'amazon_url'),
                mercari_url=get_value(row, 'mercari_url'),
                vinted_url=get_value(row, 'vinted_url'),
                poshmark_url=get_value(row, 'poshmark_url'),
                depop_url=get_value(row, 'depop_url'),
                whatnot_url=get_value(row, 'whatnot_url'),
                A=get_value(row, 'A'),
                B=get_value(row, 'B'),
                S=get_value(row, 'S'),
                C=get_value(row, 'C'),
                location_code=get_value(row, 'location_code'),
                item_thumb=get_value(row, 'item_thumb'),
                supplier=get_value(row, 'supplier'),
                item_cost=get_value(row, 'item_cost'),
                item_price=get_value(row, 'item_price'),
                quantity=get_value(row, 'quantity', 1),
                low_stock_threshold=get_value(row, 'low_stock_threshold', 1),
                is_active=bool(get_value(row, 'is_active', True)),
                category=get_value(row, 'category'),
                listing_date=get_value(row, 'listing_date'),
                purchased_at=get_value(row, 'purchased_at'),
                ebay_item_id=get_value(row, 'ebay_item_id'),
                ebay_listing_id=get_value(row, 'ebay_listing_id'),
                ebay_sku=get_value(row, 'ebay_sku'),
                synced_from_ebay=bool(get_value(row, 'synced_from_ebay', False)),
                last_ebay_sync=get_value(row, 'last_ebay_sync'),
                notes=get_value(row, 'notes'),
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
            # JSON fields
            if get_value(row, 'image_urls'):
                item.image_urls = row['image_urls']
            if get_value(row, 'tags'):
                item.tags = row['tags']
            db.session.add(item)
        db.session.commit()
        print(f"✅ Migrados {len(items_data)} items")

        # 5. Migrar Sales
        print("\n📦 Migrando ventas...")
        cursor.execute("SELECT * FROM sales ORDER BY id")
        sales_data = cursor.fetchall()
        for row in sales_data:
            sale = Sale(
                id=row['id'],
                user_id=row['user_id'],
                item_id=get_value(row, 'item_id'),
                marketplace=row['marketplace'],
                marketplace_order_id=get_value(row, 'marketplace_order_id'),
                item_title=row['item_title'],
                item_sku=get_value(row, 'item_sku'),
                sold_price=row['sold_price'],
                item_cost=get_value(row, 'item_cost'),
                marketplace_fee=get_value(row, 'marketplace_fee', 0),
                payment_processing_fee=get_value(row, 'payment_processing_fee', 0),
                shipping_cost=get_value(row, 'shipping_cost', 0),
                shipping_charged=get_value(row, 'shipping_charged', 0),
                other_fees=get_value(row, 'other_fees', 0),
                gross_profit=get_value(row, 'gross_profit'),
                net_profit=get_value(row, 'net_profit'),
                sold_at=row['sold_at'],
                paid_at=get_value(row, 'paid_at'),
                shipped_at=get_value(row, 'shipped_at'),
                tracking_number=get_value(row, 'tracking_number'),
                buyer_username=get_value(row, 'buyer_username'),
                status=get_value(row, 'status', 'pending'),
                return_reason=get_value(row, 'return_reason'),
                returned_at=get_value(row, 'returned_at'),
                refund_amount=get_value(row, 'refund_amount'),
                refund_reason=get_value(row, 'refund_reason'),
                ebay_transaction_id=get_value(row, 'ebay_transaction_id'),
                ebay_buyer_username=get_value(row, 'ebay_buyer_username'),
                notes=get_value(row, 'notes'),
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
            # Nuevos campos de fulfillment (pueden no existir en SQLite)
            if 'delivered_at' in row.keys() and row['delivered_at']:
                sale.delivered_at = row['delivered_at']
            if 'carrier' in row.keys() and row['carrier']:
                sale.carrier = row['carrier']
            db.session.add(sale)
        db.session.commit()
        print(f"✅ Migrados {len(sales_data)} ventas")

        # 6. Migrar Expenses (puede no existir en SQLite antiguo)
        print("\n📦 Migrando gastos...")
        try:
            cursor.execute("SELECT * FROM expenses ORDER BY id")
            expenses_data = cursor.fetchall()
            for row in expenses_data:
                expense = Expense(
                    id=row['id'],
                    user_id=row['user_id'],
                    description=row['description'],
                    amount=row['amount'],
                    category=get_value(row, 'category'),
                    expense_date=row['expense_date'],
                    is_recurring=bool(get_value(row, 'is_recurring', False)),
                    recurring_frequency=get_value(row, 'recurring_frequency'),
                    recurring_day=get_value(row, 'recurring_day'),
                    recurring_until=get_value(row, 'recurring_until'),
                    notes=get_value(row, 'notes'),
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                )
                db.session.add(expense)
            db.session.commit()
            print(f"✅ Migrados {len(expenses_data)} gastos")
        except sqlite3.OperationalError:
            print("⚠️  Tabla 'expenses' no existe en SQLite (es nueva)")

        # 7. Migrar Import Jobs (puede no existir)
        print("\n📦 Migrando import jobs...")
        try:
            cursor.execute("SELECT * FROM import_jobs ORDER BY id")
            jobs_data = cursor.fetchall()
            for row in jobs_data:
                job = ImportJob(
                    id=row['id'],
                    user_id=row['user_id'],
                    celery_task_id=get_value(row, 'celery_task_id'),
                    import_mode=get_value(row, 'import_mode'),
                    listing_status=get_value(row, 'listing_status'),
                    status=get_value(row, 'status', 'pending'),
                    total_items=get_value(row, 'total_items', 0),
                    processed_items=get_value(row, 'processed_items', 0),
                    imported_count=get_value(row, 'imported_count', 0),
                    updated_count=get_value(row, 'updated_count', 0),
                    skipped_count=get_value(row, 'skipped_count', 0),
                    error_count=get_value(row, 'error_count', 0),
                    error_message=get_value(row, 'error_message'),
                    started_at=get_value(row, 'started_at'),
                    completed_at=get_value(row, 'completed_at'),
                    created_at=row['created_at']
                )
                db.session.add(job)
            db.session.commit()
            print(f"✅ Migrados {len(jobs_data)} import jobs")
        except sqlite3.OperationalError:
            print("⚠️  Tabla 'import_jobs' no existe en SQLite (es nueva)")

        # 8. Migrar Subscriptions (si existen)
        print("\n📦 Migrando suscripciones...")
        try:
            cursor.execute("SELECT * FROM subscriptions ORDER BY id")
            subs_data = cursor.fetchall()
            for row in subs_data:
                sub = Subscription(
                    id=row['id'],
                    user_id=row['user_id'],
                    plan=get_value(row, 'plan', 'free'),
                    status=get_value(row, 'status', 'active'),
                    started_at=get_value(row, 'started_at'),
                    ends_at=get_value(row, 'ends_at'),
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                )
                db.session.add(sub)
            db.session.commit()
            print(f"✅ Migrados {len(subs_data)} suscripciones")
        except sqlite3.OperationalError:
            print("⚠️  Tabla subscriptions no existe (OK)")

        sqlite_conn.close()

        print("\n" + "="*60)
        print("✅ ¡MIGRACIÓN COMPLETADA EXITOSAMENTE!")
        print("="*60)
        print(f"\n📊 Resumen:")
        print(f"   • Usuarios: {len(users_data)}")
        print(f"   • Items: {len(items_data)}")
        print(f"   • Ventas: {len(sales_data)}")
        print(f"   • Gastos: {len(expenses_data)}")
        print(f"   • Credenciales: {len(creds_data)}")
        print(f"   • Settings: {len(settings_data)}")
        print(f"\n💡 Siguiente paso:")
        print(f"   Reinicia los servicios: sudo systemctl restart qventory celery-qventory")

if __name__ == '__main__':
    migrate_data()
