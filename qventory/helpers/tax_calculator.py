"""
Tax Calculator Helper Module
Advanced tax calculations for Schedule C and quarterly estimated taxes
"""
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import func, and_, or_, extract
from qventory.models.sale import Sale
from qventory.models.expense import Expense
from qventory.models.item import Item
from qventory.models.receipt import Receipt
from qventory.models.receipt_item import ReceiptItem
from qventory.models.tax_report import TaxReport
from qventory.extensions import db


class TaxCalculator:
    """
    Main tax calculation engine for Qventory
    Superior to Flipwise with automatic COGS, multi-marketplace, and AI-powered insights
    """

    def __init__(self, user_id, tax_year=None, quarter=None):
        self.user_id = user_id
        self.tax_year = tax_year or datetime.now().year
        self.quarter = quarter
        self.start_date, self.end_date = self._get_date_range()

    def _get_date_range(self):
        """Calculate date range based on year and quarter"""
        if self.quarter:
            # Quarterly ranges
            quarters = {
                1: (date(self.tax_year, 1, 1), date(self.tax_year, 3, 31)),
                2: (date(self.tax_year, 4, 1), date(self.tax_year, 6, 30)),
                3: (date(self.tax_year, 7, 1), date(self.tax_year, 9, 30)),
                4: (date(self.tax_year, 10, 1), date(self.tax_year, 12, 31)),
            }
            return quarters.get(self.quarter)
        else:
            # Full year
            return (date(self.tax_year, 1, 1), date(self.tax_year, 12, 31))

    def calculate_gross_sales_revenue(self):
        """
        Calculate gross sales revenue (excluding refunds/returns)
        Broken down by marketplace
        """
        sales = Sale.query.filter(
            Sale.user_id == self.user_id,
            Sale.sold_at >= self.start_date,
            Sale.sold_at <= self.end_date,
            Sale.status.notin_(['cancelled', 'refunded'])
        ).all()

        total_revenue = Decimal('0.00')
        marketplace_breakdown = {}
        total_count = 0

        for sale in sales:
            amount = Decimal(str(sale.sold_price)) if sale.sold_price else Decimal('0.00')
            total_revenue += amount
            total_count += 1

            # Marketplace breakdown
            marketplace = sale.marketplace or 'other'
            if marketplace not in marketplace_breakdown:
                marketplace_breakdown[marketplace] = {
                    'revenue': Decimal('0.00'),
                    'count': 0,
                    'fees': Decimal('0.00')
                }

            marketplace_breakdown[marketplace]['revenue'] += amount
            marketplace_breakdown[marketplace]['count'] += 1

            if sale.marketplace_fee:
                marketplace_breakdown[marketplace]['fees'] += Decimal(str(sale.marketplace_fee))

        return {
            'total': float(total_revenue),
            'count': total_count,
            'by_marketplace': {k: {
                'revenue': float(v['revenue']),
                'count': v['count'],
                'fees': float(v['fees'])
            } for k, v in marketplace_breakdown.items()}
        }

    def calculate_shipping_revenue(self):
        """Calculate shipping charges collected from buyers"""
        result = db.session.query(
            func.sum(Sale.shipping_charged)
        ).filter(
            Sale.user_id == self.user_id,
            Sale.sold_at >= self.start_date,
            Sale.sold_at <= self.end_date,
            Sale.status.notin_(['cancelled', 'refunded'])
        ).scalar()

        return float(result) if result else 0.0

    def calculate_refunds_returns(self):
        """Calculate total refunds and returns (revenue deduction)"""
        # Refunded sales
        refunds = db.session.query(
            func.sum(Sale.refund_amount),
            func.count(Sale.id)
        ).filter(
            Sale.user_id == self.user_id,
            Sale.sold_at >= self.start_date,
            Sale.sold_at <= self.end_date,
            Sale.status == 'refunded'
        ).first()

        total_refund_amount = float(refunds[0]) if refunds[0] else 0.0
        refund_count = refunds[1] if refunds[1] else 0

        # Returned items
        returns = db.session.query(
            func.sum(Sale.sold_price),
            func.count(Sale.id)
        ).filter(
            Sale.user_id == self.user_id,
            Sale.sold_at >= self.start_date,
            Sale.sold_at <= self.end_date,
            Sale.status == 'returned'
        ).first()

        total_return_amount = float(returns[0]) if returns[0] else 0.0
        return_count = returns[1] if returns[1] else 0

        return {
            'refunds': {
                'amount': total_refund_amount,
                'count': refund_count
            },
            'returns': {
                'amount': total_return_amount,
                'count': return_count
            },
            'total': total_refund_amount + total_return_amount
        }

    def calculate_cogs(self):
        """
        Calculate Cost of Goods Sold (COGS)
        IMPROVEMENT OVER FLIPWISE: Automatically calculated from item_cost
        """
        # Get all sold items in period
        sales = Sale.query.filter(
            Sale.user_id == self.user_id,
            Sale.sold_at >= self.start_date,
            Sale.sold_at <= self.end_date,
            Sale.status.in_(['paid', 'shipped', 'completed', 'delivered'])
        ).all()

        total_cogs = Decimal('0.00')
        items_with_cost = 0
        items_missing_cost = 0
        missing_cost_details = []

        for sale in sales:
            if sale.item_cost and sale.item_cost > 0:
                total_cogs += Decimal(str(sale.item_cost))
                items_with_cost += 1
            else:
                items_missing_cost += 1
                missing_cost_details.append({
                    'sale_id': sale.id,
                    'item_title': sale.item_title,
                    'sold_price': float(sale.sold_price) if sale.sold_price else 0.0,
                    'sold_at': sale.sold_at.isoformat() if sale.sold_at else None
                })

        return {
            'total': float(total_cogs),
            'items_count': items_with_cost,
            'missing_count': items_missing_cost,
            'missing_details': missing_cost_details,
            'completeness_rate': (items_with_cost / (items_with_cost + items_missing_cost) * 100) if (items_with_cost + items_missing_cost) > 0 else 0
        }

    def calculate_inventory_values(self):
        """
        Calculate opening and closing inventory values
        Opening = Jan 1, Closing = Dec 31
        """
        # Opening inventory (items existing on Jan 1)
        opening_items = Item.query.filter(
            Item.user_id == self.user_id,
            Item.purchased_at < date(self.tax_year, 1, 1),
            or_(
                Item.sold_at.is_(None),  # Not sold yet
                Item.sold_at >= date(self.tax_year, 1, 1)  # Sold during/after this year
            )
        ).all()

        opening_value = sum(
            (Decimal(str(item.item_cost)) * item.quantity)
            for item in opening_items
            if item.item_cost and item.quantity
        )

        # Closing inventory (items existing on Dec 31)
        closing_items = Item.query.filter(
            Item.user_id == self.user_id,
            or_(
                Item.sold_at.is_(None),  # Still in inventory
                Item.sold_at > date(self.tax_year, 12, 31)  # Sold after year end
            )
        ).all()

        closing_value = sum(
            (Decimal(str(item.item_cost)) * item.quantity)
            for item in closing_items
            if item.item_cost and item.quantity
        )

        # Inventory purchased during year
        purchased_items = Item.query.filter(
            Item.user_id == self.user_id,
            Item.purchased_at >= self.start_date,
            Item.purchased_at <= self.end_date
        ).all()

        purchased_value = sum(
            (Decimal(str(item.item_cost)) * item.quantity)
            for item in purchased_items
            if item.item_cost and item.quantity
        )

        return {
            'opening': float(opening_value),
            'closing': float(closing_value),
            'purchased': float(purchased_value)
        }

    def calculate_marketplace_fees(self):
        """
        Calculate marketplace fees breakdown by type
        IMPROVEMENT: Detailed breakdown by fee type
        """
        sales = Sale.query.filter(
            Sale.user_id == self.user_id,
            Sale.sold_at >= self.start_date,
            Sale.sold_at <= self.end_date,
            Sale.status.notin_(['cancelled'])
        ).all()

        total_marketplace_fees = Decimal('0.00')
        total_payment_fees = Decimal('0.00')
        total_other_fees = Decimal('0.00')

        marketplace_breakdown = {}

        for sale in sales:
            marketplace = sale.marketplace or 'other'

            if marketplace not in marketplace_breakdown:
                marketplace_breakdown[marketplace] = {
                    'final_value_fees': Decimal('0.00'),
                    'payment_processing': Decimal('0.00'),
                    'other_fees': Decimal('0.00')
                }

            if sale.marketplace_fee:
                fee = Decimal(str(sale.marketplace_fee))
                total_marketplace_fees += fee
                marketplace_breakdown[marketplace]['final_value_fees'] += fee

            if sale.payment_processing_fee:
                fee = Decimal(str(sale.payment_processing_fee))
                total_payment_fees += fee
                marketplace_breakdown[marketplace]['payment_processing'] += fee

            if sale.other_fees:
                fee = Decimal(str(sale.other_fees))
                total_other_fees += fee
                marketplace_breakdown[marketplace]['other_fees'] += fee

        return {
            'total': float(total_marketplace_fees),
            'payment_processing': float(total_payment_fees),
            'other_fees': float(total_other_fees),
            'by_marketplace': {k: {
                'final_value_fees': float(v['final_value_fees']),
                'payment_processing': float(v['payment_processing']),
                'other_fees': float(v['other_fees'])
            } for k, v in marketplace_breakdown.items()}
        }

    def calculate_shipping_costs(self):
        """Calculate shipping costs (expense)"""
        result = db.session.query(
            func.sum(Sale.shipping_cost)
        ).filter(
            Sale.user_id == self.user_id,
            Sale.sold_at >= self.start_date,
            Sale.sold_at <= self.end_date
        ).scalar()

        total_shipping = float(result) if result else 0.0

        # Break down by carrier if data available
        carrier_breakdown = db.session.query(
            Sale.carrier,
            func.sum(Sale.shipping_cost),
            func.count(Sale.id)
        ).filter(
            Sale.user_id == self.user_id,
            Sale.sold_at >= self.start_date,
            Sale.sold_at <= self.end_date,
            Sale.carrier.isnot(None)
        ).group_by(Sale.carrier).all()

        return {
            'total': total_shipping,
            'by_carrier': {
                carrier: {'cost': float(cost), 'count': count}
                for carrier, cost, count in carrier_breakdown
            } if carrier_breakdown else {}
        }

    def calculate_business_expenses(self):
        """
        Calculate business expenses by category
        IMPROVEMENT: Integration with Receipt OCR data
        """
        # Direct expenses from Expense model
        expenses = Expense.query.filter(
            Expense.user_id == self.user_id,
            Expense.expense_date >= self.start_date,
            Expense.expense_date <= self.end_date
        ).all()

        total_expenses = Decimal('0.00')
        category_breakdown = {}

        for expense in expenses:
            amount = Decimal(str(expense.amount))
            total_expenses += amount

            category = expense.category or 'Uncategorized'
            if category not in category_breakdown:
                category_breakdown[category] = Decimal('0.00')
            category_breakdown[category] += amount

        # Receipt-based expenses (from ReceiptItem associated with Expense)
        receipt_expenses = db.session.query(
            func.sum(ReceiptItem.final_total_price)
        ).select_from(ReceiptItem).join(
            Receipt, ReceiptItem.receipt_id == Receipt.id
        ).filter(
            Receipt.user_id == self.user_id,
            Receipt.receipt_date >= self.start_date,
            Receipt.receipt_date <= self.end_date,
            ReceiptItem.expense_id.isnot(None)  # Associated with expense
        ).scalar()

        receipt_total = float(receipt_expenses) if receipt_expenses else 0.0

        return {
            'total': float(total_expenses),
            'receipt_based': receipt_total,
            'by_category': {k: float(v) for k, v in category_breakdown.items()},
            'count': len(expenses)
        }

    def calculate_estimated_taxes(self, net_profit, filing_status='single'):
        """
        Calculate estimated quarterly taxes (Form 1040-ES)
        IMPROVEMENT OVER FLIPWISE: Automated tax calculations

        Args:
            net_profit: Net profit from business
            filing_status: 'single', 'married_joint', 'married_separate', 'head_of_household'
        """
        net_profit = Decimal(str(net_profit))

        # Self-Employment Tax (Schedule SE)
        # 92.35% of net profit is subject to SE tax
        se_income = net_profit * Decimal('0.9235')

        # SE tax rate is 15.3% (12.4% Social Security + 2.9% Medicare)
        # Social Security portion capped at $160,200 (2023), $168,600 (2024)
        ss_wage_base = Decimal('168600.00')  # 2024

        ss_tax = min(se_income, ss_wage_base) * Decimal('0.124')
        medicare_tax = se_income * Decimal('0.029')

        # Additional Medicare tax (0.9%) on income over threshold
        medicare_threshold = {
            'single': Decimal('200000.00'),
            'married_joint': Decimal('250000.00'),
            'married_separate': Decimal('125000.00'),
            'head_of_household': Decimal('200000.00')
        }

        threshold = medicare_threshold.get(filing_status, Decimal('200000.00'))
        additional_medicare = max(Decimal('0'), se_income - threshold) * Decimal('0.009')

        total_se_tax = ss_tax + medicare_tax + additional_medicare

        # Income Tax (simplified brackets for 2024 - Single filer)
        # NOTE: This is simplified; actual calculation would consider deductions
        tax_brackets_2024 = {
            'single': [
                (11600, 0.10),   # 10% up to $11,600
                (47150, 0.12),   # 12% up to $47,150
                (100525, 0.22),  # 22% up to $100,525
                (191950, 0.24),  # 24% up to $191,950
                (243725, 0.32),  # 32% up to $243,725
                (609350, 0.35),  # 35% up to $609,350
                (float('inf'), 0.37)  # 37% above
            ]
        }

        # Deduct 1/2 of SE tax from income
        taxable_income = net_profit - (total_se_tax / 2)

        # Calculate income tax (simplified)
        income_tax = self._calculate_income_tax(taxable_income, filing_status, tax_brackets_2024)

        # Total estimated tax
        total_tax = total_se_tax + income_tax

        # Quarterly payment
        quarterly_payment = total_tax / 4

        return {
            'self_employment_tax': float(total_se_tax),
            'income_tax': float(income_tax),
            'total_annual': float(total_tax),
            'quarterly_payment': float(quarterly_payment),
            'breakdown': {
                'social_security': float(ss_tax),
                'medicare': float(medicare_tax),
                'additional_medicare': float(additional_medicare)
            }
        }

    def _calculate_income_tax(self, taxable_income, filing_status, brackets):
        """Calculate progressive income tax"""
        brackets_list = brackets.get(filing_status, brackets['single'])

        tax = Decimal('0.00')
        previous_limit = Decimal('0.00')

        for limit, rate in brackets_list:
            limit = Decimal(str(limit))
            rate = Decimal(str(rate))

            if taxable_income <= previous_limit:
                break

            taxable_in_bracket = min(taxable_income, limit) - previous_limit
            tax += taxable_in_bracket * rate

            previous_limit = limit

        return tax

    def validate_data_quality(self):
        """
        Validate data quality and identify issues
        IMPROVEMENT: Proactive issue detection
        """
        warnings = []

        # Check for missing COGS data
        cogs_data = self.calculate_cogs()
        if cogs_data['missing_count'] > 0:
            warnings.append({
                'type': 'error',
                'category': 'cogs',
                'message': f"{cogs_data['missing_count']} sold items are missing purchase cost or date",
                'action': 'Review sold items and add cost basis',
                'items': cogs_data['missing_details'][:10]  # Limit to 10 examples
            })

        # Check for unassociated receipts
        unassociated_receipts = Receipt.query.filter(
            Receipt.user_id == self.user_id,
            Receipt.receipt_date >= self.start_date,
            Receipt.receipt_date <= self.end_date,
            Receipt.status.in_(['extracted', 'pending'])
        ).count()

        if unassociated_receipts > 0:
            warnings.append({
                'type': 'warning',
                'category': 'receipts',
                'message': f"{unassociated_receipts} receipts are not fully associated with items or expenses",
                'action': 'Associate receipt items with inventory or expenses'
            })

        # Check for active items without purchase date
        active_no_date = Item.query.filter(
            Item.user_id == self.user_id,
            Item.sold_at.is_(None),
            Item.purchased_at.is_(None)
        ).count()

        if active_no_date > 0:
            warnings.append({
                'type': 'warning',
                'category': 'inventory',
                'message': f"{active_no_date} active items are missing purchase dates",
                'action': 'Add purchase dates to track inventory properly'
            })

        # Check for items without cost
        items_no_cost = Item.query.filter(
            Item.user_id == self.user_id,
            or_(Item.item_cost.is_(None), Item.item_cost == 0)
        ).count()

        if items_no_cost > 0:
            warnings.append({
                'type': 'warning',
                'category': 'inventory',
                'message': f"{items_no_cost} items are missing cost information",
                'action': 'Add cost to calculate accurate COGS'
            })

        # Calculate completeness score
        total_checks = 4
        passed_checks = total_checks - len(warnings)
        completeness_score = (passed_checks / total_checks) * 100

        return {
            'warnings': warnings,
            'completeness_score': completeness_score,
            'total_issues': len(warnings)
        }

    def generate_full_report(self):
        """
        Generate complete tax report
        IMPROVEMENT: All-in-one comprehensive report
        """
        # Revenue calculations
        gross_sales = self.calculate_gross_sales_revenue()
        shipping_revenue = self.calculate_shipping_revenue()
        refunds_returns = self.calculate_refunds_returns()

        # Calculate business income
        business_income = gross_sales['total'] + shipping_revenue - refunds_returns['total']

        # COGS and inventory
        cogs = self.calculate_cogs()
        inventory = self.calculate_inventory_values()

        # Gross profit
        gross_profit = business_income - cogs['total']

        # Expenses
        marketplace_fees = self.calculate_marketplace_fees()
        shipping_costs = self.calculate_shipping_costs()
        business_expenses = self.calculate_business_expenses()

        # Total expenses
        total_expenses = (
            marketplace_fees['total'] +
            marketplace_fees['payment_processing'] +
            marketplace_fees['other_fees'] +
            shipping_costs['total'] +
            business_expenses['total']
        )

        # Net profit
        net_profit = gross_profit - total_expenses

        # Tax estimates
        tax_estimates = self.calculate_estimated_taxes(net_profit)

        # Data validation
        validation = self.validate_data_quality()

        return {
            'tax_year': self.tax_year,
            'quarter': self.quarter,
            'report_type': 'quarterly' if self.quarter else 'annual',
            'generated_at': datetime.utcnow().isoformat(),

            # Revenue
            'revenue': {
                'gross_sales': gross_sales,
                'shipping_revenue': shipping_revenue,
                'refunds_returns': refunds_returns,
                'business_income': business_income
            },

            # COGS & Inventory
            'cogs': cogs,
            'inventory': inventory,

            # Profit
            'gross_profit': gross_profit,
            'net_profit': net_profit,

            # Expenses
            'expenses': {
                'marketplace_fees': marketplace_fees,
                'shipping_costs': shipping_costs,
                'business_expenses': business_expenses,
                'total': total_expenses
            },

            # Tax estimates
            'tax_estimates': tax_estimates,

            # Data quality
            'validation': validation
        }


