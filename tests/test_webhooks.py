from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from fxapis import WebhookVerificationError, webhooks

SECRET = "whsec_test"
BODY = json.dumps({"id": "e1", "type": "order.filled", "createdAt": "2026-10-08T12:00:00.000Z", "data": {"id": "o1"}})
T = 1_791_400_000


def sig(secret: str, at: int = T, body: str = BODY) -> str:
    return hmac.new(secret.encode(), f"{at}.{body}".encode(), hashlib.sha256).hexdigest()


def test_returns_the_event_when_the_signature_matches() -> None:
    event = webhooks.verify(BODY, f"t={T},v1={sig(SECRET)}", SECRET, now=T)
    assert event["id"] == "e1"
    assert event["data"] == {"id": "o1"}


def test_accepts_bytes_and_either_signature_during_rotation() -> None:
    header = f"t={T},v1={sig('whsec_new')},v1={sig(SECRET)}"
    assert webhooks.verify(BODY.encode(), header, SECRET, now=T)["type"] == "order.filled"


@pytest.mark.parametrize(
    ("body", "header", "now", "message"),
    [
        (BODY, f"t={T},v1={sig('whsec_other')}", T, "does not match"),
        (BODY + " ", f"t={T},v1={sig(SECRET)}", T, "does not match"),
        (BODY, f"t={T},v1={sig(SECRET)}", T + 301, "tolerance"),
        (BODY, None, T, "missing"),
        (BODY, "garbage", T, "malformed"),
    ],
)
def test_refuses_what_it_should(body: str, header: str | None, now: int, message: str) -> None:
    with pytest.raises(WebhookVerificationError, match=message):
        webhooks.verify(body, header, SECRET, now=now)
