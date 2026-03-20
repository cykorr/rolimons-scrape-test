"""
parse.py — Parse all data points from korroutput.html into variables.

The file korroutput.html is a Qt Rich Text HTML document that wraps the
scraped output of the Rolimons item-sales page for "Gold Clockwork Headphones"
(item ID 16477149823).  All data that appears on that page is extracted below.

Sections
--------
1.  Item metadata          – name, ID, URL, thumbnail URL
2.  Top stats              – best price, current RAP, current value, sellers
3.  Primary stats          – per-period sale counts, Robux spent, RAP sold,
                             value sold  (day / week / month / all-time)
4.  Historical sales data  – 2,500-point arrays from the in-page JS variable
                             `item_sales`  (timestamps, sale IDs, prices,
                             RAP, value)
5.  Recent sales entries   – 201 individual sale records visible on the page
                             (timestamp, sale ID, sale price, old RAP, new RAP)
"""

import re
import json
from html.parser import HTMLParser
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Load the file and extract the inner Rolimons HTML
# ---------------------------------------------------------------------------

HTML_FILE = "korroutput.html"

with open(HTML_FILE, "r", encoding="utf-8") as fh:
    raw_file = fh.read()

# The outer document is a Qt Rich Text HTML shell; every <p> element holds
# a fragment of the scraped Rolimons page as plain text.
qt_soup = BeautifulSoup(raw_file, "html.parser")
inner_html = "\n".join(p.get_text() for p in qt_soup.find_all("p"))

# Parse the inner HTML as a regular web page.
soup = BeautifulSoup(inner_html, "html.parser")

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _to_int(text: str) -> int:
    """Strip commas and convert a formatted number string to int."""
    return int(text.replace(",", "").strip())


# ===========================================================================
# 1. Item metadata
# ===========================================================================

# Item name from <title>
page_title_tag = soup.find("title")
item_name: str = (
    page_title_tag.get_text().split("|")[0].strip()
    if page_title_tag
    else ""
)

# Item ID and URL from the canonical <link>
canonical_tag = soup.find("link", rel="canonical")
item_url: str = canonical_tag["href"] if canonical_tag else ""
item_id_match = re.search(r"/itemsales/(\d+)", item_url)
item_id: int = int(item_id_match.group(1)) if item_id_match else 0

# Thumbnail URL from Open Graph image meta tag
og_image_tag = soup.find("meta", property="og:image")
item_thumbnail_url: str = og_image_tag["content"] if og_image_tag else ""

# ===========================================================================
# 2. Top stats
# ===========================================================================

top_stat_headers = soup.find_all(class_="top-stat-header")
top_stat_data    = soup.find_all(class_="top-stat-data")

_top_stats: dict = {}
for header_el, data_el in zip(top_stat_headers, top_stat_data):
    key  = header_el.get_text().strip()
    val  = data_el.get_text().strip()
    if key and val:
        _top_stats[key] = val

best_price:    int = _to_int(_top_stats.get("Best Price",    "0"))
current_rap:   int = _to_int(_top_stats.get("Current RAP",   "0"))
current_value: int = _to_int(_top_stats.get("Current Value", "0"))
sellers_count: int = _to_int(_top_stats.get("Sellers",       "0"))

# ===========================================================================
# 3. Primary stats  (day / week / month / all-time)
# ===========================================================================

# Each primary-stat-box contains:
#   • primary-stat-data-large  → sale count for the period
#   • primary-stat-data [0]    → Robux spent
#   • primary-stat-data [1]    → RAP sold
#   • primary-stat-data [2]    → Value sold

primary_stat_boxes = soup.find_all(class_="primary-stat-box")

def _extract_primary_box(box) -> dict:
    count_el = box.find(class_="primary-stat-data-large")
    data_els = box.find_all(class_="primary-stat-data")
    return {
        "sales_count":  _to_int(count_el.get_text()) if count_el else 0,
        "robux_spent":  _to_int(data_els[0].get_text()) if len(data_els) > 0 else 0,
        "rap_sold":     _to_int(data_els[1].get_text()) if len(data_els) > 1 else 0,
        "value_sold":   _to_int(data_els[2].get_text()) if len(data_els) > 2 else 0,
    }

