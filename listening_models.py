"""Local streaming speech recognition and conservative environmental sound labels.

Model inference never opens a network connection. Sound classification uses the
original microphone input; optional speech enhancement only feeds the ASR branch.
The session interface matches Vosk so both backends share capture/stop/print rules.
"""

import json
import math
from pathlib import Path


SPEECH_MODEL = 'sherpa-onnx-streaming-zipformer-en-2023-06-21'
SOUND_MODEL = 'sherpa-onnx-zipformer-small-audio-tagging-2024-04-15'
SOUND_WINDOW_SECONDS = 2
SOUND_LABELS = {
    'Bark': 'dog barking', 'Bow-wow': 'dog barking', 'Howl': 'dog howling',
    'Meow': 'cat meowing', 'Purr': 'cat purring',
    'Chirp, tweet': 'birds chirping', 'Laughter': 'laughter',
    'Cough': 'coughing', 'Sneeze': 'sneezing', 'Clapping': 'clapping',
    'Knock': 'knocking', 'Doorbell': 'doorbell',
    'Telephone bell ringing': 'phone ringing', 'Siren': 'siren',
    'Smoke detector, smoke alarm': 'smoke alarm sound',
    'Glass': 'glass sound', 'Thunderstorm': 'thunder',
}


class ListeningModelError(Exception):
    pass


class SoundEvents:
    """Emit one label per burst; never print every classifier frame."""

    def __init__(self, threshold=0.6, cooldown_seconds=15):
        if not math.isfinite(threshold) or not 0.1 <= threshold <= 1:
            raise ValueError('Sound confidence threshold must be between 0.1 and 1.')
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.active = {}
        self.last_emitted = {}

    def update(self, predictions, seconds):
        scores = {}
        for name, score in predictions:
            label = SOUND_LABELS.get(name)
            if label and math.isfinite(score) and self.threshold <= score <= 1:
                scores[label] = max(scores.get(label, 0), score)
        for label in list(self.active):
            if label not in scores:
                self.active[label] += 1
                if self.active[label] >= 2:
                    del self.active[label]
        output = []
        for label in sorted(scores, key=scores.get, reverse=True):
            if label not in self.active and seconds - self.last_emitted.get(label, -math.inf) >= self.cooldown_seconds:
                output.append(label)
                self.last_emitted[label] = seconds
            self.active[label] = 0
        return output[:3]


class LocalListeningModels:
    """Lazily load shared inference weights, once per server process."""

    def __init__(self, root, *, enhance_speech=False, sound_threshold=0.6):
        self.root = Path(root)
        self.enhance_speech = enhance_speech
        self.sound_threshold = sound_threshold
        SoundEvents(sound_threshold)  # Validate before acquiring the microphone.
        self.asr = self.tagger = None

    def _file(self, relative):
        path = self.root / relative
        if not path.is_file():
            raise ListeningModelError('Local listening models are missing. Run install_listening_models.py on the Pi.')
        return str(path)

    def _load(self):
        if self.asr is not None:
            return
        try:
            import numpy as np
            import sherpa_onnx as sherpa
        except (ImportError, OSError) as exc:
            raise ListeningModelError('Install requirements-listening.txt on the Pi, then restart Samson.') from exc
        speech = Path(SPEECH_MODEL)
        sounds = Path(SOUND_MODEL)
        asr = sherpa.OnlineRecognizer.from_transducer(
            tokens=self._file(speech / 'tokens.txt'),
            encoder=self._file(speech / 'encoder-epoch-99-avg-1.int8.onnx'),
            decoder=self._file(speech / 'decoder-epoch-99-avg-1.onnx'),
            joiner=self._file(speech / 'joiner-epoch-99-avg-1.int8.onnx'),
            num_threads=2, model_type='zipformer', provider='cpu',
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4, rule2_min_trailing_silence=1.2,
        )
        config = sherpa.AudioTaggingConfig(
            model=sherpa.AudioTaggingModelConfig(
                zipformer=sherpa.OfflineZipformerAudioTaggingModelConfig(
                    model=self._file(sounds / 'model.int8.onnx')),
                num_threads=1, provider='cpu'),
            labels=self._file(sounds / 'class_labels_indices.csv'), top_k=20,
        )
        tagger = sherpa.AudioTagging(config)
        self.np, self.sherpa = np, sherpa
        self.asr, self.tagger = asr, tagger

    def denoiser(self):
        if not self.enhance_speech:
            return None
        s = self.sherpa
        return s.OnlineSpeechDenoiser(s.OnlineSpeechDenoiserConfig(
            model=s.OfflineSpeechDenoiserModelConfig(
                gtcrn=s.OfflineSpeechDenoiserGtcrnModelConfig(model=self._file('gtcrn_simple.onnx')),
                num_threads=1, provider='cpu')))

    def create_recognizer(self, sample_rate):
        self._load()
        return LocalRecognizer(self, sample_rate)


