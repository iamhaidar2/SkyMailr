# Testing

## Supported Python version

Run tests with **Python 3.11** — matches `.python-version`, `pytest.ini`, and avoids Django test-client issues seen on **Python 3.14+** (template context copying during UI tests).

```bash
py -3.11 -m pytest tests/
```

With venv activated:

```bash
python -m pytest tests/
```

## Configuration

- `pytest.ini` sets `DJANGO_SETTINGS_MODULE=config.settings.test`.
- Test settings: SQLite at `test_db.sqlite3`, `CELERY_TASK_ALWAYS_EAGER=True` (tasks run synchronously).

## What to run before merging

```bash
py -3.11 -m pytest tests/ -q
```

Optional verbosity:

```bash
py -3.11 -m pytest tests/ -v --tb=short
```

## What the suites cover

| File | Focus |
|------|--------|
| `tests/test_api_core.py` | API health, sends, idempotency (including failed-render replay), tenant isolation, templates preview/approve, webhooks, workflows |
| `tests/test_send_api.py` | Idempotent templated send |
| `tests/test_workflow_engine.py` | Enrollment + `process_due_executions` |
| `tests/test_template_render.py` | Jinja render + missing variables |
| `tests/test_providers.py` | Dummy provider stores payload |
| `tests/test_suppression.py` | Suppression rules |
| `tests/test_llm_schema.py` | LLM schema validation |
| `tests/test_ui.py` | Operator UI smoke (staff login, dashboard, key routes) |

## Confidence and gaps

**Reasonable confidence:** Core API paths for sends, idempotency, cross-tenant 404s, webhook persistence and message update when `provider_message_id` matches, workflow step creating a message with eager Celery + dummy provider.

**Intentionally light or absent:**

- Live **Postal** HTTP against a real server (infra-dependent).
- Full **signature verification** matrix for webhooks (`X-SkyMailr-Signature` path exists in code but is not the focus of integration tests).
- **Load / rate-limit** testing.
- **End-to-end browser** automation (UI tests use Django test client).

## Debugging a failing test

1. Run the single test: `py -3.11 -m pytest tests/test_api_core.py::test_name -vv --tb=long`
2. Check `DATABASE_URL` — should be unset or point to a reachable DB; test settings use SQLite file `test_db.sqlite3`.
3. If failures mention Celery, confirm `config.settings.test` has eager mode (it does).
4. If UI tests fail only on Python 3.14+, **switch to 3.11** for the run.

## Old README note

The README previously showed:

```bash
set DATABASE_URL=
set DJANGO_SETTINGS_MODULE=config.settings.test
pytest
```

Prefer **`py -3.11 -m pytest tests/`** with `pytest.ini` handling `DJANGO_SETTINGS_MODULE`. Unsetting `DATABASE_URL` is only needed if your shell forces a broken remote URL.

## Avoiding “Python 3.14 confusion”

- Use **3.11** for development and CI.
- Do not assume the latest Python works with Django’s test client until the ecosystem catches up.
