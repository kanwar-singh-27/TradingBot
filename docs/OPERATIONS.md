# NIFTY agent activation and operations

## What exists now

This folder contains the master plan, four VS Code custom agents and a bounded paper-only runner. Use [paper trading usage](PAPER-TRADING.md) for the implemented prototype. It has public NSE/Yahoo observation adapters and an explicit synthetic demo, an unvalidated baseline and local simulated exits. No broker connection, MCP server, trained model or production/live runtime exists. The sections below describing authenticated live operations remain future design, not available functionality.

## Activate in VS Code

1. Use **File → Open Folder** and choose this project folder, or open [NIFTY-Trading.code-workspace](../NIFTY-Trading.code-workspace).
2. Review the files before granting workspace trust.
3. Open Copilot Chat and select **NIFTY Paper Trader**, **NIFTY Analyst**, **NIFTY Adversary** or **NIFTY Builder** from the agent picker.
4. Select an available model in the model picker. These agents intentionally do not pin a model.
5. If an agent is missing, use **Chat: Open Customizations** or **Chat: New Custom Agent** to inspect discovery. Chat diagnostics can report malformed or unavailable customization/tool entries. Reload the window if required.
6. Agent tool availability varies by VS Code version and account policy. Confirm effective tools; missing tools must not be replaced with broader privileges.

## First prompts

### Analyst

> Read the implementation plan. Audit current readiness. State which capabilities are actually implemented and what blocks a fresh NIFTY analysis. Do not invent prices or place orders.

### Builder

> Implement milestone M1 only from the implementation plan. Create a small test-first execution plan, build the offline mode/readiness foundation, run the tests and report evidence. No broker connection, credentials or live trading.

### Adversary

> Review the implementation plan and the current implementation. Find paths that could bypass risk limits, use future data, duplicate orders or expose credentials. Distinguish demonstrated defects from hypothetical concerns.

## Future daily operation after the runtime exists

1. Start the independently supervised services; startup remains DISARMED until readiness and reconciliation pass.
2. Log in through the operator's independent broker flow if required. Type secrets only in the intended credential interface, never Copilot chat.
3. Select paper/live mode in the authenticated local operator UI. Approve only released scopes.
4. Ask Analyst for status and sourced evidence. The local service, not chat, generates numerical proposals.
5. Human-approved live entries require an expiring exact-proposal approval in the operator UI.
6. Runtime owns confirmed fills and exits. Closing VS Code must not stop position monitoring.
7. Verify confirmed flat state and end-of-day reconciliation. An exit request is not an exit fill.

## Incident response

### Unknown broker status

- Halt new entries; retain reservations.
- Query authoritative order/trade/position state through the runtime's reconciliation path.
- Never repeat a timed-out order blindly.
- Escalate to independent broker access if the runtime cannot determine exposure.

### Stale data or reasoning outage

- Skip new entries.
- Keep deterministic protective management active.
- Never substitute a web page, screenshot or guessed quote for the required executable feed.

### Critical runtime/power/network failure

- Use independent phone/mobile broker access and alerts; local kill controls may be unreachable.
- Check actual positions and working orders before acting.
- Preserve protection when closing multi-leg structures.
- Do not shut down the only functioning exit process as a substitute for a controlled halt.

### Recovery

- Restart halted.
- Reconcile orders, fills, cash, reservations and positions.
- Review the incident, fix and test the cause, then obtain explicit operator rearming.

## Capability boundaries

Agent Markdown instructions are not deterministic enforcement. Do not give the Analyst/Adversary a terminal, browser automation, database writes, a trade-capable MCP server or broker secrets. Prompt files can alter effective tool selection, so review those too.

The Builder has development edit/execute capabilities. Run it only in a credential-free development identity. A live service running as the same unrestricted user would not provide adequate isolation merely because the agent body says not to trade.

No guarantees of returns, fills, stop execution, loss-cap adherence during outages or complete catastrophe prevention are made.