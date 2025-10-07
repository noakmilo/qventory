"""
Image Processing Helper
Download external images, compress them, and upload to Cloudinary
"""
import os
import sys
import requests
from io import BytesIO
from PIL import Image
import cloudinary
import cloudinary.uploader

def log_img(msg):
    """Helper function for logging"""
    print(f"[IMAGE_PROCESSOR] {msg}", file=sys.stderr, flush=True)

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)


def download_and_upload_image(image_url, target_size_kb=2, max_dimension=400):
    """
    Download an image from URL, compress it to ~2KB, and upload to Cloudinary

    Args:
        image_url (str): URL of the image to download
        target_size_kb (int): Target file size in KB (default 2KB)
        max_dimension (int): Max width/height for thumbnail (default 400px)

    Returns:
        str: Cloudinary URL of uploaded image, or None if failed
    """
    if not image_url:
        return None

    try:
        log_img(f"Downloading image from: {image_url}")

        # Download image with no-referrer header (for eBay)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': ''  # No referrer
        }
        response = requests.get(image_url, headers=headers, timeout=10)
        response.raise_for_status()

        log_img(f"Downloaded {len(response.content)} bytes")

        # Open image with Pillow
        img = Image.open(BytesIO(response.content))

        # Convert to RGB if needed (handle PNG with transparency)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Resize to thumbnail maintaining aspect ratio
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        log_img(f"Resized to: {img.size}")

        # Compress to target size
        # Start with quality 85 and reduce if needed
        target_bytes = target_size_kb * 1024
        quality = 85

        while quality > 20:
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            size = buffer.tell()

            if size <= target_bytes or quality <= 20:
                break

            # Reduce quality more aggressively if still too large
            if size > target_bytes * 2:
                quality -= 20
            elif size > target_bytes * 1.5:
                quality -= 10
            else:
                quality -= 5

        buffer.seek(0)
        final_size_kb = buffer.tell() / 1024
        log_img(f"Compressed to {final_size_kb:.2f}KB at quality {quality}")

        # Upload to Cloudinary
        log_img("Uploading to Cloudinary...")
        result = cloudinary.uploader.upload(
            buffer,
            folder="qventory/items",
            resource_type="image",
            format="jpg",
            transformation=[
                {'quality': 'auto:low', 'fetch_format': 'auto'}
            ]
        )

        cloudinary_url = result.get('secure_url')
        log_img(f"Upload success: {cloudinary_url}")

        return cloudinary_url

    except requests.exceptions.RequestException as e:
        log_img(f"Download error: {str(e)}")
        return None
    except Exception as e:
        log_img(f"Processing error: {str(e)}")
        return None


def batch_process_images(image_urls, target_size_kb=2, max_dimension=400):
    """
    Process multiple images in batch

    Args:
        image_urls (list): List of image URLs
        target_size_kb (int): Target file size in KB
        max_dimension (int): Max width/height for thumbnails

    Returns:
        list: List of Cloudinary URLs (None for failed uploads)
    """
    results = []
    for idx, url in enumerate(image_urls):
        log_img(f"Processing image {idx + 1}/{len(image_urls)}")
        cloudinary_url = download_and_upload_image(url, target_size_kb, max_dimension)
        results.append(cloudinary_url)

    return results


def delete_cloudinary_image(image_url):
    """
    Delete an image from Cloudinary by URL
    Extracts public_id from Cloudinary URL and deletes it

    Args:
        image_url (str): Cloudinary URL of the image

    Returns:
        bool: True if deleted successfully, False otherwise
    """
    if not image_url:
        return False

    # Check if this is actually a Cloudinary URL
    if 'cloudinary.com' not in image_url:
        log_img(f"Not a Cloudinary URL, skipping: {image_url}")
        return False

    try:
        # Extract public_id from URL
        # Example: https://res.cloudinary.com/dxxxx/image/upload/v123456/qventory/items/abc123.jpg
        # public_id: qventory/items/abc123

        # Split by '/upload/' to get the path after it
        if '/upload/' not in image_url:
            log_img(f"Invalid Cloudinary URL format: {image_url}")
            return False

        path_after_upload = image_url.split('/upload/')[-1]

        # Remove version (v123456/) if present
        parts = path_after_upload.split('/')
        if parts[0].startswith('v') and parts[0][1:].isdigit():
            parts = parts[1:]  # Skip version

        # Remove file extension
        public_id_parts = '/'.join(parts).rsplit('.', 1)
        public_id = public_id_parts[0]

        log_img(f"Deleting Cloudinary image with public_id: {public_id}")

        # Delete from Cloudinary
        result = cloudinary.uploader.destroy(public_id)

        if result.get('result') == 'ok':
            log_img(f"Successfully deleted: {public_id}")
            return True
        else:
            log_img(f"Delete failed: {result}")
            return False

    except Exception as e:
        log_img(f"Error deleting Cloudinary image: {str(e)}")
        return False
