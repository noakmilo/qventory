"""
Auto-Relist Routes
Handles UI and API endpoints for auto-relist feature
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, time as datetime_time, timedelta
from sqlalchemy import desc
import sys

from ..extensions import db
from ..models.auto_relist_rule import AutoRelistRule, AutoRelistHistory
from ..helpers.ebay_inventory import fetch_ebay_inventory_offers

auto_relist_bp = Blueprint('auto_relist', __name__, url_prefix='/auto-relist')


def log_relist_route(msg):
    """Helper for logging"""
    print(f"[AUTO_RELIST_ROUTE] {msg}", file=sys.stderr, flush=True)


# ==================== DASHBOARD ====================

@auto_relist_bp.route('/')
@login_required
def dashboard():
    """
    Main auto-relist dashboard
    Shows all rules and recent history
    """
    # Get user's rules
    rules = AutoRelistRule.query.filter_by(
        user_id=current_user.id
    ).order_by(desc(AutoRelistRule.created_at)).all()

    # Get recent history (last 50 executions)
    history = AutoRelistHistory.query.filter_by(
        user_id=current_user.id
    ).order_by(desc(AutoRelistHistory.started_at)).limit(50).all()

    # Calculate stats
    total_rules = len(rules)
    active_rules = sum(1 for r in rules if r.enabled)
    auto_rules = sum(1 for r in rules if r.mode == 'auto')
    manual_rules = sum(1 for r in rules if r.mode == 'manual')

    # Success rate
    total_runs = sum(r.run_count for r in rules)
    total_success = sum(r.success_count for r in rules)
    success_rate = (total_success / total_runs * 100) if total_runs > 0 else 0

    return render_template(
        'auto_relist/dashboard.html',
        rules=rules,
        history=history,
        stats={
            'total_rules': total_rules,
            'active_rules': active_rules,
            'auto_rules': auto_rules,
            'manual_rules': manual_rules,
            'total_runs': total_runs,
            'total_success': total_success,
            'success_rate': success_rate
        }
    )


# ==================== CREATE RULE ====================

@auto_relist_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_rule():
    """
    Create new auto-relist rule
    GET: Show form with available offers
    POST: Create rule
    """
    if request.method == 'GET':
        # Simply render the form - items are loaded dynamically via AJAX autocomplete
        log_relist_route(f"Rendering create form for user {current_user.id}")
        prefill_item = None
        item_id = request.args.get('item_id')
        if item_id:
            try:
                from ..models.item import Item
                item = Item.query.filter_by(
                    id=int(item_id),
                    user_id=current_user.id,
                    is_active=True
                ).first()
                if item and item.ebay_listing_id:
                    prefill_item = {
                        'offer_id': item.ebay_listing_id,
                        'listing_id': item.ebay_listing_id,
                        'title': item.title,
                        'sku': item.sku or '',
                        'price': float(item.item_price) if item.item_price is not None else None,
                        'quantity': item.quantity or 0,
                        'image_url': item.item_thumb
                    }
            except (ValueError, TypeError):
                prefill_item = None
        return render_template('auto_relist/create.html', prefill_item=prefill_item)

    # POST: Create rule
    try:
        data = request.form
        log_relist_route(f"Creating rule - Form data keys: {list(data.keys())}")
        log_relist_route(f"Creating rule - offer_id raw value: '{data.get('offer_id')}'")
        log_relist_route(f"Creating rule - Full form data: {dict(data)}")

        # Basic validation
        # offer_id can be either an actual offerId (Inventory API) or listingId (Trading API legacy)
        offer_id = data.get('offer_id')
        mode = data.get('mode', 'auto')

        log_relist_route(f"Extracted: offer_id='{offer_id}' (type: {type(offer_id)}), mode={mode}")

        # Validate offer_id - must not be empty, 'None', or None
        # Note: For legacy listings, this will be the listingId
        if not offer_id or offer_id == 'None' or offer_id.strip() == '':
            log_relist_route(f"ERROR: Invalid offer_id/listing_id provided: '{offer_id}'")
            flash('Listing ID is required. Please select a valid listing from the list.', 'error')
            return redirect(url_for('auto_relist.create_rule'))

        # Check if rule already exists
        existing = AutoRelistRule.query.filter_by(
            user_id=current_user.id,
            offer_id=offer_id
        ).first()

        if existing:
            flash('A rule already exists for this offer', 'error')
            return redirect(url_for('auto_relist.dashboard'))

        # Create rule
        log_relist_route(f"Creating AutoRelistRule object with:")
        log_relist_route(f"  offer_id={offer_id}")
        log_relist_route(f"  sku={data.get('sku')}")
        log_relist_route(f"  item_title={data.get('item_title')}")
        log_relist_route(f"  current_price={data.get('current_price')}")
        log_relist_route(f"  listing_id={data.get('listing_id')}")

        rule = AutoRelistRule(
            user_id=current_user.id,
            offer_id=offer_id,
            sku=data.get('sku'),
            marketplace_id=data.get('marketplace_id', 'EBAY_US'),
            item_title=data.get('item_title'),
            current_price=float(data.get('current_price')) if data.get('current_price') else None,
            listing_id=data.get('listing_id'),
            mode=mode
        )

        # Mode-specific settings
        if mode == 'auto':
            rule.frequency = data.get('frequency', 'weekly')

            if rule.frequency == 'custom':
                rule.custom_interval_days = int(data.get('custom_interval_days', 7))

            # Quiet hours
            quiet_enabled = data.get('enable_quiet_hours') == 'on'
            if quiet_enabled:
                quiet_start = data.get('quiet_hours_start')
                quiet_end = data.get('quiet_hours_end')

                if quiet_start and quiet_end:
                    h_start, m_start = map(int, quiet_start.split(':'))
                    h_end, m_end = map(int, quiet_end.split(':'))
                    rule.quiet_hours_start = datetime_time(h_start, m_start)
                    rule.quiet_hours_end = datetime_time(h_end, m_end)
                else:
                    rule.quiet_hours_start = None
                    rule.quiet_hours_end = None
            else:
                rule.quiet_hours_start = None
                rule.quiet_hours_end = None

            rule.timezone = data.get('timezone', 'America/Los_Angeles')

            # Safety rules
            rule.min_hours_since_last_order = int(data.get('min_hours_since_last_order', 48))
            rule.check_active_returns = data.get('check_active_returns') == 'on'
            rule.require_positive_quantity = data.get('require_positive_quantity') == 'on'
            rule.check_duplicate_skus = data.get('check_duplicate_skus') == 'on'
            rule.pause_on_error = data.get('pause_on_error') == 'on'
            rule.max_consecutive_errors = int(data.get('max_consecutive_errors', 3))

            # Price decrease settings (auto mode only)
            rule.enable_price_decrease = data.get('enable_price_decrease') == 'on'
            if rule.enable_price_decrease:
                rule.price_decrease_type = data.get('price_decrease_type', 'fixed')
                rule.price_decrease_amount = float(data.get('price_decrease_amount', 0))
                min_price_val = data.get('min_price')
                rule.min_price = float(min_price_val) if min_price_val else None

            # First run behavior
            rule.run_first_relist_immediately = data.get('run_first_relist_immediately') == 'on'

            # Calculate first run
            rule.calculate_next_run()

            if rule.run_first_relist_immediately:
                rule.next_run_at = datetime.utcnow() - timedelta(seconds=5)

        # Common settings
        rule.withdraw_publish_delay_seconds = int(data.get('withdraw_publish_delay_seconds', 30))
        rule.notes = data.get('notes')

        db.session.add(rule)
        db.session.commit()

        log_relist_route(f"Created rule {rule.id} for user {current_user.id}")

        # If user wants first relist immediately, trigger it now (auto mode only)
        if mode == 'auto' and rule.run_first_relist_immediately:
            from ..tasks import auto_relist_offers
            auto_relist_offers.delay()
            flash(f'Auto-relist rule created and first relist triggered! Check history in a few minutes.', 'success')
        else:
            flash(f'Auto-relist rule created successfully! ({mode} mode)', 'success')

        return redirect(url_for('auto_relist.dashboard'))

    except Exception as e:
        log_relist_route(f"Error creating rule: {str(e)}")
        import traceback
        log_relist_route(traceback.format_exc())
        db.session.rollback()
        flash(f'Error creating rule: {str(e)}', 'error')
        return redirect(url_for('auto_relist.create_rule'))


# ==================== EDIT RULE ====================

@auto_relist_bp.route('/<int:rule_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_rule(rule_id):
    """Edit existing rule"""
    rule = AutoRelistRule.query.filter_by(
        id=rule_id,
        user_id=current_user.id
    ).first_or_404()

    if request.method == 'GET':
        return render_template('auto_relist/edit.html', rule=rule)

    # POST: Update rule
    try:
        data = request.form

        rule.mode = data.get('mode', rule.mode)

        if rule.mode == 'auto':
            rule.frequency = data.get('frequency', 'weekly')

            if rule.frequency == 'custom':
                rule.custom_interval_days = int(data.get('custom_interval_days', 7))

            # Quiet hours
            quiet_enabled = data.get('enable_quiet_hours') == 'on'
            if quiet_enabled:
                quiet_start = data.get('quiet_hours_start')
                quiet_end = data.get('quiet_hours_end')

                if quiet_start and quiet_end:
                    h_start, m_start = map(int, quiet_start.split(':'))
                    h_end, m_end = map(int, quiet_end.split(':'))
                    rule.quiet_hours_start = datetime_time(h_start, m_start)
                    rule.quiet_hours_end = datetime_time(h_end, m_end)
                else:
                    rule.quiet_hours_start = None
                    rule.quiet_hours_end = None
            else:
                rule.quiet_hours_start = None
                rule.quiet_hours_end = None

            rule.timezone = data.get('timezone', 'America/Los_Angeles')

            # Safety rules
            rule.min_hours_since_last_order = int(data.get('min_hours_since_last_order', 48))
            rule.check_active_returns = data.get('check_active_returns') == 'on'
            rule.require_positive_quantity = data.get('require_positive_quantity') == 'on'
            rule.check_duplicate_skus = data.get('check_duplicate_skus') == 'on'
            rule.pause_on_error = data.get('pause_on_error') == 'on'
            rule.max_consecutive_errors = int(data.get('max_consecutive_errors', 3))

            # Price decrease settings (auto mode only)
            rule.enable_price_decrease = data.get('enable_price_decrease') == 'on'
            if rule.enable_price_decrease:
                rule.price_decrease_type = data.get('price_decrease_type', 'fixed')
                rule.price_decrease_amount = float(data.get('price_decrease_amount', 0))
                min_price_val = data.get('min_price')
                rule.min_price = float(min_price_val) if min_price_val else None
            else:
                # Clear price decrease settings if disabled
                rule.price_decrease_type = None
                rule.price_decrease_amount = None
                rule.min_price = None

            # Recalculate next run
            rule.calculate_next_run()

        rule.withdraw_publish_delay_seconds = int(data.get('withdraw_publish_delay_seconds', 30))
        rule.notes = data.get('notes')
        rule.updated_at = datetime.utcnow()

        db.session.commit()

        flash('Rule updated successfully!', 'success')
        return redirect(url_for('auto_relist.dashboard'))

    except Exception as e:
        log_relist_route(f"Error updating rule: {str(e)}")
        db.session.rollback()
        flash(f'Error updating rule: {str(e)}', 'error')
        return redirect(url_for('auto_relist.edit_rule', rule_id=rule_id))


# ==================== TOGGLE ENABLE/DISABLE ====================

@auto_relist_bp.route('/<int:rule_id>/toggle', methods=['POST'])
@login_required
def toggle_rule(rule_id):
    """Enable/disable a rule"""
    try:
        rule = AutoRelistRule.query.filter_by(
            id=rule_id,
            user_id=current_user.id
        ).first_or_404()

        rule.enabled = not rule.enabled

        if rule.enabled and rule.mode == 'auto':
            # Recalculate next run when re-enabling
            rule.calculate_next_run()

        db.session.commit()

        return jsonify({
            'success': True,
            'enabled': rule.enabled,
            'next_run_at': rule.next_run_at.isoformat() if rule.next_run_at else None
        })

    except Exception as e:
        log_relist_route(f"Error toggling rule: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400


# ==================== DELETE RULE ====================

@auto_relist_bp.route('/<int:rule_id>/delete', methods=['DELETE', 'POST'])
@login_required
def delete_rule(rule_id):
    """Delete a rule"""
    try:
        rule = AutoRelistRule.query.filter_by(
            id=rule_id,
            user_id=current_user.id
        ).first_or_404()

        # Delete all history records first (to avoid foreign key constraint errors)
        AutoRelistHistory.query.filter_by(rule_id=rule_id).delete()

        # Now delete the rule
        db.session.delete(rule)
        db.session.commit()

        return jsonify({'success': True})

    except Exception as e:
        log_relist_route(f"Error deleting rule: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


# ==================== SEARCH ITEMS API (AJAX) ====================

@auto_relist_bp.route('/api/search-items', methods=['GET'])
@login_required
def search_items_api():
    """
    AJAX endpoint to search active eBay listings with autocomplete
    Returns JSON with items matching search query

    Query params:
        q: Search query (title, SKU, listing ID)
        limit: Max results (default 10)

    Response:
        {
            'success': True,
            'items': [
                {
                    'offer_id': '123456',
                    'listing_id': '376512345678',
                    'title': 'Sony PlayStation 5 Console',
                    'sku': 'A1-B2-S3-C4',
                    'price': 499.99,
                    'quantity': 1,
                    'image_url': 'https://...',
                    'views': 234  # if available
                }
            ],
            'total': 5
        }
    """
    try:
        query = request.args.get('q', '').strip()
        limit = int(request.args.get('limit', 10))

        # Return empty if no query
        if not query or len(query) < 2:
            return jsonify({'success': True, 'items': [], 'total': 0})

        from ..models.item import Item
        from sqlalchemy import or_

        log_relist_route(f"Searching items for query: '{query}' (limit: {limit})")

        # Search in items table (same as Active Inventory search)
        # Only items with ebay_listing_id (active on eBay)
        search_pattern = f'%{query}%'

        items_query = Item.query.filter(
            Item.user_id == current_user.id,
            Item.is_active == True,
            Item.ebay_listing_id.isnot(None),  # Must have eBay listing
            or_(
                Item.title.ilike(search_pattern),
                Item.sku.ilike(search_pattern)
            )
        ).limit(limit).all()

        log_relist_route(f"Found {len(items_query)} items in database matching '{query}'")

        # Format results for autocomplete
        filtered_items = []
        for item in items_query:
            item_data = {
                'offer_id': item.ebay_listing_id,  # Use listing_id as offer_id
                'listing_id': item.ebay_listing_id,
                'title': item.title,
                'sku': item.sku or '',
                'price': item.item_price,
                'quantity': item.quantity or 0,
                'image_url': item.item_thumb  # Cloudinary URL
            }
            filtered_items.append(item_data)

        return jsonify({
            'success': True,
            'items': filtered_items,
            'total': len(filtered_items)
        })

    except Exception as e:
        log_relist_route(f"Error searching items: {str(e)}")
        import traceback
        log_relist_route(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== MANUAL RELIST ====================

@auto_relist_bp.route('/<int:rule_id>/relist-now', methods=['POST'])
@login_required
def relist_now(rule_id):
    """
    Trigger immediate relist for a rule
    Can optionally include changes to price/title/description
    """
    try:
        log_relist_route(f"Received relist-now request for rule {rule_id}")
        log_relist_route(f"Request Content-Type: {request.content_type}")
        log_relist_route(f"Request data: {request.data[:200] if request.data else 'empty'}")

        rule = AutoRelistRule.query.filter_by(
            id=rule_id,
            user_id=current_user.id
        ).first_or_404()

        log_relist_route(f"Found rule: ID={rule.id}, Mode={rule.mode}, Offer={rule.offer_id}")

        # Handle both JSON and form data, and handle missing body
        try:
            data = request.get_json(force=True, silent=True) or {}
            log_relist_route(f"Parsed JSON data: {data}")
        except Exception as e:
            log_relist_route(f"JSON parsing failed: {e}")
            data = {}

        # Fallback to form data if JSON parsing failed
        if not data:
            data = request.form.to_dict()
            log_relist_route(f"Using form data: {data}")

        # Check if changes were requested
        changes = {}

        if 'price' in data and data['price']:
            changes['price'] = float(data['price'])

        if 'title' in data and data['title']:
            changes['title'] = data['title']

        if 'description' in data and data['description']:
            changes['description'] = data['description']

        if 'quantity' in data and data['quantity']:
            changes['quantity'] = int(data['quantity'])

        log_relist_route(f"Changes requested: {changes if changes else 'None'}")

        # Set pending changes if any
        if changes:
            rule.set_pending_changes(**changes)
            log_relist_route(f"Set pending_changes on rule")
        else:
            rule.clear_pending_changes()
            log_relist_route(f"Cleared pending_changes on rule")

        # Trigger manual relist
        if rule.mode == 'manual':
            log_relist_route(f"Triggering manual relist")
            rule.trigger_manual_relist()
        else:
            log_relist_route(f"Setting next_run_at to now for auto rule")
            rule.next_run_at = datetime.utcnow()

        db.session.commit()
        log_relist_route(f"Database committed successfully")

        # Trigger Celery task immediately
        log_relist_route(f"Queueing Celery task...")
        from ..tasks import auto_relist_offers
        task = auto_relist_offers.delay()
        log_relist_route(f"Celery task queued: {task.id}")

        return jsonify({
            'success': True,
            'message': 'Relist job queued. Check history in a few moments.',
            'has_changes': bool(changes),
            'task_id': str(task.id)
        })

    except Exception as e:
        log_relist_route(f"Error triggering relist: {str(e)}")
        import traceback
        log_relist_route(f"Traceback: {traceback.format_exc()}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


# ==================== HISTORY ====================

@auto_relist_bp.route('/history')
@login_required
def history():
    """View full execution history"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    pagination = AutoRelistHistory.query.filter_by(
        user_id=current_user.id
    ).order_by(desc(AutoRelistHistory.started_at)).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    return render_template(
        'auto_relist/history.html',
        history=pagination.items,
        pagination=pagination
    )


