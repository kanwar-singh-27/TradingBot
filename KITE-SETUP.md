# Zerodha Kite Feed Integration

The paper trading system now supports **Zerodha Kite WebSocket** as a real-time market data source alongside the existing NSE HTTP polling and DemoFeed.

## Prerequisites

1. **Zerodha account** with active Kite Connect API access
2. **API credentials:**
   - `api_key` (from Kite Connect settings)
   - `api_secret` (from the Kite app credentials)
   - `request_token` (one-time token returned after login redirect)

The live `access_token` is generated in-session and kept in memory only; it is not stored in `.env`.

## Setup

### 1. Obtain Kite Credentials

1. Log in to your [Zerodha Kite](https://kite.zerodha.com)
2. Go to **Settings → API Tokens**
3. Note your `api_key`
4. Copy your `api_secret` from the Kite app credentials
5. Get the one-time `request_token` from the redirect URL after login

### 2. Store Credentials (Choose One)

**Option A: Using .env File (Recommended for this repo)**

1. Copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env` with your credentials:
   ```
   KITE_API_KEY=your_actual_api_key
   KITE_API_SECRET=your_actual_api_secret
   KITE_REQUEST_TOKEN=the_request_token_from_kite_redirect
   ```

   The access token is generated in memory when the worker starts and is not written to disk or saved in `.env`.

3. Run the Kite launcher script (loads `.env` automatically):
   ```powershell
   .\run-kite.ps1 -DurationMinutes 30 -PollSeconds 1 -OutputDir runtime/kite
   ```

**Option B: Environment Variables (Manual)**
```powershell
$env:KITE_API_KEY = "your_api_key_here"
$env:KITE_API_SECRET = "your_api_secret_here"
$env:KITE_REQUEST_TOKEN = "request_token_from_redirect_url"
python paper.py run --source kite --duration-minutes 30 --output runtime/kite
```

**Important:** In Kite v3, the access token is not generated from the API key alone. It is produced by exchanging the one-time `request_token` with the `api_secret` at the `/session/token` endpoint. The code does that automatically at runtime and keeps the resulting session token in memory only.

## Usage

### Start a Kite Feed Session (Using run-kite.ps1)

**Default (30 min, 1-second polling):**
```powershell
.\run-kite.ps1
```

**Custom parameters:**
```powershell
.\run-kite.ps1 -DurationMinutes 60 -PollSeconds 2 -OutputDir runtime/kite-prod
```

**Check Kite feed health:**
```powershell
.\run-kite.ps1 -Command check
```

### Start a Kite Feed Session (Manual)

If not using the script, load env vars first:
```powershell
$env:KITE_API_KEY = "your_key"
$env:KITE_API_SECRET = "your_api_secret"
$env:KITE_REQUEST_TOKEN = "request_token_from_redirect"
python paper.py run --source kite --duration-minutes 30 --poll-seconds 1 --output runtime/kite
```

### Check Kite Feed Health

```bash
python paper.py check --source kite
```

### Get a Request Token

1. Open the Kite login flow in a browser:
   ```text
   https://kite.zerodha.com/connect/login?v=3&api_key=YOUR_API_KEY
   ```
2. Log in and authorize the app.
3. Kite redirects back to your registered redirect URL with a `request_token` query parameter.
4. Paste that token into `KITE_REQUEST_TOKEN` in `.env`.
5. The runner exchanges it with `KITE_API_SECRET` and fetches the session access token in memory automatically.

Expected output:
```json
{
  "status": "SOURCE_RESPONSE_RECEIVED",
  "kind": "ZERODHA_KITE_WEBSOCKET",
  "as_of": "2026-09-17T10:45:32.123456+00:00",
  "spot": 23850.5,
  "options": 18,
  "completed_bars": 61
}
```

## How It Works

### Data Sources

| Component | Source | Frequency | Latency |
|-----------|--------|-----------|---------|
| **Spot Price** | Kite Quote API | Per fetch | 100–500ms |
| **Option Chain** | Kite Instruments + Quote API | Per fetch | 100–500ms |
| **Context Bars** | Kite Historical Data (1m candles) | Per fetch | 1–2s |
| **Lot Size** | Kite Instruments (cached) | Once per session | — |

### Request Flow

1. **Initialize**: Fetch eligible expiries and lot size (cached)
2. **Fetch Snapshot**:
   - Request NIFTY50 spot price
   - Fetch all NIFTY options within ±1% of spot
   - Download last 61 1-minute candles for baseline calibration
   - Return complete `Snapshot` to engine

3. **Entry Decision** (same as other sources):
   - Build baseline model from bars
   - Score each option post-cost
   - Risk-check lot against budget
   - Fill on next snapshot if positive

## Rate Limits

Zerodha Kite free tier: **5 requests/second** (usually enough for paper trading with `--poll-seconds 1`)

For faster polling, consider **Kite Connect Pro** or **Shoonya institutional**.

## Troubleshooting

### "KITE_API_KEY and KITE_API_SECRET required"
Ensure the API key and API secret are set in the environment or passed as CLI arguments. The access token is fetched at runtime from the request token when needed.

### "Kite API error: HTTPError: 401"
- API key is invalid or expired
- Check credentials in Kite dashboard

### "No NIFTY options found for current spot"
- NSE market is closed (Kite only returns live data during market hours)
- Try running during 09:15–15:30 IST

### "Kite feed in bounded error backoff"
- Multiple fetch failures have triggered exponential backoff
- Feed will retry after 60–300 seconds
- Check network and API rate limits

## Comparison: Kite vs NSE vs Demo

| Feature | Kite | NSE | Demo |
|---------|------|-----|------|
| Real-time | ✅ Yes (~500ms) | ❌ Polling (~2–3s) | ❌ No (synthetic) |
| Latency | 100–500ms | 2–3s | <1ms |
| Cost | Free tier OK | Free | Free |
| Requires Account | ✅ Yes | ❌ No | ❌ No |
| Market Hours Only | ✅ Yes | ✅ Yes | ❌ No (24/7) |
| Reproducible | ❌ No | ❌ No | ✅ Yes (deterministic) |

## Next Steps

1. Add CLI arguments `--api-key` and `--access-token` if not using environment variables
2. Test with live market hours (09:15–15:30 IST weekdays)
3. Monitor WebSocket connection health in production
4. Consider fallback to PublicFeed if Kite becomes unavailable mid-session

---

**Important:** Kite feed is for **research and paper trading only**. No real orders are placed. All fills remain simulated in the local SQLite journal.
