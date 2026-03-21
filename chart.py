"""
chart.py — Generate Plotly OHLC charts from Rolimons sales data.

Reads the CSV produced by main.py (sales_data.csv) and renders:
  1. A basic OHLC chart (open / high / low / close per day)
  2. A full chart with 20-day Bollinger Band overlays and a range-selector

Column mapping (mirrors the Plotly Apple finance example):
  Apple CSV column   →  sales_data.csv column
  ─────────────────────────────────────────────
  AAPL.Open          →  Price.Open
  AAPL.High          →  Price.High
  AAPL.Low           →  Price.Low
  AAPL.Close         →  Price.Close
  AAPL.Volume        →  Price.Volume
  AAPL.Adjusted      →  Price.Adjusted
  dn                 →  dn
  mavg               →  mavg
  up                 →  up
  direction          →  direction

Usage
-----
  # Generate both charts after running main.py:
  python chart.py

  # Use a custom CSV:
  python chart.py --input my_data.csv

  # Use the Plotly Apple finance demo CSV instead of local data:
  python chart.py --demo
"""

import sys
import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CSV   = "sales_data.csv"
DEMO_CSV_URL  = (
    "https://raw.githubusercontent.com/plotly/datasets/master/"
    "finance-charts-apple.csv"
)

OUTPUT_BASIC  = "chart_ohlc_basic.html"
OUTPUT_FULL   = "chart_ohlc_full.html"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_local(path: str) -> pd.DataFrame:
    """Load the finance-style CSV produced by main.py."""
    df = pd.read_csv(path)
    # Normalise column names: rename Price.* → AAPL.* style aliases
    # so the rest of the code works with either source.
    df = df.rename(columns={
        "Price.Open":     "Open",
        "Price.High":     "High",
        "Price.Low":      "Low",
        "Price.Close":    "Close",
        "Price.Volume":   "Volume",
        "Price.Adjusted": "Adjusted",
    })
    return df


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
# Chart 1 – Basic OHLC
# ---------------------------------------------------------------------------

def make_basic_ohlc(df: pd.DataFrame, title: str = "OHLC Chart") -> go.Figure:
    """
    Recreate the introductory Plotly OHLC example:
      go.Ohlc with Date on x-axis and OHLC prices on y-axis.
    """
    fig = go.Figure(
        data=go.Ohlc(
            x=df["Date"],
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Price (Robux)",
        xaxis_rangeslider_visible=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 2 – Full OHLC with Bollinger Bands, range selector, direction colour
# ---------------------------------------------------------------------------

def make_full_ohlc(df: pd.DataFrame, title: str = "OHLC Chart with Bollinger Bands") -> go.Figure:
    """
    Advanced chart that mirrors the complete Plotly finance example:
      • OHLC bars colour-coded by direction (Increasing / Decreasing)
      • Upper Bollinger Band (up)
      • 20-day moving average (mavg)
      • Lower Bollinger Band (dn)
      • Interactive range selector and range slider
    """
    fig = go.Figure()

    # --- OHLC bars ---
    fig.add_trace(go.Ohlc(
        name="Price",
        x=df["Date"],
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        increasing_line_color="green",
        decreasing_line_color="red",
    ))

    # --- Upper Bollinger Band ---
    fig.add_trace(go.Scatter(
        name="Upper Band",
        x=df["Date"],
        y=df["up"],
        line={"color": "rgba(0, 0, 200, 0.5)", "width": 1, "dash": "dash"},
        mode="lines",
    ))

    # --- 20-day moving average ---
    fig.add_trace(go.Scatter(
        name="20-Day MA",
        x=df["Date"],
        y=df["mavg"],
        line={"color": "rgba(200, 100, 0, 0.8)", "width": 1},
        mode="lines",
    ))

    # --- Lower Bollinger Band ---
    fig.add_trace(go.Scatter(
        name="Lower Band",
        x=df["Date"],
        y=df["dn"],
        line={"color": "rgba(0, 0, 200, 0.5)", "width": 1, "dash": "dash"},
        fill="tonexty",
        fillcolor="rgba(0, 0, 200, 0.05)",
        mode="lines",
    ))

    # --- Layout with range selector ---
    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Price (Robux)",
        legend={"orientation": "h", "x": 0, "y": 1.1},
        xaxis=dict(
            rangeslider={"visible": True},
            rangeselector=dict(
                buttons=[
                    {"count": 7,  "label": "1w", "step": "day",  "stepmode": "backward"},
                    {"count": 1,  "label": "1m", "step": "month","stepmode": "backward"},
                    {"count": 3,  "label": "3m", "step": "month","stepmode": "backward"},
                    {"count": 6,  "label": "6m", "step": "month","stepmode": "backward"},
                    {"step": "all", "label": "All"},
                ]
            ),
        ),
    )

    return fig


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    demo_mode  = "--demo"   in sys.argv
    input_path = DEFAULT_CSV

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--input" and i + 1 < len(sys.argv):
            input_path = sys.argv[i + 1]

    # Load data
    if demo_mode:
        print("[data] Loading Plotly Apple finance demo CSV …")
        df = load_demo()
        item_label = "Apple (AAPL)"
    else:
        print(f"[data] Loading local CSV: {input_path}")
        df = load_local(input_path)
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
