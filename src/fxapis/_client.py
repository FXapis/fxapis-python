"""The synchronous client. ``_async_client.py`` mirrors it method for method."""

from __future__ import annotations

import builtins
import time
from collections.abc import Iterator
from typing import Any, cast

import httpx

from . import _base as b
from ._base import UNSET, Number, Request, Timestamp
from .errors import AccountNeedsAttentionError, APIConnectionError, APITimeoutError, FxapisError, WaitTimeoutError
from .types import (
    Account,
    AccountEvent,
    AccountMode,
    AccountStatus,
    AlertDelivery,
    AlertHook,
    AlertHookDefaults,
    BarrierPolicy,
    BrokerServer,
    BrokerSymbol,
    CalculateResult,
    CoolResult,
    Deal,
    DeleteResult,
    DisconnectResult,
    Instrument,
    InstrumentMapping,
    MarketHours,
    ModeResult,
    Order,
    OrderState,
    Page,
    PendingKind,
    Plan,
    Position,
    PrepareResult,
    ReconcileResult,
    Side,
    SymbolsSynced,
    Usage,
    UsageDay,
    WarmResult,
    Wave,
    Workspace,
)

__all__ = ["Fxapis"]


class Fxapis:
    """Client for the fxapis MetaTrader 5 REST API.

    >>> from fxapis import Fxapis
    >>> client = Fxapis()  # reads FXAPIS_API_KEY
    >>> client.workspace.get()["plan"]

    Every trading call carries an ``Idempotency-Key``: generated for you, or
    the one you pass. A retry with the same key returns the first answer and
    never places a second order. The client retries, with that same key, only
    failures that prove nothing was done (``SEND_FAILED``,
    ``ACCOUNT_NOT_READY``, ``NO_RUNTIME``, ``IDEMPOTENCY_IN_FLIGHT``,
    ``RATE_LIMITED``) and lost connections. It never retries
    ``ORDER_UNRESOLVED`` or a broker rejection.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = b.DEFAULT_BASE_URL,
        timeout: float | httpx.Timeout = b.DEFAULT_TIMEOUT,
        max_retries: int = b.DEFAULT_MAX_RETRIES,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = b.resolve_api_key(api_key)
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, max_retries)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        self._headers = b.default_headers(self.api_key)

        self.workspace = Workspace_(self)
        self.accounts = Accounts(self)
        self.orders = Orders(self)
        self.instruments = Instruments(self)
        self.positions = Positions(self)
        self.deals = Deals(self)
        self.calculate = Calculate(self)
        self.waves = Waves(self)
        self.alert_hooks = AlertHooks(self)
        #: The same as ``waves``: one trade placed on many accounts at once.
        self.multi_account_orders = self.waves
        self.usage = Usage_(self)
        self.plans = Plans(self)

    # -- lifecycle -------------------------------------------------------------

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Fxapis:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- transport -------------------------------------------------------------

    def _send(self, request: Request) -> Any:
        attempt = 0
        while True:
            try:
                response = self._http.request(
                    request.method,
                    self.base_url + request.path,
                    params=request.params or None,
                    json=request.json,
                    headers={**self._headers, **b.build_headers(request)},
                )
                return b.handle_response(request, response)
            except FxapisError as error:
                failure: FxapisError = error
                cause: BaseException | None = None
            except httpx.TimeoutException as exc:
                failure = APITimeoutError(
                    f"no answer within the timeout: {exc}", idempotency_key=request.idempotency_key
                )
                cause = exc
            except httpx.TransportError as exc:
                failure = APIConnectionError(f"connection failed: {exc}", idempotency_key=request.idempotency_key)
                cause = exc
            if attempt >= self.max_retries or not b.should_retry(request, failure):
                if cause is None:
                    raise failure
                raise failure from cause
            time.sleep(b.retry_delay(attempt, failure))
            attempt += 1


def _one_target(symbol: str | None, instrument: str | None) -> str | None:
    """An order names the broker's symbol or an instrument: exactly one."""
    if (symbol is None) == (instrument is None):
        raise ValueError("Pass either symbol= (the broker's own name) or instrument= (e.g. 'XAUUSD'), not both.")
    return instrument


