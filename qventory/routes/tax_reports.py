"""
Tax Reports Blueprint
Routes for generating, viewing, and exporting tax reports
"""
from flask import Blueprint, render_template, jsonify, request, send_file, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime
import io
import csv
import json
from qventory.models.tax_report import TaxReport, TaxReportExport
from qventory.helpers.tax_calculator import TaxCalculator, get_or_create_tax_report
from qventory.extensions import db

tax_reports_bp = Blueprint('tax_reports', __name__, url_prefix='/tax-reports')


@tax_reports_bp.route('/')
@login_required
def index():
    """Tax reports dashboard - list all available reports"""
    current_year = datetime.now().year

    # Get all user's tax reports
    reports = TaxReport.query.filter_by(
        user_id=current_user.id
    ).order_by(TaxReport.tax_year.desc(), TaxReport.quarter.desc()).all()

    # Available years (last 3 years + current)
    available_years = list(range(current_year, current_year - 4, -1))

    return render_template(
        'tax_reports/index.html',
        reports=reports,
        available_years=available_years,
        current_year=current_year
    )


@tax_reports_bp.route('/<int:year>')
@login_required
def annual_report(year):
    """View annual tax report for specific year"""
    # Get or generate report
    report = get_or_create_tax_report(current_user.id, year)

    # Get calculator for additional insights
    calculator = TaxCalculator(current_user.id, year)

    return render_template(
        'tax_reports/annual_report.html',
        report=report,
        year=year
    )


@tax_reports_bp.route('/<int:year>/quarterly/<int:quarter>')
@login_required
def quarterly_report(year, quarter):
    """View quarterly tax report"""
    if quarter not in [1, 2, 3, 4]:
        flash('Invalid quarter. Please select 1-4.', 'error')
        return redirect(url_for('tax_reports.index'))

    # Get or generate quarterly report
    report = get_or_create_tax_report(current_user.id, year, quarter=quarter)

    return render_template(
        'tax_reports/quarterly_report.html',
        report=report,
        year=year,
        quarter=quarter
    )


@tax_reports_bp.route('/api/generate', methods=['POST'])
@login_required
def generate_report():
    """
    API endpoint to generate/regenerate tax report
    """
    data = request.get_json()
    year = data.get('year', datetime.now().year)
    quarter = data.get('quarter')  # Optional
    regenerate = data.get('regenerate', False)

    try:
        report = get_or_create_tax_report(
            current_user.id,
            year,
            quarter=quarter,
            regenerate=regenerate
        )

        return jsonify({
            'success': True,
            'report': report.to_dict(),
            'message': 'Tax report generated successfully'
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@tax_reports_bp.route('/api/<int:report_id>/summary')
@login_required
def get_report_summary(report_id):
    """Get tax report summary data (for AJAX)"""
    report = TaxReport.query.filter_by(
        id=report_id,
        user_id=current_user.id
    ).first_or_404()

    return jsonify({
        'success': True,
        'report': report.to_dict()
    })


@tax_reports_bp.route('/api/<int:report_id>/validation')
@login_required
def get_validation_issues(report_id):
    """Get data validation warnings for a report"""
    report = TaxReport.query.filter_by(
        id=report_id,
        user_id=current_user.id
    ).first_or_404()

    return jsonify({
        'success': True,
        'warnings': report.validation_warnings,
        'completeness_score': float(report.data_completeness_score) if report.data_completeness_score else 0,
        'needs_review': report.needs_review
    })


@tax_reports_bp.route('/api/<int:report_id>/finalize', methods=['POST'])
@login_required
def finalize_report(report_id):
    """Mark report as finalized (no more edits)"""
    report = TaxReport.query.filter_by(
        id=report_id,
        user_id=current_user.id
    ).first_or_404()

    if report.needs_review:
        return jsonify({
            'success': False,
            'error': 'Cannot finalize report with data quality issues. Please resolve warnings first.'
        }), 400

    report.status = 'finalized'
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Report finalized successfully'
    })


