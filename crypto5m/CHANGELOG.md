# Engineering revisions

- v1: initial bounded public collection candidate, no paper positions. Source bundle 5a6f7f601bd84124fc3f93ad2113920d5700a1f9dc7fa049936ec85697b90f21 and capture retained privately for reproducibility. Reconnect/freshness rejections exposed feed-handling limitations; not scientific strategy results.
- v1.1: validate a complete CLOB change batch before testing the resulting spread; track outcome-specific tick sizes and refresh full snapshots after tick changes; clock decisions after snapshot copying; preserve exact input-packet hashes. Same strategy/risk defaults, new version and study state. No migration, reset, or selection of profitable history.

Final v1.1 acceptance also isolates a low-root-disk unit-test fixture from the production free-space threshold. This changes test setup only; production policy is unchanged. Candidate captures remain separate from the reviewed study.
