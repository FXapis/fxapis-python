# Contributing

## This client is generated, mostly

The resource methods in `src/fxapis/_client.py` and `_async_client.py` are generated from
fxapis's OpenAPI spec in the main repository — the sync and async clients mirror each other
method for method. That generation step lives in the private monorepo, not here, because it also
generates the TypeScript SDK and the published OpenAPI document from the same source of truth.

**What that means for a pull request here:**

- A new or changed **endpoint method** (name, parameters, return type) needs to come from a
  change to the API first, then a regeneration — open an issue or email
  [support@fxapis.com](mailto:support@fxapis.com) rather than hand-editing a generated method.
- The **hand-written parts** are fair game: `_base.py` (the HTTP layer, retries, idempotency),
  `errors.py` (the exception hierarchy), helper methods (`wait_until_ready`, `wait_until_resolved`,
  `wait_until_settled`, pagination `iter()`), and `types.py`'s docstrings.
- **Tests, docs and examples** are always welcome.

## Before you open a pull request

```bash
pip install -e ".[dev]"
ruff check .      # lint
mypy              # strict type checking
pytest -q         # 85+ tests, no network — a Recorder fixture scripts the HTTP layer
```

These are exactly what the `ci` workflow runs, on Python 3.10 through 3.14. A behaviour change
to a method's signature or return shape should match the TypeScript SDK's equivalent method —
the two are meant to stay in step.

## Reporting a bug

Open an [issue](https://github.com/FXapis/fxapis-python/issues) with the method called, the
exception raised (`.code`, `.message`, `.request_id`), and what you expected. For account or
billing issues rather than a client bug, email [support@fxapis.com](mailto:support@fxapis.com).
