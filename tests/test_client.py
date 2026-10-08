from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from fxapis import (
    AccountHasPositionsError,
    AccountInWaveError,
    AccountNeedsAttentionError,
    AccountNotReadyError,
    APIConnectionError,
    AuthenticationError,
    Fxapis,
    FxapisError,
    IdempotencyKeyReusedError,
    NotFoundError,
    OrderRejectedError,
    OrderUnresolvedError,
    Page,
    QuotaExceededError,
    RateLimitedError,
    SendFailedError,
    ServerError,
    WaitTimeoutError,
)
from fxapis._base import fmt_number, fmt_time
from fxapis.errors import error_from_response

from .conftest import Recorder, error

ACCOUNT = "0d7c1f5e-4b6a-4c1e-9f0a-2d9e8c7b6a51"
ORDER = {
    "id": "ord-1",
    "accountId": ACCOUNT,
    "symbol": "EURUSD",
    "side": "buy",
    "state": "filled",
    "filledPrice": "1.13426",
}


# -- requests -------------------------------------------------------------------


def test_sends_bearer_key_and_user_agent(client: Fxapis, api: Recorder) -> None:
    api.responses.append((200, {"data": {"id": "ws", "plan": "free"}}))
    assert client.workspace.get()["plan"] == "free"
    sent = api.requests[0]
    assert sent.headers["authorization"] == "Bearer fx_test_abc"
    assert sent.headers["user-agent"].startswith("fxapis-python/")
    assert str(sent.url) == "https://api.fxapis.com/v1/workspace"


def test_reads_key_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FXAPIS_API_KEY", "fx_live_env")
    assert Fxapis().api_key == "fx_live_env"


def test_missing_key_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FXAPIS_API_KEY", raising=False)
    monkeypatch.delenv("FXAPIS_KEY", raising=False)
    with pytest.raises(FxapisError, match="FXAPIS_API_KEY"):
        Fxapis()


def test_escapes_path_parameters(client: Fxapis, api: Recorder) -> None:
    api.responses.append((200, {"data": {}}))
    client.accounts.get("a/../b")
    assert api.requests[0].url.raw_path == b"/v1/accounts/a%2F..%2Fb"


def test_connect_account_uses_spec_field_names(client: Fxapis, api: Recorder) -> None:
    api.responses.append((201, {"data": {"id": ACCOUNT, "state": "created"}}))
    client.accounts.connect(login=26177561, server="VantageMarkets-Demo", password="pw", mode="warm_on_demand")
    assert api.body() == {
        "login": "26177561",
        "server": "VantageMarkets-Demo",
        "password": "pw",
        "mode": "warm_on_demand",
    }


def test_market_order_body_and_automatic_idempotency_key(client: Fxapis, api: Recorder) -> None:
    api.responses.append((201, {"data": ORDER}))
    order = client.orders.market(
        ACCOUNT,
        symbol="EURUSD",
        side="buy",
        volume=0.1 + 0.2,
        stop_loss=Decimal("1.12900"),
        take_profit="1.14200",
        deviation_points=20,
        client_order_id="sig-42",
    )
    assert order["state"] == "filled"
    assert api.body() == {
        "symbol": "EURUSD",
        "side": "buy",
        "volume": "0.3",
        "stopLoss": "1.129",
        "takeProfit": "1.14200",
        "deviationPoints": 20,
        "clientOrderId": "sig-42",
    }
    uuid.UUID(api.requests[0].headers["idempotency-key"])  # a real UUID


def test_idempotency_key_override(client: Fxapis, api: Recorder) -> None:
    api.responses.append((201, {"data": ORDER}))
    client.orders.market(ACCOUNT, symbol="XAUUSD", side="buy", volume="0.05", idempotency_key="signal_9931:member_4821")
    assert api.requests[0].headers["idempotency-key"] == "signal_9931:member_4821"


def test_each_order_gets_its_own_key(client: Fxapis, api: Recorder) -> None:
    api.responses += [(201, {"data": ORDER}), (201, {"data": ORDER})]
    client.orders.market(ACCOUNT, symbol="EURUSD", side="buy", volume="0.01")
    client.orders.market(ACCOUNT, symbol="EURUSD", side="buy", volume="0.01")
    assert api.requests[0].headers["idempotency-key"] != api.requests[1].headers["idempotency-key"]


