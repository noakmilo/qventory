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
            from qventory.helpers.ebay_scraper import scrape_ebay_sold_listings, format_listings_for_ai
            import openai
            import os

            # Get item data
            item_title = report.item_title
            condition = "Used"
            market_region = "US"
            currency = "USD"

            if report.item_id:
                item = Item.query.get(report.item_id)
                if item:
                    condition = item.condition or "Used"

            # STEP 1: Scrape eBay
            print(f"[Report {report_id}] Scraping eBay...", file=sys.stderr)
            scraped_data = scrape_ebay_sold_listings(item_title, max_results=10)
            report.scraped_count = scraped_data.get('count', 0)
            db.session.commit()

            print(f"[Report {report_id}] Scraped {report.scraped_count} listings", file=sys.stderr)

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

            openai.api_key = os.environ.get("OPENAI_API_KEY")

            response = openai.ChatCompletion.create(
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
    """View all reports page"""
    # Cleanup expired reports
    Report.cleanup_expired()

    # Get user reports
    reports = Report.get_user_reports(current_user.id)

    return render_template("reports.html", reports=reports)


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
