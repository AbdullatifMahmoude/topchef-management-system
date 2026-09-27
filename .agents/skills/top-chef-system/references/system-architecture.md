# System architecture (source map)

## Entry points and layers

- `pyproject.toml` defines Python 3.12+, FastAPI, SQLAlchemy, Redis, and `app.main:app`. `app/main.py` registers the module routers and mounts `app/frontend` last at `/` for the admin login, dashboard, cashier, and static assets.
- `app/modules/<domain>/router.py` is the HTTP/WebSocket boundary. Most domains then use `schemas.py` for contracts, `service.py` for business rules, `repository.py` for persistence queries, and `models.py` for SQLAlchemy tables. Some domains use extra files; inspect the actual module.
- `app/core/config.py` owns settings and feature gates. `app/core/database.py` builds the async SQLAlchemy engine/session. `alembic/versions` contains source migrations; `alembic/env.py` provides migration metadata. Do not infer remote migration state from source files.
- `app/core/redis.py`, `events.py`, and `leader.py` handle cache/infrastructure, order events, and singleton worker leadership across replicas. `app/main.py` starts/stops them through lifespan according to `APP_ROLE` (`api`, `worker`, or default `all`).
- `app/core/business_calendar.py` defines business-date/holiday helpers; `app/core/enums.py` defines shared domain enums. Use these before changing date or state logic.

## Domain routes: inspect these first

| Task | Source entry | Adjacent rules |
| --- | --- | --- |
| Staff login, access | `app/modules/auth/router.py`; `app/modules/users/router.py` | `app/modules/infrastructure/middlewares/auth.py`, `role_guard.py`, `app/core/security.py` |
| Catalog | `app/modules/menu/router.py` | menu schemas/service/repository/models; bundled admin `app/frontend/js/product.js`, `category.js` |
| Offers and totals | `app/modules/offer/router.py`; `app/modules/pricing/router.py` | offer service, `app/modules/pricing/service.py`, `domain.py` |
| Orders and live updates | `app/modules/orders/router.py` | orders schemas/service/repository/models, `state_machine.py`, `notifications.py`, `app/core/events.py` |
| Customer records/accounts | `app/modules/customer/router.py`; `account_router.py` | customer schemas/service/repository/models, `account_security.py` |
| Customer points and redemption | `app/modules/settings/router.py`; `app/modules/customer/account_router.py` | `customer/loyalty.py`, order service reservation/confirmation/edit/cancellation hooks, point ledger and order redemption migrations; public selection in `../menu/js/app.js`, display in `account.js` and `profile.js`, cashier receipt in `print_agent/printer.py` |
| Payments, menu controls, WhatsApp | `app/modules/settings/router.py`; `whatsapp_webhook.py` | settings schemas/service/repository/models and `whatsapp*` modules |
| Shifts, expenses, reports | `app/modules/shifts/router.py`; `app/modules/report/router.py` | corresponding services/models and business calendar |
| Reviews, AI menu, Meta integration | `app/modules/comments/router.py`; `ai_menu/router.py`; `meta_agent/router.py` | corresponding services; Meta routes register only when `META_AGENT_ENABLED` |

`app/frontend/dashboard.html` loads admin scripts in `app/frontend/js/`; `app/frontend/cashier/cashier.html` loads `app/frontend/cashier/js/`. Those clients use the API on their current origin. The separate customer site is mapped in `customer-site.md`.

## Important boundaries

- `AuthMiddleware` has explicit public HTTP routes and hands WebSocket authentication to the orders channel handler; role/capability checks also occur in dependencies. Inspect the complete route and dependency path before changing permissions.
- `OrderService` validates catalog items/prices and checkout controls, uses an order transaction and idempotency key, and calls pricing/offer services. `OrderStateMachine` defines allowed status changes. Changes to totals, order creation, or status must check client payload, persistence, notifications, and response.
- Redis leader election gates global workers. `run_daily_reconciliation` in `app/modules/infrastructure/workers/sync_worker.py` currently only logs an “integrity check,” sleeps for 60 seconds, logs completion, then waits an hour. Those logs do **not** demonstrate a database integrity check.
- `print_agent/service.py` is a separate local FastAPI service for the Windows print agent; the cashier browser uses its loopback API. Check `print_agent/printer.py`, `app/frontend/cashier/js/cashier.js`, and print-agent tests together for print changes.
- Source references Supabase-hosted Postgres and FastAPI Cloud. Treat source migrations, configured connection, and live schema as separate facts; production verification requires fresh evidence.
