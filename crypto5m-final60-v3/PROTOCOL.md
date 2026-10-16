# Final-minute partial-TWAP study v3, amendment 16 October 2026

A new ledger and service. v1 and v2 are preserved; nothing is pooled. Everything in the v2 amendment and the v1 preregistration below applies unchanged except as stated here. Paper only.

Evidence: the v2 server preflight reproduced a crash. A fully empty Up book passes the v2 freshness rules, and the market-probability fallback succeeds, but the worker's per-second sampling diagnostics divided by zero computing book imbalance. v2 had fixed this division only in the forecast model.

Change: book imbalance in the worker's sampling diagnostics is recorded as null when the Up book's top five levels are empty. The unused inherited baseline forecast function now abstains on one-sided books instead of dividing by zero. An audit of every book read in the lane found no other unguarded empty-side access. A new test drives the real worker sampling and decision paths through all 16 combinations of empty and non-empty bids and asks on both outcomes. It reproduces the v2 crash and passes on v3.

No decision, model, risk or evaluation rule changes.

# Final-minute partial-TWAP study v2, amendment preregistered 16 October 2026

A new ledger and service. The v1 lane (never installed; candidate archived) is preserved. Everything in the v1 preregistration below applies unchanged except as stated here. Paper only.

Evidence from the v1 candidate:
- TWAP reconstruction matched the official Chainlink snapshot within 0.04 to 0.13 basis points at all 9 independent boundaries (median 0.086), against the preregistered 1 basis point limit. The first-100 check is not yet due.
- The candidate produced zero final-minute forecasts. 180 of about 220 final-minute decisions failed on the inherited two-sided book requirement. In the final minute the losing outcome's book is routinely one-sided or empty, because nobody bids for a token about to pay zero.
- The runner ended the process at about 895 s (exit -9) before clean shutdown could be confirmed.

Change 1, one-sided books.
- Both outcome books must still be fresh (identity, stream liveness or REST age, venue lag), and neither may be crossed or locked when both its sides are quoted.
- An empty side no longer blocks a decision.
- A directional buy requires asks on the outcome being bought. The spread limit applies to that outcome whenever it has bids.
- Delayed fills apply the same rule to the fresh REST book of the bought outcome.
- The inherited two-sided rule is unchanged wherever it is still used.

Change 2, market-implied probability, in this order:
1. the normalized midpoints of both outcomes when both are two-sided
2. otherwise the Up midpoint
3. otherwise one minus the Down midpoint
4. otherwise the normalized best asks
5. otherwise unavailable, and the decision abstains

The method used is recorded with every observation. The report scores model against market on identical observations as before; results can additionally be split by method.

Change 3, robustness. Book imbalance is defined as 0 when the Up book's top five levels are empty, and the forecast records up_book_empty. Previously this case divided by zero.

Operations. The candidate must run under a runner whose own time limit is at least 1,200 s for --seconds 900, so that shutdown and the capture queue drain complete. A run ended by the runner does not count.

All other rules are unchanged: the model, decision window, edge threshold, caps, loss controls, reconstruction check, evaluation plan and gates.

# Final-minute partial-TWAP study v1, preregistered 16 October 2026

A new research lane, not a version of the crypto5m baseline study. It has its own ledger, service and evaluation. It reuses the crypto5m v5 infrastructure unchanged unless stated here: transport, in-place book reconstruction, crossing grace, REST rule refresh, Chainlink public reference adapter, exact opening anchor, ledger, delayed fills, settlement, loss controls, capture and reporting. Paper only. No live execution, credentials, signer, account actions, paid calls or automatic promotion. The v5 candidate, v2 service, earlier archives and v1.1 are untouched, and nothing is pooled across lanes.

## Motivation and evidence

These markets settle Up when the Chainlink 60-second TWAP over the final minute is at least the TWAP at the window start. Inside the final minute part of that average is already realized, so the outcome is more knowable than spot price alone suggests. Hypothesis: the market underprices this partially locked outcome.

Prior evidence is public and anecdotal, not ours. One public Polymarket account (NIULAI4) shows about 121.5K USD PnL on 3.9M USD volume across about 10,700 markets since June 2026. In five BTC 5-minute markets on 16 October its trades landed 60 to 27 seconds before window end. In a 50-position sample from 23 September it bought sides priced at 0.75 or more 40 times and won 39 (about +14% on cost); its 10 cheaper buys won once. That sample is small, from one day and selected after the fact. It motivates this test; it is not evidence for our model.

