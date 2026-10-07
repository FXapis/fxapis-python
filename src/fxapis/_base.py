"""Shared, I/O-free parts of the sync and async clients.

Everything here is pure: building requests, formatting values, turning a
response into data or an exception, and deciding whether a failure may be
retried. The two clients only differ in how they send and how they sleep.
"""

from __future__ import annotations

import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Final
from urllib.parse import quote

import httpx

from ._version import __version__
from .errors import (
    APIConnectionError,
    APIStatusError,
    FxapisError,
    OrderRejectedError,
    OrderUnresolvedError,
    RateLimitedError,
    ServerError,
    error_from_response,
)
from .types import Page

DEFAULT_BASE_URL: Final = "https://api.fxapis.com"
#: An order can wait for the account to come online (up to ~45 s) and then for
#: the broker (up to ~60 s). A client timeout shorter than that turns a slow
#: fill into an ambiguous one.
DEFAULT_TIMEOUT: Final = httpx.Timeout(120.0, connect=10.0)
DEFAULT_MAX_RETRIES: Final = 2

#: States in which an account is online and can trade.
ONLINE_STATES: Final = frozenset({"ready", "executing"})
#: States only a person can fix. Polling longer tells you nothing new.
NEEDS_ATTENTION_STATES: Final = frozenset({"invalid_credentials", "needs_2fa", "needs_certificate", "trading_disabled"})
#: Order states in which the broker's answer is not known yet.
UNRESOLVED_ORDER_STATES: Final = frozenset({"unknown", "validating", "sending"})
#: Wave states after which nothing more will happen.
FINAL_WAVE_STATES: Final = frozenset({"settled", "cancelled", "abandoned"})

#: Codes that prove nothing was done, so the same request may simply be sent again.
_NOTHING_DONE: Final = frozenset(
    {"SEND_FAILED", "ACCOUNT_NOT_READY", "NO_RUNTIME", "IDEMPOTENCY_IN_FLIGHT", "RATE_LIMITED"}
)


class _Unset:
    """Marks an argument that was not passed, as distinct from ``None`` (which clears a level)."""

    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Final = _Unset()

Number = str | Decimal | int | float
Timestamp = str | datetime


@dataclass
class Request:
    method: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    json: Any = None
    idempotency_key: str | None = None
    #: How the body is returned: "data" unwraps ``{"data": ...}``, "page" builds a :class:`Page`.
    returns: str = "data"
    #: A transport failure may be retried: reads, and requests that are safe to repeat as-is.
    safe: bool = False


def resolve_api_key(api_key: str | None) -> str:
    key = api_key or os.environ.get("FXAPIS_API_KEY") or os.environ.get("FXAPIS_KEY")
    if not key:
        raise FxapisError(
            "No API key. Pass api_key=... or set FXAPIS_API_KEY. Create one in the console at https://fxapis.com."
        )
    return key


def default_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": f"fxapis-python/{__version__}",
    }


def new_idempotency_key() -> str:
    return str(uuid.uuid4())


def seg(value: str) -> str:
    """A path segment, escaped: an id is never interpolated raw into a URL."""
    return quote(str(value), safe="")


def fmt_number(value: Number) -> str:
    """Volumes and prices go to the API as strings. A float is rounded to 8 places first.

    ``0.1 + 0.2`` is ``0.30000000000000004``; sent as-is the broker would reject
    it. Rounding to the API's 8 decimal places recovers what was meant.
    """
    if isinstance(value, bool):
        raise TypeError("expected a number or a numeric string, got a bool")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        value = Decimal(repr(round(value, 8)))
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
        return text if text != "-0" else "0"
    raise TypeError(f"expected a number or a numeric string, got {type(value).__name__}")


def fmt_time(value: Timestamp) -> str:
    """RFC 3339 in UTC. A naive datetime is taken to be UTC already."""
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def compact(values: dict[str, Any]) -> dict[str, Any]:
    """Drops arguments that were not given. ``UNSET`` and ``None`` both mean "not given" here."""
    return {k: v for k, v in values.items() if v is not None and v is not UNSET}


