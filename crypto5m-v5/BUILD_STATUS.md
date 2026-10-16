# Build status: v5

Source commit 0446998e2a4199b85337590514b333de8ab6d584; bundle 9bcc18aace069035f5c3e9debad7c98af947117cd6ad52d70023f40bcdec79eb.

Server verification on 16 October 2026: exact bundle and all 21 source hashes matched; 90 tests OK; synthetic lifecycle passed. The new 600-second candidate completed normally (600.891 seconds including setup/shutdown), on device 2064. All candidate gates passed. The candidate was archived separately and will never be reused as final state.

Owner installation completed 16 October 2026 at 17:38:16 UTC. The health check passed at 17:40:24 UTC (service age 128 seconds): active, enabled, zero restarts; all 21 runtime hashes matched; fresh captures, connected reference and usable books; virtual cash 10,000. An independent server read reconfirmed the runtime hashes, correct device 2064 and both v5 and v2 active/enabled with zero restarts. No existing service was changed.

| Asset | v5 lag median / p95 / max (s) | Time above 3 s | Disconnects v5 / v4 |
|---|---|---|---|
| BTC | 0.042482 / 0.052110 / 0.239733 | 0% | 3 / 9 |
| ETH | 0.042064 / 0.054131 / 1.374785 | 0% | 0 / 0 |
| SOL | 0.041008 / 0.052569 / 0.132646 | 0% | 0 / 0 |

| Asset | Crossing episodes / resolved | Longest resolved (s) | Maximum events | Persistent-crossing resyncs |
|---|---|---|---|---|
| BTC | 64 / 64 | 0.01558685302734375 | 2 | 0 |
| ETH | 2 / 2 | 0.0001304149627685547 | 1 | 0 |
| SOL | 0 / 0 | 0 | 0 | 0 |

These observed short resolved crossings support the publication-order hypothesis; they do not prove that the stream never misses messages. BTC resync reasons were ConnectionError: 3, with no more detailed closure reason available in this version. ETH and SOL reasons were empty. No PING rejection was specifically identified. Every reported last_invalid_level was null. Rule refresh counts BTC/ETH/SOL: 6/5/4; errors 0/0/0. All crossing states were clear at completion. No code or tolerance was changed.

CPU: 119 five-second interval samples, median 25.5419% and maximum 46.6987% of one core, on an 8-core server. No CPU stop. CPU was higher than v4's 14.6% median but remained well below one core; market traffic differed between the runs.

Reference connected, error null, disconnects 0. Ledger reopened cleanly; capture verified 3,194 records with 0 dropped; worker log empty. Operational forecasts BTC12/ETH12/SOL12; 41 observations per asset. Reservations5, attempts5, natural paper fills2. Rejected attempts: no_post_delay_liquidity2, fill_math_or_cost_limit1. All decision reasons are in ACCEPTANCE.json, including already_entered_this_window22 and no invalid_reservation.

Virtual cash 9,950.50730743, unsettled purchase cost 49.49269257, cost-basis equity 10,000. Realized daily/cumulative losses 0, no daily or permanent halts. Candidate positions stay archived as recorded; no settlement was invented and no trade was forced. No forecast-quality, edge or live-fill claim is established.

Lag quantiles use approximately one-second captured worker states. Above-threshold fractions are time weighted with intervals capped at ten seconds; null/gap time is excluded and separately reported. Counters aggregate observed maxima across feed instances and market rotations. Prior v4 figures came from the already reported results, without accessing its archive.

All 21 pinned source files remained unchanged. v2 state, v4/v3 candidate archives, lag diagnostic archive and v1.1 were untouched. Paper only; no signer, credentials, account actions, paid calls, real budget changes or live orders. Inherited RUNBOOK venue-lag and rollback-v3 lines remain inconsistent with authoritative HANDOVER; pinned files were not edited.

Next gate: 48 hours of parallel paper observation, starting at the passed health check on 16 October 2026 at 17:40:24 UTC (20:40:24 Cyprus), with earliest owner review on 18 October 2026 at 17:40:24 UTC (20:40:24 Cyprus). Leave v2 running until the owner decides. No automatic promotion, v2 shutdown or live execution is authorized.

Installation health is separate from the candidate figures above. At the two-minute health check, all three current book feeds had zero disconnects and roughly 41–44 ms stream lag, no invalid levels, no resync reasons and no rule-refresh errors. BTC had eight short crossing episodes, all resolved, at the later independent read. No installed realized loss or halt was observed. Full installed generic figures are in ACCEPTANCE.json. The pre-install candidate archive remains separate and was not reused or altered during post-install verification.
