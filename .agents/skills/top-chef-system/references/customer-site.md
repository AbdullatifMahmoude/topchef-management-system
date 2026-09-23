# Public customer site (`../menu`)

`../menu` is a separate static HTML/CSS/JavaScript repository with `vercel.json` rewrites for `/profile`, `/profile/settings`, and `/ai-menu`. Its JavaScript sets an API base pointing to the FastAPI service. Verify the current deployed URLs/config separately when deployment matters.

## Route to the source

| Customer task | Site source | Backend contract |
| --- | --- | --- |
| Catalog, offers, cart, checkout, reviews, live refresh | `index.html`, `js/app.js`, `css/style.css` | `menu`, `offer`, `pricing`, `orders`, `settings`, `comments` routers/schemas |
| Session and notification bootstrap | `js/customer-session.js` | `customer/account_router.py`, account schemas/security |
| Login, account challenge and UI | `js/account.js`, `css/account.css` | `customer/account_router.py` |
| Profile and past orders | `profile.html`, `js/profile.js`, `css/profile.css` | `/customer-auth/me/*` routes |
| Name, address, devices | `account-settings.html`, `js/account-settings.js`, `css/account-settings.css` | `/customer-auth/me/*` routes |

`js/app.js` initially fetches `/menu/categories`, `/menu/products`, `/offers/`, and `/settings/menu-checkout`; it previews offers at `/pricing/preview`, submits at `/orders/`, and subscribes to `/orders/ws/online`. The guest and authenticated order paths differ: the latter uses `window.customerApiRequest` from `js/customer-session.js`. Check both when changing checkout.

The site generates an order idempotency key and sends product IDs, quantity, unit price, payment method, and optional offer/customer data. The server validates authoritative prices and business controls. Search `js/app.js` and the backend order/pricing schemas before changing fields or error responses. Live events and account refresh also cross the repository boundary.

This repository has no package manifest or checked-in test suite in the inspected source. Browser checks should exercise the affected flow against a suitable API environment; do not treat a static page render as proof checkout, auth, or live updates work.