def test_pending_order(client: Fxapis, api: Recorder) -> None:
    api.responses.append((201, {"data": {**ORDER, "type": "stop_limit", "state": "accepted"}}))
    client.orders.pending(
        ACCOUNT,
        symbol="EURUSD",
        side="buy",
        kind="stop_limit",
        volume="0.01",
        price="1.12800",
        stop_limit_price="1.12780",
        expires_at=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
    )
    assert api.requests[0].url.path == f"/v1/accounts/{ACCOUNT}/orders/pending"
    assert api.body()["stopLimitPrice"] == "1.12780"
    assert api.body()["expiresAt"] == "2026-10-01T12:00:00Z"
    assert "idempotency-key" in api.requests[0].headers


def test_close_always_carries_a_key(client: Fxapis, api: Recorder) -> None:
    api.responses.append((201, {"data": {**ORDER, "intent": "close"}}))
    client.positions.close(ACCOUNT, 123456789, volume="0.02")
    assert api.requests[0].url.path == f"/v1/accounts/{ACCOUNT}/positions/123456789/close"
    assert api.body() == {"volume": "0.02"}
    assert api.requests[0].headers["idempotency-key"]


def test_close_whole_position_sends_empty_object(client: Fxapis, api: Recorder) -> None:
    api.responses.append((201, {"data": ORDER}))
    client.positions.close(ACCOUNT, "123")
    assert api.body() == {}


def test_modify_position_none_clears_and_omitted_keeps(client: Fxapis, api: Recorder) -> None:
    api.responses.append((201, {"data": ORDER}))
    client.positions.modify(ACCOUNT, "123", stop_loss=None)
    assert api.body() == {"stopLoss": None}


def test_modify_position_needs_a_level() -> None:
    client = Fxapis("k")
    with pytest.raises(ValueError):
        client.positions.modify(ACCOUNT, "123")


def test_modify_order(client: Fxapis, api: Recorder) -> None:
    api.responses.append((201, {"data": ORDER}))
    client.orders.modify("ord-1", price="1.12750", take_profit=None)
    assert api.body() == {"price": "1.12750", "takeProfit": None}


def test_calculate(client: Fxapis, api: Recorder) -> None:
    api.responses.append((200, {"data": {"kind": "profit", "value": "50.00"}}))
    result = client.calculate.profit(
        ACCOUNT, symbol="EURUSD", side="buy", volume="0.10", price="1.13426", close_price="1.13926"
    )
    assert result["value"] == "50.00"
    assert api.body() == {
        "kind": "profit",
        "symbol": "EURUSD",
        "side": "buy",
        "volume": "0.10",
        "price": "1.13426",
        "closePrice": "1.13926",
    }


def test_prepare_dedupes_and_limits() -> None:
    client = Fxapis("k")
    with pytest.raises(ValueError, match="200"):
        client.accounts.prepare([str(i) for i in range(201)])
    with pytest.raises(ValueError):
        client.accounts.prepare([])


def test_prepare(client: Fxapis, api: Recorder) -> None:
    api.responses.append((202, {"data": [{"accountId": ACCOUNT, "result": "starting"}]}))
    results = client.accounts.prepare([ACCOUNT, ACCOUNT])
    assert results[0]["result"] == "starting"
    assert api.body() == {"accountIds": [ACCOUNT]}


def test_lifecycle_paths(client: Fxapis, api: Recorder) -> None:
    api.responses += [
        (202, {"data": {}}),
        (200, {"data": {}}),
        (200, {"data": {}}),
        (200, {"data": {}}),
        (202, {"data": {}}),
    ]
    client.accounts.warm(ACCOUNT)
    client.accounts.cool(ACCOUNT)
    client.accounts.disconnect(ACCOUNT)
    client.accounts.mode(ACCOUNT, "always_on")
    client.accounts.restart(ACCOUNT)
    assert [r.url.path.rsplit("/", 1)[1] for r in api.requests] == ["warm", "cool", "disconnect", "mode", "restart"]
    assert api.body(3) == {"mode": "always_on"}


