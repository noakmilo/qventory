"""
Auto-Relist Rule Model
Manages automatic and manual end/relist cycles for eBay offers

Two modes:
1. AUTO: Scheduled relist every N days (no changes to listing)
2. MANUAL: User-triggered relist with optional price/title/description changes
"""
from datetime import datetime, timedelta
from ..extensions import db


class AutoRelistRule(db.Model):
    """
    Auto-relist configuration for eBay offers
    Supports both scheduled auto-relist and manual relist with modifications
    """
    __tablename__ = "auto_relist_rules"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # eBay identifiers
    offer_id = db.Column(db.String(100), nullable=False, index=True)
    sku = db.Column(db.String(100), index=True)
    inventory_item_id = db.Column(db.String(100))  # eBay inventory item ID
    marketplace_id = db.Column(db.String(50), default='EBAY_US')

    # Display info (cached from offer for UI convenience)
    item_title = db.Column(db.String(500))
    current_price = db.Column(db.Float)
    listing_id = db.Column(db.String(100))  # Current active listing ID

    # MODE: 'auto' or 'manual'
    mode = db.Column(db.String(20), nullable=False, default='auto', index=True)
    # 'auto' = scheduled automatic relist (no changes)
    # 'manual' = one-time relist triggered by user (can include changes)

    # ========== AUTO MODE SETTINGS ==========

    # Scheduling - User-configurable frequency (only for auto mode)
    frequency = db.Column(db.String(20), default='weekly')
    # Options: 'daily', 'every_3_days', 'weekly', 'every_10_days', 'biweekly',
    #          'every_20_days', 'monthly', 'custom'

    custom_interval_days = db.Column(db.Integer)  # Used when frequency='custom'

    # Time constraints (only for auto mode)
    quiet_hours_start = db.Column(db.Time)  # Start of preferred time window (e.g., 02:00)
    quiet_hours_end = db.Column(db.Time)    # End of preferred time window (e.g., 05:00)
    timezone = db.Column(db.String(50), default='America/Los_Angeles')

    # Safety rules - All user-configurable
    min_hours_since_last_order = db.Column(db.Integer, default=48)
    check_active_returns = db.Column(db.Boolean, default=True)
    require_positive_quantity = db.Column(db.Boolean, default=True)
    check_duplicate_skus = db.Column(db.Boolean, default=True)
    pause_on_error = db.Column(db.Boolean, default=True)
    max_consecutive_errors = db.Column(db.Integer, default=3)  # Pause after N errors

    # Price decrease strategy (only for auto mode)
    enable_price_decrease = db.Column(db.Boolean, default=False)
    price_decrease_type = db.Column(db.String(20))  # 'fixed' or 'percentage'
    price_decrease_amount = db.Column(db.Float)  # Amount to decrease (e.g., 2.00 or 10.0 for 10%)
    min_price = db.Column(db.Float)  # Minimum price floor (don't go below this)

    # First run behavior (only for auto mode)
    run_first_relist_immediately = db.Column(db.Boolean, default=False)
    # If True, first relist runs ASAP. If False, waits for full interval.

    # ========== MANUAL MODE SETTINGS ==========

    # Pending changes to apply before publish (only for manual mode)
    pending_changes = db.Column(db.JSON)
    # Structure: {
    #   'price': 29.99,
    #   'title': 'New optimized title',
    #   'description': 'Updated description',
    #   'quantity': 5,
    #   'condition': 'NEW'  # or other eBay condition
    # }

    apply_changes = db.Column(db.Boolean, default=False)
    # If True, update offer with pending_changes before publishing

    # Manual execution flag
    manual_trigger_requested = db.Column(db.Boolean, default=False)
    # Set to True when user clicks "Relist Now"

    # ========== COMMON SETTINGS ==========

    # Delays
    withdraw_publish_delay_seconds = db.Column(db.Integer, default=30)

    # Status & tracking
    enabled = db.Column(db.Boolean, default=True, index=True)
    next_run_at = db.Column(db.DateTime, index=True)
    last_run_at = db.Column(db.DateTime)
    last_run_status = db.Column(db.String(50))  # 'success', 'error', 'skipped', 'pending'
    last_error_message = db.Column(db.Text)
    last_new_listing_id = db.Column(db.String(100))

    # Counters
    run_count = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    error_count = db.Column(db.Integer, default=0)
    consecutive_errors = db.Column(db.Integer, default=0)  # Reset on success

    # Metadata
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship("User", backref="auto_relist_rules")

    def __repr__(self):
        mode_str = f"[{self.mode.upper()}]"
        return f'<AutoRelistRule {self.id}: {mode_str} {self.item_title or self.sku}>'

    def get_interval_days(self):
        """
        Get the interval in days based on frequency setting (auto mode only)

        Returns:
            int: Number of days between relists
        """
        if self.mode == 'manual':
            return None  # Manual mode has no interval

        frequency_map = {
            'daily': 1,
            'every_3_days': 3,
            'weekly': 7,
            'every_10_days': 10,
            'biweekly': 14,
            'every_20_days': 20,
            'monthly': 30,
            'custom': self.custom_interval_days or 7
        }

        return frequency_map.get(self.frequency, 7)

    def calculate_next_run(self, from_time=None):
        """
        Calculate next execution time based on mode and frequency

        Args:
            from_time: Optional datetime to calculate from (default: now)

        Returns:
            datetime: Next scheduled run time (None for manual mode)
        """
        # Manual mode: only runs when manually triggered
        if self.mode == 'manual':
            if self.manual_trigger_requested:
                self.next_run_at = datetime.utcnow()
            else:
                self.next_run_at = None
            return self.next_run_at

        # Auto mode: calculate based on frequency
        try:
            from pytz import timezone as pytz_timezone

            # Get current time in user's timezone
            tz = pytz_timezone(self.timezone)
            now = from_time or datetime.now(tz)

            # Check if this is the first run (never executed before)
            is_first_run = self.run_count == 0

            # Calculate base next run time
            interval_days = self.get_interval_days()
            if not interval_days:
                interval_days = 7  # Fallback

            # If first run and user wants immediate execution, schedule ASAP
            if is_first_run and self.run_first_relist_immediately:
                # Schedule 10 seconds in the past to ensure it's picked up immediately
                next_run = now - timedelta(seconds=10)
                # IMPORTANT: Skip quiet hours for immediate first run
                skip_quiet_hours = True
            else:
                next_run = now + timedelta(days=interval_days)
                skip_quiet_hours = False

            # Apply quiet hours window if configured (but not for immediate first run)
            if self.quiet_hours_start and self.quiet_hours_end and not skip_quiet_hours:
                # Set time to start of quiet hours window
                next_run = next_run.replace(
                    hour=self.quiet_hours_start.hour,
                    minute=self.quiet_hours_start.minute,
                    second=0,
                    microsecond=0
                )

                # If the calculated time already passed today, move to next day
                if next_run <= now:
                    next_run += timedelta(days=1)

            # Convert to UTC for storage (remove timezone info)
            self.next_run_at = next_run.astimezone(pytz_timezone('UTC')).replace(tzinfo=None)

        except Exception as e:
            # Fallback: just add interval days to current UTC time
            now_utc = from_time or datetime.utcnow()
            interval_days = self.get_interval_days() or 7
            self.next_run_at = now_utc + timedelta(days=interval_days)

        return self.next_run_at

    def set_pending_changes(self, price=None, title=None, description=None, quantity=None, condition=None):
        """
        Set pending changes for manual relist mode

        Args:
            price: New listing price
            title: New title
            description: New description
            quantity: New quantity
            condition: New condition code
        """
        if self.mode != 'manual':
            return  # Only for manual mode

        changes = {}

        if price is not None:
            changes['price'] = float(price)

        if title is not None:
            changes['title'] = str(title).strip()

        if description is not None:
            changes['description'] = str(description).strip()

        if quantity is not None:
            changes['quantity'] = int(quantity)

        if condition is not None:
            changes['condition'] = str(condition).upper()

        self.pending_changes = changes if changes else None
        self.apply_changes = bool(changes)

    def clear_pending_changes(self):
        """Clear pending changes"""
        self.pending_changes = None
        self.apply_changes = False

    def trigger_manual_relist(self):
        """
        Trigger manual relist execution
        Sets the flag for immediate processing
        """
        if self.mode == 'manual':
            self.manual_trigger_requested = True
            self.next_run_at = datetime.utcnow()

    def mark_success(self, new_listing_id):
        """
        Mark rule execution as successful

        Args:
            new_listing_id: New eBay listing ID generated
        """
        self.last_run_status = 'success'
        self.last_run_at = datetime.utcnow()
        self.last_new_listing_id = new_listing_id
        self.listing_id = new_listing_id  # Update current listing ID
        self.last_error_message = None

        self.run_count += 1
        self.success_count += 1
        self.consecutive_errors = 0  # Reset error counter

        # Clear manual trigger and pending changes
        if self.mode == 'manual':
            self.manual_trigger_requested = False
            self.clear_pending_changes()

        # Calculate next run (auto mode only)
        self.calculate_next_run()

    def mark_error(self, error_message):
        """
        Mark rule execution as failed

        Args:
            error_message: Error description
        """
        self.last_run_status = 'error'
        self.last_run_at = datetime.utcnow()
        self.last_error_message = error_message

        self.run_count += 1
        self.error_count += 1
        self.consecutive_errors += 1

        # Auto-disable if too many consecutive errors (auto mode only)
        if self.mode == 'auto' and self.pause_on_error and self.consecutive_errors >= self.max_consecutive_errors:
            self.enabled = False

        # Clear manual trigger on error
        if self.mode == 'manual':
            self.manual_trigger_requested = False

        # Calculate next run (auto mode only)
        if self.mode == 'auto':
            self.calculate_next_run()

    def mark_skipped(self, reason):
        """
        Mark rule execution as skipped (safety check failed)

        Args:
            reason: Skip reason description
        """
        self.last_run_status = 'skipped'
        self.last_run_at = datetime.utcnow()
        self.last_error_message = f'Skipped: {reason}'

        self.run_count += 1

        # Clear manual trigger on skip
        if self.mode == 'manual':
            self.manual_trigger_requested = False

        # Calculate next run (auto mode only)
        if self.mode == 'auto':
            self.calculate_next_run()

    @property
    def is_due(self):
        """Check if rule is due to run"""
        if not self.enabled:
            return False

        # Manual mode: check if manually triggered
        if self.mode == 'manual':
            return self.manual_trigger_requested

        # Auto mode: check if next_run_at has passed
        if not self.next_run_at:
            return False

        return self.next_run_at <= datetime.utcnow()

    @property
    def success_rate(self):
        """Calculate success rate percentage"""
        if self.run_count == 0:
            return 0.0

        return (self.success_count / self.run_count) * 100

    @property
    def has_pending_changes(self):
        """Check if there are pending changes to apply"""
        return self.apply_changes and self.pending_changes is not None

    def calculate_new_price(self):
        """
        Calculate new price with decrease applied (auto mode only)

        Returns:
            float: New price after decrease, respecting min_price
            None: If price decrease not enabled or current_price not set
        """
        if self.mode != 'auto' or not self.enable_price_decrease:
            return None

        if not self.current_price or not self.price_decrease_amount:
            return None

        # Calculate new price based on decrease type
        if self.price_decrease_type == 'fixed':
            new_price = self.current_price - self.price_decrease_amount
        elif self.price_decrease_type == 'percentage':
            # percentage is stored as whole number (e.g., 10 for 10%)
            decrease_multiplier = self.price_decrease_amount / 100.0
            new_price = self.current_price * (1 - decrease_multiplier)
        else:
            return None

        # Apply minimum price floor
        if self.min_price and new_price < self.min_price:
            new_price = self.min_price

        # Round to 2 decimals
        return round(new_price, 2)

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'offer_id': self.offer_id,
            'sku': self.sku,
            'inventory_item_id': self.inventory_item_id,
            'item_title': self.item_title,
            'current_price': self.current_price,
            'listing_id': self.listing_id,
            'mode': self.mode,
            'frequency': self.frequency,
            'custom_interval_days': self.custom_interval_days,
            'interval_days': self.get_interval_days(),
            'quiet_hours_start': self.quiet_hours_start.strftime('%H:%M') if self.quiet_hours_start else None,
            'quiet_hours_end': self.quiet_hours_end.strftime('%H:%M') if self.quiet_hours_end else None,
            'quiet_hours_enabled': bool(self.quiet_hours_start and self.quiet_hours_end),
            'timezone': self.timezone,
            'min_hours_since_last_order': self.min_hours_since_last_order,
            'check_active_returns': self.check_active_returns,
            'require_positive_quantity': self.require_positive_quantity,
            'check_duplicate_skus': self.check_duplicate_skus,
            'pause_on_error': self.pause_on_error,
            'max_consecutive_errors': self.max_consecutive_errors,
            'enable_price_decrease': self.enable_price_decrease,
            'price_decrease_type': self.price_decrease_type,
            'price_decrease_amount': self.price_decrease_amount,
            'min_price': self.min_price,
            'run_first_relist_immediately': self.run_first_relist_immediately,
            'pending_changes': self.pending_changes,
            'apply_changes': self.apply_changes,
            'has_pending_changes': self.has_pending_changes,
            'manual_trigger_requested': self.manual_trigger_requested,
            'withdraw_publish_delay_seconds': self.withdraw_publish_delay_seconds,
            'enabled': self.enabled,
            'next_run_at': self.next_run_at.isoformat() if self.next_run_at else None,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'last_run_status': self.last_run_status,
            'last_error_message': self.last_error_message,
            'last_new_listing_id': self.last_new_listing_id,
            'run_count': self.run_count,
            'success_count': self.success_count,
            'error_count': self.error_count,
            'consecutive_errors': self.consecutive_errors,
            'success_rate': self.success_rate,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class AutoRelistHistory(db.Model):
    """
    Execution history for auto-relist rules
    Tracks every withdraw/publish cycle for auditing
    """
    __tablename__ = "auto_relist_history"

    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey("auto_relist_rules.id", ondelete='CASCADE'),
                       nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True, index=True)
    sku = db.Column(db.String(100), index=True)

    # Execution timing
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    completed_at = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer)

    # Execution context
    mode = db.Column(db.String(20))  # 'auto' or 'manual'
    changes_applied = db.Column(db.JSON)  # Copy of pending_changes if applied

    # Results
    status = db.Column(db.String(50), nullable=False, index=True)  # 'success', 'error', 'skipped'
    old_listing_id = db.Column(db.String(100))
    new_listing_id = db.Column(db.String(100))

    # Pricing changes (for tracking)
    old_price = db.Column(db.Float)
    new_price = db.Column(db.Float)
    old_title = db.Column(db.String(500))
    new_title = db.Column(db.String(500))

    # Error tracking
    error_message = db.Column(db.Text)
    error_code = db.Column(db.String(50))
    skip_reason = db.Column(db.String(500))

    # Raw API responses (for debugging)
    withdraw_response = db.Column(db.JSON)
    update_response = db.Column(db.JSON)  # If changes were applied
    publish_response = db.Column(db.JSON)

    # Relationships
    rule = db.relationship("AutoRelistRule", backref="history")
    user = db.relationship("User", backref="auto_relist_history")

    def __repr__(self):
        return f'<AutoRelistHistory {self.id}: Rule {self.rule_id} - {self.status}>'

    def mark_completed(self):
        """Mark execution as completed and calculate duration"""
        self.completed_at = datetime.utcnow()

        if self.started_at:
            delta = self.completed_at - self.started_at
            self.duration_seconds = int(delta.total_seconds())

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'rule_id': self.rule_id,
            'user_id': self.user_id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration_seconds': self.duration_seconds,
            'mode': self.mode,
            'changes_applied': self.changes_applied,
            'status': self.status,
            'old_listing_id': self.old_listing_id,
            'new_listing_id': self.new_listing_id,
            'old_price': self.old_price,
            'new_price': self.new_price,
            'old_title': self.old_title,
            'new_title': self.new_title,
            'error_message': self.error_message,
            'error_code': self.error_code,
            'skip_reason': self.skip_reason,
        }
