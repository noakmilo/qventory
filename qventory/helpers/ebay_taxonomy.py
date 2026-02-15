import requests
from datetime import datetime
from ..extensions import db
from ..models.ebay_category import EbayCategory
from .ebay_oauth import EbayOAuth


def _flatten_tree(node, parent_id=None, path=None, level=0, tree_id=None, tree_version=None, out=None):
    if out is None:
        out = []
    if path is None:
        path = []

    category = node.get("category") or {}
    category_id = category.get("categoryId")
    name = category.get("categoryName")
    is_leaf = node.get("leafCategoryTreeNode", False)

    if category_id and name:
        full_path = " > ".join(path + [name])
        out.append({
            "category_id": category_id,
            "name": name,
            "parent_id": parent_id,
            "full_path": full_path,
            "level": level,
            "is_leaf": is_leaf,
            "tree_id": tree_id,
            "tree_version": tree_version,
        })

    for child in node.get("childCategoryTreeNodes") or []:
        _flatten_tree(
            child,
            parent_id=category_id,
            path=path + [name] if name else path,
            level=level + 1,
            tree_id=tree_id,
            tree_version=tree_version,
            out=out
        )

    return out


def sync_ebay_categories(marketplace_id="EBAY_US"):
    oauth = EbayOAuth()
    headers = oauth.get_auth_header()
    headers["Content-Type"] = "application/json"

    default_tree_url = "https://api.ebay.com/commerce/taxonomy/v1/get_default_category_tree_id"
    tree_resp = requests.get(default_tree_url, headers=headers, params={"marketplace_id": marketplace_id}, timeout=15)
    tree_resp.raise_for_status()
    tree_data = tree_resp.json()
    tree_id = tree_data.get("categoryTreeId")

    if not tree_id:
        raise ValueError("Missing categoryTreeId from eBay taxonomy API")

    tree_url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{tree_id}"
    tree_detail = requests.get(tree_url, headers=headers, timeout=30)
    tree_detail.raise_for_status()
    tree_body = tree_detail.json()

    root_node = tree_body.get("rootCategoryNode")
    tree_version = tree_body.get("categoryTreeVersion")
    if not root_node:
        raise ValueError("Missing rootCategoryNode from eBay taxonomy API")

    flat = _flatten_tree(
        root_node,
        parent_id=None,
        path=[],
        level=0,
        tree_id=tree_id,
        tree_version=tree_version
    )

    existing = {
        cat.category_id: cat
        for cat in EbayCategory.query.all()
    }

    updated = 0
    created = 0

    for row in flat:
        cat = existing.get(row["category_id"])
        if cat:
            cat.name = row["name"]
            cat.parent_id = row["parent_id"]
            cat.full_path = row["full_path"]
            cat.level = row["level"]
            cat.is_leaf = row["is_leaf"]
            cat.tree_id = row["tree_id"]
            cat.tree_version = row["tree_version"]
            cat.updated_at = datetime.utcnow()
            updated += 1
        else:
            db.session.add(EbayCategory(**row))
            created += 1

    db.session.commit()
    return {
        "tree_id": tree_id,
        "tree_version": tree_version,
        "total": len(flat),
        "created": created,
        "updated": updated,
    }
