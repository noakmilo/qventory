"""
Tax Report Model for Annual Tax Summary Generation
Stores cached tax calculations and metadata for audit trails
"""
from qventory.extensions import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB


class TaxReport(db.Model):
    """
    Stores annual tax report summaries with cached calculations
    """
    __tablename__ = 'tax_reports'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    # Report Metadata
    tax_year = db.Column(db.Integer, nullable=False, index=True)  # e.g., 2024
    report_type = db.Column(db.String(50), default='annual')  # annual, quarterly, ytd
    quarter = db.Column(db.Integer)  # 1-4 for quarterly reports

    # Generation Timestamps
    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Status
    status = db.Column(db.String(20), default='draft')  # draft, finalized, exported, archived

    # Revenue Summary (cached calculations)
    gross_sales_revenue = db.Column(db.Numeric(10, 2), default=0.0)
    total_sales_count = db.Column(db.Integer, default=0)

    # Revenue Breakdown by Marketplace (JSON)
    marketplace_sales = db.Column(JSONB, default=dict)  # {"ebay": 3471.53, "mercari": 500, ...}

    # Additional Revenue
    additional_revenue = db.Column(db.Numeric(10, 2), default=0.0)
    shipping_revenue = db.Column(db.Numeric(10, 2), default=0.0)  # shipping_charged from sales
    credits_adjustments = db.Column(db.Numeric(10, 2), default=0.0)  # misc credits

    # Refunds/Returns (deductions from revenue)
    total_refunds = db.Column(db.Numeric(10, 2), default=0.0)
    total_returns = db.Column(db.Numeric(10, 2), default=0.0)

    # Business Income (gross - refunds)
    business_income = db.Column(db.Numeric(10, 2), default=0.0)

    # Cost of Goods Sold (COGS)
    total_cogs = db.Column(db.Numeric(10, 2), default=0.0)
    cogs_items_count = db.Column(db.Integer, default=0)
    cogs_missing_count = db.Column(db.Integer, default=0)  # items without purchase date/cost

    # Inventory Status
    opening_inventory_value = db.Column(db.Numeric(10, 2), default=0.0)  # Jan 1
    closing_inventory_value = db.Column(db.Numeric(10, 2), default=0.0)  # Dec 31
    inventory_purchased = db.Column(db.Numeric(10, 2), default=0.0)  # During year

    # Business Expenses
    total_marketplace_fees = db.Column(db.Numeric(10, 2), default=0.0)
    marketplace_fees_breakdown = db.Column(JSONB, default=dict)  # {"ebay_fvf": 459.03, ...}

    total_shipping_costs = db.Column(db.Numeric(10, 2), default=0.0)
    shipping_costs_breakdown = db.Column(JSONB, default=dict)  # {"label_cost": 650, "return": 7.78}

    total_business_expenses = db.Column(db.Numeric(10, 2), default=0.0)
    expense_categories_breakdown = db.Column(JSONB, default=dict)  # {"Supplies": 200, "Rent": 500, ...}

    payment_processing_fees = db.Column(db.Numeric(10, 2), default=0.0)

    total_expenses = db.Column(db.Numeric(10, 2), default=0.0)  # Sum of all above

    # Net Profit/Loss
    gross_profit = db.Column(db.Numeric(10, 2), default=0.0)  # business_income - cogs
    net_profit = db.Column(db.Numeric(10, 2), default=0.0)  # gross_profit - total_expenses

    # Tax Estimates (calculated)
    estimated_self_employment_tax = db.Column(db.Numeric(10, 2))  # 15.3% of net
    estimated_income_tax = db.Column(db.Numeric(10, 2))  # Based on tax bracket
    estimated_quarterly_tax = db.Column(db.Numeric(10, 2))  # For 1040-ES

    # Data Quality Metrics
    validation_warnings = db.Column(JSONB, default=list)  # List of data issues
    missing_purchase_dates_count = db.Column(db.Integer, default=0)
    missing_costs_count = db.Column(db.Integer, default=0)
    receipts_without_association_count = db.Column(db.Integer, default=0)

    data_completeness_score = db.Column(db.Numeric(5, 2), default=0.0)  # 0-100%

    # Detailed Breakdown (JSON storage for complex data)
    detailed_sales = db.Column(JSONB, default=dict)  # Full sales breakdown by month
    detailed_expenses = db.Column(JSONB, default=dict)  # Expense details

    # Export History
    exported_formats = db.Column(JSONB, default=list)  # ["pdf", "csv", "schedule_c"]
    last_exported_at = db.Column(db.DateTime)

    # Notes
    notes = db.Column(db.Text)  # User notes for CPA
    cpa_email = db.Column(db.String(255))  # Optional CPA contact

    # Relationships
    user = db.relationship('User', backref=db.backref('tax_reports', lazy='dynamic', cascade='all, delete-orphan'))

    # Constraints
    __table_args__ = (
        db.UniqueConstraint('user_id', 'tax_year', 'report_type', 'quarter', name='unique_user_tax_report'),
        db.Index('idx_tax_reports_user_year', 'user_id', 'tax_year'),
    )

    def __repr__(self):
        return f'<TaxReport {self.tax_year} Q{self.quarter or "Annual"} - User {self.user_id}>'

    @property
    def is_finalized(self):
        """Check if report is finalized (no more edits)"""
        return self.status == 'finalized'

    @property
    def needs_review(self):
        """Check if report has data quality issues"""
        return len(self.validation_warnings) > 0 or self.data_completeness_score < 90

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'tax_year': self.tax_year,
            'quarter': self.quarter,
            'report_type': self.report_type,
            'status': self.status,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'business_income': float(self.business_income) if self.business_income else 0.0,
            'gross_sales_revenue': float(self.gross_sales_revenue) if self.gross_sales_revenue else 0.0,
            'total_cogs': float(self.total_cogs) if self.total_cogs else 0.0,
            'total_expenses': float(self.total_expenses) if self.total_expenses else 0.0,
            'net_profit': float(self.net_profit) if self.net_profit else 0.0,
            'gross_profit': float(self.gross_profit) if self.gross_profit else 0.0,
            'marketplace_sales': self.marketplace_sales,
            'validation_warnings': self.validation_warnings,
            'data_completeness_score': float(self.data_completeness_score) if self.data_completeness_score else 0.0,
        }


class TaxReportExport(db.Model):
    """
    Tracks export history and stores generated files
    """
    __tablename__ = 'tax_report_exports'

    id = db.Column(db.Integer, primary_key=True)
    tax_report_id = db.Column(db.Integer, db.ForeignKey('tax_reports.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    export_format = db.Column(db.String(50), nullable=False)  # pdf, csv, excel, schedule_c_json, quickbooks_iif
    file_path = db.Column(db.String(500))  # Cloud storage URL or local path
    file_size = db.Column(db.Integer)  # bytes

    exported_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    downloaded_at = db.Column(db.DateTime)  # Track if CPA downloaded

    # Metadata
    export_parameters = db.Column(JSONB, default=dict)  # Config used for export

    # Relationships
    tax_report = db.relationship('TaxReport', backref=db.backref('exports', lazy='dynamic', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('tax_exports', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<TaxReportExport {self.export_format} - Report {self.tax_report_id}>'
