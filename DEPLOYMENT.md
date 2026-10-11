# Deploy Samson to the Raspberry Pi

The Pi serves the website and API. Deploy in four steps: **publish → back up →
install → restart and verify**. Pushing to GitHub alone does not update the Pi.

## Current installation

| Item | Value |
| --- | --- |
| Repository | [samueldrozdov/ticket-printer](https://github.com/samueldrozdov/ticket-printer), branch `main` |
| Pi user / hostname | `sd` / `sd-pi` |
| Checkout | `/home/sd/ticket-printer-os` |
| Python | `/home/sd/ticket-printer-os/.venv/bin/python` |
| App | Root `app.py`, served by `serve_remote.py` on `127.0.0.1:5000` |
| App service | `ticket-printer.service` |
| HTTPS tunnel service | `samson-tunnel.service` |
| Current public address | Run `samson-link` on the Pi |
| Settings / history / models | `.env`, `data/print-history.sqlite3`, `models/` |
| Backups | `/home/sd/ticket-printer-backups/` |

Use [Raspberry Pi Connect](#access-the-pi-in-the-browser) or an existing SSH
connection. Keep the tunnel running: restarting it or rebooting the Pi changes
the public URL. There is no frontend build or Netlify deployment.

## 1. Publish a tested commit from the development computer

Review the working tree and select the completed changes for this release:

```bash
git status --short
git branch --show-current
git diff
git diff --cached
```

Finish merging onto `main`. If other tasks are editing the checkout, wait for
their changes or test an isolated checkout. Stage only the intended release with
`git add <file>` or `git add -p`; uncommitted changes do not reach the Pi.

In the development Python environment, install dependencies from
`requirements-remote.txt` and `requirements-listening.txt` as needed. Run both
suites (JavaScript tests require Node.js):

```bash
samson_test_dir=$(mktemp -d)
SAMSON_PASSWORD='' SAMSON_REMOTE_ACCESS=false \
  PRINT_HISTORY_PATH="$samson_test_dir/history.sqlite3" \
  python -m unittest discover -s tests
node --test tests/*.test.cjs
```

Both suites must pass. The temporary history and authentication overrides apply
only to tests; keep the Pi's `.env` unchanged. Printer operations are mocked.

For documentation-only changes, check links, referenced paths, and command syntax.
After updating the Pi checkout, skip the application suites and app restart.

Commit the reviewed files, push, and record the full commit ID:

```bash
git diff --cached --check
git commit -m "Describe the completed change"
git push origin main
git rev-parse HEAD
```

Use this exact tested commit for the remaining steps.

## 2. Prepare the Pi

Stop recording or Passive Listening, wait for queued printing to finish, and
keep other clients idle during deployment.

On the Pi, check the checkout and services:

```bash
cd /home/sd/ticket-printer-os
git status --short
git rev-parse HEAD
sudo systemctl status ticket-printer samson-tunnel --no-pager
```

Reconcile local changes before continuing; do not force a clean checkout with
`git reset --hard` or `git clean`. Preserve `.env`, history, and models. Avoid the
legacy `setup.sh`, `deploy.sh`, and `backend/ticket-printer.service`.

Make a backup and record the previous revision in this same shell:

```bash
umask 077
mkdir -p /home/sd/ticket-printer-backups
samson_backup_dir=$(mktemp -d /home/sd/ticket-printer-backups/before-deploy-XXXXXX)
git rev-parse HEAD > "$samson_backup_dir/commit.txt"
cp .env "$samson_backup_dir/.env"
.venv/bin/python - "$samson_backup_dir" <<'PYTHON'
import os
from pathlib import Path
import sqlite3
import sys
from dotenv import load_dotenv

load_dotenv('.env')
history = Path(os.getenv('PRINT_HISTORY_PATH', 'data/print-history.sqlite3'))
if history.exists():
    with sqlite3.connect(history) as source, sqlite3.connect(
        Path(sys.argv[1]) / 'print-history.sqlite3'
    ) as destination:
        source.backup(destination)
PYTHON
printf 'Backup: %s\n' "$samson_backup_dir"
```

Record the backup path for rollback. It contains the password; keep it private.

## 3. Install the exact release

Replace the placeholder with the full commit ID from step 1. Run this block as a
unit so a failed check stops the update:

```bash
(
  set -eu
  cd /home/sd/ticket-printer-os
  SAMSON_RELEASE=PASTE_FULL_COMMIT_ID_HERE
  test -z "$(git status --porcelain)"
  test "$(git branch --show-current)" = main
  git fetch origin
  git merge-base --is-ancestor "$SAMSON_RELEASE" origin/main
  git merge-base --is-ancestor HEAD "$SAMSON_RELEASE"
  git merge --ff-only "$SAMSON_RELEASE"
  test "$(git rev-parse HEAD)" = "$SAMSON_RELEASE"
)
```

If requirements changed, install them using the Pi's existing environment:

```bash
.venv/bin/python -m pip install -r requirements-remote.txt -r requirements-listening.txt
```

Model changes use [microphone setup](MICROPHONE_SETUP.md#upgrade-to-local-speech-and-sound-recognition);
routine releases do not need model downloads.

Run the Python suite on the Pi with isolated history:

```bash
samson_test_dir=$(mktemp -d)
SAMSON_PASSWORD='' SAMSON_REMOTE_ACCESS=false \
  PRINT_HISTORY_PATH="$samson_test_dir/history.sqlite3" \
  .venv/bin/python -m unittest discover -s tests
```

Proceed only if it passes. If installation or tests fail, restore the previous
revision before reopening the site for use; frontend files are served directly
from the checkout even before the app restarts.

## 4. Restart and verify

Confirm listening and printing are still idle, then restart only the app:

```bash
sudo systemctl restart ticket-printer.service
sudo systemctl is-active ticket-printer.service samson-tunnel.service
sudo journalctl -u ticket-printer.service -n 50 --no-pager
git rev-parse HEAD
samson-link
```

Both services must be `active`, and the commit must match the release ID.
Restarting loads the new Python code and HTML templates. Use the existing app
service; do not launch a second server.

Verify the public UI files with the command below, then check the browser.

### Check public files from the Pi checkout

This uses the existing password without printing it:

```bash
.venv/bin/python - <<'PYTHON'
from pathlib import Path
import subprocess
import requests
from dotenv import dotenv_values

config = dotenv_values('.env')
session = requests.Session()
session.auth = ('samson', config.get('SAMSON_PASSWORD', ''))
url = subprocess.check_output(['samson-link'], text=True).strip().rstrip('/')
frontend = Path('frontend')
for asset in sorted(frontend.glob('*.js')) + sorted(frontend.glob('*.css')):
    response = session.get(f'{url}/{asset.name}', timeout=20, allow_redirects=False)
    assert response.status_code == 200, f'{asset.name}: HTTP {response.status_code}'
    assert response.content == asset.read_bytes(), f'{asset.name}: public file differs'
    print('Public asset verified:', asset.name)
print('Verified checkout:', subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
PYTHON
```

Every file must match. For failures, check the URL, authentication, and service
checkout.

### Check the browser

1. Reload Samson or open a separate tab to preserve an unsent message or photo.
   Open tabs keep their old JavaScript until reloaded, even with `no-store`.
2. Open Settings → **Connection** → **Check again**. The app should be reachable
   and the printer available. Authenticated `/health` reports `service: samson`,
   `status: healthy`, and `printer_state`; `healthy` alone does not confirm printer
   readiness.
3. Check the feature changed by this release and confirm existing history appears.
4. If printing changed, send one clearly labeled test and check the paper. Do not
   automatically resend an unconfirmed ticket. If listening changed, record and
   stop a short sample in review mode before testing automatic printing.

Report the commit, completed checks, and unverified hardware behavior. Call it
deployed only after the restart, public-file check, and browser checks succeed;
before then, report it as pushed or installed.

## Roll back a failed release

Wait for recording and printing to be idle. With a clean Pi checkout, use the
backup directory recorded in step 2 (set `samson_backup_dir` again if this is a
new shell):

```bash
git switch --detach "$(cat "$samson_backup_dir/commit.txt")"
sudo systemctl restart ticket-printer.service
```

Repeat verification. This restores code while preserving settings and history;
dependency or database changes need a compatible rollback. Before the next
deployment, return to `main` during an idle window, install the tested release,
and restart.

## Access the Pi in the browser

Use the browser already signed in to [Raspberry Pi Connect](https://connect.raspberrypi.com/devices).
Choose **sd-pi → Connect via → Remote shell**. This also works when SSH cannot
reach `sd-pi.local`. In each new shell, confirm `whoami` is `sd`, `hostname` is
`sd-pi`, and change to `/home/sd/ticket-printer-os`.

- Before pasting, verify the window is **sd-pi remote shell – Raspberry Pi Connect**
  and focus **Terminal input**. If the active window changes, re-read the current
  state and reselect the shell; Samson's message field must not receive commands.
- Wait for the result and shell prompt before continuing. If output is delayed,
  take a fresh screenshot instead of repeating a command. An echo or truncated
  log does not establish success; check the final result and exit status.
- Keep the shell open until work finishes. After reconnecting, check the process,
  logs, and Git revision before retrying, and recreate needed shell variables.

### If browser automation loses multiline input

Use a paste operation that preserves line breaks. If that is unreliable, save a
reviewed Bash script locally as `/tmp/samson-deploy.sh`, starting with
`set -euo pipefail` and `cd /home/sd/ticket-printer-os`. Encode it locally:

```bash
python3 -c 'import base64, pathlib; print(base64.b64encode(pathlib.Path("/tmp/samson-deploy.sh").read_bytes()).decode("ascii"))'
```

Replace the placeholder below with that output and send it as one line to the
Pi. It decodes, checks Bash syntax, runs the script, and reports its exit status:

```bash
samson_script=$(mktemp /tmp/samson-deploy-XXXXXX) && printf '%s' 'BASE64_OF_REVIEWED_SCRIPT' | base64 --decode > "$samson_script" && bash -n "$samson_script" && bash "$samson_script"; samson_exit=$?; printf 'Script exit status: %s\n' "$samson_exit"
```

Keep passwords in the Pi's `.env`; base64 does not conceal them. Script variables
and directory changes do not carry back to the parent shell, so record the backup
path and previous revision from its output.

## If the website looks out of date

Compare the development commit, GitHub's `main`, and the Pi's `git rev-parse HEAD`.
Check for uncommitted development changes. Then confirm the running service uses
`/home/sd/ticket-printer-os/serve_remote.py` and reload the browser after preserving
its draft. Restarting the tunnel does not update the code and may invalidate the
link. Use `samson-link` if the Pi or tunnel was restarted.

## Related setup guides

- [Remote access](REMOTE_ACCESS.md): password, tunnel, service setup, and connection troubleshooting.
- [Microphone setup](MICROPHONE_SETUP.md): hardware and local speech/sound models.
- [Bluetooth configuration](CONFIGURE_BLUETOOTH_PRINTER.md): printer connection settings.
- [Legacy Netlify notes](README_NETLIFY.md): the older split frontend/backend layout.
