"""
Receipt image processing and Cloudinary upload helper.

Handles:
- Image validation (size, format)
- Cloudinary upload with transformations
- Thumbnail generation
- Image cleanup/deletion
"""
import os
import logging
from typing import Dict, Optional, Tuple
from werkzeug.datastructures import FileStorage
import cloudinary
import cloudinary.uploader
import cloudinary.api

logger = logging.getLogger(__name__)

# Configuration from environment
CLOUDINARY_ENABLED = all([
    os.environ.get('CLOUDINARY_CLOUD_NAME'),
    os.environ.get('CLOUDINARY_API_KEY'),
    os.environ.get('CLOUDINARY_API_SECRET')
])

if CLOUDINARY_ENABLED:
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
        secure=True
    )

# Limits
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp', 'heic', 'heif'}
ALLOWED_MIME_TYPES = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/bmp',
    'image/tiff',
    'image/webp',
    'image/heic',
    'image/heif'
}


class ReceiptImageProcessor:
    """Process and upload receipt images to Cloudinary."""

    def __init__(self, user_id: int):
        """
        Initialize processor for a specific user.

        Args:
            user_id: User ID for organizing uploads in Cloudinary
        """
        self.user_id = user_id
        self.folder = f"qventory/receipts/user_{user_id}"

    def validate_file(self, file: FileStorage) -> Tuple[bool, Optional[str]]:
        """
        Validate uploaded file.

        Args:
            file: Uploaded file from request.files

        Returns:
            (is_valid, error_message)
        """
        # Check if file exists
        if not file or not file.filename:
            return False, "No file uploaded"

        # Check file extension
        filename = file.filename.lower()
        extension = filename.rsplit('.', 1)[1] if '.' in filename else ''
        if extension not in ALLOWED_EXTENSIONS:
            return False, f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"

        # Check MIME type
        if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
            return False, f"Invalid content type: {file.content_type}"

        # Check file size (seek to end, get position, seek back)
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Seek back to start

        if file_size > MAX_FILE_SIZE:
            size_mb = MAX_FILE_SIZE / (1024 * 1024)
            return False, f"File too large. Maximum size: {size_mb}MB"

        if file_size == 0:
            return False, "File is empty"

        return True, None

    def upload_receipt(
        self,
        file: FileStorage,
        receipt_id: Optional[int] = None
    ) -> Dict[str, any]:
        """
        Upload receipt image to Cloudinary.

        Args:
            file: Uploaded file
            receipt_id: Optional receipt ID for naming

        Returns:
            Dict with keys:
                - success: bool
                - url: str (full image URL)
                - thumbnail_url: str (thumbnail URL)
                - public_id: str (Cloudinary identifier)
                - error: str (if success=False)
        """
        result = {
            'success': False,
            'url': None,
            'thumbnail_url': None,
            'public_id': None,
            'error': None
        }

        # Validate file first
        is_valid, error = self.validate_file(file)
        if not is_valid:
            result['error'] = error
            logger.warning(f"File validation failed: {error}")
            return result

        # Check Cloudinary configuration
        if not CLOUDINARY_ENABLED:
            result['error'] = "Cloudinary not configured. Check environment variables."
            logger.error(result['error'])
            return result

        try:
            # Generate public_id
            timestamp = int(os.times().elapsed * 1000)
            public_id_suffix = f"receipt_{receipt_id}" if receipt_id else f"temp_{timestamp}"
            public_id = f"{self.folder}/{public_id_suffix}"

            # Upload to Cloudinary with transformations
            # Force JPEG format to ensure HEIC images work on all browsers
            upload_result = cloudinary.uploader.upload(
                file,
                folder=self.folder,
                public_id=public_id_suffix,
                resource_type='image',
                overwrite=False,
                format='jpg',  # Convert HEIC and other formats to JPEG
                # Transformations
                transformation=[
                    {'quality': 'auto:good'},  # Auto quality optimization
                ],
                # Add context for searchability
                context=f"user_id={self.user_id}|type=receipt",
                tags=['receipt', f'user_{self.user_id}']
            )

            # Extract URLs - force .jpg extension in URL
            result['url'] = upload_result['secure_url']
            result['public_id'] = upload_result['public_id']

            # Generate thumbnail URL (200px wide, auto height) in JPEG format
            result['thumbnail_url'] = cloudinary.CloudinaryImage(
                result['public_id']
            ).build_url(
                width=200,
                height=200,
                crop='fill',
                quality='auto:low',
                format='jpg'  # Force JPEG for thumbnails too
            )

            result['success'] = True
            logger.info(f"Receipt uploaded successfully: {result['public_id']}")

        except Exception as e:
            logger.exception(f"Cloudinary upload failed: {e}")
            result['error'] = f"Upload failed: {str(e)}"

        return result

    def delete_receipt(self, public_id: str) -> bool:
        """
        Delete receipt image from Cloudinary.

        Args:
            public_id: Cloudinary public ID

        Returns:
            True if deleted successfully
        """
        if not CLOUDINARY_ENABLED:
            logger.warning("Cloudinary not configured, cannot delete image")
            return False

        try:
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type='image'
            )
            success = result.get('result') == 'ok'
            if success:
                logger.info(f"Receipt image deleted: {public_id}")
            else:
                logger.warning(f"Receipt deletion failed: {result}")
            return success

        except Exception as e:
            logger.exception(f"Error deleting receipt from Cloudinary: {e}")
            return False

    @staticmethod
    def get_image_info(public_id: str) -> Optional[Dict]:
        """
        Get metadata about an uploaded image.

        Args:
            public_id: Cloudinary public ID

        Returns:
            Dict with image metadata or None if not found
        """
        if not CLOUDINARY_ENABLED:
            return None

        try:
            result = cloudinary.api.resource(
                public_id,
                resource_type='image'
            )
            return {
                'url': result['secure_url'],
                'format': result['format'],
                'width': result['width'],
                'height': result['height'],
                'bytes': result['bytes'],
                'created_at': result['created_at']
            }
        except Exception as e:
            logger.exception(f"Error fetching image info: {e}")
            return None


def allowed_file(filename: str) -> bool:
    """
    Check if filename has allowed extension.

    Args:
        filename: Filename to check

    Returns:
        True if extension is allowed
    """
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string (e.g., "2.5 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"
