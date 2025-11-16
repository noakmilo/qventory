from qventory.helpers.ebay_inventory import deduplicate_ebay_items


def test_deduplicate_by_listing_id():
    payload = [
        {'ebay_listing_id': '123', 'product': {'title': 'Camera'}, 'source': 'trading_api'},
        {'ebay_listing_id': '123', 'product': {'title': 'Camera duplicate'}, 'source': 'trading_api'},
        {'ebay_listing_id': '456', 'product': {'title': 'Lens'}, 'source': 'trading_api'},
    ]

    deduped, duplicates = deduplicate_ebay_items(payload)

    assert len(deduped) == 2
    assert len(duplicates) == 1
    assert any(item.get('ebay_listing_id') == '456' for item in deduped)


def test_deduplicate_without_listing_id_uses_title_sku_price():
    payload = [
        {
            'ebay_listing_id': '',
            'sku': 'SKU-1',
            'item_price': 19.99,
            'product': {'title': 'Vintage Shirt'},
            'source': 'browse_api'
        },
        {
            'listing_id': None,
            'sku': 'SKU-1',
            'item_price': 19.99,
            'product': {'title': 'Vintage Shirt'},
            'source': 'browse_api'
        },
        {
            'listing_id': None,
            'sku': 'SKU-2',
            'item_price': 19.99,
            'product': {'title': 'Vintage Shirt'},
            'source': 'browse_api'
        },
    ]

    deduped, duplicates = deduplicate_ebay_items(payload)

    assert len(deduped) == 2  # SKU-1 collapsed, SKU-2 kept
    assert len(duplicates) == 1
