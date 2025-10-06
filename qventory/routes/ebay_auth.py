"""
eBay OAuth Integration Routes
Handles user-level OAuth flow for eBay account connection
"""
from flask import Blueprint, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import requests
import base64
import os
import secrets

from qventory import db
from qventory.models.marketplace_credential import MarketplaceCredential

ebay_auth_bp = Blueprint('ebay_auth', __name__, url_prefix='/settings/ebay')

# eBay OAuth Configuration
EBAY_CLIENT_ID = os.environ.get('EBAY_CLIENT_ID')
EBAY_CLIENT_SECRET = os.environ.get('EBAY_CLIENT_SECRET')
EBAY_ENV = os.environ.get('EBAY_ENV', 'production')

if EBAY_ENV == 'production':
    EBAY_OAUTH_URL = "https://auth.ebay.com/oauth2/authorize"
    EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    EBAY_REDIRECT_URI = os.environ.get('EBAY_REDIRECT_URI', 'https://qventory.com/settings/ebay/callback')
else:
    EBAY_OAUTH_URL = "https://auth.sandbox.ebay.com/oauth2/authorize"
    EBAY_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    EBAY_REDIRECT_URI = os.environ.get('EBAY_REDIRECT_URI', 'https://qventory.com/settings/ebay/callback')

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
    # Generate and store state token for CSRF protection
    state = secrets.token_urlsafe(32)
    session['ebay_oauth_state'] = state

    # Build authorization URL
    scope_string = ' '.join(EBAY_SCOPES)

    auth_url = (
        f"{EBAY_OAUTH_URL}"
        f"?client_id={EBAY_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={EBAY_REDIRECT_URI}"
        f"&scope={scope_string}"
        f"&state={state}"
    )

    return redirect(auth_url)


@ebay_auth_bp.route('/callback')
@login_required
def callback():
    """
    eBay OAuth callback
    Exchanges authorization code for access token and refresh token
    """
    # Verify state token (CSRF protection)
    state = request.args.get('state')
    stored_state = session.pop('ebay_oauth_state', None)

    if not state or state != stored_state:
        flash('Invalid OAuth state. Please try again.', 'error')
        return redirect(url_for('main.settings'))

    # Check for errors from eBay
    error = request.args.get('error')
    if error:
        error_desc = request.args.get('error_description', 'Unknown error')
        flash(f'eBay authorization failed: {error_desc}', 'error')
        return redirect(url_for('main.settings'))

    # Get authorization code
    auth_code = request.args.get('code')
    if not auth_code:
        flash('No authorization code received from eBay.', 'error')
        return redirect(url_for('main.settings'))

    try:
        # Exchange authorization code for tokens
        tokens = exchange_code_for_token(auth_code)

        if not tokens:
            flash('Failed to get access token from eBay.', 'error')
            return redirect(url_for('main.settings'))

        # Get eBay user info
        ebay_user_id = get_ebay_user_info(tokens['access_token'])

        # Save or update credentials in database
        save_ebay_credentials(
            user_id=current_user.id,
            access_token=tokens['access_token'],
            refresh_token=tokens['refresh_token'],
            expires_in=tokens['expires_in'],
            ebay_user_id=ebay_user_id
        )

        flash(f'Successfully connected to eBay! (User: {ebay_user_id})', 'success')
        return redirect(url_for('main.settings'))

    except Exception as e:
        flash(f'Error connecting to eBay: {str(e)}', 'error')
        return redirect(url_for('main.settings'))


@ebay_auth_bp.route('/disconnect', methods=['POST'])
@login_required
def disconnect():
    """
    Disconnect eBay account
    Removes credentials from database
    """
    try:
        credential = MarketplaceCredential.query.filter_by(
            user_id=current_user.id,
            marketplace='ebay'
        ).first()

        if credential:
            db.session.delete(credential)
            db.session.commit()
            flash('eBay account disconnected successfully.', 'success')
        else:
            flash('No eBay account connected.', 'info')

    except Exception as e:
        flash(f'Error disconnecting eBay: {str(e)}', 'error')

    return redirect(url_for('main.settings'))


@ebay_auth_bp.route('/refresh-token', methods=['POST'])
@login_required
def refresh_token():
    """
    Manually refresh eBay token
    Useful for debugging or force refresh
    """
    try:
        credential = MarketplaceCredential.query.filter_by(
            user_id=current_user.id,
            marketplace='ebay'
        ).first()

        if not credential:
            flash('No eBay account connected.', 'error')
            return redirect(url_for('main.settings'))

        # Get current refresh token
        refresh_token = credential.get_refresh_token()

        if not refresh_token:
            flash('No refresh token available. Please reconnect your eBay account.', 'error')
            return redirect(url_for('main.settings'))

        # Request new access token using refresh token
        tokens = refresh_access_token(refresh_token)

        if not tokens:
            flash('Failed to refresh token. Please reconnect your eBay account.', 'error')
            return redirect(url_for('main.settings'))

        # Update credentials
        credential.set_access_token(tokens['access_token'])
        credential.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens['expires_in'])
        credential.updated_at = datetime.utcnow()
        db.session.commit()

        flash('eBay token refreshed successfully.', 'success')

    except Exception as e:
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

    response = requests.post(EBAY_TOKEN_URL, headers=headers, data=data, timeout=10)
    response.raise_for_status()

    token_data = response.json()

    return {
        'access_token': token_data['access_token'],
        'refresh_token': token_data['refresh_token'],
        'expires_in': token_data.get('expires_in', 7200)  # Usually 2 hours
    }


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


def get_ebay_user_info(access_token):
    """
    Get eBay user information using access token

    Args:
        access_token: eBay access token

    Returns:
        str: eBay username/user ID
    """
    base_url = "https://api.ebay.com" if EBAY_ENV == 'production' else "https://api.sandbox.ebay.com"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    try:
        response = requests.get(
            f'{base_url}/commerce/identity/v1/user/',
            headers=headers,
            timeout=10
        )
        response.raise_for_status()

        user_data = response.json()
        return user_data.get('username', 'Unknown')
    except:
        # If user info fails, return generic identifier
        return 'eBay User'


def save_ebay_credentials(user_id, access_token, refresh_token, expires_in, ebay_user_id):
    """
    Save or update eBay credentials in database

    Args:
        user_id: Qventory user ID
        access_token: eBay access token
        refresh_token: eBay refresh token
        expires_in: Token expiration time in seconds
        ebay_user_id: eBay username
    """
    # Check if credential already exists
    credential = MarketplaceCredential.query.filter_by(
        user_id=user_id,
        marketplace='ebay'
    ).first()

    if credential:
        # Update existing
        credential.set_access_token(access_token)
        credential.set_refresh_token(refresh_token)
        credential.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        credential.ebay_user_id = ebay_user_id
        credential.is_active = True
        credential.updated_at = datetime.utcnow()
    else:
        # Create new
        credential = MarketplaceCredential(
            user_id=user_id,
            marketplace='ebay',
            ebay_user_id=ebay_user_id,
            is_active=True
        )
        credential.set_access_token(access_token)
        credential.set_refresh_token(refresh_token)
        credential.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        db.session.add(credential)

    db.session.commit()