@tax_reports_bp.route('/export/<int:report_id>/csv')
@login_required
def export_csv(report_id):
    """
    Export tax report as CSV
    IMPROVEMENT: Multiple export formats
    """
    report = TaxReport.query.filter_by(
        id=report_id,
        user_id=current_user.id
    ).first_or_404()

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([f'Tax Report - {report.tax_year}'])
    writer.writerow([f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}'])
    writer.writerow([])

    # Revenue Section
    writer.writerow(['REVENUE'])
    writer.writerow(['Gross Sales Revenue', f'${report.gross_sales_revenue:,.2f}'])
    writer.writerow(['Shipping Revenue', f'${report.shipping_revenue:,.2f}'])
    writer.writerow(['Refunds', f'-${report.total_refunds:,.2f}'])
    writer.writerow(['Returns', f'-${report.total_returns:,.2f}'])
    writer.writerow(['Business Income', f'${report.business_income:,.2f}'])
    writer.writerow([])

    # Marketplace Breakdown
    writer.writerow(['SALES BY MARKETPLACE'])
    if report.marketplace_sales:
        for marketplace, data in report.marketplace_sales.items():
            writer.writerow([
                marketplace.upper(),
                f'${data.get("revenue", 0):,.2f}',
                f'{data.get("count", 0)} sales'
            ])
    writer.writerow([])

    # COGS Section
    writer.writerow(['COST OF GOODS SOLD (COGS)'])
    writer.writerow(['Total COGS', f'${report.total_cogs:,.2f}'])
    writer.writerow(['Items Sold', report.cogs_items_count])
    writer.writerow(['Missing Cost Data', report.cogs_missing_count])
    writer.writerow([])

    # Inventory
    writer.writerow(['INVENTORY'])
    writer.writerow(['Opening Inventory (Jan 1)', f'${report.opening_inventory_value:,.2f}'])
    writer.writerow(['Inventory Purchased', f'${report.inventory_purchased:,.2f}'])
    writer.writerow(['Closing Inventory (Dec 31)', f'${report.closing_inventory_value:,.2f}'])
    writer.writerow([])

    # Gross Profit
    writer.writerow(['GROSS PROFIT'])
    writer.writerow(['Gross Profit', f'${report.gross_profit:,.2f}'])
    writer.writerow([])

    # Expenses Section
    writer.writerow(['BUSINESS EXPENSES'])
    writer.writerow(['Marketplace Fees', f'${report.total_marketplace_fees:,.2f}'])
    writer.writerow(['Payment Processing Fees', f'${report.payment_processing_fees:,.2f}'])
    writer.writerow(['Shipping Costs', f'${report.total_shipping_costs:,.2f}'])
    writer.writerow(['Business Expenses', f'${report.total_business_expenses:,.2f}'])
    writer.writerow(['Total Expenses', f'${report.total_expenses:,.2f}'])
    writer.writerow([])

    # Expense Categories
    if report.expense_categories_breakdown:
        writer.writerow(['EXPENSE BREAKDOWN BY CATEGORY'])
        for category, amount in report.expense_categories_breakdown.items():
            writer.writerow([category, f'${amount:,.2f}'])
        writer.writerow([])

    # Net Profit
    writer.writerow(['NET PROFIT/LOSS'])
    writer.writerow(['Net Profit', f'${report.net_profit:,.2f}'])
    writer.writerow([])

    # Tax Estimates
    writer.writerow(['ESTIMATED TAXES'])
    writer.writerow(['Self-Employment Tax', f'${report.estimated_self_employment_tax:,.2f}'])
    writer.writerow(['Estimated Income Tax', f'${report.estimated_income_tax:,.2f}'])
    writer.writerow(['Quarterly Payment', f'${report.estimated_quarterly_tax:,.2f}'])
    writer.writerow([])

    # Data Quality
    writer.writerow(['DATA QUALITY'])
    writer.writerow(['Completeness Score', f'{report.data_completeness_score:.1f}%'])
    writer.writerow(['Validation Warnings', len(report.validation_warnings)])

    # Record export
    export_record = TaxReportExport(
        tax_report_id=report.id,
        user_id=current_user.id,
        export_format='csv',
        file_size=len(output.getvalue())
    )
    db.session.add(export_record)

    if 'csv' not in report.exported_formats:
        report.exported_formats.append('csv')
    report.last_exported_at = datetime.utcnow()
    db.session.commit()

    # Prepare file download
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'tax_report_{report.tax_year}_qventory.csv'
    )


