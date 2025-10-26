"""
Receipts blueprint for receipt upload, OCR processing, and item association.

Routes:
- GET/POST /receipts/upload - Upload new receipt
- GET /receipts - List all receipts (history)
- GET /receipts/<id> - View receipt details and associate items
- POST /receipts/<id>/associate - Associate receipt item with inventory/expense
- POST /receipts/<id>/disassociate - Remove association
- POST /receipts/<id>/update-item - Update receipt item details
- POST /receipts/<id>/mark-complete - Mark receipt as completed
- POST /receipts/<id>/discard - Mark receipt as discarded
- DELETE /receipts/<id> - Delete receipt
- GET /api/receipts/<id>/items - Get receipt items as JSON
"""
import logging
from datetime import datetime
from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from qventory.extensions import db
from qventory.models.receipt import Receipt
from qventory.models.receipt_item import ReceiptItem
from qventory.models.receipt_usage import ReceiptUsage
from qventory.models.item import Item
from qventory.models.expense import Expense
from qventory.helpers.receipt_image_processor import ReceiptImageProcessor
from qventory.helpers.ocr_service import get_ocr_service

logger = logging.getLogger(__name__)

receipts_bp = Blueprint('receipts', __name__, url_prefix='/receipts')


@receipts_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    """Upload new receipt and trigger OCR processing."""
    if request.method == 'GET':
        # Get user's OCR usage stats
        plan_limits = current_user.get_plan_limits()
        subscription = current_user.get_subscription()

        can_process, limit_message, used, limit = ReceiptUsage.can_process_receipt(current_user, plan_limits)

        usage_stats = {
            'can_process': can_process,
            'message': limit_message,
            'used': used,
            'limit': limit,
            'plan': subscription.plan,
            'plan_display': subscription.plan.replace('_', ' ').title(),
            'period': 'day' if plan_limits.max_receipt_ocr_per_day else 'month'
        }

        return render_template('receipts/upload.html', usage_stats=usage_stats)

    # POST: Handle file upload
    if 'receipt_image' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(request.url)

    file = request.files['receipt_image']
    if not file or file.filename == '':
        flash('No file selected', 'error')
        return redirect(request.url)

    # Initialize image processor
    processor = ReceiptImageProcessor(user_id=current_user.id)

    # Validate file
    is_valid, error = processor.validate_file(file)
    if not is_valid:
        flash(error, 'error')
        return redirect(request.url)

    try:
        # Check if Cloudinary is configured
        from qventory.helpers.receipt_image_processor import CLOUDINARY_ENABLED
        if not CLOUDINARY_ENABLED:
            flash('Receipt upload is not configured. Please contact administrator to set up Cloudinary.', 'error')
            logger.error("Cloudinary not configured - missing environment variables")
            return redirect(request.url)

        # Create receipt record first (without image)
        receipt = Receipt(
            user_id=current_user.id,
            image_url='',  # Will update after upload
            image_public_id='',
            original_filename=secure_filename(file.filename),
            file_size=0,
            status='pending'
        )
        db.session.add(receipt)
        db.session.flush()  # Get receipt.id

        # Upload to Cloudinary
        upload_result = processor.upload_receipt(file, receipt_id=receipt.id)

        if not upload_result['success']:
            db.session.rollback()
            flash(f"Upload failed: {upload_result['error']}", 'error')
            logger.error(f"Cloudinary upload failed: {upload_result['error']}")
            return redirect(request.url)

        # Update receipt with image info
        receipt.image_url = upload_result['url']
        receipt.thumbnail_url = upload_result['thumbnail_url']
        receipt.image_public_id = upload_result['public_id']

        # Get file size (file might have been read, so reset first)
        try:
            file.seek(0, 2)  # Seek to end
            receipt.file_size = file.tell()
            file.seek(0)  # Reset to beginning
        except Exception:
            # If seek fails, file size is not critical
            receipt.file_size = 0

        db.session.commit()
        logger.info(f"Receipt {receipt.id} uploaded by user {current_user.id}")

        # Check plan limits before processing OCR
        subscription = current_user.get_subscription()
        plan_limits = current_user.get_plan_limits()

        # Check if user can process receipt with AI OCR
        can_process, limit_message, used, limit = ReceiptUsage.can_process_receipt(current_user, plan_limits)

        if not can_process:
            # User hit their limit - save receipt without OCR processing
            receipt.status = 'pending'
            receipt.ocr_error_message = limit_message
            db.session.commit()
            flash(f'Receipt uploaded but OCR limit reached: {limit_message}. Upgrade your plan for more AI OCR processing.', 'warning')
            logger.warning(f"User {current_user.id} hit OCR limit: {limit_message}")
            return redirect(url_for('receipts.view_receipt', receipt_id=receipt.id))

        # Trigger OCR processing
        try:
            receipt.status = 'processing'
            db.session.commit()

            # Process OCR
            ocr_service = get_ocr_service()
            logger.info(f"Starting OCR processing for receipt {receipt.id} with provider: {ocr_service.provider}")
            ocr_result = ocr_service.extract_receipt_data(receipt.image_url)

            # Update receipt with OCR results
            receipt.ocr_provider = ocr_service.provider
            receipt.ocr_raw_text = ocr_result.raw_text
            receipt.ocr_confidence = ocr_result.confidence
            receipt.ocr_processed_at = datetime.utcnow()

            if ocr_result.error:
                receipt.status = 'failed'
                receipt.ocr_error_message = ocr_result.error
                logger.error(f"OCR failed for receipt {receipt.id}: {ocr_result.error}")
                flash(f'OCR processing failed: {ocr_result.error}', 'warning')
            else:
                receipt.status = 'extracted'
                receipt.merchant_name = ocr_result.merchant_name
                receipt.receipt_date = ocr_result.receipt_date
                receipt.receipt_number = ocr_result.receipt_number
                receipt.subtotal = ocr_result.subtotal
                receipt.tax_amount = ocr_result.tax_amount
                receipt.total_amount = ocr_result.total_amount

                logger.info(f"OCR extracted {len(ocr_result.line_items)} items from receipt {receipt.id}")

                # Create receipt items
                for item_data in ocr_result.line_items:
                    receipt_item = ReceiptItem(
                        receipt_id=receipt.id,
                        line_number=item_data.get('line_number'),
                        description=item_data.get('description'),
                        quantity=item_data.get('quantity'),
                        unit_price=item_data.get('unit_price'),
                        total_price=item_data.get('total_price'),
                        ocr_confidence=item_data.get('confidence')
                    )
                    db.session.add(receipt_item)
                    logger.debug(f"Added receipt item: {receipt_item.description}")

                # Record OCR usage
                ReceiptUsage.record_usage(
                    user_id=current_user.id,
                    receipt_id=receipt.id,
                    plan=subscription.plan,
                    provider=ocr_service.provider
                )

                flash(f'Receipt uploaded successfully! Extracted {len(ocr_result.line_items)} items. ({used + 1}/{limit or "unlimited"} AI OCR used this {"day" if plan_limits.max_receipt_ocr_per_day else "month"}).', 'success')
                logger.info(f"Receipt {receipt.id} processing completed successfully")

            db.session.commit()

        except Exception as e:
            logger.exception(f"OCR processing failed for receipt {receipt.id}: {e}")
            receipt.status = 'failed'
            receipt.ocr_error_message = str(e)
            db.session.commit()
            flash('Receipt uploaded but OCR processing failed. You can retry later.', 'warning')

        # Redirect to review page
        return redirect(url_for('receipts.view_receipt', receipt_id=receipt.id))

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Receipt upload failed: {e}")
        flash(f'Upload failed: {str(e)}', 'error')
        return redirect(request.url)


