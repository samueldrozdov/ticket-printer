# Legacy Netlify deployment notes

**The current Samson site is served entirely by the Pi.** Use
[DEPLOYMENT.md](DEPLOYMENT.md) to deploy it, or [REMOTE_ACCESS.md](REMOTE_ACCESS.md)
to set up its password-protected HTTPS link.

Earlier versions used a Netlify frontend and a separately exposed Pi API. The
repository retains these files for that older integration:

| File | Purpose |
| --- | --- |
| `netlify.toml` | Publishes `frontend/` without a build step and configures functions/redirects |
| `netlify/functions/` | Legacy submission integration |
| `backend/api.py` | Older standalone ticket API |
| `backend/ticket-printer.service` | Example service for that older API |

The current frontend uses routes provided by the root `app.py`, including chat
printing, microphone control, and saved history. The older `backend/api.py` does
not implement that full API. Do not pair the current frontend with it or replace
the installed Pi service with the legacy service file.

The current password/session setup expects the website and API at the same
origin. A separate Netlify deployment would need its own tested authentication,
API routing, and browser-origin configuration. Setting a Netlify environment
variable alone does not inject it into these static files: the checked-in build
command only prints a message.

A GitHub-connected Netlify deployment, if separately configured, updates only
that Netlify site. It does not update the Pi's checkout or restart its app.
