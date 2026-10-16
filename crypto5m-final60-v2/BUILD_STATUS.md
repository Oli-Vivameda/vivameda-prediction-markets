# Build status: final-minute partial-TWAP v2

Source bundle b2e6f6296306073d17e2d99639fbfaeb208734de382b040583d897bad298378b, built 16 October 2026 from final60 v1 bundle 45fe476c02760baf6204a9b922987bad3229a670354142a94383600852b04bfe.

Why v2 exists: the v1 candidate confirmed the premise (TWAP reconstruction median 0.086 bp, max 0.131 bp, across 9 boundaries) but produced zero final-minute forecasts. 180 of about 220 final-minute decisions failed on the inherited two-sided book rule, because the losing outcome's book is routinely empty at the end. The run was also ended by the runner at about 895 s.

Local results: 118 synthetic tests pass (108 inherited, with the version pin updated, plus 10 v2 tests). The synthetic lifecycle passes.

Server tests, the bounded candidate (runner limit at least 1,200 s) and installation are pending. No forecast quality, edge or real-fill claim is made.
