# Build status: v4

Source bundle 275b728b1f972f2b6cba5b37dabe443d4c9e76e0f2aef47a6b1a24a852e4e7f3, built 16 October 2026 from v3 bundle 76b4c6e51bd58c74988877d16becdc7e8a4537e87b71dc35a8b70b753d545364.

Why v4 exists: the v3 candidate failed on 30 to 43 s median stream lag. A same-server diagnostic proved the venue feed current (independent consumer median about 40 ms) while v3 used about 105% of one core. The bottleneck was v3's per-delta full rebuild, sort and hash.

Local results: 81 synthetic tests pass (71 inherited plus 10 v4), including equivalence with a naive full reconstruction and a throughput bound. Synthetic lifecycle passes. Local benchmark on identical synthetic streams: v3 about 690 us per event, v4 about 20 us.

The build environment has no route to Polymarket. Server tests, the bounded candidate and installation are pending. No forecast, fill or advantage is claimed. v2 remains the running service; the v3 candidate archive and v1.1 are untouched.