class _Resource:
    def __init__(self, client: Fxapis) -> None:
        self._client = client


class Workspace_(_Resource):
    def get(self) -> Workspace:
        """The workspace this key belongs to: its plan, and whether trading is switched off."""
        return cast(Workspace, self._client._send(b.op_workspace()))


class Accounts(_Resource):
    """Connect MT5 accounts and bring them online or offline."""

    def connect(
        self,
        *,
        login: str | int,
        server: str,
        password: str,
        mode: AccountMode | None = None,
        label: str | None = None,
    ) -> Account:
        """Stores an MT5 account. It does not log in yet: the account starts in ``created``.

        Send the **trading** password, not the investor password. It is
        encrypted on arrival and never returned. ``mode`` defaults to ``cold``
        on the API; ``warm_on_demand`` connects on the first order or prepare
        and goes offline by itself after 15 idle minutes.
        """
        return cast(Account, self._client._send(b.op_connect_account(login, server, password, mode, label)))

    def list(self) -> builtins.list[Account]:
        """Every account in this workspace, newest first."""
        return cast("builtins.list[Account]", self._client._send(b.op_list_accounts()))

    def get(self, account_id: str) -> Account:
        return cast(Account, self._client._send(b.op_get_account(account_id)))

    def status(self, account_id: str) -> AccountStatus:
        """Lifecycle state. Cheap enough to poll every second or two."""
        return cast(AccountStatus, self._client._send(b.op_account_status(account_id)))

    def warm(self, account_id: str) -> WarmResult:
        """Starts bringing the account online and returns at once (HTTP 202). Then ``wait_until_ready``."""
        return cast(WarmResult, self._client._send(b.op_warm(account_id)))

    def prepare(self, account_ids: builtins.list[str]) -> builtins.list[PrepareResult]:
        """Brings up to 200 accounts online in one call, for a signal about to be acted on."""
        return cast("builtins.list[PrepareResult]", self._client._send(b.op_prepare(account_ids)))

    def cool(self, account_id: str) -> CoolResult:
        """Takes the account offline, keeping its stored password. Open positions and their stops are untouched."""
        return cast(CoolResult, self._client._send(b.op_cool(account_id)))

    def restart(self, account_id: str) -> WarmResult:
        """Restarts the connection of an account that is online but misbehaving. Then ``wait_until_ready``."""
        return cast(WarmResult, self._client._send(b.op_restart(account_id)))

    def disconnect(self, account_id: str) -> DisconnectResult:
        """Takes the account offline and **deletes the stored password**. History is kept."""
        return cast(DisconnectResult, self._client._send(b.op_disconnect(account_id)))

    def delete(self, account_id: str, *, force: bool = False) -> DeleteResult:
        """Deletes the account **and its history** for good. Cannot be undone.

        Stops its terminal, erases its password, and removes its orders, deals and positions.
        Refused (:class:`AccountHasPositionsError`) while it has open positions unless ``force=True``
        -- they stay open at the broker, but can no longer be shown or closed here -- and
        (:class:`AccountExecutingError`, :class:`AccountInWaveError`) while an order or an unfinished
        multi-account order involves it. To keep the history, use ``disconnect`` instead.
        """
        return cast(DeleteResult, self._client._send(b.op_delete_account(account_id, force)))

    def symbols(
        self,
        account_id: str,
        *,
        search: str | None = None,
        tradable: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[BrokerSymbol]:
        """The symbols this account's broker offers, with contract specifications.

        Read from the broker when the account was last online, so it answers while
        it is offline. Raises :class:`ConflictError` (``SYMBOLS_NOT_SYNCED``) for an
        account that has never been online.
        """
        request = b.op_account_symbols(account_id, search, tradable, limit, cursor)
        return cast(Page[BrokerSymbol], self._client._send(request))

    def instruments(self, account_id: str) -> builtins.list[InstrumentMapping]:
        """How each instrument maps onto this account's broker: ``mapped``, ``ambiguous`` or ``missing``."""
        return cast("builtins.list[InstrumentMapping]", self._client._send(b.op_account_instruments(account_id)))

    def sessions(self, account_id: str, *, instrument: str | None = None, symbol: str | None = None) -> MarketHours:
        """Market hours at this account's broker: open now, the next change, and the weekly sessions.

        Name an ``instrument`` (``"XAUUSD"``) or the broker's ``symbol``. Read from the
        broker's own configuration, in its server time and in UTC.
        """
        if (instrument is None) == (symbol is None):
            raise ValueError("Pass either instrument= or symbol=.")
        return cast(MarketHours, self._client._send(b.op_account_sessions(account_id, symbol, instrument)))

    def sync_symbols(self, account_id: str) -> SymbolsSynced:
        """Reads the broker's symbol list again now. Needs the account online; it happens daily on its own."""
        return cast(SymbolsSynced, self._client._send(b.op_sync_symbols(account_id)))

    def set_mode(self, account_id: str, mode: AccountMode) -> ModeResult:
        """``always_on``, ``warm_on_demand`` or ``cold``."""
        return cast(ModeResult, self._client._send(b.op_set_mode(account_id, mode)))

    mode = set_mode

    def replace_credentials(self, account_id: str, *, password: str, server: str | None = None) -> Account:
        """Gives the account a new trading password (and optionally a corrected server name).

        For an account in ``invalid_credentials``, or after the password changed at the broker.
        The account is taken offline first and lands in ``created``; bring it online to check the
        new password. Connecting a *disconnected* login again with ``connect`` also works.
        """
        return cast(Account, self._client._send(b.op_replace_credentials(account_id, password, server)))

    def search_servers(self, query: str, *, limit: int | None = None) -> builtins.list[BrokerServer]:
        """MT5 servers matching a broker's name or the start of a server name, for a picker.

        Servers accounts on fxapis have logged in to come first. A server not listed can still be connected.
        """
        return cast(builtins.list[BrokerServer], self._client._send(b.op_search_servers(query, limit)))

    def switch_server(self, account_id: str, *, server: str, connect: bool = True) -> Account:
        """Moves the account to another server, keeping the stored password.

        For a login refused because it was added under the wrong server name: the likely
        servers are in ``account["problem"]["otherServers"]``. With ``connect`` (the default)
        the account is brought online at once, so the answer is back in seconds.
        """
        return cast(Account, self._client._send(b.op_switch_server(account_id, server, connect)))

    def events(self, account_id: str, *, limit: int | None = None) -> builtins.list[AccountEvent]:
        """The account's history in words, newest first — the console's activity list."""
        return cast(builtins.list[AccountEvent], self._client._send(b.op_account_events(account_id, limit)))

    def reconcile(self, account_id: str) -> ReconcileResult:
        """Confirms every ``unknown`` order with the broker now and refreshes deals and positions."""
        return cast(ReconcileResult, self._client._send(b.op_reconcile(account_id)))

    def wait_until_ready(self, account_id: str, *, timeout: float = 120.0, poll_interval: float = 2.0) -> AccountStatus:
        """Polls ``status`` until the account is online.

        Raises :class:`AccountNeedsAttentionError` as soon as the account
        reaches a state a person must fix (wrong password, 2FA, certificate,
        trading disabled) instead of polling until the timeout, and
        :class:`WaitTimeoutError` if it is not online in time. Usually about
        10 seconds; allow more for a busy broker.
        """
        deadline = time.monotonic() + timeout
        last: AccountStatus | None = None
        while True:
            last = self.status(account_id)
            state = last.get("state")
            if state in b.ONLINE_STATES:
                return last
            if state in b.NEEDS_ATTENTION_STATES:
                raise AccountNeedsAttentionError(account_id, str(state), last.get("detail"))
            if time.monotonic() + poll_interval > deadline:
                raise WaitTimeoutError(
                    f"account {account_id} was not online within {timeout:g}s (last state: {state})", last=last
                )
            time.sleep(poll_interval)

    def bring_online(self, account_id: str, *, timeout: float = 120.0, poll_interval: float = 2.0) -> AccountStatus:
        """``warm`` followed by ``wait_until_ready``."""
        self.warm(account_id)
        return self.wait_until_ready(account_id, timeout=timeout, poll_interval=poll_interval)


class Instruments(_Resource):
    """The markets an order or a signal can name, whatever each broker calls them."""

    def list(self, *, category: str | None = None) -> builtins.list[Instrument]:
        """``forex``, ``metals``, ``indices``, ``energies`` or ``crypto``; all when omitted."""
        return cast("builtins.list[Instrument]", self._client._send(b.op_list_instruments(category)))


class Orders(_Resource):
    """Place, modify, cancel and look up orders."""

    def market(
        self,
        account_id: str,
        *,
        symbol: str | None = None,
        instrument: str | None = None,
        side: Side,
        volume: Number,
        stop_loss: Number | None = None,
        take_profit: Number | None = None,
        deviation_points: int | None = None,
        comment: str | None = None,
        client_order_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Order:
        """Sends a market order and waits for the broker's answer.

        Name the broker's ``symbol``, or an ``instrument`` from ``instruments.list()``
        (``"XAUUSD"``) to trade this account's own symbol for it -- one name for
        every member's broker. ``volume`` is in lots; prices are absolute (not pips). Pass your own
        ``idempotency_key`` to tie the order to something you know -- e.g.
        ``f"signal_{signal_id}:member_{member_id}"`` -- so a double click can
        never open two positions. Otherwise a UUID is generated.

        Raises :class:`OrderRejectedError` (broker refused; nothing opened),
        :class:`OrderUnresolvedError` (**do not resend**: poll
        ``wait_until_resolved(err.order_id)``), :class:`SendFailedError` /
        :class:`AccountNotReadyError` (nothing sent; already retried with the
        same key up to ``max_retries``).
        """
        request = b.op_market_order(
            account_id,
            symbol=symbol,
            instrument=_one_target(symbol, instrument),
            side=side,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=take_profit,
            deviation_points=deviation_points,
            comment=comment,
            client_order_id=client_order_id,
            idempotency_key=idempotency_key,
        )
        return cast(Order, self._client._send(request))

    def pending(
        self,
        account_id: str,
        *,
        symbol: str | None = None,
        instrument: str | None = None,
        side: Side,
        kind: PendingKind,
        volume: Number,
        price: Number,
        stop_limit_price: Number | None = None,
        stop_loss: Number | None = None,
        take_profit: Number | None = None,
        expires_at: Timestamp | None = None,
        comment: str | None = None,
        client_order_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Order:
        """Places a limit, stop or stop-limit order. Success means *accepted and waiting*, not filled.

        A ``limit`` waits for a better price (buy below the market); a ``stop``
        for a worse one (buy above). ``stop_limit_price`` is required for
        ``stop_limit``. Omit ``expires_at`` for good-till-cancelled.
        """
        request = b.op_pending_order(
            account_id,
            symbol=symbol,
            instrument=_one_target(symbol, instrument),
            side=side,
            kind=kind,
            volume=volume,
            price=price,
            stop_limit_price=stop_limit_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            expires_at=expires_at,
            comment=comment,
            client_order_id=client_order_id,
            idempotency_key=idempotency_key,
        )
        return cast(Order, self._client._send(request))

    def modify(
        self,
        order_id: str,
        *,
        price: Number | None = None,
        stop_loss: Number | Any | None = UNSET,
        take_profit: Number | Any | None = UNSET,
        stop_limit_price: Number | None = None,
        expires_at: Timestamp | None = None,
    ) -> Order:
        """Moves a pending order's price or levels, keeping its ticket.

        For ``stop_loss`` and ``take_profit``, ``None`` **removes** the level;
        leaving the argument out keeps it unchanged.
        """
        request = b.op_modify_order(
            order_id,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            stop_limit_price=stop_limit_price,
            expires_at=expires_at,
        )
        return cast(Order, self._client._send(request))

    def cancel(self, order_id: str) -> Order:
        """Cancels a pending order that has not triggered."""
        return cast(Order, self._client._send(b.op_cancel_order(order_id)))

    def get(self, order_id: str) -> Order:
        """The authoritative record of one order, including the broker's own return code."""
        return cast(Order, self._client._send(b.op_get_order(order_id)))

    def list(
        self,
        *,
        account_id: str | None = None,
        state: OrderState | None = None,
        symbol: str | None = None,
        since: Timestamp | None = None,
        until: Timestamp | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Order]:
        """One page of orders, newest first (``limit`` up to 200, default 50)."""
        request = b.op_list_orders(
            account_id=account_id, state=state, symbol=symbol, since=since, until=until, limit=limit, cursor=cursor
        )
        return cast("Page[Order]", self._client._send(request))

    def iter(
        self,
        *,
        account_id: str | None = None,
        state: OrderState | None = None,
        symbol: str | None = None,
        since: Timestamp | None = None,
        until: Timestamp | None = None,
        page_size: int = 200,
    ) -> Iterator[Order]:
        """Every matching order, newest first, fetching pages as you iterate."""
        cursor: str | None = None
        while True:
            page = self.list(
                account_id=account_id,
                state=state,
                symbol=symbol,
                since=since,
                until=until,
                limit=page_size,
                cursor=cursor,
            )
            yield from page.data
            if not page.has_more or not page.next_cursor:
                return
            cursor = page.next_cursor

    def deals(self, order_id: str) -> builtins.list[Deal]:
        """The broker deals one order produced (a partial fill leaves several)."""
        return cast("builtins.list[Deal]", self._client._send(b.op_order_deals(order_id)))

    def wait_until_resolved(self, order_id: str, *, timeout: float = 120.0, poll_interval: float = 2.0) -> Order:
        """Polls an order until its result is known -- the answer to an ``ORDER_UNRESOLVED``.

        Returns the order once it has left ``unknown`` (filled, rejected ...).
        Raises :class:`WaitTimeoutError` if it is still unresolved after ``timeout``.
        """
        deadline = time.monotonic() + timeout
        while True:
            order = self.get(order_id)
            if order.get("state") not in b.UNRESOLVED_ORDER_STATES:
                return order
            if time.monotonic() + poll_interval > deadline:
                raise WaitTimeoutError(f"order {order_id} still {order.get('state')} after {timeout:g}s", last=order)
            time.sleep(poll_interval)


class Positions(_Resource):
    def list(self, account_id: str, *, include_closed: bool = False) -> builtins.list[Position]:
        """Open positions as last seen. ``observedAt`` says how fresh each one is."""
        return cast("builtins.list[Position]", self._client._send(b.op_list_positions(account_id, include_closed)))

    def close(
        self,
        account_id: str,
        position_id: str | int,
        *,
        volume: Number | None = None,
        deviation_points: int | None = None,
        comment: str | None = None,
        client_order_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Order:
        """Closes a position (its ``brokerPositionId``), in whole or -- with ``volume`` -- in part.

        Always idempotent: a repeated close on a hedging account would open an
        opposite position, so a key is sent even if you do not pass one.
        """
        request = b.op_close_position(
            account_id,
            position_id,
            volume=volume,
            deviation_points=deviation_points,
            comment=comment,
            client_order_id=client_order_id,
            idempotency_key=idempotency_key,
        )
        return cast(Order, self._client._send(request))

    def modify(
        self,
        account_id: str,
        position_id: str | int,
        *,
        stop_loss: Number | Any | None = UNSET,
        take_profit: Number | Any | None = UNSET,
    ) -> Order:
        """Moves a position's stop loss or take profit. ``None`` removes a level; omitting keeps it."""
        request = b.op_modify_position(account_id, position_id, stop_loss=stop_loss, take_profit=take_profit)
        return cast(Order, self._client._send(request))


class Deals(_Resource):
    def list(
        self,
        account_id: str,
        *,
        symbol: str | None = None,
        since: Timestamp | None = None,
        until: Timestamp | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Deal]:
        """One page of an account's deal history, newest first by the broker's time.

        Includes deals no order of yours caused: a stop loss firing, swap,
        deposits, or trades placed from the MetaTrader desktop.
        """
        request = b.op_list_deals(account_id, symbol=symbol, since=since, until=until, limit=limit, cursor=cursor)
        return cast("Page[Deal]", self._client._send(request))

    def iter(
        self,
        account_id: str,
        *,
        symbol: str | None = None,
        since: Timestamp | None = None,
        until: Timestamp | None = None,
        page_size: int = 200,
    ) -> Iterator[Deal]:
        """Every matching deal, newest first, fetching pages as you iterate."""
        cursor: str | None = None
        while True:
            page = self.list(account_id, symbol=symbol, since=since, until=until, limit=page_size, cursor=cursor)
            yield from page.data
            if not page.has_more or not page.next_cursor:
                return
            cursor = page.next_cursor

    def for_order(self, order_id: str) -> builtins.list[Deal]:
        return cast("builtins.list[Deal]", self._client._send(b.op_order_deals(order_id)))


class Calculate(_Resource):
    """Margin or profit, computed by the account's own terminal. Opens nothing; the account must be online."""

    def margin(self, account_id: str, *, symbol: str, side: Side, volume: Number, price: Number) -> CalculateResult:
        request = b.op_calculate(
            account_id, kind="margin", symbol=symbol, side=side, volume=volume, price=price, close_price=None
        )
        return cast(CalculateResult, self._client._send(request))

    def profit(
        self, account_id: str, *, symbol: str, side: Side, volume: Number, price: Number, close_price: Number
    ) -> CalculateResult:
        request = b.op_calculate(
            account_id, kind="profit", symbol=symbol, side=side, volume=volume, price=price, close_price=close_price
        )
        return cast(CalculateResult, self._client._send(request))


class AlertHooks(_Resource):
    """TradingView alerts to MT5: secret URLs that turn alerts into orders on your accounts."""

    def list(self) -> builtins.list[AlertHook]:
        return cast("builtins.list[AlertHook]", self._client._send(b.op_list_alert_hooks()))

    def create(
        self, *, name: str, account_ids: builtins.list[str], defaults: AlertHookDefaults | None = None
    ) -> AlertHook:
        """Creates a hook. The returned ``url`` holds its secret and is shown **only now** -- store it."""
        return cast(
            AlertHook,
            self._client._send(b.op_create_alert_hook(name, account_ids, cast("dict[str, Any] | None", defaults))),
        )

    def get(self, hook_id: str) -> AlertHook:
        return cast(AlertHook, self._client._send(b.op_get_alert_hook(hook_id)))

    def update(
        self,
        hook_id: str,
        *,
        name: str | None = None,
        account_ids: builtins.list[str] | None = None,
        defaults: AlertHookDefaults | None = None,
    ) -> AlertHook:
        """Changes name, accounts or defaults. The URL stays the same."""
        return cast(
            AlertHook,
            self._client._send(
                b.op_update_alert_hook(hook_id, name, account_ids, cast("dict[str, Any] | None", defaults))
            ),
        )

    def rotate(self, hook_id: str) -> AlertHook:
        """Issues a new secret URL (returned once); the old one stops working at once."""
        return cast(AlertHook, self._client._send(b.op_alert_hook_action(hook_id, "rotate")))

    def enable(self, hook_id: str) -> AlertHook:
        return cast(AlertHook, self._client._send(b.op_alert_hook_action(hook_id, "enable")))

    def disable(self, hook_id: str) -> AlertHook:
        return cast(AlertHook, self._client._send(b.op_alert_hook_action(hook_id, "disable")))

    def delete(self, hook_id: str) -> AlertHook:
        return cast(AlertHook, self._client._send(b.op_delete_alert_hook(hook_id)))

    def deliveries(self, hook_id: str) -> builtins.list[AlertDelivery]:
        """The most recent alerts this hook received, and what became of each."""
        return cast("builtins.list[AlertDelivery]", self._client._send(b.op_alert_deliveries(hook_id)))


class Waves(_Resource):
    """Multi-account orders ("execution waves"): one trade placed on many accounts at once."""

    def create(
        self,
        *,
        account_ids: builtins.list[str],
        symbol: str,
        side: Side,
        volume: Number,
        weights: dict[str, Number] | None = None,
        stop_loss: Number | None = None,
        take_profit: Number | None = None,
        comment: str | None = None,
        label: str | None = None,
        client_wave_id: str | None = None,
        barrier_policy: BarrierPolicy | None = None,
        execute_at: Timestamp | None = None,
        expires_at: Timestamp | None = None,
        idempotency_key: str | None = None,
    ) -> Wave:
        """Places one order on each account (up to 500). Returns at once; follow it with ``wait_until_settled``.

        ``weights`` maps account id to its own volume. ``barrier_policy``
        decides what happens when some accounts are not online in time:
        ``release-ready`` (default) trades on those that are.
        """
        request = b.op_create_wave(
            account_ids=account_ids,
            symbol=symbol,
            side=side,
            volume=volume,
            weights=weights,
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment=comment,
            label=label,
            client_wave_id=client_wave_id,
            barrier_policy=barrier_policy,
            execute_at=execute_at,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
        )
        return cast(Wave, self._client._send(request))

    def get(self, wave_id: str) -> Wave:
        return cast(Wave, self._client._send(b.op_get_wave(wave_id)))

    def list(self) -> builtins.list[Wave]:
        return cast("builtins.list[Wave]", self._client._send(b.op_list_waves()))

    def cancel(self, wave_id: str) -> Wave:
        """Cancels a multi-account order, only while nothing has been sent."""
        return cast(Wave, self._client._send(b.op_cancel_wave(wave_id)))

    def wait_until_settled(self, wave_id: str, *, timeout: float = 300.0, poll_interval: float = 1.0) -> Wave:
        """Polls until every account has a result (``settled``), or it was ``cancelled`` / ``abandoned``."""
        deadline = time.monotonic() + timeout
        while True:
            wave = self.get(wave_id)
            if wave.get("state") in b.FINAL_WAVE_STATES:
                return wave
            if time.monotonic() + poll_interval > deadline:
                raise WaitTimeoutError(f"wave {wave_id} still {wave.get('state')} after {timeout:g}s", last=wave)
            time.sleep(poll_interval)


class Usage_(_Resource):
    def get(self) -> Usage:
        """This month's usage against the plan, and what it would cost."""
        return cast(Usage, self._client._send(b.op_usage()))

    def daily(self) -> builtins.list[UsageDay]:
        return cast("builtins.list[UsageDay]", self._client._send(b.op_usage_daily()))


class Plans(_Resource):
    def list(self) -> builtins.list[Plan]:
        """The plans on offer. Prices are in minor units: ``9900`` is $99.00."""
        return cast("builtins.list[Plan]", self._client._send(b.op_plans()))
