"""
Enterprise Printing Facade
--------------------------
Uses a single HTML receipt renderer so desktop silent print, backend print,
and reprint all share the same receipt shape as the cashier frontend.
"""

import html
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from desktop.logger import desktop_logger as log


class PrinterManager:
    def __init__(self):
        self._job_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._worker_thread = threading.Thread(target=self._printer_worker, daemon=True)
        self._worker_thread.start()
        self._last_order_id: Optional[int] = None
        self._last_receipt_html: Optional[str] = None
        self._last_receipt_name: Optional[str] = None

    def _printer_worker(self) -> None:
        while True:
            try:
                job = self._job_queue.get()
                success = False
                attempts = 0

                while not success and attempts < 3:
                    try:
                        success = self._execute_html_print(job["html"], job.get("document_name", "Top Chef Receipt"))
                        if success:
                            log.info("Print successful for %s", job.get("document_name", "receipt"))
                        else:
                            attempts += 1
                            time.sleep(2)
                    except Exception as exc:
                        attempts += 1
                        log.error("Print error (attempt %s): %s", attempts, exc)
                        time.sleep(2)

                self._job_queue.task_done()
            except Exception as exc:
                log.error("Printer worker encountered error: %s", exc)

    def print_receipt(self, order: Dict[str, Any], receipt_type: str = "customer") -> bool:
        self._last_order_id = order.get("id")
        html_content = self.build_receipt_html(order, receipt_type)
        document_name = f"order-{order.get('order_number') or order.get('id')}"
        self._last_receipt_html = html_content
        self._last_receipt_name = document_name
        self._job_queue.put({"html": html_content, "document_name": document_name})
        return True

    def print_html(self, html_content: str, document_name: str = "Top Chef Receipt") -> bool:
        self._last_receipt_html = html_content
        self._last_receipt_name = document_name
        self._job_queue.put({"html": html_content, "document_name": document_name})
        return True

    def reprint_last(self, receipt_type: str = "customer") -> bool:
        if not self._last_receipt_html:
            log.warning("No last order to reprint")
            return False
        self._job_queue.put(
            {
                "html": self._last_receipt_html,
                "document_name": self._last_receipt_name or f"reprint-{self._last_order_id or 'receipt'}",
            }
        )
        return True

    def build_receipt_html(self, order: Dict[str, Any], receipt_type: str = "customer") -> str:
        order_number = self._value(order, "orderNumber", "order_number", "id", default="---")
        cashier_name = self._value(order, "creator_name", "cashierName", "cashier_name", default="---")
        order_date = self._value(order, "created_at", "order_date")

        formatted_date, formatted_time = self._format_date_parts(order_date)
        raw_address = self._value(order, "customerAddress", "customer_address", "address", default="")
        print_addr_text = self._address_to_text(raw_address)
        order_type = self._value(order, "orderType", "order_type", default="hall")
        is_double_print = order_type in {"delivery", "takeaway"}

        items = order.get("cart") or self._order_items_to_cart(order)
        item_rows = "".join(self._render_item_row(item) for item in items)

        customer_name = self._value(order, "customerName", "customer_name", default="")
        customer_phone = self._value(order, "customerPhone", "customer_phone", default="")
        delivery_person = self._value(order, "delivery_person_name", default="")
        selected_delivery = order.get("selectedDelivery") or {}
        if not delivery_person and isinstance(selected_delivery, dict):
            delivery_person = selected_delivery.get("name", "")

        delivery_fee = self._number(self._value(order, "delivery_fee", "selectedDeliveryFee", default=0))
        dine_in_fee = self._number(self._value(order, "selectedDineInFee", default=0))
        subtotal = self._number(self._value(order, "itemsTotal", "subtotal", default=0))
        grand_total = self._number(self._value(order, "total_amount", "grandTotal", default=0))

        receipt_content = f"""
      <div class="receipt-header">
        <div class="header-row" style="position:relative; justify-content:center; min-height:50px; align-items:center;">
          <div style="position:absolute; right:0; top:50%; transform:translateY(-50%);">
            <img src="https://api.qrserver.com/v1/create-qr-code/?size=100x100&amp;data=https://topcheifmenu.vercel.app/" alt="QR" style="width:45px; height:45px;" />
          </div>
          <h1 class="order-number" style="font-size:26px; font-weight:900; border:1px solid #000; padding:2px 8px; border-radius:4px;">#{html.escape(str(order_number))}</h1>
          <div style="position:absolute; left:0; top:50%; transform:translateY(-50%); text-align:left; font-size:10px; font-weight:bold; line-height:1.2;">
            <div>{html.escape(formatted_date)}</div>
            <div>{html.escape(formatted_time)}</div>
          </div>
        </div>

        <div class="info-line" style="display:flex; justify-content:space-between; margin-top:8px; border-top:1px dashed #000; padding-top:4px; font-size:12px; font-weight:bold;">
          <span>كاشير: {html.escape(cashier_name)}</span>
          <span>{html.escape(self._order_type_label(order_type))}</span>
        </div>

        {f'<div class="info-line" style="border:none; margin-top:2px;"><span style="width:100%">مندوب: {html.escape(delivery_person)}</span></div>' if order_type == "delivery" and delivery_person else ""}
      </div>

      <table class="items">
        <thead>
          <tr>
            <th class="item-name">الصنف</th>
            <th class="qty">ك</th>
            <th class="price">سعر</th>
            <th class="total">إجمالي</th>
          </tr>
        </thead>
        <tbody>
          {item_rows}
        </tbody>
      </table>

      <div class="totals">
        <div class="totals-row">
          <span>المجموع:</span>
          <span>{subtotal:.2f}</span>
        </div>
        {f'<div class="totals-row"><span>التوصيل:</span><span>{delivery_fee:.2f}</span></div>' if order_type == "delivery" and delivery_fee else ""}
        {f'<div class="totals-row"><span>الصالة:</span><span>{(self._number(self._value(order, "delivery_fee", default=0)) or dine_in_fee):.2f}</span></div>' if order_type in {"hall", "dine_in"} and (self._number(self._value(order, "delivery_fee", default=0)) or dine_in_fee) else ""}
        <div class="totals-row grand">
          <span>الإجمالي النهائي:</span>
          <span>{grand_total:.2f} ج.م</span>
        </div>
      </div>

      {self._render_customer_info(customer_name, customer_phone, print_addr_text)}

      <div class="footer">
        <p>مزلقان هرية رزنة - الزقازيق - الشرقية</p>
        <p>01212758001 - 01129820007</p>
        <p style="margin-top: 5px;">شكراً لزيارتكم - Top Chef</p>
      </div>
        """

        return f"""
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
  <meta charset="utf-8">
  <title>{html.escape(str(receipt_type).title())} Receipt</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    @page {{ margin: 0; size: 80mm auto; }}
    html, body {{ background: #fff; }}
    body {{
      font-family: 'Cairo', Arial, sans-serif;
      width: 72mm;
      margin: 0 auto;
      padding: 2mm;
      font-size: 11px;
      color: #000;
      background: #fff;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .receipt-header {{
      border-bottom: 1px dashed #000;
      padding-bottom: 4px;
      margin-bottom: 6px;
    }}
    .header-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .order-number {{ font-size: 22px; font-weight: 900; }}
    .info-line {{
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      font-weight: bold;
      margin-top: 3px;
      border-top: 1px solid #eee;
      padding-top: 2px;
    }}
    .items {{ width: 100%; border-collapse: collapse; margin-top: 5px; }}
    .items th {{ border-bottom: 1px solid #000; font-size: 10px; padding: 2px; }}
    .items td {{ border-bottom: 1px solid #eee; padding: 4px 2px; font-size: 11px; font-weight: bold; }}
    .items .item-name {{ text-align: right; width: 50%; }}
    .items .qty {{ text-align: center; width: 10%; }}
    .items .price {{ text-align: center; width: 20%; }}
    .items .total {{ text-align: left; width: 20%; }}
    .totals {{ margin-top: 6px; border-top: 1px solid #000; padding-top: 4px; }}
    .totals-row {{ display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 2px; font-weight: bold; }}
    .totals-row.grand {{ font-size: 15px; font-weight: 900; margin-top: 4px; border-top: 1px dashed #000; padding-top: 4px; }}
    .customer-info {{ margin-top: 8px; border: 1px dashed; padding: 4px 6px; border-radius: 4px; }}
    .customer-info-title {{ font-size: 11px; font-weight: 900; text-align: center; margin-bottom: 3px; }}
    .customer-info-row {{ font-size: 11px; font-weight: bold; margin-bottom: 2px; }}
    .footer {{ text-align: center; margin-top: 10px; font-size: 10px; border-top: 1px dashed #777; padding-top: 6px; }}
    .footer p {{ margin-bottom: 2px; }}
    .receipt-wrapper {{
      page-break-after: always;
      width: 100%;
      display: block;
    }}
    .receipt-wrapper:last-child {{ page-break-after: auto; }}
  </style>
</head>
<body>
  <div class="receipt-wrapper">{receipt_content}</div>
  {"<div class=\"receipt-wrapper\" style=\"margin-top:10mm; border-top:1px dashed #ccc; padding-top:5mm;\">" + receipt_content + "</div>" if is_double_print else ""}
</body>
</html>
        """.strip()

    def _execute_html_print(self, html_content: str, document_name: str) -> bool:
        try:
            import win32api

            temp_dir = Path(os.environ.get("TEMP", "."))
            timestamp = int(time.time() * 1000)
            temp_file = temp_dir / f"{document_name}_{timestamp}.html"
            temp_file.write_text(html_content, encoding="utf-8")
            win32api.ShellExecute(0, "print", str(temp_file), None, str(temp_dir), 0)

            cleanup = threading.Thread(target=self._cleanup_temp_file, args=(temp_file,), daemon=True)
            cleanup.start()
            return True
        except Exception as exc:
            log.error("Native HTML print failed: %s", exc)
            return False

    def _cleanup_temp_file(self, file_path: Path) -> None:
        time.sleep(60)
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            log.debug("Could not clean up temp print file: %s", file_path)

    def _order_items_to_cart(self, order: Dict[str, Any]) -> list[Dict[str, Any]]:
        cart = []
        for item in order.get("items", []):
            price = self._number(item.get("unit_price"))
            name = item.get("product_name") or item.get("name") or f"Product {item.get('product_id', '')}".strip()
            cart.append(
                {
                    "qty": int(item.get("quantity", 0) or 0),
                    "item": {
                        "name": name,
                        "price": price,
                    },
                }
            )
        return cart

    def _render_item_row(self, cart_item: Dict[str, Any]) -> str:
        item_data = cart_item.get("item") or {}
        name = item_data.get("name") or "---"
        qty = int(cart_item.get("qty", 0) or 0)
        price = self._number(item_data.get("price"))
        total = qty * price
        return f"""
            <tr>
              <td class="item-name">{html.escape(str(name))}</td>
              <td class="qty">{qty} x</td>
              <td class="price">{price:.0f}</td>
              <td class="total">{total:.0f}</td>
            </tr>
        """

    def _render_customer_info(self, customer_name: str, customer_phone: str, address_text: str) -> str:
        if not any([customer_name, customer_phone, address_text]):
            return ""
        return f"""
      <div class="customer-info">
        <div class="customer-info-title">بيانات العميل</div>
        {f'<div class="customer-info-row"><span> اسم العميل :{html.escape(customer_name)}</span></div>' if customer_name else ""}
        {f'<div class="customer-info-row"><span style="direction:ltr"> رقم التليفون :{html.escape(customer_phone)}</span></div>' if customer_phone else ""}
        {f'<div class="customer-info-row"><span> العنوان :{html.escape(address_text)}</span></div>' if address_text else ""}
      </div>
        """

    @staticmethod
    def _value(payload: Dict[str, Any], *keys: str, default: Any = "") -> Any:
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        return default

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _address_to_text(raw_address: Any) -> str:
        if isinstance(raw_address, dict):
            return str(raw_address.get("address") or raw_address.get("name") or "")
        return str(raw_address or "")

    @staticmethod
    def _format_date_parts(raw_value: Any) -> tuple[str, str]:
        if not raw_value:
            return "---", "---"
        value = str(raw_value)
        candidates = [value]
        if value.endswith("Z"):
            candidates.append(value.replace("Z", "+00:00"))
        for candidate in candidates:
            try:
                dt = datetime.fromisoformat(candidate)
                return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
            except ValueError:
                continue
        if len(value) > 10:
            return value[:10], value[11:16] if len(value) >= 16 else "---"
        return value, "---"

    @staticmethod
    def _order_type_label(order_type: str) -> str:
        mapping = {
            "delivery": "دليفري",
            "takeaway": "تيك اواي",
            "dine_in": "صالة",
            "hall": "صالة",
        }
        return mapping.get(str(order_type or "").lower(), "غير محدد")

    def test_print(self) -> bool:
        dummy_order = {
            "id": 0,
            "order_number": "TEST-0001",
            "order_date": "2026-04-25T12:00:00",
            "order_type": "takeaway",
            "total_amount": 120.0,
            "subtotal": 120.0,
            "customer_name": "عميل تجريبي",
            "customer_phone": "01000000000",
            "items": [
                {"product_id": 1, "product_name": "وجبة فراخ", "quantity": 2, "unit_price": 50},
                {"product_id": 2, "product_name": "بيبسي", "quantity": 1, "unit_price": 20},
            ],
        }
        return self.print_receipt(dummy_order, "test")


thermal_printer = PrinterManager()
