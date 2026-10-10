# Use Samson away from home

Run the complete website and API on the Raspberry Pi and expose it through an
HTTPS tunnel. Your phone can then use cellular or another Wi-Fi network. The Pi
must stay powered, online, and connected to the printer. Recording still uses
the microphone attached to the Pi.

## Start a password-protected link

Run these steps **on the Pi**, in this repository's root, using its existing
Python virtual environment. Use Python 3.9 or newer.

1. Install the remote server and
   [cloudflared](https://developers.cloudflare.com/tunnel/downloads/):

   ```bash
   python -m pip install -r requirements-remote.txt
   cloudflared --version
   ```

2. Generate a password and save it as `SAMSON_PASSWORD` in the Pi's `.env` file.
   Keep its existing printer and microphone settings. Do not replace the file
   with an example. The username is **samson**.

   ```bash
   python -c 'import secrets; print(secrets.token_urlsafe(24))'
   ```

   Add these settings, substituting your generated password:

   ```dotenv
   SAMSON_PASSWORD=YOUR_GENERATED_PASSWORD
   SAMSON_REMOTE_ACCESS=true
   DEBUG=false
   ```

   `.env` is ignored by Git. Restrict access with `chmod 600 .env`. Passwords must
   be at least 16 characters; use the generated value, not a predictable phrase.

3. Stop the existing Samson app or service before starting the remote server.
   There must be only one application process controlling the printer and
   microphone. If your service is called `ticket-printer`:

   ```bash
   sudo systemctl stop ticket-printer
   ```

4. Start the website and temporary tunnel together:

   ```bash
   python serve_remote.py --tunnel
   ```

5. Open the **https://…trycloudflare.com** link printed in the terminal. In the
   Samson sign-in page, enter your generated password. No username is needed. Open
   that same link on your phone with Wi-Fi off to check remote access. Settings →
   **Check again** checks connectivity without printing. Then send a ticket when
   ready to test the physical printer.

The sign-in page is public; the website, assets, health checks, printing, and
microphone controls require authentication. Browser sessions last seven days
and use a signed, HttpOnly, SameSite cookie, marked Secure over HTTPS. Explicit
HTTP Basic credentials (username **samson**) remain supported for API clients.
Use this single link for both the website and API; leave
`productionApiUrl` and `window._env.REACT_APP_API_URL` unset in the frontend.
This password mode serves the frontend from the Pi, not a separate Netlify origin.

Keep the command running. Ctrl+C closes the tunnel and server. A
[Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
gets a new address each time, stops working when closed, and has no uptime
guarantee. Anyone you give the link **and password** can print and control the Pi
microphone. Use a private window on shared devices and close that window
afterward. Changing the password in `.env` and restarting also revokes existing
browser sessions.

## Keep the same link after a restart

For everyday use, create a
[named Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/get-started/)
with a domain in your Cloudflare account. Set its published application's service
URL to `http://127.0.0.1:5000` and retain the original public Host header. Install
the tunnel connector as a service using Cloudflare's setup instructions.

Run `python serve_remote.py` without `--tunnel` as the Pi's application service.
For an existing systemd service, set `WorkingDirectory` to this repository's root
and `ExecStart` to the absolute virtual-environment Python path followed by the
absolute path to `serve_remote.py`. Keep the existing service user and hardware
permissions. Enable both the application service and tunnel service at boot.
Do not run the legacy `backend/api.py` alongside it.

The server binds only to `127.0.0.1`, uses one Waitress process with eight threads,
and trusts only the local proxy's HTTPS scheme header. This keeps microphone
origin checks working over HTTPS and preserves shared printer/session state.
There is no router port forwarding. The old `http://PI_ADDRESS:5000` LAN address
is replaced by the shared HTTPS link while this server is running. `--port 5001`
can select another port; update the named tunnel's service URL to match.

## Troubleshooting

### Services installed on sd-pi

The current Pi installation runs `/home/sd/ticket-printer-os/serve_remote.py`
under `ticket-printer.service`, with a separate `samson-tunnel.service` for the
public connection. Both are enabled at boot and restart after failures. The
desktop Samson launcher opens the running service without starting a second
printer process. The Mac preview is no longer needed.

Run these commands on the Pi:

```bash
samson-link                              # Show the current public HTTPS address
sudo systemctl status ticket-printer samson-tunnel
sudo systemctl restart ticket-printer    # Restart the app, keeping the same link
sudo journalctl -u ticket-printer -n 50
```

The current tunnel is a Quick Tunnel: restarting `samson-tunnel` or rebooting the
Pi changes the address. Run `samson-link` or open the desktop Samson launcher to
find the new one. A stable address requires the named-tunnel setup above.
The password stays in the Pi's `.env` file. The pre-update backup is in
`/home/sd/ticket-printer-backups/`.

The Pi's `/etc/bluetooth/main.conf` already sets `ControllerMode = le`.
The redundant `bt-le-only.service` helper is disabled: its unbounded `btmgmt`
startup commands became stuck and blocked Bluetooth restarts. Its unit file is
backed up alongside the app, and the normal `bluetooth.service` remains enabled.

### Common issues

- **Printer busy or unresponsive, but the page loads:** printer operations run
  in one isolated daemon thread. Concurrent print requests return 503 without
  queuing; connection checks report `busy`, `checking`, or `unavailable` while
  the server remains healthy. An admitted print waits at most 90 seconds (504
  on timeout), and a connection check waits at most 5 seconds. Override these
  with positive `PRINTER_OPERATION_TIMEOUT` and `PRINTER_CHECK_TIMEOUT` values
  in seconds. The existing operation retains exclusive printer access until it
  actually exits; a timeout never starts a retry or a second hardware worker.
  Bluetooth calls additionally run in a child process: each write has a
  5-second deadline, disconnect has a 3-second deadline, and the entire process
  is killed and reaped after 60 seconds if the driver cannot be cancelled.
  This releases Bluetooth access for a later request without restarting the
  app. Packets are capped to the negotiated connection size, and no write is
  retried once sending starts, even if its first acknowledgement is lost.
  Check the paper before resending an unconfirmed ticket. Other printer
  drivers may still need `sudo systemctl restart ticket-printer` if they never
  return; this keeps the tunnel URL. A live-listening queue stops on a rejected
  or timed-out print rather than silently retrying it.

- **Missing password:** startup fails before opening a listener or tunnel. Set
  `SAMSON_PASSWORD` in the root `.env` and try again.
- **Port already in use:** stop the previous application. Do not start a second
  copy on another port to control the same printer.
- **cloudflared missing:** install it for the Pi's OS/CPU from the linked
  downloads page, then confirm `cloudflared --version` works.
- **Login keeps appearing:** open `/login` for Samson's password form. Cancel any
  old browser login popup and reload. Enter the password from the Pi's `.env`;
  **Show password** lets you check the pasted value. Cookies must be enabled.
- **Page opens but printer is offline:** check Settings. Remote connectivity does
  not replace the Pi's Bluetooth/USB connection to the printer.
- **Microphone receives a 403:** use `serve_remote.py` and the same public URL for
  the page and API. Do not override the Host header in the tunnel configuration.
- **502 / tunnel offline:** verify the Pi has Internet access and the server and
  tunnel are both running. Quick Tunnel links expire when their command stops.

## Verification without paper

```bash
SAMSON_PASSWORD= SAMSON_REMOTE_ACCESS=false python -m unittest discover -s tests -v
TEST_MODE=true python serve_remote.py --tunnel
```

The test command overrides your `.env` login settings for that test process only;
the authentication tests create their own protected app. Test mode renders ticket
previews without printing. Do not leave it enabled when
switching to the physical printer. The remote-access tests cover rejected
credentials, protected routes, cross-site requests, and microphone origin checks
through the actual Waitress proxy configuration.
