"""
AI Research Reports Routes
Handles async report generation, viewing, and notifications
"""
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from flask_login import login_required, current_user
from qventory import db
from qventory.models.report import Report
from qventory.models.item import Item
import json
import threading
import traceback
import sys

reports_bp = Blueprint('reports', __name__)


def process_report_async(report_id):
    """
    Background task to process AI research report
    This runs in a separate thread
    """
    from qventory import create_app
    from flask import current_app

    # Get app instance - either from current context or create new one
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        # No app context available, create new app
        app = create_app()

    with app.app_context():
        try:
            report = Report.query.get(report_id)
            if not report:
                return

            print(f"[Report {report_id}] Starting async processing...", file=sys.stderr)

            # Import here to avoid circular imports
            from qventory.helpers.ebay_api_scraper import get_sold_listings_ebay_api, format_listings_for_ai
            from openai import OpenAI
            import os

            # Get item data
            item_title = report.item_title
            condition = "Used"  # Default condition
            market_region = "US"
            currency = "USD"

            # STEP 1: Get sold listings from eBay API (last 7 days)
            print(f"[Report {report_id}] Fetching sold listings from eBay API...", file=sys.stderr)
            scraped_data = get_sold_listings_ebay_api(item_title, max_results=10, days_back=7)
            report.scraped_count = scraped_data.get('count', 0)
            db.session.commit()

            print(f"[Report {report_id}] Found {report.scraped_count} sold listings (last 7 days)", file=sys.stderr)

            # Save examples
            examples = []
            for item in scraped_data.get('items', [])[:3]:
                examples.append({
                    'title': item['title'],
                    'price': item['price'],
                    'link': item['link']
                })
            report.examples_json = json.dumps(examples)
            db.session.commit()

            # STEP 2: Format for AI
            real_market_data = format_listings_for_ai(scraped_data)
            ebay_search_url = scraped_data.get('url', '')

            # STEP 3: Call OpenAI
            print(f"[Report {report_id}] Calling OpenAI...", file=sys.stderr)

            system_prompt = """You are an eBay pricing analyst. You MUST respond with ONLY pure HTML code.
NO explanations, NO markdown, NO code blocks - just raw HTML starting with <div."""

            user_prompt = f"""Analyze REAL eBay sold listings data for: {item_title}
Condition: {condition}
Market: {market_region}

REAL SOLD LISTINGS DATA:
{real_market_data}

Based on this REAL market data above, provide:
1. Accurate pricing strategy
2. Title optimization tips based on what's actually selling
3. Market insights from the real data

RESPOND WITH ONLY THIS HTML (no ```html, no explanations):

<div style="font-family:system-ui;line-height:1.5;color:#e8e8e8;font-size:13px">
  <div style="background:#1a1d24;padding:10px;border-radius:6px;margin-bottom:10px">
    <div style="color:#9ca3af;font-size:12px;margin-bottom:6px">📊 Market Analysis</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      <div><span style="color:#60a5fa">●</span> Price Range: ${currency}XX-XX</div>
      <div><span style="color:#60a5fa">●</span> Average: ${currency}XX</div>
    </div>
  </div>

  <div style="background:#1a1d24;padding:10px;border-radius:6px;margin-bottom:10px">
    <div style="color:#9ca3af;font-size:12px;margin-bottom:6px">💰 Pricing Strategy</div>
    <div style="margin-bottom:4px"><strong style="color:#34d399">List Price:</strong> ${currency}XX.XX</div>
    <div style="margin-bottom:4px"><strong style="color:#fbbf24">Minimum Accept:</strong> ${currency}XX.XX</div>
    <div style="margin-bottom:6px"><strong style="color:#f87171">Auto-Decline:</strong> Below ${currency}XX</div>
    <div style="color:#9ca3af;font-size:11px">💡 Format: BIN + Best Offer | Shipping: [Free/Calculated based on trends]</div>
  </div>

  <div style="background:#1a1d24;padding:10px;border-radius:6px;margin-bottom:10px">
    <div style="color:#9ca3af;font-size:12px;margin-bottom:6px">✨ Title Optimization</div>
    <div style="font-size:11px;color:#e8e8e8;line-height:1.6">
      <div style="margin-bottom:4px"><strong style="color:#34d399">Keywords found in sold listings:</strong></div>
      <div style="color:#9ca3af">• [Analyze real titles and list common keywords/patterns]</div>
      <div style="margin-top:6px"><strong style="color:#fbbf24">Suggested title format:</strong></div>
      <div style="color:#9ca3af">[Brand] [Model] [Key Specs] [Condition] - [Unique Features]</div>
    </div>
  </div>

  <div style="background:#1a1d24;padding:10px;border-radius:6px">
    <div style="color:#9ca3af;font-size:12px;margin-bottom:6px">📝 Market Insights</div>
    <div style="font-size:11px;color:#9ca3af;line-height:1.5">[2-3 sentences analyzing the market: what's selling, at what prices, and why. Include specific observations from the real data.]</div>
    <div style="margin-top:8px;padding:6px;background:#0f1115;border-radius:4px;font-size:10px;color:#6b7280">
      ✅ Based on {len(scraped_data.get('items', []))} real sold listings | <a href="{ebay_search_url}" target="_blank" style="color:#60a5fa;text-decoration:none">View on eBay ↗</a>
    </div>
  </div>
</div>
"""

            # Initialize OpenAI client with API key
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=2000
            )

            result = response.choices[0].message.content.strip()

            # Clean markdown
            if result.startswith("```html"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]
            result = result.strip()

            # Save result
            report.result_html = result
            report.status = 'completed'
            report.completed_at = db.func.now()
            db.session.commit()

            print(f"[Report {report_id}] ✅ Completed successfully", file=sys.stderr)

        except Exception as e:
            print(f"[Report {report_id}] ✗ Error: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

            report = Report.query.get(report_id)
            if report:
                report.status = 'failed'
                report.error_message = str(e)
                db.session.commit()


@reports_bp.route("/api/ai-research-async", methods=["POST"])
@login_required
def ai_research_async():
    """
    Start async AI research report generation
    Checks token availability before starting
    """
    try:
        # CHECK TOKEN AVAILABILITY
        can_use, remaining = current_user.can_use_ai_research()

        if not can_use:
            token_stats = current_user.get_ai_token_stats()
            return jsonify({
                "ok": False,
                "error": f"No AI tokens remaining. You have {token_stats['used_today']}/{token_stats['daily_limit']} used today.",
                "error_type": "no_tokens",
                "token_stats": token_stats
            }), 403

        data = request.get_json()
        item_id = data.get("item_id")

        # Get item title
        if item_id:
            item = Item.query.filter_by(id=item_id, user_id=current_user.id).first()
            if not item:
                return jsonify({"ok": False, "error": "Item not found"}), 404
            item_title = item.title
        else:
            item_title = data.get("title", "").strip()
            if not item_title:
                return jsonify({"ok": False, "error": "Item title is required"}), 400

        # CONSUME TOKEN
        current_user.consume_ai_token()
        print(f"[User {current_user.id}] Consumed 1 AI token, {remaining-1} remaining", file=sys.stderr)

        # Create report record
        report = Report(
            user_id=current_user.id,
            item_title=item_title,
            item_id=item_id,
            status='processing'
        )
        db.session.add(report)
        db.session.commit()

        # Start background processing
        thread = threading.Thread(target=process_report_async, args=(report.id,))
        thread.daemon = True
        thread.start()

        # Get updated token stats
        token_stats = current_user.get_ai_token_stats()

        return jsonify({
            "ok": True,
            "report_id": report.id,
            "message": "Report generation started",
            "token_stats": token_stats
        })

    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"ok": False, "error": str(e)}), 500


