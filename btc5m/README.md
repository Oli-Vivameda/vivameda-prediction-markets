# BTC five-minute Polymarket paper lab

A separate research lane in the Vivameda prediction-market repository. It observes public BTC reference ticks and exact five-minute Up/Down contracts, records order-book events, and tests locked paper decisions. No order submission, signer, wallet key or funded execution exists.

## Run locally

Python 3.11+ with standard-library runtime dependencies. From the repository root:

```bash
cd btc5m
python3 -m unittest discover -s . -q
python3 agent.py --database /absolute/private/btc5m/paper.sqlite3
```

Create a private directory before starting. The dashboard listens on `127.0.0.1:8765`. Public market discovery and WebSockets require internet access; a running dashboard alone does not prove healthy feeds. The initial portfolio uses $1,000 virtual cash. Treat the whole runtime directory as private: it contains trades, wallet observations if configured, reports and journals.

The default capture guard is 2 GiB with a 2 GiB free-space floor. Configure storage only after validating the intended mounted volume. Production capture uses an independently validated volume and larger budget; no production path or account record is included here. Missing mounted storage refuses root-filesystem fallback. History is never automatically deleted.

## Trading and learning behavior

Manual paper trades lock side, entry assessment and hold-to-resolution plan. Live probability updates cannot rewrite an entered trade. Limits are $10 per manual order, $50 open exposure and a $20 UTC-day gross realized loss stop.

Automatic shadow trials freeze one decision with 180 seconds left. Each $5 entry is tested in separate 250 ms and 2 s delay arms. Fills require fresh post-delay observed book depth, stated fees and an adverse-price limit. The baseline is an uncalibrated Brownian/TWAP model; there is no established profitable edge. Official explicit winning tokens settle positions.

Health guards pause new automatic entries on stale feeds, capture gaps or worker faults. Bounded supervision allows at most three recoveries per rolling hour. Reports use Cyprus calendar days and identify coverage gaps, skips, fees, missed fills and official-settlement P&L. Review [the protocol](OPS_PROTOCOL.md) for exact rules.

Read-only real-account tracking accepts a public account wallet. It cannot place trades. Account-cost reconciliation is incomplete and observed account history never automatically retrains or changes the strategy.

## Frozen chronological study

The registered window is 14–28 October 2026 UTC: eight training days, three independent calibration days and three held-out test days, with boundary purges. At least 1,000 eligible resolved markets and 80% window coverage are required; the coverage threshold means at least 3,226 markets in practice.

Two fixed numeric challengers use logistic regression and shallow gradient boosting, with sigmoid calibration on calibration days only. Predictions are saved and hashed before held-out targets are extracted. Reports compare baseline, market and momentum using Brier, log loss, reliability bins, 2,000 day bootstrap resamples and delayed-depth counterfactual results. Challengers never activate automatically.

Optional training requires NumPy, scikit-learn and joblib. The synthetic pipeline was verified with NumPy 1.26.4 and scikit-learn 1.9.1; the actual study records dependency versions. Runtime and gate checks need none of these packages. Use a dedicated environment for a standalone installation:

```bash
python3 -m venv /absolute/private/btc5m-training-venv
/absolute/private/btc5m-training-venv/bin/pip install numpy==1.26.4 scikit-learn==1.9.1 joblib
/absolute/private/btc5m-training-venv/bin/python check_training_synthetic.py
/absolute/private/btc5m-training-venv/bin/python training.py \
  --journal /absolute/private/btc5m/paper.sqlite3 \
  --output /absolute/private/btc5m-research
```

Synthetic acceptance creates disposable fake outcomes, never reads real labels and does not demonstrate an edge. Real-data fitting remains gated until the registered window ends and coverage passes. Reusing an already evaluated study directory will not fit another model.

## Reviewed deployment

`launch.py` computes a content hash over the runtime files. `upgrade.py` and `supervised_upgrade.py` validate reviewed hashes and process identities, preserve journal backups and refuse unrelated listeners. Deployment does not occur merely by cloning this repository.

`install_services.py` is a narrowly scoped root installer for dedicated paper-worker and daily training-gate units. Applications run as the engineering user, never root. It requires explicit private runtime/interpreter paths and pinned bundle/installer hashes. It assumes the existing `vivameda-engineer` account and a validated capture-storage configuration; it is not a generic host bootstrap script. Dedicated paper-service and training-timer units were activated and verified on 13 October 2026. The daily training gate is scheduled for 08:05 Asia/Nicosia.

## Validation and outstanding gates

- 74 functional tests pass, including a 10,000-event capture burst.
- Synthetic end-to-end challenger training/calibration/evaluation passes.
- Dashboard JavaScript and systemd unit/calendar checks pass.
- Controlled worker recovery preserved the journal; the accepted capture session had zero drops.
- First completed healthy collection day, future model evaluation and any execution approval remain pending.

See [the build status](BUILD_STATUS.md), [handover](HANDOVER.md) and [source manifest](SOURCE_MANIFEST.json). The company-linked scanner at the repository root retains its own evidence and emission rules; a BTC prediction never counts as company-stack evidence.
