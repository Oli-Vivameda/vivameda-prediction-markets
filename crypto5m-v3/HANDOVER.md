# v3 handover for the server agent (Astra)

Bundle: 76b4c6e51bd58c74988877d16becdc7e8a4537e87b71dc35a8b70b753d545364

## Ten-point summary

1. Scope: commit, verify, candidate-run and install the isolated v3 paper study next to v2. Paper only.
2. Authorization: owner asked on 16 October 2026 to build v3 and send the agent to deploy it. No real trading authorization exists or is implied.
3. Reuse: v2 transport, Chainlink reference adapter, model, strategies, costs, caps, fill rules, settlement and capture are unchanged.
4. Change: stream books reconnect only on real inconsistency; connection liveness keeps quiet books usable; the realized-loss daily halt resets at midnight UTC, with a cumulative 500 stop; fills get scheduling priority; same-observation scoring; offline training builder.
5. Provenance: v2 installed-run findings (BTC 14 book reconnects in 120 s, zero fills, degraded books from stale or regressing deltas) and a code review of the v2 halt latch.
6. Validation so far: 71 local tests and the synthetic lifecycle pass. No real-data run yet, because the build machine could not reach Polymarket.
7. Limits: the liveness rule assumes in-order delivery per connection. The 1.5 s PING cadence is untested against venue rate limits. The reference feed is still retiring. The model is still uncalibrated.
8. Financial boundaries: virtual ledger only; no signer, credentials, account actions, paid calls or real budget changes.
9. Rollback: stop only vivameda-crypto5m-study-v3.service; preserve its state, v2 and v1.1. Never edit a pinned file or ledger in place.
10. Next gate: server tests, a 10-minute candidate run that meets the criteria below, root install, an independent health check, then 48 hours of observation before any comparison claims.

## Steps

1. **Commit.** Add the crypto5m-v3/ folder to Oli-Vivameda/vivameda-prediction-markets on main. Do not modify crypto5m-v2/ or crypto5m/.
2. **Verify the bundle hash.** On the server, in a fresh checkout of crypto5m-v3/, run `python3 -B install.py` and confirm the bundle equals the hash above. Stop on any mismatch.
3. **Run the synthetic tests** as vivameda-engineer:
   - `python3 -B -m unittest -q test_study test_reference test_v3` must report 71 OK.
   - `python3 -B verify_lifecycle.py` must print synthetic_integration_passed true.
4. **Run the candidate.** As vivameda-engineer, on a NEW candidate directory on the same external capture volume as v2 (device 2064), run:
   `python3 -B worker.py --state ABSOLUTE_CANDIDATE_STATE --device 2064 --expected-sha256 HASH --seconds 600`
5. **Evaluate the candidate.** Read candidate status.json and `python3 -B report.py --state ABSOLUTE_CANDIDATE_STATE`. It passes when all of the following hold:
   - reference_feed.error is null and reference disconnects are 0 or 1
   - for each asset, book_feeds disconnects are at most 5 over 600 s (v2 averaged about 70 per 600 s on BTC); record resync_reasons, superseded_deltas, superseded_snapshots, late_deltas_applied and stream_lag
   - operational forecasts exist for at least two assets
   - the ledger reopens without error and capture.verify_capture succeeds
   - no exception in the service log
   A fill is not required and must not be forced.
6. **Archive the candidate.** Keep the candidate state as a separate archive and never reuse it as the final state.
7. **Install.** As root, with a NEW final state directory next to the v2 state:
   `python3 -B install.py --install --expected-sha256 HASH --state ABSOLUTE_FINAL_STATE --device 2064`
8. **Run an independent health check after 2 minutes:**
   - service active, enabled and zero restarts
   - all 19 runtime hashes in /opt/vivameda-crypto5m-study-v3 match SYNC_MANIFEST
   - fresh capture writes
   - reference connected
   - book disconnect counts consistent with the candidate run
   - virtual cash 10,000
9. **Leave v2 running in parallel.** Running both lets book continuity be compared directly. Stopping v2 is the owner's decision after 48 hours.
10. **Report back.** Update BUILD_STATUS.md and ACCEPTANCE.json in crypto5m-v3/ with generic counts only, then commit. Report to Oli:
    - candidate and installed figures
    - per-asset book disconnects, v2 against v3
    - forecasts by asset
    - reservations, fills and rejection reasons
    - realized losses and halts

## Stop conditions

Stop and report without installing if any of the following happens:
- hash mismatch or a failing test
- the candidate fails a criterion in step 5
- stream_lag above 3 s for most of the run
- the venue rejects or disconnects because of PING cadence
- any change is needed to pass

Any fix is a new reviewed version, not an in-place edit.

## Owner policy decisions recorded in config

These values are pinned at genesis and change only with a new version:
- daily realized-loss halt: 100
- cumulative permanent stop: 500
- book liveness window: 3 s
- risk caps and costs: unchanged from v2

## Not changed, deliberately

These are carried over from v2 as-is:
- model and edge threshold
- paired-strategy rules (expected to fire rarely)
- reference adapter
- fill timing
- REST fill-book rules
- settlement
- chronology

Real execution is out of scope. It requires evidence from the same-observation score first.