## Model, fixed before data

Let O be the exact Chainlink 60-second TWAP at window start (the existing anchor rule, no substitution). Let E be the window end, r = E - t the seconds remaining with 0 < r <= 60, and k = 60 - r the elapsed part of the averaging window.

Realized part: the time-weighted average of the public Chainlink raw points over (E - 60, t], treating each point as a step held until the next one. It is usable only if a point exists at or before E - 60 and no step in the interval, including the final step to t, relies on a point more than 3 seconds old. Otherwise the decision abstains.

Remaining part: under arithmetic Brownian motion from the latest raw price S with per-second volatility sigma (estimated exactly as in the baseline from the last 180 seconds of raw points), the mean of the future path over the remaining r seconds has mean S and variance sigma^2 r / 3.

Final average A = (k * realized + r * future) / 60. So A is normal with mean (k * realized + r * S) / 60 and standard deviation sigma * r^1.5 / (60 * sqrt(3)). P(Up) = Phi((mean - O) / sd), clamped to [0.01, 0.99]. At r = 60 this equals the baseline model's sigma^2 (r - 40) variance, so the two models join continuously. A shadow forecast with sigma multiplied by 1.5 is recorded for every decision as a fat-tail robustness check. It is never traded.

Features recorded: normalized distance z, r / 60, k / 60 and book imbalance. Model version string: final-minute-partial-twap.v1.

## Reconstruction validation

The realized part relies on our reconstruction of Chainlink's TWAP. At every window start and end where the official 60-second TWAP snapshot and enough raw points exist, the study records the reconstructed value, the official value, the difference in basis points and the raw-point coverage. This is a primary diagnostic. If the median absolute reconstruction error over the first 100 comparisons exceeds 1 basis point, the model's premise is unreliable, and that finding is reported before any profit result.

## Decisions and execution

- Decisions run only inside the final minute, every 2 seconds, while 12 <= r <= 58. Outside the final minute, market observations are recorded every 15 seconds for calibration only, with no model forecast and no entries.
- Directional strategy only. Paired is disabled.
- Edge rule unchanged: model probability minus the all-in unit cost (price, taker fee, 0.003 additional cost per share) must be at least 0.05.
- One entry per asset and window, at most 25 cost per position, 75 per window across assets.
- Delayed fill after 2 seconds against a fresh REST book, maximum lateness 3 seconds. Fills are rejected if fewer than 6 seconds remain.
- Market terms are rediscovered every 10 seconds so that the 30-second freshness rule holds inside the final minute.
- Loss controls unchanged: daily worst-case bound 100, daily realized-loss halt 100 with next-day resume, cumulative stop 500.

## Evaluation, fixed in advance

Primary outcomes, scored on identical observations: Brier score of the model against the market-implied probability, by asset and by remaining-time band (12 to 30 seconds, 30 to 58 seconds), plus calibration bins.

Secondary outcomes:
- net settled paper PnL after fees and additional costs
- the share of PnL from the five largest winning markets
- the zero-payout stress test
- the shadow (1.5 sigma) Brier score
- fill rate, and the rejection reasons for unfilled attempts

The 7/3/4/28-day chronology from this lane's own genesis applies. Final-period scores are withheld until day 42. A favourable result in the first days is not evidence of an edge. Tail risk is explicit: buying near-certain outcomes loses about the full cost when wrong, so the report states the largest single loss next to the average win.

Not claimed: queue position, speed parity with professional bots, or real-fill quality. The delayed-fill simulation and the 2-second cadence are conservative relative to the trader who motivated this test.

## Acceptance gates before persistent installation

All of the following must hold:
- all tests and the synthetic lifecycle pass on the server
- a bounded candidate of at least 15 minutes (at least three final minutes per asset) on a separate state shows the reference connected
- per asset: book disconnects at most 5, stream lag median at most 1 second and above 3 seconds for at most 5% of the time
- final-minute forecasts on at least two assets
- at least three reconstruction comparisons recorded
- intact ledger and capture
- worker CPU recorded

A fill is not required and must not be forced.

The inherited protocol of the crypto5m study (v5 and earlier) follows for background. Where it conflicts with this document, this document governs.

# Version 5 preregistered crossing-tolerance extension (16 October 2026)

Distinct study and ledger. Preserve v4 and v3 candidate archives, v2 (installed and running) and v1.1. No pooling, no reset history. Live execution, credentials, signer access, provider spend and automatic promotion remain disabled. The v4 extension below applies unchanged except where stated.