def test_instruments_and_symbols(client: Fxapis, api: Recorder) -> None:
    api.responses += [
        (200, {"data": [{"instrument": "XAUUSD", "name": "Gold vs US Dollar", "category": "metals"}]}),
        (200, {"data": [{"name": "XAUUSD.a", "tradable": True}], "page": {"hasMore": True, "nextCursor": "200"}}),
        (200, {"data": [{"instrument": "XAUUSD", "status": "mapped", "symbol": "XAUUSD.a"}]}),
        (200, {"data": {"symbolCount": 812}}),
    ]
    assert client.instruments.list(category="metals")[0]["instrument"] == "XAUUSD"
    page = client.accounts.symbols(ACCOUNT, search="gold", tradable=True)
    assert page.has_more and page.next_cursor == "200"
    assert client.accounts.instruments(ACCOUNT)[0]["symbol"] == "XAUUSD.a"
    assert client.accounts.sync_symbols(ACCOUNT)["symbolCount"] == 812
    assert api.requests[0].url.params["category"] == "metals"
    assert api.requests[1].url.path == f"/v1/accounts/{ACCOUNT}/symbols"
    assert api.requests[1].url.params["search"] == "gold" and api.requests[1].url.params["tradable"] == "true"
    assert api.requests[3].method == "POST"


def test_market_hours(client: Fxapis, api: Recorder) -> None:
    hours_body = {"symbol": "XAUUSD.a", "instrument": "XAUUSD", "openNow": False, "nextOpen": "2026-10-04T22:01:00Z"}
    api.responses.append((200, {"data": hours_body}))
    hours = client.accounts.sessions(ACCOUNT, instrument="XAUUSD")
    assert hours["openNow"] is False and hours["nextOpen"]
    assert api.requests[0].url.path == f"/v1/accounts/{ACCOUNT}/sessions"
    assert api.requests[0].url.params["instrument"] == "XAUUSD"
    with pytest.raises(ValueError):
        client.accounts.sessions(ACCOUNT)


def test_an_order_can_name_an_instrument(client: Fxapis, api: Recorder) -> None:
    api.responses.append((201, {"data": {"id": "o1", "symbol": "XAUUSD.a", "instrument": "XAUUSD"}}))
    order = client.orders.market(ACCOUNT, instrument="XAUUSD", side="buy", volume="0.01")
    assert order["symbol"] == "XAUUSD.a"
    body = api.body()
    assert body["instrument"] == "XAUUSD" and "symbol" not in body


def test_an_order_names_a_symbol_or_an_instrument_not_both(client: Fxapis) -> None:
    with pytest.raises(ValueError):
        client.orders.market(ACCOUNT, symbol="XAUUSD.a", instrument="XAUUSD", side="buy", volume="0.01")
    with pytest.raises(ValueError):
        client.orders.market(ACCOUNT, side="buy", volume="0.01")


def test_delete_account(client: Fxapis, api: Recorder) -> None:
    removed = {"orders": 3, "deals": 2, "positions": 1, "alertHooksUpdated": 0}
    api.responses += [(200, {"data": {"accountId": ACCOUNT, "deleted": True, "removed": removed}})] * 2
    result = client.accounts.delete(ACCOUNT)
    client.accounts.delete(ACCOUNT, force=True)
    assert result["removed"]["orders"] == 3
    assert [r.method for r in api.requests] == ["DELETE", "DELETE"]
    assert api.requests[0].url.path == f"/v1/accounts/{ACCOUNT}"
    assert "force" not in api.requests[0].url.params
    assert api.requests[1].url.params["force"] == "true"


def test_positions_include_closed(client: Fxapis, api: Recorder) -> None:
    api.responses += [(200, {"data": []}), (200, {"data": []})]
    client.positions.list(ACCOUNT)
    client.positions.list(ACCOUNT, include_closed=True)
    assert "includeClosed" not in api.requests[0].url.params
    assert api.requests[1].url.params["includeClosed"] == "true"


# -- errors ---------------------------------------------------------------------


def test_order_unresolved_is_never_retried(client: Fxapis, api: Recorder) -> None:
    api.responses.append(
        error("ORDER_UNRESOLVED", 502, details=[{"orderId": "ord-9", "state": "unknown", "retryable": False}])
    )
    with pytest.raises(OrderUnresolvedError) as caught:
        client.orders.market(ACCOUNT, symbol="EURUSD", side="buy", volume="0.01", idempotency_key="k1")
    assert len(api.requests) == 1
    err = caught.value
    assert err.order_id == "ord-9"
    assert err.retryable is False
    assert err.idempotency_key == "k1"
    assert err.request_id == "req-1"


