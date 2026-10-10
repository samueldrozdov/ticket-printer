"""Durable print journal, shared by HTTP requests and microphone workers."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3


logger = logging.getLogger(__name__)


class PrintHistory:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS print_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    preview TEXT,
                    status TEXT NOT NULL,
                    error TEXT
                )""")
                yield connection
        finally:
            connection.close()

    @contextmanager
    def record(self, *, source, kind="text", text, preview=None, test_mode=False):
        # Commit before touching hardware. A crash or lost connection must never
        # erase the content or incorrectly claim the ticket was printed.
        with self.connection() as connection:
            job_id = connection.execute(
                """INSERT INTO print_history
                (created_at, source, kind, text, preview, status)
                VALUES (?, ?, ?, ?, ?, 'unconfirmed')""",
                (datetime.now(timezone.utc).isoformat(), source, kind, text,
                 json.dumps(preview) if preview else None),
            ).lastrowid
        try:
            yield job_id
        except Exception as error:
            self._finish(job_id, "failed", str(error))
            raise
        else:
            self._finish(job_id, "test_mode" if test_mode else "printed")

    def _finish(self, job_id, status, error=None):
        try:
            with self.connection() as connection:
                connection.execute("UPDATE print_history SET status = ?, error = ? WHERE id = ?",
                                   (status, error, job_id))
        except Exception:
            # The initial record is durable. Do not turn a completed hardware
            # operation into a retryable error if its status cannot be updated.
            logger.exception("Could not update print history entry %s", job_id)

    def page(self, *, before=None, limit=30):
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM print_history " + ("WHERE id < ? " if before else "") +
                "ORDER BY id DESC LIMIT ?",
                (before, limit + 1) if before else (limit + 1,),
            ).fetchall()
        more = len(rows) > limit
        entries = [dict(row) for row in reversed(rows[:limit])]
        for entry in entries:
            entry["preview"] = json.loads(entry["preview"]) if entry["preview"] else None
        return {"entries": entries, "next_before": entries[0]["id"] if more else None}
