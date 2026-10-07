from __future__ import annotations

import inspect
from collections.abc import Callable

import httpx
import pytest

from fxapis import (
    AccountNeedsAttentionError,
    AsyncFxapis,
    Fxapis,
    OrderUnresolvedError,
    SendFailedError,
    _async_client,
    _client,
)

from .conftest import Recorder, error

ACCOUNT = "acct-1"


async def test_market_order_with_retry(api: Recorder, make_async: Callable[[], AsyncFxapis]) -> None:
    api.responses += [error("SEND_FAILED", 502), (201, {"data": {"id": "o1", "state": "filled"}})]
    async with make_async() as client:
        order = await client.orders.market(ACCOUNT, symbol="EURUSD", side="sell", volume="0.01")
    assert order["state"] == "filled"
    assert api.requests[0].headers["idempotency-key"] == api.requests[1].headers["idempotency-key"]


async def test_unresolved_not_retried(api: Recorder, make_async: Callable[[], AsyncFxapis]) -> None:
    api.responses.append(error("ORDER_UNRESOLVED", 502, details=[{"orderId": "o9"}]))
    async with make_async() as client:
        with pytest.raises(OrderUnresolvedError) as caught:
            await client.orders.market(ACCOUNT, symbol="EURUSD", side="buy", volume="0.01")
    assert len(api.requests) == 1
    assert caught.value.order_id == "o9"


async def test_retries_exhausted(api: Recorder, make_async: Callable[[], AsyncFxapis]) -> None:
    api.responses += [error("SEND_FAILED", 502)] * 3
    async with make_async() as client:
        with pytest.raises(SendFailedError):
            await client.positions.close(ACCOUNT, "123")
    assert len(api.requests) == 3


async def test_iter_pages(api: Recorder, make_async: Callable[[], AsyncFxapis]) -> None:
    api.responses += [
        (200, {"data": [{"id": "1"}], "page": {"hasMore": True, "nextCursor": "c"}}),
        (200, {"data": [{"id": "2"}], "page": {"hasMore": False, "nextCursor": None}}),
    ]
    async with make_async() as client:
        ids = [order["id"] async for order in client.orders.iter(state="unknown")]
    assert ids == ["1", "2"]
    assert api.requests[1].url.params["cursor"] == "c"


async def test_wait_until_ready(api: Recorder, make_async: Callable[[], AsyncFxapis]) -> None:
    api.responses += [(200, {"data": {"state": "connecting"}}), (200, {"data": {"state": "ready"}})]
    async with make_async() as client:
        assert (await client.accounts.wait_until_ready(ACCOUNT, poll_interval=0))["state"] == "ready"


async def test_wait_until_ready_needs_attention(api: Recorder, make_async: Callable[[], AsyncFxapis]) -> None:
    api.responses.append((200, {"data": {"state": "needs_2fa", "detail": "2FA"}}))
    async with make_async() as client:
        with pytest.raises(AccountNeedsAttentionError):
            await client.accounts.wait_until_ready(ACCOUNT, poll_interval=0)


async def test_connection_error_retried_for_prepare(api: Recorder, make_async: Callable[[], AsyncFxapis]) -> None:
    api.responses += [httpx.ConnectError("reset"), (202, {"data": [{"accountId": ACCOUNT, "result": "starting"}]})]
    async with make_async() as client:
        results = await client.accounts.prepare([ACCOUNT])
    assert results[0]["result"] == "starting"


def _public_methods(cls: type) -> dict[str, inspect.Signature]:
    return {name: inspect.signature(fn) for name, fn in vars(cls).items() if callable(fn) and not name.startswith("_")}


@pytest.mark.parametrize(
    "name", ["Workspace_", "Accounts", "Orders", "Positions", "Deals", "Calculate", "Waves", "Usage_", "Plans"]
)
def test_sync_and_async_resources_match(name: str) -> None:
    sync_methods = _public_methods(getattr(_client, name))
    async_methods = _public_methods(getattr(_async_client, name))
    assert sync_methods.keys() == async_methods.keys()
    for method, signature in sync_methods.items():
        assert list(signature.parameters) == list(async_methods[method].parameters), method
        for param in signature.parameters.values():
            assert param.default == async_methods[method].parameters[param.name].default, (method, param.name)


def test_clients_expose_the_same_resources() -> None:
    sync_client = Fxapis("k")
    async_client = AsyncFxapis("k")
    names = {n for n in vars(sync_client) if not n.startswith("_")}
    assert names == {n for n in vars(async_client) if not n.startswith("_")}
    assert async_client.multi_account_orders is async_client.waves
