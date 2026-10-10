#!/usr/bin/env python3
"""Serve password-protected Samson, optionally with a temporary HTTPS link."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading

from dotenv import load_dotenv

from remote_access import remote_password


def create_remote_server(app, port):
    from waitress import create_server

    # One process owns all printer and microphone state. Only the local tunnel
    # may supply HTTPS scheme information; forwarded host/IP headers are ignored.
    return create_server(app, host="127.0.0.1", port=port, threads=8,
                         trusted_proxy="127.0.0.1",
                         trusted_proxy_headers={"x-forwarded-proto"},
                         clear_untrusted_proxy_headers=True,
                         max_request_body_size=16 * 1024 * 1024)


def main():
    load_dotenv(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "5000")))
    parser.add_argument("--tunnel", action="store_true", help="Create a temporary Cloudflare HTTPS link")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")

    os.environ["SAMSON_REMOTE_ACCESS"] = "true"
    try:
        remote_password()
    except ValueError as error:
        parser.error(str(error))
    cloudflared = shutil.which("cloudflared") if args.tunnel else None
    if args.tunnel and not cloudflared:
        parser.error("Install cloudflared first; see REMOTE_ACCESS.md.")

    from app import app
    app.debug = False
    try:
        server = create_remote_server(app, args.port)
    except OSError as error:
        parser.error(f"Could not start the server: {error}. Stop the existing Samson app first.")

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    tunnel = None
    closing = threading.Event()
    try:
        print(f"Samson is password protected. Username: samson. Local port: {args.port}.", flush=True)
        # Bind the server before starting the tunnel. A failed bind must never
        # publish a different (possibly unprotected) app already using this port.
        if args.tunnel:
            tunnel = subprocess.Popen([cloudflared, "tunnel", "--url", f"http://127.0.0.1:{args.port}"])

            def watch_tunnel():
                tunnel.wait()
                if not closing.is_set():
                    os.kill(os.getpid(), signal.SIGTERM)

            threading.Thread(target=watch_tunnel, daemon=True).start()
        server.run()
        return (tunnel.returncode or 0) if tunnel else 0
    except KeyboardInterrupt:
        return (tunnel.returncode or 0) if tunnel else 0
    finally:
        closing.set()
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait()
        server.task_dispatcher.shutdown()
        server.close()


if __name__ == "__main__":
    raise SystemExit(main())