@tax_reports_bp.route('/export/<int:report_id>/schedule-c')
@login_required
def export_schedule_c(report_id):
    """
    Export Schedule C data in JSON format
    IMPROVEMENT OVER FLIPWISE: Tax software integration
    """
    report = TaxReport.query.filter_by(
        id=report_id,
        user_id=current_user.id
    ).first_or_404()

    # Schedule C format (IRS Form 1040 Schedule C)
    schedule_c_data = {
        'form': 'Schedule C',
        'tax_year': report.tax_year,
        'business_name': f'{current_user.username} - Online Reselling',
        'business_code': '453310',  # NAICS: Used Merchandise Stores

        # Part I: Income
        'gross_receipts': float(report.gross_sales_revenue) if report.gross_sales_revenue else 0,
        'returns_allowances': float(report.total_refunds + report.total_returns) if (report.total_refunds and report.total_returns) else 0,
        'gross_income': float(report.business_income) if report.business_income else 0,

        # Part II: Expenses
        'advertising': 0,  # TODO: Add if tracked
        'car_truck_expenses': 0,  # TODO: Add mileage tracking
        'commissions_fees': float(report.total_marketplace_fees) if report.total_marketplace_fees else 0,
        'contract_labor': 0,
        'depletion': 0,
        'depreciation': 0,  # TODO: Add asset depreciation
        'employee_benefits': 0,
        'insurance': 0,  # TODO: Add business insurance
        'interest_mortgage': 0,
        'interest_other': 0,
        'legal_professional': 0,
        'office_expense': float(report.expense_categories_breakdown.get('Supplies', 0)) if report.expense_categories_breakdown else 0,
        'pension_profit_sharing': 0,
        'rent_vehicles': 0,
        'rent_property': float(report.expense_categories_breakdown.get('Rent/Storage', 0)) if report.expense_categories_breakdown else 0,
        'repairs_maintenance': 0,
        'supplies': float(report.expense_categories_breakdown.get('Supplies', 0)) if report.expense_categories_breakdown else 0,
        'taxes_licenses': 0,
        'travel': float(report.expense_categories_breakdown.get('Transportation', 0)) if report.expense_categories_breakdown else 0,
        'utilities': float(report.expense_categories_breakdown.get('Utilities', 0)) if report.expense_categories_breakdown else 0,
        'wages': 0,
        'other_expenses': float(report.total_business_expenses) if report.total_business_expenses else 0,

        # Part III: Cost of Goods Sold
        'inventory_beginning': float(report.opening_inventory_value) if report.opening_inventory_value else 0,
        'purchases': float(report.inventory_purchased) if report.inventory_purchased else 0,
        'cost_labor': 0,
        'materials_supplies': 0,
        'other_costs': 0,
        'inventory_ending': float(report.closing_inventory_value) if report.closing_inventory_value else 0,
        'cost_goods_sold': float(report.total_cogs) if report.total_cogs else 0,

        # Net Profit
        'net_profit_loss': float(report.net_profit) if report.net_profit else 0,

        # Metadata
        'generated_by': 'Qventory Tax Report System',
        'generated_at': datetime.utcnow().isoformat(),
        'data_completeness': float(report.data_completeness_score) if report.data_completeness_score else 0
    }

    # Record export
    export_record = TaxReportExport(
        tax_report_id=report.id,
        user_id=current_user.id,
        export_format='schedule_c_json',
        file_size=len(json.dumps(schedule_c_data))
    )
    db.session.add(export_record)

    if 'schedule_c' not in report.exported_formats:
        report.exported_formats.append('schedule_c')
    report.last_exported_at = datetime.utcnow()
    db.session.commit()

    return send_file(
        io.BytesIO(json.dumps(schedule_c_data, indent=2).encode('utf-8')),
        mimetype='application/json',
        as_attachment=True,
        download_name=f'schedule_c_{report.tax_year}_qventory.json'
    )


