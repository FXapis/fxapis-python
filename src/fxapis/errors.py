"""Typed errors mapped from the API's ``error.code``.

Every failure the API returns has the shape
``{"error": {"code", "message", "details"}, "requestId"}``. The ``code`` is
stable; ``message`` is written for a human and may change. This module turns
the code into an exception class you can catch, and gives each one an honest
``retryable`` answer.

The one that matters most is :class:`OrderUnresolvedError`: the order may be
live at the broker. It is **never** retried by this library, and you should not
resend it either -- poll the order (``client.orders.wait_until_resolved``).
"""

from __future__ import annotations

from typing import Any

__all__ = [
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
    "NeedsOperatorError",
    "AccountNeedsAttentionError",
    "WaitTimeoutError",
    "error_from_response",
]


class FxapisError(Exception):
    """Base class for every error raised by this library."""

    @property
    def retryable(self) -> bool:
        """Whether sending the *same* request again (same idempotency key) is safe and may succeed."""
        return False


class APIConnectionError(FxapisError):
    """The request did not get an HTTP answer: DNS, TLS, a reset connection.

    For a trading request this does **not** prove the order was not placed.
    Retry it with the same ``idempotency_key`` (available on this error) and the
    API answers with the first result instead of placing a second order.
    """

    def __init__(self, message: str, *, idempotency_key: str | None = None) -> None:
        super().__init__(message)
        self.idempotency_key = idempotency_key

    @property
    def retryable(self) -> bool:
        return True


class APITimeoutError(APIConnectionError):
    """No answer within the client's timeout. Same advice: retry with the same key."""


class WaitTimeoutError(FxapisError, TimeoutError):
    """A ``wait_until_*`` helper ran out of time. ``last`` holds the last state seen."""

    def __init__(self, message: str, *, last: Any = None) -> None:
        super().__init__(message)
        self.last = last


class APIStatusError(FxapisError):
    """The API answered with a non-2xx status."""

    #: Codes that mean "nothing was done -- the same request may succeed later".
    _RETRYABLE_CODES: frozenset[str] = frozenset()

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: str,
        request_id: str | None = None,
        details: list[dict[str, Any]] | None = None,
        body: Any = None,
        headers: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.request_id = request_id
        self.details: list[dict[str, Any]] = details or []
        self.body = body
        self.headers: dict[str, str] = headers or {}
        #: The Idempotency-Key the failed request carried, if any. Reuse it to retry safely.
        self.idempotency_key = idempotency_key

    def __str__(self) -> str:
        suffix = f" (requestId {self.request_id})" if self.request_id else ""
        return f"{self.status} {self.code}: {self.message}{suffix}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status!r}, code={self.code!r}, message={self.message!r})"

    @property
    def order_id(self) -> str | None:
        """The order this failure concerns, when the API created one (``details[0].orderId``)."""
        for detail in self.details:
            order_id = detail.get("orderId") if isinstance(detail, dict) else None
            if isinstance(order_id, str):
                return order_id
        return None

    @property
    def retryable(self) -> bool:
        if self.code in self._RETRYABLE_CODES:
            return True
        return any(isinstance(d, dict) and d.get("retryable") is True for d in self.details)


class InvalidRequestError(APIStatusError):
    """400 -- the body or parameters failed validation. ``details`` names the fields."""


class AuthenticationError(APIStatusError):
    """401 ``UNAUTHENTICATED`` -- missing, malformed, unknown, revoked or expired key."""


class PermissionDeniedError(APIStatusError):
    """403 -- valid key, but not allowed (``MISSING_SCOPE`` and friends)."""


class NotFoundError(APIStatusError):
    """404 -- ``ACCOUNT_NOT_FOUND``, ``ORDER_NOT_FOUND``, ``WAVE_NOT_FOUND``, ``POSITION_NOT_FOUND`` ..."""


class ConflictError(APIStatusError):
    """409 -- the request conflicts with the current state."""


class PaymentRequiredError(APIStatusError):
    """402 -- the plan does not allow it. Waiting will not help; a plan change or a new month will."""


class QuotaExceededError(PaymentRequiredError):
    """402 ``QUOTA_EXCEEDED`` -- the plan's monthly allowance is used up."""


class FeatureNotInPlanError(PaymentRequiredError):
    """402 ``FEATURE_NOT_IN_PLAN`` -- e.g. pending orders or multi-account orders on a plan without them."""


class RateLimitedError(APIStatusError):
    """429 ``RATE_LIMITED``. ``retry_after`` is the server's advice in seconds."""

    _RETRYABLE_CODES = frozenset({"RATE_LIMITED"})

    @property
    def retry_after(self) -> float | None:
        value = self.headers.get("retry-after")
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    @property
    def retryable(self) -> bool:
        return True


class ServerError(APIStatusError):
    """5xx without a more specific code (``INTERNAL_ERROR``, ``MT5_UNAVAILABLE``, ``SCHEDULER_FAILED`` ...)."""

    @property
    def retryable(self) -> bool:
        return True


class OrderRejectedError(APIStatusError):
    """422 ``ORDER_REJECTED`` -- the broker refused the order. Nothing opened.

    ``retryable`` says whether the reason was transient (a requote, a moved
    price). Even then, a new attempt needs a **new** idempotency key: the old
    key now answers with this rejection. The library never retries it for you.
    """


class OrderUnresolvedError(APIStatusError):
    """503 ``ORDER_UNRESOLVED`` -- nobody knows yet whether the order reached the broker.

    **Never resend it.** The order is in ``unknown`` while fxapis confirms the
    result with the broker. Poll it: ``client.orders.wait_until_resolved(err.order_id)``.
    """

    @property
    def retryable(self) -> bool:
        return False