# ==================== API: GET RULE DETAILS ====================

@auto_relist_bp.route('/<int:rule_id>/details')
@login_required
def get_rule_details(rule_id):
    """Get full rule details as JSON"""
    try:
        rule = AutoRelistRule.query.filter_by(
            id=rule_id,
            user_id=current_user.id
        ).first_or_404()

        return jsonify({
            'success': True,
            'rule': rule.to_dict()
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 404


# ==================== API: GET AVAILABLE OFFERS ====================

@auto_relist_bp.route('/debug/rules')
@login_required
def debug_rules():
    """Debug endpoint to see rule execution status"""
    from datetime import datetime

    rules = AutoRelistRule.query.filter_by(user_id=current_user.id).all()

    debug_info = []
    now = datetime.utcnow()

    for rule in rules:
        time_diff = None
        if rule.next_run_at:
            time_diff = (rule.next_run_at - now).total_seconds() / 60  # minutes

        debug_info.append({
            'id': rule.id,
            'item_title': rule.item_title,
            'enabled': rule.enabled,
            'mode': rule.mode,
            'frequency': rule.frequency,
            'run_first_immediately': rule.run_first_relist_immediately,
            'next_run_at': rule.next_run_at.isoformat() if rule.next_run_at else None,
            'current_time_utc': now.isoformat(),
            'minutes_until_run': round(time_diff, 2) if time_diff else None,
            'ready_to_run': rule.next_run_at <= now if rule.next_run_at else False,
            'run_count': rule.run_count,
            'success_count': rule.success_count,
            'last_run_status': rule.last_run_status,
            'last_run_at': rule.last_run_at.isoformat() if rule.last_run_at else None,
            'manual_trigger_requested': getattr(rule, 'manual_trigger_requested', False)
        })

    return jsonify({
        'success': True,
        'current_time_utc': now.isoformat(),
        'rules': debug_info,
        'total_rules': len(rules),
        'enabled_rules': sum(1 for r in rules if r.enabled)
    })


@auto_relist_bp.route('/api/offers')
@login_required
def get_available_offers():
    """
    Get list of user's active eBay offers that can be relisted
    Returns only offers that don't already have a rule
    """
    try:
        # Get all active offers
        offers_result = get_active_listings(current_user.id, limit=200)
        all_offers = offers_result.get('offers', [])

        # Get existing rule offer_ids
        existing_rules = AutoRelistRule.query.filter_by(
            user_id=current_user.id
        ).all()
        existing_offer_ids = {r.offer_id for r in existing_rules}

        # Filter out offers that already have rules
        available_offers = [
            {
                'offerId': offer.get('offerId'),
                'sku': offer.get('sku'),
                'title': offer.get('title'),
                'price': offer.get('pricingSummary', {}).get('price', {}).get('value'),
                'quantity': offer.get('availableQuantity'),
                'listingId': offer.get('listingId'),
                'status': offer.get('status')
            }
            for offer in all_offers
            if offer.get('offerId') not in existing_offer_ids
        ]

        return jsonify({
            'success': True,
            'offers': available_offers,
            'total': len(available_offers)
        })

    except Exception as e:
        log_relist_route(f"Error fetching available offers: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400