_period_stats: list = [_extract_primary_box(b) for b in primary_stat_boxes]

# Past 24 hours
past_day_sales_count:  int = _period_stats[0]["sales_count"]  if len(_period_stats) > 0 else 0
past_day_robux_spent:  int = _period_stats[0]["robux_spent"]  if len(_period_stats) > 0 else 0
past_day_rap_sold:     int = _period_stats[0]["rap_sold"]     if len(_period_stats) > 0 else 0
past_day_value_sold:   int = _period_stats[0]["value_sold"]   if len(_period_stats) > 0 else 0

# Past 7 days
past_week_sales_count: int = _period_stats[1]["sales_count"]  if len(_period_stats) > 1 else 0
past_week_robux_spent: int = _period_stats[1]["robux_spent"]  if len(_period_stats) > 1 else 0
past_week_rap_sold:    int = _period_stats[1]["rap_sold"]     if len(_period_stats) > 1 else 0
past_week_value_sold:  int = _period_stats[1]["value_sold"]   if len(_period_stats) > 1 else 0

# Past 30 days
past_month_sales_count: int = _period_stats[2]["sales_count"] if len(_period_stats) > 2 else 0
past_month_robux_spent: int = _period_stats[2]["robux_spent"] if len(_period_stats) > 2 else 0
past_month_rap_sold:    int = _period_stats[2]["rap_sold"]    if len(_period_stats) > 2 else 0
past_month_value_sold:  int = _period_stats[2]["value_sold"]  if len(_period_stats) > 2 else 0

# All tracked (since April 19 2021)
all_tracked_sales_count: int = _period_stats[3]["sales_count"] if len(_period_stats) > 3 else 0
all_tracked_robux_spent: int = _period_stats[3]["robux_spent"] if len(_period_stats) > 3 else 0
all_tracked_rap_sold:    int = _period_stats[3]["rap_sold"]    if len(_period_stats) > 3 else 0
all_tracked_value_sold:  int = _period_stats[3]["value_sold"]  if len(_period_stats) > 3 else 0

# ===========================================================================
# 4. Historical sales data  (from the in-page JS variable `item_sales`)
# ===========================================================================

_scripts = soup.find_all("script")
_item_sales_raw: dict = {}
_oldest_sale_ts: int = 0

for script in _scripts:
    sc_text = script.get_text()
    if "item_sales" in sc_text and "timestamp_list" in sc_text:
        # Extract the JSON object assigned to `item_sales`
        js_match = re.search(
            r"var\s+item_sales\s*=\s*(\{.*?\});",
            sc_text,
            re.DOTALL,
        )
        if js_match:
            _item_sales_raw = json.loads(js_match.group(1))

        # Extract oldest_sale_timestamp
        ts_match = re.search(r"var\s+oldest_sale_timestamp\s*=\s*(\d+)", sc_text)
        if ts_match:
            _oldest_sale_ts = int(ts_match.group(1))
        break

# Number of data points in the historical dataset
num_sale_data_points: int = _item_sales_raw.get("num_points", 0)

# Oldest Unix timestamp present in the historical dataset
oldest_sale_timestamp: int = _oldest_sale_ts

# Parallel lists — each index i describes a single historical sale
sale_timestamps: list[int] = _item_sales_raw.get("timestamp_list",  [])
sale_ids:        list[int] = _item_sales_raw.get("sale_id_list",    [])
sale_prices:     list[int] = _item_sales_raw.get("sale_price_list", [])
sale_rap_values: list[int] = _item_sales_raw.get("sale_rap_list",   [])
sale_values:     list[int] = _item_sales_raw.get("sale_value_list", [])

# ===========================================================================
# 5. Recent sales entries  (the 201 individual rows shown on the page)
# ===========================================================================
# Each entry exposes: timestamp, sale_id, sale_price, old_rap, new_rap.

_mix_items = soup.find_all("div", class_="mix_item")