def get_or_create_tax_report(user_id, tax_year, quarter=None, regenerate=False):
    """
    Get existing tax report or create new one

    Args:
        user_id: User ID
        tax_year: Tax year
        quarter: Optional quarter (1-4)
        regenerate: Force regeneration even if exists

    Returns:
        TaxReport model instance
    """
    report_type = 'quarterly' if quarter else 'annual'

    # Check for existing report
    existing = TaxReport.query.filter_by(
        user_id=user_id,
        tax_year=tax_year,
        report_type=report_type,
        quarter=quarter
    ).first()

    if existing and not regenerate:
        return existing

    # Generate new report
    calculator = TaxCalculator(user_id, tax_year, quarter)
    report_data = calculator.generate_full_report()

    if existing:
        # Update existing
        report = existing
    else:
        # Create new
        report = TaxReport(
            user_id=user_id,
            tax_year=tax_year,
            report_type=report_type,
            quarter=quarter
        )
        db.session.add(report)

    # Populate report fields
    report.gross_sales_revenue = report_data['revenue']['gross_sales']['total']
    report.total_sales_count = report_data['revenue']['gross_sales']['count']
    report.marketplace_sales = report_data['revenue']['gross_sales']['by_marketplace']

    report.shipping_revenue = report_data['revenue']['shipping_revenue']
    report.total_refunds = report_data['revenue']['refunds_returns']['refunds']['amount']
    report.total_returns = report_data['revenue']['refunds_returns']['returns']['amount']

    report.business_income = report_data['revenue']['business_income']

    report.total_cogs = report_data['cogs']['total']
    report.cogs_items_count = report_data['cogs']['items_count']
    report.cogs_missing_count = report_data['cogs']['missing_count']

    report.opening_inventory_value = report_data['inventory']['opening']
    report.closing_inventory_value = report_data['inventory']['closing']
    report.inventory_purchased = report_data['inventory']['purchased']

    report.total_marketplace_fees = report_data['expenses']['marketplace_fees']['total']
    report.marketplace_fees_breakdown = report_data['expenses']['marketplace_fees']['by_marketplace']

    report.total_shipping_costs = report_data['expenses']['shipping_costs']['total']
    report.shipping_costs_breakdown = report_data['expenses']['shipping_costs']['by_carrier']

    report.total_business_expenses = report_data['expenses']['business_expenses']['total']
    report.expense_categories_breakdown = report_data['expenses']['business_expenses']['by_category']

    report.payment_processing_fees = report_data['expenses']['marketplace_fees']['payment_processing']

    report.total_expenses = report_data['expenses']['total']

    report.gross_profit = report_data['gross_profit']
    report.net_profit = report_data['net_profit']

    report.estimated_self_employment_tax = report_data['tax_estimates']['self_employment_tax']
    report.estimated_income_tax = report_data['tax_estimates']['income_tax']
    report.estimated_quarterly_tax = report_data['tax_estimates']['quarterly_payment']

    report.validation_warnings = report_data['validation']['warnings']
    report.data_completeness_score = report_data['validation']['completeness_score']
    report.missing_costs_count = report_data['cogs']['missing_count']

    report.last_updated_at = datetime.utcnow()

    db.session.commit()

    return report
