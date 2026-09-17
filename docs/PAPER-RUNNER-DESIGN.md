# Bounded paper runner: implementation scope

Date: 2026-09-17. This is an explicitly requested paper-only prototype, not completion of the master platform milestones and never a live-trading release.

## Behavior

- A dedicated NIFTY Paper Trader custom agent starts, inspects or stops a detached local Python worker through a fixed CLI.
- Duration is mandatory at the CLI and defaults to 60 minutes only when the operator asks the agent to start without specifying a duration. Public polling is no faster than 60 seconds. Maximum duration is 375 minutes.
- Public source: NSE expiry discovery, newer option-chain JSON and official monthly market-lot CSV; Yahoo NIFTY completed minute bars provide underlying forecast context. Google Finance has no supported executable NIFTY option feed here.
- No login, cookies copied from a browser, captcha bypass, proxy rotation or retries around access controls. HTTP 401/403/429 disables requests to that source for the session. Other failures use bounded backoff. Operator must ensure permitted source usage.
- Quotes are public reference snapshots, possibly delayed. A chain timestamp does not prove every individual option quote is fresh. Paper results are labelled PUBLIC_SNAPSHOT_SIMULATION and cannot satisfy the master live-promotion gates.
- A separate explicit DEMO source emits deterministic synthetic observations to exercise buy/hold/sell behavior outside market hours. No silent fallback from public to demo.
- SQLite journals configuration, heartbeats, source snapshots, decisions, simulated orders, fills and positions per session. Only one active worker per output directory. Status distinguishes running, stale heartbeat, completed, interrupted and unresolved exposure.
- An exclusive OS file lock prevents competing workers. Restart never resumes an old portfolio implicitly. New starts refuse unresolved previous positions; demo sessions use a separate output directory by default.

## Baseline and risk

- Long CE/PE only, one lot/position at most, 3–15 calendar days to expiry, liquid ATM/moderately ITM strikes; no short opening orders.
- Use recent completed minute log returns, shrink their mean, estimate variance and evaluate a normal-grid underlying distribution at a 15-minute horizon. Reprice options with simple Black-Scholes assumptions at three IV shifts. Choose the worst mean payoff over IV shifts, subtract a mean-estimation uncertainty allowance and simulated costs, then compare with cash.
- This is an uncalibrated research baseline, not a trained ML model or validated positive edge. No HMM, model registry, full surface, news classifier, portfolio optimizer or calibrated LLM critique is claimed.
- Risk uses full premium plus entry/exit cost reserve, max 0.25% capital per idea, max 1% session drawdown/loss trigger, three consecutive losers, six entries, one position and no forced minimum trade count. Paper capital is explicitly virtual (default INR 1,000,000), not an inferred real balance.
- Proposed entries fill only on a strictly later usable source snapshot, at ask plus adverse slippage, within the original budget and price envelope. Reject stale/invalid/insufficient-depth quotes and expired proposals. Entry eligibility is recomputed before fill.
- Sell exits also require a later usable bid and sufficient quoted size. No same-snapshot profitable fills. Costs are transparent conservative configurable assumptions, not a complete effective-dated Indian charge engine.
- Stops, targets, maximum hold and session-end flattening trigger exit intents. No artificial end-of-session fill: if no fresh quote arrives, persist UNRESOLVED rather than fabricate a close. Last known marks are timestamped; a full-premium-loss equity bound is shown separately.
- Entries only in normal weekday 09:30–14:30 IST window; exits requested by 15:10. No entries unless enough duration remains for next-snapshot fill and holding horizon. No official holiday calendar yet; same-day source freshness is required, so stale holiday feeds cannot create trades.

## Tests before implementation

Use standard-library unittest to avoid new dependencies on this Windows Python 3.14 machine. Verify public schemas, timestamps, lot lookup, pricing parity, expensive-option rejection, long-only risk, stale data, later-snapshot fills, ask/bid accounting, stop without quotes, session exclusivity, persistence and CLI bounded demo completion. Tests use fixtures, not network.

## Limits

A detached process survives chat closure but not guaranteed OS shutdown, sleep, host policy or terminal-manager cleanup. No position is real. No broker SDK, key, account, order route or live-mode switch exists. Tool allowlists/instructions are not OS sandboxing; run the custom agent in a credential-free development environment.