class LocalRecognizer:
    def __init__(self, models, sample_rate):
        self.models, self.sample_rate = models, sample_rate
        self.np, self.asr, self.tagger = models.np, models.asr, models.tagger
        self.events = SoundEvents(models.sound_threshold)
        self.seconds = 0
        self.pending_labels = []
        self.Reset()

    def Reset(self):
        self.stream = self.asr.create_stream()
        self.cleaner = self.models.denoiser()
        self.speech_rate = self.cleaner.sample_rate if self.cleaner else self.sample_rate
        self.raw_chunks = []
        self.raw_frames = 0
        self.final_text = None
        self.pending_labels.clear()

    def _decode(self, samples, rate):
        if len(samples):
            self.stream.accept_waveform(rate, samples)
            while self.asr.is_ready(self.stream):
                self.asr.decode_stream(self.stream)

    def _classify(self):
        if not self.raw_frames:
            return
        samples = self.np.concatenate(self.raw_chunks)
        self.raw_chunks, self.raw_frames = [], 0
        # Skip digital silence; do not amplify quiet background noise into events.
        predictions = []
        if float(self.np.max(self.np.abs(samples))) >= 0.0001:
            stream = self.tagger.create_stream()
            stream.accept_waveform(self.sample_rate, samples)
            predictions = [(event.name, event.prob) for event in self.tagger.compute(stream)]
        for label in self.events.update(predictions, self.seconds):
            if label not in self.pending_labels:
                self.pending_labels.append(label)

    def AcceptWaveform(self, data):
        samples = self.np.frombuffer(data, dtype=self.np.int16).astype(self.np.float32) / 32768.0
        self.seconds += len(samples) / self.sample_rate
        # Limit each classification to two seconds regardless of the print cadence.
        offset = 0
        while offset < len(samples):
            size = min(len(samples) - offset, int(self.sample_rate * SOUND_WINDOW_SECONDS) - self.raw_frames)
            self.raw_chunks.append(samples[offset:offset + size])
            self.raw_frames += size
            offset += size
            if self.raw_frames >= int(self.sample_rate * SOUND_WINDOW_SECONDS):
                self._classify()
        if self.cleaner is None:
            self._decode(samples, self.sample_rate)
        else:
            clean = self.cleaner(samples, self.sample_rate)
            self._decode(self.np.asarray(clean.samples, dtype=self.np.float32), clean.sample_rate)
        return self.asr.is_endpoint(self.stream)

    def _text(self):
        speech = self.asr.get_result(self.stream).strip().lower()
        return '\n'.join(([speech] if speech else []) + [f'[{label}]' for label in self.pending_labels])

    def PartialResult(self):
        return json.dumps({'partial': self._text()})

    def Result(self):
        text = self._text()
        self.asr.reset(self.stream)
        self.pending_labels.clear()
        return json.dumps({'text': text})

    def FinalResult(self):
        if self.final_text is None:
            self._classify()
            if self.cleaner is not None:
                clean = self.cleaner.flush()
                self._decode(self.np.asarray(clean.samples, dtype=self.np.float32), clean.sample_rate)
            self._decode(self.np.zeros(int(self.speech_rate * .5), dtype=self.np.float32), self.speech_rate)
            self.stream.input_finished()
            while self.asr.is_ready(self.stream):
                self.asr.decode_stream(self.stream)
            self.final_text = self._text()
        return json.dumps({'text': self.final_text})