@tax_reports_bp.route('/export/<int:report_id>/quickbooks')
@login_required
def export_quickbooks_iif(report_id):
    """
    Export in QuickBooks IIF format
    IMPROVEMENT: Accounting software integration
    """
    report = TaxReport.query.filter_by(
        id=report_id,
        user_id=current_user.id
    ).first_or_404()

    # Create IIF file (QuickBooks Import Format)
    output = io.StringIO()

    # Header
    output.write('!TRNS\tTRNSID\tTRNSTYPE\tDATE\tACCNT\tNAME\tCLASS\tAMOUNT\tDOCNUM\tMEMO\n')
    output.write('!SPL\tSPLID\tTRNSTYPE\tDATE\tACCNT\tNAME\tCLASS\tAMOUNT\tDOCNUM\tMEMO\n')
    output.write('!ENDTRNS\n')

    # Sales Revenue Transaction
    output.write(f'TRNS\t\tGENERAL JOURNAL\t12/31/{report.tax_year}\tSales Revenue\t\t\t{report.gross_sales_revenue}\tYEAR-END\tAnnual Sales\n')
    output.write(f'SPL\t\tGENERAL JOURNAL\t12/31/{report.tax_year}\tAccounts Receivable\t\t\t-{report.gross_sales_revenue}\tYEAR-END\tAnnual Sales\n')
    output.write('ENDTRNS\n')

    # COGS Transaction
    output.write(f'TRNS\t\tGENERAL JOURNAL\t12/31/{report.tax_year}\tCost of Goods Sold\t\t\t{report.total_cogs}\tYEAR-END\tAnnual COGS\n')
    output.write(f'SPL\t\tGENERAL JOURNAL\t12/31/{report.tax_year}\tInventory Asset\t\t\t-{report.total_cogs}\tYEAR-END\tAnnual COGS\n')
    output.write('ENDTRNS\n')

    # Expenses Transaction
    output.write(f'TRNS\t\tGENERAL JOURNAL\t12/31/{report.tax_year}\tBusiness Expenses\t\t\t{report.total_expenses}\tYEAR-END\tAnnual Expenses\n')
    output.write(f'SPL\t\tGENERAL JOURNAL\t12/31/{report.tax_year}\tAccounts Payable\t\t\t-{report.total_expenses}\tYEAR-END\tAnnual Expenses\n')
    output.write('ENDTRNS\n')

    # Record export
    export_record = TaxReportExport(
        tax_report_id=report.id,
        user_id=current_user.id,
        export_format='quickbooks_iif',
        file_size=len(output.getvalue())
    )
    db.session.add(export_record)

    if 'quickbooks' not in report.exported_formats:
        report.exported_formats.append('quickbooks')
    report.last_exported_at = datetime.utcnow()
    db.session.commit()

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/plain',
        as_attachment=True,
        download_name=f'quickbooks_import_{report.tax_year}_qventory.iif'
    )


