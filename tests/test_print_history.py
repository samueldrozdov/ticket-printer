import base64
import io
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import app as printer_app
from live_print import LivePrintQueue
from print_history import PrintHistory


class PrintHistoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'data' / 'history.sqlite3'
        self.history = PrintHistory(self.path)
        for name, value in [('print_history', self.history), ('TEST_MODE', False),
                            ('PRINTER_TYPE', 'ble'), ('BLE_PRINTER_ADDR', 'test-printer')]:
            setting = patch.object(printer_app, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        self.client = printer_app.app.test_client()

    def entries(self):
        response = self.client.get('/history')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        return response.json['entries']

    def test_empty_history(self):
        self.assertEqual(self.entries(), [])

    def test_text_and_exact_photo_preview_survive_new_process(self):
        photo = io.BytesIO()
        Image.new('RGB', (80, 60), '#777777').save(photo, 'PNG')
        data_url = 'data:image/png;base64,' + base64.b64encode(photo.getvalue()).decode()
        with patch.object(printer_app, 'ble_print_raster_ticket') as printer:
            text = self.client.post('/print', json={'content': 'Remember this', 'include_date': False})
            image = self.client.post('/print', json={'type': 'image', 'content': data_url, 'caption': 'My photo'})
        self.assertEqual(printer.call_count, 2)
        entries = self.entries()
        self.assertEqual([entry['id'] for entry in entries], [text.json['history_id'], image.json['history_id']])
        self.assertEqual([entry['status'] for entry in entries], ['printed', 'printed'])
        self.assertEqual(entries[0]['text'], 'Remember this')
        self.assertEqual(entries[1]['text'], 'My photo')
        self.assertEqual(entries[1]['preview'], image.json['preview'])
        self.assertTrue(entries[0]['created_at'].endswith('+00:00'))
        # A fresh interpreter must recover the same file without printing anything.
        result = subprocess.check_output([sys.executable, '-c',
            'import json, sys; from print_history import PrintHistory; '
            'print(json.dumps(PrintHistory(sys.argv[1]).page()))', str(self.path)], text=True)
        import json
        self.assertEqual(json.loads(result)['entries'], entries)

    def test_failed_attempt_and_test_preview_are_never_marked_printed(self):
        with patch.object(printer_app, 'ble_print_raster_ticket', side_effect=RuntimeError('Disconnected')):
            self.assertEqual(self.client.post('/print', json={'content': 'Keep this too'}).status_code, 500)
        with patch.object(printer_app, 'TEST_MODE', True), patch.object(printer_app, 'ble_print_raster_ticket') as printer:
            self.assertEqual(self.client.post('/print', json={'content': 'Preview only'}).status_code, 200)
            printer.assert_not_called()
        failed, preview = self.entries()
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['text'], 'Keep this too')
        self.assertEqual(failed['error'], 'Disconnected')
        self.assertEqual(preview['status'], 'test_mode')

    def test_invalid_request_is_not_added(self):
        self.assertEqual(self.client.post('/print', json={'content': ''}).status_code, 400)
        self.assertEqual(self.entries(), [])

    def test_legacy_and_live_prints_are_saved_and_live_reports_history_id(self):
        with patch.object(printer_app, 'ble_print_text'):
            legacy = self.client.post('/submit_ticket', json={'from_name': 'Sam', 'question': 'A question'})
            queue = LivePrintQueue(lambda text: printer_app.print_text_content(text, return_history=True), threading.Event())
            queue.enqueue('Spoken words')
            queue.finish()
            queue.wait()
        entries = self.entries()
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual([entry['source'] for entry in entries], ['ticket', 'listening'])
        self.assertEqual(entries[1]['text'], 'Spoken words')
        self.assertEqual(queue.snapshot()['recent_jobs'][0]['history_id'], entries[1]['id'])

    def test_keyset_pagination_has_no_duplicates_when_new_prints_arrive(self):
        for n in range(5):
            with self.history.record(source='chat', text=str(n)):
                pass
        first = self.client.get('/history?limit=2').json
        self.assertEqual([entry['text'] for entry in first['entries']], ['3', '4'])
        with self.history.record(source='chat', text='new'):
            pass
        second = self.client.get(f"/history?limit=2&before={first['next_before']}").json
        third = self.client.get(f"/history?limit=2&before={second['next_before']}").json
        self.assertEqual([entry['text'] for entry in second['entries']], ['1', '2'])
        self.assertEqual([entry['text'] for entry in third['entries']], ['0'])
        self.assertIsNone(third['next_before'])
        for query in ['limit=0', 'limit=101', 'limit=x', 'before=-1', 'before=0', 'before=no', 'before=99999999999999999999']:
            self.assertEqual(self.client.get('/history?' + query).status_code, 400)

    def test_initial_storage_failure_prevents_printing(self):
        with patch.object(self.history, 'connection', side_effect=sqlite3.OperationalError('Disk full')), \
                patch.object(printer_app, 'ble_print_raster_ticket') as printer:
            self.assertEqual(self.client.post('/print', json={'content': 'Do not lose me'}).status_code, 500)
            printer.assert_not_called()
            self.assertEqual(self.client.get('/history').status_code, 503)

    def test_lost_status_update_preserves_unconfirmed_content_without_retry(self):
        def lose_storage(*_):
            # This occurs after the initial durable insert and hardware operation.
            setting = patch.object(self.history, 'connection', side_effect=sqlite3.OperationalError('Disk full'))
            setting.start()
            self.addCleanup(setting.stop)

        with patch.object(printer_app, 'ble_print_raster_ticket', side_effect=lose_storage) as printer:
            response = self.client.post('/print', json={'content': 'Already sent'})
        self.assertEqual(response.status_code, 200)
        printer.assert_called_once()
        entries = PrintHistory(self.path).page()['entries']
        self.assertEqual(entries[0]['status'], 'unconfirmed')
        self.assertEqual(entries[0]['text'], 'Already sent')

    def test_history_read_does_not_wait_for_printer_lock(self):
        with patch.object(printer_app, '_printer_worker') as worker:
            self.entries()
            worker.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
