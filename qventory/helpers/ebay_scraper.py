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
import json
import requests
from datetime import datetime
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


def save_html_to_json(html_content, item_title, task_id):
    """
    Save HTML content to JSON file on server

    Args:
        html_content: HTML string from Browse.AI
        item_title: Search term used
        task_id: Browse.AI task ID

    Returns:
        Path to saved JSON file
    """
    # Create data directory if it doesn't exist
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'browseai_cache')
    os.makedirs(data_dir, exist_ok=True)

    # Create filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_title = re.sub(r'[^\w\s-]', '', item_title).strip().replace(' ', '_')[:50]
    filename = f"{safe_title}_{timestamp}_{task_id[:8]}.json"
    filepath = os.path.join(data_dir, filename)

    # Prepare data
    data = {
        'task_id': task_id,
        'item_title': item_title,
        'timestamp': timestamp,
        'html_content': html_content,
        'html_length': len(html_content)
    }

    # Save to JSON
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✓ Saved HTML to {filepath}", flush=True)
    return filepath


def scrape_url_with_browseai(target_url):
    """
    Scrape URL using Browse.AI robot
    Returns HTML content and task_id

    Args:
        target_url: The URL to scrape

    Returns:
        Tuple of (html_content, task_id) or (None, None)
    """
    api_key = os.environ.get("BROWSEAI_API_KEY")
    robot_id = os.environ.get("BROWSEAI_ROBOT_ID", "0199b598-b94f-7b53-bd37-bec82a6d78e9")

    if not api_key:
        return None, None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Start robot task
    start_url = f"https://api.browse.ai/v2/robots/{robot_id}/tasks"

    payload = {
        "inputParameters": {
            "originUrl": target_url
        }
    }

    try:
        # Start task
        response = requests.post(start_url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()

        result = response.json()
        task_id = result.get("result", {}).get("id")

        if not task_id:
            return None, None

        print(f"✓ Browse.AI task started: {task_id}", flush=True)

        # Poll for results (Browse.AI can take 60-90 seconds)
        max_attempts = 90  # 90 attempts = 3 minutes max
        for attempt in range(max_attempts):
            time.sleep(2)  # Wait 2 seconds between polls

            status_url = f"https://api.browse.ai/v2/robots/{robot_id}/tasks/{task_id}"
            status_response = requests.get(status_url, headers=headers, timeout=15)
            status_response.raise_for_status()

            status_data = status_response.json()
            status = status_data.get("result", {}).get("status")

            # Log progress every 5 attempts (10 seconds)
            if attempt % 5 == 0:
                elapsed = attempt * 2
                print(f"⏳ Waiting for Browse.AI... ({elapsed}s elapsed)", flush=True)

            if status == "successful":
                # Get captured HTML (Browse.AI returns it as "HTML")
                captured_texts = status_data.get("result", {}).get("capturedTexts", {})
                html_content = captured_texts.get("HTML", "")

                if html_content:
                    print(f"✓ Browse.AI returned HTML ({len(html_content)} chars)", flush=True)
                    return html_content, task_id
                else:
                    print(f"✗ No HTML in capturedTexts. Available keys: {list(captured_texts.keys())}", flush=True)

                return None, None

            elif status in ["failed", "cancelled"]:
                print(f"✗ Browse.AI task {status}", flush=True)
                return None, None

        # Timeout
        print("✗ Browse.AI timed out after 3 minutes", flush=True)
        return None, None

    except Exception as e:
        print(f"Browse.AI error: {e}")
        return None, None


def scrape_ebay_sold_listings(item_title, max_results=10):
    """
    Scrape eBay sold listings using Browse.AI

    FLUJO:
    1. Llamar Browse.AI para obtener HTML
    2. Guardar HTML en JSON
    3. Parsear JSON para extraer listings
    4. Devolver datos estructurados para OpenAI

    Args:
        item_title: The item title to search for
        max_results: Maximum number of results to return (default: 10)

    Returns:
        dict with:
            - success: bool
            - url: str (eBay search URL)
            - items: list of dicts with title, price, link
            - count: int (number of items found)
            - json_path: str (path to saved JSON file)
    """
    try:
        # PASO 1: Crear URL y llamar Browse.AI
        url = create_ebay_sold_url(item_title)
        print(f"📡 Calling Browse.AI for: {item_title}", flush=True)

        html_content, task_id = scrape_url_with_browseai(url)

        if html_content and task_id:
            # PASO 2: Guardar HTML en JSON
            json_path = save_html_to_json(html_content, item_title, task_id)

            # PASO 3: Parsear HTML con BeautifulSoup
            print(f"🔍 Parsing HTML to extract listings...", flush=True)
            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            listings = []

            # Find all eBay listing items
            items = soup.find_all('li', class_='s-item')
            print(f"🔍 Found {len(items)} <li class='s-item'> elements", flush=True)

            if not items:
                items = soup.find_all('div', class_='s-item')
                print(f"🔍 Found {len(items)} <div class='s-item'> elements instead", flush=True)

            # PASO 4: Extraer datos de cada listing
            for item in items[:max_results * 2]:
                try:
                    # Extract title
                    title_elem = (
                        item.find('div', class_='s-item__title') or
                        item.find('h3', class_='s-item__title') or
                        item.find('span', class_='s-item__title')
                    )

                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)

                    # Skip invalid entries
                    if not title or title.lower() in ['shop on ebay', 'new listing', '']:
                        continue

                    # Extract price
                    price_elem = item.find('span', class_='s-item__price')

                    if not price_elem:
                        continue

                    price_str = price_elem.get_text(strip=True)

                    # Clean price (e.g., "$14.50" -> 14.50)
                    price_clean = re.sub(r'[,$]', '', price_str)
                    if ' to ' in price_clean:
                        price_clean = price_clean.split(' to ')[0].strip()

                    try:
                        price = float(price_clean)
                    except ValueError:
                        continue

                    # Extract link
                    link_elem = item.find('a', class_='s-item__link')

                    if not link_elem:
                        continue

                    link = link_elem.get('href', '')

                    # Calculate similarity
                    similarity = calculate_title_similarity(item_title.lower(), title.lower())

                    listings.append({
                        'title': title,
                        'price': price,
                        'link': link,
                        'similarity': similarity
                    })

                except Exception as e:
                    print(f"⚠️  Skipped item due to: {e}", flush=True)
                    continue

            # PASO 5: Ordenar por similitud y devolver resultados
            listings.sort(key=lambda x: x['similarity'], reverse=True)

            print(f"✅ Successfully parsed {len(listings)} listings", flush=True)

            return {
                'success': True,
                'url': url,
                'items': listings[:max_results],
                'count': len(listings[:max_results]),
                'json_path': json_path,
                'task_id': task_id
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