@reports_bp.route("/api/reports/<int:report_id>/status")
@login_required
def report_status(report_id):
    """Check status of a report"""
    report = Report.query.filter_by(id=report_id, user_id=current_user.id).first()

    if not report:
        return jsonify({"ok": False, "error": "Report not found"}), 404

    return jsonify({
        "ok": True,
        "status": report.status,
        "scraped_count": report.scraped_count,
        "created_at": report.created_at.isoformat(),
        "completed_at": report.completed_at.isoformat() if report.completed_at else None
    })


@reports_bp.route("/api/reports/unread-count")
@login_required
def unread_count():
    """Get count of unread reports"""
    count = Report.get_unread_count(current_user.id)
    return jsonify({"ok": True, "count": count})


@reports_bp.route("/api/ai-tokens/stats")
@login_required
def token_stats():
    """Get user's AI token statistics"""
    stats = current_user.get_ai_token_stats()
    return jsonify({"ok": True, "stats": stats})


@reports_bp.route("/reports")
@login_required
def reports_page():
    """DEPRECATED - Redirect to analytics"""
    return redirect(url_for('reports.analytics'))


@reports_bp.route("/api/import-ebay-sales", methods=["POST"])
@login_required
def import_ebay_sales_route():
    """Trigger eBay sales import"""
    try:
        from qventory.tasks import import_ebay_sales

        # Get days_back parameter (None = all time)
        days_back_str = request.form.get('days_back', '').strip()
        days_back = int(days_back_str) if days_back_str and days_back_str.lower() != 'all' else None

        # Trigger Celery task
        task = import_ebay_sales.delay(current_user.id, days_back=days_back)

        if days_back:
            flash(f"eBay sales import started (last {days_back} days). This may take a few minutes.", "ok")
        else:
            flash("eBay sales import started (ALL TIME - lifetime). This may take several minutes.", "ok")

        return redirect(url_for('reports.analytics'))

    except Exception as e:
        flash(f"Error starting import: {str(e)}", "error")
        return redirect(url_for('reports.analytics'))


