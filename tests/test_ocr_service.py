"""
Unit tests for OCR service
"""
import unittest
from decimal import Decimal
from datetime import datetime
from qventory.helpers.ocr_service import OCRService, OCRResult


class TestOCRService(unittest.TestCase):
    """Test OCR service functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.ocr_service = OCRService(provider='mock')

    def test_mock_ocr_extraction(self):
        """Test mock OCR extraction returns expected data."""
        result = self.ocr_service.extract_receipt_data('http://example.com/receipt.jpg')

        # Verify basic structure
        self.assertIsInstance(result, OCRResult)
        self.assertIsNotNone(result.raw_text)
        self.assertGreater(len(result.raw_text), 0)

        # Verify confidence
        self.assertIsInstance(result.confidence, float)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

        # Verify merchant
        self.assertIsNotNone(result.merchant_name)
        self.assertIn('TARGET', result.merchant_name.upper())

        # Verify date
        self.assertIsInstance(result.receipt_date, datetime)

        # Verify totals
        self.assertIsInstance(result.subtotal, Decimal)
        self.assertIsInstance(result.tax_amount, Decimal)
        self.assertIsInstance(result.total_amount, Decimal)
        self.assertGreater(result.total_amount, 0)

        # Verify line items
        self.assertIsInstance(result.line_items, list)
        self.assertGreater(len(result.line_items), 0)

    def test_line_items_structure(self):
        """Test line items have correct structure."""
        result = self.ocr_service.extract_receipt_data('http://example.com/receipt.jpg')

        for item in result.line_items:
            self.assertIn('line_number', item)
            self.assertIn('description', item)
            self.assertIn('quantity', item)
            self.assertIn('unit_price', item)
            self.assertIn('total_price', item)
            self.assertIn('confidence', item)

            # Verify types
            self.assertIsInstance(item['line_number'], int)
            self.assertIsInstance(item['description'], str)
            self.assertIsInstance(item['quantity'], int)
            self.assertIsInstance(item['unit_price'], Decimal)
            self.assertIsInstance(item['total_price'], Decimal)
            self.assertIsInstance(item['confidence'], float)

            # Verify values
            self.assertGreater(item['quantity'], 0)
            self.assertGreater(item['unit_price'], 0)
            self.assertGreater(item['total_price'], 0)

    def test_totals_calculation(self):
        """Test that totals are consistent."""
        result = self.ocr_service.extract_receipt_data('http://example.com/receipt.jpg')

        # Calculate sum of line items
        items_total = sum(item['total_price'] for item in result.line_items)

        # Should match subtotal (allowing for rounding)
        self.assertAlmostEqual(
            float(items_total),
            float(result.subtotal),
            places=2,
            msg="Line items total should match subtotal"
        )

        # Total should equal subtotal + tax
        expected_total = result.subtotal + result.tax_amount
        self.assertAlmostEqual(
            float(result.total_amount),
            float(expected_total),
            places=2,
            msg="Total should equal subtotal + tax"
        )

    def test_to_dict_serialization(self):
        """Test OCRResult can be serialized to dict."""
        result = self.ocr_service.extract_receipt_data('http://example.com/receipt.jpg')
        data = result.to_dict()

        self.assertIsInstance(data, dict)
        self.assertIn('raw_text', data)
        self.assertIn('confidence', data)
        self.assertIn('merchant_name', data)
        self.assertIn('line_items', data)

    def test_unknown_provider_error(self):
        """Test that unknown provider returns error."""
        ocr_service = OCRService(provider='invalid_provider')
        result = ocr_service.extract_receipt_data('http://example.com/receipt.jpg')

        self.assertIsNotNone(result.error)
        self.assertIn('Unknown OCR provider', result.error)


if __name__ == '__main__':
    unittest.main()
