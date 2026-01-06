"""
Tracking Helper - Unified tracking via EasyPost API
Supports USPS, FedEx, UPS, DHL and 100+ carriers
"""
import os
import sys
import requests
from typing import Optional
from bs4 import BeautifulSoup
from datetime import datetime

def log_tracking(msg):
    """Helper function for logging"""
    print(f"[TRACKING] {msg}", file=sys.stderr, flush=True)


EASYPOST_API_KEY = os.environ.get('EASYPOST_API_KEY', '')
EASYPOST_API_BASE = 'https://api.easypost.com/v2'


def get_tracking_info(tracking_number, carrier_hint=None):
    """
    Get tracking information for a package using EasyPost

    Args:
        tracking_number: The tracking number
        carrier_hint: Optional carrier hint (USPS, FedEx, UPS, DHL)

    Returns:
        dict: {
            'success': bool,
            'carrier': str,
            'status': str,  # pre_transit, in_transit, out_for_delivery, delivered, etc.
            'status_detail': str,
            'shipped_at': datetime or None,
            'delivered_at': datetime or None,
            'est_delivery_date': datetime or None,
            'tracking_details': list,  # All scan events
            'error': str (if success=False)
        }
    """
    if not EASYPOST_API_KEY:
        return {
            'success': False,
            'error': 'EASYPOST_API_KEY not configured'
        }

    if not tracking_number:
        return {
            'success': False,
            'error': 'No tracking number provided'
        }

    try:
        # EasyPost auto-detects the carrier!
        payload = {
            'tracker': {
                'tracking_code': tracking_number.strip()
            }
        }

        # Optional: provide carrier hint to speed up lookup
        if carrier_hint:
            payload['tracker']['carrier'] = carrier_hint

        headers = {
            'Authorization': f'Bearer {EASYPOST_API_KEY}',
            'Content-Type': 'application/json'
        }

        log_tracking(f"Looking up tracking: {tracking_number}")

        response = requests.post(
            f'{EASYPOST_API_BASE}/trackers',
            headers=headers,
            json=payload,
            timeout=10
        )

        if response.status_code in [200, 201]:
            data = response.json()

            # Parse the response
            carrier = data.get('carrier', 'Unknown')
            status = data.get('status', 'unknown')
            status_detail = data.get('status_detail', '')

            # Parse dates
            shipped_at = _parse_easypost_date(data.get('shipment_date'))
            delivered_at = _parse_easypost_date(data.get('delivered_at'))
            est_delivery_date = _parse_easypost_date(data.get('est_delivery_date'))

            # Get tracking details (all scan events)
            tracking_details = data.get('tracking_details', [])

            log_tracking(f"Success: {tracking_number} - {carrier} - {status}")

            return {
                'success': True,
                'carrier': carrier,
                'status': status,
                'status_detail': status_detail,
                'shipped_at': shipped_at,
                'delivered_at': delivered_at,
                'est_delivery_date': est_delivery_date,
                'tracking_details': tracking_details,
                'raw_data': data  # Store full response for debugging
            }

        elif response.status_code == 422:
            # Invalid tracking number or carrier not found
            error_data = response.json()
            error_msg = error_data.get('error', {}).get('message', 'Invalid tracking number')
            log_tracking(f"Error: {tracking_number} - {error_msg}")

            return {
                'success': False,
                'error': error_msg
            }

        else:
            log_tracking(f"API Error {response.status_code}: {response.text}")
            return {
                'success': False,
                'error': f'API returned status {response.status_code}'
            }

    except requests.exceptions.Timeout:
        log_tracking(f"Timeout looking up {tracking_number}")
        return {
            'success': False,
            'error': 'Request timeout'
        }

    except Exception as e:
        log_tracking(f"Exception: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def _parse_easypost_date(date_str):
    """Parse EasyPost date format to datetime"""
    if not date_str:
        return None

    try:
        # EasyPost uses ISO 8601 format
        # Example: "2025-10-11T14:32:00Z"
        return datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')
    except:
        try:
            # Try with milliseconds
            return datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.%fZ')
        except:
            log_tracking(f"Could not parse date: {date_str}")
            return None


def detect_carrier(tracking_number):
    """
    Detect carrier from tracking number pattern (fallback if EasyPost fails)

    Returns: 'USPS', 'FedEx', 'UPS', 'DHL', or 'Unknown'
    """
    if not tracking_number:
        return 'Unknown'

    tracking = tracking_number.strip()

    # UPS: Always starts with 1Z
    if tracking.startswith('1Z') and len(tracking) == 18:
        return 'UPS'

    # USPS: Various patterns
    if (tracking[0:2] in ['94', '93', '92', '95', '82', 'EC', 'CP', 'RA', 'EA'] and
        len(tracking) >= 20):
        return 'USPS'

    if tracking.startswith('420') and len(tracking) >= 24:
        return 'USPS'

    # FedEx: 12, 15, or 20 digits
    if tracking.isdigit():
        length = len(tracking)
        if length in [12, 15] or (length == 22 and tracking.startswith('96')):
            return 'FedEx'

    # DHL: 10-11 digits
    if tracking.isdigit() and len(tracking) in [10, 11]:
        return 'DHL'

    return 'Unknown'


def _get_selenium_driver():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
    except Exception as exc:
        log_tracking(f"Selenium unavailable: {exc}")
        return None

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        options.binary_location = chrome_bin

    driver_path = os.environ.get("CHROMEDRIVER_PATH")
    try:
        if driver_path:
            service = Service(driver_path)
            return webdriver.Chrome(service=service, options=options)
        return webdriver.Chrome(options=options)
    except Exception as exc:
        log_tracking(f"Failed to start Chrome driver: {exc}")
        return None


def _selenium_get_text(url: str, by, selector: str) -> Optional[str]:
    try:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except Exception as exc:
        log_tracking(f"Selenium wait helpers unavailable: {exc}")
        return None

    driver = _get_selenium_driver()
    if not driver:
        return None
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((by, selector)))
        element = driver.find_element(by, selector)
        return element.text
    except Exception as exc:
        log_tracking(f"Selenium read failed for {url}: {exc}")
        return None
    finally:
        driver.quit()