Evidence. The v4 candidate passed every lag and CPU gate (median stream lag about 0.042 s on all assets, 0% of time above 3 s, worker CPU median 14.6% of one core) and produced three natural paper fills. ETH and SOL had zero disconnects. It failed only on BTC: 9 disconnects against a limit of 5, of which 8 were crossed_book resyncs and 1 a connection error.

Change 1, crossing grace. A delta batch that leaves an outcome's reconstructed book crossed (best bid above best ask) no longer forces an immediate resync. Working hypothesis: on the busiest market, a match can publish the aggressive order's level an instant before the removal of the level it matched against. The alternative, a missed message, cannot be ruled out because the venue provides no sequence numbers. Rule: the crossed state is retained for at most crossed_grace_seconds (2 s, pinned in config, at most 5). It ends when a later delta uncrosses that side or a fresh full snapshot replaces it. If it persists beyond the grace, the stream resyncs as before ('persistent_crossed_book'). The check runs on every event and every loop tick, so it fires even without further traffic. While crossed, a snapshot cannot be built, so decisions and fills abstain. A crossed or locked book was already never tradeable. A crossed full snapshot from the venue is still fatal. Status records crossing episodes, resolutions, the longest resolved duration, the most events inside one episode and any side crossed right now, so the candidate shows which hypothesis holds.

Change 2, decision label. A second decision for an asset, window and strategy that already has a position is recorded as 'already_entered_this_window' before planning, instead of surfacing from the ledger as 'invalid_reservation'. The one-entry rule and all ledger checks are unchanged.

Acceptance gates are unchanged from v4. In addition, record per asset: crossing_episodes, crossings_resolved, crossing_max_seconds_resolved and crossing_max_events. If persistent_crossed_book still appears, that is evidence of missed messages and must be reported, not tuned.

The following v4 protocol (with v3, v2 and v1.1 below it) is retained. Where it conflicts with this extension, this extension governs.

# Version 4 preregistered throughput extension (16 October 2026)

Distinct study and ledger. Preserve v3 (never installed; failed candidate archived), v2 (installed and running) and v1.1. No pooling, no reset history. Live execution, credentials, signer access, provider spend and automatic promotion remain disabled. Everything in the v3 extension below applies unchanged except where stated here.

Evidence for this version. The v3 server candidate failed on stream lag (medians 33 to 43 s, maxima up to 170 s on all three assets). A same-server diagnostic then showed an independent minimal BTC consumer staying current (median 41 to 43 ms, p95 113 to 167 ms) while v3, running alongside it, reported BTC lag of 21 s median and 87 s maximum and used about 105% of one core on an 8-core server with whole-server CPU near 25%. The bottleneck is v3's own single-process book path, not the venue and not the machine. A local benchmark on identical synthetic streams measured v3 at about 690 microseconds per event and v4 at about 20.

Change 1, in-place book updates. Each outcome side is held as a price-to-size map. A delta touches only its changed levels; per-level validation (price range, non-negative size, exact tick) runs on each touched level, and the crossed-book check runs on the batch's final state as before. Sorting, full validation through the v2 book constructor and the snapshot hash are computed only when a consumer requests a snapshot. Snapshot contents, identity hash and all downstream decision, fill and ledger rules are unchanged; a test proves equality with a naive full reconstruction over 2,000 random multi-level events.

Change 2, rule refresh on connection. Before every stream (re)connection the per-outcome tick and minimum size are re-read from the public CLOB REST book for both tokens, with identity checks. Inference behind this: v3's repeated invalid_book_level resyncs on ETH and SOL fit a tick that changed while the stream was disconnected, so each reconnect re-applied a stale tick and failed again; the diagnostic's REST-tick probe found no off-tick prices. A delayed fill still rejects any tick or minimum change relative to its reservation.

Change 3, diagnostics. Every invalid level records outcome, side, price, size, tick in force and the reason (range or off_tick). Status reports frames, cumulative and maximum per-frame processing time, and rule refresh counts and errors.

Change 4, service limit. CPUQuota rises from 25% to 100% of one core. The v3 candidate ran outside systemd; at 25% the installed unit would have starved further. Expected v4 usage is a small fraction of one core.

Acceptance gates before persistent installation (unchanged in kind from v3): all tests and the synthetic lifecycle pass on the server; a bounded candidate of at least ten minutes on a separate candidate state shows reference connected; per-asset book disconnects at most 5; v4 worker stream_lag median at most 1 s and above 3 s for at most 5% of measured time per asset; forecasts on at least two assets; intact ledger and capture; worker CPU recorded. A fill is not required and must not be forced.

