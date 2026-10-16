# Build status: final-minute partial-TWAP v3

Source bundle 35483aa13336bad9f3d9c0c1635bfa55b68541e6a45545ff753fab5a9146c91c, built 16 October 2026 from final60 v2 bundle b2e6f6296306073d17e2d99639fbfaeb208734de382b040583d897bad298378b.

Why v3 exists: the v2 server preflight showed a fully empty Up book crashing the worker's sampling diagnostics (division by zero), so no v2 candidate was run. v3 fixes that path and audits every book read in the lane.

Local results: 121 synthetic tests pass (118 inherited plus 3 v3 tests, including the 16-shape matrix, which reproduces the v2 crash on v2 source). The synthetic lifecycle passes.

Server tests, the 900-second candidate (runner limit at least 1,200 s) and installation are pending. No forecast quality, edge or real-fill claim is made.
