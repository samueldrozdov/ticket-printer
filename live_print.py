"""Bounded print queue for one live dictation session."""

from collections import deque
import threading


MAX_PENDING_JOBS = 20
RECENT_JOBS = 20


class LivePrintError(Exception):
    pass


class LivePrintQueue:
    def __init__(self, print_text, stop_recording):
        self._print_text = print_text
        self._stop_recording = stop_recording
        self._condition = threading.Condition()
        self._pending = deque()
        self._recent = deque(maxlen=RECENT_JOBS)
        self._current = None
        self._closed = False
        self._cancelled = False
        self._sequence = 0
        self._printed_count = 0
        self._cancelled_count = 0
        self._error = None
        self._failed_job = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue(self, text):
        text = text.strip()
        if not text:
            return False
        with self._condition:
            if self._cancelled:
                return False
            if self._closed:
                raise LivePrintError("The print queue is closed.")
            if len(self._pending) >= MAX_PENDING_JOBS:
                raise LivePrintError("The printer cannot keep up: the print queue is full. Live listening stopped.")
            self._sequence += 1
            self._pending.append({"id": self._sequence, "text": text, "state": "queued"})
            self._condition.notify_all()
            return True

    def cancel(self):
        """Cancel waiting work. A job already handed to the printer may finish."""
        with self._condition:
            self._cancelled = True
            self._closed = True
            while self._pending:
                job = self._pending.popleft()
                job["state"] = "cancelled"
                self._recent.append(job)
                self._cancelled_count += 1
            self._condition.notify_all()

    def finish(self):
        """Close input while allowing previously queued jobs to drain."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def wait(self):
        self._thread.join()

    def snapshot(self):
        with self._condition:
            return {
                "queue_depth": len(self._pending),
                "queued_jobs": [dict(job) for job in self._pending],
                "printing": dict(self._current) if self._current else None,
                "printed_count": self._printed_count,
                "cancelled_count": self._cancelled_count,
                "recent_jobs": [dict(job) for job in self._recent],
                "failed_job": dict(self._failed_job) if self._failed_job else None,
                "print_error": self._error,
            }

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending)
                if not self._pending:
                    return
                job = self._pending.popleft()
                job["state"] = "printing"
                self._current = job
            try:
                result = self._print_text(job["text"])
            except Exception as exc:
                with self._condition:
                    job["state"] = "failed"
                    job["error"] = str(exc)
                    self._failed_job = dict(job)
                    self._error = "Printing failed; live listening stopped. Check the printer before restarting."
                    self._recent.append(job)
                    self._current = None
                    # Never retry an ambiguous print outcome: some text may already be on paper.
                    self._stop_recording.set()
                    self.cancel()
                return
            with self._condition:
                if isinstance(result, dict) and isinstance(result.get("history_id"), int):
                    job["history_id"] = result["history_id"]
                job["state"] = "printed"
                self._printed_count += 1
                self._recent.append(job)
                self._current = None