@receipts_bp.route('/')
@login_required
def list_receipts():
    """List all receipts for current user (history view)."""
    # Get filter parameters
    status_filter = request.args.get('status', 'all')
    sort_by = request.args.get('sort', 'date_desc')

    # Build query
    query = Receipt.query.filter_by(user_id=current_user.id)

    # Apply status filter
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    # Apply sorting
    if sort_by == 'date_desc':
        query = query.order_by(Receipt.uploaded_at.desc())
    elif sort_by == 'date_asc':
        query = query.order_by(Receipt.uploaded_at.asc())
    elif sort_by == 'merchant':
        query = query.order_by(Receipt.merchant_name)
    elif sort_by == 'total':
        query = query.order_by(Receipt.total_amount.desc())

    receipts = query.all()

    # Calculate statistics
    stats = {
        'total_receipts': Receipt.query.filter_by(user_id=current_user.id).count(),
        'pending': Receipt.query.filter_by(user_id=current_user.id, status='pending').count(),
        'processing': Receipt.query.filter_by(user_id=current_user.id, status='processing').count(),
        'extracted': Receipt.query.filter_by(user_id=current_user.id, status='extracted').count(),
        'partially_associated': Receipt.query.filter_by(user_id=current_user.id, status='partially_associated').count(),
        'completed': Receipt.query.filter_by(user_id=current_user.id, status='completed').count(),
    }

    return render_template(
        'receipts/list.html',
        receipts=receipts,
        stats=stats,
        current_status=status_filter,
        current_sort=sort_by
    )


