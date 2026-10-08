# Changelog

All notable changes to this package. Versions follow [Semantic Versioning](https://semver.org/):
while the version is `0.x`, a minor release (`0.2.0`) may change the API and a patch release
(`0.1.2`) does not.

## [Unreleased]

## [0.1.2] — 2026-10-08

- Multi-account orders accept up to 1,000 accounts (was 500), matching the API; your plan's own limit still applies.
- ACCOUNT_LEASED_ELSEWHERE, ACCOUNT_EXECUTING and SESSIONS_NOT_SYNCED prove nothing was done: the client retries them, and retryable is true for them.

## [0.1.1] — 2026-10-08

- First release on PyPI: `pip install fxapis`. Same client as 0.1.0.

## [0.1.0] — 2026-10-07

- First release, installable from this repository. Sync and async clients on httpx; fully typed (`py.typed`, `mypy --strict`); idempotency keys added for you; one exception class per error code; `wait_until_ready()`, `wait_until_resolved()`, `wait_until_settled()`.
