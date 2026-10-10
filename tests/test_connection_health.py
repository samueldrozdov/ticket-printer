import unittest
from unittest.mock import Mock, patch

from usb.core import NoBackendError
from escpos.exceptions import USBNotFoundError

import app as printer_app


class ConnectionHealthTests(unittest.TestCase):
    def setUp(self):
        self.client = printer_app.app.test_client()
        for name, value in [('TEST_MODE', False), ('PRINTER_TYPE', 'usb')]:
            setting = patch.object(printer_app, name, value)
            setting.start()
            self.addCleanup(setting.stop)

    def test_hardware_identity_does_not_guess_pi_from_operating_system(self):
        with patch.object(printer_app.Path, 'read_text', side_effect=FileNotFoundError), \
                patch.object(printer_app.platform, 'system', return_value='Darwin'):
            self.assertEqual(printer_app.server_identity(), {'kind': 'computer', 'name': 'Mac'})
        with patch.object(printer_app.Path, 'read_text', side_effect=FileNotFoundError), \
                patch.object(printer_app.platform, 'system', return_value='Linux'):
            self.assertEqual(printer_app.server_identity()['kind'], 'computer')
        with patch.object(printer_app.Path, 'read_text', return_value='Raspberry Pi 4 Model B\x00'):
            self.assertEqual(printer_app.server_identity()['kind'], 'raspberry_pi')

    def test_missing_usb_support_reports_setup_needed_while_server_is_healthy(self):
        with patch.object(printer_app, 'Usb', side_effect=NoBackendError('No backend available')):
            response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['service'], 'samson')
        self.assertEqual(response.json['status'], 'healthy')
        self.assertFalse(response.json['test_mode'])
        self.assertFalse(response.json['printer_connected'])
        self.assertEqual(response.json['printer_state'], 'setup_required')
        self.assertIn('USB support', response.json['printer_message'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_missing_usb_printer_is_distinct_from_missing_support(self):
        with patch.object(printer_app, 'Usb', side_effect=USBNotFoundError('Unplugged')):
            response = self.client.get('/health')
        self.assertEqual(response.json['printer_state'], 'disconnected')
        self.assertIn('cable', response.json['printer_message'])

    def test_ready_usb_printer_is_closed_without_printing(self):
        printer = Mock()
        with patch.object(printer_app, 'Usb', return_value=printer):
            response = self.client.get('/health')
        self.assertTrue(response.json['printer_connected'])
        self.assertEqual(response.json['printer_state'], 'ready')
        printer.close.assert_called_once()
        printer._raw.assert_not_called()
        printer.text.assert_not_called()
        printer.cut.assert_not_called()

    def test_bluetooth_setup_discovery_and_check_failure_are_distinct(self):
        with patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', ''), \
                patch.object(printer_app, 'ble_is_available') as discover:
            self.assertEqual(self.client.get('/health').json['printer_state'], 'setup_required')
            discover.assert_not_called()
        with patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', 'configured-printer'):
            for result, state in [(True, 'available'), (False, 'disconnected')]:
                with patch.object(printer_app, 'ble_is_available', return_value=result):
                    self.assertEqual(self.client.get('/health').json['printer_state'], state)
            with patch.object(printer_app, 'ble_is_available', side_effect=RuntimeError('Bluetooth denied')):
                response = self.client.get('/health')
                self.assertEqual(response.json['printer_state'], 'unavailable')
                self.assertIn('server', response.json)

    def test_test_mode_identifies_host_without_accessing_printer(self):
        with patch.object(printer_app, 'TEST_MODE', True), \
                patch.object(printer_app, 'get_printer') as printer, \
                patch.object(printer_app, 'ble_is_available') as bluetooth:
            response = self.client.get('/health')
        self.assertTrue(response.json['test_mode'])
        self.assertEqual(response.json['printer_state'], 'test_mode')
        self.assertIn('server', response.json)
        printer.assert_not_called()
        bluetooth.assert_not_called()
