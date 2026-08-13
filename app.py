"""
BTC Hourly Range Explorer
--------------------------
Pulls hourly BTCUSDT candles from Binance's public REST API and shows,
per hour-of-day, how big the typical / max candle range is.

Runs on Streamlit Community Cloud (streamlit.app) or locally with:
    pip install -r requirements.txt
    streamlit run app.py
"""

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from zoneinfo import ZoneInfo

st.set_page_config(page_title="BTC Hourly Range Explorer", layout="wide")

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]

TIMEZONES = {
    "UTC": "UTC",
    "Munich / Berlin (CET/CEST)": "Europe/Berlin",
    "New York (ET)": "America/New_York",
    "India (IST)": "Asia/Kolkata",
    "Tokyo (JST)": "Asia/Tokyo",
}

BUCKET_EDGES = [0, 100, 200, 300, 400, 500, float("inf")]
BUCKET_LABELS = ["0-100", "100-200", "200-300", "300-400", "400-500", "500+"]


@st.cache_data(ttl=60 * 30, show_spinner=False)
def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Pull klines from Binance in pages of 1000 (Binance's per-request cap)."""
    all_rows = []
    cursor = start_ms
    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        }
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        all_rows.extend(rows)
        last_open_time = rows[-1][0]
        next_cursor = last_open_time + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(rows) < 1000:
            break
        time.sleep(0.2)  # be polite to the API

    if not all_rows:
        return pd.DataFrame(columns=COLUMNS)

    df = pd.DataFrame(all_rows, columns=COLUMNS)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df


def build_view(df: pd.DataFrame, tz_name: str) -> pd.DataFrame:
    out = df.copy()
    out["range"] = out["high"] - out["low"]
    out["local_time"] = out["open_time"].dt.tz_convert(ZoneInfo(tz_name))
    out["hour"] = out["local_time"].dt.hour
    out["dow"] = out["local_time"].dt.day_name()
    return out


st.title("₿ BTC Hourly Range Explorer")
st.caption(
    "Live hourly candles from Binance (BTCUSDT spot). Pick a window and "
    "timezone to see which hours of the day tend to move the most / least."
)

with st.sidebar:
    st.header("Settings")
    lookback_days = st.slider("Lookback window (days)", 7, 180, 90, step=1)
    tz_label = st.selectbox("Display timezone", list(TIMEZONES.keys()), index=1)
    tz_name = TIMEZONES[tz_label]
    symbol = st.selectbox("Symbol", ["BTCUSDT", "ETHUSDT"], index=0)
    st.caption(
        "Data source: Binance public REST API "
        "(`/api/v3/klines`), no key required."
    )

end_dt = datetime.now(timezone.utc)
start_dt = end_dt - timedelta(days=lookback_days)
start_ms = int(start_dt.timestamp() * 1000)
end_ms = int(end_dt.timestamp() * 1000)

with st.spinner(f"Fetching {lookback_days} days of hourly {symbol} candles..."):
    try:
        raw = fetch_klines(symbol, "1h", start_ms, end_ms)
    except Exception as e:
        st.error(f"Couldn't reach Binance API: {e}")
        st.stop()

if raw.empty:
    st.warning("No data returned. Try a shorter lookback window.")
    st.stop()

df = build_view(raw, tz_name)

st.success(
    f"Loaded {len(df):,} hourly candles "
    f"({df['open_time'].min().date()} to {df['open_time'].max().date()})"
)

# ---- Top line stats ----
overall_max = df.loc[df["range"].idxmax()]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Max single-hour range", f"${overall_max['range']:,.0f}")
c2.metric("Max happened at", overall_max["local_time"].strftime("%Y-%m-%d %H:%M"))
c3.metric("Median hourly range", f"${df['range'].median():,.0f}")
c4.metric("Mean hourly range", f"${df['range'].mean():,.0f}")

st.divider()

# ---- Per-hour-of-day summary ----
st.subheader(f"Range by hour of day ({tz_label})")

hourly = (
    df.groupby("hour")["range"]
    .agg(max_range="max", mean_range="mean", median_range="median", count="count")
    .reindex(range(24))
    .reset_index()
)

fig_max = px.bar(
    hourly,
    x="hour",
    y="max_range",
    labels={"hour": f"Hour of day ({tz_label})", "max_range": "Max range (USD)"},
    title="Maximum hourly range seen, by hour of day",
)
fig_max.update_layout(xaxis=dict(tickmode="linear", dtick=1))
st.plotly_chart(fig_max, use_container_width=True)

fig_mean = px.bar(
    hourly,
    x="hour",
    y="mean_range",
    labels={"hour": f"Hour of day ({tz_label})", "mean_range": "Average range (USD)"},
    title="Average hourly range, by hour of day (typical movement)",
)
fig_mean.update_layout(xaxis=dict(tickmode="linear", dtick=1))
st.plotly_chart(fig_mean, use_container_width=True)

quietest = hourly.loc[hourly["mean_range"].idxmin()]
busiest = hourly.loc[hourly["mean_range"].idxmax()]
q1, q2 = st.columns(2)
q1.info(
    f"**Quietest hour on average:** {int(quietest['hour']):02d}:00 {tz_label} "
    f"— avg range ${quietest['mean_range']:,.0f}"
)
q2.warning(
    f"**Busiest hour on average:** {int(busiest['hour']):02d}:00 {tz_label} "
    f"— avg range ${busiest['mean_range']:,.0f}"
)

st.divider()

# ---- Bucket distribution ----
st.subheader("Range buckets by hour of day")
st.caption("Each hourly candle is bucketed by its high-low range in USD points.")

df["bucket"] = pd.cut(df["range"], bins=BUCKET_EDGES, labels=BUCKET_LABELS, right=False)

bucket_counts = (
    df.groupby(["hour", "bucket"], observed=True)
    .size()
    .reset_index(name="count")
)

fig_bucket = px.bar(
    bucket_counts,
    x="hour",
    y="count",
    color="bucket",
    category_orders={"bucket": BUCKET_LABELS},
    labels={"hour": f"Hour of day ({tz_label})", "count": "Number of candles"},
    title="Distribution of candle-range buckets across the day",
)
fig_bucket.update_layout(xaxis=dict(tickmode="linear", dtick=1))
st.plotly_chart(fig_bucket, use_container_width=True)

st.subheader("Overall bucket breakdown (whole window)")
total_bucket = df["bucket"].value_counts().reindex(BUCKET_LABELS).fillna(0).astype(int)
total_bucket_pct = (total_bucket / total_bucket.sum() * 100).round(1)
summary_df = pd.DataFrame({"candles": total_bucket, "% of hours": total_bucket_pct})
st.dataframe(summary_df, use_container_width=True)

st.divider()

# ---- Raw table + download ----
with st.expander("Raw hourly data (sortable table)"):
    show_cols = ["local_time", "dow", "hour", "open", "high", "low", "close", "range", "bucket"]
    st.dataframe(
        df[show_cols].sort_values("local_time", ascending=False),
        use_container_width=True,
    )

csv = df[show_cols].to_csv(index=False).encode("utf-8")
st.download_button(
    "Download this data as CSV",
    data=csv,
    file_name=f"{symbol}_hourly_range_{lookback_days}d.csv",
    mime="text/csv",
)

st.caption(
    "Data refreshes from Binance every time you change a setting (cached for 30 min). "
    "This is spot market data — actual ranges can differ slightly across exchanges."
)
