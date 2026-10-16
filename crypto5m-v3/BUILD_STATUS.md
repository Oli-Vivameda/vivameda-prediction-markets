# Build status: v3 — candidate failed, not installed

Source commit faca3eb496a1f266ab0072b7de589e76b4391490. Bundle 76b4c6e51bd58c74988877d16becdc7e8a4537e87b71dc35a8b70b753d545364. Server verification on 16 October 2026 used a fresh main checkout and left all 19 manifest-listed files unchanged.

## Step results

- Bundle and manifest: PASS.
- Server synthetic tests: PASS, 71 tests OK.
- Synthetic worker lifecycle: PASS.
- Separate candidate execution: PASS, 601.34 seconds, exit 0.
- Candidate acceptance: FAIL. Book reconnect and sustained-lag gates failed.
- Candidate archive: PASS, preserved separately; never reused as final state.
- Root installation and two-minute installed health check: NOT RUN, blocked by failed candidate.
- Existing v2: active, zero restarts, original activation time unchanged. v1.1 untouched.

## Candidate counts

Reference error null, zero reference disconnects, 3,280 responses and eight rejected stale snapshots. Forecasts: BTC 2, ETH 1, SOL 1; 123 observations. One directional reservation, one attempt rejected as stale_or_changed_book, zero fills. Virtual cash 10,000, daily and cumulative realized losses zero, no day halt or permanent halt. Ledger reopened cleanly; 2,164 capture envelopes verified. Worker log empty with no logged exceptions.

Book counters are aggregated over all observed feed instances and market rotations, not just the last status snapshot:

| Asset | Disconnects | Superseded deltas | Superseded snapshots | Late deltas applied | Lag median (s) | Lag maximum (s) | Measured time above 3 s |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 5 | 11 | 3 | 140323 | 38.15 | 120.86 | 93.14% |
| ETH | 13 | 0 | 1 | 103147 | 42.58 | 169.76 | 93.36% |
| SOL | 12 | 2 | 0 | 80823 | 32.74 | 134.85 | 85.11% |

Resync reasons: BTC crossed_book 4 and ConnectionError 1; ETH invalid_book_level 13; SOL invalid_book_level 12. Final lag values were BTC 8.06 s, ETH 67.59 s, SOL 36.14 s. Above-three-second durations were at least 543.39, 512.20 and 464.08 seconds respectively, so all exceed half of the entire run even if every unmeasured interval were fresh.

The historical v2 rates extrapolated from its 120-second baseline are BTC 70, ETH 25, SOL 10 per 600 seconds. This is not a contemporaneous comparison; v2 state and captures were not read or changed. BTC and ETH had fewer disconnects by that historical comparison, but all assets failed freshness and SOL exceeded its historical rate. Fewer disconnects do not establish a usable stream.

No explicit PING-cadence rejection was recorded. The one BTC ConnectionError is unattributed because the transport does not expose its close code. The initial diagnostic submission exceeded the engineering runner's accepted arguments; the identical evaluator was then run as a separate verification helper outside the pinned source. No v3 code was changed.

## Handover and next gate

Stop here. This bundle is not approved for installation. Preserve the archived candidate and frozen source. Any fix requires a new reviewed version and a new candidate; do not modify this version, loosen freshness or force a fill. After a new version passes its gates and installed health check, observe it alongside v2 for 48 hours; the owner then decides whether v2 changes. That observation gate has not started.

Paper only. No signer, credentials, account actions, paid calls, real budget changes, automatic promotion or validated edge.