def test_unresolved_stays_unretryable_even_if_details_say_otherwise() -> None:
    err = error_from_response(
        502, {"error": {"code": "ORDER_UNRESOLVED", "message": "?", "details": [{"retryable": True}]}}
    )
    assert isinstance(err, OrderUnresolvedError)
    assert err.retryable is False


def test_send_failed_is_retried_with_the_same_key(client: Fxapis, api: Recorder) -> None:
    api.responses += [error("SEND_FAILED", 502), (201, {"data": ORDER})]
    order = client.orders.market(ACCOUNT, symbol="EURUSD", side="buy", volume="0.01")
    assert order["id"] == "ord-1"
    assert len(api.requests) == 2
    assert api.requests[0].headers["idempotency-key"] == api.requests[1].headers["idempotency-key"]
    assert api.requests[0].content == api.requests[1].content


def test_account_not_ready_retries_then_raises(client: Fxapis, api: Recorder) -> None:
    api.responses += [error("ACCOUNT_NOT_READY", 409)] * 3
    with pytest.raises(AccountNotReadyError) as caught:
        client.orders.market(ACCOUNT, symbol="EURUSD", side="buy", volume="0.01", idempotency_key="same")
    assert len(api.requests) == 3  # 1 + max_retries (2)
    assert {r.headers["idempotency-key"] for r in api.requests} == {"same"}
    assert caught.value.retryable is True


def test_rejection_is_not_retried(client: Fxapis, api: Recorder) -> None:
    api.responses.append(
        error("ORDER_REJECTED", 422, details=[{"orderId": "ord-2", "state": "rejected", "retryable": True}])
    )
    with pytest.raises(OrderRejectedError) as caught:
        client.orders.market(ACCOUNT, symbol="EURUSD", side="buy", volume="0.01")
    assert len(api.requests) == 1
    assert caught.value.retryable is True  # a new attempt (new key) may succeed


def test_max_retries_zero(api: Recorder) -> None:
    http = httpx.Client(transport=httpx.MockTransport(api.handler))
    client = Fxapis("k", http_client=http, max_retries=0)
    api.responses.append(error("SEND_FAILED", 502))
    with pytest.raises(SendFailedError):
        client.orders.market(ACCOUNT, symbol="EURUSD", side="buy", volume="0.01")
    assert len(api.requests) == 1


def test_server_error_retried_on_reads(client: Fxapis, api: Recorder) -> None:
    api.responses += [error("INTERNAL_ERROR", 500), (200, {"data": []})]
    assert client.accounts.list() == []
    assert len(api.requests) == 2


def test_server_error_not_retried_on_unkeyed_writes(client: Fxapis, api: Recorder) -> None:
    api.responses.append(error("INTERNAL_ERROR", 500))
    with pytest.raises(ServerError):
        client.accounts.cool(ACCOUNT)
    assert len(api.requests) == 1


def test_connection_error_retried_for_keyed_order(client: Fxapis, api: Recorder) -> None:
    api.responses += [httpx.ConnectError("reset"), (201, {"data": ORDER})]
    client.orders.market(ACCOUNT, symbol="EURUSD", side="buy", volume="0.01")
    assert len(api.requests) == 2
    assert api.requests[0].headers["idempotency-key"] == api.requests[1].headers["idempotency-key"]


def test_connection_error_not_retried_for_unkeyed_write(client: Fxapis, api: Recorder) -> None:
    api.responses.append(httpx.ConnectError("reset"))
    with pytest.raises(APIConnectionError):
        client.orders.cancel("ord-1")
    assert len(api.requests) == 1


def test_timeout_surfaces_key_for_a_manual_retry(api: Recorder) -> None:
    http = httpx.Client(transport=httpx.MockTransport(api.handler))
    client = Fxapis("k", http_client=http, max_retries=0)
    api.responses.append(httpx.ReadTimeout("slow"))
    with pytest.raises(APIConnectionError) as caught:
        client.orders.market(ACCOUNT, symbol="EURUSD", side="buy", volume="0.01", idempotency_key="abc")
    assert caught.value.idempotency_key == "abc"


