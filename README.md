# Vivameda prediction-market scanner v1

Status: source built and tested on Hetzner; recurring service installation pending.
Live execution, signing, wallets, paid enrichment and alert-policy changes are absent.

## Behavior
Public GET adapters discover ordinary binary Polymarket and Kalshi contracts in rotating bounded pages.
A starter alias registry routes company questions; Solana terms route to crypto research. BTC/ETH coverage
is withheld. Every candidate retains question, rule text, source fingerprint, deadline and observation time.
Relevance is a heuristic and never becomes a probability.

The evidence bridge reuses installed cached-only Vivameda Research for bounded descriptive company context,
once per company/day. Market text is never dispatched as instructions. The Solana bridge reads existing
fresh retained memory, requiring an exact mint in the question. Generic chain price questions abstain.
Company and crypto evidence remain separate. The live OpenAI bridge passed; the actual crypto bridge is
not yet verified on a supported live contract.

Researcher forecasts require reviewed identity, rules, scope, current dated evidence and a scan <=15 minutes old.
They are immutable and labelled unvalidated. Paper entries require a quote <=60 seconds old, observed depth,
explicit reviewed fees/slippage and positive conservative expected payout minus all-in price. Paper fills are
assumptions, not real executions. Reviewed final settlement computes forecast diagnostics and simulated P&L.
No autonomous forecast or paper position has been created.

## Installation
Run in the existing Hetzner root terminal:
```bash
python3 /var/lib/vivameda-engineering/repo/client_learning/prediction_scanner_v1/install.py --install --expected-sha256 b894122f634aa19a97eddcd876e92d8d5c4b3104abb6fb241de5e6f6faf0afb3
```
Installer runs42 tests/compilation/systemd syntax, backs up prior scoped source, runs an actual installed
cycle, requires at least one successful real feed, enables a15-minute timer and verifies runtime hashes.
Failure restores prior source/timer state. It modifies only this new scanner service. State is private under
/var/lib/vivameda-prediction-scanner; source under /opt/vivameda-prediction-scanner.
It runs as the existing vivameda-agent user to retain established read permissions.
Direct engineering runs as vivameda-engineer and has no deployment operation for this service.

Status after installation:
```bash
python3 /opt/vivameda-prediction-scanner/scanner.py status
systemctl status vivameda-prediction-scanner.timer
```

## Development
```bash
cd /var/lib/vivameda-engineering/repo/client_learning/prediction_scanner_v1
python3 -m unittest -v test_scanner test_ledger
python3 scanner.py scan --state runtime --pages 2 --quote-limit 3
python3 bridge.py --state runtime --limit 2
python3 paper.py report --state runtime
```
Do not commit runtime/, cached company archives, forecasts or paper/outcome state.
This public repository contains reviewed scanner source and aggregate build receipts only.
Private runtime databases, evidence archives, proprietary datasets and forecasts are excluded.
The evidence bridge requires separately installed private Vivameda modules; standalone discovery
and synthetic tests work without them. No proprietary models or datasets are included.

## Limits and next gates
- The first sample is2,200 records,8 candidates, not the complete catalog or8 independent opportunities.
  Seven contracts belonged to one OpenAI IPO event. Avoid treating correlated brackets as independent bets.
- Starter aliases are not full company coverage or verified legal identity. Company mapping must be reviewed.
- No calibrated prediction-market model; no proved advantage or profitable track record.
- Position-based Polymarket V2 books are withheld; legacy token books were verified live.
- Kalshi top-of-book entries need known ask size; missing depth is not an assumed fill.
- Market endDate/close_time is recorded as a platform deadline; reviewers must establish actual resolution
  timing, early resolution, source-specific conditions and event dependence before any forecast.
- Outcomes require explicit reviewed final payout; no automatic oracle settlement ingester yet.
- Scans are bounded rotating pages; catalogue changes may cause gaps. Reports identify feed errors/coverage.
- Only in-scope snapshots persist. Database512 MiB guard stops growth and requires archiving; state has
  no automatic pruning that could erase frozen forecasts.
- Installation must verify service-user access to actual retained evidence; a descriptive context receipt
  never certifies identity/perimeter or future-event answerability.
- Further markets can be added after these two adapters are stable. Live trading requires a separate
  reviewed approval/execution design and is outside this package.
