"""
Crypto Hourly Range Explorer
-----------------------------
Pulls hourly OHLC candles (BTC, ETH, and easy to extend to more) from
Coinbase's public REST API and shows, per hour-of-day, how big the
typical / max candle range is, plus which hours are historically calmest.

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

st.set_page_config(page_title="Crypto Hourly Range Explorer", layout="wide")

# ---- Coin registry: add more coins here as needed ----
COINS = {
    "BTC/USD": {"coinbase_id": "BTC-USD", "short": "BTC", "emoji": "₿"},
    "ETH/USD": {"coinbase_id": "ETH-USD", "short": "ETH", "emoji": "Ξ"},
}
DEFAULT_COIN = "BTC/USD"

COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/{product_id}/candles"
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
REC_BUCKET_EDGES = [0, 200, 400, 600, float("inf")]
REC_BUCKET_LABELS = ["<200", "200-400", "400-600", "600+"]


@st.cache_data(ttl=60 * 30, show_spinner=False)
def fetch_klines(product_id: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """
    Pull hourly OHLC from Coinbase Exchange's public candles endpoint.
    No key required, not geo-blocked, and unlike Kraken's OHLC endpoint
    (hard-capped at the most recent 720 candles / ~30 days regardless of
    what you ask for), Coinbase supports real pagination arbitrarily far
    back in time via start/end params. Max 300 candles per call, so we
    page through in ~12.5-day chunks.
    """
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
    out["range_pct"] = (out["range"] / out["close"]) * 100
    out["local_time"] = out["open_time"].dt.tz_convert(ZoneInfo(tz_name))
    out["hour"] = out["local_time"].dt.hour
    out["dow"] = out["local_time"].dt.day_name()
    return out


st.title("🪙 Crypto Hourly Range Explorer")
st.caption(
    "Live hourly candles from Coinbase. Pick a coin, a window, and a "
    "timezone to see which hours of the day tend to move the most / least."
)

with st.sidebar:
    st.header("Settings")
    coin_label = st.selectbox("Coin", list(COINS.keys()), index=list(COINS.keys()).index(DEFAULT_COIN))
    coin = COINS[coin_label]
    product_id = coin["coinbase_id"]

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
    range_mode = st.radio(
        "Range measured as",
        ["% of price", "Absolute price ($)"],
        index=0,
        help=(
            "% of price is comparable across coins at different price levels "
            "(e.g. ETH's $13 range isn't the same 'size' of move as BTC's $13 "
            "range). Absolute $ is easier to read if you only ever look at one coin."
        ),
    )
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

st.header(f"{coin['emoji']} {coin['short']}/USD")

with st.spinner(f"Fetching {lookback_days} days of hourly {coin['short']} candles..."):
    try:
        raw = fetch_klines(product_id, start_ms, end_ms)
    except Exception as e:
        st.error(f"Couldn't reach the data API: {e}")
        st.stop()

if raw.empty:
    st.warning("No data returned. Try a shorter lookback window.")
    st.stop()

df = build_view(raw, tz_name)

# ---- Active range-display mode: % of price (default) or absolute $ ----
PCT_BUCKET_EDGES = [0, 0.1, 0.2, 0.3, 0.4, 0.5, float("inf")]
PCT_BUCKET_LABELS = ["0-0.1%", "0.1-0.2%", "0.2-0.3%", "0.3-0.4%", "0.4-0.5%", "0.5%+"]
PCT_REC_EDGES = [0, 0.2, 0.4, 0.6, float("inf")]
PCT_REC_LABELS = ["<0.2%", "0.2-0.4%", "0.4-0.6%", "0.6%+"]

if range_mode == "% of price":
    df["display_range"] = df["range_pct"]
    unit = "%"
    ACTIVE_BUCKET_EDGES, ACTIVE_BUCKET_LABELS = PCT_BUCKET_EDGES, PCT_BUCKET_LABELS
    ACTIVE_REC_EDGES, ACTIVE_REC_LABELS = PCT_REC_EDGES, PCT_REC_LABELS

    def fmt(v):
        return f"{v:.3f}%"
else:
    df["display_range"] = df["range"]
    unit = "$"
    ACTIVE_BUCKET_EDGES, ACTIVE_BUCKET_LABELS = BUCKET_EDGES, BUCKET_LABELS
    ACTIVE_REC_EDGES, ACTIVE_REC_LABELS = REC_BUCKET_EDGES, REC_BUCKET_LABELS

    def fmt(v):
        return f"${v:,.0f}"


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
overall_max = df.loc[df["display_range"].idxmax()]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Max single-hour range", fmt(overall_max["display_range"]))
c2.metric("Max happened at", overall_max["local_time"].strftime("%Y-%m-%d %H:%M"))
c3.metric("Median hourly range", fmt(df["display_range"].median()))
c4.metric("Mean hourly range", fmt(df["display_range"].mean()))

st.divider()

# ---- Per-hour-of-day summary ----
hourly = (
    df.groupby("hour")
    .agg(
        max_range=("display_range", "max"),
        mean_range=("display_range", "mean"),
        median_range=("display_range", "median"),
        std_range=("display_range", "std"),
        mean_volume=("volume", "mean"),
        count=("display_range", "count"),
    )
    .reindex(range(24))
    .reset_index()
)

st.divider()

# ---- Recommended calm trading hours ----
st.subheader(f"🎯 Recommended calm hours to trade ({tz_label})")
st.caption(
    f"Ranked from the data you selected above (range shown as **{unit}**), "
    "purely by how calm each hour's price range historically was. This "
    "reflects **what already happened historically** in this window — it "
    "is not a prediction, and it isn't financial advice. Quiet hours can "
    "still spike on news."
)

df["rec_bucket"] = pd.cut(df["display_range"], bins=ACTIVE_REC_EDGES, labels=ACTIVE_REC_LABELS, right=False)
df["bucket"] = pd.cut(df["display_range"], bins=ACTIVE_BUCKET_EDGES, labels=ACTIVE_BUCKET_LABELS, right=False)

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

# Per-hour count of candles in each range bucket (e.g. "<0.2%: 42, 0.2-0.4%: 15, ...")
bucket_pivot = (
    df.groupby(["hour", "rec_bucket"], observed=True)
    .size()
    .unstack(fill_value=0)
    .reindex(columns=ACTIVE_REC_LABELS, fill_value=0)
    .reindex(index=range(24), fill_value=0)
)

display_cols = pd.DataFrame({
    "Hour": top_calm["hour"].apply(lambda h: f"{int(h):02d}:00"),
    "Avg range": top_calm["mean_range"].apply(fmt),
    "Max range seen": top_calm["max_range"].apply(fmt),
    "Consistency (std dev)": top_calm["std_range"].apply(lambda v: f"±{fmt(v)}"),
})
for label in ACTIVE_REC_LABELS:
    display_cols[label] = top_calm["hour"].apply(lambda h: int(bucket_pivot.loc[h, label]))
display_cols["Avg volume"] = top_calm["mean_volume"].apply(lambda v: f"{v:,.1f}").values

st.table(display_cols.set_index("Hour"))
bucket_col_str = " / ".join(f"`{l}`" for l in ACTIVE_REC_LABELS)
st.caption(
    f"The {bucket_col_str} columns show how many candles in that hour fell "
    f"into each range bucket — e.g. if the lowest bucket is high and the "
    f"highest is 0, the hour was consistently calm, not just calm on average."
)

low_vol_in_top = top_calm[top_calm["thin_liquidity"]]
if not low_vol_in_top.empty:
    low_vol_list = ", ".join(f"{int(h):02d}:00" for h in low_vol_in_top["hour"])
    st.caption(
        f"ℹ️ Note: {low_vol_list} also had below-average volume in this window "
        f"(bottom 25% of the day) — range was still genuinely low, but thinner "
        f"volume can sometimes mean wider spreads. Included here since you "
        f"asked not to filter on this."
    )

st.markdown("#### All 24 hours, ranked calm → busy")
st.caption(
    "Green = calmest, red = busiest. This is the whole day at a glance, "
    "not just the top 5 — useful for picking a backup hour or seeing how "
    "big the gap is between your #1 and #2 choice."
)
sorted_by_calm = hourly.sort_values("calm_score", ascending=True)
range_axis_label = f"Average range ({'%' if unit == '%' else 'USD'})"
fig_ranked = px.bar(
    sorted_by_calm,
    x="mean_range",
    y=sorted_by_calm["hour"].apply(lambda h: f"{int(h):02d}:00"),
    orientation="h",
    color="calm_score",
    color_continuous_scale=["#2ca02c", "#f0e442", "#d62728"],
    labels={"mean_range": range_axis_label, "y": "Hour", "calm_score": "Calm score"},
)
fig_ranked.update_layout(yaxis=dict(autorange="reversed"), coloraxis_showscale=False, height=600)
if unit == "%":
    fig_ranked.update_layout(xaxis=dict(ticksuffix="%"))
st.plotly_chart(fig_ranked, use_container_width=True)

st.markdown("#### Full distribution per hour (not just the average)")
st.caption(
    "Box plots show the spread of outcomes for each hour — the box is where "
    "most candles fall, the line inside is the median, and dots above are "
    "outlier spikes. A tight, low box means an hour is reliably calm; a low "
    "box with lots of high dots means it's usually calm but spikes sometimes."
)
fig_box = px.box(
    df,
    x="hour",
    y="display_range",
    labels={"hour": f"Hour of day ({tz_label})", "display_range": range_axis_label.replace("Average ", "")},
    points="outliers",
)
fig_box.update_layout(xaxis=dict(tickmode="linear", dtick=1))
if unit == "%":
    fig_box.update_layout(yaxis=dict(ticksuffix="%"))
st.plotly_chart(fig_box, use_container_width=True)

st.markdown("#### Per-hour range breakdown (% of candles in each bucket)")
st.caption(
    f"For each hour, what share of candles fell into each range bucket "
    f"(buckets shown in **{unit}**, matching your selection above). This is "
    f"the most direct way to compare how *often* an hour stays calm, not "
    f"just what it averages on paper."
)

pct_table = (
    pd.crosstab(df["hour"], df["bucket"], normalize="index")
    .reindex(columns=ACTIVE_BUCKET_LABELS, fill_value=0)
    .reindex(index=range(24), fill_value=0)
    * 100
)

fig_pct = px.bar(
    pct_table.reset_index().melt(id_vars="hour", var_name="bucket", value_name="pct"),
    x="hour",
    y="pct",
    color="bucket",
    category_orders={"bucket": ACTIVE_BUCKET_LABELS},
    labels={"hour": f"Hour of day ({tz_label})", "pct": "% of candles"},
)
fig_pct.update_layout(xaxis=dict(tickmode="linear", dtick=1), yaxis=dict(ticksuffix="%"), barmode="stack")
st.plotly_chart(fig_pct, use_container_width=True)

with st.expander("See exact percentages as a table"):
    pct_display = pct_table.copy()
    pct_display.index = pct_display.index.map(lambda h: f"{int(h):02d}:00")
    pct_display = pct_display.round(1).astype(str) + "%"
    st.dataframe(pct_display, use_container_width=True)

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
    labels={"hour": f"Hour of day ({tz_label})", "max_range": f"Max range ({unit})"},
    title="Maximum hourly range seen, by hour of day",
)
fig_max.update_layout(xaxis=dict(tickmode="linear", dtick=1))
if unit == "%":
    fig_max.update_layout(yaxis=dict(ticksuffix="%"))
st.plotly_chart(fig_max, use_container_width=True)

fig_mean = px.bar(
    hourly,
    x="hour",
    y="mean_range",
    color="thin_liquidity",
    color_discrete_map={True: "#d3a625", False: "#1f77b4"},
    labels={
        "hour": f"Hour of day ({tz_label})",
        "mean_range": f"Average range ({unit})",
        "thin_liquidity": "Low volume (bottom 25%)",
    },
    title="Average hourly range, by hour of day (typical movement)",
)
fig_mean.update_layout(xaxis=dict(tickmode="linear", dtick=1))
if unit == "%":
    fig_mean.update_layout(yaxis=dict(ticksuffix="%"))
st.plotly_chart(fig_mean, use_container_width=True)

st.divider()

# ---- Bucket distribution ----
st.subheader("Range buckets by hour of day")
st.caption(f"Each hourly candle is bucketed by its high-low range, shown in {unit}.")

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
    category_orders={"bucket": ACTIVE_BUCKET_LABELS},
    labels={"hour": f"Hour of day ({tz_label})", "count": "Number of candles"},
    title="Distribution of candle-range buckets across the day",
)
fig_bucket.update_layout(xaxis=dict(tickmode="linear", dtick=1))
st.plotly_chart(fig_bucket, use_container_width=True)

st.subheader("Overall bucket breakdown (whole window)")
total_bucket = df["bucket"].value_counts().reindex(ACTIVE_BUCKET_LABELS).fillna(0).astype(int)
total_bucket_pct = (total_bucket / total_bucket.sum() * 100).round(1)
summary_df = pd.DataFrame({"candles": total_bucket, "% of hours": total_bucket_pct})
st.dataframe(summary_df, use_container_width=True)

st.divider()

# ---- Raw table + download ----
with st.expander("Raw hourly data (sortable table)"):
    show_cols = ["local_time", "dow", "hour", "open", "high", "low", "close", "range", "range_pct", "bucket"]
    st.dataframe(
        df[show_cols].sort_values("local_time", ascending=False),
        use_container_width=True,
    )

csv = df[show_cols].to_csv(index=False).encode("utf-8")
st.download_button(
    "Download this data as CSV",
    data=csv,
    file_name=f"{coin['short']}_hourly_range_{lookback_days}d.csv",
    mime="text/csv",
)

st.caption(
    "Data refreshes from Coinbase every time you change a setting (cached for 30 min). "
    "This is Coinbase's own spot market data — actual ranges can differ slightly "
    "from other exchanges like Binance or Kraken."
)
