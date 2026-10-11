# Deploy Samson to the Raspberry Pi

This is the deployment runbook for the current Samson installation. The Pi serves
both the website and API. **Pushing to GitHub does not update the Pi**: publish a
tested commit, install that commit on the Pi, restart the app, then reload the page.

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

Use Raspberry Pi Connect → **Remote shell**, or an existing SSH connection.
The current tunnel is a Cloudflare Quick Tunnel. Restart only the app during an
ordinary deployment; restarting the tunnel or rebooting the Pi changes its URL.
There is no frontend build step and no Netlify deployment in this setup.

## 1. Publish a tested commit from the development computer

Review the working tree and select the completed changes for this release:

```bash
git status --short
git branch --show-current
git diff
git diff --cached
```

This workflow publishes `main`; finish merging any working branch before testing
and publishing. If other tasks are editing this checkout, wait for those changes
to be ready or test an isolated checkout of the intended release.
Stage explicit files with `git add <file>` or review hunks with `git add -p`;
do not sweep unrelated work into a deployment with `git add .`. Uncommitted files
on the development computer never reach the Pi through Git.

Run the checks below in your activated development Python environment. Install
the applicable dependencies first; `requirements-remote.txt` includes the base
requirements, and `requirements-listening.txt` includes microphone support and
NumPy for the audio pipeline tests. JavaScript tests require Node.js.

```bash
samson_test_dir=$(mktemp -d)
SAMSON_PASSWORD='' SAMSON_REMOTE_ACCESS=false \
  PRINT_HISTORY_PATH="$samson_test_dir/history.sqlite3" \
  python -m unittest discover -s tests
node --test tests/*.test.cjs
```

Both commands must pass. The authentication overrides apply only to the test
process; never copy them into the Pi's `.env`. The temporary history path keeps
test records out of real print history. Tests mock printer operations; they do
not replace a physical check when printer behavior changes.

For documentation-only changes, check links, referenced paths, and command syntax.
After updating the Pi checkout, skip the application suites and app restart.

Commit the reviewed files, push, and record the full commit ID:

```bash
git diff --cached --check
git commit -m "Describe the completed change"
git push origin main
git rev-parse HEAD
```

The commit must contain the same code you tested. Keep that ID for the Pi step
and the deployment report; avoid chasing a moving branch while other work lands.

## 2. Prepare the Pi

Stop recording or Passive Listening in the website and wait for all queued
messages and physical printing to finish. Preserve any draft before reloading.
Keep other clients from sending messages during the short deployment window.

On the Pi, check the checkout and services:

```bash
cd /home/sd/ticket-printer-os
git status --short
git rev-parse HEAD
sudo systemctl status ticket-printer samson-tunnel --no-pager
```

If the checkout has local changes, reconcile them before continuing. Do not use
`git reset --hard`, `git clean`, or overwrite `.env` to force a deployment.
Preserve the existing password, printer/microphone settings, history, and models.
Do not run `setup.sh`, `deploy.sh`, or install `backend/ticket-printer.service` on
this installation: those are older setup paths with different service settings.

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

SQLite's backup API handles an open database correctly. Keep this directory
private because it contains the password. Models are not changed by a Git update.

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

Only run `.venv/bin/python install_listening_models.py` when installing or changing
the local listening models. Routine code/UI updates do not need new model
downloads. See [microphone setup](MICROPHONE_SETUP.md#upgrade-to-local-speech-and-sound-recognition)
for model configuration; audio recognition stays on the Pi.

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

Both services should report `active`, and the commit must match the release ID.
The existing HTTPS address should still work. Do not launch a second `app.py`,
`serve_remote.py --tunnel`, or `backend/api.py` process alongside the service.

In the browser:

1. Preserve any draft, reload the page, and sign in if needed. An already-open tab
   keeps its loaded JavaScript until reloaded, even though responses use `no-store`.
2. Open Settings → **Check again**. The app should be reachable and the printer
   available. Authenticated `/health` reports `service: samson`, `status: healthy`,
   and `printer_state`; `healthy` alone does not confirm printer readiness.
3. Check the feature changed by this release and confirm existing history appears.
4. If printing changed, send one clearly labeled test and check the paper. Do not
   automatically resend an unconfirmed ticket. If listening changed, record and
   stop a short sample in review mode before testing automatic printing.

Report the deployed commit, checks performed, and any hardware checks still
unverified. A successful push alone is not a completed deployment.

## Roll back a failed release

Wait for recording and printing to be idle. With a clean Pi checkout, use the
backup directory recorded in step 2 (set `samson_backup_dir` again if this is a
new shell):

```bash
git switch --detach "$(cat "$samson_backup_dir/commit.txt")"
sudo systemctl restart ticket-printer.service
```

Repeat the service and browser checks above. This restores code and frontend
together without replacing `.env`, history, or models. Dependency or database
format changes need their own compatible rollback; do not erase newer history
by blindly restoring a database backup. Before the next deployment, return to
`main` with `git switch main` during the idle deployment window, then install the
new tested release before restarting.

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
