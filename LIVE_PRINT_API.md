# Continuous listening and printing API

This backend mode captures the Pi's USB microphone, transcribes speech locally,
and automatically prints the finalized text at a chosen cadence. It is separate
from the existing 30-second record/review/print flow.

In the chat, open **+ → Listen & print**. Choose **Print every** (including a custom
interval) and **Stop after**, or leave **Until I stop** selected. Press **Start
listening**. The persistent listening bar shows the applied timing and ticket
count, with a **Stop** button. Printed, waiting, cancelled, and failed tickets
appear in the conversation; the newest 20 are retained in each live history.

The page recovers an active session after refresh. Closing the page does not stop
the Pi. A connection failure keeps the status visible and retries discovery;
it never automatically starts another session. An unconfirmed manual Stop is
retried after reconnecting. Stopping preserves final unqueued text in the current
draft; queued tickets cancelled by Stop remain labelled in the conversation.

Use the root `app.py`, with microphone support installed and
`MICROPHONE_ENABLED=true`; see [MICROPHONE_SETUP.md](MICROPHONE_SETUP.md).
The mode starts only after an explicit API request. Use one application process
and disable the development reloader (`DEBUG=False`).

## Start

`POST /microphone/live/start`, with `Content-Type: application/json`:

```json
{"cadence_seconds": 10, "duration_seconds": 300}
```

| Field | Meaning | Default | Accepted values |
| --- | --- | --- | --- |
| `cadence_seconds` | How much audio to accumulate per printed ticket | `10` | Integer, 1–300 |
| `duration_seconds` | How long to listen before automatically stopping | `null` | Integer, 1–86400, or `null` |
| `include_date` | Include the date and time on each printed ticket | `true` | Boolean |

Omit `duration_seconds` or set it to `null` to listen until manually stopped.
Omit all fields with `{}` to use the defaults. Duration begins when audio capture
starts, after model/device initialization. Changing settings requires stopping
the current session and starting another.

Returns HTTP `202` with `success: true`, an `id`, and the session status. `starting`
means initialization is in progress; wait for `recording` before prompting the
user to speak. Missing hardware/model errors can appear asynchronously in status.
The same microphone cannot run live and review sessions simultaneously.

## Read status

- `GET /microphone/live`: returns the current or most recent live session. Before
  any live session exists, returns `{"success":true,"state":"idle","mode":"live","id":null}`.
  Use this endpoint after refreshing/reopening the frontend.
- `GET /microphone/<id>`: reads a specific session, including completed results.

Poll while active (about once per second is sufficient). Recording and automatic
shutdown continue independently of the browser and polling.

| Status field | Meaning |
| --- | --- |
| `id`, `mode` | Session identifier and `"live"` |
| `state` | `starting`, `recording`, `stopping`, `done`, or `error` |
| `seconds` | Elapsed capture time, frozen when capture ends |
| `cadence_seconds`, `duration_seconds` | Applied settings |
| `max_seconds` | Same as duration; `null` for an indefinite session |
| `text` | Current unqueued transcript; may contain a changing partial hypothesis while recording |
| `stop_reason` | `null`, `manual`, `duration`, or `error` |
| `flush_on_stop` | Whether final buffered speech and waiting jobs will print |
| `queue_depth`, `queued_jobs` | Waiting job count and jobs |
| `printing` | Job already dispatched to the shared printer operation, or `null` |
| `printed_count`, `cancelled_count` | Session totals |
| `recent_jobs` | Last 20 completed, cancelled, or failed jobs |
| `failed_job` | Most recent failed job, including its text and transport error, or `null` |
| `error`, `print_error` | Human-readable session/printing failure messages, or `null` |
| `test_mode` | Whether successful jobs were logged instead of sent to hardware |

Jobs contain `id` (sequence within this session), `text`, and `state` (`queued`,
`printing`, `printed`, `cancelled`, or `failed`). Failed jobs also contain `error`.
`printed` means the printer operation returned successfully, not confirmation of
paper output. With `TEST_MODE=true`, operations log instead of sending to hardware;
the same counters advance. `GET /health` exposes the app's test-mode setting.

## Stop

`POST /microphone/live/<id>/stop`, with JSON:

```json
{"flush": false}
```

`{}` also defaults to `flush: false`: stop capture, cancel waiting print jobs, and
retain the final unqueued transcript in `text`. A job already dispatched may still
finish, including one waiting for another print request to release the printer.

Use `{"flush":true}` to stop capture and print the final buffered text plus all
waiting jobs. Automatic duration expiry behaves this way too. Empty recognized
windows do not print.

Returns HTTP `202` with the current status. Poll until `done` or `error`; the
`stopping` state includes transcription finalization and printer queue draining.
Stopping repeatedly is safe. Once a stop cancels printing, another stop with
`flush: true` cannot restore the cancelled work. The older
`POST /microphone/<id>/stop` endpoint also stops live sessions without flushing.

## Printing behavior and failures

- Each cadence window is finalized once before printing; partial hypotheses are
  never printed. Recognition resets after each window so earlier text is not
  repeated. The cadence rounds up to an audio block boundary; recognition and
  printer speed may delay physical output. A boundary can split a spoken sentence.
- Printing runs on a separate worker so slow printing does not block audio capture.
  Live and HTTP printing share a lock to avoid interleaving printer commands.
- At most 20 jobs may wait for printing. If the queue fills, the session stops with
  an error, cancels waiting jobs, and retains the overflow text in `text`.
- A printer failure stops the session and cancels waiting jobs. Inspect
  `failed_job`, `recent_jobs`, and `text` before restarting. The live queue never
  automatically resubmits failed jobs: a failure may follow partial paper output.
- Audio interruption/overflow also stops the session rather than silently
  continuing with missing speech. An already dispatched print may still finish
  after an error; check `printing` before treating the printer as idle.

## Errors and lifecycle

Invalid fields, values, or malformed JSON return `400`; non-JSON POSTs return
`415`. Busy microphone or wrong session mode returns `409`; an unknown/expired
session returns `404`; disabled or unconfigured live mode returns `503`.
Runtime failures are exposed by `state: "error"` in otherwise successful status
responses. A new start may still return `409` while a previous worker is finishing.

Microphone routes use the existing same-origin/`MICROPHONE_ALLOWED_ORIGINS` check
and `Cache-Control: no-store`. In local mode this is a trusted-local-network API.
[Remote mode](REMOTE_ACCESS.md) requires the same browser login for every route,
including live status and microphone controls, and accepts only the page's origin.

Sessions, transcripts, and pending jobs are in memory. Restarting the app stops
listening and discards them; it never resumes listening or replays pending prints
automatically. The app retains up to eight recent sessions across both modes.
Audio is neither saved to disk nor uploaded. No extra dependencies beyond the
existing optional microphone packages are needed.

## Tests

```bash
python -m unittest discover -s tests -v
node --test tests/live-listening.test.cjs
```

Tests simulate audio and printer transports; they do not start a real microphone
or print physical tickets. A full hardware test still requires the Pi and printer.
