# NIFTY Local Research and Trading Lab

NIFTY 50 index options only. Local quantitative runtime planned; GitHub Copilot in VS Code serves as analyst, adversary and development assistant.

**Status: a bounded paper-only prototype, a local Streamlit dashboard and four VS Code custom agents are implemented. Public snapshots and an explicit synthetic demo are supported. No broker integration, live trading, validated strategy or production risk platform is installed.**

## Start here

1. Open [NIFTY-Trading.code-workspace](NIFTY-Trading.code-workspace) in VS Code.
2. Read the [implementation plan](docs/superpowers/plans/2026-09-17-nifty-local-agent-platform.md).
3. Follow [paper trading usage](docs/PAPER-TRADING.md).
4. For the local monitoring UI, follow [dashboard usage](docs/LOCAL-DASHBOARD.md).
5. Select **NIFTY Paper Trader** and ask: **Start paper trading for 60 minutes using public data.**
6. For further platform development, use **NIFTY Builder** and an explicitly scoped milestone; the prototype does not complete the master milestones.

## Agents

| Agent | Purpose | Current tools |
|---|---|---|
| [NIFTY Paper Trader](.github/agents/nifty-paper-trader.agent.md) | Start/status/report/stop the bounded local paper worker | Read, search, execute (fixed CLI by instruction, not OS sandboxing) |
| [NIFTY Analyst](.github/agents/nifty-analyst.agent.md) | Readiness, sourced research and evidence-based explanations | Read, search, web |
| [NIFTY Adversary](.github/agents/nifty-adversary.agent.md) | Independent review of proposals and safety/evidence gaps | Read, search, web |
| [NIFTY Builder](.github/agents/nifty-builder.agent.md) | Implement and test explicitly scoped development milestones | Read, search, edit, execute |

## Intended trading flow

Licensed data → causal features → regimes and distributions → option scenarios → structure selection or CASH → critique → deterministic risk reservation → permitted execution → independent monitoring and exit → reconciliation/autopsy.

Live trading will require a separate authenticated runtime identity, approved release, broker/data integration, evidence gates and operator arming. No agent directly receives broker credentials or order tools.

Selecting an agent alone does not start a service. Asking NIFTY Paper Trader to start launches the implemented detached paper worker. It may simulate buys/sells or stay in cash; public data is reference-only and the baseline is unvalidated. Copilot chat and any optional unattended LLM API are separate integrations.

Implementation: [CLI](paper.py), [paper package](nifty_paper/__init__.py), [paper tests](tests/test_paper.py), [lifecycle tests](tests/test_runner.py), [prototype design](docs/PAPER-RUNNER-DESIGN.md)."# TradingBot" 
