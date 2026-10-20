"""Response and parameter types, matching the field names of the fxapis OpenAPI spec exactly.

Responses are returned as plain ``dict`` objects typed with these
``TypedDict`` classes: they serialise straight to JSON, print readably, and a
field the API adds later is simply there rather than dropped.

Prices, volumes and money are **strings** (``"0.10"``, not ``0.1``) -- the API
never puts a float in a request body, and neither does this library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypedDict, TypeVar

__all__ = [
    "ApiKey",
    "KeyLimits",
    "KeyMaker",
    "KeyScope",
    "AlertHook",
    "AlertHookDefaults",
    "AlertDelivery",
    "AccountMode",
    "AccountState",
    "Side",
    "PendingKind",
    "OrderState",
    "WaveState",
    "BarrierPolicy",
    "Account",
    "AccountFigures",
    "Quote",
    "AccountStatus",
    "WarmResult",
    "PrepareResult",
    "CoolResult",
    "DisconnectResult",
    "ModeResult",
    "ReconcileResult",
    "Order",
    "Deal",
    "Position",
    "CalculateResult",
    "Wave",
    "WaveLeg",
    "WaveSummary",
    "Workspace",
    "Usage",
    "UsageDay",
    "Plan",
    "Page",
    "Event",
    "WebhookDelivery",
    "WebhookDeliveryDetail",
    "ReplayResult",
    "DeliveryState",
    "CopyStrategy",
    "CopySubscription",
    "CopySubscriptionStatus",
    "CopyExecution",
    "CopyLink",
    "CopyDeleted",
]

AccountMode = Literal["always_on", "warm_on_demand", "cold"]
AccountState = Literal[
    "created",
    "provisioning",
    "standby",
    "starting",
    "connecting",
    "synchronizing",
    "ready",
    "executing",
    "cooling",
    "offline",
    "degraded",
    "reconnecting",
    "invalid_credentials",
    "trading_disabled",
    "needs_2fa",
    "needs_certificate",
    "error",
]
Side = Literal["buy", "sell"]
PendingKind = Literal["limit", "stop", "stop_limit"]
OrderState = Literal[
    "accepted",
    "validating",
    "sending",
    "working",
    "completed",
    "filled",
    "partially_filled",
    "rejected",
    "failed",
    "unknown",
    "cancelled",
    "expired",
]
WaveState = Literal["planned", "preparing", "armed", "releasing", "settled", "cancelled", "abandoned"]
BarrierPolicy = Literal["release-ready", "all-or-nothing", "wait"]


class Account(TypedDict, total=False):
    id: str
    label: str | None
    login: str
    server: str
    mode: AccountMode
    state: AccountState
    stateDetail: str | None
    stateChangedAt: str
    currency: str | None
    leverage: int | None
    marginMode: Literal["netting", "hedging"] | None
    tradeAllowed: bool | None
    brokerName: str | None
    tradingDisabled: bool
    createdAt: str
    balance: str | None
    equity: str | None
    margin: str | None
    freeMargin: str | None
    marginLevel: str | None
    credit: str | None
    profit: str | None
    figuresObservedAt: str | None
    problem: AccountProblem | None


class AccountFigures(TypedDict, total=False):
    """Money figures as decimal strings in the account's currency. ``marginLevel`` is None while no margin is used."""

    accountId: str
    balance: str | None
    equity: str | None
    margin: str | None
    freeMargin: str | None
    marginLevel: str | None
    credit: str | None
    profit: str | None
    currency: str | None
    leverage: int | None
    marginMode: Literal["netting", "hedging"] | None
    observedAt: str | None
    ageMs: int | None
    source: Literal["live", "snapshot"]


class Quote(TypedDict, total=False):
    """A price from the account's own broker. ``stale`` only while the market is open and the tick is over 60 s old."""

    symbol: str
    instrument: str | None
    status: Literal["ok", "no_price", "unknown_symbol"]
    bid: str | None
    ask: str | None
    spread: int | None
    digits: int | None
    brokerTime: str | None
    time: str | None
    observedAt: str
    ageMs: int | None
    stale: bool
    marketOpen: bool | None
    tradeMode: Literal["full", "longOnly", "shortOnly", "closeOnly", "disabled"] | None


class ProblemAction(TypedDict, total=False):
    kind: Literal["switch_server", "replace_credentials", "connect", "contact_support"]
    server: str


