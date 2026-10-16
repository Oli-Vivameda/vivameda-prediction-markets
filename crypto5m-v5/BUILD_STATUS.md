# Build status: v5

Source bundle 9bcc18aace069035f5c3e9debad7c98af947117cd6ad52d70023f40bcdec79eb, built 16 October 2026 from v4 bundle 275b728b1f972f2b6cba5b37dabe443d4c9e76e0f2aef47a6b1a24a852e4e7f3.

Why v5 exists: the v4 candidate passed every lag and CPU gate (median lag about 0.042 s on all assets, 0% above 3 s, CPU median 14.6% of one core) and produced three natural paper fills. ETH and SOL had zero disconnects. It failed only on BTC, with 9 disconnects against a limit of 5: 8 were immediate crossed_book resyncs and 1 a connection error.

Local results: 90 synthetic tests pass (81 inherited, with the unit-name pin updated, plus 9 v5 tests). The synthetic lifecycle passes. Throughput is unchanged from v4 (about 15 us per event locally).

Server tests, the bounded candidate and installation are pending. No forecast quality, edge or real-fill claim is made. v2 remains the running service; the v4 and v3 candidate archives and v1.1 are untouched.
