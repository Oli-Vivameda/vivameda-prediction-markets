# BTC ETH SOL five-minute paper study v2

Public legacy Chainlink raw/TWAP snapshots now supply the reference adapter. Empty books remain collectible but never executable. This is a new source-pinned experiment, separate from v1.1; do not mix their results. No account credentials, signer or financial API calls.

Risk policy: 10,000 virtual cash; 25 per directional or paired attempt; shared 75 per market window; daily worst-case loss limit 100; no Kelly, passive fills or automatic promotion. Existing delayed-fill, fees, shared reservations, settlement and chronology rules remain.

Run synthetic validation with `python3 -B -m unittest -q test_study test_reference`. See PROTOCOL.md and RUNBOOK.md. Installer creates only vivameda-crypto5m-study-v2.service, runtime /opt/vivameda-crypto5m-study-v2 and its separate external-volume state. The prior collector is preserved.

This is paper research, not a validated trading strategy. The public reference endpoint is retiring. Missing, stale, revised or incomplete data causes abstention, not replacement prices.

Run `python3 -B verify_lifecycle.py` for the separate synthetic worker integration test (no network and no prospective trades).