class AccountProblem(TypedDict, total=False):
    """What is wrong with an account, in words, and what fixes it. ``None`` on a healthy account."""

    code: Literal[
        "LOGIN_REFUSED", "TRADING_DISABLED", "NEEDS_2FA", "NEEDS_CERTIFICATE", "CONNECTION_FAILED", "PLATFORM_ISSUE"
    ]
    title: str
    explanation: str
    detail: str | None
    otherServers: list[str]
    actions: list[ProblemAction]


class BrokerServer(TypedDict, total=False):
    """An MT5 server to connect with: ``name`` is exactly what to send as ``server``."""

    name: str
    company: str | None
    kind: Literal["demo", "live", "contest", "unknown"]
    proven: bool


class AccountEvent(TypedDict, total=False):
    id: str
    at: str
    tone: Literal["success", "info", "warning", "danger"]
    title: str
    detail: str | None
    by: Literal["key", "member", "staff", "system"]
    action: str


class AccountStatus(TypedDict, total=False):
    id: str
    state: AccountState
    detail: str | None
    since: str
    mode: AccountMode
    tradingDisabled: bool


class WarmResult(TypedDict, total=False):
    accountId: str
    runtimeId: str
    alreadyRunning: bool
    state: AccountState
    pollUrl: str


class PrepareResult(TypedDict, total=False):
    accountId: str
    result: Literal[
        "starting", "already_running", "not_found", "leased_elsewhere", "needs_operator", "no_secret", "failed"
    ]
    message: str | None


class CoolResult(TypedDict, total=False):
    accountId: str
    stopped: bool
    state: str


class DisconnectResult(TypedDict, total=False):
    accountId: str
    state: str
    credentialsRemoved: bool


class DeletedCounts(TypedDict, total=False):
    orders: int
    deals: int
    positions: int
    alertHooksUpdated: int


class DeleteResult(TypedDict, total=False):
    accountId: str
    deleted: bool
    #: What went with it.
    removed: DeletedCounts


class ModeResult(TypedDict, total=False):
    accountId: str
    mode: AccountMode
    restingState: str


class ReconcileResult(TypedDict, total=False):
    accountId: str
    examined: int
    resolved: int
    stillUnknown: int
    ambiguous: int
    historyNotReady: int
    historyReady: bool | None
    dealsIngested: int
    positionsOpen: int
    positionsClosed: int
    skipped: str | None


class Order(TypedDict, total=False):
    id: str
    accountId: str
    clientOrderId: str | None
    symbol: str
    side: Side
    type: Literal["market", "limit", "stop", "stop_limit"]
    intent: Literal["open", "close", "modify", "cancel"]
    #: On a close or modify, the position acted on. On an opening order, the position it opened:
    #: usually set when it fills, else linked within a few minutes (pending orders, older terminals).
    brokerPositionId: str | None
    volume: str | None
    stopLoss: str | None
    takeProfit: str | None
    state: OrderState
    stateDetail: str | None
    needsReconciliation: bool
    retcode: int | None
    retcodeText: str | None
    brokerOrderId: str | None
    brokerDealId: str | None
    filledVolume: str | None
    filledPrice: str | None
    sentAt: str | None
    settledAt: str | None
    reconciledAt: str | None
    createdAt: str


class Deal(TypedDict, total=False):
    id: str
    accountId: str
    orderId: str | None
    brokerDealId: str
    brokerOrderId: str | None
    brokerPositionId: str | None
    symbol: str
    dealType: str
    entry: str | None
    volume: str | None
    price: str | None
    commission: str | None
    swap: str | None
    profit: str | None
    fee: str | None
    dealtAt: str
    comment: str | None


class Position(TypedDict, total=False):
    id: str
    accountId: str
    brokerPositionId: str
    symbol: str
    side: Side
    volume: str | None
    openPrice: str | None
    currentPrice: str | None
    stopLoss: str | None
    takeProfit: str | None
    swap: str | None
    profit: str | None
    openedAt: str | None
    observedAt: str
    closedAt: str | None


class CalculateResult(TypedDict, total=False):
    kind: Literal["margin", "profit"]
    value: str | None


class WaveSummary(TypedDict, total=False):
    total: int
    filled: int
    rejected: int
    skipped: int
    unresolved: int


class WaveLeg(TypedDict, total=False):
    accountId: str
    orderId: str | None
    symbol: str
    volume: str | None
    state: Literal["pending", "preparing", "ready", "dispatched", "filled", "rejected", "skipped", "unresolved"]
    stateDetail: str | None
    sentAt: str | None
    settledAt: str | None