def _fetch_tracking_page(url: str) -> Optional[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException as exc:
        log_tracking(f"Tracking page request failed: {exc}")
        return None
    if response.status_code != 200:
        log_tracking(f"Tracking page status {response.status_code} for {url}")
        return None
    return response.text


def carrier_delivered_via_web(tracking_number: str, carrier_hint: Optional[str]) -> Optional[bool]:
    """
    Scrape carrier tracking pages to detect delivered status.
    Returns True/False when detected, None when status cannot be determined.
    """
    if not tracking_number:
        return None

    carrier = (carrier_hint or "").strip().lower()

    if "usps" in carrier:
        url = f"https://tools.usps.com/go/TrackConfirmAction?qtc_tLabels1={tracking_number}"
        delivered_text = None
        try:
            from selenium.webdriver.common.by import By
            delivered_text = _selenium_get_text(url, By.CSS_SELECTOR, "p.tb-status")
        except Exception:
            delivered_text = None
        if delivered_text is None:
            html = _fetch_tracking_page(url)
            if not html:
                return None
            soup = BeautifulSoup(html, "html.parser")
            status_elem = soup.find("p", class_="tb-status")
            delivered_text = status_elem.get_text(strip=True) if status_elem else None
        if delivered_text and delivered_text.strip().lower() == "delivered":
            return True
        return False

    if "fedex" in carrier or "fed ex" in carrier:
        url = f"https://www.fedex.com/fedextrack/?trknbr={tracking_number}"
        delivered_text = None
        try:
            from selenium.webdriver.common.by import By
            delivered_text = _selenium_get_text(url, By.ID, "status_delivered")
        except Exception:
            delivered_text = None
        if delivered_text is None:
            html = _fetch_tracking_page(url)
            if not html:
                return None
            soup = BeautifulSoup(html, "html.parser")
            status_elem = soup.find("span", id="status_delivered")
            delivered_text = status_elem.get_text(strip=True) if status_elem else None
        if delivered_text and "delivered" in delivered_text.strip().lower():
            return True
        return False

    if "ups" in carrier:
        url = f"https://www.ups.com/track?tracknum={tracking_number}&loc=en_US&requester=QUIC"
        delivered_text = None
        try:
            from selenium.webdriver.common.by import By
            delivered_text = _selenium_get_text(url, By.ID, "st_App_DelvdLabel")
        except Exception:
            delivered_text = None
        if delivered_text is None:
            html = _fetch_tracking_page(url)
            if not html:
                return None
            soup = BeautifulSoup(html, "html.parser")
            status_elem = soup.find("span", id="st_App_DelvdLabel")
            delivered_text = status_elem.get_text(strip=True) if status_elem else None
        if delivered_text and "delivered" in delivered_text.strip().lower():
            return True
        return False

    return None


def batch_get_tracking_info(tracking_numbers):
    """
    Get tracking info for multiple packages

    Args:
        tracking_numbers: List of (tracking_number, carrier_hint) tuples

    Returns:
        dict: {tracking_number: tracking_info_dict}
    """
    results = {}

    for item in tracking_numbers:
        if isinstance(item, tuple):
            tracking_number, carrier_hint = item
        else:
            tracking_number = item
            carrier_hint = None

        results[tracking_number] = get_tracking_info(tracking_number, carrier_hint)

    return results
