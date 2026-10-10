"""On-demand and continuous recording from the USB microphone on the printer host."""

import json
import os
from pathlib import Path
import queue
import secrets
import threading
import time

from flask import Blueprint, jsonify, request

from live_print import LivePrintError, LivePrintQueue


MAX_SECONDS = 30
DEFAULT_CADENCE_SECONDS = 10
MAX_CADENCE_SECONDS = 300
MAX_DURATION_SECONDS = 86400


class MicrophoneError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class Microphone:
    def __init__(self, enabled=False, device="Samson", model_path="models/vosk-model-small-en-us-0.15", print_text=None):
        self.enabled = enabled
        self.device = int(device) if str(device).isdigit() else device
        self.model_path = Path(model_path)
        self._model = None
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
            result = {key: session[key] for key in ("id", "state", "mode", "text", "error", "stop_reason")}
            result.update(max_seconds=limit, seconds=int(min(limit, elapsed) if limit is not None else elapsed))
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
        try:
            try:
                import sounddevice as sd
                from vosk import Model, KaldiRecognizer
            except (ImportError, OSError) as exc:
                raise MicrophoneError(
                    "Install requirements-microphone.txt and libportaudio2 on the Pi, then restart the app."
                ) from exc

            if not self.model_path.is_dir():
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

            if self._model is None:
                self._model = Model(str(self.model_path))
            if session["stop"].is_set():
                self._update(session, state="done")
                return
            recognizer = KaldiRecognizer(self._model, sample_rate)
            audio = queue.Queue(maxsize=64)
            failed = threading.Event()
            stop = session["stop"]
            segments = []
            window_frames = 0
            cadence_frames = session["cadence_seconds"] * sample_rate if live else None

            def capture(indata, frames, timing, status):
                if stop.is_set():
                    raise sd.CallbackStop
                if status:
                    failed.set()
                    raise sd.CallbackAbort
                try:
                    audio.put_nowait((bytes(indata), frames))
                except queue.Full:
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
                    if failed.is_set() or (not stream.active and not stop.is_set()):
                        raise MicrophoneError("Microphone recording was interrupted. Check its USB connection and try again.")
                    try:
                        consume(audio.get(timeout=0.2))
                    except queue.Empty:
                        continue
            self._update(session, state="stopping" if live else "transcribing", ended_at=time.monotonic())
            if failed.is_set():
                raise MicrophoneError("Audio was interrupted. Please try recording again.")
            while not audio.empty():
                consume(audio.get_nowait())
            if not live or window_frames:
                finalize_window()
            if not live:
                self._update(session, state="done")
        except Exception as exc:
            message = str(exc) if isinstance(exc, (MicrophoneError, LivePrintError)) else (
                "Could not record or transcribe. Check the microphone, speech model, and Pi audio permissions."
            )
            self._update(session, state="error", error=message, stop_reason="error")
            if live:
                live.cancel()
        finally:
            if timer:
                timer.cancel()
            self._update(session, ended_at=session["ended_at"] or time.monotonic())
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
                       max_seconds=MAX_SECONDS, test_mode=test_mode)

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
    return Microphone(
        enabled=os.getenv("MICROPHONE_ENABLED", "false").lower() == "true",
        device=os.getenv("MICROPHONE_DEVICE", "Samson"),
        model_path=os.getenv("VOSK_MODEL_PATH", str(Path(__file__).parent / "models/vosk-model-small-en-us-0.15")),
        print_text=print_text,
    )
