import threading
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image

import app as printer_app


class PrinterTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        history = patch.object(printer_app, 'print_history', printer_app.PrintHistory(Path(directory.name) / 'history.sqlite3'))
        history.start()
        self.addCleanup(history.stop)

    def test_live_callback_can_print_without_request_context(self):
        with patch.object(printer_app, 'TEST_MODE', False), \
                patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', 'printer'), \
                patch.object(printer_app, 'ble_print_text') as transport:
            printer_app.print_text_content('live dictation')
        transport.assert_called_once()
        self.assertEqual(transport.call_args.args[0], 'printer')
        self.assertIn('live dictation', transport.call_args.args[1])

    def test_test_mode_does_not_touch_hardware(self):
        with patch.object(printer_app, 'TEST_MODE', True), \
                patch.object(printer_app, 'get_printer') as get_printer, \
                patch.object(printer_app, 'ble_print_text') as transport:
            self.assertIn('no paper printed', printer_app.print_text_content('test'))
            response = printer_app.app.test_client().post('/print', json={'content': 'manual test'})
            self.assertTrue(response.json['test_mode'])
            self.assertEqual(response.status_code, 200)
            get_printer.assert_not_called()
            transport.assert_not_called()

    def test_non_ble_device_is_closed_even_when_print_fails(self):
        printer = Mock()
        printer.text.side_effect = RuntimeError('USB unplugged')
        with patch.object(printer_app, 'TEST_MODE', False), \
                patch.object(printer_app, 'PRINTER_TYPE', 'usb'), \
                patch.object(printer_app, 'get_printer', return_value=printer):
            with self.assertRaisesRegex(RuntimeError, 'USB unplugged'):
                printer_app.print_text_content('text')
            printer.close.assert_called_once()

    def test_unconfigured_printer_reports_failure(self):
        with patch.object(printer_app, 'TEST_MODE', False), \
                patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', ''):
            with self.assertRaisesRegex(RuntimeError, 'BLE_PRINTER_ADDR'):
                printer_app.print_text_content('text')

    def test_busy_printer_rejects_new_prints_and_health_never_touches_hardware(self):
        printing, release = threading.Event(), threading.Event()
        outcomes = []

        def print_text(address, text):
            printing.set()
            release.wait(3)

        def live_print():
            outcomes.append(printer_app.print_text_content('live first'))

        with patch.object(printer_app, 'TEST_MODE', False), \
                patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', 'printer'), \
                patch.object(printer_app, 'ble_print_text', side_effect=print_text) as transport, \
                patch.object(printer_app, 'ble_is_available') as discover:
            live = threading.Thread(target=live_print)
            live.start()
            try:
                self.assertTrue(printing.wait(1))
                client = printer_app.app.test_client()
                for path, payload in [('/print', {'content': 'manual'}),
                                      ('/submit_ticket', {'question': 'manual'})]:
                    response = client.post(path, json=payload)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json['printer_state'], 'busy')
                health = client.get('/health')
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json['status'], 'healthy')
                self.assertEqual(health.json['printer_state'], 'busy')
                discover.assert_not_called()
                transport.assert_called_once()
            finally:
                release.set()
                live.join(2)
            self.assertFalse(live.is_alive())
            self.assertEqual(len(outcomes), 1)


if __name__ == '__main__':
    unittest.main()
