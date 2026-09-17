# Local paper dashboard

This dashboard is a **local, loopback-only, paper-session monitor** for the existing NIFTY paper worker. It reads the SQLite journal already produced by the worker and invokes the fixed `paper.py` CLI for `start`, `status`, `stop` and `check` operations. It does **not** place live orders, connect to a broker or bypass the paper engine.

## Implemented views

- Overview: selected session, worker liveness, heartbeat age, stored session state, planned end, capital, cash, realized P&L, estimated unrealized P&L, last-known equity, conservative lower bound, fees, entries, completed trades, pending action and source timestamps.
- Market: recorded NIFTY snapshot history, completed underlying minute bars from the journal, and the latest recorded option rows with expiry/right/proximity filters.
- Timeline: recorded events with deterministic reason labels, raw reason codes and expandable payload details.
- Forecast: only the currently persisted baseline outputs, with a standing warning that they are unvalidated research values.
- Positions and risk: current simulated position, completed trade linkage when auditable, exposure, risk budget, drawdown threshold and halt state.
- History: realized P&L, timestamped equity history for newer sessions, estimated cumulative fees, and a trade-outcome distribution when enough trades exist.

## Unavailable or intentionally omitted

- No broker connectivity, live-trading switch, manual buy button, manual sell button or browser order automation.
- No news, calibrated ML, Greeks, option volume, option OI, spread strategies or master-plan features that are not already journaled by the current prototype.
- Older sessions may show `Historical equity samples unavailable.` because timestamped equity storage starts with this dashboard milestone.
- Older sessions without stable trade IDs may show `Auditable buy/sell linkage unavailable for this older session.` rather than a guessed pairing.

## Local setup

From [d:/Trading](../):

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Run the dashboard

```powershell
.\.venv\Scripts\python -m streamlit run dashboard.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501` in a local browser.

## Start or stop paper sessions

- From the dashboard sidebar, use `Start paper session` for `public`, `public_loose`, or the explicit `demo` source.
- `public_loose` uses the same public NSE plus Yahoo inputs as `public`, but applies a looser research scoring rule so you can compare trade frequency and rejection reasons without weakening the default conservative mode.
- `Request graceful stop` targets the currently active session identity for the selected source and refuses to stop a different session.
- `Source health check` is explicit. The dashboard does not automatically hit NSE or Yahoo during refresh.

## Notes

- The dashboard refreshes UI state periodically, but normal refreshes only read the local journal and local CLI status.
- Synthetic smoke testing should use `demo` only. Do not start `public` or `public_loose` market sessions as a side effect of automated UI verification.
- Closing or refreshing the dashboard does not stop or duplicate the detached worker.