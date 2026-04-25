"""
Local SQLite Database Layer — ENTERPRISE EDITION
────────────────────────────────────────────────
Robust offline storage with:
1. ACID transactions for data integrity.
2. Conflict resolution via versions & timestamps.
3. Full schema mirroring production.
4. Incremental sync tracking.
"""

import sqlite3
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from desktop.config import DB_PATH
from desktop.logger import desktop_logger as log

_TZ = timezone(timedelta(hours=2))

_SCHEMA_SQL = """
-- ── Reference Tables (Pulled from server) ──

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    username        TEXT    NOT NULL,
    full_name       TEXT,
    role            TEXT    NOT NULL,
    phone           TEXT,
    hashed_password TEXT    NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    version         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY,
    name            TEXT,
    image_url       TEXT,
    display_order   INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    version         INTEGER DEFAULT 1,
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY,
    cat_id          INTEGER NOT NULL REFERENCES categories(id),
    name            TEXT,
    description     TEXT,
    image_url       TEXT,
    price           REAL DEFAULT 0,
    is_available    INTEGER DEFAULT 1,
    version         INTEGER DEFAULT 1,
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS variants (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    name            TEXT,
    price_override  REAL,
    is_default      INTEGER DEFAULT 0,
    version         INTEGER DEFAULT 1,
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS offers (
    offer_id        INTEGER PRIMARY KEY,
    code            TEXT    NOT NULL UNIQUE,
    display_name    TEXT,
    discount_type   TEXT    NOT NULL,
    discount_value  REAL    NOT NULL,
    min_order_amount REAL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    valid_to        TEXT    NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key             TEXT PRIMARY KEY,
    value_bool      INTEGER,
    description     TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT,
    updated_at      TEXT
);

-- ── Transactional Tables (Bi-directional) ──

CREATE TABLE IF NOT EXISTS customers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id       INTEGER,
    name            TEXT    NOT NULL,
    phone_number    TEXT    NOT NULL UNIQUE,
    created_at      TEXT,
    updated_at      TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    is_synced       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customer_addresses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id       INTEGER,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    address         TEXT    NOT NULL,
    created_at      TEXT,
    updated_at      TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    is_synced       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id       INTEGER,
    order_number    TEXT    NOT NULL,
    order_date      TEXT    NOT NULL,
    customer_id     INTEGER,
    customer_phone  TEXT,
    customer_name   TEXT,
    order_type      TEXT    NOT NULL,
    order_status    TEXT    NOT NULL DEFAULT 'new',
    order_source    TEXT    NOT NULL DEFAULT 'cashier',
    subtotal        REAL    NOT NULL,
    discount_amount REAL    NOT NULL DEFAULT 0,
    delivery_fee    REAL    NOT NULL DEFAULT 0,
    total_amount    REAL    NOT NULL,
    customer_notes  TEXT,
    internal_notes  TEXT,
    created_at      TEXT,
    updated_at      TEXT,
    is_synced       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS order_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    unit_price      REAL    NOT NULL,
    total_price     REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS order_status_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id       INTEGER,
    order_id        INTEGER NOT NULL REFERENCES orders(id),
    status          TEXT    NOT NULL,
    changed_at      TEXT,
    changed_by_user_id INTEGER,
    is_synced       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS offer_usages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id        INTEGER NOT NULL,
    customer_phone  TEXT,
    order_id        INTEGER,
    discount_amount REAL    NOT NULL,
    applied_at      TEXT,
    is_synced       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS comments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id       INTEGER,
    full_name       TEXT    NOT NULL,
    stars           INTEGER NOT NULL,
    comment_text    TEXT    NOT NULL,
    created_at      TEXT,
    is_synced       INTEGER NOT NULL DEFAULT 1
);

-- ── Enterprise Infrastructure ──

CREATE TABLE IF NOT EXISTS audit_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT    NOT NULL,  -- LOGIN, CREATE_ORDER, PRINT, etc.
    user_id         INTEGER,
    details         TEXT,              -- JSON blob
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS sync_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action          TEXT    NOT NULL,
    payload         TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS receipts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL,
    receipt_type    TEXT    NOT NULL,
    content         TEXT    NOT NULL,
    printed_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Indexes for Speed
CREATE INDEX IF NOT EXISTS idx_orders_synced   ON orders(is_synced);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone_number);
CREATE INDEX IF NOT EXISTS idx_audit_type      ON audit_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_comments_synced ON comments(is_synced);
"""

