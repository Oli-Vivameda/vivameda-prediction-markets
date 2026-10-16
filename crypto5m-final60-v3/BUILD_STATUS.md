# Build status: final-minute partial-TWAP v3

Source commit 5cd756b0f999bf93f417667b397ed5ce7240ead6; reviewed bundle 35483aa13336bad9f3d9c0c1635bfa55b68541e6a45545ff753fab5a9146c91c.
Verified on the server on 16 October 2026. All 24 pinned runtime files remain unchanged.

Server verification passed: exact bundle, 121 tests, synthetic lifecycle and the independent fresh empty-Up-book reproduction (null diagnostics imbalance; Down midpoint complement; no network or study state).

The detached candidate passed after 900.763 seconds with exit 0 under a 1,500-second runner limit. Three final-minute windows per asset were observed, forecasts occurred on all three assets, the ledger reopened, and all 5,317 capture records verified and matched the enqueue count. CPU: 179 five-second samples, median 23.583% and max 41.971% of one core; server has 8 cores. No worker exceptions.

BTC lag median/p95/max: 0.042447 / 0.075474 / 1.746900 s; 2 connection disconnects.
ETH: 0.042294 / 0.068875 / 1.481257 s; 0 disconnects.
SOL: 0.042355 / 0.065900 / 1.470559 s; 0 disconnects.
Time above 3 s was 0% of measured time for each asset. Missing/unknown intervals are recorded separately in ACCEPTANCE.json. Counters are aggregated across all four market feed instances, not only the last status snapshot. The earlier baseline v5 600-second candidate had disconnects 3/0/0 and lag medians about 0.042 s; durations and traffic differ.

Final-minute forecasts: BTC 25, ETH 27, SOL 12. Forecasts occurred in two windows per asset; three final-minute windows were observed per asset. Four natural reservations, one paper fill, three no_post_delay_liquidity rejections. Realized losses 0; no halts. Candidate virtual ending cash 10004.32866656; net settled paper PnL +4.32866656 is early operational evidence only.

TWAP: 18 usable comparisons at 9 independent asset/boundary pairs, median absolute error 0.082888 bp, max 0.185142 bp. Three initial windows unusable: no_point_at_averaging_start. The first-100 gate is not yet due.

Direct distinct condition counts: observations 12, markets 12, outcomes 6; 345 observation rows. Eligible priced conditions: 9. The inherited report incorrectly says 18 priced markets because a variable is reused for reconstruction errors. Direct verified queries provide the correct counts; pinned code was not edited. The three matched settled observations have model Brier 0.078334 versus market 0.049842 (difference +0.028492); shadow 0.106219. This is not an edge claim.

Other limitations: 139 no_market_quote skips; natural market_probability_method counts both_midpoints 203, not recorded 142. No fallback method occurred prospectively, although synthetic coverage and preflight pass. The RUNBOOK example still says 600 seconds; HANDOVER authority requires and received 900. The public legacy reference adapter is retiring.

Candidate archived separately. Root installation command and an independent 24-file, two-minute health checker are prepared. Persistent installation and installed health remain pending; no privilege escalation was attempted. v2 remains active with zero restarts. All other installed services, states, archives and real budgets were left unchanged. No signer, credentials, account actions, live execution or paid calls.

Next gate: owner root installation to a NEW final state and independent two-minute health check, then the first 100 TWAP comparisons (median absolute error at most 1 bp) before profit claims and the lane's separate 7/3/4/28-day chronology.
