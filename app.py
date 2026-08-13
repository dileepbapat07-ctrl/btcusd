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

COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/{product_id}/candles"
COINBASE_PRODUCTS = {"BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD"}
COINBASE_MAX_CANDLES_PER_CALL = 300  # Coinbase's hard cap per request
GRANULARITY_SECONDS = 3600  # 1 hour

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
    """
    Pull hourly OHLC from Coinbase Exchange's public candles endpoint.
    No key required, not geo-blocked, and unlike Kraken's OHLC endpoint
    (hard-capped at the most recent 720 candles / ~30 days regardless of
    what you ask for), Coinbase supports real pagination arbitrarily far
    back in time via start/end params. Max 300 candles per call, so we
    page through in ~12.5-day chunks.
    """
    product_id = COINBASE_PRODUCTS.get(symbol, "BTC-USD")
    url = COINBASE_CANDLES_URL.format(product_id=product_id)

    start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)

    chunk_span = timedelta(seconds=GRANULARITY_SECONDS * COINBASE_MAX_CANDLES_PER_CALL)

    all_rows = []
    chunk_start = start_dt
    while chunk_start < end_dt:
        chunk_end = min(chunk_start + chunk_span, end_dt)
        params = {
            "start": chunk_start.isoformat(),
            "end": chunk_end.isoformat(),
            "granularity": GRANULARITY_SECONDS,
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            time.sleep(1.0)
            resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        rows = resp.json()  # each row: [time, low, high, open, close, volume]
        if isinstance(rows, dict):
            raise RuntimeError(rows.get("message", "Coinbase API error"))
        all_rows.extend(rows)

        chunk_start = chunk_end
        time.sleep(0.35)  # Coinbase public rate limit is ~3 req/sec

    if not all_rows:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_rows, columns=["time", "low", "high", "open", "close", "volume"])
    df = df.drop_duplicates(subset="time").sort_values("time")
    df["open_time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["open_time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def build_view(df: pd.DataFrame, tz_name: str) -> pd.DataFrame:
    out = df.copy()
    out["range"] = out["high"] - out["low"]
    out["local_time"] = out["open_time"].dt.tz_convert(ZoneInfo(tz_name))
    out["hour"] = out["local_time"].dt.hour
    out["dow"] = out["local_time"].dt.day_name()
    return out


st.title("₿ BTC Hourly Range Explorer")
st.caption(
    "Live hourly candles from Coinbase (BTC/USD spot). Pick a window and "
    "timezone to see which hours of the day tend to move the most / least."
)

with st.sidebar:
    st.header("Settings")
    lookback_mode = st.radio("Time window", ["Quick preset", "Custom date range"], index=0)

    if lookback_mode == "Quick preset":
        preset = st.select_slider(
            "Lookback",
            options=["1 week", "2 weeks", "1 month", "3 months", "6 months", "1 year"],
            value="6 months",
        )
        preset_days = {
            "1 week": 7, "2 weeks": 14, "1 month": 30,
            "3 months": 90, "6 months": 180, "1 year": 365,
        }
        lookback_days = preset_days[preset]
        custom_start = None
        custom_end = None
    else:
        today = datetime.now(timezone.utc).date()
        default_start = today - timedelta(days=180)
        date_range = st.date_input(
            "Select start and end date",
            value=(default_start, today),
            min_value=today - timedelta(days=365 * 3),
            max_value=today,
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            custom_start, custom_end = date_range
        else:
            custom_start, custom_end = default_start, today
        lookback_days = (custom_end - custom_start).days
        if lookback_days < 1:
            st.warning("End date must be after start date. Using last 7 days instead.")
            custom_start, custom_end = today - timedelta(days=7), today
            lookback_days = 7
    tz_label = st.selectbox("Display timezone", list(TIMEZONES.keys()), index=1)
    tz_name = TIMEZONES[tz_label]
    symbol_label = st.selectbox("Symbol", ["BTC/USD", "ETH/USD"], index=0)
    symbol = "BTCUSDT" if symbol_label == "BTC/USD" else "ETHUSDT"
    st.caption(
        "Data source: Coinbase Exchange public API "
        "(`/products/{id}/candles`), no key required."
    )

if lookback_mode == "Custom date range" and custom_start is not None:
    start_dt = datetime.combine(custom_start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(custom_end, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
    end_dt = min(end_dt, datetime.now(timezone.utc))
else:
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days)
start_ms = int(start_dt.timestamp() * 1000)
end_ms = int(end_dt.timestamp() * 1000)

with st.spinner(f"Fetching {lookback_days} days of hourly {symbol} candles..."):
    try:
        raw = fetch_klines(symbol, "1h", start_ms, end_ms)
    except Exception as e:
        st.error(f"Couldn't reach the data API: {e}")
        st.stop()

if raw.empty:
    st.warning("No data returned. Try a shorter lookback window.")
    st.stop()

df = build_view(raw, tz_name)

st.success(
    f"Loaded {len(df):,} hourly candles "
    f"({df['open_time'].min().date()} to {df['open_time'].max().date()})"
)

# ---- Freshness check ----
latest_utc = raw["open_time"].max()
latest_local = latest_utc.tz_convert(ZoneInfo(tz_name))
now_utc = datetime.now(timezone.utc)
staleness = now_utc - latest_utc.to_pydatetime()
staleness_hours = staleness.total_seconds() / 3600

f1, f2 = st.columns(2)
f1.metric("Most recent candle", latest_local.strftime("%Y-%m-%d %H:%M") + f" ({tz_label.split(' ')[0]})")
if staleness_hours <= 2:
    f2.success(f"Data is current — last candle is ~{staleness_hours:.1f}h old.")
elif staleness_hours <= 6:
    f2.warning(f"Last candle is {staleness_hours:.1f}h old — slightly behind live.")
else:
    f2.error(f"Last candle is {staleness_hours:.1f}h old — data may be stale, try refreshing.")

st.caption(
    "Note: the most recent hour shown may still be **in progress** on the exchange "
    "(its range will grow until the hour closes), so treat the very last row with "
    "that in mind when comparing it to fully-closed hours."
)

st.divider()

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
    df.groupby("hour")
    .agg(
        max_range=("range", "max"),
        mean_range=("range", "mean"),
        median_range=("range", "median"),
        std_range=("range", "std"),
        mean_volume=("volume", "mean"),
        count=("range", "count"),
    )
    .reindex(range(24))
    .reset_index()
)

st.divider()

# ---- Recommended calm trading hours ----
st.subheader(f"🎯 Recommended calm hours to trade ({tz_label})")
st.caption(
    "Ranked from the data you selected above, purely by how calm each hour's "
    "price range historically was. This reflects **what already happened "
    "historically** in this window — it is not a prediction, and it isn't "
    "financial advice. Quiet hours can still spike on news."
)

liquidity_threshold = hourly["mean_volume"].quantile(0.25)
hourly["thin_liquidity"] = hourly["mean_volume"] < liquidity_threshold

# Calmness score: primarily average range, with a penalty for inconsistency
# (a hour that's usually calm but occasionally spikes hard is riskier than
# one that's consistently calm), normalized 0-100 (lower = calmer).
range_norm = (hourly["mean_range"] - hourly["mean_range"].min()) / (
    hourly["mean_range"].max() - hourly["mean_range"].min() + 1e-9
)
std_norm = (hourly["std_range"] - hourly["std_range"].min()) / (
    hourly["std_range"].max() - hourly["std_range"].min() + 1e-9
)
hourly["calm_score"] = (0.7 * range_norm + 0.3 * std_norm) * 100

ranked = hourly.sort_values("calm_score").reset_index(drop=True)
top_calm = ranked.head(5)

display_cols = pd.DataFrame({
    "Hour": top_calm["hour"].apply(lambda h: f"{int(h):02d}:00"),
    "Avg range": top_calm["mean_range"].apply(lambda v: f"${v:,.0f}"),
    "Max range seen": top_calm["max_range"].apply(lambda v: f"${v:,.0f}"),
    "Consistency (std dev)": top_calm["std_range"].apply(lambda v: f"±${v:,.0f}"),
    "Avg volume": top_calm["mean_volume"].apply(lambda v: f"{v:,.1f}"),
    "Sample size": top_calm["count"].apply(lambda v: f"{int(v)} candles"),
})
st.table(display_cols)

low_vol_in_top = top_calm[top_calm["thin_liquidity"]]
if not low_vol_in_top.empty:
    low_vol_list = ", ".join(f"{int(h):02d}:00" for h in low_vol_in_top["hour"])
    st.caption(
        f"ℹ️ Note: {low_vol_list} also had below-average volume in this window "
        f"(bottom 25% of the day) — range was still genuinely low, but thinner "
        f"volume can sometimes mean wider spreads. Included here since you "
        f"asked not to filter on this."
    )

worst = ranked.tail(3).sort_values("calm_score", ascending=False)
worst_list = ", ".join(f"{int(h):02d}:00" for h in worst["hour"])
st.error(f"🔥 Historically most volatile hours in this window — avoid if you want calm conditions: **{worst_list}**")

st.divider()

# ---- Per-hour-of-day summary ----
st.subheader(f"Range by hour of day ({tz_label})")

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
    color="thin_liquidity",
    color_discrete_map={True: "#d3a625", False: "#1f77b4"},
    labels={
        "hour": f"Hour of day ({tz_label})",
        "mean_range": "Average range (USD)",
        "thin_liquidity": "Low volume (bottom 25%)",
    },
    title="Average hourly range, by hour of day (typical movement)",
)
fig_mean.update_layout(xaxis=dict(tickmode="linear", dtick=1))
st.plotly_chart(fig_mean, use_container_width=True)

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
    "Data refreshes from Coinbase every time you change a setting (cached for 30 min). "
    "This is Coinbase's own spot market data — actual ranges can differ slightly "
    "from other exchanges like Binance or Kraken."
)
