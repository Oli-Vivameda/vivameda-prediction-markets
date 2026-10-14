# Broad Polymarket opportunity lab

This source adds a separate broad-market research lane. It does not modify the
existing company scanner, BTC study, model defaults or owner-operated BTC pilot.
The paper strategy has a $100 virtual bankroll. No live signer, order submission,
redemption, trading wallet configuration or real-money service is enabled.

## Implemented
- Public discovery across categories: rotating catalogue and volume-ranked pages.
  Coverage is bounded and explicitly reported. First book adapter supports v1
  CTF ordinary binary markets; unsupported protocols and delays fail closed.
- Fees/depth-aware complementary-pair scanner with a two-second delayed probe.
  Pair economics include a one-cent/share reserve, venue minimums, fresh metadata,
  book timestamps, exact identities and rule hashes. Books are not atomic fills.
- Maker watchlist without invented fills, rebates or market-making P&L.
- Diagnostic payoff-matrix verifier for explicitly reviewed cross-market rules.
- Persistent paper ledger, locked-capital accounting, exact official settlement,
  one pair per market, $5 entry cap and $20 open-cost cap.
- Prospective 60-second quote-risk labels, chronological contract-disjoint
  training/calibration/test, portable logistic model, prediction hashes,
  baseline comparisons, uncertainty and no automatic model promotion.
- Storage guards, STOP file, single-writer lock, status file and hash-chained log.
- Reviewed owner-operated paper service and daily training-gate installer.

## Use
Python 3.11+; scanner uses standard library. Training and the synthetic model test
require numpy/scikit-learn in an existing environment. No package purchases or
account subscriptions are required. Use an absolute private state directory.

```bash
python3 engine.py scan --state-dir /absolute/private/polymarket-lab
python3 engine.py run --state-dir /absolute/private/polymarket-lab
python3 engine.py status --state-dir /absolute/private/polymarket-lab
python3 engine.py verify --state-dir /absolute/private/polymarket-lab
python3 training.py --state-dir /absolute/private/polymarket-lab
python3 -m unittest -q test_engine
```

Place `STOP` inside the state directory to prevent further cycles. Restart does
not clear prior positions or budgets. A paper position waits for an officially
closed, uniquely resolved contract; the build does not assume instant redemption
or merge cash. Long-duration positions can lock capital for substantial periods.

`install.py` prints the source bundle hash without changing services. The owner
can install the exact reviewed hash with `--install --expected-sha256 HASH
--training-python /absolute/existing/venv/bin/python`. This creates only the new
paper service and training timer. Service installation requires root privileges;
the service runs as a non-root engineering user. Existing units are preserved.

## Training status and limitations
The prospective model cannot train immediately: 14 elapsed days, 2,000 labelled
market-minutes and 200 distinct contracts are required. Passing synthetic tests
establishes implementation, not real-data training or profitable trading.
The model estimates adverse quote movements; it is not a universal event
forecaster. Candidate scanning is polling research, not low-latency arbitrage.

Broad live execution is the next separate engineering gate. It requires a
privately configured eligible account, exact current SDK/protocol verification,
allowances, confirmed fills, bounded partial-leg handling and cash reconciliation.
Batch orders are not atomic. The official SDK inspected during this build did
not expose FOK on `create_limit_order`; this build does not silently turn a
resting limit order into a supposedly atomic equal-share pair.
The existing BTC live pilot remains distinct and unchanged.

Private runtime data, accounts and learned artifacts must never be committed.
See PROTOCOL.md for the frozen study and evidence boundaries.
