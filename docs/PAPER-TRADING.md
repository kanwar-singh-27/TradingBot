# Running the NIFTY paper agent

## Start in VS Code

Open [NIFTY-Trading.code-workspace](../NIFTY-Trading.code-workspace), then select **NIFTY Paper Trader** in Copilot Chat. If missing, reload the window and inspect Chat Customizations/Diagnostics.

Send one of:

> Start paper trading for 60 minutes using public data.

> Start paper trading for 120 minutes with virtual capital of INR 500,000.

> Show paper trading status.

> Show the session report and explain why it traded or stayed in cash.

> Stop paper trading.

For an explicitly synthetic demonstration outside market hours:

> Run a synthetic demo for one minute, then show its report.

The agent launches a detached Python worker. It does not need to repeatedly prompt itself or keep the chat busy. Ask for a report after the duration; there is no proactive chat notification feature in this prototype. Closing VS Code is not intended to stop the detached worker, but sleep, shutdown and host process-cleanup policies can. Keep the machine awake.

**Current capability: paper-only prototype. No broker, credentials, real-order route or live-mode flag.**

## Defaults and sources

| Setting | Default |
|---|---|
| Source | Public NSE option-chain snapshots plus Yahoo NIFTY context |
| Duration when omitted in agent request | 60 minutes |
| Maximum duration | 375 minutes |
| Polling | 60 seconds public; one second demo |
| Paper capital | INR 1,000,000 virtual, not real account equity |
| Per-idea risk | Full premium plus cost reserve, at most 0.25% |
| Session loss trigger | 1% including conservative stale-mark treatment |
| Position | One long CE or PE, one official lot, at most one position |
| Limits | At most six entries; stop new entries after three consecutive losses |
| Expiry | First eligible 3–15-calendar-day expiry reported by NSE |
| Entry window | Ordinary weekdays 09:30–14:30 IST with enough session duration left |
| Exit | Stop/target/15-minute hold/session end, using a subsequent valid bid |

No fixed lot size is coded. The provider reads NSE's market-lot CSV and requires a matching expiry-month column. Contract-level transition differences are not validated against a licensed daily instrument master; this remains a public-data prototype.

NSE's newer option-chain endpoint requires an expiry discovered from its contract-info endpoint. The historical option-chain endpoint returned 404 during development. No API stability is guaranteed.

Yahoo minute bars are filtered to completed bars from the same local trading day. No current bars at midnight is correct. Spot/futures/option timestamps are not exchange-grade synchronized here.

Google Finance is not integrated: a displayed index quote is insufficient for a NIFTY options bid/ask simulator. Neither a public page nor a quote snapshot proves fillability or a right to unrestricted automated collection. Verify source terms/permissions before routine use. Sources are disabled individually for the session on 401/403/429, with no bypass; other failures back off.

## How paper entries are selected

The baseline uses at least 31 completed minute observations, a shrunk recent mean, return variance and a 15-minute normal-grid scenario distribution. It reprices eligible options under IV minus two points, unchanged IV and IV plus two points using a zero-carry Black-Scholes approximation. It subtracts adverse spread/slippage, estimated fees and a conservative mean-estimation deduction, and chooses positive scenario value over CASH.

This model is **not trained/calibrated or validated**. Its numerical output is neither a demonstrated expected return nor a statistical lower confidence bound. There is no claim that the first 15-minute sample predicts NIFTY usefully. It exists to exercise a transparent paper workflow and gather evidence.

Missing IV, wide spreads, insufficient displayed quantity, inconsistent underlying sources, stale/gapped bars, unaffordable minimum lots or nonpositive score mean no entry. More virtual capital can change feasibility, not turn an unvalidated model into an edge. Do not loosen risk thresholds to force trades.

## Fill and cost semantics

- Entry intent is recorded on one snapshot; simulated buy occurs only at a strictly later usable snapshot, ask plus 0.1% adverse slippage, within the original ask envelope and revalidated risk/selection.
- Exit intent similarly requires a later bid minus 0.1% slippage. IV or ask-depth failure cannot unnecessarily prevent a bid-valid long-option exit.
- Whole-lot fill only when displayed depth suffices. No partial-fill or queue model yet; failure defers/rejects rather than inventing liquidity.
- Estimated fee per filled order: INR 25 plus 0.2% of premium notional. These are **simulation allowances**, not a broker tariff or correct historical tax accounting. Fees/spreads are not charged twice.
- Amounts are rounded to paise at cash-flow boundaries. Forecast/pricing use floating-point arithmetic. This is not the master exact-decimal accounting system.
- Stop at approximately 15% premium loss, target at approximately 25% premium gain, maximum holding 15 source-clock minutes. Actual simulated exits occur on later usable bids, so limits can be overshot.
- Entry candidates stop early enough to fit holding time; session closing requests begin before its wall-clock deadline. The public network uses bounded socket timeouts; process shutdown can overrun during in-flight HTTP, but late-arriving responses cannot produce new fills after the deadline.
- Source timestamps are chain-wide; leg quotes may themselves be older. Mark all public results PUBLIC_SNAPSHOT_SIMULATION, never realistic executable backtest evidence.

## Duration, stop and unresolved positions

The duration measures elapsed wall time, not exchange-open minutes. Starting after hours will normally produce MARKET_CLOSED and no trades. The prototype has no official holiday/event calendar; same-day freshness blocks old holiday observations, but that is not a complete calendar system.

Stop sets a persisted stop request. If a position exists, the worker attempts a later-snapshot exit for up to two polling intervals plus a short grace interval, bounded by the original end. It never fabricates an exit at the last known bid.

If fresh quotes are missing, final state is **UNRESOLVED**. The report keeps the virtual position, timestamp of last bid, last-known equity and a conservative full-premium-loss equity bound. A new session in that output directory refuses to reset unresolved exposure. There is no automatic portfolio-resume/recovery command yet. Inspect and retain the old session; do not delete it to pretend the trade closed. A separate explicitly named experimental book is a new simulation, not recovery or compounding of the old one.

## Files, process state and auditing

The [CLI](../paper.py) implements start, run, status, report, stop and check. It uses Python 3.12+ standard library; tested here with Python 3.14. No package installation is needed.

Runtime output is created on first use beneath the ignored runtime directory, separated by public/demo source. Each output directory has a SQLite database and worker log. The database stores session configuration/state, snapshots and ordered events. An OS file lock permits only one worker per output directory. This is not a system-wide account lock across deliberately different directories.

Status reports process-lock liveness and heartbeat separately from stored trading state. START_REQUESTED only means the parent spawned a child; confirm a new session and held lock through status. STOP_REQUESTED is not a confirmed sell. Persisted RUNNING with no process lock means interrupted, not healthy.

Every new session gets a new virtual book and records its own starting capital. Reports are not an automatically compounded multi-session portfolio. Simulated intent/fill and state are committed together locally; no external broker reconciliation is involved.

Run the test suite through NIFTY Builder when modifying code. Tests must remain offline; the check command alone performs explicit public source probes.

## What remains in the master plan

This requested prototype does not complete M1–M13. It omits licensed tick feeds, complete historical options replay, official calendars, full tax schedules, trained/calibrated forecasting, news ingestion, LLM gating, full volatility surfaces, spreads/partial fills, risk permits, independent production identities and live broker execution.

There is no promotion path from merely profitable public/demo paper runs. Follow the [master plan](superpowers/plans/2026-09-17-nifty-local-agent-platform.md) before considering a separately built real-money system.