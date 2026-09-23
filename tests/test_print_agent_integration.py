import unittest
from unittest.mock import PropertyMock, patch

from fastapi.testclient import TestClient

from print_agent.service import app


class PrintAgentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_receipt_details_only_include_present_payment_and_offer(self):
        from print_agent.printer import PrinterManager

        printer = PrinterManager()
        plain = {"payment_method": "cash", "discount_amount": 0}
        self.assertEqual(printer._payment_lines(plain), ["طريقة الدفع: نقدي"])
        self.assertEqual(printer._offer_lines(plain), [])

        discounted = {
            "payment_method": "instapay",
            "payment_destination": "01009515031",
            "applied_offer": {
                "code": "SAVE20",
                "display_name": "عرض العائلة",
                "discount_type": "percentage",
                "discount_value": 20,
                "discount_amount": 30,
            },
            "discount_amount": 30,
        }
        self.assertEqual(
            printer._payment_lines(discounted),
            ["طريقة الدفع: إنستا باي", "رقم التحويل: 01009515031"],
        )
        self.assertEqual(
            printer._offer_lines(discounted),
            ["العرض: عرض العائلة", "كود العرض: SAVE20", "تفاصيل العرض: خصم 20%"],
        )
        self.assertEqual(
            printer._payment_lines({"payment_method": "wallet"}),
            ["طريقة الدفع: محفظة إلكترونية", "رقم التحويل: 01009515031"],
        )

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_invoice_is_forwarded_to_native_printer(self):
        order = {
            "id": 42,
            "orderNumber": "T1-0042",
            "cart": [{"item": {"name": "اختبار", "price": 50}, "qty": 2}],
            "grandTotal": 100,
        }
        with (
            patch(
                "print_agent.config.PrintAgentConfig.printer_names",
                new_callable=PropertyMock,
                return_value=["Test Printer"],
            ),
            patch("print_agent.service.thermal_printer.print_receipt", return_value=True) as printer,
        ):
            response = self.client.post(
                "/api/print",
                json={"order": order, "receipt_type": "customer"},
                headers={"Origin": "https://topchef-system.fastapicloud.dev"},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"ok": True, "queued": True})
        printer.assert_called_once_with(order, "customer")
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "https://topchef-system.fastapicloud.dev",
        )

    def test_chrome_private_network_preflight(self):
        response = self.client.options(
            "/api/print",
            headers={
                "Origin": "https://topchef-system.fastapicloud.dev",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"),
                         "https://topchef-system.fastapicloud.dev")
        self.assertEqual(response.headers.get("access-control-allow-private-network"), "true")

    def test_unapproved_web_origin_is_rejected_by_cors(self):
        response = self.client.options(
            "/api/print",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertNotEqual(response.headers.get("access-control-allow-origin"),
                            "https://example.com")


if __name__ == "__main__":
    unittest.main()
