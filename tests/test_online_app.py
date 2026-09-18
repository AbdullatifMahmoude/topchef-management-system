import unittest

from app.main import app


class OnlineApplicationTests(unittest.TestCase):
    def test_online_routes_have_no_legacy_client_endpoints(self):
        paths = [route.path.lower() for route in app.routes]
        self.assertFalse([path for path in paths if "desktop" in path])
        self.assertIn("/health", paths)


if __name__ == "__main__":
    unittest.main()
