# v5 handover for the server agent (Astra)

Bundle: 9bcc18aace069035f5c3e9debad7c98af947117cd6ad52d70023f40bcdec79eb

## Ten-point summary

1. Scope: verify, candidate-test and (only if the candidate passes) install the isolated v5 paper study next to v2. Paper only.
2. Authorization: owner request on 16 October 2026 after the v4 candidate failure. No real trading authorization exists or is implied.
3. Reuse: v4 carries over unchanged. That covers in-place book updates, REST rule refresh, liveness freshness, realized-loss halts, fill priority, scoring and training builder, plus the v2 reference adapter, model, strategies, costs, caps, fills and settlement.
4. Change: a crossed reconstructed book is tolerated for up to 2 s, never tradeable, and resyncs only if it persists. Crossing evidence is recorded. A repeat decision in an already-entered window is labelled already_entered_this_window.
5. Provenance:
   - v4 candidate archive: /mnt/HC_Volume_104237945/vivameda-btc5m/crypto5m-study-v4-candidate-archive-b2610e8-20261016
   - v4 passed lag and CPU (about 0.042 s median lag, 14.6% CPU) and made 3 natural paper fills
   - v4 failed only BTC disconnects: 9, of which 8 were crossed_book
6. Validation so far: 90 local tests and the synthetic lifecycle. Throughput unchanged from v4. No server run yet.
7. Limits:
   - Whether BTC crossings are publication-order artefacts or missed messages is unproven; the crossing counters will show it.
   - The liveness rule assumes in-order delivery per connection.
   - The reference feed is retiring and the model is uncalibrated.
8. Financial boundaries: virtual ledger only. No signer, credentials, account actions, paid calls or real budget changes.
9. Rollback: stop only vivameda-crypto5m-study-v5.service. Preserve its state, the v4 and v3 archives, v2 and v1.1. Never edit a pinned file or ledger in place.
10. Next gate:
    - server tests
    - a 10-minute candidate that meets the criteria below
    - root install and an independent health check
    - 48 hours of parallel observation with v2, after which the owner decides about v2

## Steps

1. **Check out the source.** Fresh checkout of main. Work in crypto5m-v5/ only. Do not modify crypto5m-v4/, crypto5m-v3/, crypto5m-v2/ or crypto5m/.
2. **Verify the bundle hash.** Run `python3 -B install.py`. The bundle must equal the hash above; stop on mismatch.
3. **Run the tests.** As vivameda-engineer:
   - `python3 -B -m unittest -q test_study test_reference test_v3 test_v4 test_v5` must report 90 OK.
   - `python3 -B verify_lifecycle.py` must print synthetic_integration_passed true.
4. **Run the candidate.** As vivameda-engineer, on a NEW candidate directory on device 2064:
   `python3 -B worker.py --state ABSOLUTE_CANDIDATE_STATE --device 2064 --expected-sha256 HASH --seconds 600`
   While it runs, sample the worker's CPU % every 5 s. Optionally rerun the earlier minimal BTC probe alongside it for 120 s as an independent lag reference.
5. **Evaluate the candidate.** Use status.json, `python3 -B report.py --state ABSOLUTE_CANDIDATE_STATE` and the CPU samples. The candidate passes only if all of these hold:
   - reference_feed.error is null and reference disconnects are 0 or 1
   - book_feeds disconnects are at most 5 per asset over 600 s
   - per asset, worker stream_lag has a median of at most 1 s and is above 3 s for at most 5% of measured time
   - operational forecasts exist on at least two assets
   - the ledger reopens without error, capture.verify_capture passes, and the worker log has no exceptions
   - worker CPU median is recorded (expected well below one core)

   Also record per asset: crossing_episodes, crossings_resolved, crossing_max_seconds_resolved, crossing_max_events, resync_reasons, last_invalid_level, rule_refreshes, rule_refresh_errors, superseded_deltas, superseded_snapshots, late_deltas_applied, frames, processing_seconds_total and processing_seconds_max_frame. A fill is not required and must not be forced.
6. **Archive the candidate.** Archive the candidate state separately. Never reuse it as final state.
7. **Install.** As root, with a NEW final state directory on device 2064:
   `python3 -B install.py --install --expected-sha256 HASH --state ABSOLUTE_FINAL_STATE --device 2064`
8. **Run the health check after 2 minutes.**
   - service active, enabled, zero restarts
   - all 21 runtime hashes in /opt/vivameda-crypto5m-study-v5 match SYNC_MANIFEST.json
   - fresh capture writes and the reference connected
   - stream_lag and book disconnects consistent with the candidate
   - virtual cash at 10,000
9. **Leave v2 running in parallel.**
10. **Commit generic results.** Update crypto5m-v5/BUILD_STATUS.md and crypto5m-v5/ACCEPTANCE.json with generic counts only, then commit and push to main.

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
- per asset: stream_lag (median, p95, max) and disconnects, set against v4's candidate figures (BTC 9, ETH 0, SOL 0 disconnects)
- worker CPU
- forecasts by asset
- reservations, fills and rejection reasons
- realized losses and halts
- the invalid-level details
- anything unexpected

End with an Astra handover covering the exact commands, paths, hashes, results, open issues and next gate.