def test_rate_limit_uses_retry_after(client: Fxapis, api: Recorder) -> None:
    api.responses += [(*error("RATE_LIMITED", 429), {"retry-after": "3"}), (200, {"data": []})]
    client.accounts.list()
    assert len(api.requests) == 2
    err = error_from_response(429, {"error": {"code": "RATE_LIMITED", "message": "slow"}}, {"retry-after": "3"})
    assert isinstance(err, RateLimitedError)
    assert err.retry_after == 3.0


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (401, "UNAUTHENTICATED", AuthenticationError),
        (404, "ACCOUNT_NOT_FOUND", NotFoundError),
        (402, "QUOTA_EXCEEDED", QuotaExceededError),
        (409, "IDEMPOTENCY_KEY_REUSED", IdempotencyKeyReusedError),
        (409, "ACCOUNT_HAS_POSITIONS", AccountHasPositionsError),
        (409, "ACCOUNT_IN_WAVE", AccountInWaveError),
        (404, "SOMETHING_NEW", NotFoundError),
        (503, "SOMETHING_ELSE", ServerError),
    ],
)
def test_error_mapping(status: int, code: str, cls: type) -> None:
    err = error_from_response(status, {"error": {"code": code, "message": "m"}, "requestId": "r"})
    assert type(err) is cls
    assert err.code == code
    assert err.status == status
    assert "r" in str(err)


def test_non_json_error_body(client: Fxapis, api: Recorder) -> None:
    api.responses.append(lambda request: httpx.Response(418, text="teapot"))
    with pytest.raises(FxapisError) as caught:
        client.workspace.get()
    assert caught.value.status == 418  # type: ignore[attr-defined]


# -- helpers --------------------------------------------------------------------


def test_wait_until_ready(client: Fxapis, api: Recorder) -> None:
    api.responses += [
        (200, {"data": {"id": ACCOUNT, "state": "starting"}}),
        (200, {"data": {"id": ACCOUNT, "state": "synchronizing"}}),
        (200, {"data": {"id": ACCOUNT, "state": "ready"}}),
    ]
    status = client.accounts.wait_until_ready(ACCOUNT, poll_interval=0)
    assert status["state"] == "ready"
    assert len(api.requests) == 3


def test_wait_until_ready_stops_on_needs_attention(client: Fxapis, api: Recorder) -> None:
    api.responses += [
        (200, {"data": {"id": ACCOUNT, "state": "connecting"}}),
        (200, {"data": {"id": ACCOUNT, "state": "invalid_credentials", "detail": "wrong password"}}),
    ]
    with pytest.raises(AccountNeedsAttentionError) as caught:
        client.accounts.wait_until_ready(ACCOUNT, poll_interval=0)
    assert caught.value.state == "invalid_credentials"
    assert caught.value.detail == "wrong password"


def test_wait_until_ready_times_out(client: Fxapis, api: Recorder) -> None:
    api.responses += [(200, {"data": {"id": ACCOUNT, "state": "starting"}})]
    with pytest.raises(WaitTimeoutError) as caught:
        client.accounts.wait_until_ready(ACCOUNT, timeout=0.01, poll_interval=1)
    assert caught.value.last["state"] == "starting"
    assert isinstance(caught.value, TimeoutError)


def test_bring_online(client: Fxapis, api: Recorder) -> None:
    api.responses += [(202, {"data": {"pollUrl": "/v1/accounts/x/status"}}), (200, {"data": {"state": "ready"}})]
    assert client.accounts.bring_online(ACCOUNT, poll_interval=0)["state"] == "ready"


def test_wait_until_resolved(client: Fxapis, api: Recorder) -> None:
    api.responses += [(200, {"data": {**ORDER, "state": "unknown"}}), (200, {"data": {**ORDER, "state": "filled"}})]
    assert client.orders.wait_until_resolved("ord-1", poll_interval=0)["state"] == "filled"


def test_orders_pagination(client: Fxapis, api: Recorder) -> None:
    api.responses += [
        (
            200,
            {"data": [{"id": "1"}, {"id": "2"}], "page": {"hasMore": True, "nextCursor": "2026-09-30T10:00:00.000Z"}},
        ),
        (200, {"data": [{"id": "3"}], "page": {"hasMore": False, "nextCursor": None}}),
    ]
    since = datetime(2026, 9, 1, tzinfo=timezone(timedelta(hours=-6)))
    ids = [o["id"] for o in client.orders.iter(account_id=ACCOUNT, state="filled", since=since, page_size=2)]
    assert ids == ["1", "2", "3"]
    first, second = api.requests
    assert first.url.params["accountId"] == ACCOUNT
    assert first.url.params["state"] == "filled"
    assert first.url.params["since"] == "2026-09-01T06:00:00Z"
    assert first.url.params["limit"] == "2"
    assert "cursor" not in first.url.params
    assert second.url.params["cursor"] == "2026-09-30T10:00:00.000Z"


