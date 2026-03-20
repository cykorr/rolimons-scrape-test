"""
main.py — Fetch and sort Rolimons item-sales data into a finance-style CSV.

Output format mirrors the Plotly Apple finance CSV:
  Date, Price.Open, Price.High, Price.Low, Price.Close, Price.Volume,
  Price.Adjusted, dn, mavg, up, direction

Column mapping from Rolimons data
----------------------------------
  Date          → calendar date (UTC) derived from each sale's Unix timestamp
  Price.Open    → first sale price of the day
  Price.High    → highest sale price of the day
  Price.Low     → lowest sale price of the day
  Price.Close   → last sale price of the day
  Price.Volume  → number of sales recorded that day
  Price.Adjusted→ RAP (Recent Average Price) at the end of the day
  dn            → 20-day lower Bollinger Band  (mavg − 2 × σ)
  mavg          → 20-day simple moving average of daily closing prices
  up            → 20-day upper Bollinger Band  (mavg + 2 × σ)
  direction     → "Increasing" if Close ≥ previous-day Close, else "Decreasing"

Usage
-----
  python main.py                   # fetches live, outputs sales_data.csv
  python main.py --output out.csv  # custom output path
"""

import csv
import json
import re
import sys
import statistics
from collections import defaultdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ITEM_SALES_URL = "https://www.rolimons.com/itemsales/16477149823"
FALLBACK_HTML  = "korroutput.html"
OUTPUT_CSV     = "sales_data.csv"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_BOLLINGER_WINDOW = 20

# ---------------------------------------------------------------------------
# Step 1 – Fetch page HTML
# ---------------------------------------------------------------------------

def fetch_html(url: str) -> str:
    """
    Attempt to GET the Rolimons item-sales page.
    On any network error fall back to the local korroutput.html snapshot.
    """
    request = requests.get(url, headers=_HEADERS, timeout=20)

    if request.ok:
        print(f"[fetch] Live page fetched  ({len(request.content):,} bytes)")
        return request.text

    print(f"[fetch] HTTP {request.status_code} – falling back to {FALLBACK_HTML}")
    try:
        return _load_fallback()
    except FileNotFoundError:
        raise RuntimeError(
            f"HTTP {request.status_code} from server and fallback file "
            f"'{FALLBACK_HTML}' not found. Cannot continue."
        )


def _load_fallback() -> str:
    """
    Load the saved Qt-Rich-Text HTML snapshot (korroutput.html).
    The inner Rolimons page is stored as plain text inside <p> elements.
    """
    with open(FALLBACK_HTML, "r", encoding="utf-8") as fh:
        raw = fh.read()
    qt_soup   = BeautifulSoup(raw, "html.parser")
    inner_html = "\n".join(p.get_text() for p in qt_soup.find_all("p"))
    return inner_html


# ---------------------------------------------------------------------------
# Step 2 – Parse item_sales JSON from the page script
# ---------------------------------------------------------------------------

def parse_item_sales(html: str) -> dict:
    """Return the `item_sales` JavaScript object embedded in the page."""
    soup    = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script")

    for script in scripts:
        text = script.get_text()
        if "item_sales" in text and "timestamp_list" in text:
            match = re.search(
                r"var\s+item_sales\s*=\s*(\{.*?\});",
                text,
                re.DOTALL,
            )
            if match:
                return json.loads(match.group(1))

    raise ValueError(
        "Could not locate the `item_sales` JavaScript variable in the page. "
        "The page structure may have changed."
    )


# ---------------------------------------------------------------------------
# Step 3 – Aggregate sales by calendar date (OHLCV)
# ---------------------------------------------------------------------------

