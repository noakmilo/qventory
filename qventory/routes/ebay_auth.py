"""
eBay OAuth Integration Routes
Handles user-level OAuth flow for eBay account connection
"""
from flask import Blueprint, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import requests
import base64
import os
import secrets
import sys
import xml.etree.ElementTree as ET

from qventory.extensions import db
from qventory.models.marketplace_credential import MarketplaceCredential

ebay_auth_bp = Blueprint('ebay_auth', __name__, url_prefix='/settings/ebay')

def log(msg):
    """Helper function for logging to stderr (visible in journalctl)"""
    print(f"[EBAY_AUTH] {msg}", file=sys.stderr, flush=True)

# eBay OAuth Configuration
EBAY_CLIENT_ID = os.environ.get('EBAY_CLIENT_ID')
EBAY_CLIENT_SECRET = os.environ.get('EBAY_CLIENT_SECRET')
EBAY_ENV = os.environ.get('EBAY_ENV', 'production')

if EBAY_ENV == 'production':
    EBAY_OAUTH_URL = "https://auth.ebay.com/oauth2/authorize"
    EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    EBAY_REDIRECT_URI = os.environ.get('EBAY_REDIRECT_URI', 'https://qventory.com/settings/ebay/callback')
    TRADING_API_URL = "https://api.ebay.com/ws/api.dll"
else:
    EBAY_OAUTH_URL = "https://auth.sandbox.ebay.com/oauth2/authorize"
    EBAY_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    EBAY_REDIRECT_URI = os.environ.get('EBAY_REDIRECT_URI', 'https://qventory.com/settings/ebay/callback')
    TRADING_API_URL = "https://api.sandbox.ebay.com/ws/api.dll"

TRADING_COMPAT_LEVEL = os.environ.get('EBAY_TRADING_COMPAT_LEVEL', '1145')
_XML_NS = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}

# Log configuration on startup
log(f"eBay OAuth Configuration:")
log(f"  Environment: {EBAY_ENV}")
log(f"  Client ID: {'SET' if EBAY_CLIENT_ID else 'NOT SET'}")
log(f"  Client Secret: {'SET' if EBAY_CLIENT_SECRET else 'NOT SET'}")
log(f"  Redirect URI: {EBAY_REDIRECT_URI}")
log(f"  OAuth URL: {EBAY_OAUTH_URL}")
log(f"  Token URL: {EBAY_TOKEN_URL}")

# OAuth scopes for selling and inventory management
EBAY_SCOPES = [
    'https://api.ebay.com/oauth/api_scope',
    'https://api.ebay.com/oauth/api_scope/sell.marketing.readonly',
    'https://api.ebay.com/oauth/api_scope/sell.marketing',
    'https://api.ebay.com/oauth/api_scope/sell.inventory.readonly',
    'https://api.ebay.com/oauth/api_scope/sell.inventory',
    'https://api.ebay.com/oauth/api_scope/sell.account.readonly',
    'https://api.ebay.com/oauth/api_scope/sell.account',
    'https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly',
    'https://api.ebay.com/oauth/api_scope/sell.fulfillment',
    'https://api.ebay.com/oauth/api_scope/sell.analytics.readonly',
    'https://api.ebay.com/oauth/api_scope/sell.finances',
    'https://api.ebay.com/oauth/api_scope/commerce.identity.readonly'
]


@ebay_auth_bp.route('/connect')
@login_required
def connect():
    """
    Initiate eBay OAuth flow
    Redirects user to eBay consent page
    """
    log(f"=== CONNECT ROUTE CALLED ===")
    log(f"User: {current_user.id} ({current_user.username})")

    # Check if credentials are configured
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        log("ERROR: eBay credentials not configured!")
        flash('eBay integration not configured. Please contact administrator.', 'error')
        return redirect(url_for('main.settings'))

    # Generate and store state token for CSRF protection
    state = secrets.token_urlsafe(32)
    session['ebay_oauth_state'] = state
    log(f"Generated state token: {state[:10]}...")

    # Build authorization URL with proper URL encoding
    # eBay requires scopes separated by %20 (not +) and the scope param
    # must NOT double-encode the URLs within each scope string.
    from urllib.parse import urlencode, quote

    scope_string = ' '.join(EBAY_SCOPES)

    base_params = {
        'client_id': EBAY_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': EBAY_REDIRECT_URI,
        'state': state
    }

    # quote_via=quote encodes spaces as %20 instead of +, which eBay requires
    query_string = urlencode(base_params, quote_via=quote)
    # Append scope separately, already space-joined; quote encodes spaces as %20
    query_string += '&scope=' + quote(scope_string, safe='')

    auth_url = f"{EBAY_OAUTH_URL}?{query_string}"

    log(f"Full auth URL: {auth_url}")
    log(f"Redirecting to eBay authorization page...")
    return redirect(auth_url)