def test_list_returns_a_page(client: Fxapis, api: Recorder) -> None:
    api.responses.append((200, {"data": [{"id": "d1"}], "page": {"hasMore": False, "nextCursor": None}}))
    page = client.deals.list(ACCOUNT, symbol="EURUSD", limit=10)
    assert isinstance(page, Page)
    assert len(page) == 1
    assert [d["id"] for d in page] == ["d1"]
    assert page.has_more is False
    assert api.requests[0].url.path == f"/v1/accounts/{ACCOUNT}/deals"


def test_deals_iter(client: Fxapis, api: Recorder) -> None:
    api.responses += [
        (200, {"data": [{"id": "d1"}], "page": {"hasMore": True, "nextCursor": "c1"}}),
        (200, {"data": [{"id": "d2"}], "page": {"hasMore": False, "nextCursor": None}}),
    ]
    assert [d["id"] for d in client.deals.iter(ACCOUNT)] == ["d1", "d2"]


def test_wave_accepts_up_to_1000_accounts(client: Fxapis, api: Recorder) -> None:
    api.responses.append((201, {"data": {"id": "w1", "state": "planned"}}))
    ids = [f"acc-{i}" for i in range(1000)]
    client.multi_account_orders.create(account_ids=ids, symbol="EURUSD", side="buy", volume="0.01")
    with pytest.raises(ValueError, match="1,000"):
        client.multi_account_orders.create(account_ids=[*ids, "one-more"], symbol="EURUSD", side="buy", volume="0.01")


def test_busy_account_is_retried_since_nothing_was_done(client: Fxapis, api: Recorder) -> None:
    api.responses += [error("ACCOUNT_LEASED_ELSEWHERE", 409), (200, {"data": []})]
    assert client.accounts.list() == []
    assert len(api.requests) == 2


def test_wave_create_and_settle(client: Fxapis, api: Recorder) -> None:
    wave = {"id": "w1", "state": "planned"}
    api.responses += [
        (201, {"data": wave}),
        (200, {"data": {**wave, "state": "releasing"}}),
        (200, {"data": {**wave, "state": "settled", "summary": {"total": 2, "filled": 2}}}),
    ]
    created = client.multi_account_orders.create(
        account_ids=["a", "b", "a"],
        symbol="EURUSD",
        side="buy",
        volume="0.10",
        weights={"b": Decimal("0.50")},
        client_wave_id="master-1",
        barrier_policy="all-or-nothing",
        execute_at="2026-10-01T07:00:00Z",
    )
    assert created["id"] == "w1"
    assert api.body(0) == {
        "accountIds": ["a", "b"],
        "symbol": "EURUSD",
        "side": "buy",
        "volume": "0.10",
        "weights": {"b": "0.5"},
        "clientWaveId": "master-1",
        "barrierPolicy": "all-or-nothing",
        "executeAt": "2026-10-01T07:00:00Z",
    }
    assert api.requests[0].headers["idempotency-key"]
    settled = client.waves.wait_until_settled("w1", poll_interval=0)
    assert settled["summary"]["filled"] == 2


def test_wave_cancel_and_list(client: Fxapis, api: Recorder) -> None:
    api.responses += [(200, {"data": {"id": "w1", "state": "cancelled"}}), (200, {"data": []})]
    assert client.waves.cancel("w1")["state"] == "cancelled"
    assert client.waves.list() == []
    assert api.requests[0].url.path == "/v1/execution-waves/w1/cancel"


def test_usage(client: Fxapis, api: Recorder) -> None:
    api.responses += [(200, {"data": {"plan": "starter", "usage": {"orders": 3}}}), (200, {"data": []})]
    assert client.usage.get()["usage"]["orders"] == 3
    client.usage.daily()
    assert [r.url.path for r in api.requests] == ["/v1/billing/usage", "/v1/billing/usage/daily"]


