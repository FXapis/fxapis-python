"""Verifying webhook deliveries from fxapis.

    from fxapis import webhooks

    event = webhooks.verify(request.body, request.headers.get("fxapis-signature"), secret)
    if seen(event["id"]):   # deliveries can repeat: deduplicate on the event id
        return 200

Pass the body exactly as it arrived (bytes or str), before any JSON parsing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from .errors import FxapisError

TOLERANCE_SECONDS = 300


class WebhookVerificationError(FxapisError):
    """The delivery's signature is missing, malformed, too old, or does not match."""


def verify(
    payload: str | bytes,
    signature_header: str | None,
    secret: str,
    *,
    tolerance: int = TOLERANCE_SECONDS,
    now: float | None = None,
) -> dict[str, Any]:
    """Check the ``fxapis-signature`` header and return the event.

    During a secret rotation the header carries two signatures; either one matching is enough.
    """
    if not signature_header:
        raise WebhookVerificationError("missing fxapis-signature header")
    body = payload.decode("utf-8") if isinstance(payload, bytes) else payload

    timestamp: int | None = None
    signatures: list[str] = []
    for part in signature_header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t" and value.isdigit():
            timestamp = int(value)
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp is None or not signatures:
        raise WebhookVerificationError("malformed fxapis-signature header")

    current = int(now if now is not None else time.time())
    if abs(current - timestamp) > tolerance:
        raise WebhookVerificationError("signature timestamp is outside the tolerance")

    expected = hmac.new(secret.encode("utf-8"), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise WebhookVerificationError("signature does not match")
    event: dict[str, Any] = json.loads(body)
    return event