@receipts_bp.route('/<int:receipt_id>')
@login_required
def view_receipt(receipt_id):
    """View receipt details and associate items."""
    receipt = Receipt.query.filter_by(id=receipt_id, user_id=current_user.id).first_or_404()

    # Update last_reviewed_at
    receipt.last_reviewed_at = datetime.utcnow()
    db.session.commit()

    # Get receipt items
    receipt_items = receipt.items.order_by(ReceiptItem.line_number).all()

    # Get user's inventory items for autocomplete (convert to dict for JSON)
    inventory_items_query = Item.query.filter_by(
        user_id=current_user.id,
        is_active=True
    ).order_by(Item.title).all()

    # Convert to serializable format for JavaScript
    inventory_items = [
        {
            'id': item.id,
            'title': item.title,
            'sku': item.sku,
            'location_code': item.location_code,
            'item_cost': float(item.item_cost) if item.item_cost else None
        }
        for item in inventory_items_query
    ]

    return render_template(
        'receipts/view.html',
        receipt=receipt,
        receipt_items=receipt_items,
        inventory_items=inventory_items
    )


@receipts_bp.route('/<int:receipt_id>/associate', methods=['POST'])
@login_required
def associate_item(receipt_id):
    """Associate a receipt item with inventory item or expense."""
    receipt = Receipt.query.filter_by(id=receipt_id, user_id=current_user.id).first_or_404()

    receipt_item_id = request.form.get('receipt_item_id', type=int)
    association_type = request.form.get('association_type')  # 'inventory' or 'expense'

    if not receipt_item_id or not association_type:
        return jsonify({'success': False, 'error': 'Missing parameters'}), 400

    receipt_item = ReceiptItem.query.filter_by(
        id=receipt_item_id,
        receipt_id=receipt_id
    ).first_or_404()

    try:
        if association_type == 'inventory':
            inventory_item_id = request.form.get('inventory_item_id', type=int)
            update_cost = request.form.get('update_cost', 'false') == 'true'

            if not inventory_item_id:
                return jsonify({'success': False, 'error': 'Missing inventory_item_id'}), 400

            # Verify item belongs to user
            inventory_item = Item.query.filter_by(
                id=inventory_item_id,
                user_id=current_user.id
            ).first()
            if not inventory_item:
                return jsonify({'success': False, 'error': 'Invalid item'}), 404

            # Associate
            receipt_item.associate_with_inventory(inventory_item_id, update_cost=update_cost)

            flash(f'Associated with inventory item: {inventory_item.title}', 'success')

        elif association_type == 'expense':
            # Create new expense
            expense_description = request.form.get('expense_description') or receipt_item.final_description
            expense_amount = request.form.get('expense_amount', type=float) or float(receipt_item.final_total_price or 0)
            expense_category = request.form.get('expense_category', 'Receipt Item')
            expense_date_str = request.form.get('expense_date')
            expense_notes = request.form.get('expense_notes', '')

            # Parse expense date if provided
            if expense_date_str:
                try:
                    from datetime import datetime as dt
                    expense_date = dt.strptime(expense_date_str, '%Y-%m-%d').date()
                except ValueError:
                    expense_date = receipt.receipt_date or datetime.utcnow().date()
            else:
                expense_date = receipt.receipt_date or datetime.utcnow().date()

            # Combine notes
            notes = expense_notes if expense_notes else ''
            if notes:
                notes += f"\n\nFrom receipt #{receipt.id}"
            else:
                notes = f"From receipt #{receipt.id}"

            expense = Expense(
                user_id=current_user.id,
                description=expense_description,
                amount=Decimal(str(expense_amount)),
                category=expense_category,
                date=expense_date,
                notes=notes
            )
            db.session.add(expense)
            db.session.flush()

            # Associate
            receipt_item.associate_with_expense(expense.id)

            flash(f'Created expense: {expense_description}', 'success')

        else:
            return jsonify({'success': False, 'error': 'Invalid association type'}), 400

        # Update receipt status
        receipt.update_status()
        db.session.commit()

        logger.info(f"Receipt item {receipt_item_id} associated as {association_type} by user {current_user.id}")

        return jsonify({
            'success': True,
            'association_type': receipt_item.association_type,
            'receipt_status': receipt.status,
            'progress': receipt.association_progress
        })

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Association failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@receipts_bp.route('/<int:receipt_id>/disassociate', methods=['POST'])
@login_required
def disassociate_item(receipt_id):
    """Remove association from receipt item."""
    receipt = Receipt.query.filter_by(id=receipt_id, user_id=current_user.id).first_or_404()

    receipt_item_id = request.form.get('receipt_item_id', type=int)
    delete_expense = request.form.get('delete_expense', 'false') == 'true'

    if not receipt_item_id:
        return jsonify({'success': False, 'error': 'Missing receipt_item_id'}), 400

    receipt_item = ReceiptItem.query.filter_by(
        id=receipt_item_id,
        receipt_id=receipt_id
    ).first_or_404()

    try:
        # If associated with expense and delete flag is set, delete expense
        if delete_expense and receipt_item.expense_id:
            expense = Expense.query.get(receipt_item.expense_id)
            if expense and expense.user_id == current_user.id:
                db.session.delete(expense)

        # Clear association
        receipt_item.clear_association()

        # Update receipt status
        receipt.update_status()
        db.session.commit()

        flash('Association removed', 'success')

        return jsonify({
            'success': True,
            'receipt_status': receipt.status,
            'progress': receipt.association_progress
        })

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Disassociation failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@receipts_bp.route('/<int:receipt_id>/update-item', methods=['POST'])
@login_required
def update_receipt_item(receipt_id):
    """Update receipt item details (user corrections)."""
    receipt = Receipt.query.filter_by(id=receipt_id, user_id=current_user.id).first_or_404()

    receipt_item_id = request.form.get('receipt_item_id', type=int)

    if not receipt_item_id:
        return jsonify({'success': False, 'error': 'Missing receipt_item_id'}), 400

    receipt_item = ReceiptItem.query.filter_by(
        id=receipt_item_id,
        receipt_id=receipt_id
    ).first_or_404()

    try:
        # Update fields if provided
        if 'description' in request.form:
            receipt_item.user_description = request.form['description']
        if 'quantity' in request.form:
            receipt_item.user_quantity = int(request.form['quantity'])
        if 'unit_price' in request.form:
            receipt_item.user_unit_price = Decimal(request.form['unit_price'])
        if 'total_price' in request.form:
            receipt_item.user_total_price = Decimal(request.form['total_price'])
        if 'notes' in request.form:
            receipt_item.notes = request.form['notes']

        db.session.commit()

        flash('Item updated', 'success')

        return jsonify({
            'success': True,
            'item': receipt_item.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Update failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@receipts_bp.route('/<int:receipt_id>/mark-complete', methods=['POST'])
@login_required
def mark_complete(receipt_id):
    """Mark receipt as completed."""
    receipt = Receipt.query.filter_by(id=receipt_id, user_id=current_user.id).first_or_404()

    try:
        receipt.status = 'completed'
        receipt.completed_at = datetime.utcnow()
        db.session.commit()

        flash('Receipt marked as completed', 'success')
        return redirect(url_for('receipts.list_receipts'))

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Mark complete failed: {e}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('receipts.view_receipt', receipt_id=receipt_id))


@receipts_bp.route('/<int:receipt_id>/discard', methods=['POST'])
@login_required
def discard_receipt(receipt_id):
    """Mark receipt as discarded."""
    receipt = Receipt.query.filter_by(id=receipt_id, user_id=current_user.id).first_or_404()

    try:
        receipt.status = 'discarded'
        db.session.commit()

        flash('Receipt discarded', 'success')
        return redirect(url_for('receipts.list_receipts'))

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Discard failed: {e}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('receipts.view_receipt', receipt_id=receipt_id))


