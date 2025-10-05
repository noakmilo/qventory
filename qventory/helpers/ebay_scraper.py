"""
eBay Sold Listings Scraper
Scrapes real sold items from eBay using Selenium to bypass anti-bot protection
"""
import urllib.parse
import re
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup


def create_ebay_sold_url(item_title):
    """
    Convert item title to eBay sold listings search URL

    Args:
        item_title: The item title to search for

    Returns:
        Full eBay sold listings URL
    """
    # Clean and encode the title
    query = urllib.parse.quote_plus(item_title)

    # Build eBay sold listings URL
    url = f"https://www.ebay.com/sch/i.html?_nkw={query}&_sacat=0&_from=R40&rt=nc&LH_Sold=1&LH_Complete=1"

    return url


def get_selenium_driver():
    """
    Create and configure a Selenium WebDriver with anti-detection settings

    Returns:
        WebDriver instance
    """
    chrome_options = Options()

    # Headless mode
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')

    # Anti-detection measures
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # Realistic window size
    chrome_options.add_argument('--window-size=1920,1080')

    # User agent
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # Create driver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Additional anti-detection
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        '''
    })

    return driver


def scrape_ebay_sold_listings(item_title, max_results=10):
    """
    Scrape eBay sold listings for an item using Selenium

    Args:
        item_title: The item title to search for
        max_results: Maximum number of results to return (default: 10)

    Returns:
        dict with:
            - success: bool
            - url: str (eBay search URL)
            - items: list of dicts with title, price, link
            - error: str (if failed)
    """
    driver = None

    try:
        url = create_ebay_sold_url(item_title)

        # Create Selenium driver
        driver = get_selenium_driver()

        # Navigate to eBay
        driver.get(url)

        # Wait for listings to load
        time.sleep(2)  # Initial wait for page load

        # Wait for search results
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "s-item"))
            )
        except:
            # If timeout, still try to parse what we have
            pass

        # Additional wait for dynamic content
        time.sleep(1)

        # Get page source and parse with BeautifulSoup
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Find all listing items
        listings = []

        # Try modern eBay layout (s-item class)
        items = soup.find_all('li', class_='s-item')

        if not items:
            # Try alternative selector
            items = soup.find_all('div', class_='s-item__info')

        for item in items[:max_results * 2]:  # Get more to filter later
            try:
                # Extract title
                title_elem = item.find('div', class_='s-item__title') or item.find('h3', class_='s-item__title')
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)

                # Skip "Shop on eBay" promotional items
                if title.lower() in ['shop on ebay', 'new listing', '']:
                    continue

                # Extract price
                price_elem = item.find('span', class_='s-item__price')
                if not price_elem:
                    continue

                price_text = price_elem.get_text(strip=True)

                # Clean price (remove $ and commas, handle ranges)
                price_clean = re.sub(r'[,$]', '', price_text)

                # If it's a range (e.g., "$20 to $30"), take the first value
                if ' to ' in price_clean:
                    price_clean = price_clean.split(' to ')[0].strip()

                # Convert to float
                try:
                    price = float(price_clean)
                except ValueError:
                    continue

                # Extract link
                link_elem = item.find('a', class_='s-item__link')
                if not link_elem:
                    continue

                link = link_elem.get('href', '')

                # Calculate similarity score (simple word matching)
                similarity = calculate_title_similarity(item_title.lower(), title.lower())

                listings.append({
                    'title': title,
                    'price': price,
                    'link': link,
                    'similarity': similarity
                })

            except Exception as e:
                # Skip individual items that fail
                continue

        # Sort by similarity (most relevant first)
        listings.sort(key=lambda x: x['similarity'], reverse=True)

        # Limit results
        listings = listings[:max_results]

        return {
            'success': True,
            'url': url,
            'items': listings,
            'count': len(listings)
        }

    except Exception as e:
        return {
            'success': False,
            'url': url if 'url' in locals() else '',
            'error': f'Scraping failed: {str(e)}',
            'items': [],
            'count': 0
        }

    finally:
        # Always close the driver
        if driver:
            try:
                driver.quit()
            except:
                pass


def calculate_title_similarity(title1, title2):
    """
    Simple word-based similarity score

    Args:
        title1: First title (lowercase)
        title2: Second title (lowercase)

    Returns:
        float: Similarity score (0-1)
    """
    # Remove common words
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}

    words1 = set(re.findall(r'\w+', title1)) - stop_words
    words2 = set(re.findall(r'\w+', title2)) - stop_words

    if not words1 or not words2:
        return 0.0

    # Jaccard similarity
    intersection = words1.intersection(words2)
    union = words1.union(words2)

    return len(intersection) / len(union) if union else 0.0


def format_listings_for_ai(listings_data):
    """
    Format scraped listings into a clean structure for OpenAI

    Args:
        listings_data: Result from scrape_ebay_sold_listings()

    Returns:
        str: Formatted text for AI prompt
    """
    if not listings_data.get('success') or not listings_data.get('items'):
        return "No sold listings found on eBay."

    items = listings_data['items']

    output = f"Found {len(items)} recently sold items on eBay:\n\n"

    for i, item in enumerate(items, 1):
        output += f"{i}. {item['title']}\n"
        output += f"   Sold for: ${item['price']:.2f}\n"
        output += f"   Relevance: {item['similarity']*100:.0f}%\n"
        output += f"   Link: {item['link']}\n\n"

    return output