@tax_reports_bp.route('/api/<int:report_id>/tax-optimization')
@login_required
def get_tax_optimization_suggestions(report_id):
    """
    AI-powered tax optimization suggestions
    IMPROVEMENT: Smart tax advice
    """
    report = TaxReport.query.filter_by(
        id=report_id,
        user_id=current_user.id
    ).first_or_404()

    suggestions = []

    # Check if user is tracking all deductible expenses
    if report.total_business_expenses < (report.gross_sales_revenue * 0.1):
        suggestions.append({
            'category': 'expenses',
            'priority': 'high',
            'title': 'Low Expense Tracking Detected',
            'description': 'Your business expenses are less than 10% of revenue. You may be missing deductible expenses.',
            'action': 'Review common deductions: office supplies, storage rent, shipping materials, software subscriptions',
            'potential_savings': float(report.gross_sales_revenue * 0.05 * 0.25)  # Estimate 5% more expenses, 25% tax rate
        })

    # Check for missing COGS
    if report.cogs_missing_count > 0:
        potential_cogs = report.cogs_missing_count * (report.total_cogs / max(report.cogs_items_count, 1))
        potential_savings = potential_cogs * 0.25  # 25% tax rate
        suggestions.append({
            'category': 'cogs',
            'priority': 'high',
            'title': 'Missing Cost of Goods Sold Data',
            'description': f'{report.cogs_missing_count} items are missing cost information',
            'action': 'Add purchase costs to reduce taxable income',
            'potential_savings': float(potential_savings)
        })

    # Home office deduction suggestion
    suggestions.append({
        'category': 'deductions',
        'priority': 'medium',
        'title': 'Consider Home Office Deduction',
        'description': 'If you use part of your home exclusively for business, you may qualify for home office deduction',
        'action': 'Simplified method: $5 per sq ft (max 300 sq ft = $1,500)',
        'potential_savings': 375.0  # $1,500 * 25% tax rate
    })

    # Mileage tracking
    if not report.expense_categories_breakdown or 'Transportation' not in report.expense_categories_breakdown:
        suggestions.append({
            'category': 'deductions',
            'priority': 'medium',
            'title': 'Track Business Mileage',
            'description': 'Trips for sourcing inventory, shipping, and business errands are deductible',
            'action': f'Standard mileage rate for {report.tax_year}: $0.67/mile',
            'potential_savings': 250.0  # Estimate
        })

    # Quarterly tax payments
    if report.estimated_quarterly_tax and report.estimated_quarterly_tax > 1000:
        suggestions.append({
            'category': 'tax_planning',
            'priority': 'high',
            'title': 'Make Quarterly Estimated Tax Payments',
            'description': 'Avoid penalties by paying estimated taxes quarterly',
            'action': f'Pay ${report.estimated_quarterly_tax:,.2f} per quarter (April 15, June 15, Sept 15, Jan 15)',
            'penalty_avoidance': float(report.estimated_quarterly_tax * 4 * 0.05)  # 5% penalty estimate
        })

    # Retirement contributions
    if report.net_profit > 10000:
        suggestions.append({
            'category': 'tax_planning',
            'priority': 'medium',
            'title': 'Consider SEP IRA or Solo 401(k)',
            'description': 'Self-employed retirement contributions are tax-deductible',
            'action': f'You could contribute up to ${min(report.net_profit * 0.20, 66000):,.2f} to a SEP IRA',
            'potential_savings': float(min(report.net_profit * 0.20, 66000) * 0.25)
        })

    return jsonify({
        'success': True,
        'suggestions': suggestions,
        'total_potential_savings': sum(s.get('potential_savings', 0) for s in suggestions)
    })


@tax_reports_bp.route('/comparison/<int:year>')
@login_required
def multi_year_comparison(year):
    """
    Multi-year tax comparison view
    IMPROVEMENT: Year-over-year analysis
    """
    years = [year, year - 1, year - 2]
    reports_data = []

    for y in years:
        report = TaxReport.query.filter_by(
            user_id=current_user.id,
            tax_year=y,
            report_type='annual'
        ).first()

        if report:
            reports_data.append(report.to_dict())
        else:
            # Generate if not exists
            try:
                new_report = get_or_create_tax_report(current_user.id, y)
                reports_data.append(new_report.to_dict())
            except:
                reports_data.append(None)

    return render_template(
        'tax_reports/comparison.html',
        reports=reports_data,
        years=years
    )
