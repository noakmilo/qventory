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
import os
from qventory.models.tax_report import TaxReport, TaxReportExport
from qventory.helpers.tax_calculator import TaxCalculator, get_or_create_tax_report
from qventory.extensions import db

tax_reports_bp = Blueprint('tax_reports', __name__, url_prefix='/tax-reports')


@tax_reports_bp.route('/')
@login_required
def index():
    """Tax reports dashboard - list all available reports"""
    # Restrict to paid users only (Premium, Pro, Early Adopter, God Mode)
    if not current_user.is_premium and not current_user.is_god_mode:
        flash('Tax Reports are available for Premium and Pro users only. Upgrade your plan to access this feature.', 'error')
        return redirect(url_for('main.dashboard'))

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
    # Restrict to paid users only (Premium, Pro, Early Adopter, God Mode)
    if not current_user.is_premium and not current_user.is_god_mode:
        flash('Tax Reports are available for Premium and Pro users only.', 'error')
        return redirect(url_for('main.dashboard'))

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


@tax_reports_bp.route('/export/<int:report_id>/pdf')
@login_required
def export_pdf(report_id):
    """
    Export tax report as PDF for printing
    """
    # Restrict to paid users only (Premium, Pro, Early Adopter, God Mode)
    if not current_user.is_premium and not current_user.is_god_mode:
        flash('PDF export is available for Premium and Pro users only.', 'error')
        return redirect(url_for('main.dashboard'))

    report = TaxReport.query.filter_by(
        id=report_id,
        user_id=current_user.id
    ).first_or_404()

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT

        # Create PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                               topMargin=72, bottomMargin=18)

        # Container for PDF elements
        elements = []
        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#667eea'),
            spaceAfter=30,
            alignment=TA_CENTER
        )

        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#667eea'),
            spaceAfter=12
        )

        # Title
        elements.append(Paragraph(f"Tax Report - {report.tax_year}", title_style))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y')}", styles['Normal']))
        elements.append(Spacer(1, 20))

        # Revenue Summary
        elements.append(Paragraph("Revenue Summary", heading_style))
        revenue_data = [
            ['Description', 'Amount'],
            ['Gross Sales Revenue', f'${report.gross_sales_revenue:,.2f}'],
            ['Shipping Revenue', f'${report.shipping_revenue:,.2f}'],
            ['Refunds', f'-${report.total_refunds:,.2f}'],
            ['Returns', f'-${report.total_returns:,.2f}'],
            ['Business Income', f'${report.business_income:,.2f}'],
        ]
        revenue_table = Table(revenue_data, colWidths=[4*inch, 2*inch])
        revenue_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(revenue_table)
        elements.append(Spacer(1, 20))

        # Expenses
        elements.append(Paragraph("Expenses", heading_style))
        expense_data = [
            ['Category', 'Amount'],
            ['Cost of Goods Sold (COGS)', f'${report.total_cogs:,.2f}'],
            ['Business Expenses', f'${report.total_business_expenses:,.2f}'],
            ['Total Expenses', f'${report.total_expenses:,.2f}'],
        ]
        expense_table = Table(expense_data, colWidths=[4*inch, 2*inch])
        expense_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(expense_table)
        elements.append(Spacer(1, 20))

        # Net Profit
        elements.append(Paragraph("Net Profit/Loss", heading_style))
        profit_data = [
            ['Description', 'Amount'],
            ['Gross Profit', f'${report.gross_profit:,.2f}'],
            ['Net Profit', f'${report.net_profit:,.2f}'],
        ]
        profit_table = Table(profit_data, colWidths=[4*inch, 2*inch])
        profit_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(profit_table)
        elements.append(Spacer(1, 20))

        # Tax Estimates
        elements.append(Paragraph("Estimated Tax Obligations", heading_style))
        tax_data = [
            ['Description', 'Amount'],
            ['Self-Employment Tax', f'${report.estimated_self_employment_tax:,.2f}'],
            ['Income Tax', f'${report.estimated_income_tax:,.2f}'],
            ['Quarterly Tax Payment', f'${report.estimated_quarterly_tax:,.2f}'],
        ]
        tax_table = Table(tax_data, colWidths=[4*inch, 2*inch])
        tax_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(tax_table)
        elements.append(Spacer(1, 20))

        # Footer
        elements.append(Spacer(1, 40))
        disclaimer = Paragraph(
            "<b>Disclaimer:</b> This report is for informational purposes only. Consult a qualified tax professional for tax advice.",
            styles['Normal']
        )
        elements.append(disclaimer)

        # Build PDF
        doc.build(elements)

        # Record export
        export_record = TaxReportExport(
            tax_report_id=report.id,
            user_id=current_user.id,
            export_format='pdf',
            exported_at=datetime.utcnow()
        )
        db.session.add(export_record)

        if not report.exported_formats:
            report.exported_formats = []
        if 'pdf' not in report.exported_formats:
            report.exported_formats.append('pdf')
        report.last_exported_at = datetime.utcnow()
        db.session.commit()

        buffer.seek(0)
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'tax_report_{report.tax_year}_qventory.pdf'
        )

    except Exception as e:
        flash(f'Error generating PDF: {str(e)}', 'error')
        return redirect(url_for('tax_reports.annual_report', year=report.tax_year))


