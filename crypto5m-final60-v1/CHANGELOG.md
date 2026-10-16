# Changes

Final-minute partial-TWAP v1:
- new lane on crypto5m v5 infrastructure; preregistered model forecasting the final-minute TWAP from its realized part plus a Brownian remainder, with a 1.5-sigma shadow forecast
- decisions every 2 s while 12 to 58 s remain; observations every 15 s outside the final minute
- directional only; fills allowed to 6 s before end; market terms rediscovered every 10 s
- reconstruction validation against official Chainlink TWAP snapshots at every window start and end
- report adds remaining-time bands, the shadow score, reconstruction results and the largest-loss versus average-win statement
- own config, ledger, service and runtime

Inherited history: see ../crypto5m-v5/CHANGELOG.md.
