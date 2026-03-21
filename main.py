"""
main.py — Fetch, process, and chart Rolimons item-sales data.

Fetches data from the Rolimons item-sales page, aggregates it into a
finance-style OHLCV CSV, computes 20-day Bollinger Band indicators, and
renders interactive Plotly OHLC charts — all in a single run.

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
  python main.py                   # fetches live, outputs sales_data.csv + charts
  python main.py --output out.csv  # custom CSV output path
  python main.py --no-charts       # skip chart generation

Chart outputs
-------------
  chart_ohlc_basic.html       – basic OHLC chart
  chart_ohlc_full.html        – OHLC + Bollinger Bands with data and chart-type menus
  chart_candlestick_basic.html– basic Candlestick chart
"""

import csv
import json
import re
import sys
import statistics
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ITEM_SALES_URL = "https://www.rolimons.com/itemsales/16477149823"
FALLBACK_HTML  = "korroutput.html"
OUTPUT_CSV     = "sales_data.csv"
OUTPUT_BASIC        = "chart_ohlc_basic.html"
OUTPUT_FULL         = "chart_ohlc_full.html"
OUTPUT_CANDLESTICK  = "chart_candlestick_basic.html"

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
        return load_fallback()
    except FileNotFoundError:
        raise RuntimeError(
            f"HTTP {request.status_code} from server and fallback file "
            f"'{FALLBACK_HTML}' not found. Cannot continue."
        )


def load_fallback() -> str:
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
# Step 6 – Convert rows to a DataFrame for charting
# ---------------------------------------------------------------------------

def rows_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    """
    Convert the processed list of row dicts to a pandas DataFrame,
    renaming Price.* columns to the short aliases used by the chart functions.
    """
    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "Price.Open":     "Open",
        "Price.High":     "High",
        "Price.Low":      "Low",
        "Price.Close":    "Close",
        "Price.Volume":   "Volume",
        "Price.Adjusted": "Adjusted",
    })
    return df


# ---------------------------------------------------------------------------
# Step 7 – Chart 1: Basic OHLC
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
# Step 8 – Chart 2: Basic Candlestick
# ---------------------------------------------------------------------------

