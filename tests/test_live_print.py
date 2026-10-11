import json
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from flask import Flask

from live_print import LivePrintError, LivePrintQueue, MAX_PENDING_JOBS
from microphone import Microphone, MicrophoneError, create_microphone_blueprint


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.005)
    raise AssertionError('Timed out waiting for worker')


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.release = threading.Event()
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.printed = []
        self.failure = False

        def print_text(text):
            self.started.set()
            if not self.release.wait(2):
                raise RuntimeError('Test did not release printer')
            if self.failure:
                raise RuntimeError('Printer disconnected')
            self.printed.append(text)

        self.queue = LivePrintQueue(print_text, self.stopped)
        self.addCleanup(self.finish)

    def finish(self):
        self.release.set()
        self.queue.cancel()
        self.queue._thread.join(2)
        self.assertFalse(self.queue._thread.is_alive())

    def test_finish_drains_once_in_order_and_skips_empty_windows(self):
        self.assertFalse(self.queue.enqueue('  '))
        for text in [' first ', 'second', 'second']:
            self.queue.enqueue(text)
        self.queue.finish()
        self.release.set()
        self.queue.wait()
        self.assertEqual(self.printed, ['first', 'second', 'second'])
        self.assertEqual(self.queue.snapshot()['printed_count'], 3)

    def test_cancel_discards_waiting_jobs_but_allows_inflight_job_to_finish(self):
        self.queue.enqueue('in flight')
        self.assertTrue(self.started.wait(1))
        self.queue.enqueue('waiting')
        self.queue.cancel()
        self.assertFalse(self.queue.enqueue('after stop'))
        self.release.set()
        self.queue.wait()
        self.assertEqual(self.printed, ['in flight'])
        status = self.queue.snapshot()
        self.assertEqual(status['cancelled_count'], 1)
        self.assertEqual(status['queue_depth'], 0)
        self.assertIsNone(status['printing'])

    def test_failure_stops_recording_cancels_queue_and_does_not_retry(self):
        self.failure = True
        self.queue.enqueue('failed text')
        self.assertTrue(self.started.wait(1))
        self.queue.enqueue('waiting')
        self.release.set()
        self.assertTrue(self.stopped.wait(1))
        self.queue.wait()
        status = self.queue.snapshot()
        self.assertEqual(status['failed_job']['text'], 'failed text')
        self.assertEqual(status['failed_job']['error'], 'Printer disconnected')
        self.assertEqual(status['printed_count'], 0)
        self.assertEqual(status['cancelled_count'], 1)
        self.assertEqual(len(status['recent_jobs']), 2)

    def test_backpressure_is_bounded(self):
        self.queue.enqueue('in flight')
        self.assertTrue(self.started.wait(1))
        for index in range(MAX_PENDING_JOBS):
            self.queue.enqueue(str(index))
        with self.assertRaisesRegex(LivePrintError, 'queue is full'):
            self.queue.enqueue('overflow')
        self.assertEqual(self.queue.snapshot()['queue_depth'], MAX_PENDING_JOBS)

    def test_long_session_retains_only_recent_history(self):
        self.release.set()
        for index in range(25):
            self.queue.enqueue(str(index))
            wait_until(lambda: self.queue.snapshot()['printed_count'] == index + 1)
        self.queue.finish()
        self.queue.wait()
        status = self.queue.snapshot()
        self.assertEqual(status['printed_count'], 25)
        self.assertEqual(len(status['recent_jobs']), 20)
        self.assertEqual(status['recent_jobs'][0]['text'], '5')


class LiveRecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.print_text = Mock()
        self.first_print_options = dict(include_date=True, include_separator=True, continuous=True)
        self.next_print_options = dict(include_date=False, include_separator=False, continuous=True)
        self.mic = Microphone(enabled=True, model_path=self.directory.name, print_text=self.print_text)
        self.opened = threading.Event()
        self.closed = threading.Event()
        test = self

        class Stream:
            active = True

            def __init__(self, **kwargs):
                test.capture = kwargs['callback']

            def __enter__(self):
                test.opened.set()
                return self

            def __exit__(self, *args):
                self.active = False
                test.closed.set()

        class Recognizer:
            def __init__(self, model, sample_rate):
                self.pending = ''
                self.completed = ''

            def AcceptWaveform(self, data):
                kind, text = data.decode().split(':', 1)
                if kind == 'final':
                    self.completed = text
                    self.pending = ''
                    return True
                self.pending = text
                return False

            def Result(self):
                return json.dumps({'text': self.completed})

            def PartialResult(self):
                return json.dumps({'partial': 'draft ' + self.pending if self.pending else ''})

            def FinalResult(self):
                text = self.pending
                self.pending = ''
                return json.dumps({'text': text})

            def Reset(self):
                self.pending = self.completed = ''

        self.sd = SimpleNamespace(
            query_devices=Mock(return_value={'default_samplerate': 8000}),
            check_input_settings=Mock(), RawInputStream=Mock(side_effect=Stream),
            CallbackStop=StopIteration, CallbackAbort=RuntimeError,
        )
        self.vosk = SimpleNamespace(Model=Mock(return_value=object()), KaldiRecognizer=Mock(side_effect=Recognizer))
        modules = patch.dict('sys.modules', sounddevice=self.sd, vosk=self.vosk)
        modules.start()
        self.addCleanup(modules.stop)
        self.addCleanup(self.finish)
        app = Flask(__name__)
        app.register_blueprint(create_microphone_blueprint(self.mic))
        self.client = app.test_client()

    def finish(self):
        for session_id in list(self.mic._sessions):
            self.mic.stop(session_id)
        if self.mic._thread:
            self.mic._thread.join(2)
            self.assertFalse(self.mic._thread.is_alive())
        for session in self.mic._sessions.values():
            if 'live' in session:
                self.assertFalse(session['live']._thread.is_alive())

    def start(self, **options):
        self.session = self.mic.start_live(**options)
        self.assertTrue(self.opened.wait(1))
        wait_until(lambda: self.mic.status(self.session['id'])['state'] == 'recording')
        return self.session

    def result(self):
        self.mic._thread.join(2)
        self.assertFalse(self.mic._thread.is_alive())
        return self.mic.status(self.session['id'])

    def send(self, data, frames=8000):
        self.capture(data, frames, None, False)

    def test_cadence_prints_final_text_once_per_window_without_partial_hypotheses(self):
        self.start(cadence_seconds=1)
        self.send(b'final:first phrase', frames=4000)
        wait_until(lambda: self.mic.live_status()['text'] == 'first phrase')
        self.print_text.assert_not_called()
        self.send(b'partial:second phrase', frames=4000)
        wait_until(lambda: self.mic.live_status()['printed_count'] == 1)
        self.send(b'partial:third phrase')
        wait_until(lambda: self.mic.live_status()['printed_count'] == 2)
        self.mic.stop(self.session['id'], flush=True)
        self.assertEqual(self.result()['state'], 'done')
        self.assertEqual(self.print_text.call_args_list, [
            call('first phrase second phrase', **self.first_print_options),
            call('third phrase', **self.next_print_options)])

    def test_manual_stop_preserves_unprinted_final_text_by_default(self):
        self.start(cadence_seconds=10)
        self.send(b'partial:keep this')
        wait_until(lambda: bool(self.mic.live_status()['text']))
        self.mic.stop(self.session['id'])
        result = self.result()
        self.assertEqual(result['text'], 'keep this')
        self.assertEqual(result['stop_reason'], 'manual')
        self.assertEqual(result['state'], 'done')
        self.assertTrue(self.closed.is_set())
        self.print_text.assert_not_called()

    def test_manual_stop_can_flush_last_window(self):
        self.start(cadence_seconds=10)
        self.send(b'partial:print the remainder')
        wait_until(lambda: bool(self.mic.live_status()['text']))
        self.mic.stop(self.session['id'], flush=True)
        self.assertEqual(self.result()['printed_count'], 1)
        self.print_text.assert_called_once_with('print the remainder', **self.first_print_options)

    def test_duration_stops_and_flushes_without_any_polling(self):
        self.start(cadence_seconds=10, duration_seconds=1)
        self.send(b'partial:timed session')
        result = self.result()
        self.assertEqual(result['stop_reason'], 'duration')
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['seconds'], 1)
        self.assertTrue(self.closed.is_set())
        self.print_text.assert_called_once_with('timed session', **self.first_print_options)

    def test_indefinite_mode_has_no_review_deadline(self):
        with patch('microphone.threading.Timer') as timer:
            self.start()
            timer.assert_not_called()
            self.assertIsNone(self.mic.live_status()['max_seconds'])
            self.mic.stop(self.session['id'])
            self.result()

    def test_silence_does_not_print(self):
        self.start(cadence_seconds=1)
        self.send(b'partial:')
        self.mic.stop(self.session['id'], flush=True)
        self.assertEqual(self.result()['printed_count'], 0)
        self.print_text.assert_not_called()

    def test_local_backend_sound_labels_use_the_existing_print_queue(self):
        self.mic._listening_models = SimpleNamespace(create_recognizer=lambda rate:
            self.vosk.KaldiRecognizer(None, rate))
        self.start(cadence_seconds=1)
        self.send(b'partial:[dog barking]')
        wait_until(lambda: self.mic.live_status()['printed_count'] == 1)
        self.mic.stop(self.session['id'])
        result = self.result()
        self.assertEqual(result['state'], 'done')
        self.print_text.assert_called_once_with('[dog barking]', **self.first_print_options)

    def test_input_overflow_continues_live_printing_without_replaying_a_ticket(self):
        self.start(cadence_seconds=1)
        self.send(b'partial:first ticket')
        wait_until(lambda: self.mic.live_status()['printed_count'] == 1)
        self.capture(b'partial:second ticket', 8000, None, SimpleNamespace(input_overflow=True))
        wait_until(lambda: self.mic.live_status()['printed_count'] == 2)
        status = self.mic.live_status()
        self.assertEqual(status['state'], 'recording')
        self.assertEqual(status['audio_overflows'], 1)
        self.assertIn('Some audio was missed', status['warning'])
        self.mic.stop(self.session['id'])
        self.assertEqual(self.result()['state'], 'done')
        self.assertEqual(self.print_text.call_args_list, [
            call('first ticket', **self.first_print_options),
            call('second ticket', **self.next_print_options)])

    def test_printer_failure_stops_audio_and_reports_failed_text(self):
        self.print_text.side_effect = RuntimeError('No paper')
        self.start(cadence_seconds=1)
        self.send(b'partial:failed ticket')
        result = self.result()
        self.assertEqual(result['state'], 'error')
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['failed_job']['text'], 'failed ticket')
        self.assertEqual(result['failed_job']['error'], 'No paper')
        self.assertTrue(self.closed.is_set())
        self.print_text.assert_called_once()

    def test_slow_printer_does_not_block_audio_and_manual_stop_cancels_backlog(self):
        release = threading.Event()
        printing = threading.Event()

        def slow_print(text, **options):
            printing.set()
            if not release.wait(2):
                raise RuntimeError('Test printer timed out')

        self.print_text.side_effect = slow_print
        self.start(cadence_seconds=1)
        try:
            self.send(b'partial:in flight')
            self.assertTrue(printing.wait(1))
            self.send(b'partial:waiting')
            wait_until(lambda: self.mic.live_status()['queue_depth'] == 1)
            self.send(b'partial:buffered', frames=4000)
            wait_until(lambda: self.mic.live_status()['text'] == 'draft buffered')
            status = self.mic.stop(self.session['id'])
            self.assertEqual(status['state'], 'stopping')
            self.assertEqual(status['cancelled_count'], 1)
            self.assertEqual(status['queue_depth'], 0)
            self.assertTrue(self.closed.wait(1))
            # A repeated stop cannot restore cancelled work, and the printer still owns the session.
            self.assertFalse(self.mic.stop(self.session['id'], flush=True)['flush_on_stop'])
            with self.assertRaises(MicrophoneError) as raised:
                self.mic.start_live()
            self.assertEqual(raised.exception.status, 409)
        finally:
            release.set()
        result = self.result()
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['text'], 'buffered')
        self.print_text.assert_called_once_with('in flight', **self.first_print_options)

    def test_full_print_queue_stops_capture_and_preserves_overflow_text(self):
        release = threading.Event()
        printing = threading.Event()

        def slow_print(text, **options):
            printing.set()
            if not release.wait(2):
                raise RuntimeError('Test printer timed out')

        self.print_text.side_effect = slow_print
        with patch('live_print.MAX_PENDING_JOBS', 1):
            self.start(cadence_seconds=1)
            try:
                self.send(b'partial:in flight')
                self.assertTrue(printing.wait(1))
                self.send(b'partial:waiting')
                wait_until(lambda: self.mic.live_status()['queue_depth'] == 1)
                self.send(b'partial:overflow text')
                wait_until(lambda: self.mic.live_status()['state'] == 'error')
                self.assertTrue(self.closed.wait(1))
            finally:
                release.set()
            result = self.result()
        self.assertIn('queue is full', result['error'])
        self.assertEqual(result['text'], 'overflow text')
        self.assertEqual(result['cancelled_count'], 1)
        self.print_text.assert_called_once_with('in flight', **self.first_print_options)

    def test_missing_microphone_closes_queue_and_allows_restart(self):
        self.sd.query_devices.side_effect = ValueError('Disconnected')
        self.session = self.mic.start_live()
        self.assertEqual(self.result()['state'], 'error')
        self.assertFalse(self.mic._sessions[self.session['id']]['live']._thread.is_alive())
        self.sd.query_devices.side_effect = None
        self.start()
        self.mic.stop(self.session['id'])
        self.assertEqual(self.result()['state'], 'done')

    def test_live_and_review_modes_share_exclusive_access(self):
        self.start()
        for start in [self.mic.start, self.mic.start_live]:
            with self.assertRaises(MicrophoneError) as raised:
                start()
            self.assertEqual(raised.exception.status, 409)
        self.mic.stop(self.session['id'])
        self.result()
        self.session = self.mic.start()
        with self.assertRaises(MicrophoneError) as raised:
            self.mic.start_live()
        self.assertEqual(raised.exception.status, 409)

    def test_api_start_recover_status_and_stop_with_flush(self):
        self.assertEqual(self.client.get('/microphone/live').json['state'], 'idle')
        response = self.client.post('/microphone/live/start', json={'cadence_seconds': 5, 'duration_seconds': 90})
        self.assertEqual(response.status_code, 202)
        self.session = response.json
        self.assertTrue(self.opened.wait(1))
        self.send(b'partial:through the API')
        wait_until(lambda: bool(self.mic.live_status()['text']))
        status = self.client.get('/microphone/live').json
        self.assertEqual(status['id'], self.session['id'])
        self.assertEqual(status['cadence_seconds'], 5)
        self.assertEqual(status['duration_seconds'], 90)
        self.assertEqual(self.client.get('/microphone/' + status['id']).json['mode'], 'live')
        stop = self.client.post('/microphone/live/' + status['id'] + '/stop', json={'flush': True})
        self.assertEqual(stop.status_code, 202)
        self.assertEqual(self.result()['state'], 'done')
        self.print_text.assert_called_once_with('through the API', **self.first_print_options)
        self.assertEqual(self.client.get('/microphone/live').json['state'], 'done')

    def test_legacy_stop_also_safely_stops_live_mode(self):
        self.start()
        self.send(b'partial:do not print')
        wait_until(lambda: bool(self.mic.live_status()['text']))
        response = self.client.post('/microphone/' + self.session['id'] + '/stop', json={})
        self.assertEqual(response.status_code, 200)
        self.result()
        self.print_text.assert_not_called()

    def test_live_api_passes_date_preference_to_print_worker(self):
        response = self.client.post('/microphone/live/start', json={'include_date': False})
        self.assertEqual(response.status_code, 202)
        self.session = response.json
        self.assertTrue(self.opened.wait(1))
        self.send(b'partial:no timestamp')
        wait_until(lambda: bool(self.mic.live_status()['text']))
        self.mic.stop(self.session['id'], flush=True)
        self.assertEqual(self.result()['printed_count'], 1)
        self.print_text.assert_called_once_with('no timestamp', include_date=False,
                                                include_separator=True, continuous=True)

    def test_invalid_start_options_never_open_microphone(self):
        cases = [[], {'unknown': 1}, {'cadence_seconds': None}]
        cases += [{'include_date': value} for value in [None, 'false', 0, 1, []]]
        for field, maximum in [('cadence_seconds', 300), ('duration_seconds', 86400)]:
            cases += [{field: value} for value in [0, -1, maximum + 1, True, False, '10', 1.5]]
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.client.post('/microphone/live/start', json=data).status_code, 400)
        response = self.client.post('/microphone/live/start', data='{', content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.sd.RawInputStream.assert_not_called()
        self.assertIsNone(self.mic._thread)

    def test_invalid_stop_options_do_not_stop_session(self):
        self.start()
        path = '/microphone/live/' + self.session['id'] + '/stop'
        for data in [[], {'flush': 'false'}, {'flush': 1}, {'flush': None}, {'unknown': True}]:
            self.assertEqual(self.client.post(path, json=data).status_code, 400)
        self.assertEqual(self.mic.live_status()['state'], 'recording')

    def test_live_routes_require_allowed_origin_and_json_and_disable_caching(self):
        for path, method in [('/microphone/live', 'GET'), ('/microphone/live/start', 'POST'),
                             ('/microphone/live/unknown/stop', 'POST')]:
            response = self.client.open(path, method=method, json={}, headers={'Origin': 'https://foreign.test'})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.post('/microphone/live/start').status_code, 415)
        self.assertEqual(self.client.get('/microphone/live').headers['Cache-Control'], 'no-store')

    def test_disabled_and_unconfigured_live_modes_return_unavailable(self):
        self.mic.enabled = False
        self.assertEqual(self.client.post('/microphone/live/start', json={}).status_code, 503)
        self.mic.enabled = True
        self.mic._print_text = None
        self.assertEqual(self.client.post('/microphone/live/start', json={}).status_code, 503)
        self.sd.RawInputStream.assert_not_called()


if __name__ == '__main__':
    unittest.main()
