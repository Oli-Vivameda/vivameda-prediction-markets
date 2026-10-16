# Final-minute partial-TWAP v2 handover for the server agent (Astra)

Bundle: b2e6f6296306073d17e2d99639fbfaeb208734de382b040583d897bad298378b

## Ten-point summary

1. Scope: verify, candidate-test and (only if the candidate passes) install the separate final-minute partial-TWAP paper lane next to v2. Paper only.
2. Authorization: owner request on 16 October 2026, after reviewing a public trader's final-minute record. No real trading authorization exists or is implied.
3. Reuse: crypto5m v5 infrastructure, unchanged. That covers in-place books, crossing grace, REST rule refresh, liveness, the Chainlink public adapter, exact opening anchor, ledger, fills, settlement, loss controls and capture.
4. Change (v2): one-sided final-minute books are allowed, so only the bought outcome needs asks; the market-probability fallback is recorded; the empty-book divide-by-zero is fixed. Inherited from v1: a preregistered final-minute model (realized TWAP plus a Brownian remainder, with a 1.5-sigma shadow). Decisions every 2 s while 12 to 58 s remain. Directional only. Fills allowed to 6 s before end. Discovery every 10 s. TWAP reconstruction is validated against official snapshots.
5. Provenance:
   - PROTOCOL.md: the v2 amendment, then the v1 preregistration with the motivating evidence and its limits
   - v1 candidate archive: /mnt/HC_Volume_104237945/vivameda-btc5m/crypto5m-final60-v1-candidate-archive-159e2bc-20261016
6. Validation so far: 118 local tests and the synthetic lifecycle. No server run of v2 yet.
7. Limits:
   - The reconstruction of Chainlink's TWAP is unproven until the comparisons accumulate.
   - The normal model may understate tails when buying near-certain outcomes; the shadow forecast measures this.
   - No speed parity with professional bots; the delayed-fill simulation is conservative.
   - The reference feed is retiring.
8. Financial boundaries: virtual ledger only. No signer, credentials, account actions, paid calls or real budget changes.
9. Rollback: stop only vivameda-crypto5m-final60-v2.service. Preserve its state, every crypto5m archive and service, v2 and v1.1. Never edit a pinned file or ledger in place.
10. Next gate:
    - server tests
    - a 15-minute candidate that meets the criteria below
    - root install and an independent health check
    - then data accumulation under the 7/3/4/28-day chronology; the reconstruction check at 100 comparisons comes first

This lane is independent of the crypto5m v5 candidate. Both may run; neither depends on the other's result.

## Steps

1. **Check out the source.** Fresh checkout of main. Work in crypto5m-final60-v2/ only. Do not modify crypto5m-final60-v1/, crypto5m-v5/, crypto5m-v4/, crypto5m-v3/, crypto5m-v2/ or crypto5m/.
2. **Verify the bundle hash.** Run `python3 -B install.py`. The bundle must equal the hash above; stop on mismatch.
3. **Run the tests.** As vivameda-engineer:
   - `python3 -B -m unittest -q test_study test_reference test_v3 test_v4 test_v5 test_final60 test_final60_v2` must report 118 OK.
   - `python3 -B verify_lifecycle.py` must print synthetic_integration_passed true.
4. **Run the candidate.** As vivameda-engineer, on a NEW candidate directory on device 2064:
   `python3 -B worker.py --state ABSOLUTE_CANDIDATE_STATE --device 2064 --expected-sha256 HASH --seconds 900`
   Use a runner whose own time limit is at least 1,200 s (for example, start it detached as vivameda-engineer and poll status.json). A run ended by the runner does not count.
   While it runs, sample the worker's CPU % every 5 s. Optionally rerun the earlier minimal BTC probe alongside it for 120 s as an independent lag reference.
5. **Evaluate the candidate.** Use status.json, `python3 -B report.py --state ABSOLUTE_CANDIDATE_STATE` and the CPU samples. The candidate passes only if all of these hold:
   - reference_feed.error is null and reference disconnects are 0 or 1
   - book_feeds disconnects are at most 5 per asset over 900 s
   - per asset, worker stream_lag has a median of at most 1 s and is above 3 s for at most 5% of measured time
   - final-minute forecasts exist on at least two assets
   - at least three TWAP reconstruction comparisons are recorded (report median and max abs error in bps)
   - the ledger reopens without error, capture.verify_capture passes, and the worker log has no exceptions
   - worker CPU median is recorded (expected well below one core)

   Also record per asset: crossing_episodes, crossings_resolved, crossing_max_seconds_resolved, crossing_max_events, resync_reasons, last_invalid_level, rule_refreshes, rule_refresh_errors, superseded_deltas, superseded_snapshots, late_deltas_applied, frames, processing_seconds_total and processing_seconds_max_frame. A fill is not required and must not be forced.
6. **Archive the candidate.** Archive the candidate state separately. Never reuse it as final state.
7. **Install.** As root, with a NEW final state directory on device 2064:
   `python3 -B install.py --install --expected-sha256 HASH --state ABSOLUTE_FINAL_STATE --device 2064`
8. **Run the health check after 2 minutes.**
   - service active, enabled, zero restarts
   - all 23 runtime hashes in /opt/vivameda-crypto5m-final60-v2 match SYNC_MANIFEST.json
   - fresh capture writes and the reference connected
   - stream_lag and book disconnects consistent with the candidate
   - virtual cash at 10,000
9. **Leave v2 running in parallel.**
10. **Commit generic results.** Update crypto5m-final60-v2/BUILD_STATUS.md and crypto5m-final60-v2/ACCEPTANCE.json with generic counts only, then commit and push to main.

## Stop conditions

Stop and report without installing if any of these happens:
- hash mismatch or a failing test
- any candidate criterion fails
- the worker approaches one core of CPU
- rule_refresh_errors prevent connection
- the venue rejects the PING cadence
- anything requires a code change

Fixes are a new reviewed version, never an in-place edit. If invalid_book_level still occurs, report last_invalid_level verbatim; that is the evidence needed for the next decision.

## Report back to Oli

Report in plain text:
- pass or fail per step
- candidate and installed figures
- per asset: stream_lag (median, p95, max) and disconnects, set against the latest crypto5m candidate figures
- worker CPU
- final-minute forecasts by asset, decision skip reasons, and counts of market_probability_method
- the distinct market (condition) counts in the index tables observations, markets and outcomes; v1 reported 18 priced markets where 9 were expected, so check this directly
- TWAP reconstruction: comparisons, unusable windows, median and max absolute error in bps
- model_vs_market_same_observation, if any windows have settled (report as early observation only, no edge claim)
- reservations, fills and rejection reasons
- realized losses and halts
- the invalid-level details
- anything unexpected

End with an Astra handover covering the exact commands, paths, hashes, results, open issues and next gate.
