"""Decide which eBay listings can safely leave active inventory."""

import logging

LOGGER = logging.getLogger(__name__)


def confirmed_inactive_listing_ids(user_id, snapshot, active_listing_ids):
    """Require per-listing confirmation for large or empty inventory reductions.

    Never infer a closure from an API error, an unknown status, or a partial
    snapshot. Returned IDs are strings and only belong to the supplied account.
    """
    if not snapshot.get('success') or not snapshot.get('can_mark_inactive'):
        return set()

    active_ids = {str(value) for value in active_listing_ids if value}
    present_ids = {
        str(offer['ebay_listing_id'])
        for offer in snapshot.get('offers', [])
        if offer.get('ebay_listing_id')
    }
    missing_ids = active_ids - present_ids
    if not missing_ids or len(missing_ids) / len(active_ids) <= 0.15:
        return missing_ids

    from qventory.helpers.ebay_inventory import get_listing_status_trading_api

    confirmed = set()
    for listing_id in sorted(missing_ids):
        result = get_listing_status_trading_api(user_id, listing_id)
        if result.get('success') and result.get('status') in {'ENDED', 'COMPLETED'}:
            confirmed.add(listing_id)
        elif not result.get('success'):
            error = result.get('error', 'unknown_error')
            LOGGER.warning('Closure verification deferred user=%s listing=%s: %s',
                           user_id, listing_id, error)
            # An unavailable/old listing must not block the rest of an account.
            # Stop only for systemic failures such as throttling or lost access.
            if result.get('retryable') or error in {'http_429', 'no_access_token'}:
                break

    LOGGER.info('Closure verification user=%s missing=%s confirmed=%s deferred=%s',
                user_id, len(missing_ids), len(confirmed), len(missing_ids - confirmed))
    return confirmed
