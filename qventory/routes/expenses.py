"""
Business Expenses Routes
Manage operational expenses for the business
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from qventory import db
from qventory.models.expense import Expense, EXPENSE_CATEGORIES
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

expenses_bp = Blueprint('expenses', __name__)


@expenses_bp.route("/expenses")
@login_required
def expenses_page():
    """Main expenses management page"""
    # Get date range from query params (default: current month)
    range_param = request.args.get('range', 'this_month')

    now = datetime.utcnow()

    if range_param == 'this_month':
        start_date = now.replace(day=1).date()
        end_date = (now.replace(day=1) + relativedelta(months=1)).date()
    elif range_param == 'last_month':
        last_month = now - relativedelta(months=1)
        start_date = last_month.replace(day=1).date()
        end_date = now.replace(day=1).date()
    elif range_param == 'this_year':
        start_date = now.replace(month=1, day=1).date()
        end_date = (now.replace(month=12, day=31) + relativedelta(days=1)).date()
    elif range_param == 'all_time':
        start_date = date(2000, 1, 1)
        end_date = date(2099, 12, 31)
    else:
        start_date = now.replace(day=1).date()
        end_date = (now.replace(day=1) + relativedelta(months=1)).date()

    # Query expenses in range
    expenses = Expense.query.filter(
        Expense.user_id == current_user.id,
        Expense.expense_date >= start_date,
        Expense.expense_date < end_date
    ).order_by(Expense.expense_date.desc()).all()

    # Calculate totals by category
    totals_by_category = {}
    total_amount = 0.0

    for expense in expenses:
        category = expense.category or 'Other'
        if category not in totals_by_category:
            totals_by_category[category] = 0.0
        totals_by_category[category] += expense.amount
        total_amount += expense.amount

    # Get current monthly budget
    monthly_budget = float(current_user.monthly_expense_budget) if current_user.monthly_expense_budget else None

    # Calculate this month's expenses for budget tracking
    this_month_start = now.replace(day=1).date()
    this_month_end = (now.replace(day=1) + relativedelta(months=1)).date()

    this_month_expenses = Expense.query.filter(
        Expense.user_id == current_user.id,
        Expense.expense_date >= this_month_start,
        Expense.expense_date < this_month_end
    ).all()

    this_month_total = sum(e.amount for e in this_month_expenses)

    # Get active Liberis loan
    from qventory.models.liberis_loan import LiberisLoan
    liberis_loan = LiberisLoan.get_active_loan(current_user.id)

    return render_template("expenses.html",
                         expenses=expenses,
                         categories=EXPENSE_CATEGORIES,
                         totals_by_category=totals_by_category,
                         total_amount=total_amount,
                         range_param=range_param,
                         monthly_budget=monthly_budget,
                         this_month_total=float(this_month_total),
                         liberis_loan=liberis_loan)


@expenses_bp.route("/api/expenses", methods=["POST"])
@login_required
def create_expense():
    """Create a new expense"""
    try:
        data = request.get_json()

        # Parse date
        expense_date_str = data.get('expense_date')
        expense_date = datetime.strptime(expense_date_str, '%Y-%m-%d').date()

        expense = Expense(
            user_id=current_user.id,
            description=data.get('description'),
            amount=float(data.get('amount')),
            category=data.get('category'),
            expense_date=expense_date,
            is_recurring=data.get('is_recurring', False),
            recurring_frequency=data.get('recurring_frequency'),
            recurring_day=data.get('recurring_day'),
            recurring_until=datetime.strptime(data.get('recurring_until'), '%Y-%m-%d').date() if data.get('recurring_until') else None,
            notes=data.get('notes')
        )

        db.session.add(expense)
        db.session.commit()

        return jsonify({
            "ok": True,
            "expense": {
                "id": expense.id,
                "description": expense.description,
                "amount": expense.amount,
                "category": expense.category,
                "expense_date": expense.expense_date.isoformat(),
                "is_recurring": expense.is_recurring
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400


@expenses_bp.route("/api/expenses/<int:expense_id>", methods=["PUT"])
@login_required
def update_expense(expense_id):
    """Update an expense"""
    try:
        expense = Expense.query.filter_by(id=expense_id, user_id=current_user.id).first()

        if not expense:
            return jsonify({"ok": False, "error": "Expense not found"}), 404

        data = request.get_json()

        if 'description' in data:
            expense.description = data['description']
        if 'amount' in data:
            expense.amount = float(data['amount'])
        if 'category' in data:
            expense.category = data['category']
        if 'expense_date' in data:
            expense.expense_date = datetime.strptime(data['expense_date'], '%Y-%m-%d').date()
        if 'is_recurring' in data:
            expense.is_recurring = data['is_recurring']
        if 'recurring_frequency' in data:
            expense.recurring_frequency = data['recurring_frequency']
        if 'recurring_day' in data:
            expense.recurring_day = data['recurring_day']
        if 'recurring_until' in data:
            expense.recurring_until = datetime.strptime(data['recurring_until'], '%Y-%m-%d').date() if data['recurring_until'] else None
        if 'notes' in data:
            expense.notes = data['notes']

        expense.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({"ok": True, "message": "Expense updated"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400


@expenses_bp.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
@login_required
def delete_expense(expense_id):
    """Delete an expense"""
    try:
        expense = Expense.query.filter_by(id=expense_id, user_id=current_user.id).first()

        if not expense:
            return jsonify({"ok": False, "error": "Expense not found"}), 404

        db.session.delete(expense)
        db.session.commit()

        return jsonify({"ok": True, "message": "Expense deleted"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400


@expenses_bp.route("/api/budget", methods=["POST"])
@login_required
def update_budget():
    """Update monthly expense budget"""
    try:
        data = request.get_json()
        budget = data.get('budget')

        if budget is not None:
            current_user.monthly_expense_budget = float(budget) if budget != '' else None
        else:
            current_user.monthly_expense_budget = None

        db.session.commit()

        return jsonify({
            "ok": True,
            "budget": float(current_user.monthly_expense_budget) if current_user.monthly_expense_budget else None
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400


@expenses_bp.route("/api/liberis/recalculate", methods=["POST"])
@login_required
def recalculate_liberis_loan():
    """Manually recalculate Liberis loan repayment progress"""
    try:
        from qventory.models.liberis_loan import LiberisLoan

        liberis_loan = LiberisLoan.get_active_loan(current_user.id)

        if not liberis_loan:
            return jsonify({"ok": False, "error": "No active Liberis loan found"}), 404

        # Recalculate
        liberis_loan.recalculate_paid_amount()

        return jsonify({
            "ok": True,
            "paid_amount": float(liberis_loan.paid_amount),
            "total_amount": float(liberis_loan.total_amount),
            "progress_percentage": float(liberis_loan.progress_percentage),
            "remaining_amount": float(liberis_loan.remaining_amount)
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400