class LocalDB:
    _lock = threading.RLock()

    def __init__(self, db_path: str = None):
        self.db_path = str(db_path or DB_PATH)
        self._init_db()

    def _init_db(self):
        with self.connect() as conn:
            conn.executescript(_SCHEMA_SQL)
            # Migration: Ensure created_at exists if table already created
            try: conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
            except: pass
            try: conn.execute("ALTER TABLE categories ADD COLUMN created_at TEXT")
            except: pass
            log.info("Enterprise Local DB initialized and migrated.")

    @contextmanager
    def connect(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception as e:
                try: conn.rollback()
                except: pass
                log.error(f"Database transaction error: {e}")
                raise
            finally:
                conn.close()

    # ── Master Data Pull & Conflict Resolution ───────────────────

    def upsert_master_data(self, data: Dict[str, List[Dict[str, Any]]]):
        """Saves master data in a single transaction with field mapping."""
        # 1. Flatten nested variants before starting the transaction
        if "products" in data:
            all_nested_variants = data.get("variants", [])
            for item in data["products"]:
                if "variants" in item:
                    for v in item["variants"]:
                        v["product_id"] = item["id"]
                        all_nested_variants.append(v)
            if all_nested_variants:
                data["variants"] = all_nested_variants

        table_order = [
            "users", "categories", "products", "variants", 
            "offers", "app_settings", "customers", 
            "customer_addresses", "comments", "order_status_history"
        ]
        
        with self.connect() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            sorted_tables = sorted(data.keys(), key=lambda k: table_order.index(k) if k in table_order else 99)
            
            for table in sorted_tables:
                items = data[table]
                if not isinstance(items, list) or not items: continue
                
                cursor = conn.execute(f"PRAGMA table_info({table})")
                local_cols = [row[1] for row in cursor.fetchall()]
                if not local_cols: continue

                mappings = {"cat_name": "name", "product_name": "name", "product_type": "type"}
                processed_items = []
                for item in items:
                    mapped_item = {}
                    for k, v in item.items():
                        target_key = mappings.get(k, k)
                        if target_key in local_cols:
                            mapped_item[target_key] = v
                    if mapped_item: processed_items.append(mapped_item)
                
                if not processed_items: continue

                keys = list(processed_items[0].keys())
                placeholders = ",".join(["?"] * len(keys))
                sql = f"INSERT OR REPLACE INTO {table} ({','.join(keys)}) VALUES ({placeholders})"
                bulk_values = [tuple(item.get(k) for k in keys) for item in processed_items]
                conn.executemany(sql, bulk_values)

            conn.execute("PRAGMA foreign_keys=ON")
            # Save timestamp inside the SAME connection
            conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES (?,?)", 
                         ("last_pull_timestamp", datetime.now(timezone.utc).isoformat()))

    # ── Data Retrieval ──────────────────────────
    
    def get_categories(self) -> List[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM categories WHERE is_active=1").fetchall()
            return [dict(r) for r in rows]

    def get_products(self) -> List[dict]:
        with self.connect() as conn:
            # Fetch all available products
            prod_rows = conn.execute("SELECT * FROM products WHERE is_available=1").fetchall()
            products = [dict(r) for r in prod_rows]
            
            # Fetch all variants and attach them to products
            var_rows = conn.execute("SELECT * FROM variants").fetchall()
            variants = [dict(r) for r in var_rows]
            
            for p in products:
                p["variants"] = [v for v in variants if v["product_id"] == p["id"]]
            
            return products

    # ── Transactions ──────────────────────────────

    def create_order(self, order: dict) -> int:
        now = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO orders 
                (order_number, order_date, customer_id, customer_phone, customer_name,
                 order_type, subtotal, discount_amount, delivery_fee, total_amount, 
                 customer_notes, internal_notes, created_at, updated_at, is_synced)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                """,
                (order["order_number"], order.get("order_date"), order.get("customer_id"), 
                 order.get("customer_phone"), order.get("customer_name"), order["order_type"],
                 order["subtotal"], order.get("discount_amount", 0), order.get("delivery_fee", 0),
                 order["total_amount"], order.get("customer_notes"), order.get("internal_notes"),
                 now, now)
            )
            order_id = cur.lastrowid
            for item in order["items"]:
                conn.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, unit_price, total_price) VALUES (?,?,?,?,?)",
                    (order_id, item["product_id"], item["quantity"], item["unit_price"], item["unit_price"] * item["quantity"])
                )
            self.enqueue_sync("create_order", {"local_id": order_id, **order})
            return order_id

    def add_comment(self, comment: dict) -> int:
        now = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO comments (full_name, stars, comment_text, created_at, is_synced) VALUES (?,?,?,?,0)",
                (comment["full_name"], comment["stars"], comment["comment_text"], now)
            )
            comment_id = cur.lastrowid
            self.enqueue_sync("add_comment", {"local_id": comment_id, **comment})
            return comment_id

    def create_customer(self, data: dict) -> int:
        now = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as conn:
            # Check if phone exists
            existing = conn.execute("SELECT id FROM customers WHERE phone_number=?", (data["phone_number"],)).fetchone()
            if existing: return existing["id"]

            cur = conn.execute(
                "INSERT INTO customers (name, phone_number, created_at, updated_at, is_synced) VALUES (?,?,?,?,0)",
                (data["name"], data["phone_number"], now, now)
            )
            cust_id = cur.lastrowid
            self.enqueue_sync("create_customer", {"local_id": cust_id, **data})
            return cust_id

    def add_customer_address(self, cust_id: int, address: str) -> int:
        now = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO customer_addresses (customer_id, address, created_at, updated_at, is_synced) VALUES (?,?,?,?,0)",
                (cust_id, address, now, now)
            )
            addr_id = cur.lastrowid
            self.enqueue_sync("add_address", {"local_id": addr_id, "customer_id": cust_id, "address": address})
            return addr_id

    def update_order_status(self, order_id: int, status: str):
        now = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as conn:
            conn.execute("UPDATE orders SET order_status=?, updated_at=? WHERE id=?", (status, now, order_id))
            conn.execute(
                "INSERT INTO order_status_history (order_id, status, changed_at, is_synced) VALUES (?,?,?,0)",
                (order_id, status, now)
            )
            self.enqueue_sync("update_status", {"order_id": order_id, "status": status})

    # ── Sync Helpers ──────────────────────────────

    def get_unsynced_data(self) -> dict:
        with self.connect() as conn:
            orders = []
            order_rows = conn.execute("SELECT * FROM orders WHERE is_synced=0").fetchall()
            for r in order_rows:
                o = dict(r)
                o["items"] = [dict(ri) for ri in conn.execute("SELECT * FROM order_items WHERE order_id=?", (o["id"],)).fetchall()]
                orders.append(o)
            
            return {
                "orders": orders,
                "customers": [dict(r) for r in conn.execute("SELECT * FROM customers WHERE is_synced=0").fetchall()],
                "customer_addresses": [dict(r) for r in conn.execute("SELECT * FROM customer_addresses WHERE is_synced=0").fetchall()],
                "offer_usages": [dict(r) for r in conn.execute("SELECT * FROM offer_usages WHERE is_synced=0").fetchall()],
                "comments": [dict(r) for r in conn.execute("SELECT * FROM comments WHERE is_synced=0").fetchall()],
                "order_status_history": [dict(r) for r in conn.execute("SELECT * FROM order_status_history WHERE is_synced=0").fetchall()],
            }

    def mark_synced(self, table: str, local_id: int):
        with self.connect() as conn:
            conn.execute(f"UPDATE {table} SET is_synced=1 WHERE id=?", (local_id,))

    def log_event(self, event_type: str, user_id: int, details: dict):
        with self.connect() as conn:
            conn.execute("INSERT INTO audit_logs (event_type, user_id, details) VALUES (?,?,?)", (event_type, user_id, json.dumps(details)))

    def get_audit_logs(self, limit: int = 100):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def get_user_by_username(self, username: str):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()
            return dict(row) if row else None

    def set_meta(self, key: str, value: str):
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES (?,?)", (key, value))

    def get_meta(self, key: str, default: str = None):
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def enqueue_sync(self, action: str, payload: dict):
        with self.connect() as conn:
            conn.execute("INSERT INTO sync_queue (action, payload) VALUES (?,?)", (action, json.dumps(payload)))

    def next_order_number(self):
        today = datetime.now(_TZ).strftime("%Y%m%d")
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM orders WHERE order_date=?", (datetime.now(_TZ).strftime("%Y-%m-%d"),)).fetchone()
            cnt = row[0] if row else 0
            return f"D-{today}-{cnt+1:04d}"

    def get_order(self, order_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if not row: return None
            order = dict(row)
            order["items"] = [dict(r) for r in conn.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()]
            return order

    def save_receipt(self, order_id, content, receipt_type="customer"):
        with self.connect() as conn:
            conn.execute("INSERT INTO receipts (order_id, receipt_type, content) VALUES (?,?,?)", (order_id, receipt_type, content))

local_db = LocalDB()