@receipts_bp.route('/<int:receipt_id>', methods=['DELETE'])
@login_required
def delete_receipt(receipt_id):
    """Delete receipt and its image."""
    receipt = Receipt.query.filter_by(id=receipt_id, user_id=current_user.id).first_or_404()

    try:
        # Delete image from Cloudinary
        processor = ReceiptImageProcessor(user_id=current_user.id)
        processor.delete_receipt(receipt.image_public_id)

        # Manually delete receipt_usage records first to avoid FK constraint issues
        from qventory.models.receipt_usage import ReceiptUsage
        ReceiptUsage.query.filter_by(receipt_id=receipt_id).delete()

        # Delete receipt (cascade will delete receipt_items)
        db.session.delete(receipt)
        db.session.commit()

        logger.info(f"Receipt {receipt_id} deleted by user {current_user.id}")

        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Delete failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@receipts_bp.route('/api/<int:receipt_id>/items')
@login_required
def get_receipt_items_json(receipt_id):
    """Get receipt items as JSON (for AJAX)."""
    receipt = Receipt.query.filter_by(id=receipt_id, user_id=current_user.id).first_or_404()

    items = receipt.items.order_by(ReceiptItem.line_number).all()

    return jsonify({
        'success': True,
        'items': [item.to_dict() for item in items],
        'receipt': receipt.to_dict()
    })


