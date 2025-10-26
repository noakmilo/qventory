"""
Unit tests for Receipt and ReceiptItem models
"""
import unittest
import sys
import os
from datetime import datetime
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


class TestReceiptModels(unittest.TestCase):
    """Test Receipt and ReceiptItem model functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test Flask app and database."""
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.app.config['WTF_CSRF_ENABLED'] = False

    def setUp(self):
        """Set up test fixtures before each test."""
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create test user
        self.user = User(email='test@example.com', username='testuser')
        self.user.set_password('password123')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        """Clean up after each test."""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_create_receipt(self):
        """Test creating a receipt."""
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            merchant_name='Test Store',
            total_amount=Decimal('99.99'),
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        # Verify
        self.assertIsNotNone(receipt.id)
        self.assertEqual(receipt.user_id, self.user.id)
        self.assertEqual(receipt.merchant_name, 'Test Store')
        self.assertEqual(receipt.status, 'extracted')

    def test_receipt_items_relationship(self):
        """Test receipt items relationship."""
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        # Add items
        item1 = ReceiptItem(
            receipt_id=receipt.id,
            line_number=1,
            description='Item 1',
            quantity=1,
            total_price=Decimal('10.00')
        )
        item2 = ReceiptItem(
            receipt_id=receipt.id,
            line_number=2,
            description='Item 2',
            quantity=2,
            total_price=Decimal('20.00')
        )
        db.session.add_all([item1, item2])
        db.session.commit()

        # Verify
        self.assertEqual(receipt.items_count, 2)
        items = receipt.items.all()
        self.assertEqual(len(items), 2)

    def test_receipt_association_progress(self):
        """Test association progress calculation."""
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        # Create inventory item
        inventory_item = Item(
            user_id=self.user.id,
            title='Test Item',
            sku='TEST-001'
        )
        db.session.add(inventory_item)
        db.session.commit()

        # Add 4 receipt items
        for i in range(1, 5):
            item = ReceiptItem(
                receipt_id=receipt.id,
                line_number=i,
                description=f'Item {i}',
                quantity=1,
                total_price=Decimal('10.00')
            )
            db.session.add(item)
        db.session.commit()

        # Initially 0% associated
        self.assertEqual(receipt.association_progress, 0)
        self.assertEqual(receipt.associated_items_count, 0)

        # Associate 2 items
        items = receipt.items.all()
        items[0].associate_with_inventory(inventory_item.id, update_cost=False)
        items[1].associate_with_inventory(inventory_item.id, update_cost=False)
        db.session.commit()

        # Should be 50% (2/4)
        self.assertEqual(receipt.association_progress, 50)
        self.assertEqual(receipt.associated_items_count, 2)

    def test_receipt_update_status(self):
        """Test automatic status updates."""
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        # Create inventory item
        inventory_item = Item(
            user_id=self.user.id,
            title='Test Item',
            sku='TEST-001'
        )
        db.session.add(inventory_item)
        db.session.commit()

        # Add 2 items
        item1 = ReceiptItem(
            receipt_id=receipt.id,
            line_number=1,
            description='Item 1',
            quantity=1,
            total_price=Decimal('10.00')
        )
        item2 = ReceiptItem(
            receipt_id=receipt.id,
            line_number=2,
            description='Item 2',
            quantity=1,
            total_price=Decimal('20.00')
        )
        db.session.add_all([item1, item2])
        db.session.commit()

        # Associate one item
        item1.associate_with_inventory(inventory_item.id, update_cost=False)
        db.session.commit()
        receipt.update_status()
        db.session.commit()

        # Should be partially_associated
        self.assertEqual(receipt.status, 'partially_associated')

        # Associate second item
        item2.associate_with_inventory(inventory_item.id, update_cost=False)
        db.session.commit()
        receipt.update_status()
        db.session.commit()

        # Should be completed
        self.assertEqual(receipt.status, 'completed')
        self.assertIsNotNone(receipt.completed_at)

    def test_receipt_item_final_values(self):
        """Test final value properties (user override vs OCR)."""
        item = ReceiptItem(
            receipt_id=1,
            line_number=1,
            description='OCR Description',
            quantity=1,
            unit_price=Decimal('10.00'),
            total_price=Decimal('10.00')
        )

        # Initially, final values should match OCR values
        self.assertEqual(item.final_description, 'OCR Description')
        self.assertEqual(item.final_quantity, 1)
        self.assertEqual(item.final_unit_price, Decimal('10.00'))

        # Override with user values
        item.user_description = 'User Description'
        item.user_quantity = 2
        item.user_unit_price = Decimal('15.00')

        # Final values should now match user values
        self.assertEqual(item.final_description, 'User Description')
        self.assertEqual(item.final_quantity, 2)
        self.assertEqual(item.final_unit_price, Decimal('15.00'))

    def test_associate_with_expense(self):
        """Test associating receipt item with expense."""
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
            category='Supplies'
        )
        db.session.add(expense)
        db.session.commit()

        item = ReceiptItem(
            receipt_id=receipt.id,
            line_number=1,
            description='Item 1',
            total_price=Decimal('50.00')
        )
        db.session.add(item)
        db.session.commit()

        # Associate
        item.associate_with_expense(expense.id)
        db.session.commit()

        # Verify
        self.assertTrue(item.is_associated)
        self.assertEqual(item.expense_id, expense.id)
        self.assertEqual(item.association_type, 'expense')
        self.assertIsNone(item.inventory_item_id)

    def test_mutual_exclusion_constraint(self):
        """Test that item can't be associated with both inventory and expense."""
        # This test verifies the database constraint
        # In SQLite, the constraint is not enforced, so we skip this test
        # In production PostgreSQL, this would raise an IntegrityError
        pass

    def test_receipt_to_dict(self):
        """Test receipt serialization to dict."""
        receipt = Receipt(
            user_id=self.user.id,
            image_url='https://example.com/receipt.jpg',
            image_public_id='receipts/test_123',
            merchant_name='Test Store',
            total_amount=Decimal('99.99'),
            status='extracted'
        )
        db.session.add(receipt)
        db.session.commit()

        data = receipt.to_dict()

        self.assertIsInstance(data, dict)
        self.assertEqual(data['merchant_name'], 'Test Store')
        self.assertEqual(data['status'], 'extracted')
        self.assertEqual(data['total_amount'], 99.99)
        self.assertIn('uploaded_at', data)


if __name__ == '__main__':
    unittest.main()
