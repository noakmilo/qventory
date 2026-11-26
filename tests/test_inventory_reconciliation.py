from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
from flask import Flask

from qventory.extensions import db
from qventory.helpers import ebay_inventory as ebay
from qventory.helpers.inventory_reconciliation import confirmed_inactive_listing_ids
from qventory.models.item import Item
from qventory.models.marketplace_credential import MarketplaceCredential
from qventory.models.setting import Setting
from qventory.models.user import User
from qventory.models.sale import Sale
from qventory.models.system_setting import SystemSetting
from qventory.routes import main as main_routes
from qventory.routes.webhooks_platform import parse_platform_notification
from qventory import tasks


def snapshot(ids=(), complete=True):
    return {'success': True, 'can_mark_inactive': complete,
            'offers': [{'ebay_listing_id': str(i)} for i in ids]}


def test_large_reduction_confirms_ids_instead_of_blocking_account(monkeypatch):
    statuses = {'2': 'Completed', '3': 'Active', '4': 'Ended'}
    monkeypatch.setattr(ebay, 'get_listing_status_trading_api',
                        lambda user, listing: {'success': True, 'status': statuses[listing].upper()})
    assert confirmed_inactive_listing_ids(22, snapshot(['1']), ['1', '2', '3', '4']) == {'2', '4'}


@pytest.mark.parametrize('complete', [False, True])
def test_empty_inventory_requires_complete_snapshot_and_confirmed_closures(monkeypatch, complete):
    calls = []

    def status(user, listing):
        calls.append(listing)
        return {'success': True, 'status': 'COMPLETED'}

    monkeypatch.setattr(ebay, 'get_listing_status_trading_api', status)
    assert confirmed_inactive_listing_ids(22, snapshot(complete=complete), ['1', '2']) == (
        {'1', '2'} if complete else set())
    assert len(calls) == (2 if complete else 0)


def test_verification_error_defers_unconfirmed_ids(monkeypatch):
    calls = []

    def status(user, listing):
        calls.append((user, listing))
        return {'success': False, 'error': 'http_429'}

    monkeypatch.setattr(ebay, 'get_listing_status_trading_api', status)
    assert confirmed_inactive_listing_ids(22, snapshot(), ['1', '2']) == set()
    assert calls == [(22, '1')]


def test_unavailable_old_listing_does_not_block_other_closures(monkeypatch):
    monkeypatch.setattr(ebay, 'get_listing_status_trading_api', lambda user, listing:
                        {'success': False, 'error': 'api_failure'} if listing == '1'
                        else {'success': True, 'status': 'COMPLETED'})
    assert confirmed_inactive_listing_ids(22, snapshot(), ['1', '2']) == {'2'}


def test_small_reduction_uses_complete_snapshot(monkeypatch):
    def unexpected(*args):
        pytest.fail('Small complete reductions do not need extra calls')

    monkeypatch.setattr(ebay, 'get_listing_status_trading_api', unexpected)
    assert confirmed_inactive_listing_ids(22, snapshot(range(1, 10)), range(1, 11)) == {'10'}


@pytest.mark.parametrize('complete', [False, True])
def test_snapshot_preserves_empty_trading_response_metadata(monkeypatch, complete):
    monkeypatch.setattr(ebay, 'fetch_ebay_inventory_offers',
                        lambda *a, **k: {'success': False, 'error': 'offers_api_disabled'})
    monkeypatch.setattr(ebay, 'get_active_listings_trading_api',
                        lambda *a, **k: ([], {'is_complete': complete, 'expected_total': 0}))
    result = ebay.fetch_active_listings_snapshot(22)
    assert result['offers'] == []
    assert result['can_mark_inactive'] is complete


def test_trading_empty_response_is_complete_only_with_explicit_zero_total(monkeypatch):
    monkeypatch.setattr(ebay, 'get_user_access_token', lambda user: 'test-token')
    xml = '''<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents">
      <Ack>Success</Ack><ActiveList><PaginationResult>
      <TotalNumberOfPages>0</TotalNumberOfPages><TotalNumberOfEntries>0</TotalNumberOfEntries>
      </PaginationResult></ActiveList></GetMyeBaySellingResponse>'''
    response = SimpleNamespace(status_code=200, content=xml.encode())
    monkeypatch.setattr(ebay.requests, 'post', lambda *a, **k: response)
    items, meta = ebay.get_active_listings_trading_api(22, collect_failures=False, return_meta=True)
    assert items == []
    assert meta['is_complete'] is True
    response.content = xml.replace('<TotalNumberOfEntries>0</TotalNumberOfEntries>', '').encode()
    _, meta = ebay.get_active_listings_trading_api(22, collect_failures=False, return_meta=True)
    assert meta['is_complete'] is False