def nullable(values: dict[str, Any]) -> dict[str, Any]:
    """Drops only ``UNSET``: ``None`` survives and is sent as JSON ``null``, which clears a level."""
    return {k: v for k, v in values.items() if v is not UNSET}


def price_or_null(value: Number | _Unset | None) -> str | _Unset | None:
    if value is UNSET or value is None:
        return value
    return fmt_number(value)  # type: ignore[arg-type]


def parse_body(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return {"error": {"code": "INVALID_RESPONSE", "message": response.text[:500]}}


def handle_response(request: Request, response: httpx.Response) -> Any:
    body = parse_body(response)
    if response.status_code >= 400:
        raise error_from_response(
            response.status_code,
            body,
            {k.lower(): v for k, v in response.headers.items()},
            idempotency_key=request.idempotency_key,
        )
    if request.returns == "page":
        body = body if isinstance(body, dict) else {}
        page = body.get("page") or {}
        return Page(
            data=list(body.get("data") or []),
            has_more=bool(page.get("hasMore")),
            next_cursor=page.get("nextCursor"),
        )
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def should_retry(request: Request, error: FxapisError) -> bool:
    """Whether the library may send this exact request again on the caller's behalf.

    Never for ``ORDER_UNRESOLVED`` -- the order may be live -- and never for a
    broker rejection, whose key now answers with that rejection. Codes proving
    nothing was done are retried; so are server errors and lost connections,
    but only for reads and for requests carrying an idempotency key, where a
    repeat returns the first answer instead of doing the work twice.
    """
    if isinstance(error, (OrderUnresolvedError, OrderRejectedError)):
        return False
    if isinstance(error, APIStatusError):
        if error.code in _NOTHING_DONE:
            return True
        if isinstance(error, ServerError):
            return request.safe or request.idempotency_key is not None
        return False
    if isinstance(error, APIConnectionError):
        return request.safe or request.idempotency_key is not None
    return False


def retry_delay(attempt: int, error: FxapisError, base: float = 0.5, cap: float = 8.0) -> float:
    retry_after = error.retry_after if isinstance(error, RateLimitedError) else None
    if retry_after is not None:
        return min(retry_after, 60.0)
    # Jitter, not a fixed schedule: clients backing off in lockstep arrive together.
    return min(cap, base * (2.0**attempt)) * (0.5 + random.random())


def build_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    if request.json is not None:
        headers["Content-Type"] = "application/json"
    if request.idempotency_key:
        headers["Idempotency-Key"] = request.idempotency_key
    return headers


def query(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, datetime):
            value = fmt_time(value)
        elif isinstance(value, bool):
            value = "true" if value else "false"
        out[key] = value
    return out


# --- request builders ---------------------------------------------------------
#
# One function per operation. Both clients call these, so a field name is
# spelled in exactly one place.


def op_workspace() -> Request:
    return Request("GET", "/v1/workspace", safe=True)


def op_connect_account(login: str | int, server: str, password: str, mode: str | None, label: str | None) -> Request:
    body = compact({"login": str(login), "server": server, "password": password, "mode": mode, "label": label})
    return Request("POST", "/v1/accounts", json=body)


def op_list_accounts() -> Request:
    return Request("GET", "/v1/accounts", safe=True)


def op_get_account(account_id: str) -> Request:
    return Request("GET", f"/v1/accounts/{seg(account_id)}", safe=True)


def op_account_status(account_id: str) -> Request:
    return Request("GET", f"/v1/accounts/{seg(account_id)}/status", safe=True)


def op_warm(account_id: str) -> Request:
    # Safe to repeat: warming an online account answers alreadyRunning: true.
    return Request("POST", f"/v1/accounts/{seg(account_id)}/warm", safe=True)


def op_prepare(account_ids: list[str]) -> Request:
    ids = list(dict.fromkeys(account_ids))
    if not ids:
        raise ValueError("prepare needs at least one account id")
    if len(ids) > 200:
        raise ValueError("prepare accepts at most 200 accounts per call; split the list")
    return Request("POST", "/v1/accounts/prepare", json={"accountIds": ids}, safe=True)


def op_cool(account_id: str) -> Request:
    return Request("POST", f"/v1/accounts/{seg(account_id)}/cool")


def op_restart(account_id: str) -> Request:
    return Request("POST", f"/v1/accounts/{seg(account_id)}/restart")


def op_disconnect(account_id: str) -> Request:
    return Request("POST", f"/v1/accounts/{seg(account_id)}/disconnect")


def op_delete_account(account_id: str, force: bool = False) -> Request:
    params = {"force": "true"} if force else {}
    return Request("DELETE", f"/v1/accounts/{seg(account_id)}", params=params)


def op_replace_credentials(account_id: str, password: str, server: str | None = None) -> Request:
    body: dict[str, Any] = {"password": password}
    if server is not None:
        body["server"] = server
    return Request("POST", f"/v1/accounts/{seg(account_id)}/password", json=body)


def op_search_servers(query: str, limit: int | None = None) -> Request:
    params = {"q": query, **({"limit": str(limit)} if limit is not None else {})}
    return Request("GET", "/v1/brokers/servers", params=params, safe=True)


def op_switch_server(account_id: str, server: str, connect: bool = True) -> Request:
    return Request("POST", f"/v1/accounts/{seg(account_id)}/server", json={"server": server, "connect": connect})


def op_account_events(account_id: str, limit: int | None = None) -> Request:
    params = {"limit": str(limit)} if limit is not None else {}
    return Request("GET", f"/v1/accounts/{seg(account_id)}/events", params=params, safe=True)


def op_list_alert_hooks() -> Request:
    return Request("GET", "/v1/alert-hooks", safe=True)


def op_create_alert_hook(name: str, account_ids: list[str], defaults: dict[str, Any] | None) -> Request:
    body: dict[str, Any] = {"name": name, "accountIds": list(account_ids)}
    if defaults is not None:
        body["defaults"] = defaults
    return Request("POST", "/v1/alert-hooks", json=body)


def op_get_alert_hook(hook_id: str) -> Request:
    return Request("GET", f"/v1/alert-hooks/{seg(hook_id)}", safe=True)


def op_update_alert_hook(
    hook_id: str, name: str | None, account_ids: list[str] | None, defaults: dict[str, Any] | None
) -> Request:
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if account_ids is not None:
        body["accountIds"] = list(account_ids)
    if defaults is not None:
        body["defaults"] = defaults
    return Request("PATCH", f"/v1/alert-hooks/{seg(hook_id)}", json=body)


def op_alert_hook_action(hook_id: str, action: str) -> Request:
    return Request("POST", f"/v1/alert-hooks/{seg(hook_id)}/{action}")


def op_delete_alert_hook(hook_id: str) -> Request:
    return Request("DELETE", f"/v1/alert-hooks/{seg(hook_id)}")


def op_alert_deliveries(hook_id: str) -> Request:
    return Request("GET", f"/v1/alert-hooks/{seg(hook_id)}/deliveries", safe=True)


def op_set_mode(account_id: str, mode: str) -> Request:
    return Request("POST", f"/v1/accounts/{seg(account_id)}/mode", json={"mode": mode})


def op_reconcile(account_id: str) -> Request:
    return Request("POST", f"/v1/accounts/{seg(account_id)}/reconcile")


def op_market_order(
    account_id: str,
    *,
    symbol: str | None,
    instrument: str | None,
    side: str,
    volume: Number,
    stop_loss: Number | None,
    take_profit: Number | None,
    deviation_points: int | None,
    comment: str | None,
    client_order_id: str | None,
    idempotency_key: str | None,
) -> Request:
    body = compact(
        {
            "symbol": symbol,
            "instrument": instrument,
            "side": side,
            "volume": fmt_number(volume),
            "stopLoss": None if stop_loss is None else fmt_number(stop_loss),
            "takeProfit": None if take_profit is None else fmt_number(take_profit),
            "deviationPoints": deviation_points,
            "comment": comment,
            "clientOrderId": client_order_id,
        }
    )
    return Request(
        "POST",
        f"/v1/accounts/{seg(account_id)}/orders/market",
        json=body,
        idempotency_key=idempotency_key or new_idempotency_key(),
    )


def op_pending_order(
    account_id: str,
    *,
    symbol: str | None,
    instrument: str | None,
    side: str,
    kind: str,
    volume: Number,
    price: Number,
    stop_limit_price: Number | None,
    stop_loss: Number | None,
    take_profit: Number | None,
    expires_at: Timestamp | None,
    comment: str | None,
    client_order_id: str | None,
    idempotency_key: str | None,
) -> Request:
    body = compact(
        {
            "symbol": symbol,
            "instrument": instrument,
            "side": side,
            "kind": kind,
            "volume": fmt_number(volume),
            "price": fmt_number(price),
            "stopLimitPrice": None if stop_limit_price is None else fmt_number(stop_limit_price),
            "stopLoss": None if stop_loss is None else fmt_number(stop_loss),
            "takeProfit": None if take_profit is None else fmt_number(take_profit),
            "expiresAt": None if expires_at is None else fmt_time(expires_at),
            "comment": comment,
            "clientOrderId": client_order_id,
        }
    )
    return Request(
        "POST",
        f"/v1/accounts/{seg(account_id)}/orders/pending",
        json=body,
        idempotency_key=idempotency_key or new_idempotency_key(),
    )


def op_modify_order(
    order_id: str,
    *,
    price: Number | None,
    stop_loss: Any,
    take_profit: Any,
    stop_limit_price: Number | None,
    expires_at: Timestamp | None,
) -> Request:
    body = nullable(
        {
            "price": UNSET if price is None else fmt_number(price),
            "stopLoss": price_or_null(stop_loss),
            "takeProfit": price_or_null(take_profit),
            "stopLimitPrice": UNSET if stop_limit_price is None else fmt_number(stop_limit_price),
            "expiresAt": UNSET if expires_at is None else fmt_time(expires_at),
        }
    )
    return Request("POST", f"/v1/orders/{seg(order_id)}/modify", json=body)


def op_cancel_order(order_id: str) -> Request:
    return Request("POST", f"/v1/orders/{seg(order_id)}/cancel")


def op_get_order(order_id: str) -> Request:
    return Request("GET", f"/v1/orders/{seg(order_id)}", safe=True)


def op_list_orders(
    *,
    account_id: str | None,
    state: str | None,
    symbol: str | None,
    since: Timestamp | None,
    until: Timestamp | None,
    limit: int | None,
    cursor: str | None,
) -> Request:
    params = query(
        {
            "accountId": account_id,
            "state": state,
            "symbol": symbol,
            "since": since,
            "until": until,
            "limit": limit,
            "cursor": cursor,
        }
    )
    return Request("GET", "/v1/orders", params=params, returns="page", safe=True)


def op_order_deals(order_id: str) -> Request:
    return Request("GET", f"/v1/orders/{seg(order_id)}/deals", safe=True)


def op_list_deals(
    account_id: str,
    *,
    symbol: str | None,
    since: Timestamp | None,
    until: Timestamp | None,
    limit: int | None,
    cursor: str | None,
) -> Request:
    params = query({"symbol": symbol, "since": since, "until": until, "limit": limit, "cursor": cursor})
    return Request("GET", f"/v1/accounts/{seg(account_id)}/deals", params=params, returns="page", safe=True)


def op_list_instruments(category: str | None) -> Request:
    return Request("GET", "/v1/instruments", params=query({"category": category}), safe=True)


def op_account_symbols(
    account_id: str, search: str | None, tradable: bool | None, limit: int | None, cursor: str | None
) -> Request:
    params = query({"search": search, "tradable": tradable, "limit": limit, "cursor": cursor})
    return Request("GET", f"/v1/accounts/{seg(account_id)}/symbols", params=params, returns="page", safe=True)


def op_account_instruments(account_id: str) -> Request:
    return Request("GET", f"/v1/accounts/{seg(account_id)}/instruments", safe=True)


def op_account_sessions(account_id: str, symbol: str | None, instrument: str | None) -> Request:
    params = query({"symbol": symbol, "instrument": instrument})
    return Request("GET", f"/v1/accounts/{seg(account_id)}/sessions", params=params, safe=True)


def op_sync_symbols(account_id: str) -> Request:
    return Request("POST", f"/v1/accounts/{seg(account_id)}/symbols/sync")


def op_list_positions(account_id: str, include_closed: bool) -> Request:
    params = {"includeClosed": "true"} if include_closed else {}
    return Request("GET", f"/v1/accounts/{seg(account_id)}/positions", params=params, safe=True)


def op_close_position(
    account_id: str,
    position_id: str | int,
    *,
    volume: Number | None,
    deviation_points: int | None,
    comment: str | None,
    client_order_id: str | None,
    idempotency_key: str | None,
) -> Request:
    body = compact(
        {
            "volume": None if volume is None else fmt_number(volume),
            "deviationPoints": deviation_points,
            "comment": comment,
            "clientOrderId": client_order_id,
        }
    )
    return Request(
        "POST",
        f"/v1/accounts/{seg(account_id)}/positions/{seg(str(position_id))}/close",
        json=body,
        idempotency_key=idempotency_key or new_idempotency_key(),
    )


def op_modify_position(account_id: str, position_id: str | int, *, stop_loss: Any, take_profit: Any) -> Request:
    body = nullable({"stopLoss": price_or_null(stop_loss), "takeProfit": price_or_null(take_profit)})
    if not body:
        raise ValueError("pass stop_loss and/or take_profit (None removes a level)")
    return Request("POST", f"/v1/accounts/{seg(account_id)}/positions/{seg(str(position_id))}/modify", json=body)


def op_calculate(
    account_id: str,
    *,
    kind: str,
    symbol: str,
    side: str,
    volume: Number,
    price: Number,
    close_price: Number | None,
) -> Request:
    body = compact(
        {
            "kind": kind,
            "symbol": symbol,
            "side": side,
            "volume": fmt_number(volume),
            "price": fmt_number(price),
            "closePrice": None if close_price is None else fmt_number(close_price),
        }
    )
    # Opens nothing, so repeating it after a lost connection is harmless.
    return Request("POST", f"/v1/accounts/{seg(account_id)}/calculate", json=body, safe=True)


def op_create_wave(
    *,
    account_ids: list[str],
    symbol: str,
    side: str,
    volume: Number,
    weights: dict[str, Number] | None,
    stop_loss: Number | None,
    take_profit: Number | None,
    comment: str | None,
    label: str | None,
    client_wave_id: str | None,
    barrier_policy: str | None,
    execute_at: Timestamp | None,
    expires_at: Timestamp | None,
    idempotency_key: str | None,
) -> Request:
    ids = list(dict.fromkeys(account_ids))
    if not ids:
        raise ValueError("a multi-account order needs at least one account id")
    if len(ids) > 500:
        raise ValueError("a multi-account order accepts at most 500 accounts")
    body = compact(
        {
            "accountIds": ids,
            "symbol": symbol,
            "side": side,
            "volume": fmt_number(volume),
            "weights": None if weights is None else {k: fmt_number(v) for k, v in weights.items()},
            "stopLoss": None if stop_loss is None else fmt_number(stop_loss),
            "takeProfit": None if take_profit is None else fmt_number(take_profit),
            "comment": comment,
            "label": label,
            "clientWaveId": client_wave_id,
            "barrierPolicy": barrier_policy,
            "executeAt": None if execute_at is None else fmt_time(execute_at),
            "expiresAt": None if expires_at is None else fmt_time(expires_at),
        }
    )
    return Request("POST", "/v1/execution-waves", json=body, idempotency_key=idempotency_key or new_idempotency_key())


def op_get_wave(wave_id: str) -> Request:
    return Request("GET", f"/v1/execution-waves/{seg(wave_id)}", safe=True)


def op_list_waves() -> Request:
    return Request("GET", "/v1/execution-waves", safe=True)


def op_cancel_wave(wave_id: str) -> Request:
    return Request("POST", f"/v1/execution-waves/{seg(wave_id)}/cancel")


def op_usage() -> Request:
    return Request("GET", "/v1/billing/usage", safe=True)


def op_usage_daily() -> Request:
    return Request("GET", "/v1/billing/usage/daily", safe=True)


def op_plans() -> Request:
    return Request("GET", "/v1/plans", safe=True)
