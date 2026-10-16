# Changes

Version 5: crossed reconstructed books tolerated for up to 2 s (never tradeable) and resynchronized only when persistent; crossing evidence in status; already_entered_this_window decision label; new config, ledger, service and runtime. Otherwise identical to v4.

Version 4: in-place book level updates with snapshot-time sorting and hashing (v3 saturated one core on the server; about 34x less work per event); REST tick and minimum refresh before every stream connection (breaks the stale-tick invalid_book_level loop); detailed invalid-level and processing diagnostics; CPUQuota 100%; new config, ledger, service and runtime. Behaviour otherwise identical to v3.

Version 3:
- book stream applies late ordered deltas, skips deltas superseded by a snapshot and ignores older snapshots, reconnecting only on real inconsistency, with per-reason counters
- connection-liveness freshness (PING every 1.5 s) for quiet books; locked books are not tradeable
- REST fill books keep v2 rules
- realized-loss daily halt with next-day resume, plus a cumulative 500 permanent stop; the worst-case pre-trade bound is unchanged
- attempt-first scheduling, deferring discovery and resolution while a fill is due
- input receive/source times recorded per forecast
- same-observation model-vs-market report
- offline training.py
- new config, ledger, service and runtime

Version 2: public Chainlink snapshot reference adapter; exact opening TWAP; original receive-time retention; revision/gap guards; empty-book collection without executable fills; separate source/config pin and ledger; retiring endpoint documented.