def test_truncated_trading_page_is_not_safe_for_closures(monkeypatch):
    monkeypatch.setattr(ebay, 'get_user_access_token', lambda user: 'test-token')
    xml = '''<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents">
      <Ack>Success</Ack><ActiveList><PaginationResult>
      <TotalNumberOfPages>1</TotalNumberOfPages><TotalNumberOfEntries>2</TotalNumberOfEntries>
      </PaginationResult><ItemArray><Item><ItemID>1</ItemID><Title>A</Title></Item>
      <Item><ItemID>2</ItemID><Title>B</Title></Item></ItemArray></ActiveList>
      </GetMyeBaySellingResponse>'''
    monkeypatch.setattr(ebay.requests, 'post', lambda *a, **k: SimpleNamespace(
        status_code=200, content=xml.encode()))
    items, meta = ebay.get_active_listings_trading_api(22, max_items=1,
                                                     collect_failures=False, return_meta=True)
    assert len(items) == 1
    assert meta['is_complete'] is False


@pytest.mark.parametrize('ack,status,returned_id,success', [
    ('Success', 'Completed', '123', True),
    ('Success', 'Active', '123', True),
    ('Failure', 'Completed', '123', False),
    ('Success', '', '123', False),
    ('Success', 'Completed', '999', False),
])
def test_get_item_requires_success_matching_id_and_status(monkeypatch, ack, status, returned_id, success):
    monkeypatch.setattr(ebay, 'get_user_access_token', lambda user: 'test-token')
    xml = f'''<GetItemResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>{ack}</Ack>
      <Item><ItemID>{returned_id}</ItemID><SellingStatus><ListingStatus>{status}</ListingStatus>
      </SellingStatus></Item></GetItemResponse>'''
    def post(*args, **kwargs):
        # Trading requires the XML declaration; without it eBay's gateway
        # returns ErrorCode 5 even though the request is valid XML locally.
        assert kwargs['data'].startswith('<?xml version="1.0" encoding="utf-8"?>')
        return SimpleNamespace(status_code=200, content=xml.encode())

    monkeypatch.setattr(ebay.requests, 'post', post)
    assert ebay.get_listing_status_trading_api(22, '123')['success'] is success


@pytest.mark.parametrize('event,expected', [('ItemClosed', 'EndItem'), ('ItemListed', 'AddItem'),
                                         ('ItemRevised', 'ReviseItem'), ('ItemSold', 'ItemSold')])
def test_platform_parser_uses_event_name_with_shared_response_tag(event, expected):
    xml = f'''<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
      <s:Body><GetItemResponse xmlns="urn:ebay:apis:eBLBaseComponents">
      <NotificationEventName>{event}</NotificationEventName>
      <Item><ItemID>123</ItemID><Seller><UserID>seller</UserID></Seller></Item>
      </GetItemResponse></s:Body></s:Envelope>'''
    assert parse_platform_notification(ET.fromstring(xml))['notification_type'] == expected


@pytest.fixture
def inventory_app():
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SECRET_KEY='test')
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(db.engine, tables=[User.__table__, Item.__table__,
                               MarketplaceCredential.__table__, Setting.__table__,
                               Sale.__table__, SystemSetting.__table__])
        db.session.add(User(id=22, email='test@example.com', username='test', password_hash='unused'))
        db.session.add(MarketplaceCredential(user_id=22, marketplace='ebay', is_active=True))
        db.session.add_all([
            Item(id=1, user_id=22, title='Ended', sku='ONE', ebay_listing_id='123', is_active=True,
                 item_price=10),
            Item(id=2, user_id=22, title='Manual', sku='TWO', is_active=True),
        ])
        db.session.commit()
        yield app
        db.session.remove()


def test_manual_sync_at_plan_limit_deactivates_without_deleting_history(inventory_app, monkeypatch):
    monkeypatch.setattr(main_routes, 'current_user', SimpleNamespace(
        id=22, role='free', is_god_mode=False,
        get_plan_limits=lambda: SimpleNamespace(max_items=1, max_marketplace_integrations=1)))
    monkeypatch.setattr(ebay, 'fetch_active_listings_snapshot', lambda user: snapshot())
    monkeypatch.setattr(ebay, 'get_listing_status_trading_api',
                        lambda *a: {'success': True, 'status': 'COMPLETED'})
    with inventory_app.test_request_context('/sync-ebay-inventory', method='POST'):
        response = main_routes.sync_ebay_inventory.__wrapped__()
        assert response.get_json()['deleted'] == 1
        assert db.session.get(Item, 1).is_active is False
        assert db.session.get(Item, 2).is_active is True
        assert Item.query.count() == 2


