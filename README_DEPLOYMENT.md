# Deployment instructions

Use [DEPLOYMENT.md](DEPLOYMENT.md) for the current Samson installation. It is the
single runbook for testing and pushing a release, updating the Pi, restarting the
app while keeping the public URL, verification, and rollback.

The older package-transfer and `setup.sh` instructions have been retired from
this guide. The installed Pi uses `/home/sd/ticket-printer-os/.venv/bin/python`
with `serve_remote.py`, plus a separate tunnel service.

For initial password and tunnel setup, see [REMOTE_ACCESS.md](REMOTE_ACCESS.md).
