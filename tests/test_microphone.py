import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask

from microphone import Microphone, MicrophoneError, create_microphone_blueprint


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.mic = Microphone(enabled=True, model_path=self.directory.name)
        self.opened = threading.Event()
        self.closed = threading.Event()
        self.chunks = [b'first', b'partial']
        self.audio_status = False
        test = self

        class Stream:
            active = True

            def __init__(self, **kwargs):
                self.callback = kwargs['callback']

            def __enter__(self):
                test.opened.set()
                for chunk in test.chunks:
                    try:
                        self.callback(chunk, 4000, None, test.audio_status)
                    except (StopIteration, RuntimeError):
                        self.active = False
                        break
                return self

            def __exit__(self, *args):
                self.active = False
                test.closed.set()

        recognizer = Mock()
        recognizer.AcceptWaveform.side_effect = lambda data: data == b'first'
        recognizer.Result.return_value = json.dumps({'text': 'hello'})
        recognizer.PartialResult.return_value = json.dumps({'partial': 'print'})
        recognizer.FinalResult.return_value = json.dumps({'text': 'printer'})
        self.sd = SimpleNamespace(
            query_devices=Mock(return_value={'default_samplerate': 48000}),
            check_input_settings=Mock(), RawInputStream=Mock(side_effect=Stream),
            CallbackStop=StopIteration, CallbackAbort=RuntimeError,
        )
        self.vosk = SimpleNamespace(Model=Mock(return_value=object()), KaldiRecognizer=Mock(return_value=recognizer))
        self.modules = patch.dict('sys.modules', sounddevice=self.sd, vosk=self.vosk)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(self.finish_worker)

    def finish_worker(self):
        for session in self.mic._sessions.values():
            session['stop'].set()
        if self.mic._thread:
            self.mic._thread.join(timeout=2)
            self.assertFalse(self.mic._thread.is_alive())

    def result(self, session):
        self.mic._thread.join(timeout=2)
        self.assertFalse(self.mic._thread.is_alive())
        return self.mic.status(session['id'])

    def test_stop_finalizes_transcript_and_closes_audio(self):
        session = self.mic.start()
        self.assertTrue(self.opened.wait(1))
        self.mic.stop(session['id'])
        result = self.result(session)
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['text'], 'hello printer')
        self.assertTrue(self.closed.is_set())
        self.sd.check_input_settings.assert_called_once_with(
            device='Samson', channels=1, dtype='int16', samplerate=48000)
        self.vosk.KaldiRecognizer.assert_called_once_with(self.mic._model, 48000)

    def test_connection_status_probes_device_without_recording(self):
        self.sd.query_devices.return_value = {'max_input_channels': 1}
        self.assertTrue(self.mic.connected())
        self.sd.query_devices.assert_called_once_with('Samson', 'input')
        self.sd.RawInputStream.assert_not_called()
        self.sd.query_devices.side_effect = RuntimeError('Unplugged')
        self.assertFalse(self.mic.connected())
        self.mic.enabled = False
        self.sd.query_devices.reset_mock()
        self.assertFalse(self.mic.connected())
        self.sd.query_devices.assert_not_called()

    def test_recording_stops_without_browser_polling(self):
        with patch('microphone.MAX_SECONDS', 0.03):
            session = self.mic.start()
            result = self.result(session)
        self.assertEqual(result['state'], 'done')
        self.assertTrue(self.closed.is_set())

    def test_second_recording_is_rejected_while_busy(self):
        session = self.mic.start()
        self.assertTrue(self.opened.wait(1))
        with self.assertRaises(MicrophoneError) as error:
            self.mic.start()
        self.assertEqual(error.exception.status, 409)
        self.mic.stop(session['id'])

    def test_silence_produces_empty_transcript(self):
        self.chunks = []
        self.vosk.KaldiRecognizer.return_value.FinalResult.return_value = '{"text":""}'
        with patch('microphone.MAX_SECONDS', 0.03):
            result = self.result(self.mic.start())
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['text'], '')

    def test_capture_failure_releases_microphone_for_retry(self):
        self.audio_status = True
        result = self.result(self.mic.start())
        self.assertEqual(result['state'], 'error')
        self.assertTrue(self.closed.is_set())
        self.audio_status = False
        with patch('microphone.MAX_SECONDS', 0.03):
            self.assertEqual(self.result(self.mic.start())['state'], 'done')

    def test_missing_device_does_not_open_stream(self):
        self.sd.query_devices.side_effect = ValueError('No matching device')
        result = self.result(self.mic.start())
        self.assertEqual(result['state'], 'error')
        self.assertIn('MICROPHONE_DEVICE', result['error'])
        self.sd.RawInputStream.assert_not_called()

    def test_missing_model_does_not_open_stream(self):
        self.mic.model_path = self.mic.model_path / 'missing'
        result = self.result(self.mic.start())
        self.assertEqual(result['state'], 'error')
        self.assertIn('model is missing', result['error'])
        self.sd.RawInputStream.assert_not_called()

    def test_missing_optional_packages_gives_setup_instruction(self):
        with patch.dict('sys.modules', sounddevice=None):
            result = self.result(self.mic.start())
        self.assertIn('requirements-microphone.txt', result['error'])

    def test_stop_during_model_load_does_not_start_recording(self):
        loading = threading.Event()
        release = threading.Event()

        def load_model(path):
            loading.set()
            release.wait(1)
            return object()

        self.vosk.Model.side_effect = load_model
        session = self.mic.start()
        self.assertTrue(loading.wait(1))
        self.mic.stop(session['id'])
        release.set()
        self.assertEqual(self.result(session)['state'], 'done')
        self.sd.RawInputStream.assert_not_called()

    def test_old_transcript_survives_next_recording(self):
        with patch('microphone.MAX_SECONDS', 0.03):
            first = self.result(self.mic.start())
            second = self.result(self.mic.start())
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(self.mic.status(first['id'])['text'], 'hello printer')
        self.vosk.Model.assert_called_once()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.mic = Microphone()
        app = Flask(__name__)
        app.register_blueprint(create_microphone_blueprint(self.mic, {'https://printer.example'}))
        self.client = app.test_client()

    def test_disabled_install_keeps_optional_audio_packages_unnecessary(self):
        self.assertFalse(self.client.get('/microphone').json['enabled'])
        result = self.client.post('/microphone/start', json={})
        self.assertEqual(result.status_code, 503)

    def test_foreign_origin_cannot_start_read_or_stop_recording(self):
        for path, method in [('/microphone/start', 'POST'), ('/microphone/secret', 'GET'),
                             ('/microphone/secret/stop', 'POST')]:
            response = self.client.open(path, method=method, json={}, headers={'Origin': 'https://untrusted.example'})
            self.assertEqual(response.status_code, 403)

    def test_same_and_explicit_origins_are_allowed(self):
        for origin in ['http://localhost', 'https://printer.example']:
            self.assertEqual(self.client.get('/microphone', headers={'Origin': origin}).status_code, 200)

    def test_start_requires_json(self):
        self.assertEqual(self.client.post('/microphone/start').status_code, 415)

    def test_unknown_recordings_do_not_leak_results(self):
        self.assertEqual(self.client.get('/microphone/unknown').status_code, 404)
        self.assertEqual(self.client.post('/microphone/unknown/stop', json={}).status_code, 404)

    def test_responses_are_not_cached(self):
        self.assertEqual(self.client.get('/microphone').headers['Cache-Control'], 'no-store')

    def test_live_responses_identify_test_mode_without_touching_hardware(self):
        app = Flask(__name__)
        app.register_blueprint(create_microphone_blueprint(self.mic, test_mode=True))
        client = app.test_client()
        session = {'id': 'example', 'state': 'recording', 'mode': 'live'}
        with patch.object(self.mic, 'start_live', return_value=session), \
                patch.object(self.mic, 'live_status', return_value=session), \
                patch.object(self.mic, 'status', return_value=session), \
                patch.object(self.mic, 'stop', return_value=session):
            for path, method in [('/microphone', 'GET'), ('/microphone/live', 'GET'),
                                 ('/microphone/example', 'GET'), ('/microphone/live/start', 'POST'),
                                 ('/microphone/live/example/stop', 'POST')]:
                self.assertTrue(client.open(path, method=method, json={}).json['test_mode'])

    def test_start_does_not_print_and_reviewed_text_uses_existing_print_route(self):
        import app as printer_app

        client = printer_app.app.test_client()
        with patch.object(Microphone, 'start', return_value={
            'id': 'test', 'state': 'done', 'text': 'hello printer', 'error': None
        }), patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', 'test-printer'), \
                patch.object(printer_app, 'TEST_MODE', False), \
                patch.object(printer_app, 'ble_print_raster_ticket') as print_text:
            self.assertEqual(client.post('/microphone/start', json={}).status_code, 202)
            print_text.assert_not_called()
            response = client.post('/print', json={'type': 'text', 'content': 'Edited speech'})
            self.assertEqual(response.status_code, 200)
            print_text.assert_called_once()
            self.assertIn('Edited speech', response.json['preview']['text'])


if __name__ == '__main__':
    unittest.main()
