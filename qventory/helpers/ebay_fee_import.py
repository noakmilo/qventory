import csv
from io import TextIOWrapper
from ..extensions import db
from ..models.ebay_fee_rule import EbayFeeRule


def import_ebay_fee_rules_csv(file_storage):
    """
    Import eBay fee rules from CSV upload.
    Expected columns:
      category_id, standard_rate, store_rate, top_rated_discount, fixed_fee
    """
    stream = TextIOWrapper(file_storage.stream, encoding="utf-8")
    reader = csv.DictReader(stream)
    updated = 0
    created = 0

    for row in reader:
        category_id = (row.get("category_id") or "").strip() or None
        try:
            standard_rate = float(row.get("standard_rate") or 0)
        except ValueError:
            continue
        store_rate = row.get("store_rate")
        store_rate = float(store_rate) if store_rate not in (None, "", "null") else None
        top_rated_discount = row.get("top_rated_discount")
        top_rated_discount = float(top_rated_discount) if top_rated_discount not in (None, "", "null") else 10.0
        fixed_fee = row.get("fixed_fee")
        fixed_fee = float(fixed_fee) if fixed_fee not in (None, "", "null") else 0.30

        rule = EbayFeeRule.query.filter_by(category_id=category_id).first()
        if rule:
            rule.standard_rate = standard_rate
            rule.store_rate = store_rate
            rule.top_rated_discount = top_rated_discount
            rule.fixed_fee = fixed_fee
            updated += 1
        else:
            db.session.add(EbayFeeRule(
                category_id=category_id,
                standard_rate=standard_rate,
                store_rate=store_rate,
                top_rated_discount=top_rated_discount,
                fixed_fee=fixed_fee
            ))
            created += 1

    db.session.commit()
    return {"created": created, "updated": updated}
