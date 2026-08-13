# BTC Hourly Range Explorer

An interactive Streamlit app that pulls live hourly BTC/USD candles from
CryptoCompare's public API and shows, by hour of day, how big the typical / max
price range is — plus a 100/200/300/400/500-point bucket breakdown.

> **Note:** an earlier version used Binance's API directly, but Binance
> returns HTTP 451 (geo-blocked) for US-hosted servers — including Streamlit
> Community Cloud's default region. CryptoCompare aggregates price data
> across exchanges and isn't subject to that block.

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL it prints (usually http://localhost:8501).

## Deploy it for free on Streamlit Community Cloud (streamlit.app)

1. **Put these two files in a GitHub repo.**
   Create a new repo (public or private) and upload `app.py` and
   `requirements.txt` to it — e.g. via GitHub's web "Add file → Upload
   files" button, no git command line needed.

2. **Go to** [share.streamlit.io](https://share.streamlit.io) **and sign in
   with GitHub.** It's free.

3. **Click "New app"**, pick your repo, branch (`main`), and set the main
   file path to `app.py`.

4. **Click "Deploy."** Streamlit installs `requirements.txt` and starts the
   app. You'll get a public URL like
   `https://your-app-name.streamlit.app` that you can open on any device.

5. **No secrets/API keys needed** — Binance's kline endpoint is public.

Once deployed, use the sidebar to change the lookback window (7–180 days),
timezone (UTC, Munich, New York, IST, JST), and symbol. The app re-fetches
and re-caches data (30 min cache) each time you change a setting.

## Notes

- Data comes from `https://min-api.cryptocompare.com/data/v2/histohour` —
  an aggregated BTC/USD price across major exchanges, `1h` interval, no
  API key required for this usage level.
- Ranges are `high - low` per hourly candle, in raw USD points (not %).
- Because this is an aggregated/index price rather than a single exchange's
  order book, exact numbers may differ slightly from Binance-specific data,
  but the hour-of-day patterns (quiet vs. busy hours) will be consistent.