def aggregate_by_date(item_sales: dict) -> list[dict]:
    """
    Group each sale data point by calendar date and compute:
      Open, High, Low, Close, Volume, Adjusted (last RAP of the day).

    Returns a list of row dicts sorted chronologically.
    """
    timestamps = item_sales.get("timestamp_list",  [])
    prices     = item_sales.get("sale_price_list", [])
    raps       = item_sales.get("sale_rap_list",   [])

    # Group raw data points by date
    daily: dict = defaultdict(lambda: {"prices": [], "raps": []})
    for ts, price, rap in zip(timestamps, prices, raps):
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        daily[date_str]["prices"].append(price)
        daily[date_str]["raps"].append(rap)

    # Build OHLCV rows, sorted oldest → newest
    rows = []
    for date in sorted(daily.keys()):
        d        = daily[date]
        day_px   = d["prices"]
        day_rap  = d["raps"]
        rows.append({
            "Date":           date,
            "Price.Open":     day_px[0],
            "Price.High":     max(day_px),
            "Price.Low":      min(day_px),
            "Price.Close":    day_px[-1],
            "Price.Volume":   len(day_px),
            "Price.Adjusted": day_rap[-1],   # RAP at end of the day
        })

    return rows


# ---------------------------------------------------------------------------
# Step 4 – Add technical indicators (20-day Bollinger Bands + direction)
# ---------------------------------------------------------------------------

def add_indicators(rows: list[dict]) -> list[dict]:
    """
    Append dn, mavg, up (20-day Bollinger Bands) and direction to every row.
    direction is "Increasing" if today's Close ≥ yesterday's Close.
    """
    close_prices = [r["Price.Close"] for r in rows]

    for i, row in enumerate(rows):
        # Sliding window (use available data before the window is full)
        window_slice = close_prices[max(0, i - _BOLLINGER_WINDOW + 1) : i + 1]
        mavg = statistics.mean(window_slice)
        std  = statistics.pstdev(window_slice) if len(window_slice) > 1 else 0.0

        row["dn"]   = round(mavg - 2 * std, 6)
        row["mavg"] = round(mavg, 6)
        row["up"]   = round(mavg + 2 * std, 6)

        # Direction: compare to previous day's close
        if i == 0:
            row["direction"] = "Increasing"
        else:
            row["direction"] = (
                "Increasing" if row["Price.Close"] >= close_prices[i - 1]
                else "Decreasing"
            )

    return rows


# ---------------------------------------------------------------------------
# Step 5 – Write CSV
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "Date",
    "Price.Open",
    "Price.High",
    "Price.Low",
    "Price.Close",
    "Price.Volume",
    "Price.Adjusted",
    "dn",
    "mavg",
    "up",
    "direction",
]


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[output] Wrote {len(rows)} daily rows → {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    output_path = OUTPUT_CSV
    if len(sys.argv) == 3 and sys.argv[1] == "--output":
        output_path = sys.argv[2]

    # 1. Fetch HTML (live or fallback)
    try:
        html = fetch_html(ITEM_SALES_URL)
    except Exception as exc:
        print(f"[fetch] Network error ({exc}) – falling back to {FALLBACK_HTML}")
        html = _load_fallback()

    # 2. Parse the embedded item_sales JS object
    item_sales = parse_item_sales(html)
    print(f"[parse] Found {item_sales.get('num_points', '?')} historical sale data points")

    # 3. Aggregate by date (OHLCV)
    rows = aggregate_by_date(item_sales)
    print(f"[sort]  Aggregated into {len(rows)} trading days  "
          f"({rows[0]['Date']} → {rows[-1]['Date']})")

    # 4. Add indicators
    rows = add_indicators(rows)

    # 5. Write CSV
    write_csv(rows, output_path)

    # Quick preview
    print("\n--- First 5 rows ---")
    header = ",".join(_CSV_FIELDS)
    print(header)
    for row in rows[:5]:
        print(",".join(str(row[f]) for f in _CSV_FIELDS))

    print("\n--- Last 5 rows ---")
    print(header)
    for row in rows[-5:]:
        print(",".join(str(row[f]) for f in _CSV_FIELDS))


if __name__ == "__main__":
    main()
