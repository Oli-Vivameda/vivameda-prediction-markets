# Build status — v2

Final reviewed source bundle 50c8771ed72bae39708df45a8a26a83bff5373a9b7aad7055e0e52baefa6f50a. 54 local and server tests pass, plus a separate synthetic worker lifecycle check from public-reference fixture to model, reservation, delayed fill and exactly-once settlement credit. The public adapter uses legacy Chainlink raw and exact opening TWAP snapshots; it has no credentials or signer.

The first seven-minute candidate recorded 87 observations, two qualifying directional reservations, two unfilled attempts (no post-delay liquidity), two official outcomes and 1,811 integrity-verified capture envelopes. Those results belong to candidate eb9a445cebe9d2982d8f4ad912ff54be3edf3634fd8fb1c5c9ac75bb891b3189, archived separately. Final source rejects individual late reference snapshots without resetting other assets. Source age, history gaps, revisions and wrong-source guards remain enforced. Final bounded verification is in progress; no persistent v2 service has been installed.

No prospective filled trade or validated advantage is claimed. The legacy reference endpoint is retiring; book gaps and stale data can still cause abstention. Existing risk, storage caps, calibration and final evaluation gates remain active. The prior v1.1 service and history remain intact. Real execution, signing keys, paid calls and real budgets are untouched.
