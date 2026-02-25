# eBay Listing Create (GOD-only)

## Feature Flag
Set `FEATURE_EBAY_LISTING_CREATE_ENABLED=True` to enable the UI and routes.

## Database Migration
Run Alembic migration:
```
alembic upgrade head
```

## Direct Image Upload Flow
1. Frontend requests upload session:
   `POST /api/ebay/images/upload-token`
2. Backend calls eBay Commerce Media API to create an upload session and returns:
   `upload_url`, `headers`, `upload_session_id`
3. Browser uploads the JPEG directly to `upload_url`
4. Frontend confirms:
   `POST /api/ebay/images/confirm`
5. Draft stores the `ebay_image_url` for publishing.

## Publishing Flow (Inventory API)
1. Create/replace inventory item:
   `PUT /sell/inventory/v1/inventory_item/{sku}`
2. Create offer:
   `POST /sell/inventory/v1/offer`
3. Publish offer:
   `POST /sell/inventory/v1/offer/{offerId}/publish`

## Policy IDs (TODO)
This feature requires valid eBay policy IDs per user:
- fulfillmentPolicyId
- paymentPolicyId
- returnPolicyId

These are currently manual inputs in the wizard. Wire to stored policy IDs when available.
