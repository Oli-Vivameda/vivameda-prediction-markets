# Build status: v4

Source commit b2610e8e91c7d9d9f2da4d4ae78305fa9eaff384; bundle 275b728b1f972f2b6cba5b37dabe443d4c9e76e0f2aef47a6b1a24a852e4e7f3.

Server verification on 16 October 2026: exact bundle matched, all 81 tests passed, and the synthetic lifecycle passed. The source checkout remained clean and all 20 pinned runtime files remained unchanged.

The new, isolated 600-second paper candidate completed normally (600.875 seconds including setup and shutdown) on device 2064, then was archived separately. **Acceptance failed: BTC had 9 disconnects, above the maximum of 5. No installation was attempted; the installed-service health check and 48-hour observation gate have not started.**

| Asset | Lag median / p95 / max (s) | Time above 3 s | Disconnects | Prior v3 median / max (s); disconnects |
|---|---|---|---|---|
| BTC | 0.042198 / 0.065437 / 0.566882 | 0% | 9 | 38.147 / 120.864; 5 |
| ETH | 0.041894 / 0.061333 / 1.411258 | 0% | 0 | 42.577 / 169.763; 13 |
| SOL | 0.041940 / 0.063758 / 0.222791 | 0% | 0 | 32.741 / 134.848; 12 |

Lag quantiles use approximately one-second captured worker feed states. Above-threshold fractions are time weighted with intervals capped at ten seconds; null/gap time is excluded and reported separately in ACCEPTANCE.json. Counters aggregate observed maxima across feed instances and market rotations, rather than reading only the last market. Prior v3 figures are the already reported candidate results; its p95 was unavailable. No protected archive was accessed.

CPU: 119 five-second interval samples; median 14.5667%, maximum 39.9109% of one core, on an 8-core server. No CPU stop. Reference error null, disconnects 0. Ledger reopened cleanly; capture verified 3,164 records, dropped 0; worker log empty.

Operational forecast counts: BTC 11, ETH 15, SOL 15; 41 observations per asset. Three reservations, three attempts, three natural paper fills, no rejected attempts. Virtual purchase cost 62.17343320 remains open, virtual cash 9,937.82656680 and cost-basis equity 10,000. Realized losses 0; no daily or permanent halt. Open positions are archived without inventing settlement or continuing the failed candidate.

BTC resync reasons: crossed_book 8, ConnectionError 1. ETH/SOL resync reasons empty. No invalid_book_level events; every reported last_invalid_level was null. Rule refreshes BTC/ETH/SOL: 13/6/5; rule refresh errors: 0/0/0. Additional counters and every decision-reason count are in ACCEPTANCE.json.

All non-reconnect gates passed. Remaining issues: BTC crossing resyncs need investigation under a new reviewed version; seven directional decisions reported invalid_reservation. No source fix was attempted. Two inherited RUNBOOK lines remain inconsistent with HANDOVER (venue-lag attribution and rollback naming v3); HANDOVER governed, and pinned documentation was not edited.

v2 remains active, zero restarts, with its original activation time. v2 state, v3 candidate archive, lag diagnostic archive, and v1.1 were untouched. Paper only; no signer, credentials, account actions, paid calls, live orders, real budget changes, or forced trades.

Next gate: a new reviewed version and complete re-verification. Only after a passing candidate, installation and two-minute health check may the 48 hours of parallel observation begin; the owner then decides about v2.