class SendFailedError(APIStatusError):
    """503 ``SEND_FAILED`` -- proven never to have reached the broker. Safe to resend with the same key."""

    _RETRYABLE_CODES = frozenset({"SEND_FAILED"})


class AccountNotReadyError(ConflictError):
    """409 ``ACCOUNT_NOT_READY`` -- the account could not come online in time. Nothing was sent.

    Retry with the same key once it is online (``client.accounts.wait_until_ready``).
    """

    _RETRYABLE_CODES = frozenset({"ACCOUNT_NOT_READY"})


class NoRuntimeError(ConflictError):
    """409 ``NO_RUNTIME`` -- the account is not reachable right now. Nothing was sent; retry with the same key."""

    _RETRYABLE_CODES = frozenset({"NO_RUNTIME"})


class TradingDisabledError(ConflictError):
    """409 ``TRADING_DISABLED`` -- trading is switched off for this account or workspace."""


class IdempotencyInFlightError(ConflictError):
    """409 ``IDEMPOTENCY_IN_FLIGHT`` -- the first request with this key is still running. Retry shortly."""

    _RETRYABLE_CODES = frozenset({"IDEMPOTENCY_IN_FLIGHT"})


class IdempotencyKeyReusedError(ConflictError):
    """409 ``IDEMPOTENCY_KEY_REUSED`` -- that key was used for a *different* request. Use a new key."""


class AccountExistsError(ConflictError):
    """409 ``ACCOUNT_EXISTS`` -- that login and server are already connected in this workspace."""


class AccountExecutingError(ConflictError):
    """409 ``ACCOUNT_EXECUTING`` -- an order is in flight; retry once it settles."""


class AccountHasPositionsError(ConflictError):
    """409 ``ACCOUNT_HAS_POSITIONS`` -- deleting was refused: the account has open positions.

    Close them first, or delete with ``force=True``; they stay open at the broker.
    """


class AccountInWaveError(ConflictError):
    """409 ``ACCOUNT_IN_WAVE`` -- deleting was refused: an unfinished multi-account order includes it."""


class NeedsOperatorError(ConflictError):
    """409 ``NEEDS_OPERATOR`` -- a person must fix the account (password, 2FA, certificate).

    Do not retry in a loop: repeated failed logins are how a broker locks an account.
    """


class AccountNeedsAttentionError(FxapisError):
    """Raised by ``wait_until_ready`` when the account reaches a state only a person can fix.

    ``state`` is one of ``invalid_credentials``, ``needs_2fa``, ``needs_certificate``,
    ``trading_disabled``; ``detail`` is the API's explanation.
    """

    def __init__(self, account_id: str, state: str, detail: str | None) -> None:
        super().__init__(f"account {account_id} needs attention: {state}" + (f" -- {detail}" if detail else ""))
        self.account_id = account_id
        self.state = state
        self.detail = detail


_BY_CODE: dict[str, type[APIStatusError]] = {
    "INVALID_REQUEST": InvalidRequestError,
    "UNAUTHENTICATED": AuthenticationError,
    "MISSING_SCOPE": PermissionDeniedError,
    "ACCOUNT_NOT_FOUND": NotFoundError,
    "ORDER_NOT_FOUND": NotFoundError,
    "WAVE_NOT_FOUND": NotFoundError,
    "POSITION_NOT_FOUND": NotFoundError,
    "NOT_FOUND": NotFoundError,
    "QUOTA_EXCEEDED": QuotaExceededError,
    "FEATURE_NOT_IN_PLAN": FeatureNotInPlanError,
    "RATE_LIMITED": RateLimitedError,
    "ORDER_REJECTED": OrderRejectedError,
    "ORDER_UNRESOLVED": OrderUnresolvedError,
    "SEND_FAILED": SendFailedError,
    "ACCOUNT_NOT_READY": AccountNotReadyError,
    "NO_RUNTIME": NoRuntimeError,
    "TRADING_DISABLED": TradingDisabledError,
    "IDEMPOTENCY_IN_FLIGHT": IdempotencyInFlightError,
    "IDEMPOTENCY_KEY_REUSED": IdempotencyKeyReusedError,
    "ACCOUNT_EXISTS": AccountExistsError,
    "ACCOUNT_EXECUTING": AccountExecutingError,
    "ACCOUNT_HAS_POSITIONS": AccountHasPositionsError,
    "ACCOUNT_IN_WAVE": AccountInWaveError,
    "NEEDS_OPERATOR": NeedsOperatorError,
}

_BY_STATUS: dict[int, type[APIStatusError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    402: PaymentRequiredError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitedError,
}


def error_from_response(
    status: int,
    body: Any,
    headers: dict[str, str] | None = None,
    *,
    idempotency_key: str | None = None,
) -> APIStatusError:
    """Builds the most specific exception for an API error response."""
    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    code = str(error.get("code") or "UNKNOWN")
    message = str(error.get("message") or f"request failed with {status}")
    details = error.get("details")
    request_id = body.get("requestId") if isinstance(body, dict) else None

    cls = _BY_CODE.get(code) or _BY_STATUS.get(status) or (ServerError if status >= 500 else APIStatusError)
    return cls(
        message,
        status=status,
        code=code,
        request_id=request_id if isinstance(request_id, str) else None,
        details=[d for d in details if isinstance(d, dict)] if isinstance(details, list) else [],
        body=body,
        headers=headers,
        idempotency_key=idempotency_key,
    )
