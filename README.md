<div align="center">

<img src="https://fxapis.com/logo.png" alt="" width="72" height="72">

# fxapis

**The official Python SDK for fxapis — the hosted MetaTrader 5 REST API**

[Website](https://fxapis.com) · [Docs](https://docs.fxapis.com) · [API Reference](https://docs.fxapis.com/api-reference) · [Status](https://status.fxapis.com) · [Support](mailto:support@fxapis.com)

[![License: MIT](https://img.shields.io/badge/license-MIT-22D3D6?style=flat-square)](LICENSE)
[![ci](https://img.shields.io/github/actions/workflow/status/FXapis/fxapis-python/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/FXapis/fxapis-python/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/FXapis/fxapis-python?style=flat-square&color=22D3D6)](https://github.com/FXapis/fxapis-python/releases)
[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![types](https://img.shields.io/badge/types-strict%20mypy-3178C6?style=flat-square)](pyproject.toml)
[![fxapis status](https://status.fxapis.com/badge.svg)](https://status.fxapis.com)

</div>

---

Connect an MT5 account once, then place market and pending orders, close and modify positions, read deals and positions, and send one trade to many accounts at once — from Python, over HTTPS.

You run **no MetaTrader terminal, no Windows VPS and no EA**. fxapis runs the MT5 terminals in its cloud (EU, Amsterdam) and gives you an API in front of them. That makes it a fit for **MT5 Python** automation on Linux or macOS, **copy trading** and trade copiers, **click-to-trade** signal apps, and anything that manages many MT5 accounts.

- **Sync (`Fxapis`) and async (`AsyncFxapis`) clients**, built on [httpx](https://www.python-httpx.org/)
- **Fully typed** (`py.typed`, `TypedDict` responses with the API's exact field names), checked with `mypy --strict`
- **Automatic `Idempotency-Key`** on every order, with an override for your own keys
- **Typed exceptions** for every API error code — and safe retries that never resend an unresolved order
- **Helpers:** `wait_until_ready()`, `wait_until_resolved()`, `wait_until_settled()`, pagination iterators

MT5 only (MT4 is not supported).

> [!IMPORTANT]
> Not yet published to PyPI — see [Installation](#installation).

## Table of contents

- [Installation](#installation)
- [Quickstart](#quickstart)
- [Handling order outcomes](#handling-order-outcomes)
- [Click-to-trade and signals](#click-to-trade-and-signals)
- [Copy trading: one trade on many accounts](#copy-trading-one-trade-on-many-accounts)
- [Async](#async)
- [Reference](#reference)
- [Good to know](#good-to-know)
- [Related fxapis repositories](#related-fxapis-repositories)
- [Contributing](#contributing)
- [Support](#support)
- [License](#license)

## Installation

```bash
pip install fxapis
```

> [!NOTE]
> This package is not yet published to PyPI (the release pipeline is set up — see
> [`.github/workflows/release.yml`](.github/workflows/release.yml) — and is waiting on a pending
> publisher being registered at pypi.org). Until then, install straight from this repository:
> `pip install git+https://github.com/FXapis/fxapis-python.git`, or clone it and
> `pip install -e .`. `pip install fxapis` above is what it will be once published — nothing
> else about the API changes when that happens.

Python 3.10+. Create an API key in the console at [fxapis.com](https://fxapis.com) and export it:

```bash
export FXAPIS_API_KEY="fx_test_..."
```

> [!WARNING]
> **Test keys reach real brokers.** An `fx_test_` key is a label for your configuration, not a sandbox. Build and test with a **broker demo account**.

## Quickstart

```python
from fxapis import Fxapis

client = Fxapis()  # reads FXAPIS_API_KEY

# 1. Connect an MT5 account (once). Use the trading password, not the investor password.
account = client.accounts.connect(
    login="26177561",
    server="VantageMarkets-Demo",
    password="your-mt5-trading-password",
    mode="warm_on_demand",  # online when needed, offline after 15 idle minutes
    label="demo — strategy A",
)

# 2. Bring it online and wait (about 10 seconds for a typical broker).
client.accounts.warm(account["id"])
client.accounts.wait_until_ready(account["id"])

# 3. Trade. Volumes and prices are strings: "0.01", not 0.01.
order = client.orders.market(
    account["id"],
    symbol="EURUSD",
    side="buy",
    volume="0.01",
    stop_loss="1.12900",
    take_profit="1.14200",
)
print(order["state"], order["filledPrice"])

# 4. Read positions, then close one.
for position in client.positions.list(account["id"]):
    print(position["symbol"], position["side"], position["volume"], position["profit"], position["observedAt"])
    client.positions.close(account["id"], position["brokerPositionId"])
```

The `with Fxapis() as client:` form closes the connection pool for you.

## Handling order outcomes

An order can end three ways that must be told apart. The SDK raises a different exception for each:

```python
from fxapis import (
    Fxapis,
    OrderRejectedError,
    OrderUnresolvedError,
    SendFailedError,
    AccountNotReadyError,
)

client = Fxapis()
key = f"signal_{signal_id}:member_{member_id}"  # your own idempotency key

try:
    order = client.orders.market(account_id, symbol="XAUUSD", side="buy", volume="0.05", idempotency_key=key)
except OrderRejectedError as err:
    # The broker refused it; nothing opened. err.retryable says whether the reason was
    # transient (a requote). A new attempt needs a NEW key — this one now answers with the rejection.
    print("rejected:", err.message)
except OrderUnresolvedError as err:
    # Nobody knows yet whether it reached the broker. NEVER resend it. Poll until fxapis
    # has confirmed the result with the broker:
    order = client.orders.wait_until_resolved(err.order_id)
except (SendFailedError, AccountNotReadyError) as err:
    # Nothing was sent. The SDK already retried with the same key (max_retries);
    # retrying later with err.idempotency_key is still safe.
    print("not sent:", err.code)
```

| Error class | API code | Retried automatically? |
|---|---|---|
| `SendFailedError` | `SEND_FAILED` (503) | Yes, same key |
| `AccountNotReadyError` / `NoRuntimeError` | `ACCOUNT_NOT_READY` / `NO_RUNTIME` (409) | Yes, same key |
| `IdempotencyInFlightError` | `IDEMPOTENCY_IN_FLIGHT` (409) | Yes, same key |
| `RateLimitedError` | `RATE_LIMITED` (429) | Yes, after `Retry-After` |
| `OrderUnresolvedError` | `ORDER_UNRESOLVED` (503) | **Never** — poll the order |
| `OrderRejectedError` | `ORDER_REJECTED` (422) | Never — needs a new key |
| `IdempotencyKeyReusedError` | `IDEMPOTENCY_KEY_REUSED` (409) | Never |
| `QuotaExceededError` / `FeatureNotInPlanError` | 402 | Never |
| `AuthenticationError`, `PermissionDeniedError`, `InvalidRequestError`, `NotFoundError` | 401 / 403 / 400 / 404 | Never |
| `APIConnectionError` / `APITimeoutError` | no HTTP answer | Reads, and requests with an idempotency key |

Every API error is an `APIStatusError` with `.status`, `.code`, `.message`, `.request_id` (quote it to support), `.details`, `.order_id`, `.idempotency_key` and `.retryable`. Tune retries with `Fxapis(max_retries=0..n)`.

**Idempotency keys.** Market orders, pending orders, closes and multi-account orders always carry an `Idempotency-Key` — a UUID unless you pass `idempotency_key=`. The API honours a key for 24 hours: the same key with the same body returns the first answer and never places a second order. Derive your own key from something stable (a signal and a member, a strategy tick) when a double click or a restarted worker must not trade twice.

## Click-to-trade and signals

For apps where each member approves a signal with a click: prepare the member's account **when they open the signal**, then place the order with a key made from the signal and the member.

```python
client.accounts.prepare([member.fxapis_account_id])  # up to 200 accounts per call; returns at once

order = client.orders.market(
    member.fxapis_account_id,
    symbol=signal.symbol,
    side=signal.side,
    volume=member.lot_size,
    stop_loss=signal.stop_loss,
    take_profit=signal.take_profit,
    client_order_id=f"signal_{signal.id}",
    idempotency_key=f"signal_{signal.id}:member_{member.id}",
)
```

The full walkthrough is in the [signals guide](https://docs.fxapis.com/signals).

## Copy trading: one trade on many accounts

A multi-account order ("execution wave") brings every account online, then sends the orders together:

```python
wave = client.waves.create(
    account_ids=follower_ids,  # up to 500
    symbol="EURUSD",
    side="buy",
    volume="0.10",
    weights={big_account_id: "0.50"},  # per-account volume, optional
    barrier_policy="release-ready",  # or "all-or-nothing", "wait"
    client_wave_id="master-deal-123456",
)
wave = client.waves.wait_until_settled(wave["id"])
print(wave["summary"], wave["dispatchSpreadMs"])
```

`client.multi_account_orders` is the same resource under a descriptive name. There are no event webhooks yet: to follow a master account, poll its deals (`client.deals.list(master_id, since=...)`) — see [`copy_trader.py`](https://github.com/FXapis/fxapis-examples/blob/main/python/copy_trader.py).

## Async

```python
import asyncio
from fxapis import AsyncFxapis


async def main() -> None:
    async with AsyncFxapis() as client:
        accounts = await client.accounts.list()
        async for order in client.orders.iter(state="unknown"):
            print(order["id"], order["symbol"])


asyncio.run(main())
```

## Reference

| Resource | Methods |
|---|---|
| `client.workspace` | `get()` |
| `client.accounts` | `connect()`, `list()`, `get()`, `status()`, `warm()`, `prepare()`, `cool()`, `restart()`, `disconnect()`, `delete()`, `set_mode()` (alias `mode()`), `replace_credentials()`, `reconcile()`, `wait_until_ready()`, `bring_online()`, `symbols()`, `instruments()`, `sessions()` (market hours), `sync_symbols()` |
| `client.instruments` | `list()` — markets named once (`XAUUSD`, `US30`…); pass one as `instrument=` to `orders.market()` / `orders.pending()` to trade each account's own broker symbol for it |
| `client.orders` | `market()`, `pending()`, `modify()`, `cancel()`, `get()`, `list()`, `iter()`, `deals()`, `wait_until_resolved()` |
| `client.positions` | `list()`, `close()`, `modify()` |
| `client.deals` | `list()`, `iter()`, `for_order()` |
| `client.calculate` | `margin()`, `profit()` |
| `client.waves` (= `client.multi_account_orders`) | `create()`, `get()`, `list()`, `cancel()`, `wait_until_settled()` |
| `client.alert_hooks` | `create()`, `list()`, `get()`, `update()`, `rotate()`, `enable()`, `disable()`, `delete()`, `deliveries()` — TradingView alerts to MT5 |
| `client.usage` | `get()`, `daily()` |
| `client.plans` | `list()` |

Notes:

- `orders.list()` and `deals.list()` return a `Page` (`.data`, `.has_more`, `.next_cursor`); `iter()` walks every page for you.
- `positions.modify(..., stop_loss=None)` **removes** the stop loss; leaving the argument out keeps it. The same holds for `orders.modify`.
- Times accept `datetime` (sent as RFC 3339 UTC) or strings. Numbers accept `str`, `Decimal`, `int` or `float` (rounded to 8 places) and are always sent as strings.
- `Fxapis(base_url=..., timeout=..., max_retries=..., http_client=httpx.Client(...))` for proxies, custom transports or tests.

Everything in the API — including API keys, members and billing — is in the [API reference](https://docs.fxapis.com/api-reference), with samples in 13 languages.

## Good to know

- **Accounts on demand** (`warm_on_demand`) come online for an order or a prepare and go offline after 15 idle minutes. Stop losses and take profits live at the broker and keep working while an account is offline.
- **Positions are a snapshot.** Each has `observedAt`; call `accounts.reconcile()` for a fresh read while the account is online.
- **Scoped keys.** Keys can be read-only or reduce-only (can close, cannot open) — give each service the least it needs.
- **Wrong password?** `accounts.replace_credentials(id, password=...)` fixes it on the same account; connecting a *disconnected* login again brings the same account back. `accounts.delete(id)` removes an account and its history for good.
- **No event webhooks yet.** Poll `status`, orders and deals. (Incoming TradingView alerts are supported — see `client.alert_hooks`.)

## Related fxapis repositories

| Repository | What it is |
|---|---|
| [`fxapis-examples`](https://github.com/FXapis/fxapis-examples) | Runnable examples using this SDK (Python, Node/TypeScript, curl) |
| [`fxapis-typescript`](https://github.com/FXapis/fxapis-typescript) | The official TypeScript/Node.js SDK, same conventions |
| [`fxapis-mcp-examples`](https://github.com/FXapis/fxapis-mcp-examples) | Connect AI agents (Claude, Cursor, VS Code) over MCP |
| [`fxapis-integrations`](https://github.com/FXapis/fxapis-integrations) | Postman collection, TradingView payloads, automation templates |

## Contributing

```bash
pip install -e ".[dev]"
ruff check .
mypy
pytest -q
```

These are exactly what the `ci` workflow runs, on Python 3.10 through 3.14. Pull requests that fix a
bug, improve a docstring, or add a test are welcome. A behaviour change to a method's signature or
return shape should match the TypeScript SDK's equivalent method — both are meant to stay in step.

## Support

- **Docs:** [docs.fxapis.com](https://docs.fxapis.com)
- **Status:** [status.fxapis.com](https://status.fxapis.com)
- **Bugs:** [open an issue](https://github.com/FXapis/fxapis-python/issues)
- **Everything else:** [support@fxapis.com](mailto:support@fxapis.com)

## License

MIT — see [LICENSE](LICENSE).

© 2026 El Wizard