@ebay_auth_bp.route('/callback')
def callback():
    """
    eBay OAuth callback
    Exchanges authorization code for access token and refresh token
    """
    log(f"=== CALLBACK ROUTE CALLED ===")
    log(f"Request args: {dict(request.args)}")
    log(f"User authenticated: {current_user.is_authenticated}")

    # Check if user is authenticated
    if not current_user.is_authenticated:
        log("ERROR: User not authenticated in callback!")
        flash('Session expired. Please try again.', 'error')
        return redirect(url_for('auth.login'))

    log(f"User: {current_user.id} ({current_user.username})")

    # Verify state token (CSRF protection)
    state = request.args.get('state')
    stored_state = session.pop('ebay_oauth_state', None)

    log(f"State from eBay: {state[:10] if state else 'None'}...")
    log(f"Stored state: {stored_state[:10] if stored_state else 'None'}...")

    if not state or state != stored_state:
        log("ERROR: State mismatch!")
        flash('Invalid OAuth state. Please try again.', 'error')
        return redirect(url_for('main.settings'))

    # Check for errors from eBay
    error = request.args.get('error')
    if error:
        error_desc = request.args.get('error_description', 'Unknown error')
        log(f"ERROR from eBay: {error} - {error_desc}")
        flash(f'eBay authorization failed: {error_desc}', 'error')
        return redirect(url_for('main.settings'))

    # Get authorization code
    auth_code = request.args.get('code')
    if not auth_code:
        log("ERROR: No authorization code received")
        flash('No authorization code received from eBay.', 'error')
        return redirect(url_for('main.settings'))

    log(f"Authorization code received: {auth_code[:10]}...")

    try:
        # Exchange authorization code for tokens
        log("Exchanging code for token...")
        tokens = exchange_code_for_token(auth_code)

        if not tokens:
            log("ERROR: Failed to get tokens")
            flash('Failed to get access token from eBay.', 'error')
            return redirect(url_for('main.settings'))

        log(f"Tokens received: access_token={tokens['access_token'][:10]}..., refresh_token={tokens['refresh_token'][:10]}...")

        # Get eBay user info
        log("Getting eBay user info...")
        profile = get_ebay_user_profile(tokens['access_token'])
        ebay_user_id = profile.get('username')
        ebay_top_rated = profile.get('top_rated')
        log(f"eBay user ID: {ebay_user_id}")
        log(f"eBay top rated: {ebay_top_rated}")

        # Save or update credentials in database
        log("Saving credentials to database...")
        save_ebay_credentials(
            user_id=current_user.id,
            access_token=tokens['access_token'],
            refresh_token=tokens['refresh_token'],
            expires_in=tokens['expires_in'],
            ebay_user_id=ebay_user_id,
            ebay_top_rated=ebay_top_rated
        )

        # Attempt to detect eBay Store subscription after connection
        try:
            from qventory.helpers.ebay_inventory import sync_ebay_store_subscription
            store_result = sync_ebay_store_subscription(current_user.id)
            if store_result.get('success'):
                level = store_result.get('subscription_level') or 'none'
                monthly_fee = store_result.get('monthly_fee', 0.0) or 0.0
                log(f"eBay store subscription: {level} (${monthly_fee:.2f}/month)")
            else:
                log(f"Store subscription lookup failed: {store_result.get('error')}")
        except Exception as store_error:
            log(f"WARNING: Store subscription lookup failed: {store_error}")

        # NOTE: Commerce API webhook subscriptions are disabled for now
        # They require special access/approval from eBay that may not be available for all accounts
        # Platform Notifications (below) covers the main events: ItemListed, ItemSold, ItemRevised, ItemClosed
        #
        # To enable Commerce API webhooks in the future:
        # 1. Request access to Commerce Notification API from eBay Developer Support
        # 2. Uncomment the code below
        #
        # log("Auto-setting up Commerce API webhook subscriptions...")
        # try:
        #     from qventory.helpers.webhook_auto_setup import auto_setup_webhooks
        #     webhook_result = auto_setup_webhooks(current_user.id)
        #     log(f"Commerce webhook auto-setup: {webhook_result['created']} created, {webhook_result['failed']} failed, {webhook_result['skipped']} skipped")
        # except Exception as webhook_error:
        #     log(f"WARNING: Commerce webhook auto-setup failed: {str(webhook_error)}")

        # Setup Platform Notifications (Trading API - SOAP webhooks for new listings)
        log("Setting up Platform Notifications (for real-time new listing sync)...")
        try:
            from qventory.helpers.webhook_auto_setup import setup_platform_notifications
            platform_result = setup_platform_notifications(current_user.id)

            if platform_result['success']:
                topics = ', '.join(platform_result.get('topics_enabled', []))
                log(f"✓ Platform Notifications enabled: {topics}")
            else:
                log(f"⚠️ Platform Notifications setup failed: {platform_result.get('error')}")
                # Show warning but don't fail the connection

        except Exception as platform_error:
            # Don't fail the whole connection if Platform Notifications fail
            log(f"WARNING: Platform Notifications setup failed: {str(platform_error)}")

        # Create notification that import is starting
        log("Creating import notification...")
        try:
            from qventory.models.notification import Notification
            Notification.create_notification(
                user_id=current_user.id,
                type='info',
                title='Importing eBay Inventory',
                message=f'We are importing your eBay listings. This may take a few moments. You will be notified when the import is complete.',
                link_url='/inventory',
                link_text='View Inventory',
                source='ebay_import'
            )
        except Exception as notif_error:
            log(f"WARNING: Failed to create notification: {str(notif_error)}")

        # Trigger initial inventory import (respects plan limits)
        log("Triggering initial inventory import...")
        try:
            from qventory.tasks import import_ebay_inventory
            # Import in background using Celery
            task = import_ebay_inventory.delay(current_user.id, import_mode='new_only', listing_status='ACTIVE')
            log(f"✓ Initial import triggered: task ID {task.id}")
            flash(f'Successfully connected to eBay! (User: {ebay_user_id}) Importing your inventory in the background...', 'success')
        except Exception as import_error:
            log(f"WARNING: Failed to trigger initial import: {str(import_error)}")
            flash(f'Successfully connected to eBay! (User: {ebay_user_id}) Please import your inventory manually.', 'success')

        log(f"SUCCESS: eBay account connected for user {current_user.username}")
        return redirect(url_for('main.settings'))

    except Exception as e:
        log(f"ERROR in callback: {str(e)}")
        import traceback
        log(f"Traceback: {traceback.format_exc()}")
        flash(f'Error connecting to eBay: {str(e)}', 'error')
        return redirect(url_for('main.settings'))


