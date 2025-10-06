"""
eBay OAuth Token Manager
Handles Application Token generation and auto-refresh for public API access
"""
import os
import requests
import base64
import json
from datetime import datetime, timedelta
from pathlib import Path

class EbayOAuth:
    """Manages eBay OAuth Application Tokens for public API access"""

    def __init__(self):
        self.client_id = os.environ.get("EBAY_CLIENT_ID")
        self.client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        self.env = os.environ.get("EBAY_ENV", "production")

        # Token URLs
        if self.env == "production":
            self.token_url = "https://api.ebay.com/identity/v1/oauth2/token"
            self.api_endpoint = "https://api.ebay.com"
        else:
            self.token_url = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
            self.api_endpoint = "https://api.sandbox.ebay.com"

        # Token cache
        self.cache_file = Path(__file__).parent.parent / "data" / "ebay_token_cache.json"
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)

        # Current token data
        self._token_data = None

    def _load_cached_token(self):
        """Load token from cache if valid"""
        if not self.cache_file.exists():
            return None

        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)

            # Check if token is still valid (with 5 min buffer)
            expires_at = datetime.fromisoformat(data['expires_at'])
            if datetime.now() < expires_at - timedelta(minutes=5):
                return data
        except Exception as e:
            print(f"[eBay OAuth] Cache read error: {e}")

        return None

    def _save_token_cache(self, token_data):
        """Save token to cache"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(token_data, f, indent=2)
        except Exception as e:
            print(f"[eBay OAuth] Cache write error: {e}")

    def _request_new_token(self):
        """Request new Application Token from eBay"""
        if not self.client_id or not self.client_secret:
            raise ValueError("eBay credentials not configured in environment variables")

        # Create Basic Auth header
        credentials = f"{self.client_id}:{self.client_secret}"
        b64_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {b64_credentials}"
        }

        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope"
        }

        print(f"[eBay OAuth] Requesting new {self.env} token...")

        try:
            response = requests.post(self.token_url, headers=headers, data=data, timeout=10)
            response.raise_for_status()

            token_response = response.json()
            access_token = token_response['access_token']
            expires_in = token_response.get('expires_in', 7200)  # Default 2 hours

            # Calculate expiration time
            expires_at = datetime.now() + timedelta(seconds=expires_in)

            token_data = {
                'access_token': access_token,
                'token_type': token_response.get('token_type', 'Bearer'),
                'expires_in': expires_in,
                'expires_at': expires_at.isoformat(),
                'generated_at': datetime.now().isoformat(),
                'env': self.env
            }

            # Save to cache
            self._save_token_cache(token_data)

            print(f"[eBay OAuth] ✓ Token obtained, expires in {expires_in // 60} minutes")

            return token_data

        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get eBay token: {e}")

    def get_token(self):
        """
        Get valid Application Token (from cache or request new one)
        Returns: access_token string
        """
        # Try cached token first
        cached = self._load_cached_token()
        if cached:
            print(f"[eBay OAuth] Using cached token (expires {cached['expires_at'][:19]})")
            self._token_data = cached
            return cached['access_token']

        # Request new token
        self._token_data = self._request_new_token()
        return self._token_data['access_token']

    def get_auth_header(self):
        """Get Authorization header dict ready for requests"""
        token = self.get_token()
        return {"Authorization": f"Bearer {token}"}

    def invalidate_cache(self):
        """Force token refresh on next request"""
        if self.cache_file.exists():
            self.cache_file.unlink()
        self._token_data = None
        print("[eBay OAuth] Token cache invalidated")


# Singleton instance
_oauth_instance = None

def get_ebay_oauth():
    """Get or create singleton OAuth manager"""
    global _oauth_instance
    if _oauth_instance is None:
        _oauth_instance = EbayOAuth()
    return _oauth_instance
