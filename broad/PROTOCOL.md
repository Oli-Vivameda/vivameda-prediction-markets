# Broad Polymarket opportunity lab v1

Frozen before opening prospective outcome labels on 14 October 2026.
This lane is independent of the existing BTC study. No company panel,
CoreSignal, client evidence, sealed outcomes or private wallet histories are used.

## Scope and agent
Public GET discovery across categories with rotating pages plus volume-ranked
pages; bounded coverage is reported, never called the entire market universe.
The agent is a deterministic controller: discover, capture, evaluate, delay,
recheck, paper reserve, reconcile, report. Language-model confidence is not an
order signal. First supported book/fee adapter: ordinary two-outcome CTF v1.
Protocol V2, negative-risk transformations and delayed matching are recorded
as unsupported. Individual ordinary binary pairs in negative-risk events are
also excluded from this first adapter.

## Strategies
1. Equal-size complementary taker pairs: positive net paired payout after
observed depth, per-market fees, a 0.01/share reserve and 2-second delayed
recheck. Paper only. Sequential books are not atomic execution evidence.
2. Two-sided maker candidates: quote, spread, depth and inventory-risk inputs
are recorded. No assumed maker fills or assumed rewards. No maker P&L.
3. Explicitly reviewed payoff matrices: separate file of exact contract IDs,
rule hashes, exhaustive outcome states and per-leg payouts. The verifier
computes worst-case portfolio payout; semantics are not inferred automatically.
They are diagnostic candidates, not automatically executable orders.

## Capital and accounting
Each independent paper strategy starts at $100. Pair reserve <=$5/market;
total open cost <=$20; one pair per exact condition/rule hash. Fees included.
No credited redemption until closed official winner confirmation with exact
token identity. Settlement creates virtual cash only, never real funds.
Ledger persists, uniqueness and transactions prevent duplicate entries.
Ambiguous/missing outcomes remain capital locked. No invented profits.

## Model study
Quote-risk model, not an event-resolution forecaster: binary target is adverse
60-second midpoint movement exceeding the initial half-spread, on each side.
Use the first complete observation per market per UTC minute. Features frozen:
spread, top-five imbalance, log depth, price, log seconds to stated deadline,
fee rate, paired net edge. Labels require the same rule/asset identities and
a complete observation 60-90 seconds later. Unknown or late observations
are excluded, never labelled zero.
Train only after 14 elapsed days, >=2,000 market-minute examples and >=200
distinct contracts. Chronological 60/20/20 split on unique markets' first-seen
times; purge training/calibration observations after each boundary minus 90s.
No contract appears in two partitions. Logistic model with train-only scaling;
calibration fitted on middle partition; predictions saved and hashed before
extracting test labels. Compare majority, constant empirical rate and simple
spread baseline; report Brier/log loss, calibration, class counts and 2,000
market-level bootstrap resamples. Holdout is consumed once, never tuned.
Model is a research artifact; no automatic promotion or claim of trading edge.
Quote-risk improvement alone is not a profitability gate.

## Limits and activation
Data budget 512 MiB, free-space floor 2 GiB; halt without deleting captures.
Public endpoints only, no new paid accounts or purchases. Polling scanner is
not a high-frequency arbitrage system. Freshness <=5s, pair skew <=2s,
metadata <=60s, positive time-to-deadline, all costs required.
Live execution is not activated by this build. Existing owner-operated BTC
pilot remains independent. Broad paired live execution requires account,
protocol/SDK, allowance, order/fill reconciliation and partial-leg unwind
validation; paper fills cannot pass those requirements.

## Sources checked
https://docs.polymarket.com/market-data/discover-markets
https://docs.polymarket.com/market-data/market-details
https://docs.polymarket.com/trading/fees
https://docs.polymarket.com/trading/place-orders
