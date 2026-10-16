# BTC ETH SOL five-minute paper study v3

Version 3 of the isolated paper study. It keeps v2's public Chainlink reference adapter, model, strategies, costs, caps and settlement rules, and changes four operational things:

- the book stream no longer reconnects on late or superseded messages
- connection liveness keeps quiet books usable
- the halt uses realized losses (daily reset, cumulative hard stop)
- pending delayed fills get priority over slow network housekeeping

It also adds a same-observation model-versus-market score and an offline training-row builder. This is a new source-pinned experiment, separate from v2 and v1.1; do not mix their results. No account credentials, signer or financial API calls.

Risk policy: 10,000 virtual cash; 25 per directional or paired attempt; shared 75 per market window; daily worst-case exposure bound 100; daily realized-loss halt 100 (resumes next UTC day); cumulative realized-loss stop 500 (permanent). No Kelly, passive fills or automatic promotion.

Run synthetic validation with `python3 -B -m unittest -q test_study test_reference test_v3` and `python3 -B verify_lifecycle.py`. See PROTOCOL.md, RUNBOOK.md and HANDOVER.md. The installer creates only vivameda-crypto5m-study-v3.service, runtime /opt/vivameda-crypto5m-study-v3 and its own external-volume state. v2 is preserved.

This is paper research, not a validated trading strategy. The public reference endpoint is retiring. Missing, stale, revised or incomplete data causes abstention, not replacement prices.
