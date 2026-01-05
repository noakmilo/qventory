# Analytics Data Sources in Qventory

This post explains where each Analytics number comes from in Qventory, how it is
calculated, and which data sources feed the dashboard. It is written for product
and engineering readers who want traceability from UI metrics to backend data.

## The Primary Source: Sales

Most analytics metrics are derived from the Sales table. Sales are created and
updated through marketplace imports (mainly eBay), and the analytics route
aggregates those saved records for a selected date range.

Key fields captured per sale:
- sold_price (the item price paid by the buyer)
- shipping_cost (actual shipping cost)
- shipping_charged (what the buyer paid for shipping, if available)
- marketplace_fee
- payment_processing_fee
- other_fees (used for prorated store subscriptions or additional fees)
- sold_at, shipped_at, delivered_at
- tracking_number, carrier, status

This means Analytics does not “infer” sales; it rolls up persisted sales data.

## KPI Sources on the Analytics Page

### Total Sales
- Count of Sale rows in the selected date range.

### Gross Sales
- Sum of Sale.sold_price.

### Net Profit
- Sum of Sale.net_profit (precomputed on each Sale).
- Net profit uses item cost, fees, and shipping to reflect true margin.

### Avg Gross / Sale and Avg Net / Sale
- Gross and Net totals divided by Total Sales.

### Net Profit Margin
- Net Profit divided by Gross Sales, expressed as a percentage.

## Expenses Breakdown

The expenses summary on the analytics page combines cost fields from Sales with
operational expenses stored separately.

- Inventory Spend: sum of Sale.item_cost.
- Marketplace Fees: sum of Sale.marketplace_fee + Sale.payment_processing_fee.
- Shipping: sum of Sale.shipping_cost.
- Store Subscription: sum of Sale.other_fees (store subscription prorate) plus estimated eBay insertion fees once listings exceed the tier limit (Starter 250, Basic 1000, Premium 10000, Anchor 25000, Enterprise 100000; fallback 200 when no tier).
- Business Expenses: sum of Expense.amount within the date range.
- Supplies / Other: reserved for future use (currently 0).

The shipping line item is explicitly the “real shipping cost” saved on each sale,
not the buyer’s shipping charge.

## Trends and Charts

### Sales Overview (Gross vs Net)
- Daily rollup from Sales.
- Gross = sum of sold_price by day.
- Net = sum of net_profit by day.
- Rendered in Chart.js using backend-prepared arrays.

### New Listings Trend
- Derived from Item.listing_date.
- Counts how many items were listed each day during the range.

## Top 10 Best Sellers

This section is a sorted slice of the Sales list:
- Top 10 by sold_price.
- Displays sold_price, net_profit, marketplace, and sold_at.

## Receipts Summary

Receipts are not part of Sales. They are a parallel system used for expense
tracking and OCR workflows. The analytics page shows:
- Total receipts
- Processed vs pending receipts
- Total amount across processed receipts

These values come from the Receipt table and are filtered by upload date.

## Liberis Loan Metrics (If Active)

If a user has an active Liberis loan configured:
- The analytics page displays the current repayment progress.
- The fee shown is derived from sales in the selected period and the loan’s fee
  percentage.

## Date Range Consistency

All analytics metrics are filtered by the same date range selection:
- Sales, inventory listings, receipts, and expenses are filtered consistently.
- Custom ranges are handled by explicit start and end dates.

## Why This Matters

The Analytics dashboard is a thin aggregation layer over persisted data:
- It is reliable because it uses saved records, not ad-hoc calculations.
- Each metric can be traced directly to a model field.
- Marketplace imports are the source of truth for sales-driven metrics.

If you need deeper validation, the next step is to inspect the sales import
pipeline and confirm the mapping between marketplace payloads and Sale fields.
