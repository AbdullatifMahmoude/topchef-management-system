import logging
import queue
import threading
import time
from datetime import datetime
from typing import Any, Dict, List

import arabic_reshaper
import qrcode
import win32print
import win32ui
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont, ImageWin

from print_agent.config import config

log = logging.getLogger("topchef_print_agent")


def is_arabic(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return any(
        "\u0600" <= c <= "\u06ff"
        or "\u0750" <= c <= "\u077f"
        or "\u08a0" <= c <= "\u08ff"
        or "\ufb50" <= c <= "\ufdff"
        or "\ufe70" <= c <= "\ufeff"
        for c in text
    )


def rtl(text: Any) -> str:
    if text is None:
        return ""
    text = str(text)
    if not is_arabic(text):
        return text
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


class PrinterManager:
    PAPER_WIDTH_PX = 576
    MARGIN = 16
    CONTENT_WIDTH = PAPER_WIDTH_PX - (MARGIN * 2)
    RENDER_SCALE = 2

    def __init__(self):
        self._job_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._worker_thread = threading.Thread(target=self._printer_worker, daemon=True)
        self._worker_thread.start()
        self._last_order_id = None
        self._last_order_data: Dict[str, Any] = {}
        self._last_receipt_type = "customer"

    def start(self):
        if not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._printer_worker, daemon=True)
            self._worker_thread.start()
            log.info("Native image printer manager started.")

    def get_printers(self) -> List[str]:
        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            return [p[2] for p in win32print.EnumPrinters(flags)]
        except Exception as exc:
            log.error("Failed to enumerate printers: %s", exc)
            return []

    def test_print(self) -> bool:
        test_order = {
            "id": "TEST",
            "orderNumber": "0000",
            "created_at": datetime.now().isoformat(),
            "creator_name": "Admin",
            "orderType": "hall",
            "itemsTotal": 100.0,
            "grandTotal": 100.0,
            "cart": [{"item": {"name": "تجربة طباعة", "price": 100.0}, "qty": 1}],
        }
        return self.print_receipt(test_order, "test")

    def print_receipt(self, order: Dict[str, Any], receipt_type: str = "customer") -> bool:
        if not order:
            log.warning("No order data provided to native printer.")
            return False
        self._last_order_id = order.get("id")
        self._last_order_data = order
        self._last_receipt_type = receipt_type
        document_name = f"order-{self._value(order, 'order_number', 'orderNumber', 'id', default='receipt')}"
        self._job_queue.put({"document_name": document_name, "order": order, "receipt_type": receipt_type})
        return True

    def print_html(self, html_content: str, document_name: str = "Top Chef Receipt", order_data: dict = None) -> bool:
        order = order_data or {}
        if not order:
            log.warning("Frontend silent print did not include order data; native print skipped.")
            return False
        self._last_order_id = order.get("id")
        self._last_order_data = order
        self._last_receipt_type = "customer"
        self._job_queue.put({"document_name": document_name, "order": order, "receipt_type": "customer"})
        return True

    def reprint_last(self, receipt_type: str = "customer") -> bool:
        if not self._last_order_data:
            log.warning("No last order to reprint")
            return False
        self._job_queue.put(
            {
                "document_name": f"reprint-{self._last_order_id or 'receipt'}",
                "order": self._last_order_data,
                "receipt_type": receipt_type,
            }
        )
        return True

    def _value(self, payload: Dict[str, Any], *keys: str, default: Any = "") -> Any:
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        return default

    def _number(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def _format_date_parts(self, raw_value: Any) -> tuple[str, str]:
        if not raw_value:
            return "---", "---"

        value = str(raw_value)
        for candidate in (value, value.replace("Z", "+00:00")):
            try:
                dt = datetime.fromisoformat(candidate)
                return dt.strftime("%Y/%m/%d"), dt.strftime("%I:%M %p")
            except ValueError:
                continue

        if len(value) > 10:
            return value[:10], value[11:16] if len(value) >= 16 else "---"
        return value, "---"

    def _order_type_label(self, order_type: Any) -> str:
        value = str(order_type or "").lower()
        if value == "delivery":
            return "دليفري"
        if value == "takeaway":
            return "تيك اواي"
        if value == "dine_in" or value == "hall":
            return "صالة"
        return "غير محدد"

    def _address_to_text(self, raw_address: Any) -> str:
        if isinstance(raw_address, dict):
            return str(
                raw_address.get("address")
                or raw_address.get("address_line")
                or raw_address.get("full_address")
                or raw_address.get("street")
                or raw_address.get("name")
                or ""
            )
        return str(raw_address or "")

    def _items(self, order: Dict[str, Any]) -> List[Dict[str, Any]]:
        cart = order.get("cart")
        if isinstance(cart, list) and cart:
            return cart

        items = []
        for item in order.get("items") or []:
            items.append(
                {
                    "qty": item.get("quantity", 0),
                    "item": {
                        "name": item.get("product_name") or item.get("name") or f"صنف #{item.get('product_id', '')}",
                        "price": item.get("unit_price", 0),
                    },
                }
            )
        return items

    def _font(self, name: str, size: int):
        paths = [
            f"C:/Windows/Fonts/{name}.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for path in paths:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _get_fonts(self, scale: int = 1):
        def size(value: int) -> int:
            return int(value * scale)

        return {
            "body": self._font("arialbd", size(26)),
            "small": self._font("arialbd", size(27)),
            "tiny": self._font("arialbd", size(25)),
            "item": self._font("arialbd", size(28)),
            "table": self._font("arialbd", size(27)),
            "customer": self._font("arialbd", size(26)),
            "footer": self._font("arialbd", size(24)),
            "order": self._font("arialbd", size(35)),
            "grand": self._font("arialbd", size(33)),
        }

    def _generate_receipt_image(self, order: Dict[str, Any], receipt_type: str = "customer") -> Image.Image:
        scale = self.RENDER_SCALE
        fonts = self._get_fonts(scale)
        items = self._items(order)
        width = self.PAPER_WIDTH_PX * scale
        margin = self.MARGIN * scale
        content_right = width - margin

        def u(value: int | float) -> int:
            return int(round(value * scale))

        # Allocate enough vertical room for wrapped product names and addresses;
        # the image is cropped to the actual drawn height before printing.
        height = u(900 + (len(items) * 190))
        if self._has_customer_info(order):
            height += u(300)
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        y = margin

        def text_size(text: Any, font) -> tuple[int, int]:
            shaped = rtl(text)
            box = draw.textbbox((0, 0), shaped, font=font)
            return box[2] - box[0], box[3] - box[1]

        def draw_text(text: Any, x: int, y_pos: int, font, anchor: str = "la", fill: str = "black"):
            draw.text((x, y_pos), rtl(text), fill=fill, font=font, anchor=anchor)

        def draw_right(text: Any, y_pos: int, font, x: int = content_right):
            draw_text(text, x, y_pos, font, "ra")

        def draw_center(text: Any, y_pos: int, font):
            draw_text(text, width // 2, y_pos, font, "ma")

        def line(y_pos: int, fill: str = "black", dash: bool = False):
            if dash:
                x = margin
                while x < content_right:
                    draw.line((x, y_pos, min(x + u(12), content_right), y_pos), fill=fill, width=scale)
                    x += u(18)
            else:
                draw.line((margin, y_pos, content_right, y_pos), fill=fill, width=scale)

        def wrap_text(text: Any, font, max_width: int) -> list[str]:
            raw = str(text or "")
            if not raw:
                return [rtl("")]

            words = raw.split()
            if not words:
                words = list(raw)

            lines: list[str] = []
            current = ""

            def append_fitted_chunk(chunk: str):
                piece = ""
                for char in chunk:
                    candidate = piece + char
                    if piece and draw.textlength(rtl(candidate), font=font) > max_width:
                        lines.append(rtl(piece))
                        piece = char
                    else:
                        piece = candidate
                if piece:
                    lines.append(rtl(piece))

            for word in words:
                candidate = f"{current} {word}".strip()
                if draw.textlength(rtl(candidate), font=font) <= max_width:
                    current = candidate
                    continue
                if current:
                    lines.append(rtl(current))
                    current = ""
                if draw.textlength(rtl(word), font=font) <= max_width:
                    current = word
                else:
                    append_fitted_chunk(word)

            if current:
                lines.append(rtl(current))
            return lines or [rtl(raw)]

        full_order_number = self._value(order, "orderNumber", "order_number", "id", default="---")
        order_number = str(full_order_number).split("-")[-1] if "-" in str(full_order_number) else str(full_order_number)
        cashier = self._value(order, "creator_name", "cashierName", "cashier_name", default="---")
        order_type = self._value(order, "orderType", "order_type", default="")
        formatted_date, formatted_time = self._format_date_parts(self._value(order, "created_at", "order_date"))

        qr_size = u(116)
        qr = qrcode.QRCode(version=1, box_size=4, border=0)
        qr.add_data("https://top-chef-resturant.vercel.app/")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((qr_size, qr_size))
        image.paste(qr_img, (margin, y))

        draw_right(formatted_date, y + u(14), fonts["small"])
        draw_right(formatted_time, y + u(42), fonts["small"])

        order_text = f"رقم الطلب {order_number}"
        shaped_order = rtl(order_text)
        order_bbox = draw.textbbox((0, 0), shaped_order, font=fonts["order"])
        order_w = order_bbox[2] - order_bbox[0]
        order_h = order_bbox[3] - order_bbox[1]
        box_pad_x = u(14)
        box_pad_y = u(8)
        box_left = (width - order_w) // 2 - box_pad_x
        box_top = y + u(30) - ((order_h + (box_pad_y * 2)) // 2)
        box_right = box_left + order_w + (box_pad_x * 2)
        box_bottom = box_top + order_h + (box_pad_y * 2)
        draw.rounded_rectangle(
            (box_left, box_top, box_right, box_bottom),
            radius=u(5),
            outline="black",
            width=u(2),
        )
        text_x = box_left + box_pad_x - order_bbox[0]
        text_y = box_top + box_pad_y - order_bbox[1]
        draw.text((text_x, text_y), shaped_order, fill="black", font=fonts["order"])

        y += max(qr_size, u(112)) + u(8)
        line(y, dash=True)
        y += u(12)

        draw_right(f"كاشير: {cashier}", y, fonts["small"])
        draw_text(self._order_type_label(order_type), margin, y, fonts["small"])
        y += u(40)

        delivery_person = self._value(order, "delivery_person_name", default="")
        selected_delivery = order.get("selectedDelivery")
        if not delivery_person and isinstance(selected_delivery, dict):
            delivery_person = selected_delivery.get("name", "")
        if str(order_type).lower() == "delivery" and delivery_person:
            draw_right(f"مندوب: {delivery_person}", y, fonts["small"])
            y += u(38)

        line(y, dash=True)
        y += u(12)

        qty_x = content_right - u(18)
        item_right = content_right - u(56)
        price_x = margin + u(180)
        total_x = margin + u(52)

        draw_right("ك", y, fonts["table"], qty_x)
        draw_right("الصنف", y, fonts["table"], item_right)
        draw_text("سعر", price_x, y, fonts["table"], "ma")
        draw_text("إجمالي", total_x, y, fonts["table"], "ma")
        y += u(37)
        line(y)
        y += u(10)

        for cart_item in items:
            item_data = cart_item.get("item") or cart_item
            qty = self._number(cart_item.get("qty") or cart_item.get("quantity") or 0)
            price = self._number(item_data.get("price") or cart_item.get("price") or item_data.get("unit_price") or 0)
            name = item_data.get("name") or item_data.get("product_name") or "---"
            total = qty * price

            name_lines = wrap_text(name, fonts["item"], u(235))
            row_start_y = y
            draw_right(f"{qty:g}", row_start_y, fonts["item"], qty_x)
            for line_index, line_text in enumerate(name_lines):
                draw.text(
                    (item_right, row_start_y + (line_index * u(34))),
                    line_text,
                    fill="black",
                    font=fonts["item"],
                    anchor="ra",
                )
            draw_text(f"{price:.0f}x", price_x, row_start_y, fonts["item"], "ma")
            draw_text(f"{total:.0f}", total_x, row_start_y, fonts["item"], "ma")
            y += max(u(44), len(name_lines) * u(34) + u(10))
            draw.line((margin, y, content_right, y), fill="#eeeeee", width=scale)
            y += u(12)

        y += u(2)
        line(y)
        y += u(12)

        subtotal = self._number(self._value(order, "itemsTotal", "subtotal", default=0))
        grand_total = self._number(self._value(order, "total_amount", "grandTotal", default=0))
        delivery_fee = self._number(self._value(order, "delivery_fee", "selectedDeliveryFee", default=0))
        dine_in_fee = self._number(self._value(order, "selectedDineInFee", default=0))

        draw_right("المجموع:", y, fonts["small"])
        draw_text(f"{subtotal:.2f}", margin, y, fonts["small"])
        y += u(34)

        lower_type = str(order_type).lower()
        if lower_type == "delivery" and delivery_fee:
            draw_right("التوصيل:", y, fonts["small"])
            draw_text(f"{delivery_fee:.2f}", margin, y, fonts["small"])
            y += u(34)

        hall_fee = delivery_fee or dine_in_fee
        if (lower_type == "hall" or lower_type == "dine_in") and hall_fee:
            draw_right("الصالة:", y, fonts["small"])
            draw_text(f"{hall_fee:.2f}", margin, y, fonts["small"])
            y += u(34)

        discount_amount = self._number(self._value(order, "discount_amount", "discountAmount", default=0))
        discount_reason = self._value(order, "discount_reason", "discountReason", default="")
        
        if discount_amount > 0:
            discount_label = "الخصم:"
            if discount_reason:
                discount_label = f"الخصم ({discount_reason}):"
            draw_right(discount_label, y, fonts["small"])
            draw_text(f"- {discount_amount:.2f}", margin, y, fonts["small"])
            y += u(34)

        y += u(2)
        line(y, dash=True)
        y += u(12)
        draw_right("الإجمالي النهائي:", y, fonts["grand"])
        draw_text(f"{grand_total:.2f} ج.م", margin, y, fonts["grand"])
        y += u(50)

        y = self._draw_customer_info(order, image, draw, fonts, y, scale)

        line(y, fill="#777777", dash=True)
        y += u(16)
        draw_center("مزلقان هرية رزنة - الزقازيق - الشرقية", y, fonts["footer"])
        y += u(34)
        draw_center("01212758001 - 01129820007", y, fonts["footer"])
        y += u(34)
        draw_center('زورو موقعنا الإلكتروني "topchefeg.com"', y, fonts["footer"])
        y += u(52)

        return image.crop((0, 0, width, y))

    def _has_customer_info(self, order: Dict[str, Any]) -> bool:
        return bool(
            self._value(order, "customerName", "customer_name", default="")
            or self._value(order, "customerPhone", "customer_phone", default="")
            or self._value(order, "customerNotes", "customer_notes", default="")
            or self._address_to_text(
                self._value(order, "customerAddress", "customer_address", "address", default="")
            )
        )

    def _draw_customer_info(self, order, image, draw, fonts, y: int, scale: int = 1) -> int:
        customer_name = self._value(order, "customerName", "customer_name", default="")
        customer_phone = self._value(order, "customerPhone", "customer_phone", default="")
        customer_notes = self._value(order, "customerNotes", "customer_notes", default="")
        address = self._address_to_text(
            self._value(order, "customerAddress", "customer_address", "address", default="")
        )
        if not any([customer_name, customer_phone, address, customer_notes]):
            return y

        def u(value: int | float) -> int:
            return int(round(value * scale))

        x1 = self.MARGIN * scale
        x2 = (self.PAPER_WIDTH_PX * scale) - (self.MARGIN * scale)
        box_top = y
        y += u(14)

        def draw_center(text, y_pos, font):
            draw.text(((self.PAPER_WIDTH_PX * scale) // 2, y_pos), rtl(text), fill="black", font=font, anchor="ma")

        def draw_right(text, y_pos, font):
            draw.text((x2 - u(12), y_pos), rtl(text), fill="black", font=font, anchor="ra")

        draw_center("بيانات العميل", y, fonts["small"])
        y += u(37)
        if customer_name:
            draw_right(f" اسم العميل :{customer_name}", y, fonts["customer"])
            y += u(36)
        if customer_phone:
            draw_right(f" رقم التليفون :{customer_phone}", y, fonts["customer"])
            y += u(36)
        if address:
            draw_right(f" العنوان :{address}", y, fonts["customer"])
            y += u(36)
        if customer_notes:
            draw_right(f" ملاحظات :{customer_notes}", y, fonts["customer"])
            y += u(36)

        draw.rounded_rectangle((x1, box_top, x2, y + u(10)), radius=u(4), outline="black", width=scale)
        return y + u(24)

    def _target_printers(self) -> List[str]:
        available = self.get_printers()
        selected = [name for name in config.printer_names if name in available]
        if config.printer_names:
            return selected
        ignore_list = ("pdf", "onenote", "xps", "fax", "microsoft", "send to", "webex")
        physical_printers = [
            printer
            for printer in available
            if not any(ignored in printer.lower() for ignored in ignore_list)
        ]
        if physical_printers:
            return physical_printers
        try:
            return [win32print.GetDefaultPrinter()]
        except Exception:
            return available[:1]

    def _is_printer_ready(self, printer_name: str) -> tuple[bool, str]:
        handle = None
        try:
            handle = win32print.OpenPrinter(printer_name)
            info = win32print.GetPrinter(handle, 2)
            status = info.get("Status", 0) if isinstance(info, dict) else 0
            if not isinstance(status, int):
                try:
                    status = int(status)
                except (TypeError, ValueError):
                    return False, "Unknown"

            # Printer Status is only a best-effort optimization.
            # Some Windows printer drivers (especially thermal printers) report Status == 0 even when
            # the printer is disconnected. The actual readiness check is whether StartDoc succeeds.
            unready_masks = (
                (getattr(win32print, "PRINTER_STATUS_OFFLINE", 0x00000080), "Offline"),
                (getattr(win32print, "PRINTER_STATUS_ERROR", 0x00000002), "Error"),
                (getattr(win32print, "PRINTER_STATUS_NOT_AVAILABLE", 0x00001000), "Not Available"),
                (getattr(win32print, "PRINTER_STATUS_PAPER_OUT", 0x00000010), "Paper Out"),
                (getattr(win32print, "PRINTER_STATUS_DOOR_OPEN", 0x00400000), "Door Open"),
                (getattr(win32print, "PRINTER_STATUS_PAUSED", 0x00000001), "Paused"),
                (getattr(win32print, "PRINTER_STATUS_PAPER_JAM", 0x00000008), "Paper Jam"),
                (getattr(win32print, "PRINTER_STATUS_PAPER_PROBLEM", 0x00000040), "Paper Problem"),
            )
            for mask, label in unready_masks:
                if status & mask:
                    return False, label

            return True, "No blocking status"
        except Exception as exc:
            log.warning("Could not read printer readiness for '%s': %s", printer_name, exc)
            return False, "Unknown"
        finally:
            if handle is not None:
                try:
                    win32print.ClosePrinter(handle)
                except Exception:
                    pass

    def _print_native_gdi(self, image: Image.Image, printer_name: str, document_name: str) -> bool:
        hdc = None
        try:
            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(printer_name)
            printable_width = hdc.GetDeviceCaps(110)
            printable_height = hdc.GetDeviceCaps(111)

            success = False
            for attempt in range(2):
                try:
                    hdc.StartDoc(document_name)
                    success = True
                    break
                except Exception as e:
                    if attempt == 0:
                        log.warning("StartDoc failed on %s (attempt %d). Retrying in 0.5s...", printer_name, attempt + 1)
                        time.sleep(0.5)
                    else:
                        raise e

            if success:
                hdc.StartPage()

                dib = ImageWin.Dib(image)
                scaled_height = int(image.size[1] * (printable_width / image.size[0]))
                dib.draw(hdc.GetHandleOutput(), (0, 0, printable_width, min(scaled_height, printable_height)))

                hdc.EndPage()
                hdc.EndDoc()
                log.info("Native Python GDI print successful to %s", printer_name)
                return True
            return False
        except Exception as exc:
            printer_status = "Unknown"
            try:
                handle = win32print.OpenPrinter(printer_name)
                info = win32print.GetPrinter(handle, 2)
                status = info.get("Status", 0)
                win32print.ClosePrinter(handle)
                status_label = self._status_label(status)
                printer_status = f"Status Code: {status} ({status_label})"
            except Exception:
                pass
            
            log.error("Native Python GDI print failed on %s: %s | Printer Status: %s", printer_name, exc, printer_status)
            try:
                if hdc:
                    hdc.AbortDoc()
            except Exception:
                pass
            return False
        finally:
            try:
                if hdc:
                    hdc.DeleteDC()
            except Exception:
                pass

    def _status_label(self, status: Any) -> str:
        if not isinstance(status, int):
            try:
                status = int(status)
            except (TypeError, ValueError):
                return "Unknown"

        status_map = {
            getattr(win32print, "PRINTER_STATUS_OFFLINE", 0x00000080): "Offline",
            getattr(win32print, "PRINTER_STATUS_ERROR", 0x00000002): "Error",
            getattr(win32print, "PRINTER_STATUS_NOT_AVAILABLE", 0x00001000): "Not Available",
            getattr(win32print, "PRINTER_STATUS_PAPER_OUT", 0x00000010): "Paper Out",
            getattr(win32print, "PRINTER_STATUS_DOOR_OPEN", 0x00400000): "Door Open",
            getattr(win32print, "PRINTER_STATUS_PAUSED", 0x00000001): "Paused",
            getattr(win32print, "PRINTER_STATUS_PAPER_JAM", 0x00000008): "Paper Jam",
            getattr(win32print, "PRINTER_STATUS_PAPER_PROBLEM", 0x00000040): "Paper Problem",
        }

        matched = [label for mask, label in status_map.items() if status & mask]
        if matched:
            return ", ".join(matched)
        return "Unknown"

    def _alert_ui(self, message: str) -> None:
        log.error("Print alert: %s", message)

    def _printer_worker(self) -> None:
        while True:
            job = self._job_queue.get()
            try:
                order = job.get("order")
                if not order:
                    log.warning("No order data provided to native printer. Skipping.")
                    continue

                image = self._generate_receipt_image(order, job.get("receipt_type", "customer"))
                printers = self._target_printers()
                if not printers:
                    log.error("No printers found on this device.")
                    self._alert_ui("No printers found. Please check printer connections.")
                    continue

                printed_count = 0
                for printer_name in printers:
                    try:
                        ready, reason = self._is_printer_ready(printer_name)
                        if not ready:
                            log.warning(
                                "Skipping printer '%s' because it is %s.",
                                printer_name,
                                reason,
                            )
                            continue

                        if self._print_native_gdi(image, printer_name, job.get("document_name", "Top Chef Receipt")):
                            printed_count += 1
                    finally:
                        time.sleep(0.4)

                if printed_count == 0:
                    self._alert_ui("No available printer found. Please check printer connections.")
                    log.error("No available printer found. Please check printer connections.")
            except Exception as exc:
                log.error("Printer worker encountered an error: %s", exc, exc_info=True)
            finally:
                self._job_queue.task_done()


thermal_printer = PrinterManager()