@receipts_bp.route('/api/<int:receipt_id>/debug')
@login_required
def debug_receipt(receipt_id):
    """Debug endpoint to check receipt processing status."""
    receipt = Receipt.query.filter_by(id=receipt_id, user_id=current_user.id).first_or_404()

    items = receipt.items.order_by(ReceiptItem.line_number).all()

    debug_info = {
        'receipt_id': receipt.id,
        'status': receipt.status,
        'uploaded_at': receipt.uploaded_at.isoformat() if receipt.uploaded_at else None,
        'ocr_provider': receipt.ocr_provider,
        'ocr_processed_at': receipt.ocr_processed_at.isoformat() if receipt.ocr_processed_at else None,
        'ocr_confidence': receipt.ocr_confidence,
        'ocr_error_message': receipt.ocr_error_message,
        'merchant_name': receipt.merchant_name,
        'total_amount': float(receipt.total_amount) if receipt.total_amount else None,
        'items_count': len(items),
        'items': [
            {
                'id': item.id,
                'line_number': item.line_number,
                'description': item.description,
                'user_description': item.user_description,
                'final_description': item.final_description,
                'quantity': float(item.quantity) if item.quantity else None,
                'unit_price': float(item.unit_price) if item.unit_price else None,
                'total_price': float(item.total_price) if item.total_price else None,
                'inventory_item_id': item.inventory_item_id,
                'expense_id': item.expense_id
            }
            for item in items
        ],
        'raw_text_preview': receipt.ocr_raw_text[:500] if receipt.ocr_raw_text else None
    }

    return jsonify(debug_info)
