"""
OCR Service for extracting text and structured data from receipt images.

Supports multiple providers:
- Google Cloud Vision API (recommended, most accurate)
- Tesseract OCR (free, local processing)
- Mock OCR (testing/development)

Configuration via environment variables:
- OCR_PROVIDER: 'google_vision', 'tesseract', 'mock' (default: 'mock')
- GOOGLE_VISION_API_KEY: API key for Google Vision
"""
import os
import re
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class OCRResult:
    """Structured OCR extraction result."""

    def __init__(self):
        self.raw_text: str = ""
        self.confidence: float = 0.0
        self.merchant_name: Optional[str] = None
        self.receipt_date: Optional[datetime] = None
        self.receipt_number: Optional[str] = None
        self.subtotal: Optional[Decimal] = None
        self.tax_amount: Optional[Decimal] = None
        self.total_amount: Optional[Decimal] = None
        self.line_items: List[Dict] = []
        self.error: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary for database storage."""
        return {
            'raw_text': self.raw_text,
            'confidence': self.confidence,
            'merchant_name': self.merchant_name,
            'receipt_date': self.receipt_date,
            'receipt_number': self.receipt_number,
            'subtotal': self.subtotal,
            'tax_amount': self.tax_amount,
            'total_amount': self.total_amount,
            'line_items': self.line_items,
            'error': self.error
        }


class OCRService:
    """OCR service with multiple provider support."""

    def __init__(self, provider: Optional[str] = None):
        """
        Initialize OCR service.

        Args:
            provider: 'google_vision', 'tesseract', or 'mock'.
                     If None, reads from OCR_PROVIDER env var.
        """
        self.provider = provider or os.environ.get('OCR_PROVIDER', 'mock')
        logger.info(f"OCRService initialized with provider: {self.provider}")

    def extract_receipt_data(self, image_url: str) -> OCRResult:
        """
        Extract text and structured data from receipt image.

        Args:
            image_url: URL to the receipt image (Cloudinary, local file, etc.)

        Returns:
            OCRResult with extracted data
        """
        result = OCRResult()

        try:
            if self.provider == 'google_vision':
                result = self._extract_google_vision(image_url)
            elif self.provider == 'tesseract':
                result = self._extract_tesseract(image_url)
            elif self.provider == 'mock':
                result = self._extract_mock(image_url)
            else:
                result.error = f"Unknown OCR provider: {self.provider}"
                logger.error(result.error)

        except Exception as e:
            logger.exception(f"OCR extraction failed: {e}")
            result.error = str(e)

        return result

    def _extract_google_vision(self, image_url: str) -> OCRResult:
        """
        Extract data using Google Cloud Vision API.

        Requires: pip install google-cloud-vision
        Environment: GOOGLE_VISION_API_KEY or GOOGLE_APPLICATION_CREDENTIALS
        """
        result = OCRResult()

        try:
            from google.cloud import vision
            import io
            import requests

            client = vision.ImageAnnotatorClient()

            # Download image
            response = requests.get(image_url)
            response.raise_for_status()
            image_content = response.content

            # Perform OCR
            image = vision.Image(content=image_content)
            response = client.text_detection(image=image)

            if response.error.message:
                result.error = response.error.message
                return result

            # Extract full text
            if response.text_annotations:
                result.raw_text = response.text_annotations[0].description
                result.confidence = response.text_annotations[0].confidence if hasattr(
                    response.text_annotations[0], 'confidence'
                ) else 0.9

                # Parse structured data
                self._parse_receipt_text(result)

            logger.info(f"Google Vision OCR completed with confidence: {result.confidence}")

        except ImportError:
            result.error = "google-cloud-vision not installed. Run: pip install google-cloud-vision"
            logger.error(result.error)
        except Exception as e:
            logger.exception(f"Google Vision OCR failed: {e}")
            result.error = str(e)

        return result

    def _extract_tesseract(self, image_url: str) -> OCRResult:
        """
        Extract data using Tesseract OCR (local processing).

        Requires: pip install pytesseract pillow
        System: tesseract-ocr installed (brew install tesseract on macOS)
        """
        result = OCRResult()

        try:
            import pytesseract
            from PIL import Image
            import requests
            import io

            # Download image
            response = requests.get(image_url)
            response.raise_for_status()
            image = Image.open(io.BytesIO(response.content))

            # Perform OCR with confidence data
            ocr_data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT,
                lang='eng'
            )

            # Extract text
            result.raw_text = pytesseract.image_to_string(image, lang='eng')

            # Calculate average confidence (Tesseract returns per-word confidence)
            confidences = [int(conf) for conf in ocr_data['conf'] if conf != '-1']
            if confidences:
                result.confidence = sum(confidences) / len(confidences) / 100.0  # 0-1 scale

            # Parse structured data
            self._parse_receipt_text(result)

            logger.info(f"Tesseract OCR completed with confidence: {result.confidence}")

        except ImportError:
            result.error = "pytesseract not installed. Run: pip install pytesseract pillow"
            logger.error(result.error)
        except Exception as e:
            logger.exception(f"Tesseract OCR failed: {e}")
            result.error = str(e)

        return result

    def _extract_mock(self, image_url: str) -> OCRResult:
        """
        Mock OCR for development/testing.
        Returns realistic sample data.
        """
        result = OCRResult()
        result.raw_text = """
        TARGET STORE #1234
        123 Main Street
        New York, NY 10001
        (555) 123-4567

        Date: 10/25/2025
        Receipt #: 987654321

        ITEMS PURCHASED:
        USB Flash Drive 64GB       1   $19.99
        Wireless Mouse            1   $24.99
        HDMI Cable 6ft            2   $12.99
        Keyboard RGB              1   $49.99
        Phone Case                1   $15.99

        SUBTOTAL                      $136.94
        TAX (8.875%)                   $12.15
        TOTAL                         $149.09

        VISA ending in 4242
        Auth Code: 123456

        THANK YOU FOR SHOPPING AT TARGET!
        """
        result.confidence = 0.95
        result.merchant_name = "TARGET STORE #1234"
        result.receipt_date = datetime(2025, 10, 25)
        result.receipt_number = "987654321"
        result.subtotal = Decimal("136.94")
        result.tax_amount = Decimal("12.15")
        result.total_amount = Decimal("149.09")

        result.line_items = [
            {
                'line_number': 1,
                'description': 'USB Flash Drive 64GB',
                'quantity': 1,
                'unit_price': Decimal("19.99"),
                'total_price': Decimal("19.99"),
                'confidence': 0.95
            },
            {
                'line_number': 2,
                'description': 'Wireless Mouse',
                'quantity': 1,
                'unit_price': Decimal("24.99"),
                'total_price': Decimal("24.99"),
                'confidence': 0.96
            },
            {
                'line_number': 3,
                'description': 'HDMI Cable 6ft',
                'quantity': 2,
                'unit_price': Decimal("12.99"),
                'total_price': Decimal("25.98"),
                'confidence': 0.94
            },
            {
                'line_number': 4,
                'description': 'Keyboard RGB',
                'quantity': 1,
                'unit_price': Decimal("49.99"),
                'total_price': Decimal("49.99"),
                'confidence': 0.97
            },
            {
                'line_number': 5,
                'description': 'Phone Case',
                'quantity': 1,
                'unit_price': Decimal("15.99"),
                'total_price': Decimal("15.99"),
                'confidence': 0.93
            }
        ]

        logger.info(f"Mock OCR completed with {len(result.line_items)} items")
        return result

    def _parse_receipt_text(self, result: OCRResult):
        """
        Parse raw OCR text to extract structured receipt data.

        This is a heuristic-based parser that works reasonably well
        for common receipt formats. For production, consider using
        specialized receipt parsing services (e.g., Mindee, Taggun, Veryfi).
        """
        lines = result.raw_text.split('\n')

        # Extract merchant (usually first non-empty line)
        for line in lines:
            line = line.strip()
            if line and len(line) > 3:
                result.merchant_name = line
                break

        # Extract date (various formats)
        date_patterns = [
            r'(?:date|fecha)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})'
        ]
        for pattern in date_patterns:
            match = re.search(pattern, result.raw_text, re.IGNORECASE)
            if match:
                try:
                    date_str = match.group(1)
                    # Try common date formats
                    for fmt in ['%m/%d/%Y', '%m-%d-%Y', '%d/%m/%Y', '%Y-%m-%d']:
                        try:
                            result.receipt_date = datetime.strptime(date_str, fmt)
                            break
                        except ValueError:
                            continue
                    if result.receipt_date:
                        break
                except Exception as e:
                    logger.debug(f"Date parsing failed: {e}")

        # Extract receipt number
        receipt_num_patterns = [
            r'(?:receipt|trans|order|#)[:\s#]*(\w+)',
            r'(?:no|num)[:\s]*(\w+)'
        ]
        for pattern in receipt_num_patterns:
            match = re.search(pattern, result.raw_text, re.IGNORECASE)
            if match:
                result.receipt_number = match.group(1)
                break

        # Extract totals (subtotal, tax, total)
        total_patterns = [
            (r'subtotal[:\s]*\$?([\d,]+\.?\d*)', 'subtotal'),
            (r'tax[:\s]*\$?([\d,]+\.?\d*)', 'tax'),
            (r'total[:\s]*\$?([\d,]+\.?\d*)', 'total')
        ]
        for pattern, field in total_patterns:
            match = re.search(pattern, result.raw_text, re.IGNORECASE)
            if match:
                try:
                    amount_str = match.group(1).replace(',', '')
                    amount = Decimal(amount_str)
                    if field == 'subtotal':
                        result.subtotal = amount
                    elif field == 'tax':
                        result.tax_amount = amount
                    elif field == 'total':
                        result.total_amount = amount
                except (InvalidOperation, ValueError) as e:
                    logger.debug(f"Amount parsing failed for {field}: {e}")

        # Extract line items (heuristic: lines with prices)
        # Pattern: description + optional quantity + price
        item_pattern = r'(.+?)\s+(\d+)\s+\$?([\d,]+\.?\d+)'
        line_number = 1
        for line in lines:
            match = re.search(item_pattern, line)
            if match:
                try:
                    description = match.group(1).strip()
                    quantity = int(match.group(2))
                    price_str = match.group(3).replace(',', '')
                    price = Decimal(price_str)

                    # Skip if description contains totals keywords
                    if any(kw in description.lower() for kw in ['subtotal', 'tax', 'total', 'paid', 'change']):
                        continue

                    result.line_items.append({
                        'line_number': line_number,
                        'description': description,
                        'quantity': quantity,
                        'unit_price': price / quantity if quantity > 0 else price,
                        'total_price': price,
                        'confidence': result.confidence
                    })
                    line_number += 1
                except (ValueError, InvalidOperation) as e:
                    logger.debug(f"Line item parsing failed: {e}")

        logger.info(f"Parsed {len(result.line_items)} line items from receipt")


def get_ocr_service(provider: Optional[str] = None) -> OCRService:
    """
    Factory function to get OCR service instance.

    Args:
        provider: OCR provider name, or None to use env var

    Returns:
        OCRService instance
    """
    return OCRService(provider=provider)
