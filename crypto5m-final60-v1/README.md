# Final-minute partial-TWAP study v1 (BTC ETH SOL five-minute markets)

A separate paper research lane built on the crypto5m v5 infrastructure. It tests one preregistered hypothesis: inside the final 60 seconds, part of the settlement TWAP is already realized, and the market underprices that partially locked outcome.

The model computes the realized part of the final-minute Chainlink TWAP exactly from public raw points, adds a Brownian estimate for the remainder, and forecasts P(Up) against the exact opening TWAP. Decisions run every 2 seconds while 12 to 58 seconds remain. The lane is directional only, with one entry per asset and window and delayed paper fills down to 6 seconds before end. Outside the final minute it only records market observations for calibration. Every window start and end compares our TWAP reconstruction with the official Chainlink snapshot (preregistered limit: 1 basis point median error).

Risk policy is inherited: 10,000 virtual cash, 25 per position, 75 per window, daily worst-case exposure bound 100, daily realized-loss halt 100, cumulative stop 500. No credentials, signer, account actions or paid calls.

Run `python3 -B -m unittest -q test_study test_reference test_v3 test_v4 test_v5 test_final60` (108 tests) and `python3 -B verify_lifecycle.py`. See PROTOCOL.md (the first section is this lane's preregistration), RUNBOOK.md and HANDOVER.md. The installer creates only vivameda-crypto5m-final60-v1.service, runtime /opt/vivameda-crypto5m-final60-v1 and its own state. Every crypto5m version, archive and service is preserved.

Paper research only. The motivating evidence is one public trader's record, which is anecdotal and selected after the fact.