@pytest.mark.parametrize('status,expected_active', [('COMPLETED', False), ('ACTIVE', True)])
def test_end_notification_checks_current_state(inventory_app, monkeypatch, status, expected_active):
    monkeypatch.setattr(ebay, 'get_listing_status_trading_api',
                        lambda *a: {'success': True, 'status': status})
    result = tasks.process_end_item_notification(SimpleNamespace(user_id=22, payload={'item_id': '123'}))
    assert result['status'] == 'success'
    assert db.session.get(Item, 1).is_active is expected_active
    assert Item.query.count() == 2


@pytest.mark.parametrize('task_name', ['reconcile_user_inventory',
                                     'sync_ebay_active_inventory_auto',
                                     'sync_and_purge_inactive_items'])
@pytest.mark.parametrize('complete', [True, False])
def test_background_paths_preserve_history_and_reconcile_only_confirmed_items(
        inventory_app, monkeypatch, task_name, complete):
    from datetime import datetime
    from qventory.helpers import item_limits

    user = db.session.get(User, 22)
    cred = MarketplaceCredential.query.first()
    db.session.add(Sale(user_id=22, item_id=1, marketplace='ebay',
                        item_title='Ended', sold_price=10, sold_at=datetime.utcnow()))
    db.session.add(User(id=23, email='other@example.com', username='other', password_hash='unused'))
    db.session.add(Item(id=3, user_id=23, title='Other account', sku='THREE',
                        ebay_listing_id='123', is_active=True, item_price=10))
    db.session.commit()
    monkeypatch.setattr(tasks, 'create_app', lambda: inventory_app)
    monkeypatch.setattr(tasks, '_is_ebay_quiet_window', lambda: False)
    monkeypatch.setattr(tasks, 'get_active_users_with_ebay', lambda **kw: [(user, cred)])
    monkeypatch.setattr(tasks, 'get_user_batch', lambda users, **kw: users)
    monkeypatch.setattr(item_limits, 'get_item_limit_status',
                        lambda *a, **kw: SimpleNamespace(remaining=0))
    monkeypatch.setattr(ebay, 'fetch_active_listings_snapshot', lambda user: snapshot(complete=complete))
    monkeypatch.setattr(ebay, 'get_listing_status_trading_api',
                        lambda *a: {'success': True, 'status': 'COMPLETED'})
    task = getattr(tasks, task_name)
    task.run(22) if task_name == 'reconcile_user_inventory' else task.run()
    assert db.session.get(Item, 1).is_active is (not complete)
    assert db.session.get(Item, 2).is_active is True
    assert db.session.get(Item, 3).is_active is True
    assert Sale.query.one().item_id == 1
    assert Item.query.count() == 3


def test_repair_script_reports_without_changing_inventory(inventory_app, monkeypatch, capsys):
    import qventory
    import reconcile_inventory
    import sys

    monkeypatch.setattr(qventory, 'create_app', lambda: inventory_app)
    monkeypatch.setattr(sys, 'argv', ['reconcile_inventory.py', '--user-id', '22'])
    monkeypatch.setattr(ebay, 'fetch_active_listings_snapshot', lambda user: snapshot())
    monkeypatch.setattr(ebay, 'get_listing_status_trading_api',
                        lambda *a: {'success': True, 'status': 'COMPLETED'})
    reconcile_inventory.main()
    assert '"mode": "report"' in capsys.readouterr().out
    assert db.session.get(Item, 1).is_active is True


def test_auto_sync_still_limits_reactivations(inventory_app, monkeypatch):
    from qventory.helpers import item_limits

    user = db.session.get(User, 22)
    cred = MarketplaceCredential.query.first()
    db.session.add(Item(id=4, user_id=22, title='Inactive', sku='FOUR',
                        ebay_listing_id='456', is_active=False, item_price=10))
    db.session.commit()
    monkeypatch.setattr(tasks, 'create_app', lambda: inventory_app)
    monkeypatch.setattr(tasks, '_is_ebay_quiet_window', lambda: False)
    monkeypatch.setattr(tasks, 'get_active_users_with_ebay', lambda **kw: [(user, cred)])
    monkeypatch.setattr(tasks, 'get_user_batch', lambda users, **kw: users)
    monkeypatch.setattr(item_limits, 'get_item_limit_status',
                        lambda *a, **kw: SimpleNamespace(remaining=0))
    monkeypatch.setattr(ebay, 'fetch_active_listings_snapshot', lambda user: snapshot(['123', '456']))
    tasks.sync_ebay_active_inventory_auto.run()
    assert db.session.get(Item, 1).is_active is True
    assert db.session.get(Item, 4).is_active is False
