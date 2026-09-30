# Verification routes

## Local source of truth

- `pyproject.toml` sets `tests` as the Pytest path and configures Ruff. `docs/OPEN_QUALITY_GATE.md` records a 202-test, clean-Ruff result on 2026-09-22; that is a historical baseline, not today's result.
- For Python changes, start with the relevant `tests/test_*.py` files. The maintained broad commands are `.\env\Scripts\python.exe -m pytest -q -p no:cacheprovider` and `.\env\Scripts\ruff.exe check app tests --statistics`. Use the broader checks when a shared boundary or release gate warrants them.
- Browser-oriented Node tests live in `tests/test_browser_print.js`, `tests/test_order_edit_print.js`, and `tests/test_order_edit_save.js`; inspect their invocation and scope before using them. The public `../menu` repository has no checked-in automated tests in the inspected tree.
- `alembic/versions` has source head `a93026productdaily` as of 2026-09-30. Recompute the head before migration work and verify the actual target database before claiming an upgrade was applied.

## Task-specific paths

| Change | First useful tests/evidence | Additional boundary |
| --- | --- | --- |
| Checkout, pricing, offers | `test_online_app.py`, `test_financial_business_rules.py`, `test_advanced_offer_logic.py`, `test_pricing_preview_authorization.py`, `test_menu_checkout_controls.py` | `../menu/js/app.js` payload and rendered response |
| Customer identity/session | `test_customer_account_login.py`, `test_customer_session.py`, `test_customer_account_activation.py`, `test_customer_account_notifications.py` | `../menu/js/customer-session.js`, `account.js`, profile flows |
| Customer points and redemption | `test_customer_loyalty.py`, `test_customer_redemption.py`, `test_print_agent_integration.py` | Admin rules, authenticated reservation, idempotency, confirmation/edit/cancellation, balance, receipt fields, source migration versus applied schema, `../menu` checkout/account/profile display |
| Orders/status/live | `test_order_status_history.py`, `test_transaction_ownership.py`, `test_order_counter.py`, `test_websocket_auth.py`, `test_order_notification_port.py` | cashier/menu WebSocket consumers |
| Shifts/reports/expenses | `test_shifts_business_date.py`, `test_shifts_overnight.py`, `test_financial_business_rules.py`, `test_admin_expenses.py` | admin/cashier UI and persistence |
| WhatsApp/external integrations | `test_whatsapp_outbox.py`, `test_whatsapp_inbound_verification.py`, `test_whatsapp_notifications.py`, `test_meta_agent_gateway.py` | flags, retries, remote provider behavior |
| Printing | `test_print_agent_integration.py` and the Node print tests | local print agent plus cashier client |

For all production-facing changes, distinguish source checks, applied migrations, deployed revision, and live user journey. Never run migrations, send messages, or mutate production data merely to complete discovery. `.env` is tracked in this checkout: treat it as sensitive and do not print or copy its contents into project context.
