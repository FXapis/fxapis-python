# Changelog

All notable changes to this package. Versions follow [Semantic Versioning](https://semver.org/):
while the version is `0.x`, a minor release (`0.2.0`) may change the API and a patch release
(`0.1.2`) does not.

## [Unreleased]

## [0.2.1] — 2026-10-20

- problem.code can be PLATFORM_ISSUE: accounts cannot come online because of a problem on fxapis's side; nothing about the account needs changing, and there are no actions.
- New API key scope billing:read. Reading the subscription, invoices, usage charges, agreement, standing and daily usage needs it for keys made from 21 October 2026; older keys with accounts:read keep access.
- If your code switches exhaustively on problem.code or on scopes, handle the new value.

## [0.2.0] — 2026-10-16

- Added client.copy (sync and async): strategies, subscriptions (create, change, pause, reset, delete), executions with filters and page iterators, links, and status.
- Copy trading is set up but copying starts after scheduled maintenance; until then calls that start copying raise an error with code COPY_TRADING_PAUSED (HTTP 503).

## [0.1.7] — 2026-10-15

- client.accounts.figures(account_id, fresh=False): balance, equity, margin, free margin, margin level, credit and profit as decimal strings
- client.quotes.get(account_id, symbols=..., instruments=...): live bid/ask from the account's own broker, with time, brokerTime, ageMs, marketOpen, stale and tradeMode
- CapabilityUnavailableError for the 501 CAPABILITY_UNAVAILABLE answer

## [0.1.6] — 2026-10-15

- client.admin.keys (list, create, get, update, revoke), sync and async: manage your workspace's API keys with an admin key (fx_admin_…) made by the workspace owner in the console.
- An ordinary key used on an admin method raises PermissionDeniedError (ADMIN_KEY_REQUIRED).

## [0.1.5] — 2026-10-14

- events.list() / events.iter(after=...) / events.get(): catch up on webhook events after downtime
- webhooks.replay(): re-send what an endpoint missed (failed only by default)
- webhooks.deliveries() and webhooks.delivery(): paged delivery logs with the request and response

## [0.1.4] — 2026-10-14

- waves.create() accepts instrument= instead of symbol=, for multi-account orders across accounts at different brokers (exactly one of the two)

## [0.1.3] — 2026-10-11

- Webhooks: fxapis.webhooks.verify(payload, signature_header, secret) checks a delivery's fxapis-signature header and returns the event as a dict; it raises fxapis.WebhookVerificationError when the signature is missing, malformed, more than 5 minutes old or does not match. During a secret rotation either signature is accepted.

## [0.1.2] — 2026-10-08

- Multi-account orders accept up to 1,000 accounts (was 500), matching the API; your plan's own limit still applies.
- ACCOUNT_LEASED_ELSEWHERE, ACCOUNT_EXECUTING and SESSIONS_NOT_SYNCED prove nothing was done: the client retries them, and retryable is true for them.

## [0.1.1] — 2026-10-08

- First release on PyPI: `pip install fxapis`. Same client as 0.1.0.

## [0.1.0] — 2026-10-07

- First release, installable from this repository. Sync and async clients on httpx; fully typed (`py.typed`, `mypy --strict`); idempotency keys added for you; one exception class per error code; `wait_until_ready()`, `wait_until_resolved()`, `wait_until_settled()`.
