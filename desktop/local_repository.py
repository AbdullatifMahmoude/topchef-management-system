import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.security import get_password_hash, verify_password
from desktop.config import DB_PATH
from desktop.logger import desktop_logger as log


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class LocalRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or DB_PATH)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def connect(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
            conn.execute("PRAGMA foreign_keys=ON;")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_db(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_id INTEGER UNIQUE,
            username TEXT NOT NULL UNIQUE,
            full_name TEXT,
            role TEXT NOT NULL,
            phone TEXT,
            hashed_password TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            last_sync_at TEXT
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY,
            name TEXT,
            image_url TEXT,
            display_order INTEGER DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            last_sync_at TEXT
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            cat_id INTEGER NOT NULL,
            name TEXT,
            type TEXT,
            description TEXT,
            image_url TEXT,
            is_available INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            last_sync_at TEXT
        );

        CREATE TABLE IF NOT EXISTS variants (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL,
            name TEXT,
            price REAL NOT NULL DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            last_sync_at TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id INTEGER UNIQUE,
            code TEXT NOT NULL UNIQUE,
            display_name TEXT,
            discount_type TEXT NOT NULL,
            discount_value REAL NOT NULL DEFAULT 0,
            min_order_amount REAL,
            min_quantity INTEGER,
            max_quantity INTEGER,
            max_discount_amount REAL,
            usage_limit INTEGER,
            usage_per_user INTEGER,
            current_usage INTEGER DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            valid_from TEXT,
            valid_to TEXT,
            created_at TEXT,
            updated_at TEXT,
            last_sync_at TEXT
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value_bool INTEGER,
            description TEXT,
            updated_at TEXT,
            last_sync_at TEXT
        );

        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_id INTEGER UNIQUE,
            name TEXT NOT NULL,
            phone_number TEXT NOT NULL UNIQUE,
            created_at TEXT,
            updated_at TEXT,
            pending_sync INTEGER NOT NULL DEFAULT 0,
            sync_status TEXT NOT NULL DEFAULT 'synced',
            last_sync_at TEXT
        );

        CREATE TABLE IF NOT EXISTS customer_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_id INTEGER UNIQUE,
            customer_id INTEGER NOT NULL,
            address TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT,
            pending_sync INTEGER NOT NULL DEFAULT 0,
            sync_status TEXT NOT NULL DEFAULT 'synced',
            last_sync_at TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_id INTEGER UNIQUE,
            order_number TEXT NOT NULL,
            order_date TEXT NOT NULL,
            customer_id INTEGER,
            customer_phone TEXT,
            customer_name TEXT,
            order_type TEXT NOT NULL,
            order_source TEXT NOT NULL DEFAULT 'cashier',
            order_status TEXT NOT NULL DEFAULT 'new',
            subtotal REAL NOT NULL DEFAULT 0,
            discount_amount REAL NOT NULL DEFAULT 0,
            delivery_fee REAL NOT NULL DEFAULT 0,
            total_amount REAL NOT NULL DEFAULT 0,
            customer_notes TEXT,
            internal_notes TEXT,
            idempotency_key TEXT,
            created_at TEXT,
            updated_at TEXT,
            pending_sync INTEGER NOT NULL DEFAULT 0,
            sync_status TEXT NOT NULL DEFAULT 'synced',
            last_sync_at TEXT
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS order_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_id INTEGER UNIQUE,
            order_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            changed_at TEXT,
            changed_by_user_id INTEGER,
            created_at TEXT,
            updated_at TEXT,
            pending_sync INTEGER NOT NULL DEFAULT 0,
            sync_status TEXT NOT NULL DEFAULT 'synced',
            last_sync_at TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_id INTEGER UNIQUE,
            full_name TEXT NOT NULL,
            stars INTEGER NOT NULL,
            comment_text TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT,
            pending_sync INTEGER NOT NULL DEFAULT 0,
            sync_status TEXT NOT NULL DEFAULT 'synced',
            last_sync_at TEXT
        );

        CREATE TABLE IF NOT EXISTS sync_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            action TEXT NOT NULL,
            record_id INTEGER,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TEXT NOT NULL,
            locked_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id INTEGER,
            details TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            receipt_type TEXT NOT NULL,
            content TEXT NOT NULL,
            printed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_sync_queue_status_available ON sync_queue(status, available_at);
        CREATE INDEX IF NOT EXISTS idx_orders_pending_sync ON orders(pending_sync, sync_status);
        CREATE INDEX IF NOT EXISTS idx_customers_pending_sync ON customers(pending_sync, sync_status);
        CREATE INDEX IF NOT EXISTS idx_comments_pending_sync ON comments(pending_sync, sync_status);
        """
        with self.connect() as conn:
            conn.executescript(schema)
            self._migrate_legacy_schema(conn)
        log.info("LocalRepository initialized at %s", self.db_path)

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        transactional_columns = {
            "customers": ["cloud_id", "pending_sync", "sync_status", "last_sync_at"],
            "customer_addresses": ["cloud_id", "pending_sync", "sync_status", "last_sync_at"],
            "orders": ["cloud_id", "pending_sync", "sync_status", "last_sync_at", "idempotency_key"],
            "order_status_history": ["cloud_id", "created_at", "updated_at", "pending_sync", "sync_status", "last_sync_at"],
            "comments": ["cloud_id", "updated_at", "pending_sync", "sync_status", "last_sync_at"],
        }
        for table, columns in transactional_columns.items():
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for column in columns:
                if column in existing:
                    continue
                column_sql = {
                    "cloud_id": "INTEGER",
                    "pending_sync": "INTEGER NOT NULL DEFAULT 0",
                    "sync_status": "TEXT NOT NULL DEFAULT 'synced'",
                    "last_sync_at": "TEXT",
                    "updated_at": "TEXT",
                    "created_at": "TEXT",
                    "idempotency_key": "TEXT",
                }[column]
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_sql}")

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def log_event(self, event_type: str, user_id: Optional[int], details: Dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO audit_logs(event_type, user_id, details, created_at) VALUES (?, ?, ?, ?)",
                (event_type, user_id, json.dumps(details, ensure_ascii=False), utc_now_iso()),
            )

    def get_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def cache_authenticated_user(self, user_data: Dict[str, Any], plain_password: str) -> None:
        username = user_data["username"]
        full_name = user_data.get("full_name") or username
        role = user_data.get("role") or "cashier"
        user_id = user_data.get("user_id")
        now = utc_now_iso()
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            hashed_password = get_password_hash(plain_password)
            if existing:
                conn.execute(
                    """
                    UPDATE users
                    SET cloud_id = ?, full_name = ?, role = ?, hashed_password = ?, is_active = 1,
                        updated_at = ?, last_sync_at = ?
                    WHERE username = ?
                    """,
                    (user_id, full_name, role, hashed_password, now, now, username),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO users(cloud_id, username, full_name, role, hashed_password, is_active, created_at, updated_at, last_sync_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (user_id, username, full_name, role, hashed_password, now, now, now),
                )
        self.set_meta("last_valid_username", username)

    def authenticate_offline(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        last_valid_username = self.get_meta("last_valid_username")
        if not last_valid_username or last_valid_username != username:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? AND is_active = 1",
                (username,),
            ).fetchone()
            if not row or not row["hashed_password"]:
                return None
            if not verify_password(password, row["hashed_password"]):
                return None
            return dict(row)

    def upsert_master_data(self, payload: Dict[str, Any]) -> None:
        with self.connect() as conn:
            self._upsert_categories(conn, payload.get("categories", []))
            self._upsert_products(conn, payload.get("products", []))
            self._upsert_offers(conn, payload.get("offers", []))
            self._upsert_settings(conn, payload.get("settings", {}))
            self._upsert_delivery_users(conn, payload.get("delivery_users", []))
            self._merge_customers_from_cloud(conn, payload.get("customers", []))
            self._merge_orders_from_cloud(conn, payload.get("orders", []))
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('last_pull_timestamp', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (utc_now_iso(),),
            )

    def _upsert_categories(self, conn: sqlite3.Connection, categories: List[Dict[str, Any]]) -> None:
        now = utc_now_iso()
        for item in categories:
            conn.execute(
                """
                INSERT INTO categories(id, name, image_url, display_order, is_active, created_at, updated_at, last_sync_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    image_url = excluded.image_url,
                    display_order = excluded.display_order,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at,
                    last_sync_at = excluded.last_sync_at
                """,
                (
                    item["id"],
                    item.get("cat_name") or item.get("name"),
                    item.get("image_url"),
                    item.get("display_order", 0),
                    1 if item.get("is_active", True) else 0,
                    item.get("created_at") or now,
                    item.get("updated_at") or now,
                    now,
                ),
            )

    def _upsert_products(self, conn: sqlite3.Connection, products: List[Dict[str, Any]]) -> None:
        now = utc_now_iso()
        for item in products:
            conn.execute(
                """
                INSERT INTO products(id, cat_id, name, type, description, image_url, is_available, created_at, updated_at, last_sync_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    cat_id = excluded.cat_id,
                    name = excluded.name,
                    type = excluded.type,
                    description = excluded.description,
                    image_url = excluded.image_url,
                    is_available = excluded.is_available,
                    updated_at = excluded.updated_at,
                    last_sync_at = excluded.last_sync_at
                """,
                (
                    item["id"],
                    item["cat_id"],
                    item.get("product_name") or item.get("name"),
                    item.get("product_type") or item.get("type"),
                    item.get("description"),
                    item.get("image_url"),
                    1 if item.get("is_available", True) else 0,
                    item.get("created_at") or now,
                    item.get("updated_at") or now,
                    now,
                ),
            )
            conn.execute("DELETE FROM variants WHERE product_id = ?", (item["id"],))
            for variant in item.get("variants", []):
                conn.execute(
                    """
                    INSERT INTO variants(id, product_id, name, price, created_at, updated_at, last_sync_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        product_id = excluded.product_id,
                        name = excluded.name,
                        price = excluded.price,
                        updated_at = excluded.updated_at,
                        last_sync_at = excluded.last_sync_at
                    """,
                    (
                        variant["id"],
                        item["id"],
                        variant["name"],
                        float(variant.get("price", 0)),
                        variant.get("created_at") or now,
                        variant.get("updated_at") or now,
                        now,
                    ),
                )

    def _upsert_offers(self, conn: sqlite3.Connection, offers: List[Dict[str, Any]]) -> None:
        now = utc_now_iso()
        for item in offers:
            conn.execute(
                """
                INSERT INTO offers(offer_id, code, display_name, discount_type, discount_value, min_order_amount,
                    min_quantity, max_quantity, max_discount_amount, usage_limit, usage_per_user, current_usage,
                    is_active, valid_from, valid_to, created_at, updated_at, last_sync_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(offer_id) DO UPDATE SET
                    code = excluded.code,
                    display_name = excluded.display_name,
                    discount_type = excluded.discount_type,
                    discount_value = excluded.discount_value,
                    min_order_amount = excluded.min_order_amount,
                    min_quantity = excluded.min_quantity,
                    max_quantity = excluded.max_quantity,
                    max_discount_amount = excluded.max_discount_amount,
                    usage_limit = excluded.usage_limit,
                    usage_per_user = excluded.usage_per_user,
                    current_usage = excluded.current_usage,
                    is_active = excluded.is_active,
                    valid_from = excluded.valid_from,
                    valid_to = excluded.valid_to,
                    updated_at = excluded.updated_at,
                    last_sync_at = excluded.last_sync_at
                """,
                (
                    item["offer_id"],
                    item["code"],
                    item.get("display_name"),
                    item["discount_type"],
                    float(item.get("discount_value", 0)),
                    self._to_float_or_none(item.get("min_order_amount")),
                    item.get("min_quantity"),
                    item.get("max_quantity"),
                    self._to_float_or_none(item.get("max_discount_amount")),
                    item.get("usage_limit"),
                    item.get("usage_per_user"),
                    item.get("current_usage", 0),
                    1 if item.get("is_active", True) else 0,
                    item.get("valid_from"),
                    item.get("valid_to"),
                    item.get("created_at") or now,
                    item.get("updated_at") or now,
                    now,
                ),
            )

    def _upsert_settings(self, conn: sqlite3.Connection, settings_payload: Dict[str, Any]) -> None:
        now = utc_now_iso()
        for key, value in settings_payload.items():
            conn.execute(
                """
                INSERT INTO app_settings(key, value_bool, description, updated_at, last_sync_at)
                VALUES (?, ?, 'Cloud synced setting', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_bool = excluded.value_bool,
                    updated_at = excluded.updated_at,
                    last_sync_at = excluded.last_sync_at
                """,
                (key, 1 if bool(value) else 0, now, now),
            )

    def _upsert_delivery_users(self, conn: sqlite3.Connection, users: List[Dict[str, Any]]) -> None:
        now = utc_now_iso()
        for item in users:
            conn.execute(
                """
                INSERT INTO users(cloud_id, username, full_name, role, phone, is_active, created_at, updated_at, last_sync_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    cloud_id = excluded.cloud_id,
                    full_name = excluded.full_name,
                    role = excluded.role,
                    phone = excluded.phone,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at,
                    last_sync_at = excluded.last_sync_at
                """,
                (
                    item["id"],
                    item["username"],
                    item.get("full_name"),
                    item.get("role", "delivery"),
                    item.get("phone"),
                    1 if item.get("is_active", True) else 0,
                    item.get("created_at") or now,
                    item.get("updated_at") or now,
                    now,
                ),
            )

    def upsert_users(self, users: List[Dict[str, Any]]) -> None:
        now = utc_now_iso()
        with self.connect() as conn:
            for item in users:
                conn.execute(
                    """
                    INSERT INTO users(cloud_id, username, full_name, role, phone, is_active, created_at, updated_at, last_sync_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET
                        cloud_id = excluded.cloud_id,
                        full_name = COALESCE(excluded.full_name, users.full_name),
                        role = excluded.role,
                        phone = COALESCE(excluded.phone, users.phone),
                        is_active = excluded.is_active,
                        updated_at = excluded.updated_at,
                        last_sync_at = excluded.last_sync_at
                    """,
                    (
                        item["id"],
                        item["username"],
                        item.get("full_name"),
                        item.get("role", "cashier"),
                        item.get("phone"),
                        1 if item.get("is_active", True) else 0,
                        item.get("created_at") or now,
                        item.get("updated_at") or now,
                        now,
                    ),
                )

    def _merge_customers_from_cloud(self, conn: sqlite3.Connection, customers: List[Dict[str, Any]]) -> None:
        now = utc_now_iso()
        for item in customers:
            existing = conn.execute(
                "SELECT * FROM customers WHERE cloud_id = ? OR phone_number = ?",
                (item["id"], item["phone_number"]),
            ).fetchone()
            remote_updated_at = item.get("updated_at") or item.get("created_at") or now
            if existing:
                if existing["pending_sync"] and self._is_local_newer(existing["updated_at"], remote_updated_at):
                    continue
                conn.execute(
                    """
                    UPDATE customers
                    SET cloud_id = ?, name = ?, phone_number = ?, updated_at = ?, pending_sync = 0,
                        sync_status = 'synced', last_sync_at = ?
                    WHERE id = ?
                    """,
                    (item["id"], item["name"], item["phone_number"], remote_updated_at, now, existing["id"]),
                )
                local_customer_id = existing["id"]
            else:
                cur = conn.execute(
                    """
                    INSERT INTO customers(cloud_id, name, phone_number, created_at, updated_at, pending_sync, sync_status, last_sync_at)
                    VALUES (?, ?, ?, ?, ?, 0, 'synced', ?)
                    """,
                    (item["id"], item["name"], item["phone_number"], item.get("created_at") or now, remote_updated_at, now),
                )
                local_customer_id = cur.lastrowid
            for address in item.get("addresses", []):
                self._upsert_customer_address_from_cloud(conn, local_customer_id, address)

    def _upsert_customer_address_from_cloud(self, conn: sqlite3.Connection, customer_id: int, address: Dict[str, Any]) -> None:
        now = utc_now_iso()
        existing = conn.execute("SELECT * FROM customer_addresses WHERE cloud_id = ?", (address["id"],)).fetchone()
        remote_updated_at = address.get("updated_at") or address.get("created_at") or now
        if existing:
            if existing["pending_sync"] and self._is_local_newer(existing["updated_at"], remote_updated_at):
                return
            conn.execute(
                """
                UPDATE customer_addresses
                SET customer_id = ?, address = ?, updated_at = ?, pending_sync = 0, sync_status = 'synced', last_sync_at = ?
                WHERE id = ?
                """,
                (customer_id, address["address"], remote_updated_at, now, existing["id"]),
            )
            return
        conn.execute(
            """
            INSERT INTO customer_addresses(cloud_id, customer_id, address, created_at, updated_at, pending_sync, sync_status, last_sync_at)
            VALUES (?, ?, ?, ?, ?, 0, 'synced', ?)
            """,
            (address["id"], customer_id, address["address"], address.get("created_at") or now, remote_updated_at, now),
        )

    def _merge_orders_from_cloud(self, conn: sqlite3.Connection, orders: List[Dict[str, Any]]) -> None:
        now = utc_now_iso()
        for item in orders:
            existing = conn.execute(
                "SELECT * FROM orders WHERE cloud_id = ? OR (order_number = ? AND order_date = ?)",
                (item["id"], item["order_number"], item["order_date"]),
            ).fetchone()
            remote_updated_at = item.get("updated_at") or item.get("created_at") or now
            if existing:
                if existing["pending_sync"] and self._is_local_newer(existing["updated_at"], remote_updated_at):
                    continue
                order_id = existing["id"]
                conn.execute(
                    """
                    UPDATE orders
                    SET cloud_id = ?, customer_phone = ?, customer_name = ?, order_type = ?, order_source = ?, order_status = ?,
                        subtotal = ?, discount_amount = ?, delivery_fee = ?, total_amount = ?, customer_notes = ?, internal_notes = ?,
                        updated_at = ?, pending_sync = 0, sync_status = 'synced', last_sync_at = ?
                    WHERE id = ?
                    """,
                    (
                        item["id"],
                        item.get("customer_phone"),
                        item.get("customer_name"),
                        item["order_type"],
                        item.get("source") or item.get("order_source", "cashier"),
                        item["order_status"],
                        float(item.get("subtotal", 0)),
                        float(item.get("discount_amount", 0)),
                        float(item.get("delivery_fee", 0)),
                        float(item.get("total_amount", 0)),
                        item.get("customer_notes"),
                        item.get("internal_notes"),
                        remote_updated_at,
                        now,
                        order_id,
                    ),
                )
                conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
            else:
                cur = conn.execute(
                    """
                    INSERT INTO orders(cloud_id, order_number, order_date, customer_phone, customer_name, order_type, order_source,
                        order_status, subtotal, discount_amount, delivery_fee, total_amount, customer_notes, internal_notes,
                        created_at, updated_at, pending_sync, sync_status, last_sync_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'synced', ?)
                    """,
                    (
                        item["id"],
                        item["order_number"],
                        item["order_date"],
                        item.get("customer_phone"),
                        item.get("customer_name"),
                        item["order_type"],
                        item.get("source") or item.get("order_source", "cashier"),
                        item["order_status"],
                        float(item.get("subtotal", 0)),
                        float(item.get("discount_amount", 0)),
                        float(item.get("delivery_fee", 0)),
                        float(item.get("total_amount", 0)),
                        item.get("customer_notes"),
                        item.get("internal_notes"),
                        item.get("created_at") or now,
                        remote_updated_at,
                        now,
                    ),
                )
                order_id = cur.lastrowid
            for order_item in item.get("items", []):
                conn.execute(
                    """
                    INSERT INTO order_items(order_id, product_id, quantity, unit_price, total_price)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (order_id, order_item["product_id"], order_item["quantity"], float(order_item["unit_price"]), float(order_item["total_price"])),
                )

    def get_categories(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(
                "SELECT * FROM categories WHERE is_active = 1 ORDER BY display_order, id"
            ).fetchall()]
            for row in rows:
                row["cat_name"] = row.get("name")
                row["is_active"] = bool(row.get("is_active"))
            return rows

    def get_products(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            products = [dict(row) for row in conn.execute(
                "SELECT * FROM products WHERE is_available = 1 ORDER BY id"
            ).fetchall()]
            variants = [dict(row) for row in conn.execute("SELECT * FROM variants ORDER BY id").fetchall()]
            variant_map: Dict[int, List[Dict[str, Any]]] = {}
            for variant in variants:
                variant["price"] = float(variant.get("price", 0) or 0)
                variant_map.setdefault(variant["product_id"], []).append(variant)
            for product in products:
                product["product_name"] = product["name"]
                product["product_type"] = product["type"]
                product["is_available"] = bool(product.get("is_available"))
                product["variants"] = variant_map.get(product["id"], [])
            return products

    def get_offers(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM offers WHERE is_active = 1 ORDER BY offer_id"
            ).fetchall()]

    def get_delivery_users(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT cloud_id as id, username, full_name, role, phone, is_active FROM users WHERE role = 'delivery' AND is_active = 1 ORDER BY username"
            ).fetchall()]

    def get_users(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(
                "SELECT cloud_id as id, username, full_name, role, phone, is_active, created_at, updated_at FROM users WHERE is_active = 1 ORDER BY username"
            ).fetchall()]
            for row in rows:
                row["is_active"] = bool(row.get("is_active"))
                if row.get("phone") is None:
                    row["phone"] = ""
            return rows

    def list_customers(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            customer_rows = conn.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()
            address_rows = conn.execute("SELECT * FROM customer_addresses ORDER BY id DESC").fetchall()
            addresses_by_customer: Dict[int, List[Dict[str, Any]]] = {}
            for row in address_rows:
                addresses_by_customer.setdefault(row["customer_id"], []).append(dict(row))
            customers = []
            for row in customer_rows:
                customer = dict(row)
                customer["addresses"] = addresses_by_customer.get(customer["id"], [])
                customers.append(customer)
            return customers

    def get_customer_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM customers WHERE phone_number = ?", (phone,)).fetchone()
            if not row:
                return None
            customer = dict(row)
            customer["addresses"] = [dict(address) for address in conn.execute(
                "SELECT * FROM customer_addresses WHERE customer_id = ? ORDER BY id DESC",
                (customer["id"],),
            ).fetchall()]
            return customer

    def next_order_number(self) -> str:
        today = datetime.now().strftime("%Y%m%d")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM orders WHERE substr(order_date, 1, 10) = ?",
                (datetime.now().strftime("%Y-%m-%d"),),
            ).fetchone()
            total = row["total"] if row else 0
            return f"D-{today}-{total + 1:04d}"

    def create_customer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM customers WHERE phone_number = ?",
                (payload["phone_number"],),
            ).fetchone()
            if existing:
                return dict(existing)
            now = utc_now_iso()
            cur = conn.execute(
                """
                INSERT INTO customers(name, phone_number, created_at, updated_at, pending_sync, sync_status)
                VALUES (?, ?, ?, ?, 1, 'pending')
                """,
                (payload["name"], payload["phone_number"], now, now),
            )
            local_id = cur.lastrowid
            self._enqueue_sync(conn, "customer", "create_customer", local_id, {
                "local_id": local_id,
                "name": payload["name"],
                "phone_number": payload["phone_number"],
            })
            return dict(conn.execute("SELECT * FROM customers WHERE id = ?", (local_id,)).fetchone())

    def add_customer_address(self, customer_id: int, address: str) -> Dict[str, Any]:
        with self.connect() as conn:
            now = utc_now_iso()
            cur = conn.execute(
                """
                INSERT INTO customer_addresses(customer_id, address, created_at, updated_at, pending_sync, sync_status)
                VALUES (?, ?, ?, ?, 1, 'pending')
                """,
                (customer_id, address, now, now),
            )
            local_id = cur.lastrowid
            self._enqueue_sync(conn, "customer_address", "create_customer_address", local_id, {
                "local_id": local_id,
                "customer_id": customer_id,
                "address": address,
            })
            return dict(conn.execute("SELECT * FROM customer_addresses WHERE id = ?", (local_id,)).fetchone())

    def create_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self.connect() as conn:
            now = utc_now_iso()
            order_number = payload.get("order_number") or self.next_order_number()
            items = payload.get("items", [])
            subtotal = sum(float(item["unit_price"]) * int(item["quantity"]) for item in items)
            cur = conn.execute(
                """
                INSERT INTO orders(order_number, order_date, customer_id, customer_phone, customer_name, order_type,
                    order_source, order_status, subtotal, discount_amount, delivery_fee, total_amount,
                    customer_notes, internal_notes, idempotency_key, created_at, updated_at, pending_sync, sync_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'pending')
                """,
                (
                    order_number,
                    payload.get("order_date") or datetime.now().strftime("%Y-%m-%d"),
                    payload.get("customer_id"),
                    payload.get("customer_phone"),
                    payload.get("customer_name"),
                    payload.get("order_type", "hall"),
                    payload.get("source") or payload.get("order_source", "cashier"),
                    payload.get("order_status", "new"),
                    subtotal,
                    float(payload.get("discount_amount", 0) or 0),
                    float(payload.get("delivery_fee", 0) or 0),
                    float(payload.get("total_amount", subtotal)),
                    payload.get("customer_notes"),
                    payload.get("internal_notes"),
                    payload.get("idempotency_key"),
                    now,
                    now,
                ),
            )
            local_id = cur.lastrowid
            for item in items:
                conn.execute(
                    """
                    INSERT INTO order_items(order_id, product_id, quantity, unit_price, total_price)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        local_id,
                        item["product_id"],
                        item["quantity"],
                        float(item["unit_price"]),
                        float(item["unit_price"]) * int(item["quantity"]),
                    ),
                )
            self._enqueue_sync(conn, "order", "create_order", local_id, {
                "local_id": local_id,
                "customer_id": payload.get("customer_id"),
                "customer_phone": payload.get("customer_phone"),
                "customer_name": payload.get("customer_name"),
                "order_type": payload.get("order_type", "hall"),
                "source": payload.get("source") or payload.get("order_source", "cashier"),
                "customer_notes": payload.get("customer_notes"),
                "internal_notes": payload.get("internal_notes"),
                "items": items,
                "idempotency_key": payload.get("idempotency_key"),
                "delivery_fee": float(payload.get("delivery_fee", 0) or 0),
                "offer_code": payload.get("offer_code"),
            })
            return self.get_order(local_id)

    def update_order_status(self, order_id: int, status: str) -> Dict[str, Any]:
        with self.connect() as conn:
            now = utc_now_iso()
            conn.execute(
                "UPDATE orders SET order_status = ?, updated_at = ?, pending_sync = 1, sync_status = 'pending' WHERE id = ?",
                (status, now, order_id),
            )
            cur = conn.execute(
                """
                INSERT INTO order_status_history(order_id, status, changed_at, created_at, updated_at, pending_sync, sync_status)
                VALUES (?, ?, ?, ?, ?, 1, 'pending')
                """,
                (order_id, status, now, now, now),
            )
            history_id = cur.lastrowid
            self._enqueue_sync(conn, "order_status", "update_order_status", history_id, {
                "local_id": history_id,
                "order_id": order_id,
                "order_status": status,
            })
            return self.get_order(order_id)

    def add_comment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self.connect() as conn:
            now = utc_now_iso()
            cur = conn.execute(
                """
                INSERT INTO comments(full_name, stars, comment_text, created_at, updated_at, pending_sync, sync_status)
                VALUES (?, ?, ?, ?, ?, 1, 'pending')
                """,
                (payload["full_name"], int(payload["stars"]), payload["comment_text"], now, now),
            )
            local_id = cur.lastrowid
            self._enqueue_sync(conn, "comment", "create_comment", local_id, {"local_id": local_id, **payload})
            return dict(conn.execute("SELECT * FROM comments WHERE id = ?", (local_id,)).fetchone())

    def get_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not row:
                return None
            order = dict(row)
            order["items"] = self._load_order_items(conn, order_id)
            order["source"] = order["order_source"]
            self._decorate_order(conn, order)
            return order

    def list_orders(self, source: Optional[str] = None, status: Optional[str] = None, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        clauses = []
        params: List[Any] = []
        if source:
            clauses.append("order_source = ?")
            params.append(source)
        if status:
            clauses.append("order_status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        offset = (page - 1) * page_size
        with self.connect() as conn:
            total_row = conn.execute(f"SELECT COUNT(*) AS total FROM orders {where_sql}", tuple(params)).fetchone()
            rows = conn.execute(
                f"SELECT * FROM orders {where_sql} ORDER BY datetime(created_at) DESC, id DESC LIMIT ? OFFSET ?",
                tuple(params + [page_size, offset]),
            ).fetchall()
            orders = []
            for row in rows:
                order = dict(row)
                order["items"] = self._load_order_items(conn, order["id"])
                order["source"] = order["order_source"]
                self._decorate_order(conn, order)
                orders.append(order)
            return {
                "total": total_row["total"] if total_row else 0,
                "page": page,
                "page_size": page_size,
                "orders": orders,
            }

    def _load_order_items(self, conn: sqlite3.Connection, order_id: int) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT oi.*, p.name AS product_name
            FROM order_items oi
            LEFT JOIN products p ON p.id = oi.product_id
            WHERE oi.order_id = ?
            ORDER BY oi.id
            """,
            (order_id,),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["product_name"] = item.get("product_name") or f"Product {item['product_id']}"
            items.append(item)
        return items

    def _decorate_order(self, conn: sqlite3.Connection, order: Dict[str, Any]) -> None:
        order["total_amount"] = float(order.get("total_amount", 0) or 0)
        order["subtotal"] = float(order.get("subtotal", 0) or 0)
        order["discount_amount"] = float(order.get("discount_amount", 0) or 0)
        order["delivery_fee"] = float(order.get("delivery_fee", 0) or 0)
        if order.get("customer_id"):
            address_row = conn.execute(
                "SELECT id, address FROM customer_addresses WHERE customer_id = ? ORDER BY id DESC LIMIT 1",
                (order["customer_id"],),
            ).fetchone()
            if address_row:
                order["address"] = dict(address_row)
                order["customer_address"] = address_row["address"]
        if not order.get("customer_name"):
            order["customer_name"] = "عميل"

    def get_web_orders_setting(self) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT value_bool FROM app_settings WHERE key = 'web_orders'").fetchone()
            return bool(row["value_bool"]) if row else True

    def set_web_orders_setting(self, enabled: bool) -> Dict[str, Any]:
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_settings(key, value_bool, description, updated_at, last_sync_at)
                VALUES ('web_orders', ?, 'Cloud synced setting', ?, last_sync_at)
                ON CONFLICT(key) DO UPDATE SET value_bool = excluded.value_bool, updated_at = excluded.updated_at
                """,
                (1 if enabled else 0, now),
            )
            return {"key": "web_orders", "value_bool": bool(enabled), "updated_at": now}

    def list_ready_queue_items(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                """
                SELECT * FROM sync_queue
                WHERE status IN ('pending', 'failed') AND available_at <= ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (utc_now_iso(), limit),
            ).fetchall()]

    def mark_queue_processing(self, queue_id: int) -> None:
        with self.connect() as conn:
            now = utc_now_iso()
            conn.execute(
                "UPDATE sync_queue SET status = 'processing', locked_at = ?, updated_at = ? WHERE id = ?",
                (now, now, queue_id),
            )

    def mark_queue_done(self, queue_id: int) -> None:
        with self.connect() as conn:
            now = utc_now_iso()
            conn.execute(
                "UPDATE sync_queue SET status = 'done', locked_at = NULL, updated_at = ? WHERE id = ?",
                (now, queue_id),
            )

    def mark_queue_failed(self, queue_id: int, error: str, backoff_seconds: int) -> None:
        with self.connect() as conn:
            now = utc_now_iso()
            available_at = (datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)).replace(microsecond=0).isoformat()
            conn.execute(
                """
                UPDATE sync_queue
                SET status = 'failed',
                    attempts = attempts + 1,
                    last_error = ?,
                    available_at = ?,
                    updated_at = ?,
                    locked_at = NULL
                WHERE id = ?
                """,
                (error[:1000], available_at, now, queue_id),
            )

    def get_pending_sync_count(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM sync_queue WHERE status IN ('pending', 'failed', 'processing')"
            ).fetchone()
            return row["total"] if row else 0

    def mark_customer_synced(self, local_id: int, cloud_record: Dict[str, Any]) -> None:
        with self.connect() as conn:
            now = utc_now_iso()
            conn.execute(
                """
                UPDATE customers
                SET cloud_id = ?, name = ?, phone_number = ?, pending_sync = 0, sync_status = 'synced',
                    last_sync_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (cloud_record["id"], cloud_record["name"], cloud_record["phone_number"], now, cloud_record.get("created_at") or now, local_id),
            )

    def mark_customer_address_synced(self, local_id: int, cloud_record: Dict[str, Any]) -> None:
        with self.connect() as conn:
            now = utc_now_iso()
            conn.execute(
                """
                UPDATE customer_addresses
                SET cloud_id = ?, pending_sync = 0, sync_status = 'synced',
                    last_sync_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (cloud_record["id"], now, cloud_record.get("created_at") or now, local_id),
            )

    def mark_order_synced(self, local_id: int, cloud_record: Dict[str, Any]) -> None:
        with self.connect() as conn:
            now = utc_now_iso()
            conn.execute(
                """
                UPDATE orders
                SET cloud_id = ?, order_status = ?, pending_sync = 0, sync_status = 'synced',
                    last_sync_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (cloud_record["id"], cloud_record.get("order_status", "new"), now, cloud_record.get("updated_at") or now, local_id),
            )

    def mark_order_status_synced(self, history_id: int, order_cloud_id: Optional[int] = None) -> None:
        with self.connect() as conn:
            now = utc_now_iso()
            conn.execute(
                "UPDATE order_status_history SET pending_sync = 0, sync_status = 'synced', last_sync_at = ?, updated_at = ? WHERE id = ?",
                (now, now, history_id),
            )
            if order_cloud_id is not None:
                conn.execute(
                    "UPDATE orders SET pending_sync = 0, sync_status = 'synced', last_sync_at = ? WHERE cloud_id = ?",
                    (now, order_cloud_id),
                )

    def mark_comment_synced(self, local_id: int, cloud_record: Dict[str, Any]) -> None:
        with self.connect() as conn:
            now = utc_now_iso()
            conn.execute(
                """
                UPDATE comments
                SET cloud_id = ?, pending_sync = 0, sync_status = 'synced', last_sync_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (cloud_record["id"], now, cloud_record.get("created_at") or now, local_id),
            )

    def get_customer_cloud_id(self, local_id: int) -> Optional[int]:
        with self.connect() as conn:
            row = conn.execute("SELECT cloud_id FROM customers WHERE id = ?", (local_id,)).fetchone()
            return row["cloud_id"] if row and row["cloud_id"] else None

    def get_order_cloud_id(self, local_id: int) -> Optional[int]:
        with self.connect() as conn:
            row = conn.execute("SELECT cloud_id FROM orders WHERE id = ?", (local_id,)).fetchone()
            return row["cloud_id"] if row and row["cloud_id"] else None

    def save_receipt(self, order_id: int, content: str, receipt_type: str = "customer") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO receipts(order_id, receipt_type, content, printed_at) VALUES (?, ?, ?, ?)",
                (order_id, receipt_type, content, utc_now_iso()),
            )

    def _enqueue_sync(self, conn: sqlite3.Connection, entity_type: str, action: str, record_id: int, payload: Dict[str, Any]) -> None:
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO sync_queue(entity_type, action, record_id, payload, status, attempts, available_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (entity_type, action, record_id, json.dumps(payload, ensure_ascii=False), now, now, now),
        )

    @staticmethod
    def _to_float_or_none(value: Any) -> Optional[float]:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _is_local_newer(local_updated_at: Optional[str], remote_updated_at: Optional[str]) -> bool:
        if not local_updated_at or not remote_updated_at:
            return False
        try:
            local_dt = datetime.fromisoformat(local_updated_at.replace("Z", "+00:00"))
            remote_dt = datetime.fromisoformat(remote_updated_at.replace("Z", "+00:00"))
            return local_dt > remote_dt
        except Exception:
            return False


local_repository = LocalRepository()
