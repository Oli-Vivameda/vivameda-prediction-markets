# Vivameda prediction markets

Two research lanes share this repository. Installed services keep real-money execution disabled. Optional live-pilot source requires separate owner operation.

| Lane | Code | Purpose |
|---|---|---|
| Company-linked contracts | Repository root | Discover public contracts, retain exact rules, attach bounded company evidence and track reviewed paper forecasts |
| BTC five-minute outcomes | [btc5m/](btc5m/README.md) | Capture public ticks/books, freeze paper entries, monitor health and test chronological numeric challengers |

## Company-contract scanner

Public GET adapters discover ordinary binary Polymarket and Kalshi contracts in rotating bounded pages. A starter company alias registry routes questions for retained evidence. Exact-token crypto evidence is separate; generic chain-price questions abstain. BTC/ETH coverage is withheld by this scanner; the separate BTC lane handles five-minute contracts.

Candidates retain question, rule text, source fingerprint, deadline and observation time. Relevance is a heuristic and never becomes a probability. Descriptive company context alone does not establish identity, resolution answerability or an investment edge.

Reviewed researcher forecasts are immutable and labelled unvalidated. Paper entries require a fresh quote, observed depth, reviewed fees/slippage and positive conservative expected payout minus all-in price. Paper fills are assumptions, not real executions; settlement requires explicit reviewed final payout.

The scanner supports grouped hourly notifications, direct contract links, duplicate suppression and bounded message counts. Destination configuration and credentials stay private. Adding the BTC lane does not change scanner behavior or activate any new notification channel.

## BTC five-minute paper lab

The [BTC lab](btc5m/README.md) uses an uncalibrated volatility/TWAP baseline, immutable trade plans and separate 250 ms/2 s shadow execution arms. It records public reference ticks and book events, pauses entries on unhealthy data and produces private daily reports. The running paper lab has no execution adapter enabled. A separate [owner-operated $10 pilot](btc5m/live_pilot/README.md) adds optional execution software; it is unconfigured and blocked pending account and eligibility checks.

The preregistered study runs 14–28 October 2026 UTC, with independent training, calibration and held-out testing. Two numeric challengers are evaluated against baseline, market and momentum. Count/coverage gates, prediction hashes, realistic depth limitations and no automatic promotion are documented in [the protocol](btc5m/OPS_PROTOCOL.md).

Validation as of 13 October: 74 functional checks and a disposable synthetic challenger pipeline pass. Controlled recovery preserves the journal. Dedicated paper supervision and the daily training-gate timer are active and enabled; the next check is 14 October at 08:05 Asia/Nicosia. First full healthy-day verification, real-data model evaluation and any live execution approval remain pending. No profitable edge is claimed.

## Development

The company scanner's standalone discovery and synthetic tests work without proprietary datasets; the evidence bridge requires separately installed private modules. Run the existing scanner tests from the repository root:

```bash
python3 -m unittest -v test_scanner test_ledger test_notify test_install test_configure_telegram
```

Run the isolated BTC tests separately to avoid module-name collisions:

```bash
cd btc5m
python3 -m unittest discover -s . -q
```

See [the BTC setup guide](btc5m/README.md), [build status](btc5m/BUILD_STATUS.md), [source hashes](btc5m/SOURCE_MANIFEST.json) and [handover index](HANDOVER_INDEX.md). Existing scanner releases and handovers retain their original provenance.

## Data and execution boundaries

This public repository contains reviewed source, tests, protocols and sanitized validation. It excludes credentials, account observations, raw captures, proprietary datasets, private evidence, forecast journals and learned model binaries. Runtime configuration and deployment paths are supplied privately.

Cloning or updating this repository does not deploy services, train a real-data model or place orders. Missing evidence, unknown costs, incomplete identity and unavailable liquidity are explicit limitations. Real trading requires a separate reviewed execution design and authorization.


## BTC / ETH / SOL five-minute research

The isolated [multi-asset study](crypto5m/README.md) extends the BTC collector with versioned rules, shared fixed-stake paper risk, sequential paired-leg simulation, chronological model interfaces and reporting. [Acceptance](crypto5m/ACCEPTANCE.json): 43 checks and bounded public collection verified. Stage is **collecting data—no validated edge**; required contractual reference inputs are unavailable, so both strategies abstain. [Runbook](crypto5m/RUNBOOK.md). Existing scanner and BTC lanes are preserved.
