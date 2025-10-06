"""
eBay Native API Scraper
Uses eBay Finding API to get sold listings from last 7 days
Replaces Browse.AI completely
"""
import requests
from datetime import datetime, timedelta
from urllib.parse import quote
import sys

from .ebay_oauth import get_ebay_oauth


def get_sold_listings_ebay_api(query, max_results=10, days_back=7):
    """
    Get sold listings from eBay using Finding API

    Args:
        query: Search term (e.g. "Sony PlayStation 5")
        max_results: Maximum number of results to return
        days_back: How many days back to search (default 7)

    Returns:
        dict with:
        - count: number of items found
        - items: list of {title, price, link, sold_date, condition}
        - url: eBay search URL
    """
    print(f"[eBay API] Searching sold listings: '{query}' (last {days_back} days)", file=sys.stderr)

    oauth = get_ebay_oauth()

    try:
        # Get OAuth token
        token = oauth.get_token()

        # eBay Finding API endpoint (uses different auth - App ID in URL)
        # For sold items, we use Browse API instead which supports OAuth

        # Calculate date range (last N days)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        # Format dates for eBay (ISO 8601)
        date_from = start_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        date_to = end_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')

        # Use Browse API search with sold filter
        browse_url = f"{oauth.api_endpoint}/buy/browse/v1/item_summary/search"

        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "X-EBAY-C-ENDUSERCTX": "contextualLocation=country=US,zip=90210"
        }

        # Build filter string for sold items
        # Filter format: buyingOptions:{FIXED_PRICE|AUCTION},itemEndDate:[dateFrom..dateTo]
        filter_parts = [
            f"buyingOptions:{{FIXED_PRICE|AUCTION}}",
            f"itemEndDate:[{date_from}..{date_to}]",
            "conditions:{NEW|USED|UNSPECIFIED}"
        ]

        params = {
            "q": query,
            "limit": min(max_results, 50),  # eBay max is 200, but we limit to 50
            "filter": ",".join(filter_parts),
            "sort": "endTimeSoonest",  # Most recent first
            "fieldgroups": "EXTENDED"  # Get more details
        }

        print(f"[eBay API] GET {browse_url}", file=sys.stderr)
        print(f"[eBay API] Query: {query}, Limit: {params['limit']}", file=sys.stderr)

        response = requests.get(browse_url, headers=headers, params=params, timeout=30)

        print(f"[eBay API] Status: {response.status_code}", file=sys.stderr)

        if response.status_code == 200:
            data = response.json()

            total = data.get('total', 0)
            items_data = data.get('itemSummaries', [])

            print(f"[eBay API] Found {total} total, returned {len(items_data)} items", file=sys.stderr)

            # Parse items
            items = []
            for item in items_data:
                try:
                    # Extract price
                    price_info = item.get('price', {})
                    price_value = float(price_info.get('value', 0))

                    # Extract condition
                    condition = item.get('condition', 'Used')

                    # Item URL
                    item_url = item.get('itemWebUrl', '')

                    # Sold date (itemEndDate)
                    end_date_str = item.get('itemEndDate', '')
                    sold_date = end_date_str[:10] if end_date_str else ''

                    items.append({
                        'title': item.get('title', ''),
                        'price': price_value,
                        'link': item_url,
                        'sold_date': sold_date,
                        'condition': condition,
                        'currency': price_info.get('currency', 'USD')
                    })

                except Exception as e:
                    print(f"[eBay API] Error parsing item: {e}", file=sys.stderr)
                    continue

            # Sort by most recent sold date
            items.sort(key=lambda x: x['sold_date'], reverse=True)

            # Limit to max_results
            items = items[:max_results]

            # Build eBay search URL
            ebay_search_url = f"https://www.ebay.com/sch/i.html?_nkw={quote(query)}&LH_Sold=1&LH_Complete=1"

            result = {
                'count': len(items),
                'items': items,
                'url': ebay_search_url,
                'total_available': total,
                'query': query,
                'date_range': {
                    'from': start_date.strftime('%Y-%m-%d'),
                    'to': end_date.strftime('%Y-%m-%d')
                }
            }

            print(f"[eBay API] ✓ Successfully parsed {len(items)} sold listings", file=sys.stderr)

            return result

        elif response.status_code == 401:
            print(f"[eBay API] ✗ Unauthorized - token may be invalid", file=sys.stderr)
            # Try to refresh token
            oauth.invalidate_cache()
            raise Exception("eBay OAuth token invalid - please check credentials")

        elif response.status_code == 204:
            # No content - no results found
            print(f"[eBay API] No sold listings found for '{query}'", file=sys.stderr)
            return {
                'count': 0,
                'items': [],
                'url': f"https://www.ebay.com/sch/i.html?_nkw={quote(query)}&LH_Sold=1&LH_Complete=1",
                'total_available': 0,
                'query': query,
                'date_range': {
                    'from': start_date.strftime('%Y-%m-%d'),
                    'to': end_date.strftime('%Y-%m-%d')
                }
            }

        else:
            error_msg = f"eBay API error {response.status_code}: {response.text}"
            print(f"[eBay API] ✗ {error_msg}", file=sys.stderr)
            raise Exception(error_msg)

    except requests.exceptions.Timeout:
        raise Exception("eBay API request timed out after 30 seconds")
    except requests.exceptions.RequestException as e:
        raise Exception(f"eBay API network error: {e}")
    except Exception as e:
        print(f"[eBay API] ✗ Unexpected error: {e}", file=sys.stderr)
        raise


def format_listings_for_ai(scraped_data):
    """
    Format eBay API results for OpenAI prompt

    Args:
        scraped_data: Result from get_sold_listings_ebay_api()

    Returns:
        Formatted string for AI analysis
    """
    items = scraped_data.get('items', [])
    count = scraped_data.get('count', 0)
    date_range = scraped_data.get('date_range', {})

    if count == 0:
        return "No sold listings found in the specified time period."

    output = f"SOLD LISTINGS DATA ({date_range.get('from')} to {date_range.get('to')}):\n"
    output += f"Total items analyzed: {count}\n\n"

    for i, item in enumerate(items, 1):
        title = item['title']
        price = item['price']
        currency = item.get('currency', 'USD')
        sold_date = item.get('sold_date', 'Unknown')
        condition = item.get('condition', 'Used')

        output += f"{i}. {title}\n"
        output += f"   Sold: {currency} ${price:.2f}\n"
        output += f"   Date: {sold_date}\n"
        output += f"   Condition: {condition}\n\n"

    return output