@ebay_auth_bp.route('/disconnect', methods=['POST'])
@login_required
def disconnect():
    """
    Disconnect eBay account
    Removes credentials from database and cleans up webhooks
    """
    log(f"=== DISCONNECT ROUTE CALLED ===")
    log(f"User: {current_user.id} ({current_user.username})")

    try:
        credential = MarketplaceCredential.query.filter_by(
            user_id=current_user.id,
            marketplace='ebay'
        ).first()

        if credential:
            log(f"Found credential ID: {credential.id}")

            # Clean up webhook subscriptions before deleting credentials
            try:
                from qventory.models.webhook import WebhookSubscription
                from qventory.helpers.ebay_webhooks import delete_webhook_subscription

                subscriptions = WebhookSubscription.query.filter_by(
                    user_id=current_user.id
                ).all()

                log(f"Found {len(subscriptions)} webhook subscriptions to delete")

                for subscription in subscriptions:
                    try:
                        # Try to delete from eBay first
                        log(f"Deleting subscription {subscription.subscription_id} from eBay")
                        delete_webhook_subscription(current_user.id, subscription.subscription_id)
                        log(f"✓ Deleted subscription {subscription.subscription_id} from eBay")
                    except Exception as e:
                        # Log error but continue - eBay subscription might already be expired/deleted
                        log(f"⚠ Failed to delete subscription {subscription.subscription_id} from eBay: {str(e)}")

                    # Delete from local database
                    db.session.delete(subscription)
                    log(f"✓ Deleted subscription {subscription.subscription_id} from database")

                db.session.commit()
                log(f"✓ Cleaned up {len(subscriptions)} webhook subscriptions")

            except Exception as e:
                log(f"⚠ Error cleaning up webhooks (non-fatal): {str(e)}")
                # Continue with credential deletion even if webhook cleanup fails

            # Delete the credential
            db.session.delete(credential)
            db.session.commit()
            log("Credential deleted successfully")
            flash('eBay account disconnected successfully.', 'success')
        else:
            log("No credential found to delete")
            flash('No eBay account connected.', 'info')

    except Exception as e:
        log(f"ERROR disconnecting: {str(e)}")
        import traceback
        log(f"Traceback: {traceback.format_exc()}")
        flash(f'Error disconnecting eBay: {str(e)}', 'error')

    return redirect(url_for('main.settings'))


