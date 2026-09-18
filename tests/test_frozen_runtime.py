import unittest
from unittest.mock import PropertyMock, patch

from print_agent import service


class FrozenRuntimeTests(unittest.TestCase):
    def test_uvicorn_does_not_configure_console_logging(self):
        with (
            patch("print_agent.config.PrintAgentConfig.printer_names", new_callable=PropertyMock, return_value=["Saved Printer"]),
            patch("print_agent.service.uvicorn.run") as run,
        ):
            service.main()

        options = run.call_args.kwargs
        self.assertIsNone(options["log_config"])
        self.assertFalse(options["access_log"])
        self.assertEqual(options["host"], "127.0.0.1")

    def test_main_checks_windows_autostart(self):
        with (
            patch("print_agent.service.ensure_windows_autostart") as autostart,
            patch("print_agent.config.PrintAgentConfig.printer_names", new_callable=PropertyMock, return_value=["Saved Printer"]),
            patch("print_agent.service.uvicorn.run"),
        ):
            service.main()
        autostart.assert_called_once_with()

    def test_saved_printer_does_not_reopen_setup_page(self):
        with (
            patch("print_agent.config.PrintAgentConfig.printer_names", new_callable=PropertyMock, return_value=["Saved Printer"]),
            patch("print_agent.service.threading.Timer") as timer,
            patch("print_agent.service.uvicorn.run"),
        ):
            service.main()
        timer.assert_not_called()

    def test_first_run_opens_setup_page(self):
        with (
            patch("print_agent.config.PrintAgentConfig.printer_names", new_callable=PropertyMock, return_value=[]),
            patch("print_agent.service.threading.Timer") as timer,
            patch("print_agent.service.uvicorn.run"),
        ):
            service.main()
        timer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