recent_sales: list[dict] = []
for item in _mix_items:
    # Unix timestamp (stored as plain text before JS converts it)
    ts_el    = item.find(class_="activity_entry_timestamp")
    # Link to the sale detail page  →  /itemsale/<sale_id>
    link_el  = item.find(class_="sale_details_link_button")
    # Sale Price, Old RAP, New RAP come from activity_stat_header / _data pairs
    stat_headers = item.find_all(class_="activity_stat_header")
    stat_data    = item.find_all(class_="activity_stat_data")

    _stats: dict = {}
    for h, d in zip(stat_headers, stat_data):
        _stats[h.get_text().strip()] = d.get_text().strip()

    sale_price_text = _stats.get("Sale Price", "0")
    # Sale Price may include an SVG icon; grab only the numeric part
    sale_price_num_match = re.search(r"[\d,]+", sale_price_text)

    entry = {
        "timestamp": int(ts_el.get_text().strip()) if ts_el else 0,
        "sale_id":   int(link_el["href"].replace("/itemsale/", "")) if link_el else 0,
        "sale_price": _to_int(sale_price_num_match.group(0)) if sale_price_num_match else 0,
        "old_rap":    _to_int(_stats.get("Old RAP", "0")),
        "new_rap":    _to_int(_stats.get("New RAP", "0")),
    }
    recent_sales.append(entry)

# ===========================================================================
# Quick summary printout (run  `python parse.py`  to verify all variables)
# ===========================================================================

if __name__ == "__main__":
    print("=== Item Metadata ===")
    print(f"  item_name          : {item_name}")
    print(f"  item_id            : {item_id}")
    print(f"  item_url           : {item_url}")
    print(f"  item_thumbnail_url : {item_thumbnail_url}")

    print("\n=== Top Stats ===")
    print(f"  best_price         : {best_price:,}")
    print(f"  current_rap        : {current_rap:,}")
    print(f"  current_value      : {current_value:,}")
    print(f"  sellers_count      : {sellers_count:,}")

    print("\n=== Primary Stats ===")
    print(f"  Past Day   – sales: {past_day_sales_count:,}  | robux: {past_day_robux_spent:,}"
          f"  | RAP: {past_day_rap_sold:,}  | value: {past_day_value_sold:,}")
    print(f"  Past Week  – sales: {past_week_sales_count:,}  | robux: {past_week_robux_spent:,}"
          f"  | RAP: {past_week_rap_sold:,}  | value: {past_week_value_sold:,}")
    print(f"  Past Month – sales: {past_month_sales_count:,}  | robux: {past_month_robux_spent:,}"
          f"  | RAP: {past_month_rap_sold:,}  | value: {past_month_value_sold:,}")
    print(f"  All Time   – sales: {all_tracked_sales_count:,}  | robux: {all_tracked_robux_spent:,}"
          f"  | RAP: {all_tracked_rap_sold:,}  | value: {all_tracked_value_sold:,}")

    print("\n=== Historical Sales Data ===")
    print(f"  num_sale_data_points   : {num_sale_data_points:,}")
    print(f"  oldest_sale_timestamp  : {oldest_sale_timestamp}")
    print(f"  sale_timestamps        : {len(sale_timestamps)} entries  (first: {sale_timestamps[0] if sale_timestamps else 'N/A'})")
    print(f"  sale_ids               : {len(sale_ids)} entries       (first: {sale_ids[0] if sale_ids else 'N/A'})")
    print(f"  sale_prices            : {len(sale_prices)} entries    (first: {sale_prices[0] if sale_prices else 'N/A'})")
    print(f"  sale_rap_values        : {len(sale_rap_values)} entries (first: {sale_rap_values[0] if sale_rap_values else 'N/A'})")
    print(f"  sale_values            : {len(sale_values)} entries    (first: {sale_values[0] if sale_values else 'N/A'})")

    print(f"\n=== Recent Sales Entries ===")
    print(f"  Total entries          : {len(recent_sales)}")
    if recent_sales:
        s = recent_sales[0]
        print(f"  First entry            : timestamp={s['timestamp']}  sale_id={s['sale_id']}"
              f"  price={s['sale_price']:,}  old_rap={s['old_rap']:,}  new_rap={s['new_rap']:,}")
        s = recent_sales[-1]
        print(f"  Last entry             : timestamp={s['timestamp']}  sale_id={s['sale_id']}"
              f"  price={s['sale_price']:,}  old_rap={s['old_rap']:,}  new_rap={s['new_rap']:,}")