@ebay_auth_bp.route('/refresh-token', methods=['POST'])
@login_required
def refresh_token():
    """
    Manually refresh eBay token
    Useful for debugging or force refresh
    """
    log(f"=== REFRESH TOKEN ROUTE CALLED ===")
    log(f"User: {current_user.id} ({current_user.username})")

    try:
        credential = MarketplaceCredential.query.filter_by(
            user_id=current_user.id,
            marketplace='ebay'
        ).first()

        if not credential:
            log("ERROR: No credential found")
            flash('No eBay account connected.', 'error')
            return redirect(url_for('main.settings'))

        log(f"Found credential ID: {credential.id}")

        # Get current refresh token
        try:
            refresh_token_val = credential.get_refresh_token()
            log(f"Got refresh token: {refresh_token_val[:20] if refresh_token_val else 'None'}...")
        except Exception as decrypt_error:
            log(f"ERROR decrypting refresh token: {str(decrypt_error)}")
            flash('Token is corrupted. Please disconnect and reconnect your eBay account.', 'error')
            return redirect(url_for('main.settings'))

        if not refresh_token_val:
            log("ERROR: No refresh token available")
            flash('No refresh token available. Please reconnect your eBay account.', 'error')
            return redirect(url_for('main.settings'))

        # Request new access token using refresh token
        log("Calling refresh_access_token...")
        tokens = refresh_access_token(refresh_token_val)

        if not tokens:
            log("ERROR: refresh_access_token returned None")
            flash('Failed to refresh token. Please reconnect your eBay account.', 'error')
            return redirect(url_for('main.settings'))

        log("Token refreshed successfully from eBay API")

        # Update credentials
        credential.set_access_token(tokens['access_token'])
        credential.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens['expires_in'])
        credential.updated_at = datetime.utcnow()
        db.session.commit()

        log("Credentials updated in database")
        flash('eBay token refreshed successfully.', 'success')

    except Exception as e:
        log(f"ERROR refreshing token: {str(e)}")
        import traceback
        log(f"Traceback: {traceback.format_exc()}")
        flash(f'Error refreshing token: {str(e)}', 'error')

    return redirect(url_for('main.settings'))


# ==================== Helper Functions ====================

def exchange_code_for_token(auth_code):
    """
    Exchange authorization code for access token and refresh token

    Args:
        auth_code: Authorization code from eBay callback

    Returns:
        dict with access_token, refresh_token, expires_in
    """
    log("exchange_code_for_token: Starting token exchange...")

    # Create Basic Auth header
    credentials = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}"
    b64_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {b64_credentials}'
    }

    data = {
        'grant_type': 'authorization_code',
        'code': auth_code,
        'redirect_uri': EBAY_REDIRECT_URI
    }

    log(f"Token URL: {EBAY_TOKEN_URL}")
    log(f"Redirect URI: {EBAY_REDIRECT_URI}")
    log(f"Auth code: {auth_code[:10]}...")

    try:
        response = requests.post(EBAY_TOKEN_URL, headers=headers, data=data, timeout=10)
        log(f"Response status: {response.status_code}")

        if response.status_code != 200:
            log(f"ERROR response body: {response.text}")

        response.raise_for_status()

        token_data = response.json()
        log("Token exchange successful!")

        return {
            'access_token': token_data['access_token'],
            'refresh_token': token_data['refresh_token'],
            'expires_in': token_data.get('expires_in', 7200)  # Usually 2 hours
        }
    except Exception as e:
        log(f"ERROR in exchange_code_for_token: {str(e)}")
        raise


