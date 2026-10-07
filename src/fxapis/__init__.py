"""fxapis -- Python client for the fxapis MetaTrader 5 (MT5) REST API.

Connect MT5 accounts once, then place market and pending orders, close and
modify positions, read deals, and send one trade to many accounts -- over plain
HTTPS, with no MetaTrader terminal, VPS or EA of your own.

    from fxapis import Fxapis

    client = Fxapis()  # reads FXAPIS_API_KEY
    order = client.orders.market(account_id, symbol="EURUSD", side="buy", volume="0.01")

Docs: https://docs.fxapis.com
"""

from ._async_client import AsyncFxapis
from ._base import UNSET
from ._client import Fxapis
from ._version import __version__
from .errors import (
    AccountExecutingError,
    AccountExistsError,
    AccountHasPositionsError,
    AccountInWaveError,
    AccountNeedsAttentionError,
    AccountNotReadyError,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    FeatureNotInPlanError,
    FxapisError,
    IdempotencyInFlightError,
    IdempotencyKeyReusedError,
    InvalidRequestError,
    NeedsOperatorError,
    NoRuntimeError,
    NotFoundError,
    OrderRejectedError,
    OrderUnresolvedError,
    PaymentRequiredError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitedError,
    SendFailedError,
    ServerError,
    TradingDisabledError,
    WaitTimeoutError,
)
from .types import Page

__all__ = [
    "Fxapis",
    "AsyncFxapis",
    "UNSET",
    "Page",
    "__version__",
    "FxapisError",
    "APIConnectionError",
    "APITimeoutError",
    "APIStatusError",
    "InvalidRequestError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "PaymentRequiredError",
    "QuotaExceededError",
    "FeatureNotInPlanError",
    "RateLimitedError",
    "ServerError",
    "OrderRejectedError",
    "OrderUnresolvedError",
    "SendFailedError",
    "AccountNotReadyError",
    "NoRuntimeError",
    "TradingDisabledError",
    "IdempotencyInFlightError",
    "IdempotencyKeyReusedError",
    "AccountExistsError",
    "AccountExecutingError",
    "AccountHasPositionsError",
    "AccountInWaveError",
    "NeedsOperatorError",
    "AccountNeedsAttentionError",
    "WaitTimeoutError",
]
