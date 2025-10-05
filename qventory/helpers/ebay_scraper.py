"""
eBay Sold Listings Scraper
Scrapes real sold items from eBay to provide actual market data
"""
import urllib.parse
import requests
from bs4 import BeautifulSoup
import re
import time


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


def scrape_ebay_sold_listings(item_title, max_results=10):
    """
    Scrape eBay sold listings for an item

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
    try:
        url = create_ebay_sold_url(item_title)

        # Set headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

        # Make request with timeout
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find all listing items
        # eBay uses different selectors, try multiple approaches
        listings = []

        # Try modern eBay layout (s-item class)
        items = soup.find_all('div', class_='s-item__info')

        if not items:
            # Try alternative selector
            items = soup.find_all('li', class_='s-item')

        for item in items[:max_results]:
            try:
                # Extract title
                title_elem = item.find('div', class_='s-item__title') or item.find('h3', class_='s-item__title')
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)

                # Skip "Shop on eBay" promotional items
                if title.lower() in ['shop on ebay', 'new listing']:
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

    except requests.Timeout:
        return {
            'success': False,
            'url': url if 'url' in locals() else '',
            'error': 'Request timed out',
            'items': []
        }
    except requests.RequestException as e:
        return {
            'success': False,
            'url': url if 'url' in locals() else '',
            'error': f'Request failed: {str(e)}',
            'items': []
        }
    except Exception as e:
        return {
            'success': False,
            'url': url if 'url' in locals() else '',
            'error': f'Scraping failed: {str(e)}',
            'items': []
        }


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
