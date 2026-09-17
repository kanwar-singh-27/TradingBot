# Local paper dashboard

This dashboard is a **local, loopback-only, paper-session monitor** for the existing NIFTY paper worker. It reads the SQLite journal already produced by the worker and invokes the fixed `paper.py` CLI for `start`, `status`, `stop` and `check` operations. It does **not** place live orders, connect to a broker or bypass the paper engine.

## Implemented views

- Overview: selected session, worker liveness, heartbeat age, stored session state, planned end, capital, cash, realized P&L, estimated unrealized P&L, last-known equity, conservative lower bound, fees, entries, completed trades, pending action and source timestamps.
- Market: recorded NIFTY snapshot history, completed underlying minute bars from the journal, and the latest recorded option rows with expiry/right/proximity filters.
- Timeline: recorded events with deterministic reason labels, raw reason codes and expandable payload details.
- Forecast: decision funnel, first/all rejection codes, candidate traces, score/uncertainty distributions, near misses, execution outcomes, and the unvalidated baseline outputs.
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
- `Paper source` reruns before submission so its displayed virtual capital matches the chosen mode. Defaults: public/demo INR 1,000,000; public_loose INR 4,000,000. Custom values are passed explicitly and existing sessions are never rewritten.
- If both legacy and canonical loose journals exist, choose the journal explicitly. They are independent books; no automatic merging, resetting or compounding occurs. Active/unresolved alternate books block dashboard starts.

## Diagnose zero entries without placing trades

- Open **Forecast → Decision Pipeline**. New sessions persist every normalized candidate's numeric evidence and PASS/FAIL/NOT_EVALUATED gate states. First-failure counts are exclusive; all-failure counts can overlap.
- Funnel counts are **candidate observations per snapshot**, not unique contracts. Quotes discarded before normalization are outside this milestone's count coverage; public timestamps remain chain-wide, not verified per-leg quote ages.
- The risk engine chooses the highest-scoring candidate **among those passing its hard gates**, then revalidates on a later snapshot. An unaffordable highest score no longer hides an affordable positive alternative. Risk remains full premium plus fee reserve at 0.25% of the lesser of starting capital/current equity; scoring formulas are unchanged.
- Snapshot freshness uses the configured 90-second maximum without adding the polling interval. Five seconds of future clock tolerance is retained. Strict freshness may correctly increase data rejections.
- **Diagnostic only — no positions** (CLI `--diagnostic`) evaluates entries but creates no pending buys, positions, fees or fills. `WOULD_CREATE_ENTRY_INTENT` is not a promise of a later fill.
- Older zero-entry sessions can use **Replay stored snapshots (no trades)**. The CLI `diagnose` command accepts `--source`, explicit `--output` when journals are ambiguous, and optional `--session-id`. It reads the selected SQLite journal without fetching data, starting workers, or writing to it. Save timestamps conservatively proxy old decision times; results are current-code counterfactuals, not invented historical traces. Traded legacy sessions are not replayed as flat books.
- **Download diagnostic report** exports the aggregate summary and latest complete candidate evaluation. CLI `report` includes persisted diagnostics; no-data/closed-market event counts remain visible even when no candidates were evaluated.
- Missing historical traces are labelled unavailable. New sessions with no evaluated snapshots show no-evaluation status, not a fabricated funnel.
- Historical warm-up/exchange calendars, full per-leg timestamp and halt-state redesign, and base-versus-tick-slippage comparisons are **deferred**, not implemented by this diagnostics-first milestone. There is no new uncertainty cutoff and no automatic threshold tuning.
- Restarting or creating a paper worker remains an explicit operator action. Refreshing the UI does not replace code inside an already-running worker.

## Notes

- UI refresh defaults to **Off**. Optional periodic refreshes read the local journal and local CLI status; they do not start a session or fetch market data.
- Synthetic smoke testing should use `demo` only. Do not start `public` or `public_loose` market sessions as a side effect of automated UI verification.
- Closing or refreshing the dashboard does not stop or duplicate the detached worker.