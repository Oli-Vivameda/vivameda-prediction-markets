# Build status: final-minute partial-TWAP v1

Source commit: 159e2bcd1dfeb21f6944a610abbaa0df4c9dbdcd.
Bundle: 45fe476c02760baf6204a9b922987bad3229a670354142a94383600852b04bfe.
Fresh main checkout 27a0418772b87f0694ccd6a67e3e0c428233789a had the identical lane tree, 6c46ea03f92d694b91193f9ce24d8a2c133f458e. All 22 pinned source hashes matched and remained unchanged.

Server tests on 16 October 2026: 108 tests OK; synthetic lifecycle passed, including final-minute forecast, reservation, delayed fill and exactly-once settlement.

**Candidate failed; not installed.** Two gates failed: no final-minute forecasts on any asset, and no proven clean completion of the required 900-second worker. The engineering wrapper returned interrupted/exit -9 at about 900.039 seconds of process time; the last saved status covered 895.179 seconds. No worker lock remained. This is consistent with a wrapper duration limit, but the exact termination cause was not independently established. Original metadata, partial samples and databases were preserved and archived separately. No retry, backfill, history reset or forced trade.

Three final-minute windows per asset were observed. Statistics below cover the interrupted run, not a certified full 900-second candidate.

| Asset | Lag median / p95 / max (s) | Measured time above 3 s | Observed disconnects |
|---|---|---|---|
| BTC | 0.042340 / 0.066143 / 1.357571 | 0% | 0 |
| ETH | 0.042206 / 0.072363 / 1.412526 | 0% | 0 |
| SOL | 0.042079 / 0.067149 / 2.026996 | 0% | 0 |

The previously reported parent v5 candidate had 3/0/0 disconnects over 600 seconds. No old state or archive was accessed for that comparison. Lag quantiles use approximately one-second captured worker states. Above-threshold fractions weight time until the next sample, cap intervals at ten seconds and exclude separately reported null/gap time. Counters aggregate observed maxima across feed instances and rotations.

CPU: 179 five-second samples; median 23.7457%, maximum 39.6901% of one core, eight logical cores. No CPU stop. Reference connected, error null, disconnects zero at last status. The persisted ledger reopened and the committed capture chain verified 5,128 records; last status reported zero dropped. Worker log empty. Clean finalization and complete queue drain remain unproven.

Reconstruction: 18 comparisons, nine unique asset/boundary combinations, zero unusable records/windows; median absolute error 0.08641022697 bp, maximum 0.13135720550 bp. Close/open records sharing a boundary are duplicate measurements, not independent observations. The first-100 comparison check is not due. Every raw comparison is preserved on the server; only generic results are published.

No final-minute forecasts, reservations, attempts or fills. Overall directional skip counts: empty book 180; outside final minute 122; reference_gap_or_stale 27; reference_stale 9; spread_limit 1; waiting for full stream books 6. Final-minute-only skips by asset are in ACCEPTANCE.json. Guards were not weakened. Nine official outcomes were recorded, but matched model/market sample count is zero and Brier scores/difference are null. No edge claim.

Virtual cash 10,000; spent, open cost and reserved cash zero. Realized daily/cumulative losses zero; no halts. Crossing episodes/resolved: BTC 66/66 (maximum 0.0089736 s, four events), ETH 0/0, SOL 4/4 (maximum 0.0001304 s, one event). No persistent crossings. Resync reasons empty and last_invalid_level null on every asset. Rule refreshes BTC/ETH/SOL: 6/5/5; errors 0/0/0. Full counters are in ACCEPTANCE.json.

Reporting caveats: report.py reuses its priced-market dictionary variable for reconstruction errors, reporting 18 priced markets instead of the independently counted nine eligible markets. Its reconstruction block omits maximum error, which was calculated externally. No source edit was needed to evaluate the listed gates. Any reporting fix requires a new reviewed version.

HANDOVER governed over stale RUNBOOK lines concerning 600 seconds, venue-lag attribution and rollback naming v3. No other study state, archive, pending installation or service was accessed or changed. v2 remained active with zero restarts. Paper only: no signer, credentials, account actions, live execution, paid calls or real budget changes.

Next gate: stop and report the failed candidate. Investigate zero forecasts without weakening guards, and use an execution method that permits 900 seconds plus startup/shutdown overhead for a new candidate. Any required code fix must be a new reviewed version. Installation and health checks were not attempted. Data accumulation under the 7/3/4/28-day chronology and the first-100 reconstruction check remain future gates after successful acceptance and installation.
