# Polymarket keyset recovery — 7 October 2026

Gamma rejected the scanner's deep numeric offset with HTTP 422 and directed clients to /markets/keyset. The scanner now uses after_cursor and a separate polymarket_keyset_cursor state key, preserving the old cursor and historical state. Cursor type, length, empty-page and repeated-cursor checks retain the last committed page on failure. Kalshi pagination, notification grouping, contract links and dedicated Telegram destination remain unchanged.

Validation: 84 prediction tests passed; two public keyset GET pages each returned 100 records, with zero overlap and advancing cursor. Installed production scanner SHA256 independently matches b3f583c71b7e158e15f824a5745abfc9fa6236bf15b7034dfe830e562fbff0a8; hourly timer active. Current production-feed counts and new-format Telegram delivery were not independently read through the non-root connector, and are not claimed here.

Source publication uses connector write operations, preserves the remote tree and history, and verifies remote contents. Private runtime/cursors, credentials and provider payloads are excluded. No paid provider request or live trading. Separate private daily backup is active and restore-verified; source and aggregate checkpoint are in vivameda-intelligence-stack commit ab376fbb908f38b0fcc5a4346404bbaa3699268a.
