# Owner-operated $10 live pilot

This optional execution software is separate from the running paper study. It is not activated, no real account has been connected, and no live order was used to test it. A human owner must configure and operate it. The assistant does not sign, submit or activate financial transactions.

## Limits

- Dedicated trading wallet with no more than $10 collateral. Do not connect a larger existing account.
- $3 reserved per attempted market for the whole pilot; $2.75 SDK all-in target leaves $0.25 headroom. Reservations are never recycled or refunded automatically, including failed submissions. At most three reserved attempts ($9) fit, with $1 additional unallocated headroom.
- The SDK's all-in target is an estimate, not a guaranteed settlement fee ceiling. Dedicated wallet funding, conservative headroom and post-fill cost reconciliation are separate controls. Account setup/network costs are outside the trading-capital envelope and are not automatically approved by this software.
- One unresolved submission or held position at a time. One immutable side and plan per exact contract. No leverage, martingale, averaging down, order retry or automatic redemption.
- FOK buys with a current-book price cap. Venue minimum shares/depth can prevent a small order; then skip. The first adapter supports CTF Up/Down markets only, excluding position-based protocol V2 and delayed venue matching.
- Consume the frozen paper decision; execute its same side between two and five seconds afterward, never in the final 60 seconds. This live window is a separate execution experiment from the paper delay arms; its observations must never be pooled into that frozen study.
- Fresh recording and health required. Exact market/outcome identity, description hash, deadline and fees are rechecked. An unknown submission/fill/cost result stops the runner and blocks restart pending private reconciliation. A matched order is not counted as a confirmed fill until on-chain settlement and position/balance reads pass.
- Owner chooses a timezone-aware execution window of at most 24 hours. Place a `STOP` file in the state directory to stop new orders. It does not unwind a confirmed hold-to-resolution position and cannot recall an already transmitted immediate order.

## Current readiness

19 isolated functional tests pass with mock venue calls. The official `polymarket-client==0.13.0` is installed in a separate build environment for compatibility verification. No real signing/authentication/allowance/fill test has passed.

The public trading-eligibility endpoint returned HTTP 403 from the current server on 13 October 2026. This does not identify the underlying cause; eligibility is unverified. The runner fails closed on blocked or unavailable eligibility. No proxy, VPN, endpoint override or bypass is implemented. Tomorrow's real-money operation is **not ready** until supported venue eligibility and private account setup are verified by the owner.

## Owner setup

Use Python 3.11+ and a private non-root account. Work from this directory. The paper feed must be reachable at `http://127.0.0.1:8765/api/state`, locally or through your existing private SSH tunnel.

```bash
python3 -m venv /absolute/private/pilot-venv
/absolute/private/pilot-venv/bin/pip install -r requirements.txt
/absolute/private/pilot-venv/bin/python -m unittest discover -s . -q
/absolute/private/pilot-venv/bin/python pilot.py preview
```

`preview` reads public eligibility only; it never initializes a signer or places an order. Stop here if it reports ineligible/unverified.

Create/fund an eligible dedicated account through Polymarket yourself and complete required wallet/allowance setup. Do not paste signing keys into ChatGPT, put them in command arguments or send them through engineering tools. The owner's private terminal command collects the dedicated signer key with a hidden prompt and writes an owned 0600 file without overwriting an existing secret:

```bash
/absolute/private/pilot-venv/bin/python pilot.py configure \
  --secret-file /absolute/private/pilot/pilot-secret.json
```

Private files: signer JSON, `pilot-ledger.sqlite3`, journal records and status belong only in a 0700 directory. Never upload them to this public repository. Authentication supports the explicit wallet address through the official SDK; account bootstrap/authentication may have venue-side effects and must be performed by the owner.

The owner's explicit `pilot.py run` command requires `--live`, `--secret-file`, `--state-dir`, `--not-before` and `--until`. Run `pilot.py run --help` for syntax; no execution service is enabled by this build. Once started by the owner, it selects qualifying frozen decisions automatically within that window and the capital controls above.

The lifetime ledger is authoritative. Keep it across restarts; never delete it or reset budget to continue trading. `pilot.py status --state-dir /absolute/private/pilot` reports reservations and unresolved intents without reading secrets. For an ambiguous submission, reconcile the exact contract and order with authenticated venue records in your own terminal; this build intentionally has no automatic force-resume command.

## Evidence and model caveat

The baseline remains uncalibrated and has no demonstrated profitable edge. This pilot exercises execution and capital controls; it does not pass the prospective model gate. The 14–28 October study and all production scanner policies remain unchanged.

API sources checked 13 October 2026: [official SDK](https://github.com/Polymarket/py-sdk), [order placement](https://docs.polymarket.com/trading/place-orders), [order management](https://docs.polymarket.com/trading/manage-orders). SDK metadata and source were checked for price protection, estimated fee-inclusive targeting, minimum size, authentication and asynchronous fill settlement.

## Ten-point handover

1. Scope: separate owner-run execution code, no assistant activation.
2. Capital: dedicated $10 wallet, fixed conservative reservations, no recycling.
3. Strategy: immutable same-side baseline decision, distinct live execution window.
4. Venue: pinned official SDK, CTF only, no matching delay or geographic bypass.
5. Orders: FOK, price cap, minimum/depth/identity/fee checks.
6. Persistence: SQLite atomic reservation, unique market, chained events and restart guards.
7. Reconciliation: on-chain fill plus position/balance checks; uncertainty halts.
8. Tests: mocked only; SDK compatibility recorded separately; no live order evidence.
9. Blockers: venue eligibility HTTP 403, no privately connected/funded/approved account.
10. Next: owner account/eligibility verification, then owner-operated capped pilot; no profitability claim.