class Wave(TypedDict, total=False):
    id: str
    label: str | None
    clientWaveId: str | None
    symbol: str | None
    instrument: str | None
    side: Side
    baseVolume: str | None
    state: WaveState
    stateDetail: str | None
    barrierPolicy: BarrierPolicy
    executeAt: str | None
    expiresAt: str | None
    preparedAt: str | None
    releasedAt: str | None
    settledAt: str | None
    dispatchSpreadMs: int | None
    summary: WaveSummary
    legs: list[WaveLeg]
    createdAt: str


class Workspace(TypedDict, total=False):
    id: str
    name: str
    plan: str
    planName: str
    planAssigned: bool
    tradingDisabled: bool


KeyScope = Literal[
    "accounts:read",
    "accounts:write",
    "trading:read",
    "trading:reduce",
    "trading:execute",
    "history:read",
    "billing:read",
    "webhooks:write",
]
"""The scopes an ordinary key may hold.

``admin``, ``keys:manage``, ``members:manage`` and ``billing:manage`` never can.
"""


class KeyLimits(TypedDict, total=False):
    """What a key may open, on top of its scopes. A field left out (or ``None``) is no limit."""

    maxVolume: str | None
    symbols: list[str] | None
    accountIds: list[str] | None
    maxOpeningOrdersPerDay: int | None


class KeyMaker(TypedDict):
    id: str
    name: str


class ApiKey(TypedDict, total=False):
    """An ordinary API key. ``key`` is present only in the answer to ``admin.keys.create()`` -- store it then."""

    id: str
    name: str
    publicId: str
    hint: str
    environment: Literal["live", "test"]
    scopes: list[str]
    lastUsedAt: str | None
    expiresAt: str | None
    revokedAt: str | None
    createdAt: str
    limits: KeyLimits | None
    createdBy: KeyMaker | None
    createdByAdminKey: KeyMaker | None
    key: str


class _Entitlements(TypedDict, total=False):
    accounts: int
    ordersPerMonth: int
    wavesPerMonth: int
    legsPerWave: int
    apiCallsPerMonth: int
    allowOverage: bool


class _Features(TypedDict, total=False):
    executionWaves: bool
    pendingOrders: bool
    alwaysOn: bool
    webhooks: bool


class _UsageCounts(TypedDict, total=False):
    orders: int
    waves: int
    api_calls: int
    accounts: int


class Usage(TypedDict, total=False):
    plan: str
    planName: str
    currency: str
    subtotal: int | None
    overage: int
    total: int | None
    entitlements: _Entitlements
    features: _Features
    usage: _UsageCounts


class UsageDay(TypedDict, total=False):
    day: str
    metric: str
    count: int


class Plan(TypedDict, total=False):
    code: str
    name: str
    monthlyPrice: int | None
    currency: str
    selfServe: bool
    overagePerOrder: int
    features: _Features
    entitlements: _Entitlements


T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    """One page of a cursor-paginated list. Pass ``next_cursor`` as ``cursor`` to get the next."""

    data: list[T] = field(default_factory=list)
    has_more: bool = False
    next_cursor: str | None = None

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


class Instrument(TypedDict, total=False):
    """A market named once, whatever each broker calls it. Name it as ``instrument`` in an order."""

    instrument: str
    name: str
    category: str


class BrokerSymbol(TypedDict, total=False):
    """One symbol an account's broker offers, with its contract specification."""

    name: str
    description: str
    path: str
    digits: int | None
    contractSize: float | None
    volumeMin: float | None
    volumeMax: float | None
    volumeStep: float | None
    tradable: bool
    currencyBase: str
    currencyProfit: str
    currencyMargin: str


class InstrumentCandidate(TypedDict, total=False):
    symbol: str
    confidence: float
    reason: str


class InstrumentMapping(TypedDict, total=False):
    """How one instrument maps onto an account's broker: ``mapped``, ``ambiguous`` or ``missing``."""

    instrument: str
    name: str
    category: str
    status: str
    symbol: str | None
    reason: str | None
    candidates: list[InstrumentCandidate]


class SessionWindow(TypedDict, total=False):
    day: str
    open: str
    close: str


class SessionTimes(TypedDict, total=False):
    #: In the broker's server time.
    server: list[SessionWindow]
    #: In UTC.
    utc: list[SessionWindow]


