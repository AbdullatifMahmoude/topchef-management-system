import asyncio
import json
from typing import Any, Dict, List, Optional

import httpx

from desktop.auth_service import auth_service
from desktop.config import config
from desktop.local_repository import local_repository
from desktop.logger import desktop_logger as log


class CloudAPIClient:
    def __init__(self) -> None:
        self.base_url = config.server_url.rstrip("/")

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        authenticated: bool = True,
        timeout_seconds: float = 20.0,
        allow_refresh: bool = True,
    ) -> Any:
        headers = {"Content-Type": "application/json", "User-Agent": "TopChefDesktopPOS/2.0"}
        token = auth_service.get_access_token()
        if authenticated and token and token != "offline-session":
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.request(
                method=method,
                url=f"{self.base_url}{path}",
                json=json_body,
                params=params,
                headers=headers,
            )
        if response.status_code == 401 and authenticated and allow_refresh:
            refreshed_token = await auth_service.refresh_access_token()
            if refreshed_token:
                return await self.request(
                    method,
                    path,
                    json_body=json_body,
                    params=params,
                    authenticated=authenticated,
                    timeout_seconds=timeout_seconds,
                    allow_refresh=False,
                )
        response.raise_for_status()
        if not response.content:
            return None
        if "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text

    async def fetch_master_data(self) -> Dict[str, Any]:
        log.info("Fetching cloud master data bundle.")
        has_online_session = auth_service.has_online_session()
        jobs = [
            self.request("GET", "/menu/categories", authenticated=False),
            self.request("GET", "/menu/products", authenticated=False),
            self.request("GET", "/offers/", authenticated=False),
        ]
        if has_online_session:
            role = auth_service.get_current_role()
            jobs.extend([
                self.request("GET", "/settings/web-orders"),
                self.request("GET", "/customers/"),
                self.request("GET", "/orders/", params={"source": "online", "page_size": 200}),
                self.request("GET", "/orders/", params={"source": "cashier", "page_size": 200}),
                self.request("GET", "/user/users/delivery"),
            ])
            # Only admins can list all users
            if role in ("admin", "owner", "manager"):
                jobs.append(self.request("GET", "/user/users"))
            else:
                jobs.append(asyncio.sleep(0, result=[]))
        else:
            jobs.extend([
                asyncio.sleep(0, result=True),
                asyncio.sleep(0, result=[]),
                asyncio.sleep(0, result={}),
                asyncio.sleep(0, result={}),
                asyncio.sleep(0, result=[]),
                asyncio.sleep(0, result=[]),
            ])
        results = await asyncio.gather(*jobs, return_exceptions=True)
        return {
            "categories": self._normalize_result(results[0], []),
            "products": self._normalize_result(results[1], []),
            "offers": self._normalize_result(results[2], []),
            "settings": {"web_orders": bool(self._normalize_result(results[3], True))},
            "customers": self._normalize_result(results[4], []),
            "orders": self._extract_orders(self._normalize_result(results[5], {})) + self._extract_orders(self._normalize_result(results[6], {})),
            "delivery_users": self._normalize_result(results[7], []),
            "users": self._normalize_result(results[8], []),
        }

    async def upload_pending_queue(self, queue_rows: List[Dict[str, Any]]) -> int:
        uploaded = 0
        for row in queue_rows:
            local_repository.mark_queue_processing(row["id"])
            payload = json.loads(row["payload"])
            try:
                await self._upload_queue_row(row["action"], payload)
                local_repository.mark_queue_done(row["id"])
                uploaded += 1
            except Exception as exc:
                backoff_seconds = min(300, 2 ** max(1, row.get("attempts", 0) + 1))
                local_repository.mark_queue_failed(row["id"], str(exc), backoff_seconds)
                log.error("Queue upload failed for action=%s id=%s: %s", row["action"], row["id"], exc)
                raise
        return uploaded

    async def _upload_queue_row(self, action: str, payload: Dict[str, Any]) -> None:
        if action == "create_customer":
            response = await self.request("POST", "/customers/", json_body={
                "name": payload["name"],
                "phone_number": payload["phone_number"],
            })
            local_repository.mark_customer_synced(payload["local_id"], response)
            return
        if action == "create_customer_address":
            cloud_customer_id = local_repository.get_customer_cloud_id(payload["customer_id"])
            if not cloud_customer_id:
                raise RuntimeError("Customer must sync before address upload")
            response = await self.request(
                "POST",
                f"/customers/{cloud_customer_id}/addresses",
                json_body={"address": payload["address"]},
            )
            local_repository.mark_customer_address_synced(payload["local_id"], response)
            return
        if action == "create_order":
            cloud_customer_id = None
            if payload.get("customer_id"):
                cloud_customer_id = local_repository.get_customer_cloud_id(payload["customer_id"])
            response = await self.request(
                "POST",
                "/orders/",
                json_body={
                    "customer_id": cloud_customer_id,
                    "customer_phone": payload.get("customer_phone"),
                    "customer_name": payload.get("customer_name"),
                    "order_type": payload.get("order_type", "hall"),
                    "source": payload.get("source", "cashier"),
                    "customer_notes": payload.get("customer_notes"),
                    "internal_notes": payload.get("internal_notes"),
                    "items": payload.get("items", []),
                    "idempotency_key": payload.get("idempotency_key"),
                    "delivery_fee": payload.get("delivery_fee", 0),
                    "offer_code": payload.get("offer_code"),
                },
                timeout_seconds=30.0,
            )
            local_repository.mark_order_synced(payload["local_id"], response)
            return
        if action == "update_order_status":
            cloud_order_id = local_repository.get_order_cloud_id(payload["order_id"])
            if not cloud_order_id:
                raise RuntimeError("Order must sync before status upload")
            response = await self.request(
                "PATCH",
                f"/orders/{cloud_order_id}/status",
                json_body={"order_status": payload["order_status"]},
            )
            local_repository.mark_order_status_synced(payload["local_id"], response.get("id"))
            return
        if action == "create_comment":
            response = await self.request("POST", "/comments/", json_body={
                "full_name": payload["full_name"],
                "stars": payload["stars"],
                "comment_text": payload["comment_text"],
            }, authenticated=False)
            local_repository.mark_comment_synced(payload["local_id"], response)
            return
        if action == "update_order_full":
            cloud_order_id = local_repository.get_order_cloud_id(payload["order_id"])
            if not cloud_order_id:
                raise RuntimeError("Order must sync before full update upload")
            response = await self.request(
                "PATCH",
                f"/orders/{cloud_order_id}",
                json_body=payload["update_data"],
            )
            local_repository.mark_order_synced(payload["order_id"], response)
            return
        raise ValueError(f"Unsupported queue action: {action}")

    @staticmethod
    def _extract_orders(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        return payload.get("orders", []) if isinstance(payload, dict) else []

    @staticmethod
    def _normalize_result(result: Any, fallback: Any) -> Any:
        if isinstance(result, Exception):
            log.warning("Cloud fetch segment failed: %s", result)
            return fallback
        return result


cloud_api = CloudAPIClient()
