"""Regressions for hardware stalls exhausting the eight production HTTP workers."""
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import app as printer_app
from printer_worker import PrinterUnavailable, PrinterWorker, timeout_setting
from serve_remote import create_remote_server


class PrinterWorkerTests(unittest.TestCase):
    def test_timeout_keeps_one_hardware_slot_until_the_original_operation_exits(self):
        worker = PrinterWorker()
        release = threading.Event()
        try:
            with self.assertRaises(PrinterUnavailable) as timed_out:
                worker.run(lambda: release.wait(3), timeout=0.02)
            self.assertEqual(timed_out.exception.status, 504)
            self.assertIn('may still print', str(timed_out.exception))
            active = worker._active
            self.assertIsNotNone(active)
            for _ in range(20):
                with self.assertRaises(PrinterUnavailable) as busy:
                    worker.run(lambda: self.fail('Must not start a second operation'), timeout=1)
                self.assertEqual(busy.exception.state, 'unavailable')
                self.assertIs(worker._active, active)
        finally:
            release.set()
        self.assertTrue(active.done.wait(1))
        self.assertEqual(worker.run(lambda: 'recovered', timeout=1), 'recovered')

    def test_exception_frees_the_slot_without_retrying(self):
        worker = PrinterWorker()
        failure = RuntimeError('Disconnected during write')
        def fail():
            raise failure
        with self.assertRaises(RuntimeError) as caught:
            worker.run(fail, timeout=1)
        self.assertIs(caught.exception, failure)
        self.assertEqual(worker.run(lambda: 42, timeout=1), 42)

    def test_thread_start_failure_does_not_leave_the_printer_busy(self):
        worker = PrinterWorker()
        with patch('printer_worker.threading.Thread.start', side_effect=RuntimeError('No thread')):
            with self.assertRaisesRegex(RuntimeError, 'No thread'):
                worker.run(lambda: None, timeout=1)
        self.assertEqual(worker.run(lambda: 42, timeout=1), 42)

    def test_configuration_cannot_disable_deadlines_with_nan_or_infinity(self):
        for value in ('0', '-1', 'nan', 'inf', 'invalid'):
            with self.subTest(value=value), patch.dict(os.environ, {'PRINTER_CHECK_TIMEOUT': value}):
                with self.assertRaises(ValueError):
                    timeout_setting('PRINTER_CHECK_TIMEOUT', 5)


class PrinterStallHTTPTests(unittest.TestCase):
    def setUp(self):
        self.release = threading.Event()
        self.started = threading.Event()
        self.worker = PrinterWorker()
        self.calls = 0
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = [('_printer_worker', self.worker), ('PRINTER_OPERATION_TIMEOUT', 0.5),
                    ('PRINTER_CHECK_TIMEOUT', 0.5), ('TEST_MODE', False),
                    ('PRINTER_TYPE', 'ble'), ('BLE_PRINTER_ADDR', 'test-printer')]
        # The deployed app may precede the optional durable-history feature.
        if hasattr(printer_app, 'PrintHistory'):
            settings.append(('print_history', printer_app.PrintHistory(Path(directory.name) / 'history.sqlite3')))
        for name, value in settings:
            setting = patch.object(printer_app, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        for name in ('ble_print_text', 'ble_print_raster_ticket', 'ble_is_available'):
            setting = patch.object(printer_app, name, side_effect=self.stall, create=True)
            setting.start()
            self.addCleanup(setting.stop)
        self.server = create_remote_server(printer_app.app, 0)
        self.server_thread = threading.Thread(target=self.server.run, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.stop)

    def stall(self, *_):
        self.calls += 1
        self.started.set()
        if not self.release.wait(5):
            raise RuntimeError('Test hardware was not released')
        return True

    def stop(self):
        active = self.worker._active
        self.release.set()
        if active is not None:
            self.assertTrue(active.done.wait(2))
        self.server.task_dispatcher.shutdown()
        self.server.trigger.pull_trigger(lambda: self.server.asyncore.close_all(map=self.server._map))
        self.server_thread.join(3)
        self.assertFalse(self.server_thread.is_alive())

    def request(self, path, body=None):
        connection = HTTPConnection('127.0.0.1', self.server.effective_port, timeout=2)
        try:
            connection.request('GET' if body is None else 'POST', path,
                               body=None if body is None else json.dumps(body),
                               headers={} if body is None else {'Content-Type': 'application/json'})
            response = connection.getresponse()
            content = response.read()
            return response.status, (json.loads(content) if 'application/json' in
                                     response.getheader('Content-Type', '') else content)
        finally:
            connection.close()

    def test_stalled_print_cannot_starve_pages_status_or_microphone_requests(self):
        with ThreadPoolExecutor(max_workers=16) as clients:
            printing = clients.submit(self.request, '/print', {'content': 'Simulated hardware only'})
            try:
                self.assertTrue(self.started.wait(2))
                requests = [clients.submit(self.request, '/health') for _ in range(12)]
                requests += [clients.submit(self.request, path)
                             for path in ('/', '/chat.js', '/microphone/live')]
                requests += [clients.submit(self.request, '/print', {'content': 'Must not print again'})
                             for _ in range(12)]
                results = [request.result(timeout=2) for request in requests]
                self.assertTrue(all(status == 200 for status, _ in results[:15]))
                self.assertTrue(all(status == 503 for status, _ in results[15:]))
                self.assertTrue(all(data['status'] == 'healthy' for _, data in results[:12]))
                status, data = printing.result(timeout=2)
                self.assertEqual(status, 504)
                self.assertFalse(data['success'])
                self.assertIn('may still print', data['error'])
                self.assertNotIn('preview', data)
                self.assertEqual(self.request('/health')[1]['printer_state'], 'unavailable')
                self.assertEqual(self.calls, 1)
                active = self.worker._active
            finally:
                self.release.set()
            self.assertTrue(active.done.wait(2))
            self.assertEqual(self.request('/health')[1]['printer_state'], 'available')

    def test_stalled_connection_check_does_not_spawn_more_checks_or_block_the_site(self):
        with ThreadPoolExecutor(max_workers=12) as clients:
            checking = clients.submit(self.request, '/health')
            try:
                self.assertTrue(self.started.wait(2))
                results = [clients.submit(self.request, '/health') for _ in range(10)]
                self.assertTrue(all(result.result(timeout=2)[1]['printer_state'] in ('checking', 'unavailable')
                                    for result in results))
                self.assertEqual(self.request('/')[0], 200)
                self.assertEqual(checking.result(timeout=2)[1]['printer_state'], 'unavailable')
                self.assertEqual(self.request('/print', {'content': 'Must not overlap'})[0], 503)
                self.assertEqual(self.calls, 1)
            finally:
                self.release.set()