@tax_reports_bp.route('/api/<int:report_id>/tax-optimization')
@login_required
def get_tax_optimization_suggestions(report_id):
    """
    AI-powered tax optimization suggestions using ChatGPT
    """
    # Restrict to paid users only (Premium, Pro, Early Adopter, God Mode)
    if not current_user.is_premium and not current_user.is_god_mode:
        return jsonify({'error': 'This feature is available for Premium and Pro users only'}), 403

    report = TaxReport.query.filter_by(
        id=report_id,
        user_id=current_user.id
    ).first_or_404()

    try:
        import openai

        # Get API key
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            return jsonify({'error': 'OpenAI API key not configured'}), 500

        # Initialize OpenAI client
        client = openai.OpenAI(api_key=api_key)

        # Prepare report data for AI analysis
        report_summary = f"""
Tax Year: {report.tax_year}
Business Type: Online Reseller (eBay/Depop)

Financial Summary:
- Gross Sales Revenue: ${report.gross_sales_revenue:,.2f}
- Total Sales Count: {report.total_sales_count}
- Cost of Goods Sold (COGS): ${report.total_cogs:,.2f}
- Business Expenses: ${report.total_business_expenses:,.2f}
- Net Profit: ${report.net_profit:,.2f}

Data Quality:
- COGS Items Count: {report.cogs_items_count}
- COGS Missing Count: {report.cogs_missing_count}
- Expense Categories: {', '.join(report.expense_categories_breakdown.keys()) if report.expense_categories_breakdown else 'None tracked'}
- Data Completeness Score: {report.data_completeness_score:.0f}%

Tax Estimates:
- Self-Employment Tax: ${report.estimated_self_employment_tax:,.2f}
- Income Tax: ${report.estimated_income_tax:,.2f}
- Quarterly Tax Payment: ${report.estimated_quarterly_tax:,.2f}
"""

        # Call ChatGPT for tax optimization suggestions
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a tax optimization expert specializing in small online reselling businesses (eBay, Depop, etc.). Provide 3-5 specific, actionable tax optimization tips based on the business data provided. Focus on legitimate deductions, expense tracking, and tax planning strategies. Format each tip with: priority (high/medium/low), category, title, description, and specific action steps."
                },
                {
                    "role": "user",
                    "content": f"Analyze this reseller's tax report and provide optimization suggestions:\n\n{report_summary}"
                }
            ],
            temperature=0.7,
            max_tokens=1000
        )

        ai_response = response.choices[0].message.content

        # Parse AI response and structure it
        suggestions = [{
            'category': 'ai_tips',
            'priority': 'high',
            'title': 'AI-Powered Tax Optimization Tips',
            'description': ai_response,
            'action': 'Review these personalized recommendations for your business'
        }]

        return jsonify({
            'success': True,
            'suggestions': suggestions
        })

    except Exception as e:
        print(f"Error generating AI tips: {e}")
        # Fallback to basic suggestions if AI fails
        suggestions = []

        if report.cogs_missing_count > 0:
            suggestions.append({
                'category': 'cogs',
                'priority': 'high',
                'title': 'Missing Cost of Goods Sold Data',
                'description': f'{report.cogs_missing_count} items are missing cost information',
                'action': 'Add purchase costs to reduce taxable income'
            })

        if report.total_business_expenses < (report.gross_sales_revenue * 0.1):
            suggestions.append({
                'category': 'expenses',
                'priority': 'high',
                'title': 'Low Expense Tracking',
                'description': 'Your expenses seem low. You may be missing deductible expenses.',
                'action': 'Review: office supplies, storage, shipping materials, software'
            })

        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'fallback': True
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