def refresh_access_token(refresh_token):
    """
    Refresh access token using refresh token

    Args:
        refresh_token: eBay refresh token

    Returns:
        dict with new access_token and expires_in
    """
    # Create Basic Auth header
    credentials = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}"
    b64_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {b64_credentials}'
    }

    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'scope': ' '.join(EBAY_SCOPES)
    }

    response = requests.post(EBAY_TOKEN_URL, headers=headers, data=data, timeout=10)
    response.raise_for_status()

    token_data = response.json()

    return {
        'access_token': token_data['access_token'],
        'refresh_token': token_data.get('refresh_token', refresh_token),  # May return new refresh token
        'expires_in': token_data.get('expires_in', 7200)
    }


def refresh_access_token_debug(refresh_token):
    """
    Refresh access token and return raw response for debugging (do not store tokens).
    """
    credentials = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}"
    b64_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {b64_credentials}'
    }

    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'scope': ' '.join(EBAY_SCOPES)
    }

    response = requests.post(EBAY_TOKEN_URL, headers=headers, data=data, timeout=10)
    raw_text = response.text
    try:
        token_data = response.json()
    except Exception:
        token_data = None

    log(f"[OAUTH_DEBUG] Refresh status: {response.status_code}")
    log(f"[OAUTH_DEBUG] Response body: {raw_text[:2000]}")

    return {
        'status_code': response.status_code,
        'json': token_data,
        'text': raw_text
    }


@ebay_auth_bp.route('/oauth-debug', methods=['GET'])
@login_required
def oauth_debug():
    """
    Debug route to log and return OAuth token refresh response (redacted).
    """
    credential = MarketplaceCredential.query.filter_by(
        user_id=current_user.id,
        marketplace='ebay',
        is_active=True
    ).first()

    if not credential:
        return jsonify({'ok': False, 'error': 'ebay_not_connected'}), 400

    refresh_token_val = credential.get_refresh_token()
    if not refresh_token_val:
        return jsonify({'ok': False, 'error': 'missing_refresh_token'}), 400

    debug_result = refresh_access_token_debug(refresh_token_val)
    token_json = debug_result.get('json') or {}

    # Redact tokens before returning
    redacted = dict(token_json)
    if 'access_token' in redacted:
        redacted['access_token'] = f"{str(redacted['access_token'])[:12]}...redacted"
    if 'refresh_token' in redacted:
        redacted['refresh_token'] = f"{str(redacted['refresh_token'])[:12]}...redacted"

    return jsonify({
        'ok': True,
        'status_code': debug_result.get('status_code'),
        'token_response': redacted
    })


