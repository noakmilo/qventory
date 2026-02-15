import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from qventory.helpers.ebay_inventory import get_user_access_token
from qventory.helpers.ebay_relist import TRADING_API_URL, TRADING_COMPAT_LEVEL, _XML_NS
from qventory.models.ebay_fee_snapshot import EbayFeeSnapshot
from qventory.extensions import db


def _build_verify_add_fixed_price_item_xml(category_id, price, shipping_cost):
    title = "Qventory Fee Estimate"
    description = "Fee estimate request"
    location = "San Jose, CA"
    postal_code = "95125"
    condition_id = 1000

    xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<VerifyAddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{{token}}</eBayAuthToken>
  </RequesterCredentials>
  <Item>
    <Title>{title}</Title>
    <Description>{description}</Description>
    <PrimaryCategory>
      <CategoryID>{category_id}</CategoryID>
    </PrimaryCategory>
    <StartPrice>{price:.2f}</StartPrice>
    <ConditionID>{condition_id}</ConditionID>
    <Country>US</Country>
    <Currency>USD</Currency>
    <DispatchTimeMax>3</DispatchTimeMax>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Location>{location}</Location>
    <PostalCode>{postal_code}</PostalCode>
    <Quantity>1</Quantity>
    <PaymentMethods>CreditCard</PaymentMethods>
    <ReturnPolicy>
      <ReturnsAcceptedOption>ReturnsAccepted</ReturnsAcceptedOption>
      <ReturnsWithinOption>Days_30</ReturnsWithinOption>
      <RefundOption>MoneyBack</RefundOption>
      <ShippingCostPaidByOption>Buyer</ShippingCostPaidByOption>
    </ReturnPolicy>
    <ShippingDetails>
      <ShippingType>Flat</ShippingType>
      <ShippingServiceOptions>
        <ShippingService>USPSGroundAdvantage</ShippingService>
        <ShippingServiceCost>{shipping_cost:.2f}</ShippingServiceCost>
        <ShippingServicePriority>1</ShippingServicePriority>
      </ShippingServiceOptions>
    </ShippingDetails>
  </Item>
</VerifyAddFixedPriceItemRequest>
"""
    return xml_request


def get_live_fee_estimate(user_id, category_id, price, shipping_cost=0.0, has_store=False, top_rated=False):
    if not category_id:
        return {"success": False, "error": "Missing category_id"}

    price = float(price or 0)
    shipping_cost = float(shipping_cost or 0)
    if price <= 0:
        return {"success": False, "error": "Price must be > 0"}

    cutoff = datetime.utcnow() - timedelta(hours=12)
    cached = EbayFeeSnapshot.query.filter_by(
        user_id=user_id,
        category_id=category_id,
        price=price,
        shipping_cost=shipping_cost,
        has_store=bool(has_store),
        top_rated=bool(top_rated)
    ).filter(EbayFeeSnapshot.created_at >= cutoff).order_by(EbayFeeSnapshot.created_at.desc()).first()

    if cached:
        return {
            "success": True,
            "fee_rate_percent": cached.fee_rate_percent,
            "total_fees": cached.total_fees,
            "fees": cached.fee_breakdown or []
        }

    access_token = get_user_access_token(user_id)
    if not access_token:
        return {"success": False, "error": "No valid eBay access token"}

    xml_request = _build_verify_add_fixed_price_item_xml(category_id, price, shipping_cost)
    xml_request = xml_request.replace("{token}", access_token)

    app_id = os.environ.get('EBAY_CLIENT_ID')
    headers = {
        'X-EBAY-API-SITEID': '0',
        'X-EBAY-API-COMPATIBILITY-LEVEL': TRADING_COMPAT_LEVEL,
        'X-EBAY-API-CALL-NAME': 'VerifyAddFixedPriceItem',
        'X-EBAY-API-APP-NAME': app_id,
        'Content-Type': 'text/xml'
    }

    response = requests.post(TRADING_API_URL, data=xml_request.encode('utf-8'), headers=headers, timeout=30)
    if response.status_code != 200:
        return {"success": False, "error": f"HTTP {response.status_code}"}

    root = ET.fromstring(response.content)
    ack = root.find('ebay:Ack', _XML_NS)
    if ack is None or ack.text not in ['Success', 'Warning']:
        errors = root.findall('.//ebay:Errors', _XML_NS)
        error_msgs = []
        for error in errors:
            error_msg = error.find('ebay:LongMessage', _XML_NS)
            if error_msg is not None:
                error_msgs.append(error_msg.text)
        return {"success": False, "error": '; '.join(error_msgs) or 'Unknown error'}

    fees = []
    total_fees = 0.0
    for fee in root.findall('.//ebay:Fees/ebay:Fee', _XML_NS):
        name = fee.find('ebay:Name', _XML_NS)
        amount = fee.find('ebay:Fee', _XML_NS)
        if name is None or amount is None or amount.text is None:
            continue
        try:
            value = float(amount.text)
        except ValueError:
            continue
        total_fees += value
        fees.append({"name": name.text, "amount": round(value, 2)})

    fee_rate = (total_fees / (price + shipping_cost)) * 100 if (price + shipping_cost) > 0 else 0

    snapshot = EbayFeeSnapshot(
        user_id=user_id,
        category_id=category_id,
        price=price,
        shipping_cost=shipping_cost,
        has_store=bool(has_store),
        top_rated=bool(top_rated),
        fee_rate_percent=fee_rate,
        total_fees=total_fees,
        fee_breakdown=fees
    )
    db.session.add(snapshot)
    db.session.commit()

    return {
        "success": True,
        "fee_rate_percent": fee_rate,
        "total_fees": total_fees,
        "fees": fees
    }
