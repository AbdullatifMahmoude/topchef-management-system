# Top Chef — Enterprise Restaurant Management & POS System

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-336791.svg?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-Pub%2FSub%20%26%20Lock-DC382D.svg?style=flat&logo=redis&logoColor=white)](https://redis.io)
[![Status](https://img.shields.io/badge/Status-Production%20Deployed-success.svg?style=flat)]()

**Top Chef** is a high-performance, real-time restaurant management, Point of Sale (POS), and financial custody system designed for busy hospitality environments. Built on top of **FastAPI**, **Async SQLAlchemy**, and **Redis**, it coordinates front-of-house operations, kitchen dispatch, online order ingestion, and auditable shift accounting.

> 🚀 **Production Status:** This system is **live in commercial production**, actively managing daily operations, in-store ordering, kitchen tickets, and cash settlement in an active commercial restaurant.

---

## 🌐 Connected Ecosystem

The backend serves as the single source of truth for an expanding omnichannel restaurant infrastructure:

```
                      ┌────────────────────────────────────────┐
                      │    Live Public Customer Web Platform   │
                      │  (Online Menu, Cart, Loyalty, Auth)    │
                      └──────────────────┬─────────────────────┘
                                         │ REST & WebSockets
                                         ▼
┌──────────────────────┐      ┌────────────────────────┐      ┌──────────────────────┐
│  Cashier POS Portal  │ ───► │  Top Chef FastAPI Core │ ◄─── │   Admin Backoffice   │
│ (In-store Orders)    │      │  (Async Engine & Sync) │      │  (Reports & Control) │
└──────────┬───────────┘      └──────────┬─────────────┘      └──────────────────────┘
           │ Loopback HTTP               │
           ▼                             │ Push Notifications & Handoffs
┌──────────────────────┐                 ▼
│ Windows Print Agent  │      ┌────────────────────────────────────────┐
│ (Thermal Receipts)   │      │   Dedicated Delivery Mobile App (Soon) │
└──────────────────────┘      │  (Rider Dispatch, GPS & Cash Custody)  │
                              └────────────────────────────────────────┘
```

1. **Integrated Customer Web Platform (Live):**
   * Synchronized in real time with the backend.
   * Customers browse active digital menus, place dine-in/pickup/delivery orders, check item availability, track order progress, and redeem Cairo-calendar monthly loyalty points.
2. **Dedicated Delivery Rider Application (In Active Development):**
   * A dedicated mobile application for delivery personnel is currently under development.
   * Will integrate directly with the order state machine for live dispatching, order handoffs, and real-time cash custody tracking from customer payment to cashier drop.
3. **In-Store Cashier POS & Backoffice Dashboard:**
   * Ultra-fast, touch-optimized cashier UI designed for sub-second ticket creation, guest addresses, and phone lookup.
   * Administrative console for real-time sales analytics, business-date reports, menu controls, and financial reconciliation.
4. **Local Hardware Print Agent (`print_agent`):**
   * Dedicated background service interfacing with thermal ESC/POS printers for kitchen tickets and customer receipts.

---

## ⚡ Key Modules & Features

### 1. Point of Sale & Order Lifecycle
* **Finite State Machine:** Deterministic status flow (`new` ➔ `confirmed` ➔ `out_for_delivery` ➔ `delivered` / `cancelled`) with role guards preventing illegal transitions.
* **Multi-Channel Ordering:** Unified processing for Takeaway, Dine-in, Delivery, and Phone Reservations.
* **Customer Lookup & Guest Orders:** Phone normalization (Egyptian 11-digit standards), saved address selection, and guest address preservation without customer profile friction.
* **Outbox & Real-time Broadcast:** Native WebSockets push status and inventory updates across terminals and kitchen displays.

### 2. Audited Shift Cash & Financial Custody Ledger
* **Tamper-Evident Cash Tracking:** Strict ledger tracking cashier opening balances, drawer expenses, customer collections, and rider physical handoffs.
* **Audited Administrative Reversals:** Role-gated order cancellation for delivered orders that automatically constructs reverse financial movements while preserving complete audit history.
* **Business Calendar & Shift Reconciliation:** Shift reports respect restaurant business hours (overnight shifts closing after midnight belong to the active business day).
* **Closing Snapshots:** Permanent immutable snapshots taken upon shift closure, isolating closed-shift accounting from post-close corrections.

### 3. Dynamic Menu, Pricing & Loyalty Engine
* **Catalog Management:** Categories, products, modifiers, customizable toppings, and automated seasonal pricing.
* **Daily Availability Toggles:** Instant cashier whole-product temporary pausing that automatically restores on the next business day (skipping weekly holidays).
* **Tiered Offers & Promotions:** Fixed discounts, percentage caps, buy-X-get-Y, and minimum cart constraints computed server-side with idempotency validation.
* **Cairo-Month Loyalty Ledger:** Monthly points accumulation engine allowing points earned in the current calendar month to be redeemed during checkout.

### 4. Hardware Thermal Receipt Printing (`print_agent`)
* Independent local printing daemon communicating directly with network/USB thermal printers (ESC/POS).
* Automatic print-on-acceptance for kitchen orders, customer receipt layouts with Arabic typography shaping, and digital bill verification.

### 5. Meta / WhatsApp Business Integration
* Webhook engine for inbound/outbound Meta Business Platform interactions.
* Automated WhatsApp OTP challenges and customer verification.

---

## 🛠 Tech Stack

| Layer | Technologies |
| --- | --- |
| **Backend** | Python 3.12+, FastAPI, Starlette, Pydantic v2 |
| **Database & ORM** | PostgreSQL (AsyncPG driver), SQLAlchemy 2.0 (Async Engine), Alembic |
| **Caching & Messaging** | Redis (Pub/Sub, Distributed Locks, Leader Election) |
| **Frontend** | Vanilla ES6+ JavaScript, Responsive CSS3, HTML5 (Zero-bloat, high-performance UI) |
| **Printing & POS Service** | Python, ESC/POS, Local Loopback HTTP API |
| **Testing** | Pytest, AnyIO, Asyncio, Node.js VM assertion runners |

---

## 📁 Repository Structure

```
.
├── alembic/                      # Database migrations & revision history
├── app/
│   ├── core/                     # Config, database engine, Redis, business calendar, security
│   ├── frontend/                 # Bundled Admin Backoffice & Cashier POS UI
│   │   ├── cashier/              # Fast-response cashier POS interface & assets
│   │   ├── css/                  # Backoffice stylesheets
│   │   └── js/                   # Dashboard, charts, live shift modules
│   └── modules/                  # Domain-Driven Architecture modules
│       ├── ai_menu/              # AI-assisted menu recommendations
│       ├── auth/                 # JWT authentication & session token blacklisting
│       ├── customer/             # Customer profiles, addresses & monthly loyalty
│       ├── infrastructure/       # Global middleware, role guards, leader workers
│       ├── menu/                 # Categories, products & availability rules
│       ├── meta_agent/           # Meta/WhatsApp Business Agent integration
│       ├── offer/                # Coupons, promotions & discount calculation
│       ├── orders/               # Order domain, state machine & real-time events
│       ├── pricing/              # Pricing domain & checkout controls
│       ├── report/               # Sales & performance reports
│       ├── settings/             # System runtime configuration
│       ├── shifts/               # Cash custody, drawer expenses & shift reconciliation
│       └── users/                # Staff management & RBAC roles
├── print_agent/                  # Local Windows ESC/POS thermal printer service
├── tests/                        # Comprehensive automated test suite
├── pyproject.toml                # Project metadata & Python dependencies
└── requirements.txt              # Production dependency lock
```

---

## 🚀 Getting Started

### Prerequisites
* **Python 3.12+**
* **PostgreSQL 15+**
* **Redis 7+**
* **Node.js 18+** (for frontend validation tests)

### 1. Clone & Setup Environment
```bash
git clone https://github.com/AbdullatifMahmoude/topchef-management-system.git
cd topchef-management-system

python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a local `.env` file in the project root (ensure it is never committed):
```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/topchef_db
SECRET_KEY=your-secure-secret-key-32-chars-minimum
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=720
REDIS_URL=redis://localhost:6379/0
TERMINAL_ID=T1
```

### 3. Run Database Migrations
```bash
alembic upgrade head
```

### 4. Run the Application Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
* **POS Cashier Interface:** `http://localhost:8000/cashier/cashier.html`
* **Admin Dashboard:** `http://localhost:8000/dashboard.html`
* **Interactive API Docs (Swagger):** `http://localhost:8000/docs`

---

## 🧪 Testing & Verification

The project includes an end-to-end automated test suite covering financial journeys, concurrency locks, shift edge cases, and cashier UX:

```bash
# Run backend pytest suite
pytest tests/ -v

# Run cashier frontend assertion suites
node tests/test_cashier_customer_lookup.js
node tests/test_cashier_expenses_live.js
node tests/test_shifts_post_close_ui.js
```

---

## 🔒 Security & Data Integrity
* **Immutable Financial Records:** Ledger movements use append-only semantics. Corrections generate counter-movements linking to the original movement ID.
* **Role-Based Access Control (RBAC):** Distinct capability levels for Admin, Cashier, Kitchen, and Delivery staff.
* **Zero Secret Leakage:** Environment variables and sensitive secrets are strictly excluded from source tracking.

---

## 📄 License
Proprietary software. All rights reserved. Developed for Top Chef commercial operations.
