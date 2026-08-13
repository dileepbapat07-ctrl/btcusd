# BTC Hourly Range Explorer

An interactive Streamlit app that pulls live hourly BTCUSDT candles from
Binance's public API and shows, by hour of day, how big the typical / max
price range is — plus a 100/200/300/400/500-point bucket breakdown.

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

- Data comes directly from `https://api.binance.com/api/v3/klines` —
  spot market, `1h` interval.
- If Binance's API is geo-blocked from wherever you deploy (rare, but
  happens for some cloud regions), you'd see a fetch error — Streamlit
  Community Cloud's default region hasn't had issues with this in
  practice.
- Ranges are `high - low` per hourly candle, in raw USD points (not %).