class MarketHours(TypedDict, total=False):
    """When a symbol trades at an account's broker, as the broker configured it."""

    symbol: str
    instrument: str | None
    server: str
    utcOffsetSeconds: int
    sessionsSyncedAt: str
    openNow: bool
    nextOpen: str | None
    nextClose: str | None
    trade: SessionTimes
    quote: SessionTimes


class SymbolsSynced(TypedDict, total=False):
    syncedAt: str
    server: str
    symbolCount: int


class AlertHookDefaults(TypedDict, total=False):
    """What a TradingView alert gets when its message leaves something out."""

    volume: str
    deviationPoints: int
    symbolMap: dict[str, str]
    symbolSuffix: str
    stripExchangePrefix: bool
    allowClose: bool
    onlyTradingViewIps: bool


class AlertHook(TypedDict, total=False):
    """A secret URL that turns TradingView alerts into MT5 orders. ``url`` is present only on create and rotate."""

    id: str
    name: str
    accountIds: list[str]
    defaults: AlertHookDefaults
    enabled: bool
    urlHint: str
    lastUsedAt: str | None
    createdAt: str
    url: str


class AlertDelivery(TypedDict, total=False):
    """One alert as it arrived, and what became of it."""

    id: str
    receivedAt: str
    status: Literal["pending", "accepted", "rejected", "duplicate", "ignored"]
    reason: str | None
    payload: str | None
    orderIds: list[str]
    waveId: str | None


DeliveryState = Literal["succeeded", "failed", "sending"]


class Event(TypedDict, total=False):
    """One thing that happened, exactly as a webhook delivery carries it."""

    id: str
    type: str
    createdAt: str
    data: dict[str, Any]


class WebhookDelivery(TypedDict, total=False):
    """One attempt to deliver an event to a webhook endpoint. Kept 30 days."""

    id: str
    eventId: str
    eventType: str
    attempt: int
    state: DeliveryState
    succeeded: bool
    statusCode: int | None
    durationMs: int | None
    error: str | None
    eventAvailable: bool
    """False once the event has aged out of the event history: it can no longer be redelivered."""
    createdAt: str


class WebhookRequest(TypedDict, total=False):
    url: str | None
    headers: dict[str, str]
    body: str | None


class WebhookResponse(TypedDict, total=False):
    statusCode: int
    headers: dict[str, str]
    body: str


class WebhookDeliveryDetail(WebhookDelivery, total=False):
    """An attempt in full: the request as sent, and the answer (first 4 KB), or ``None`` when none came."""

    request: WebhookRequest
    response: WebhookResponse | None


class ReplayResult(TypedDict, total=False):
    """What a replay queued. ``nextSince`` is set when the cap was reached: replay again from it."""

    queued: int
    include: Literal["failed", "all"]
    since: str
    until: str
    nextSince: str | None


CopySubscriptionStatus = Literal["active", "paused", "close_only", "stopped"]


class CopyStrategy(TypedDict, total=False):
    """An always-on account whose trades are copied to its subscribers."""

    id: str
    accountId: str
    name: str
    status: Literal["active", "paused", "archived"]
    masterAlwaysOn: bool
    followers: int
    createdAt: str
    updatedAt: str


class CopySubscription(TypedDict, total=False):
    """A follower account copying a strategy, with its own settings (see the copy-trading guide)."""

    id: str
    strategyId: str
    followerAccountId: str
    status: CopySubscriptionStatus
    stopReason: str | None
    stoppedAt: str | None
    settings: dict[str, Any]
    follower: dict[str, Any]
    lastExecution: dict[str, Any] | None
    createdAt: str
    updatedAt: str


class CopyExecution(TypedDict, total=False):
    """What one master change did on one follower: executed, skipped or failed, and why."""

    id: str
    strategyId: str
    subscriptionId: str | None
    followerAccountId: str
    status: Literal["executed", "skipped", "failed", "pending"]
    reason: str | None
    detail: str | None
    orderId: str | None
    requestedVolume: str | None
    latencyMs: int | None
    createdAt: str
    signal: dict[str, Any]


class CopyLink(TypedDict, total=False):
    """Which follower position copies which master position."""

    id: str
    subscriptionId: str
    masterPositionId: str
    followerAccountId: str
    followerPositionId: str | None
    symbol: str
    side: Side
    followerVolume: str
    masterVolume: str
    openedAt: str
    closedAt: str | None


class CopyStatus(TypedDict):
    """Whether copy trading is paused on this server, and why in a sentence (None when it runs)."""

    paused: bool
    message: str | None


class CopyDeleted(TypedDict):
    id: str
    deleted: bool
    closed: int
