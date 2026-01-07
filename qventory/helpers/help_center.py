from __future__ import annotations

from typing import List, Dict
import re
import markdown2

from qventory.extensions import db
from qventory.models.help_article import HelpArticle


HELP_ARTICLES: List[Dict[str, object]] = [
    {
        "slug": "active-inventory",
        "title": "Active Inventory",
        "summary": "Manage your live inventory, eBay sync, labels, and inline edits.",
        "display_order": 10,
        "body_md": """# Active Inventory

[IMAGE: Active inventory overview]

Active Inventory is the heart of Qventory. It shows every item that is currently available for sale and keeps it in sync with your marketplace data when possible.

## How items get into Active Inventory

- **Connect eBay in Settings** to pull your live listings automatically.
- **Add Item** to create listings that are not on eBay (local, other platforms, or unlisted stock).
- **CSV import** to bring items in bulk.
- **Flipwise and other platforms** can be imported into Qventory when you have those exports available.

## Inline editing (fast updates)

You can edit key fields directly in the table without opening each item:

- **Cost**: click the cost cell and save to update profit metrics.
- **Supplier**: click to assign a source (store, vendor, or person).
- **Location**: update Aisle/Bay/Shelf/Container and save.

[IMAGE: Inline edit for cost, supplier, location]

## QR labels and the A/B/S/C system

Qventory uses a flexible location hierarchy:

- **A** = Aisle
- **B** = Bay
- **S** = Shelf
- **C** = Container

This works for anything from a small room to a large warehouse. You can keep the labels as-is or rename them in **Settings** to match your space.

[IMAGE: A/B/S/C labels example]

## Printing labels

You can generate and print QR labels for locations and items. Labels make it easy to find inventory fast and avoid misplacement.

[IMAGE: QR label print dialog]

## Best practices

- Keep cost and supplier updated for accurate analytics.
- Use consistent location naming to make QR lookup reliable.
- Sync eBay listings regularly for the most current data.
""",
    },
    {
        "slug": "add-item",
        "title": "Add Item",
        "summary": "Create items that are not on eBay and still keep them organized.",
        "display_order": 20,
        "body_md": """# Add Item

[IMAGE: Add item form]

Use Add Item when you want inventory tracked in Qventory that is not part of your eBay account.

## Common use cases

- Items sold locally or in-store
- Stock from other marketplaces
- Items you want to prep before listing online

## What to fill in

- **Title** and **SKU** to identify the item.
- **Cost** and **Price** to power profit calculations.
- **Supplier** to track where the item came from.
- **Location** using the A/B/S/C system.

[IMAGE: Location fields in Add Item]

## Outcome

Your item appears in Active Inventory and can be managed just like eBay items.
""",
    },
    {
        "slug": "qr-batch",
        "title": "QR Batch",
        "summary": "Generate location labels in bulk to organize inventory at scale.",
        "display_order": 30,
        "body_md": """# QR Batch

[IMAGE: QR batch generator]

QR Batch lets you generate many location labels at once so you can organize inventory without missing a spot.

## How it works

1. Select the A/B/S/C components you use.
2. Enter the label values you need.
3. Generate a batch and print.

## Why it matters

Consistent location labels make inventory retrieval fast and reliable, even in large warehouses.

[IMAGE: Printed QR batch labels]
""",
    },
    {
        "slug": "fulfillment",
        "title": "Fulfillment",
        "summary": "Track shipment status and delivery using eBay Fulfillment data.",
        "display_order": 40,
        "body_md": """# Fulfillment

[IMAGE: Fulfillment dashboard]

Fulfillment shows your orders, tracking numbers, and delivery status.

## Where the data comes from

Qventory reads order and tracking details from the **eBay Fulfillment API** and saves them to your account.

## What you can do

- Review orders and tracking info
- See shipment status and delivery progress
- Manually sync if you want the latest data right away

[IMAGE: Order status detail]
""",
    },
    {
        "slug": "auto-relist",
        "title": "Auto Relist",
        "summary": "Relist items automatically or manually with optional changes.",
        "display_order": 50,
        "body_md": """# Auto Relist

[IMAGE: Auto relist dashboard]

Auto Relist lets you relist eBay items without repeating the same setup.

## Two modes

### Automatic
- Schedule relists every N days.
- Great for long-tail inventory that needs regular visibility.

### Manual
- One-time relist with optional changes.
- Useful for quick relists after updates.

[IMAGE: Auto vs manual relist options]
""",
    },
    {
        "slug": "expenses",
        "title": "Expenses",
        "summary": "Track costs and business spending that feed analytics.",
        "display_order": 60,
        "body_md": """# Expenses

[IMAGE: Expenses overview]

Expenses capture your business costs so your analytics and profit reports are accurate.

## What you can track

- Shipping supplies
- Marketplace fees
- Subscriptions
- Storage, rent, or utilities
- Any custom category you define

## How it affects analytics

Expenses are included in total costs and profit calculations across the dashboard.

[IMAGE: Expense categories]
""",
    },
    {
        "slug": "receipts",
        "title": "Receipts",
        "summary": "Upload receipts and connect them to inventory and expenses.",
        "display_order": 70,
        "body_md": """# Receipts

[IMAGE: Receipt upload]

Receipts help you track real purchase costs and keep clean records.

## How it works

- Upload a receipt image.
- Qventory extracts line items with OCR.
- Match those items to Active Inventory or create Expenses.

## Analytics impact

Receipts improve cost accuracy, which improves profit and tax reporting.

[IMAGE: Receipt line item match]
""",
    },
    {
        "slug": "analytics",
        "title": "Analytics",
        "summary": "Understand profit, sales trends, and marketplace fees.",
        "display_order": 80,
        "body_md": """# Analytics

[IMAGE: Analytics dashboard]

Analytics summarizes your sales performance, inventory costs, and profit in one place.

## Core metrics

- **Gross sales** and **net profit**
- **Average sale value**
- **Profit margins**
- **Marketplace fees** and store fees
- **Expenses** and **COGS**

## Payouts and adjustments

When connected to eBay, Qventory tracks payouts and adjustments so you can see net deposited amounts.

[IMAGE: Payout tables]
""",
    },
    {
        "slug": "tax-reports",
        "title": "Tax Reports",
        "summary": "Auto-generated tax summaries based on sales, costs, and expenses.",
        "display_order": 90,
        "body_md": """# Tax Reports

[IMAGE: Tax report summary]

Tax Reports are built from your sales, costs, and expenses to help you prepare for filing.

## Data sources

- **Sales** from your marketplace sync
- **Costs** from Active Inventory and Receipts
- **Expenses** you log manually
- **Fees and shipping costs** from marketplace data

## What you get

- Annual and quarterly summaries
- Exportable data for your accountant

[IMAGE: Tax report export options]
""",
    },
    {
        "slug": "ai-research",
        "title": "AI Research",
        "summary": "Analyze comps and pricing signals before listing.",
        "display_order": 100,
        "body_md": """# AI Research

[IMAGE: AI Research overview]

AI Research helps you price and position listings with data-driven insights.

## How it works

- Pulls recent sold comps from marketplaces
- Summarizes pricing ranges and demand signals
- Highlights keywords and listing opportunities

## Why it matters

Better research leads to stronger pricing decisions and faster sell-through.

[IMAGE: AI Research results]
""",
    },
    {
        "slug": "profit-calculator",
        "title": "Profit Calculator",
        "summary": "Estimate profit and ROI before you list.",
        "display_order": 110,
        "body_md": """# Profit Calculator

[IMAGE: Profit calculator]

Profit Calculator estimates profit and ROI based on cost, fees, and shipping.

## What it helps with

- Decide if an item is worth listing
- Compare margins across marketplaces
- Validate pricing decisions

[IMAGE: Profit breakdown]
""",
    },
    {
        "slug": "settings",
        "title": "Settings",
        "summary": "Connect marketplaces, configure locations, and manage preferences.",
        "display_order": 120,
        "body_md": """# Settings

[IMAGE: Settings overview]

Settings is where you configure the core behavior of Qventory.

## Key sections

- **Marketplace connections** (eBay and others)
- **Location system** (A/B/S/C labels and toggles)
- **Account preferences** and defaults

## Tips

- Connect eBay early to sync inventory.
- Customize A/B/S/C to fit your storage layout.

[IMAGE: Location settings]
""",
    },
]


def seed_help_articles() -> int:
    created = 0
    for article in HELP_ARTICLES:
        slug = article["slug"]
        existing = HelpArticle.query.filter_by(slug=slug).first()
        if existing:
            continue
        record = HelpArticle(
            slug=slug,
            title=article["title"],
            summary=article.get("summary"),
            body_md=article["body_md"],
            is_published=True,
            display_order=article.get("display_order", 0),
        )
        db.session.add(record)
        created += 1
    if created:
        db.session.commit()
    return created


def render_help_markdown(body_md: str) -> str:
    def replace_placeholder(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        return f'\n<div class="help-image-placeholder">[IMAGE: {label}]</div>\n'

    processed = re.sub(r"\[IMAGE:\s*([^\]]+)\]", replace_placeholder, body_md or "")
    return markdown2.markdown(processed, extras=["fenced-code-blocks", "tables"])
