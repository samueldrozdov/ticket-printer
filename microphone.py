"""On-demand and continuous recording from the USB microphone on the printer host."""

from array import array
import json
import logging
import math
import os
from pathlib import Path
import queue
import secrets
import threading
import time

from flask import Blueprint, jsonify, request

from live_print import LivePrintError, LivePrintQueue
from listening_models import ListeningModelError, LocalListeningModels


MAX_SECONDS = 30
DEFAULT_CADENCE_SECONDS = 10
MAX_CADENCE_SECONDS = 300
MAX_DURATION_SECONDS = 86400
AUDIO_QUEUE_BLOCKS = 64
AUDIO_METER_BARS = 7
AUDIO_METER_STALE_SECONDS = 1
AUDIO_GAP_WARNING = "Some audio was missed. Check the transcript and printed tickets for missing words."
logger = logging.getLogger(__name__)


def audio_activity(data):
    """Summarize native-endian mono int16 PCM without exposing audio to the browser."""
    samples = array('h', data[:len(data) // 2 * 2])

    def level(values):
        if not values:
            return 0.0
        rms = math.sqrt(sum(value * value for value in values) / len(values)) / 32768
        # A logarithmic scale makes quiet input visible; -60 dBFS is the floor.
        return round(max(0.0, min(1.0, (20 * math.log10(max(rms, 1e-6)) + 60) / 60)), 3)

    overall = level(samples)
    return {"level": overall, "detected": overall >= 0.167,  # About -50 dBFS; sound, not speech detection.
            "levels": [level(samples[index * len(samples) // AUDIO_METER_BARS:
                                     (index + 1) * len(samples) // AUDIO_METER_BARS])
                       for index in range(AUDIO_METER_BARS)]}


class MicrophoneError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class Microphone:
    def __init__(self, enabled=False, device="Samson", model_path="models/vosk-model-small-en-us-0.15", print_text=None,
                 listening_models=None):
        self.enabled = enabled
        self.device = int(device) if str(device).isdigit() else device
        self.model_path = Path(model_path)
        self._model = None
        self._listening_models = listening_models
        self._lock = threading.RLock()
        self._sessions = {}
        self._thread = None
        self._print_text = print_text
        self._last_live_id = None

    def start(self):
        return self._start()

    def start_live(self, cadence_seconds=DEFAULT_CADENCE_SECONDS, duration_seconds=None, include_date=None):
        for name, value, limit in (("cadence_seconds", cadence_seconds, MAX_CADENCE_SECONDS),
                                   ("duration_seconds", duration_seconds, MAX_DURATION_SECONDS)):
            if value is None and name == "duration_seconds":
                continue
            if type(value) is not int or not 1 <= value <= limit:
                raise MicrophoneError(f"{name} must be an integer between 1 and {limit}.", 400)
        if self._print_text is None:
            raise MicrophoneError("Live printing is not configured.")
        if include_date is not None and type(include_date) is not bool:
            raise MicrophoneError("include_date must be a boolean.", 400)
        return self._start(cadence_seconds=cadence_seconds, duration_seconds=duration_seconds, include_date=include_date)

    def _start(self, cadence_seconds=None, duration_seconds=None, include_date=None):
        with self._lock:
            if not self.enabled:
                raise MicrophoneError("Microphone is disabled. Follow MICROPHONE_SETUP.md on the Pi.")
            if self._thread and self._thread.is_alive():
                raise MicrophoneError("The Pi microphone is already in use. Try again when recording finishes.", 409)
            session_id = secrets.token_urlsafe(24)
            session = {"id": session_id, "state": "starting", "text": "", "error": None,
                       "warning": None, "audio_overflows": 0, "audio_sample": None,
                       "started_at": None, "ended_at": None, "stop": threading.Event(),
                       "mode": "live" if cadence_seconds is not None else "review",
                       "cadence_seconds": cadence_seconds, "duration_seconds": duration_seconds,
                       "stop_reason": None, "flush_on_stop": True}
            if cadence_seconds is not None:
                print_text = self._print_text if include_date is None else \
                    lambda text: self._print_text(text, include_date=include_date)
                session["live"] = LivePrintQueue(print_text, session["stop"])
                self._last_live_id = session_id
            # Keep a few completed results so another browser cannot overwrite a pending review.
            while len(self._sessions) >= 8:
                del self._sessions[next(iter(self._sessions))]
            self._sessions[session_id] = session
            self._thread = threading.Thread(target=self._record, args=(session,), daemon=True)
            self._thread.start()
            return self.status(session_id)

    def status(self, session_id):
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise MicrophoneError("Recording no longer available. Please record again.", 404)
            limit = session["duration_seconds"] if session["mode"] == "live" else MAX_SECONDS
            elapsed = max(0, (session["ended_at"] or time.monotonic()) - session["started_at"]) \
                if session["started_at"] is not None else 0
            result = {key: session[key] for key in (
                "id", "state", "mode", "text", "error", "warning", "audio_overflows", "stop_reason")}
            result.update(max_seconds=limit, seconds=int(min(limit, elapsed) if limit is not None else elapsed))
            sample = session["audio_sample"]
            result["audio"] = audio_activity(sample[1]) if (
                session["state"] == "recording" and not session["stop"].is_set() and sample and
                time.monotonic() - sample[0] <= AUDIO_METER_STALE_SECONDS
            ) else None
            if session["mode"] == "live":
                result.update(cadence_seconds=session["cadence_seconds"], duration_seconds=limit,
                              flush_on_stop=session["flush_on_stop"], **session["live"].snapshot())
                if result["print_error"]:
                    result["error"] = result["print_error"]
            return result

    def live_status(self):
        with self._lock:
            if self._last_live_id not in self._sessions:
                return {"state": "idle", "mode": "live", "id": None}
            return self.status(self._last_live_id)

    def connected(self):
        """Check the configured input device without starting a recording."""
        if not self.enabled:
            return False
        try:
            import sounddevice as sd
            device = sd.query_devices(self.device, "input")
            return device["max_input_channels"] > 0
        except Exception:
            return False

    def stop(self, session_id, flush=False):
        with self._lock:
            self.status(session_id)  # Validate before accessing the session.
            session = self._sessions[session_id]
            if session["state"] in ("done", "error"):
                return self.status(session_id)
            # Repeated stop requests cannot re-enable printing after cancellation.
            session["flush_on_stop"] = session["flush_on_stop"] and flush
            session["stop_reason"] = session["stop_reason"] or "manual"
            if session["mode"] == "live":
                session["state"] = "stopping"
                if not session["flush_on_stop"]:
                    session["live"].cancel()
            session["stop"].set()
            return self.status(session_id)

    def _update(self, session, **values):
        with self._lock:
            session.update(values)

    def _record(self, session):
        timer = None
        live = session.get("live")
        overflows = 0
        failure_reason = None

        def report_overflows():
            if overflows != session["audio_overflows"]:
                if not session["audio_overflows"]:
                    logger.warning("Microphone input overflow; continuing capture with an audio-gap warning")
                self._update(session, audio_overflows=overflows, warning=AUDIO_GAP_WARNING)

        def capture_error():
            if failure_reason == "queue_full":
                return MicrophoneError("Samson could not transcribe audio fast enough. Recording stopped; try again.")
            if failure_reason == "audio_status":
                return MicrophoneError("The microphone reported an audio error. Please try recording again.")
            return MicrophoneError("The microphone stopped sending audio. Check its USB connection and try again.")

        try:
            try:
                import sounddevice as sd
            except (ImportError, OSError) as exc:
                raise MicrophoneError(
                    "Install requirements-microphone.txt and libportaudio2 on the Pi, then restart the app."
                ) from exc

            if self._listening_models is None and not self.model_path.is_dir():
                raise MicrophoneError("Speech model is missing. Follow the model download step in MICROPHONE_SETUP.md.")
            try:
                device_info = sd.query_devices(self.device, "input")
                sample_rate = int(device_info["default_samplerate"])
                sd.check_input_settings(device=self.device, channels=1, dtype="int16", samplerate=sample_rate)
            except Exception as exc:
                raise MicrophoneError(
                    "Cannot open the configured microphone. Plug it into the Pi and check MICROPHONE_DEVICE "
                    "using python -m sounddevice."
                ) from exc

            if self._listening_models is not None:
                recognizer = self._listening_models.create_recognizer(sample_rate)
            else:
                try:
                    from vosk import Model, KaldiRecognizer
                except (ImportError, OSError) as exc:
                    raise MicrophoneError('Install requirements-microphone.txt on the Pi, then restart the app.') from exc
                if self._model is None:
                    self._model = Model(str(self.model_path))
                recognizer = KaldiRecognizer(self._model, sample_rate)
            if session["stop"].is_set():
                self._update(session, state="done")
                return
            audio = queue.Queue(maxsize=AUDIO_QUEUE_BLOCKS)
            failed = threading.Event()
            stop = session["stop"]
            segments = []
            window_frames = 0
            cadence_frames = session["cadence_seconds"] * sample_rate if live else None

            def capture(indata, frames, timing, status):
                nonlocal overflows, failure_reason
                if stop.is_set():
                    raise sd.CallbackStop
                if status:
                    # PortAudio keeps delivering usable input after an overflow.
                    # Do not turn a recoverable scheduling gap into a USB failure.
                    # Keep logging and session-lock work out of the audio callback.
                    if getattr(status, "input_overflow", False) and not any(
                        getattr(status, flag, False) for flag in (
                            "input_underflow", "output_underflow", "output_overflow", "priming_output")
                    ):
                        overflows += 1
                    else:
                        failure_reason = "audio_status"
                        failed.set()
                        raise sd.CallbackAbort
                try:
                    data = bytes(indata)
                    # Publish one immutable snapshot. Meter calculations happen in
                    # status requests, with no extra locks or DSP in this callback.
                    session["audio_sample"] = (time.monotonic(), data)
                    audio.put_nowait((data, frames))
                except queue.Full:
                    failure_reason = "queue_full"
                    failed.set()
                    raise sd.CallbackAbort

            def recognize(data):
                if recognizer.AcceptWaveform(data):
                    text = json.loads(recognizer.Result()).get("text", "").strip()
                    if text:
                        segments.append(text)
                    partial = ""
                else:
                    partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                self._update(session, text=" ".join(segments + ([partial] if partial else [])))

            def finalize_window():
                final = json.loads(recognizer.FinalResult()).get("text", "").strip()
                if final:
                    segments.append(final)
                text = " ".join(segments)
                self._update(session, text=text)
                if live:
                    accepted = live.enqueue(text)
                    recognizer.Reset()
                    if accepted or not text:
                        segments.clear()
                        self._update(session, text="")

            def consume(block):
                nonlocal window_frames
                data, frames = block
                recognize(data)
                window_frames += frames
                if live and window_frames >= cadence_frames and (not stop.is_set() or session["flush_on_stop"]):
                    finalize_window()
                    window_frames = 0

            def expire():
                with self._lock:
                    session["stop_reason"] = session["stop_reason"] or "duration"
                    stop.set()

            with sd.RawInputStream(device=self.device, samplerate=sample_rate, channels=1,
                                   dtype="int16", blocksize=4000, callback=capture) as stream:
                self._update(session, state="stopping" if stop.is_set() else "recording", started_at=time.monotonic())
                # The capture deadline is independent of HTTP requests and recognition speed.
                duration = session["duration_seconds"] if live else MAX_SECONDS
                if duration is not None:
                    timer = threading.Timer(duration, expire)
                    timer.daemon = True
                    timer.start()
                while not stop.is_set():
                    report_overflows()
                    if failed.is_set() or (not stream.active and not stop.is_set()):
                        raise capture_error()
                    try:
                        consume(audio.get(timeout=0.2))
                    except queue.Empty:
                        continue
            self._update(session, state="stopping" if live else "transcribing", ended_at=time.monotonic())
            if failed.is_set():
                raise capture_error()
            while not audio.empty():
                consume(audio.get_nowait())
            if not live or window_frames:
                finalize_window()
            if not live:
                self._update(session, state="done")
        except Exception as exc:
            logger.warning("Microphone session stopped: %s", failure_reason or type(exc).__name__)
            message = str(exc) if isinstance(exc, (MicrophoneError, LivePrintError, ListeningModelError)) else (
                "Could not record or transcribe. Check the microphone, speech model, and Pi audio permissions."
            )
            self._update(session, state="error", error=message, stop_reason="error")
            if live:
                live.cancel()
        finally:
            report_overflows()
            if timer:
                timer.cancel()
            self._update(session, ended_at=session["ended_at"] or time.monotonic(), audio_sample=None)
            if live:
                live.finish()
                live.wait()
                error = session["error"] or live.snapshot()["print_error"]
                self._update(session, state="error" if error else "done", error=error,
                             stop_reason="error" if error else session["stop_reason"])


def create_microphone_blueprint(microphone, allowed_origins=(), test_mode=False):
    api = Blueprint("microphone", __name__, url_prefix="/microphone")

    @api.before_request
    def check_origin():
        # CORS alone does not prevent a foreign web page from starting a recording.
        origin = request.headers.get("Origin")
        allowed = {request.host_url.rstrip("/"), *allowed_origins}
        if origin and origin not in allowed:
            return jsonify(success=False, error="Open the printer page directly on the Pi's address."), 403
        if request.method == "POST" and not request.is_json:
            return jsonify(success=False, error="A JSON request is required."), 415

    @api.after_request
    def no_store(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @api.errorhandler(MicrophoneError)
    def microphone_error(error):
        return jsonify(success=False, error=str(error)), error.status

    @api.get("")
    def config():
        return jsonify(success=True, enabled=microphone.enabled, connected=microphone.connected(),
                       max_seconds=MAX_SECONDS, test_mode=test_mode,
                       recognition_backend='sherpa' if microphone._listening_models else 'vosk',
                       sound_labels=bool(microphone._listening_models))

    @api.post("/start")
    def start():
        return jsonify(success=True, **microphone.start()), 202

    @api.get("/<session_id>")
    def status(session_id):
        return jsonify(success=True, test_mode=test_mode, **microphone.status(session_id))

    @api.post("/<session_id>/stop")
    def stop(session_id):
        return jsonify(success=True, **microphone.stop(session_id))

    @api.get("/live")
    def live_status():
        return jsonify(success=True, test_mode=test_mode, **microphone.live_status())

    @api.post("/live/start")
    def start_live():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) - {"cadence_seconds", "duration_seconds", "include_date"}:
            raise MicrophoneError("Provide cadence_seconds, duration_seconds, and/or include_date in a JSON object.", 400)
        if "include_date" in data and type(data["include_date"]) is not bool:
            raise MicrophoneError("include_date must be a boolean.", 400)
        return jsonify(success=True, test_mode=test_mode, **microphone.start_live(**data)), 202

    @api.post("/live/<session_id>/stop")
    def stop_live(session_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) - {"flush"} or type(data.get("flush", False)) is not bool:
            raise MicrophoneError("Provide a JSON object with an optional boolean flush field.", 400)
        if microphone.status(session_id)["mode"] != "live":
            raise MicrophoneError("This is not a live printing session.", 409)
        return jsonify(success=True, test_mode=test_mode, **microphone.stop(session_id, flush=data.get("flush", False))), 202

    return api


def microphone_from_environment(print_text=None):
    backend = os.getenv('MICROPHONE_BACKEND', 'vosk').lower()
    if backend not in ('vosk', 'sherpa'):
        raise ValueError('MICROPHONE_BACKEND must be vosk or sherpa.')
    models = LocalListeningModels(
        os.getenv('LISTENING_MODELS_PATH', str(Path(__file__).parent / 'models')),
        enhance_speech=os.getenv('SPEECH_ENHANCEMENT', 'false').lower() == 'true',
        sound_threshold=float(os.getenv('SOUND_EVENT_THRESHOLD', '0.6')),
    ) if backend == 'sherpa' else None
    return Microphone(
        enabled=os.getenv("MICROPHONE_ENABLED", "false").lower() == "true",
        device=os.getenv("MICROPHONE_DEVICE", "Samson"),
        model_path=os.getenv("VOSK_MODEL_PATH", str(Path(__file__).parent / "models/vosk-model-small-en-us-0.15")),
        print_text=print_text,
        listening_models=models,
    )