@reports_bp.route("/analytics")
@login_required
def analytics():
    """Business insights and analytics dashboard"""
    from qventory.models.sale import Sale
    from qventory.models.item import Item
    from qventory.models.listing import Listing
    from qventory.models.marketplace_credential import MarketplaceCredential
    from sqlalchemy import func
    from datetime import datetime, timedelta

    # Check if eBay is connected
    ebay_connected = MarketplaceCredential.query.filter_by(
        user_id=current_user.id,
        marketplace='ebay'
    ).first() is not None

    # Get date range from query params (default: last 30 days)
    range_param = request.args.get('range', 'last_30_days')
    custom_start = request.args.get('start')
    custom_end = request.args.get('end')

    # Calculate date range
    now = datetime.utcnow()
    end_date = now

    if range_param == 'today':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_param == 'yesterday':
        end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = (end_date - timedelta(days=1))
    elif range_param == 'last_7_days':
        start_date = now - timedelta(days=7)
    elif range_param == 'last_30_days':
        start_date = now - timedelta(days=30)
    elif range_param == 'last_90_days':
        start_date = now - timedelta(days=90)
    elif range_param == 'week_to_date':
        start_date = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_param == 'month_to_date':
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif range_param == 'year_to_date':
        start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    elif range_param == 'all_time':
        start_date = datetime(2000, 1, 1)
    elif range_param == 'custom' and custom_start and custom_end:
        try:
            start_date = datetime.strptime(custom_start, "%Y-%m-%d")
            parsed_end = datetime.strptime(custom_end, "%Y-%m-%d")
            if parsed_end < start_date:
                start_date, parsed_end = parsed_end, start_date
            actual_end = parsed_end
            # make end exclusive by adding one day
            end_date = parsed_end + timedelta(days=1)
        except ValueError:
            range_param = 'last_30_days'
            start_date = now - timedelta(days=30)
            custom_start = ''
            custom_end = ''
        else:
            # cap end_date to now to avoid future dates
            if end_date > now + timedelta(days=1):
                end_date = now + timedelta(days=1)
                actual_end = now
            custom_start = start_date.strftime("%Y-%m-%d")
            custom_end = actual_end.strftime("%Y-%m-%d")
    else:
        start_date = now - timedelta(days=30)
        custom_start = '' if range_param != 'custom' else custom_start
        custom_end = '' if range_param != 'custom' else custom_end

    # Query sales in date range (only completed sales)
    sales_query = Sale.query.filter(
        Sale.user_id == current_user.id,
        Sale.sold_at >= start_date,
        Sale.sold_at < end_date,
        Sale.status.in_(['completed', 'shipped', 'paid'])
    )

    sales = sales_query.all()

    # Calculate metrics
    total_sales = len(sales)
    gross_sales = sum(s.sold_price for s in sales)
    total_costs = sum(s.item_cost or 0 for s in sales)
    total_fees = sum((s.marketplace_fee or 0) + (s.payment_processing_fee or 0) + (s.other_fees or 0) for s in sales)
    net_sales = sum(s.net_profit or 0 for s in sales)

    avg_gross_per_sale = gross_sales / total_sales if total_sales > 0 else 0
    avg_net_per_sale = net_sales / total_sales if total_sales > 0 else 0
    npm = (net_sales / gross_sales * 100) if gross_sales > 0 else 0

    # Active listings by supplier
    active_items = Item.query.filter_by(user_id=current_user.id, is_active=True).all()
    listings_by_supplier = {}
    for item in active_items:
        supplier = item.supplier or 'Unknown'
        if supplier not in listings_by_supplier:
            listings_by_supplier[supplier] = {'count': 0, 'value': 0}
        listings_by_supplier[supplier]['count'] += 1
        listings_by_supplier[supplier]['value'] += item.item_price or 0

    # Sales by marketplace
    sales_by_marketplace = {}
    for sale in sales:
        mp = sale.marketplace
        if mp not in sales_by_marketplace:
            sales_by_marketplace[mp] = {'count': 0, 'revenue': 0}
        sales_by_marketplace[mp]['count'] += 1
        sales_by_marketplace[mp]['revenue'] += sale.sold_price

    return render_template("analytics.html",
                         range_param=range_param,
                         total_sales=total_sales,
                         gross_sales=gross_sales,
                         net_sales=net_sales,
                         avg_gross_per_sale=avg_gross_per_sale,
                         avg_net_per_sale=avg_net_per_sale,
                         npm=npm,
                         listings_by_supplier=listings_by_supplier,
                         sales_by_marketplace=sales_by_marketplace,
                         sales=sales,
                         ebay_connected=ebay_connected,
                         custom_start=custom_start if range_param == 'custom' else '',
                         custom_end=custom_end if range_param == 'custom' else '')


