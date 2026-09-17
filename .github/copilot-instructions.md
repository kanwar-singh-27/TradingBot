# NIFTY platform project instructions

- Scope: NIFTY 50 index options only. Other instruments may provide context but are not tradable here.
- Read [project status](../README.md) and the [implementation plan](../docs/superpowers/plans/2026-09-17-nifty-local-agent-platform.md). Do not confuse planned components with existing capabilities.
- Default to RESEARCH. No live orders, account connections, arming or deployment as part of coding, debugging or test execution.
- Keep broker credentials outside this repository and the VS Code identity. Never request or print tokens/passwords/API keys in chat.
- LLMs research and critique. Numerical code forecasts/prices/sizes. An independently enforced deterministic gateway authorizes all order actions.
- Use exact timestamps, provenance, effective-dated contracts/fees and point-in-time features. Never fabricate live market observations.
- CASH is a first-class decision. No minimum daily profit or forced minimum trade count.
- Use synthetic/replay/paper fixtures for tests and label synthetic data. A passing test does not demonstrate alpha or live safety.
- Preserve user changes. Implement one explicitly requested milestone at a time, test-first, with reproducible verification.
- Do not install broad order-capable tools into analyst/reviewer agents. Tool/prompt instructions do not replace OS identity separation and runtime authorization.
- No automatic promotion or self-modification of deployed strategies. Live artifacts are immutable reviewed releases outside the development checkout.