# -- formatting -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.10", "0.10"), (1, "1"), (0.1, "0.1"), (0.1 + 0.2, "0.3"), (1e-05, "0.00001"), (Decimal("2338.50"), "2338.5")],
)
def test_fmt_number(value: object, expected: str) -> None:
    assert fmt_number(value) == expected  # type: ignore[arg-type]


def test_fmt_number_rejects_bool() -> None:
    with pytest.raises(TypeError):
        fmt_number(True)


def test_fmt_time_naive_is_utc() -> None:
    assert fmt_time(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05Z"


def test_replace_credentials_sends_password_and_optional_server(client: Fxapis, api: Recorder) -> None:
    api.responses.append((200, {"data": {"id": ACCOUNT, "state": "created"}}))
    account = client.accounts.replace_credentials(ACCOUNT, password="new-pw", server="Broker-Live")
    assert account["state"] == "created"
    request = api.requests[-1]
    assert request.method == "POST"
    assert request.url.path == f"/v1/accounts/{ACCOUNT}/password"
    assert api.body() == {"password": "new-pw", "server": "Broker-Live"}


def test_switch_server_keeps_the_password_and_events_read_the_history(client: Fxapis, api: Recorder) -> None:
    api.responses.append(
        (200, {"data": {"id": ACCOUNT, "server": "Broker-Demo", "state": "starting", "problem": None}})
    )
    account = client.accounts.switch_server(ACCOUNT, server="Broker-Demo")
    assert account["server"] == "Broker-Demo"
    request = api.requests[-1]
    assert (request.method, request.url.path) == ("POST", f"/v1/accounts/{ACCOUNT}/server")
    assert api.body() == {"server": "Broker-Demo", "connect": True}

    api.responses.append((200, {"data": [{"id": "e1", "title": "Moved to Broker-Demo", "tone": "info", "by": "key"}]}))
    events = client.accounts.events(ACCOUNT, limit=10)
    assert events[0]["title"] == "Moved to Broker-Demo"
    request = api.requests[-1]
    assert (request.method, request.url.path, request.url.params.get("limit")) == (
        "GET",
        f"/v1/accounts/{ACCOUNT}/events",
        "10",
    )


def test_search_servers_sends_the_query(client: Fxapis, api: Recorder) -> None:
    api.responses.append(
        (200, {"data": [{"name": "JustMarkets-Demo", "company": "JustMarkets Ltd", "kind": "demo", "proven": True}]})
    )
    servers = client.accounts.search_servers("justmarkets", limit=5)
    assert servers[0]["name"] == "JustMarkets-Demo"
    request = api.requests[-1]
    assert (request.method, request.url.path) == ("GET", "/v1/brokers/servers")
    assert (request.url.params.get("q"), request.url.params.get("limit")) == ("justmarkets", "5")


def test_alert_hooks_create_update_rotate_and_deliveries(client: Fxapis, api: Recorder) -> None:
    hook = {
        "id": "h1",
        "name": "Gold",
        "accountIds": [ACCOUNT],
        "enabled": True,
        "url": "https://api.fxapis.com/hooks/tradingview/secret",
    }
    api.responses.extend(
        [
            (201, {"data": hook}),
            (200, {"data": {**hook, "name": "Gold 2"}}),
            (200, {"data": hook}),
            (200, {"data": [{"id": "d1", "status": "accepted", "orderIds": ["o1"]}]}),
        ]
    )
    created = client.alert_hooks.create(
        name="Gold", account_ids=[ACCOUNT], defaults={"volume": "0.01", "symbolSuffix": ".a"}
    )
    assert created["url"].startswith("https://api.fxapis.com/hooks/tradingview/")
    assert api.body(0) == {
        "name": "Gold",
        "accountIds": [ACCOUNT],
        "defaults": {"volume": "0.01", "symbolSuffix": ".a"},
    }

    client.alert_hooks.update("h1", name="Gold 2")
    assert api.requests[1].method == "PATCH" and api.body(1) == {"name": "Gold 2"}

    client.alert_hooks.rotate("h1")
    assert api.requests[2].url.path == "/v1/alert-hooks/h1/rotate"

    deliveries = client.alert_hooks.deliveries("h1")
    assert deliveries[0]["status"] == "accepted"
