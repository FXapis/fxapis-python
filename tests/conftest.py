from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from fxapis import AsyncFxapis, Fxapis, _base


@dataclass
class Recorder:
    """A scripted API: answers requests in order and remembers what was sent."""

    responses: list[Any] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError(f"unexpected request {request.method} {request.url}")
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer(request)
        status, body, *rest = answer
        headers = rest[0] if rest else {}
        return httpx.Response(status, json=body, headers=headers)

    def body(self, index: int = -1) -> Any:
        content = self.requests[index].content
        return json.loads(content) if content else None


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_base, "retry_delay", lambda attempt, error, base=0.5, cap=8.0: 0.0)


@pytest.fixture
def api() -> Recorder:
    return Recorder()


@pytest.fixture
def client(api: Recorder) -> Iterator[Fxapis]:
    http = httpx.Client(transport=httpx.MockTransport(api.handler))
    with Fxapis("fx_test_abc", http_client=http) as c:
        yield c
    http.close()


@pytest.fixture
def make_async(api: Recorder) -> Callable[[], AsyncFxapis]:
    def make() -> AsyncFxapis:
        http = httpx.AsyncClient(transport=httpx.MockTransport(api.handler))
        return AsyncFxapis("fx_test_abc", http_client=http)

    return make


def error(code: str, status: int, *, details: list[dict[str, Any]] | None = None) -> tuple[int, dict[str, Any]]:
    return (
        status,
        {"error": {"code": code, "message": f"{code} happened", "details": details or []}, "requestId": "req-1"},
    )