def make_candlestick(df: pd.DataFrame, title: str = "Candlestick Chart") -> go.Figure:
    """
    Basic Candlestick chart using go.Candlestick with Date on the x-axis
    and OHLC sale prices on the y-axis.
    """
    fig = go.Figure(
        data=go.Candlestick(
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
# Step 9 – Chart 3: Full OHLC with Bollinger Bands, range selector,
#           chart-type menu, and data menu
# ---------------------------------------------------------------------------

def make_full_ohlc(df: pd.DataFrame, title: str = "OHLC Chart with Bollinger Bands") -> go.Figure:
    """
    Advanced interactive chart with:
      • OHLC bars or Candlestick (switchable via "Chart Type" dropdown)
      • Upper / lower Bollinger Bands and 20-day moving average
      • RAP (Adjusted) line and Volume bar series (switchable via "Data" dropdown)
      • Interactive range selector and range slider

    Trace index map
    ---------------
      0  OHLC bars          (price, visible by default)
      1  Candlestick        (price, hidden by default)
      2  Upper Bollinger    (price overlay, visible by default)
      3  20-Day MA          (price overlay, visible by default)
      4  Lower Bollinger    (price overlay, visible by default)
      5  RAP line           (hidden by default)
      6  Volume bar         (hidden by default)
    """
    fig = go.Figure()

    # --- Trace 0: OHLC bars (default price view) ---
    fig.add_trace(go.Ohlc(
        name="Price (OHLC)",
        x=df["Date"],
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        increasing_line_color="green",
        decreasing_line_color="red",
        visible=True,
    ))

    # --- Trace 1: Candlestick (hidden; shown via Chart Type menu) ---
    fig.add_trace(go.Candlestick(
        name="Price (Candlestick)",
        x=df["Date"],
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        increasing_line_color="green",
        decreasing_line_color="red",
        visible=False,
    ))

    # --- Trace 2: Upper Bollinger Band ---
    fig.add_trace(go.Scatter(
        name="Upper Band",
        x=df["Date"],
        y=df["up"],
        line={"color": "rgba(0, 0, 200, 0.5)", "width": 1, "dash": "dash"},
        mode="lines",
        visible=True,
    ))

    # --- Trace 3: 20-day moving average ---
    fig.add_trace(go.Scatter(
        name="20-Day MA",
        x=df["Date"],
        y=df["mavg"],
        line={"color": "rgba(200, 100, 0, 0.8)", "width": 1},
        mode="lines",
        visible=True,
    ))

    # --- Trace 4: Lower Bollinger Band ---
    fig.add_trace(go.Scatter(
        name="Lower Band",
        x=df["Date"],
        y=df["dn"],
        line={"color": "rgba(0, 0, 200, 0.5)", "width": 1, "dash": "dash"},
        fill="tonexty",
        fillcolor="rgba(0, 0, 200, 0.05)",
        mode="lines",
        visible=True,
    ))

    # --- Trace 5: RAP / Adjusted price line (hidden by default) ---
    fig.add_trace(go.Scatter(
        name="RAP",
        x=df["Date"],
        y=df["Adjusted"],
        line={"color": "rgba(150, 0, 200, 0.8)", "width": 2},
        mode="lines",
        visible=False,
    ))

    # --- Trace 6: Volume bar chart (hidden by default) ---
    fig.add_trace(go.Bar(
        name="Volume",
        x=df["Date"],
        y=df["Volume"],
        marker_color="rgba(0, 150, 100, 0.6)",
        visible=False,
    ))

    # Visibility patterns used by the menus
    _price_ohlc  = [True,  False, True,  True,  True,  False, False]
    _price_cs    = [False, True,  True,  True,  True,  False, False]
    _rap         = [False, False, False, False, False, True,  False]
    _volume      = [False, False, False, False, False, False, True]

    # Layout constants for menu/legend positioning
    _legend_y    = 1.02   # horizontal legend just above the plot area
    _top_margin  = 120    # extra top margin (px) to fit menus + title
    _menu_y      = 1.15   # y-position of the dropdown menus (paper coords)
    _menu_x_type = 0.0    # x-position of the Chart Type menu
    _menu_x_data = 0.22   # x-position of the Data menu (offset right)
    _annot_y     = 1.22   # y-position of the menu label annotations

    # --- Layout with range selector and two dropdown menus ---
    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Price (Robux)",
        legend={"orientation": "h", "x": 0, "y": _legend_y},
        margin={"t": _top_margin},
        xaxis=dict(
            rangeslider={"visible": True},
            rangeselector=dict(
                buttons=[
                    {"count": 7,  "label": "1w", "step": "day",   "stepmode": "backward"},
                    {"count": 1,  "label": "1m", "step": "month", "stepmode": "backward"},
                    {"count": 3,  "label": "3m", "step": "month", "stepmode": "backward"},
                    {"count": 6,  "label": "6m", "step": "month", "stepmode": "backward"},
                    {"step": "all", "label": "All"},
                ]
            ),
        ),
        updatemenus=[
            # ── Menu 1: Chart Type (OHLC vs Candlestick) ──────────────────
            dict(
                type="dropdown",
                direction="down",
                showactive=True,
                x=_menu_x_type,
                xanchor="left",
                y=_menu_y,
                yanchor="top",
                pad={"r": 10, "t": 5},
                buttons=[
                    dict(
                        label="OHLC",
                        method="update",
                        args=[
                            {"visible": _price_ohlc},
                            {"yaxis.title.text": "Price (Robux)"},
                        ],
                    ),
                    dict(
                        label="Candlestick",
                        method="update",
                        args=[
                            {"visible": _price_cs},
                            {"yaxis.title.text": "Price (Robux)"},
                        ],
                    ),
                ],
            ),
            # ── Menu 2: Data series ────────────────────────────────────────
            dict(
                type="dropdown",
                direction="down",
                showactive=True,
                x=_menu_x_data,
                xanchor="left",
                y=_menu_y,
                yanchor="top",
                pad={"r": 10, "t": 5},
                buttons=[
                    dict(
                        label="Sale Price",
                        method="update",
                        args=[
                            {"visible": _price_ohlc},
                            {"yaxis.title.text": "Price (Robux)"},
                        ],
                    ),
                    dict(
                        label="RAP",
                        method="update",
                        args=[
                            {"visible": _rap},
                            {"yaxis.title.text": "RAP (Robux)"},
                        ],
                    ),
                    dict(
                        label="Volume",
                        method="update",
                        args=[
                            {"visible": _volume},
                            {"yaxis.title.text": "Volume (Sales)"},
                        ],
                    ),
                ],
            ),
        ],
        annotations=[
            dict(
                text="Chart Type:",
                showarrow=False,
                x=_menu_x_type,
                xref="paper",
                y=_annot_y,
                yref="paper",
                align="left",
            ),
            dict(
                text="Data:",
                showarrow=False,
                x=_menu_x_data,
                xref="paper",
                y=_annot_y,
                yref="paper",
                align="left",
            ),
        ],
    )

    return fig


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    output_path = OUTPUT_CSV
    generate_charts = "--no-charts" not in sys.argv

    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--output" and i + 1 < len(args):
            output_path = args[i + 1]

    # 1. Fetch HTML (live or fallback)
    try:
        html = fetch_html(ITEM_SALES_URL)
    except Exception as exc:
        print(f"[fetch] Network error ({exc}) – falling back to {FALLBACK_HTML}")
        html = load_fallback()

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

    # 6. Generate charts directly from in-memory data
    if generate_charts:
        df = rows_to_dataframe(rows)
        item_label = "Rolimons Item Sales"

        fig_basic = make_basic_ohlc(df, title=f"{item_label} — OHLC Chart")
        fig_basic.write_html(OUTPUT_BASIC)
        print(f"\n[chart] Basic OHLC chart saved        → {OUTPUT_BASIC}")

        fig_cs = make_candlestick(df, title=f"{item_label} — Candlestick Chart")
        fig_cs.write_html(OUTPUT_CANDLESTICK)
        print(f"[chart] Basic Candlestick chart saved  → {OUTPUT_CANDLESTICK}")

        fig_full = make_full_ohlc(df, title=f"{item_label} — OHLC + Bollinger Bands")
        fig_full.write_html(OUTPUT_FULL)
        print(f"[chart] Full OHLC chart saved          → {OUTPUT_FULL}")


if __name__ == "__main__":
    main()
