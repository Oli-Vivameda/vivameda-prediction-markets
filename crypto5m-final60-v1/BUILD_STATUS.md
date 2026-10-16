# Build status: final-minute partial-TWAP v1

Source bundle 45fe476c02760baf6204a9b922987bad3229a670354142a94383600852b04bfe, built 16 October 2026 on crypto5m v5 bundle 9bcc18aace069035f5c3e9debad7c98af947117cd6ad52d70023f40bcdec79eb.

Local results: 108 synthetic tests pass. That is 90 inherited, adapted where the lane deliberately differs (forecast version, final-minute-only decisions, unit name; shared ledger mechanics are still tested with paired enabled), plus 18 lane tests. The synthetic lifecycle passes with a final-minute forecast, a reservation, a delayed fill and exactly-once settlement.

The build environment has no route to Polymarket. Server tests, the bounded candidate (at least 15 minutes) and installation are pending. The v5 candidate is independent and also pending. No forecast quality, edge or real-fill claim is made.
