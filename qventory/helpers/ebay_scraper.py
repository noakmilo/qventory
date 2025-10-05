"""
eBay Sold Listings Scraper
Uses Browse.AI to scrape eBay sold listings
Browse.AI handles all anti-bot protection automatically
Sign up: https://www.browse.ai
"""
import urllib.parse
import re
import os
import time
import requests
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


def scrape_url_with_browseai(target_url):
    """
    Scrape any URL using Browse.AI's Extract Structured Data API
    No robot needed - dynamic scraping

    Args:
        target_url: The URL to scrape

    Returns:
        Extracted data or None
    """
    api_key = os.environ.get("BROWSEAI_API_KEY")

    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Use Browse.AI's extract endpoint (no robot needed)
    extract_url = "https://api.browse.ai/v2/extract"

    payload = {
        "url": target_url,
        "extract": {
            "list": {
                "selector": "li.s-item",
                "fields": {
                    "title": {
                        "selector": ".s-item__title",
                        "type": "text"
                    },
                    "price": {
                        "selector": ".s-item__price",
                        "type": "text"
                    },
                    "link": {
                        "selector": "a.s-item__link",
                        "type": "attribute",
                        "attribute": "href"
                    }
                }
            }
        }
    }

    try:
        response = requests.post(extract_url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        result = response.json()
        return result.get("result", {}).get("list", [])

    except Exception as e:
        print(f"Browse.AI extract error: {e}")
        return None


def scrape_ebay_sold_listings(item_title, max_results=10):
    """
    Scrape eBay sold listings using Browse.AI

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

        # Try Browse.AI dynamic extraction
        browse_data = scrape_url_with_browseai(url)

        if browse_data:
            # Extract data from Browse.AI result
            listings = []

            for item_data in browse_data[:max_results * 2]:
                try:
                    title = item_data.get("title", "").strip()
                    price_str = item_data.get("price", "0").strip()
                    link = item_data.get("link", "").strip()

                    # Skip invalid entries
                    if not title or title.lower() in ['shop on ebay', 'new listing', '']:
                        continue

                    # Clean price
                    price_clean = re.sub(r'[,$]', '', price_str)
                    if ' to ' in price_clean:
                        price_clean = price_clean.split(' to ')[0].strip()

                    try:
                        price = float(price_clean)
                    except ValueError:
                        continue

                    similarity = calculate_title_similarity(item_title.lower(), title.lower())

                    listings.append({
                        'title': title,
                        'price': price,
                        'link': link,
                        'similarity': similarity
                    })

                except Exception:
                    continue

            # Sort by similarity
            listings.sort(key=lambda x: x['similarity'], reverse=True)

            return {
                'success': True,
                'url': url,
                'items': listings[:max_results],
                'count': len(listings[:max_results])
            }

        # Fallback: Direct request (will likely fail on eBay)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

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

    except requests.Timeout:
        return {
            'success': False,
            'url': url if 'url' in locals() else '',
            'error': 'Request timed out',
            'items': [],
            'count': 0
        }
    except requests.RequestException as e:
        return {
            'success': False,
            'url': url if 'url' in locals() else '',
            'error': f'Request failed: {str(e)}',
            'items': [],
            'count': 0
        }
    except Exception as e:
        return {
            'success': False,
            'url': url if 'url' in locals() else '',
            'error': f'Scraping failed: {str(e)}',
            'items': [],
            'count': 0
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