@reports_bp.route("/api/reports/user-reports")
@login_required
def get_user_reports():
    """Get all reports for current user"""
    Report.cleanup_expired()

    reports = Report.query.filter_by(user_id=current_user.id)\
        .order_by(Report.created_at.desc())\
        .all()

    reports_data = []
    for report in reports:
        # Parse examples
        examples = []
        if report.examples_json:
            try:
                examples = json.loads(report.examples_json)
            except:
                pass

        reports_data.append({
            "id": report.id,
            "item_title": report.item_title,
            "status": report.status,
            "scraped_count": report.scraped_count or 0,
            "viewed": report.viewed,
            "created_at": report.created_at.isoformat(),
            "error_message": report.error_message
        })

    return jsonify({
        "ok": True,
        "reports": reports_data
    })


@reports_bp.route("/api/reports/<int:report_id>/view")
@login_required
def view_report(report_id):
    """Get report details and mark as viewed"""
    report = Report.query.filter_by(id=report_id, user_id=current_user.id).first()

    if not report:
        return jsonify({"ok": False, "error": "Report not found"}), 404

    # Mark as viewed
    report.viewed = True
    db.session.commit()

    # Parse examples
    examples = []
    if report.examples_json:
        try:
            examples = json.loads(report.examples_json)
        except:
            pass

    return jsonify({
        "ok": True,
        "report": {
            "id": report.id,
            "item_title": report.item_title,
            "status": report.status,
            "result_html": report.result_html,
            "examples": examples,
            "scraped_count": report.scraped_count,
            "created_at": report.created_at.isoformat(),
            "error_message": report.error_message
        }
    })


@reports_bp.route("/api/reports/<int:report_id>/delete", methods=["POST"])
@login_required
def delete_report(report_id):
    """Delete a report"""
    report = Report.query.filter_by(id=report_id, user_id=current_user.id).first()

    if not report:
        return jsonify({"ok": False, "error": "Report not found"}), 404

    db.session.delete(report)
    db.session.commit()

    return jsonify({"ok": True, "message": "Report deleted successfully"})
