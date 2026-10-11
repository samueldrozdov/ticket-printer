import json
import math
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

try:
    import numpy as np
except ImportError:
    np = None

from listening_models import LocalListeningModels, LocalRecognizer, ListeningModelError, SoundEvents


class SoundEventTests(unittest.TestCase):
    def test_bark_synonyms_become_one_label_and_generic_animal_scores_do_not_print(self):
        detector = SoundEvents()
        self.assertEqual(detector.update([('Animal', .99), ('Dog', .99)], 0), [])
        self.assertEqual(detector.update([('Bark', .91), ('Bow-wow', .8)], 2), ['dog barking'])
        self.assertEqual(detector.update([('Bark', .98)], 4), [])

    def test_continuous_sound_does_not_repeat_and_new_burst_rearms_after_silence(self):
        detector = SoundEvents()
        self.assertEqual(detector.update([('Bark', .9)], 0), ['dog barking'])
        self.assertEqual(detector.update([('Bark', .9)], 30), [])
        self.assertEqual(detector.update([], 32), [])
        self.assertEqual(detector.update([], 34), [])
        self.assertEqual(detector.update([('Bark', .9)], 36), ['dog barking'])

    def test_cooldown_survives_brief_silence_and_low_confidence_is_ignored(self):
        detector = SoundEvents()
        detector.update([('Bark', .9)], 0)
        detector.update([], 2)
        detector.update([], 4)
        self.assertEqual(detector.update([('Bark', .9), ('Meow', .3)], 6), [])
        self.assertEqual(detector.update([('Meow', .9)], 8), ['cat meowing'])
        self.assertEqual(detector.update([('Cough', math.nan), ('Siren', 2)], 10), [])

    def test_invalid_confidence_fails_early(self):
        for value in (0, 1.1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                SoundEvents(value)


@unittest.skipIf(np is None, 'Install requirements-listening.txt to test audio processing.')
class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.speech = ''
        self.tags = [('Bark', .9)]
        self.asr_chunks, self.sound_chunks = [], []
        test = self

        class Stream:
            def accept_waveform(self, rate, samples):
                test.asr_chunks.append((rate, np.asarray(samples).copy()))

            def input_finished(self):
                pass

        class TagStream:
            def accept_waveform(self, rate, samples):
                test.sound_chunks.append((rate, np.asarray(samples).copy()))

        self.asr = SimpleNamespace(create_stream=Stream, is_ready=lambda s: False,
            is_endpoint=lambda s: False, get_result=lambda s: test.speech, reset=Mock())
        self.models = SimpleNamespace(np=np, asr=self.asr,
            tagger=SimpleNamespace(create_stream=TagStream,
                compute=lambda s: [SimpleNamespace(name=n, prob=p) for n,p in test.tags]),
            sound_threshold=.6, denoiser=lambda: None)

    def audio(self, seconds, rate=16000):
        return np.full(int(rate*seconds), 1000, dtype=np.int16).tobytes()

    def test_sound_only_input_finalizes_as_a_printable_label_once(self):
        recognizer = LocalRecognizer(self.models, 16000)
        recognizer.AcceptWaveform(self.audio(5))
        self.assertIn('[dog barking]', json.loads(recognizer.PartialResult())['partial'])
        result = json.loads(recognizer.FinalResult())['text']
        self.assertEqual(result, '[dog barking]')
        self.assertEqual(json.loads(recognizer.FinalResult())['text'], result)
        self.assertTrue(all(len(data) <= 32000 for rate,data in self.sound_chunks))
        recognizer.Reset()
        recognizer.AcceptWaveform(self.audio(3))
        self.assertEqual(json.loads(recognizer.FinalResult())['text'], '')

    def test_sound_branch_receives_raw_audio_even_when_speech_is_cleaned(self):
        cleaner = SimpleNamespace(sample_rate=16000,
            flush=lambda: SimpleNamespace(samples=np.zeros(0), sample_rate=16000))
        class Cleaner:
            sample_rate = 16000
            def __call__(self, samples, rate):
                return SimpleNamespace(samples=np.zeros(len(samples)), sample_rate=16000)
            flush = staticmethod(cleaner.flush)
        self.models.denoiser = Cleaner
        recognizer = LocalRecognizer(self.models, 16000)
        recognizer.AcceptWaveform(self.audio(2))
        self.assertTrue(np.max(self.sound_chunks[0][1]) > 0)
        self.assertTrue(np.max(self.asr_chunks[0][1]) == 0)
        self.assertEqual(json.loads(recognizer.FinalResult())['text'], '[dog barking]')

    def test_speech_and_labels_are_combined_without_repeating_endpoint_text(self):
        recognizer = LocalRecognizer(self.models, 16000)
        self.speech = 'HELLO THERE'
        recognizer.AcceptWaveform(self.audio(2))
        self.assertEqual(json.loads(recognizer.Result())['text'], 'hello there\n[dog barking]')
        self.asr.reset.assert_called_once()
        self.speech = 'GOOD MORNING'
        self.assertEqual(json.loads(recognizer.FinalResult())['text'], 'good morning')

    def test_native_rate_is_kept_for_asr_tail_and_classifier(self):
        recognizer = LocalRecognizer(self.models, 48000)
        recognizer.AcceptWaveform(self.audio(.1, 48000))
        recognizer.FinalResult()
        self.assertTrue(all(rate == 48000 for rate,data in self.asr_chunks + self.sound_chunks))
        self.assertEqual(len(self.asr_chunks[-1][1]), 24000)

    def test_digital_silence_has_no_labels_or_sound_inference(self):
        recognizer = LocalRecognizer(self.models, 16000)
        recognizer.AcceptWaveform(np.zeros(160000, dtype=np.int16).tobytes())
        self.assertEqual(json.loads(recognizer.FinalResult())['text'], '')
        self.assertEqual(self.sound_chunks, [])

    def test_short_final_sound_windows_are_padded_without_changing_speech_input(self):
        self.speech = 'Words already recognized'
        for rate in (16000, 44100, 48000):
            for duration in (.001, .025, .091, .9):
                with self.subTest(rate=rate, duration=duration):
                    self.asr_chunks.clear()
                    self.sound_chunks.clear()
                    recognizer = LocalRecognizer(self.models, rate)
                    data = self.audio(duration, rate)
                    recognizer.AcceptWaveform(data)
                    result = json.loads(recognizer.FinalResult())['text']
                    self.assertIn('words already recognized', result)
                    self.assertEqual(len(self.sound_chunks), 1)
                    sound = self.sound_chunks[0][1]
                    frames = len(data) // 2
                    self.assertEqual(len(sound), rate * 2)
                    np.testing.assert_array_equal(sound[:frames], self.asr_chunks[0][1])
                    self.assertTrue(np.all(sound[frames:] == 0))
                    recognizer.FinalResult()
                    self.assertEqual(len(self.sound_chunks), 1)

    def test_missing_weights_are_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            models = LocalListeningModels(directory)
            with self.assertRaisesRegex(ListeningModelError, 'install_listening_models.py'):
                models._file('missing.onnx')


if __name__ == '__main__':
    unittest.main()
