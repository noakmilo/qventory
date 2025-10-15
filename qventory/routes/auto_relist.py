"""
Auto-Relist Routes
Handles UI and API endpoints for auto-relist feature
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, time as datetime_time
from sqlalchemy import desc
import sys

from ..extensions import db
from ..models.auto_relist_rule import AutoRelistRule, AutoRelistHistory
from ..helpers.ebay_inventory import get_active_listings

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
        # Fetch user's active eBay offers
        try:
            offers_result = get_active_listings(current_user.id, limit=200)
            offers = offers_result.get('offers', [])

            log_relist_route(f"Fetched {len(offers)} active offers for user {current_user.id}")

        except Exception as e:
            log_relist_route(f"Error fetching offers: {str(e)}")
            offers = []
            flash(f'Error loading eBay offers: {str(e)}', 'error')

        return render_template(
            'auto_relist/create.html',
            offers=offers
        )

    # POST: Create rule
    try:
        data = request.form

        # Basic validation
        offer_id = data.get('offer_id')
        mode = data.get('mode', 'auto')

        if not offer_id:
            flash('Offer ID is required', 'error')
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
            quiet_start = data.get('quiet_hours_start')
            quiet_end = data.get('quiet_hours_end')

            if quiet_start:
                h, m = map(int, quiet_start.split(':'))
                rule.quiet_hours_start = datetime_time(h, m)

            if quiet_end:
                h, m = map(int, quiet_end.split(':'))
                rule.quiet_hours_end = datetime_time(h, m)

            rule.timezone = data.get('timezone', 'America/Los_Angeles')

            # Safety rules
            rule.min_hours_since_last_order = int(data.get('min_hours_since_last_order', 48))
            rule.check_active_returns = data.get('check_active_returns') == 'on'
            rule.require_positive_quantity = data.get('require_positive_quantity') == 'on'
            rule.check_duplicate_skus = data.get('check_duplicate_skus') == 'on'
            rule.pause_on_error = data.get('pause_on_error') == 'on'
            rule.max_consecutive_errors = int(data.get('max_consecutive_errors', 3))

            # Calculate first run
            rule.calculate_next_run()

        # Common settings
        rule.withdraw_publish_delay_seconds = int(data.get('withdraw_publish_delay_seconds', 30))
        rule.notes = data.get('notes')

        db.session.add(rule)
        db.session.commit()

        log_relist_route(f"Created rule {rule.id} for user {current_user.id}")

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
            quiet_start = data.get('quiet_hours_start')
            quiet_end = data.get('quiet_hours_end')

            if quiet_start:
                h, m = map(int, quiet_start.split(':'))
                rule.quiet_hours_start = datetime_time(h, m)
            else:
                rule.quiet_hours_start = None

            if quiet_end:
                h, m = map(int, quiet_end.split(':'))
                rule.quiet_hours_end = datetime_time(h, m)
            else:
                rule.quiet_hours_end = None

            rule.timezone = data.get('timezone', 'America/Los_Angeles')

            # Safety rules
            rule.min_hours_since_last_order = int(data.get('min_hours_since_last_order', 48))
            rule.check_active_returns = data.get('check_active_returns') == 'on'
            rule.require_positive_quantity = data.get('require_positive_quantity') == 'on'
            rule.check_duplicate_skus = data.get('check_duplicate_skus') == 'on'
            rule.pause_on_error = data.get('pause_on_error') == 'on'
            rule.max_consecutive_errors = int(data.get('max_consecutive_errors', 3))

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

        db.session.delete(rule)
        db.session.commit()

        return jsonify({'success': True})

    except Exception as e:
        log_relist_route(f"Error deleting rule: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


# ==================== MANUAL RELIST ====================

@auto_relist_bp.route('/<int:rule_id>/relist-now', methods=['POST'])
@login_required
def relist_now(rule_id):
    """
    Trigger immediate relist for a rule
    Can optionally include changes to price/title/description
    """
    try:
        rule = AutoRelistRule.query.filter_by(
            id=rule_id,
            user_id=current_user.id
        ).first_or_404()

        data = request.get_json() or {}

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

        # Set pending changes if any
        if changes:
            rule.set_pending_changes(**changes)
        else:
            rule.clear_pending_changes()

        # Trigger manual relist
        if rule.mode == 'manual':
            rule.trigger_manual_relist()
        else:
            # For auto rules, just set next_run to now
            rule.next_run_at = datetime.utcnow()

        db.session.commit()

        # Trigger Celery task immediately
        from ..tasks import auto_relist_offers
        auto_relist_offers.delay()

        return jsonify({
            'success': True,
            'message': 'Relist job queued. Check history in a few moments.',
            'has_changes': bool(changes)
        })

    except Exception as e:
        log_relist_route(f"Error triggering relist: {str(e)}")
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