The following v3 protocol (with v2 and v1.1 below it) is retained. Where it conflicts with this extension, this extension governs.

# Version 3 preregistered operational extension (16 October 2026)

This is a distinct study and ledger, not a continuation of v2 or v1.1. Preserve the v2 source, service, ledger and captures; no pooled results, no reset history. Live execution, account credentials, signer access, provider spend and automatic model promotion remain disabled. Model, strategy thresholds, costs, caps, fees, settlement and chronology (7/3/4/28 days from this version's own genesis) are unchanged from v2 except where stated below.

Motivation. v2's bounded and installed runs showed the book stream reconnecting roughly every eight seconds on BTC, which made a delayed paper fill (which requires an unchanged stream generation) structurally improbable. v2 also latched a permanent halt on lower-bound equity, which counts every unsettled filled position as lost, so ordinary open exposure could end the trading track.

Change 1, book stream reconstruction. Delta and snapshot timestamps are no longer age-checked at ingestion. An ordered delta that arrives late is applied, because skipping it would corrupt the book; freshness is judged at decision and fill time. A delta older than the current snapshot of its outcome is already reflected in that snapshot and is skipped (counted as superseded). A snapshot older than the current book is ignored (counted). Genuine inconsistency still clears both books and reconnects: deltas out of order relative to applied deltas, crossed or invalid levels, unknown assets, timestamps more than one second in the future, tick changes and market resolution. Reconnect reasons are counted per reason in status.

Change 2, liveness freshness. A stream book is usable when (a) every frame on the unbroken connection, including the PONG reply to a PING sent every 1.5 seconds, proves the connection current within 3 seconds; (b) the venue lag of the most recent timestamped event (receive minus source) is between -1 and 3 seconds; and (c) nothing is from the future. This rests on one stated assumption: the venue delivers messages on one connection in order, so a current connection with no deltas means an unchanged book. Locked or crossed books are never tradeable. REST books used for delayed fills keep the strict v2 age rules unchanged.

Change 3, loss controls. The pre-trade worst-case bound is unchanged: today's lower-bound loss plus open reservations plus the new budget must not exceed 100. The halt now uses realized losses: cost-basis equity marks unsettled fills at cost and moves only on official settlement. Realized loss of at least 100 within a UTC day halts new entries for the rest of that day; entries resume at the next UTC day. Cumulative realized loss of at least 500 from starting cash latches a permanent halt that requires a new reviewed version. Losses settling today on yesterday's positions count today. Both thresholds are owner policy, recorded in config and pinned at genesis.

Change 4, scheduling. A pending delayed fill runs first in each loop, and discovery and resolution network calls are deferred while any fill is due within six seconds. Entries close 70 seconds before window end, so deferral never overlaps the next window's discovery. Fill timing rules are unchanged.

Change 5, evaluation instruments. Each forecast observation records the maximum receive and source time of every input it used. The report adds a model-versus-market comparison on identical observations: for each window, the first observation that carries both a market probability and a model forecast. This is the primary edge test. A new offline command, training.py, builds train and calibration rows from the index read-only and runs the existing chronological fit; it never reads selection or final targets, writes nothing, and the service never loads its output.

Acceptance gates before persistent installation: all synthetic tests and the synthetic lifecycle pass on the server; a bounded candidate run of at least ten minutes on a separate candidate state shows connected reference data, per-asset book reconnects materially below v2's installed rate, forecasts across assets and an intact ledger. A prospective fill is not required and must not be forced. Candidate data is archived separately and never pooled.

The following v2 protocol is retained as background. Where it conflicts with this extension, this extension governs.

# Version 2 preregistered public-reference extension — 16 October 2026

This is a distinct study and ledger, not a continuation or repair of v1.1's experiment. Preserve v1.1 source, service and captures. No pooled results or reset history. Live execution, account credentials, signer access, provider spend and automatic model promotion remain disabled.

Change: consume public legacy RTDS Chainlink raw prices and sixty-second TWAP snapshots from ws-live-data.polymarket.com. The official migration guide still documents those topics, but the endpoint is retiring. A bounded server probe on 16 October verified six snapshot subscriptions and repeated fresh BTC snapshots. No push updates were observed. Request all six snapshots once per second on one connection; send PING every three seconds. Preserve exact decimal strings (legacy TWAP full_accuracy_value is E18). This is a provisional legacy dependency, not a claim of long-term availability. No credential-based fallback is enabled.

Only explicit btc/usd, eth/usd and sol/usd mappings are accepted. Source and receive timestamps are retained without backdating. Require the exact TWAP timestamp at market start, no nearest-point substitution. Keep first receive times when merging overlapping snapshots; changed values at an existing timestamp invalidate the feed. A transport reconnect clears raw history and requires warmup again. Late individual snapshots are rejected without clearing other assets; each decision still checks its own source/receive ages and gaps. Revisions, invalid source and malformed timestamps remain hard failures. Model guards still require ninety seconds of raw history, maximum five-second source gaps, three-second freshness, and abstain inside the final averaging minute. The adapter never computes an opening price from exchange data. Missing data causes abstention. Official CLOB winners settle the virtual ledger independently.

Empty books are legitimate non-executable collection states. Retain them so subsequent deltas can restore liquidity without reconnect loops. Reject empty, stale or crossed books at every decision and delayed fill. Crossed books still trigger resynchronization. Risk caps and fees remain unchanged. Model forecasts are uncalibrated paper baselines; neither strategy is asserted profitable.

The 7/3/4/28-day chronology starts at this version's own ledger genesis. Bounded operational verification is prospective within this study and does not establish calibration, an edge, four weeks of validation, or actual venue fills. No forced trade is permitted merely to obtain a test result. Synthetic lifecycle tests are clearly separate from prospective data.

Official sources checked 16 October 2026:
- https://docs.polymarket.com/migrate/rtds-to-polybolt
- https://docs.polymarket.com/market-data/realtime-data
- https://docs.polymarket.com/api-reference/wss/polybolt

The following inherited v1.1 protocol is retained as background. Where it says the reference adapter is unavailable, this v2 extension supersedes it; every other guard remains applicable.

# Frozen multi-asset five-minute study v1.1

Preregistered before operational collection. New BTC/ETH/SOL paper study, separate from every existing ledger. All settings in config.json are experiment defaults, not optimized. No live client, signer, real budget changes, paid calls, model promotion, Kelly or passive fills.

Canonical source repository: Oli-Vivameda/vivameda-prediction-markets, crypto5m/. The intelligence-stack repository receives only a routing/verification checkpoint. Reuse: existing public RFC6455 transport and compressed append-only Capture implementation extracted from the deployed BTC paper collector; market identity/depth/fee and durable intent principles carry forward. New ledger is necessary for correlated assets, shared risk and sequential pairs. Old workers/journals stay untouched.

Discovery uses fixed Gamma slug and CLOB GET endpoints. Require exact per-asset description, event/outcome identity, five-minute UTC window, Chainlink 60-second TWAP, tie Up, fallback none, non-negative-risk binary market, known tick/minimum/fee schedule. Preserve full raw response, retrieval time and normalized interpretation. Opening reference must be that contractual stream's TWAP at window start; spot or unofficial frontend openPrice never substitutes. Event end, observed closure, explicit outcome confirmation and simulated payout availability differ.

CURRENT INPUT GATE: official reference streaming uses authenticated PolyBolt. This release reads no account credentials and connects no contractual reference adapter. It collects public books and supporting Binance aggregate-trade samples. Opening reference, contractual reference and normalized distance are explicitly missing. Operational predictions and both strategies abstain. Stage is "collecting data—no validated edge". No API key or signer read is implied or required for this collector. Connecting a new verified read-only reference bridge requires a new reviewed version and experiment; no silent promotion of this frozen study.

Data: public book streams maintain both outcomes; supporting exchange feed is sampled at one-second resolution. Compressed hash-chained state envelopes preserve source/local receive times, depth limited to best 20 levels (conservative only), gaps, reconnect generations, diagnostic supporting volatility/returns, decisions and outcomes. These are states and exact decision inputs, not a complete tick tape. Raw feeds have no certified venue sequence, and this limitation is explicitly attached to simulated fills. A disconnect invalidates pending fills. No missing point is interpolated. Existing external storage is used with a pinned device; no root fallback. Capture cap 8 GiB, index/ledger cap 1 GiB and 5 GiB free reserve stop new entries. No history is deleted or reset. Four-week coverage must be measured; storage limits may require extension or a separately reviewed archive plan.

Model: transparent arithmetic Brownian final-60-second-average baseline. Before final averaging begins, variance of terminal average conditional on current raw reference is sigma^2*(remaining-40). Four recorded inputs are normalized distance, time remaining, normalized momentum and book imbalance. Distance/volatility baseline is distinct from the optional asset-specific logistic interface. The latter standardizes only on training data and fits logistic coefficients on earlier windows, then Platt calibration on later calibration rows. Minimum 300 train and 100 calibration windows per asset, both classes, and actual label availability before cutoff. All rows of a UTC five-minute window across assets share a split; first partial window excluded. Seven train days, three calibration days, four selection days; then 28 untouched final days. Final metrics withheld until day 42. No scheduled fit or automatic adoption exists. Final-period safety monitoring may observe cash/exposure solely to enforce loss limits; no strategy changes based on it. Existing sealed company/BTC slices are never read.

Directional strategy: compare predicted payout probability against displayed depth-weighted all-in cost, including market taker fee and additional 0.003/share cost; require 0.05/share estimated edge. Never add spread again. Up/Down are token BUYs, not shorts. Fixed at most 25 cash cost per position; reduce quantity to available captured depth; minimums still apply. One entry/asset/window/strategy, no retry or averaging. Shared combined committed purchase cost at most 75 per five-minute window, across both strategies. No martingale. Equity values unresolved positions and unpaid receipts at zero. Daily 100 loss budget includes worst-case pending reservations, so new orders cannot overshoot the bound. At observed threshold, latch halt until a documented review/new experiment; no midnight auto-resume after a halt.

Paired strategy: own tag/accounting, same shared ledger. Equal planned quantities in one binary market. Both legs must have depth; combined initial all-in cost <=0.98/share-pair. At most 25 total reserved cash for a pair. Simulate Up first after two seconds; Down targets actual first-leg shares after one more second. Each leg may partially fill. Abort unfilled first leg. No repeat attempts; a partial/missed second leg leaves unmatched shares bounded by the reserved 25, held to official settlement. No unwind in v1, so unwind-loss column is explicitly zero, not estimated. Incomplete pairs are never called guaranteed profit.

Fills: durable reserve/intent before the delayed quote; new metadata plus a fresh REST book after due time; stream must also be healthy with unchanged reconnect generation. Source timestamp after due, receive/source age <=3 seconds, max lateness 3 seconds, >70 seconds remaining. Recompute fees and exact consumed depth; reject rule/tick/minimum/fee changes and adverse price/unit cost. Conservative fee rounding upward to five decimals; shares downward to six. No speculative rebates. Across strategies, previously consumed shares at each market/token/price stay deducted for that entire window, even if the displayed snapshot refreshes: conservative prevention of liquidity reuse. Explicit flags disclose unobservable venue sequence/queue/impact. Passive execution off.

Settlement: only explicit CLOB closed/winning outcome with exact token map. Preserve raw proof and first observed confirmation time. Capital remains unavailable until confirmation plus configured 60-second paper redemption delay. This is a simulation assumption, not proof of real cash transfer or an actual redemption. Losing tokens pay zero. Restart cancels unfilled remainder exactly once, retains actual simulated debits/inventory and later credits exactly once; no backfilled fill. Any changed code/config pin or broken hash chain refuses continuation.

Reporting: coverage and disconnects, all decision/rejection reasons, fills/partials, costs, net settled PnL, lower-bound-equity drawdown/capital utilization, Brier/calibration versus market and baseline where available, asset/strategy/time/price groups, remove top five positive markets, extra-cost and zero-payout stress. Alternative-latency/fill sensitivity remains explicitly not estimable without suitable alternate-delay replay data. UTC-day block bootstrap (2000 resamples), withheld with fewer than ten blocks. No tick-level independence claim, win-rate-only conclusion, supported edge, or real execution guarantee. Four weeks is a minimum evaluation duration, not a pass criterion.

Documentation verified 2026-10-16: https://docs.polymarket.com/market-data/realtime-data ; https://docs.polymarket.com/migrate/rtds-to-polybolt ; https://docs.polymarket.com/market-data/market-details ; https://docs.polymarket.com/trading/fees ; https://docs.polymarket.com/concepts/resolution ; https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md .

Engineering revision before persistent operation: the initial v1 candidate had a separate 45-second, zero-position collection run. Its source bundle and data are retained. Version v1.1 validates complete batched deltas atomically, uses verified per-outcome ticks rather than equating them to the Gamma advertised tick, resubscribes for full snapshots after tick changes, stamps decisions after snapshot copies, and records exact decision-input packet hashes. Strategy/risk thresholds and costs are unchanged. New v1.1 ledger/directory; no reset or pooling of prior history.
