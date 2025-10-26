"""
Integration tests for the complete receipt workflow
"""
import unittest
import sys
import os
import io
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from qventory import create_app
from qventory.extensions import db
from qventory.models.user import User
from qventory.models.receipt import Receipt
from qventory.models.receipt_item import ReceiptItem
from qventory.models.item import Item
from qventory.models.expense import Expense


class TestReceiptWorkflow(unittest.TestCase):
    """Integration tests for end-to-end receipt workflow."""

    @classmethod
    def setUpClass(cls):
        """Set up test Flask app."""
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.app.config['WTF_CSRF_ENABLED'] = False
        # Use mock OCR for testing
        cls.app.config['OCR_PROVIDER'] = 'mock'

    def setUp(self):
        """Set up test fixtures."""
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()
        db.create_all()

        # Create and login test user
        self.user = User(email='test@example.com', username='testuser')
        self.user.set_password('password123')
        self.user.email_verified = True
        db.session.add(self.user)
        db.session.commit()

        # Login
        self.client.post('/auth/login', data={
            'email': 'test@example.com',
            'password': 'password123'
        }, follow_redirects=True)

    def tearDown(self):
        """Clean up."""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_upload_receipt_page_loads(self):
        """Test that upload page loads correctly."""
        response = self.client.get('/receipts/upload')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Upload Receipt', response.data)

    def test_list_receipts_page_loads(self):
        """Test that receipts list page loads."""
        response = self.client.get('/receipts/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Receipts', response.data)

    def test_complete_workflow_inventory_association(self):
        """
        Test complete workflow:
        1. Create receipt with items
        2. Create inventory item
        3. Associate receipt item with inventory
        4. Verify status updates
        """
        # 1. Create receipt
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            thumbnail_url='https://example.com/receipt_thumb.jpg',
            merchant_name='Test Store',
            total_amount=Decimal('50.00'),
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        # 2. Add receipt items
        item1 = ReceiptItem(
            receipt_id=receipt.id,
            line_number=1,
            description='USB Drive',
            quantity=1,
            unit_price=Decimal('20.00'),
            total_price=Decimal('20.00')
        )
        item2 = ReceiptItem(
            receipt_id=receipt.id,
            line_number=2,
            description='Mouse',
            quantity=1,
            unit_price=Decimal('30.00'),
            total_price=Decimal('30.00')
        )
        db.session.add_all([item1, item2])
        db.session.commit()

        # 3. Create inventory item
        inventory_item = Item(
            user_id=self.user.id,
            title='USB Flash Drive 64GB',
            sku='USB-001',
            item_cost=Decimal('15.00')  # Old cost
        )
        db.session.add(inventory_item)
        db.session.commit()

        initial_cost = inventory_item.item_cost

        # 4. Associate receipt item with inventory (update cost)
        response = self.client.post(
            f'/receipts/{receipt.id}/associate',
            data={
                'receipt_item_id': item1.id,
                'association_type': 'inventory',
                'inventory_item_id': inventory_item.id,
                'update_cost': 'true'
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])

        # Verify association
        db.session.refresh(item1)
        self.assertTrue(item1.is_associated)
        self.assertEqual(item1.inventory_item_id, inventory_item.id)
        self.assertEqual(item1.association_type, 'inventory')

        # Verify cost was updated
        db.session.refresh(inventory_item)
        self.assertEqual(inventory_item.item_cost, Decimal('20.00'))
        self.assertNotEqual(inventory_item.item_cost, initial_cost)

        # Verify receipt status updated to partially_associated
        db.session.refresh(receipt)
        receipt.update_status()
        db.session.commit()
        self.assertEqual(receipt.status, 'partially_associated')

        # 5. Associate second item
        response = self.client.post(
            f'/receipts/{receipt.id}/associate',
            data={
                'receipt_item_id': item2.id,
                'association_type': 'inventory',
                'inventory_item_id': inventory_item.id,
                'update_cost': 'false'
            }
        )
        self.assertEqual(response.status_code, 200)

        # Verify receipt status updated to completed
        db.session.refresh(receipt)
        receipt.update_status()
        db.session.commit()
        self.assertEqual(receipt.status, 'completed')
        self.assertEqual(receipt.association_progress, 100)

    def test_complete_workflow_expense_association(self):
        """
        Test complete workflow with expense creation:
        1. Create receipt with item
        2. Create expense from receipt item
        3. Verify association
        """
        # 1. Create receipt
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            merchant_name='Office Depot',
            total_amount=Decimal('25.00'),
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        # 2. Add receipt item
        item = ReceiptItem(
            receipt_id=receipt.id,
            line_number=1,
            description='Office Supplies',
            quantity=1,
            total_price=Decimal('25.00')
        )
        db.session.add(item)
        db.session.commit()

        # 3. Create expense via association
        response = self.client.post(
            f'/receipts/{receipt.id}/associate',
            data={
                'receipt_item_id': item.id,
                'association_type': 'expense',
                'expense_description': 'Office Supplies',
                'expense_amount': '25.00',
                'expense_category': 'Supplies'
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])

        # Verify expense was created
        db.session.refresh(item)
        self.assertTrue(item.is_associated)
        self.assertIsNotNone(item.expense_id)
        self.assertEqual(item.association_type, 'expense')

        expense = Expense.query.get(item.expense_id)
        self.assertIsNotNone(expense)
        self.assertEqual(expense.description, 'Office Supplies')
        self.assertEqual(expense.amount, Decimal('25.00'))
        self.assertEqual(expense.category, 'Supplies')

    def test_disassociate_and_delete_expense(self):
        """Test removing association and deleting expense."""
        # Create receipt with expense association
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        expense = Expense(
            user_id=self.user.id,
            description='Test Expense',
            amount=Decimal('50.00'),
            category='Test'
        )
        db.session.add(expense)
        db.session.commit()

        item = ReceiptItem(
            receipt_id=receipt.id,
            line_number=1,
            description='Item',
            total_price=Decimal('50.00')
        )
        item.associate_with_expense(expense.id)
        db.session.add(item)
        db.session.commit()

        expense_id = expense.id

        # Disassociate and delete expense
        response = self.client.post(
            f'/receipts/{receipt.id}/disassociate',
            data={
                'receipt_item_id': item.id,
                'delete_expense': 'true'
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])

        # Verify association removed
        db.session.refresh(item)
        self.assertFalse(item.is_associated)
        self.assertIsNone(item.expense_id)

        # Verify expense deleted
        expense = Expense.query.get(expense_id)
        self.assertIsNone(expense)

    def test_view_receipt_details(self):
        """Test viewing receipt details page."""
        # Create receipt
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            merchant_name='Test Store',
            total_amount=Decimal('100.00'),
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        # Add items
        item = ReceiptItem(
            receipt_id=receipt.id,
            line_number=1,
            description='Test Item',
            quantity=1,
            total_price=Decimal('100.00')
        )
        db.session.add(item)
        db.session.commit()

        # View receipt
        response = self.client.get(f'/receipts/{receipt.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Test Store', response.data)
        self.assertIn(b'Test Item', response.data)

    def test_mark_receipt_complete(self):
        """Test marking receipt as completed."""
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        # Mark complete
        response = self.client.post(
            f'/receipts/{receipt.id}/mark-complete',
            follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)

        # Verify status changed
        db.session.refresh(receipt)
        self.assertEqual(receipt.status, 'completed')
        self.assertIsNotNone(receipt.completed_at)

    def test_discard_receipt(self):
        """Test discarding receipt."""
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        # Discard
        response = self.client.post(
            f'/receipts/{receipt.id}/discard',
            follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)

        # Verify status changed
        db.session.refresh(receipt)
        self.assertEqual(receipt.status, 'discarded')

    def test_filter_receipts_by_status(self):
        """Test filtering receipts by status."""
        # Create receipts with different statuses
        statuses = ['pending', 'extracted', 'completed', 'failed']
        for status in statuses:
            receipt = Receipt(
                user_id=self.user.id,
                image_url=f'https://example.com/{status}.jpg',
                image_public_id=f'receipts/{status}',
                status=status
            )
            db.session.add(receipt)
        db.session.commit()

        # Test filter
        response = self.client.get('/receipts/?status=completed')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'completed', response.data)


if __name__ == '__main__':
    unittest.main()
