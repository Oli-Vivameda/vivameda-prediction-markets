# Build status: final-minute partial-TWAP v2

Source commit: c29fe1845ed87d38f782d38e9bcd1d2deb0a332f.
Bundle: b2e6f6296306073d17e2d99639fbfaeb208734de382b040583d897bad298378b.

Server verification on 16 October 2026: fresh main checkout matched the pinned commit; bundle and all 23 source hashes matched. The required 118 tests reported OK and the synthetic lifecycle passed.

**Stopped before the candidate because an additional read-only synthetic preflight failed. No installation was prepared or attempted.**

An empty Up book is admitted by the v2 worker freshness checks. With the Down outcome quoted, market.implied_p_up also succeeds using down_midpoint_complement. The worker sampling diagnostics then computes (bid - ask) / (bid + ask) with zero Up depth, raising ZeroDivisionError: division by zero at worker.py:110. Study.sample calls this function, and the exception is not caught by the sample/tick/main loop. This is a worker crash path for an input deliberately allowed by v2.

The new model-level empty-Up test covers predict_final, but the worker diagnostics path still contains the zero-denominator calculation. The passing worker decision test calls decide, not the complete sampling path. The preflight used the pinned test fixture, passed through sampled_books and market freshness, then called diagnostics. It made zero network calls, created no study state and changed no pinned file.

The owner's frozen-code stop condition applies: a source change would be needed, so no in-place fix, candidate, detached runner, forced trade, root install command or health check was attempted. No candidate state or archive exists for this attempt. Lag, disconnects, forecast counts, skip reasons, method counts, distinct table condition counts, reconstruction comparisons, scores, fills, CPU, losses and halts are unmeasured, not zero.

The synthetic fallback method is evidence for reachability only; it is not a prospective market_probability_method count. Likewise the 118 synthetic tests and lifecycle establish no prospective forecast, fill or edge.

All 23 pinned files remain unchanged. v2 remains active with zero restarts and its original activation timestamp. No installed crypto5m service was stopped, modified or restarted; no other study state/archive, including final60 v1 or v1.1, was accessed. Paper only: no signer, credentials, account actions, paid calls or real budget changes.

Generic results are in ACCEPTANCE.json; synthetic repro code, JSON evidence and a ten-point Astra handover are retained separately on the server under client_learning/crypto5m_final60_v2_verification_20261016/. No raw market records are published.

Next gate: a new reviewed version must safely handle zero total Up-book depth in worker diagnostics and add a regression exercising the sampling path, not only the model/decision functions. Then rerun source verification, the required suite and lifecycle, and a clean 900-second candidate under a runner allowing at least 1,200 seconds. Installation preparation remains conditional on every gate passing. The first-100 reconstruction check and 7/3/4/28-day study accumulation remain future gates.