def get_ebay_user_info(access_token):
    """
    Get eBay user information using access token
    Tries multiple APIs to get the username

    Args:
        access_token: eBay access token

    Returns:
        str: eBay username/user ID
    """
    base_url = "https://api.ebay.com" if EBAY_ENV == 'production' else "https://api.sandbox.ebay.com"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    # Try 1: Commerce Identity API
    try:
        log("Trying Commerce Identity API...")
        response = requests.get(
            f'{base_url}/commerce/identity/v1/user/',
            headers=headers,
            timeout=10
        )
        log(f"Commerce Identity API status: {response.status_code}")

        if response.status_code == 200:
            user_data = response.json()
            log(f"Commerce Identity API response keys: {list(user_data.keys())}")
            log(f"Commerce Identity API full response: {user_data}")
            username = user_data.get('username')
            if username:
                log(f"Got username from Commerce Identity API: {username}")
                return username
            else:
                log("No username field in Commerce Identity response")
        else:
            log(f"Commerce Identity API error response: {response.text[:300]}")
    except Exception as e:
        log(f"Commerce Identity API exception: {str(e)}")
        import traceback
        log(f"Commerce Identity API traceback: {traceback.format_exc()}")

    # Try 2: Account API - get seller username
    try:
        log("Trying Account API for seller username...")
        response = requests.get(
            f'{base_url}/sell/account/v1/privilege',
            headers=headers,
            timeout=10
        )
        log(f"Account Privilege API status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            log(f"Privilege API response keys: {list(data.keys())}")
            log(f"Privilege API full response: {data}")

            # The privilege API returns sellingLimit with username
            seller_account = data.get('sellerAccount', {})
            username = seller_account.get('username')
            if username:
                log(f"Got username from Privilege API: {username}")
                return username
            else:
                log("No username in sellerAccount field")
        else:
            log(f"Privilege API error response: {response.text[:300]}")
    except Exception as e:
        log(f"Account Privilege API exception: {str(e)}")
        import traceback
        log(f"Privilege API traceback: {traceback.format_exc()}")

    # Try 3: Fulfillment Orders API
    try:
        log("Trying Fulfillment Orders API...")
        response = requests.get(
            f'{base_url}/sell/fulfillment/v1/order',
            headers=headers,
            params={'limit': 1},
            timeout=10
        )
        log(f"Fulfillment API status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            log(f"Fulfillment API response keys: {list(data.keys())}")
            log(f"Fulfillment API has orders: {len(data.get('orders', []))} orders")

            # Check if there are orders and extract seller info
            if data.get('orders'):
                first_order = data['orders'][0]
                log(f"First order keys: {list(first_order.keys())}")
                seller_info = first_order.get('seller', {})
                log(f"Seller info: {seller_info}")
                username = seller_info.get('username')
                if username:
                    log(f"Got username from Fulfillment API: {username}")
                    return username
                else:
                    log("No username in seller info")
            else:
                log("No orders found in Fulfillment API response")
        else:
            log(f"Fulfillment API error response: {response.text[:300]}")
    except Exception as e:
        log(f"Fulfillment API exception: {str(e)}")
        import traceback
        log(f"Fulfillment API traceback: {traceback.format_exc()}")

    # Try 4: Trading API GetUser (OAuth)
    try:
        log("Trying Trading API GetUser...")
        xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <DetailLevel>ReturnAll</DetailLevel>
</GetUserRequest>'''

        headers = {
            'X-EBAY-API-SITEID': '0',
            'X-EBAY-API-COMPATIBILITY-LEVEL': TRADING_COMPAT_LEVEL,
            'X-EBAY-API-CALL-NAME': 'GetUser',
            'X-EBAY-API-APP-NAME': EBAY_CLIENT_ID or '',
            'X-EBAY-API-IAF-TOKEN': access_token,
            'Content-Type': 'text/xml'
        }

        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=10)
        log(f"Trading API GetUser status: {response.status_code}")
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            ack = root.find('ebay:Ack', _XML_NS)
            if ack is not None and ack.text in ['Success', 'Warning']:
                user_id_elem = root.find('ebay:User/ebay:UserID', _XML_NS)
                if user_id_elem is not None and user_id_elem.text:
                    log(f"Got username from Trading API: {user_id_elem.text}")
                    return user_id_elem.text
            log(f"Trading API GetUser error response: {response.text[:300]}")
        else:
            log(f"Trading API GetUser HTTP error: {response.text[:300]}")
    except Exception as e:
        log(f"Trading API GetUser exception: {str(e)}")
        import traceback
        log(f"Trading API GetUser traceback: {traceback.format_exc()}")

    log("All APIs failed, could not resolve eBay user ID")
    return None


def get_ebay_top_rated_status(access_token):
    """
    Fetch Top Rated Seller status from Trading API GetUser.
    """
    try:
        xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <DetailLevel>ReturnAll</DetailLevel>
</GetUserRequest>'''

        headers = {
            'X-EBAY-API-SITEID': '0',
            'X-EBAY-API-COMPATIBILITY-LEVEL': TRADING_COMPAT_LEVEL,
            'X-EBAY-API-CALL-NAME': 'GetUser',
            'X-EBAY-API-APP-NAME': EBAY_CLIENT_ID or '',
            'X-EBAY-API-IAF-TOKEN': access_token,
            'Content-Type': 'text/xml'
        }

        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=10)
        if response.status_code != 200:
            return None

        root = ET.fromstring(response.content)
        ack = root.find('ebay:Ack', _XML_NS)
        if ack is None or ack.text not in ['Success', 'Warning']:
            return None

        top_rated_elem = root.find('ebay:User/ebay:SellerInfo/ebay:TopRatedSeller', _XML_NS)
        if top_rated_elem is not None and top_rated_elem.text is not None:
            return top_rated_elem.text.strip().lower() == 'true'

        seller_level = root.find('ebay:User/ebay:SellerInfo/ebay:SellerLevel', _XML_NS)
        if seller_level is not None and seller_level.text:
            return 'toprated' in seller_level.text.strip().lower()

        return None
    except Exception:
        return None


def get_ebay_user_profile(access_token):
    """
    Get username and top rated status for the connected eBay account.
    """
    return {
        'username': get_ebay_user_info(access_token),
        'top_rated': get_ebay_top_rated_status(access_token)
    }


def save_ebay_credentials(user_id, access_token, refresh_token, expires_in, ebay_user_id, ebay_top_rated=None):
    """
    Save or update eBay credentials in database

    Args:
        user_id: Qventory user ID
        access_token: eBay access token
        refresh_token: eBay refresh token
        expires_in: Token expiration time in seconds
        ebay_user_id: eBay username
    """
    log(f"save_ebay_credentials: Saving for user {user_id}...")

    # Check if credential already exists
    credential = MarketplaceCredential.query.filter_by(
        user_id=user_id,
        marketplace='ebay'
    ).first()

    if credential:
        log("Updating existing credential...")
        # Update existing
        credential.set_access_token(access_token)
        credential.set_refresh_token(refresh_token)
        credential.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        if ebay_user_id:
            credential.ebay_user_id = ebay_user_id
        else:
            log("Skipping ebay_user_id update (not available)")
        if ebay_top_rated is not None:
            credential.ebay_top_rated = ebay_top_rated
        credential.is_active = True
        credential.updated_at = datetime.utcnow()
    else:
        log("Creating new credential...")
        # Create new
        credential = MarketplaceCredential(
            user_id=user_id,
            marketplace='ebay',
            ebay_user_id=ebay_user_id if ebay_user_id else None,
            ebay_top_rated=ebay_top_rated if ebay_top_rated is not None else False,
            is_active=True
        )
        credential.set_access_token(access_token)
        credential.set_refresh_token(refresh_token)
        credential.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        db.session.add(credential)

    try:
        db.session.commit()
        log("Credentials saved successfully!")
    except Exception as e:
        log(f"ERROR saving credentials: {str(e)}")
        db.session.rollback()
        raise


@ebay_auth_bp.route('/finances-debug', methods=['GET'])
@login_required
def finances_debug():
    """
    Debug route to verify Finances API authorization for the current user.
    Returns raw eBay error body and token scope info for diagnosis.
    """
    import base64 as _base64
    import json as _json
    from qventory.helpers.ebay_inventory import get_user_access_token, EBAY_API_BASE

    access_token = get_user_access_token(current_user.id)
    if not access_token:
        return jsonify({'success': False, 'error': 'missing_access_token'}), 400

    # Decode token claims (JWT middle part) to inspect scopes - no verification needed
    token_claims = {}
    try:
        parts = access_token.split('.')
        if len(parts) == 3:
            padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
            token_claims = _json.loads(_base64.urlsafe_b64decode(padded).decode('utf-8', errors='replace'))
    except Exception as e:
        token_claims = {'decode_error': str(e)}

    # Hit the payout endpoint directly and return the raw response body
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=30)
    start_iso = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")

    raw_results = {}
    test_endpoints = [
        ('finances_payout', '/sell/finances/v1/payout'),
        ('finances_transaction', '/sell/finances/v1/transaction'),
        ('account_privilege', '/sell/account/v1/privilege'),
    ]
    for label, path in test_endpoints:
        try:
            full_url = f"{EBAY_API_BASE}{path}"
            log(f"[FINANCES_DEBUG] Calling: {full_url}")
            resp = requests.get(full_url, headers=headers, params={'limit': 1}, timeout=20)
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raw_results[label] = {
                'url_called': full_url,
                'status_code': resp.status_code,
                'body': body
            }
        except Exception as exc:
            raw_results[label] = {'error': str(exc)}

    return jsonify({
        'token_prefix': access_token[:20] + '...',
        'token_claims': token_claims,
        'raw_results': raw_results
    }), 200
