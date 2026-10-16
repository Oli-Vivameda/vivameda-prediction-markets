# BTC / ETH / SOL five-minute paper study v1.1

**Stage: collecting data—no validated edge. Live execution is absent.**

This extends the existing BTC paper infrastructure with a separate multi-asset experiment. It does not alter the scanner, earlier paper studies, model validation or live stops/budgets.

| Component | Reuse / change | Verified limitation |
|---|---|---|
| Public transport | Extract existing BTC RFC6455 client | Bounded text frames; disconnect invalidates quotes |
| Capture | Reuse compressed hash-chained SQLite batches | One-second decision states, not a complete tick tape |
| Market adapter | Extend fixed Gamma/CLOB identity, fee, minimum and depth checks | Exact recognized Chainlink TWAP rule template only |
| Model interface | Transparent TWAP baseline and offline asset logistic interface | No contractual reference adapter connected; no operational forecasts |
| Decision / simulator | New correlated ledger for fixed stakes and sequential paired legs | Synthetic acceptance is not proof of actual fills |
| Evaluation | Frozen chronological splits and read-only report | Final results withheld until registered release time; no automated adoption |

Public stream collection: both Up/Down books for all three assets, timestamped supporting exchange prices, market rules/fees/minimums, health/gaps and official resolutions. Opening TWAP, contractual reference price and normalized distance are explicitly missing. Supporting exchange samples never replace them. The current official authenticated PolyBolt reference feed is deliberately not accessed by this credential-free release. Both strategies skip until a separately reviewed reference bridge/new experiment makes those inputs available.

Defaults: independent 10,000 virtual cash, at most 25 per directional position or total paired reservation, shared 75 committed cost per five-minute window and 100 daily lower-bound-equity loss including reservations. No Kelly, passive execution, martingale, real capital, signer, paid API or profit claim. Read [PROTOCOL.md](PROTOCOL.md) for complete simulation, partial-leg, settlement and holdout assumptions.

Tests: `python3 -B -m unittest -q test_study`. Review source pin: `python3 -B install.py`. See [RUNBOOK.md](RUNBOOK.md), [HANDOVER.md](HANDOVER.md) and [BUILD_STATUS.md](BUILD_STATUS.md). Runtime and raw data remain private to the server; this repository contains generic source, synthetic fixtures and scoped verification only.
