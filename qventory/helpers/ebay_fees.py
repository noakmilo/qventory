from ..models.ebay_fee_rule import EbayFeeRule


def estimate_ebay_fees(
    category_id,
    resale_price,
    shipping_cost,
    has_store=False,
    top_rated=False,
    include_fixed_fee=False,
    ads_fee_rate=0.0,
):
    rule = None
    if category_id:
        rule = EbayFeeRule.query.filter_by(category_id=category_id).first()
    if not rule:
        rule = EbayFeeRule.query.filter_by(category_id=None).first()

    if not rule:
        raise ValueError("Missing eBay fee rules. Please seed default fees.")

    fee_rate = rule.resolve_rate(has_store=has_store, top_rated=top_rated)
    fee_base = resale_price + shipping_cost
    marketplace_fee = fee_base * (fee_rate / 100)
    fixed_fee = rule.fixed_fee if include_fixed_fee else 0.0
    ads_fee = resale_price * (ads_fee_rate / 100)
    total_fees = marketplace_fee + fixed_fee + ads_fee

    breakdown = {
        "fee_rate_percent": round(fee_rate, 4),
        "fee_base": round(fee_base, 2),
        "marketplace_fee": round(marketplace_fee, 2),
        "fixed_fee": round(fixed_fee, 2),
        "ads_fee": round(ads_fee, 2),
        "total_fees": round(total_fees, 2),
        "source": "ebay_fee_rules",
    }

    return breakdown
