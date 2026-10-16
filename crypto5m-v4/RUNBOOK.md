# Operation (v4)

Source bundle: 275b728b1f972f2b6cba5b37dabe443d4c9e76e0f2aef47a6b1a24a852e4e7f3. Confirm with `python3 -B install.py` (no arguments) before anything else.

Candidate run (engineering account, separate candidate state on the capture volume, device 2064):
`python3 -B worker.py --state ABSOLUTE_CANDIDATE_STATE --device 2064 --expected-sha256 HASH --seconds 600`
Archive the candidate state afterwards; never reuse it as the final state.

Root installation: `python3 -B install.py --install --expected-sha256 HASH --state ABSOLUTE_FINAL_STATE --device 2064`. The installer runs all 81 tests as vivameda-engineer, validates the unit, source hashes and volume, refuses to overwrite an existing deployment and changes no other unit. Use a new state directory, never a v2 or v3 one.

Health: `systemctl status vivameda-crypto5m-study-v4.service` and STATE/status.json. These are separate checks, and a running process alone proves none of the later ones:

- active process and fresh capture writes
- usable books, warmed reference history and the exact opening anchor
- forecasts and reservations
- delayed fills and official settlement

For book health, compare book_feeds.*.disconnects and resync_reasons with v2. Also read superseded_deltas, superseded_snapshots, late_deltas_applied and stream_lag. Persistent stream_lag above 3 seconds means venue lag; the books then abstain correctly.

Loss controls: status.json shows realized_losses, entries_halted_today, day_halts and halted. A day halt clears itself at the next UTC day. A permanent halt needs a new reviewed version.

Reports and research: `python3 -B report.py --state STATE`. The primary edge test is model_vs_market_same_observation; a negative brier_difference_model_minus_market means the model beat the market on identical rows. Training rows: `python3 -B training.py --state STATE --asset btc --rows-only`. Fit after day 10 only: `python3 -B training.py --state STATE --asset btc`. The fit prints an artifact; nothing is promoted or loaded by the service.

Capture integrity: capture.verify_capture(STATE/capture.sqlite3). Keep raw records on the server; publish only generic acceptance summaries. Add STATE/STOP to stop new virtual attempts; inventory is retained to resolution. Roll back by stopping only the v3 unit; preserve its state, v2 and v1.1. Never modify a pinned source or ledger in place.

Reference failure: inspect reference_feed.error, raw point counts, latest_source_at and exact-opening skip reasons. Do not remove freshness checks, invent an anchor or switch to Binance as a settlement proxy. Authenticated PolyBolt needs a separate reviewed adapter.

v4 book diagnostics in status.json book_feeds: frames, processing_seconds_total and processing_seconds_max_frame (worker throughput), last_invalid_level (outcome, side, price, size, tick, reason), rule_refreshes and rule_refresh_errors (REST tick/minimum reloads per connection). If stream_lag climbs while a separate minimal consumer stays current, the worker is backlogged again: record CPU and stop, do not tune in place.
