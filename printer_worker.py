"""Contain a stalled hardware operation without exhausting HTTP workers."""

import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


def timeout_setting(name, default):
    value = float(os.getenv(name, str(default)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive, finite number of seconds")
    return value


class PrinterUnavailable(RuntimeError):
    def __init__(self, message, *, state="unavailable", status=503):
        super().__init__(message)
        self.state = state
        self.status = status


@dataclass
class _Operation:
    kind: str
    deadline: float
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    error: BaseException = None


class PrinterWorker:
    """At most one hardware thread, with no queue of blocked HTTP callers.

    A caller timing out does not cancel hardware I/O. Keep the slot occupied
    until the operation actually exits, so a late write can never overlap a
    new print. A permanently stuck driver needs a service restart, but all
    subsequent requests return immediately instead of spawning more threads.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._active = None

    def run(self, function, *, timeout, kind="print"):
        with self._lock:
            if self._active is not None:
                active = self._active
                if time.monotonic() >= active.deadline:
                    raise PrinterUnavailable(
                        "The printer is still unresponsive. The website is available. "
                        "If it does not recover, restart Samson’s app service. "
                        "Check the paper before resending a message.")
                if active.kind == "check":
                    raise PrinterUnavailable("Checking the printer connection. Try again shortly.",
                                             state="checking")
                raise PrinterUnavailable("The printer is busy with another message. Try again when it finishes.",
                                         state="busy")
            operation = _Operation(kind, time.monotonic() + timeout)
            self._active = operation
            thread = threading.Thread(target=self._execute, args=(operation, function),
                                      name="samson-printer", daemon=True)
            try:
                thread.start()
            except BaseException:
                self._active = None
                raise

        if not operation.done.wait(max(0, operation.deadline - time.monotonic())):
            logger.error("Printer %s exceeded its %.1fs deadline; keeping hardware isolated until it exits",
                         kind, timeout)
            message = ("The printer did not confirm this message in time. It may still print; "
                       "check the paper before sending it again." if kind == "print" else
                       "The printer connection check timed out. The website is still available.")
            raise PrinterUnavailable(message, status=504)
        if operation.error is not None:
            raise operation.error
        return operation.result

    def _execute(self, operation, function):
        try:
            operation.result = function()
        except BaseException as error:
            operation.error = error
        finally:
            with self._lock:
                self._active = None
                operation.done.set()
            if time.monotonic() >= operation.deadline:
                logger.warning("Printer %s finally exited after its deadline; hardware is available for new work",
                               operation.kind)
