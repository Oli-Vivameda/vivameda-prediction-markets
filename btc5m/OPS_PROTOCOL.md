# BTC paper operations and frozen challenger protocol

Registered 13 October 2026, before the prospective study begins. Real execution remains false. This adds operational guards to the existing fixed-180-second v3 strategy; it does not change its probability formula, entry edge, stake, delay arms or hold-to-resolution plan.

Health checks run every five seconds. Reference and outcome books must be fresh within three seconds, recording healthy and the strategy worker responsive before any new automatic paper entry. Startup has a two-minute grace period but never permits unhealthy entries. Worker exits, recording failures or a market loop stalled for 90 seconds request bounded recovery. Storage budget or missing-volume faults require operator intervention, rather than a restart loop. Recovery waits with backoff and allows at most three restarts per rolling hour. A separate supervisor lock prevents duplicate supervised workers. Runtime acceptance exposed a burst overflow at the original 1,000-event queue: the recorder now has a 20,000-event / 32 MiB bounded buffer, faster 2,000-event low-compression batches and an oldest-queued-event age health guard. Any loss still latches an unhealthy session; old gaps remain recorded and excluded.

Reports use Asia/Nicosia calendar days, including daylight-saving days. Entry stakes and fees belong to entry date; realized net results belong to official settlement date. UTC risk limits remain unchanged. Reports include skips, delayed fills, misses, reasons, coverage, health observations, restarts and storage growth. Full-day verification requires a completed day, at least 95% decision coverage, 1,000 health observations and no observed unhealthy states. Partial days and missing intervals do not pass. Files and dashboard only; no external notifications.

## Frozen prospective study

- Capture window: 14 October 00:00 UTC through 28 October 00:00 UTC, exclusive end.
- Training: first eight UTC days; independent probability calibration: next three; untouched evaluation: final three. Purge five minutes around phase boundaries.
- Gate: all 14 days complete, at least 1,000 resolved eligible contracts and 80% of 4,032 expected contracts observed. In practice the coverage gate requires 3,226 eligible resolved contracts. Each phase needs at least 100 observations; training and calibration each need at least 30 of each outcome.
- One first eligible fixed-180 decision per contract, including baseline skips. Decisions missing numeric features or executable quotes are explicitly excluded. Retain market and momentum benchmarks. Use only public officially resolved outcomes; no company research data or sealed labels.
- Two fixed numeric challengers: standardized logistic regression and shallow histogram gradient boosting. Independent sigmoid calibration on calibration days only. No hyperparameter search on the test days. Record dependencies, model hashes and plan hash.
- Save and hash held-out predictions before extracting held-out target labels. Report Brier, log loss, ten fixed reliability bins and paired day bootstrap with 2,000 resamples. Three held-out days limit inference; results do not certify a profitable edge.
- Delayed quote probes are collected for both sides, including baseline skips, without paper cash movements. Counterfactual replay uses observed top-20 depth after each delay, same fees, adverse-price limit, cash/exposure/loss gates. Unobservable liquidity is excluded and counted, never assumed filled. Gross realized loss uses UTC official settlement date. Report eventual hold-to-resolution net outcomes separately from predictions.
- A completed evaluation cannot automatically run again in the same study directory. No challenger replaces the baseline or places real orders. Further model changes require a new prospective test window.

The dedicated service installer creates only BTC paper and frozen-study units. All application code runs as the engineering user. It requires root solely for system-unit installation; existing shared services remain outside its scope. The training timer checks the gate daily at 08:05 Cyprus time and exits without fitting until eligible. The existing installed numeric-model interpreter is read-only; no packages or company datasets are modified.

## Ten-point handover

1. Scope: BTC paper supervision, monitoring, private reporting and gated numeric challengers.
2. Inputs: public reference ticks, official market metadata, observed books, immutable journal.
3. Registration: fixed dates, features, models and thresholds in training.py; hash emitted in reports.
4. Prediction timing: fixed 180-second cohort; delayed probes never enter features.
5. Outcome provenance: public explicit winning token only.
6. Benchmarks: frozen Brownian baseline, market midpoint and momentum.
7. Statistics: proper scores, reliability bins and 2,000 day resamples; limited test days acknowledged.
8. Execution: counterfactual depth replay, two latency arms, fees and risk limits; no real execution.
9. Validation: functional unit checks and runtime acceptance recorded separately; future gates remain pending.
10. Next gate: first completed healthy day, then the frozen study; root service activation remains separately evidenced.
