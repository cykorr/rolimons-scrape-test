"""
chart.py — Generate Plotly OHLC charts from Rolimons sales data.

Chart generation functions and the Rolimons data pipeline now live in
main.py.  This module re-exports those functions for backward compatibility
and provides its own entry point that fetches live data through main.py's
pipeline rather than reading a pre-existing CSV.

Usage
-----
  # Fetch live data and generate both charts (same as running main.py):
  python chart.py

  # Use the Plotly Apple finance demo CSV instead of live data:
  python chart.py --demo
"""

import sys
import pandas as pd

from main import (
    fetch_html,
    load_fallback,
    parse_item_sales,
    aggregate_by_date,
    add_indicators,
    rows_to_dataframe,
    make_basic_ohlc,
    make_full_ohlc,
    ITEM_SALES_URL,
    FALLBACK_HTML,
    OUTPUT_BASIC,
    OUTPUT_FULL,
)

# ---------------------------------------------------------------------------
# Demo data loader (Plotly Apple finance CSV)
# ---------------------------------------------------------------------------

DEMO_CSV_URL = (
    "https://raw.githubusercontent.com/plotly/datasets/master/"
    "finance-charts-apple.csv"
)


def load_demo() -> pd.DataFrame:
    """Load the Plotly Apple finance demo CSV (internet required)."""
    df = pd.read_csv(DEMO_CSV_URL)
    df = df.rename(columns={
        "AAPL.Open":     "Open",
        "AAPL.High":     "High",
        "AAPL.Low":      "Low",
        "AAPL.Close":    "Close",
        "AAPL.Volume":   "Volume",
        "AAPL.Adjusted": "Adjusted",
    })
    return df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    demo_mode = "--demo" in sys.argv

    if demo_mode:
        print("[data] Loading Plotly Apple finance demo CSV …")
        df = load_demo()
        item_label = "Apple (AAPL)"
    else:
        # Use main.py's pipeline to fetch and process live data
        try:
            html = fetch_html(ITEM_SALES_URL)
        except Exception as exc:
            print(f"[fetch] Network error ({exc}) – falling back to {FALLBACK_HTML}")
            html = load_fallback()

        item_sales = parse_item_sales(html)
        print(f"[parse] Found {item_sales.get('num_points', '?')} historical sale data points")

        rows = aggregate_by_date(item_sales)
        rows = add_indicators(rows)
        df = rows_to_dataframe(rows)
        item_label = "Rolimons Item Sales"

    print(f"[data] {len(df)} rows loaded  ({df['Date'].iloc[0]} → {df['Date'].iloc[-1]})")

    # Chart 1 – basic OHLC
    fig_basic = make_basic_ohlc(df, title=f"{item_label} — OHLC Chart")
    fig_basic.write_html(OUTPUT_BASIC)
    print(f"[chart] Basic OHLC chart saved → {OUTPUT_BASIC}")

    # Chart 2 – full OHLC with Bollinger Bands
    fig_full = make_full_ohlc(df, title=f"{item_label} — OHLC + Bollinger Bands")
    fig_full.write_html(OUTPUT_FULL)
    print(f"[chart] Full OHLC chart saved  → {OUTPUT_FULL}")


if __name__ == "__main__":
    main()

