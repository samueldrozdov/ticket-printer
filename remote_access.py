"""Optional, whole-application password protection for an HTTPS tunnel."""
import hashlib
import hmac
import os

from flask import jsonify, redirect, render_template_string, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer


SESSION_COOKIE = "samson_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
LOGIN_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in · Samson</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100svh; display: grid; place-items: center;
      padding: 24px; background: #f5f5f7; color: #202124;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { width: 100%; max-width: 390px; background: white; padding: 32px;
      border-radius: 24px; box-shadow: 0 12px 40px #0000000a; }
    h1 { font-size: 28px; margin: 0 0 10px; letter-spacing: -.7px; }
    p { color: #65666c; line-height: 1.5; margin: 0 0 26px; }
    label { display: block; font-size: 14px; margin-bottom: 8px; }
    input[type=password], input[type=text] { width: 100%; padding: 14px;
      border: 1px solid #c9c9ce; border-radius: 12px; font-size: 16px; }
    input:focus-visible, button:focus-visible { outline: 3px solid #b7d7ff; outline-offset: 3px; }
    .show { display: flex; align-items: center; gap: 7px; margin: 14px 0 22px; }
    button { width: 100%; border: 0; border-radius: 12px; padding: 14px;
      background: #007aff; color: white; font-size: 16px; font-weight: 600; cursor: pointer; }
    .error { color: #b42318; margin: 0 0 16px; font-size: 14px; }
  </style>
</head>
<body>
<main>
  <h1>Welcome to Samson</h1>
  <p>Enter your password to send something worth putting on paper.</p>
  <form method="post" action="{{ url_for('samson_login') }}">
    <input type="hidden" name="username" value="samson" autocomplete="username">
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password"
      autocapitalize="none" spellcheck="false" required maxlength="1024"
      {% if error %}aria-invalid="true" aria-describedby="login-error"{% endif %}>
    <label class="show"><input id="show-password" type="checkbox"> Show password</label>
    {% if error %}<p id="login-error" class="error" role="alert">{{ error }}</p>{% endif %}
    <button type="submit">Sign in</button>
  </form>
</main>
<script>
  document.getElementById('show-password').addEventListener('change', function () {
    document.getElementById('password').type = this.checked ? 'text' : 'password';
  });
</script>
</body>
</html>"""


def remote_password(environ=None):
    environ = os.environ if environ is None else environ
    password = environ.get("SAMSON_PASSWORD", "")
    required = environ.get("SAMSON_REMOTE_ACCESS", "false").lower() == "true"
    if required and not password:
        raise ValueError("Set SAMSON_PASSWORD before enabling remote access. See REMOTE_ACCESS.md.")
    if password and (len(password) < 16 or not password.strip()):
        raise ValueError("SAMSON_PASSWORD must contain at least 16 characters. Use a random password.")
    return password


def configure_remote_access(app):
    password = remote_password()
    app.config["SAMSON_PASSWORD_REQUIRED"] = bool(password)
    if not password:
        return

    expected = password.encode("utf-8")
    # A password change revokes existing sessions; a process restart does not.
    signing_key = hmac.new(expected, b"samson-browser-session-v1", hashlib.sha256).digest()
    sessions = URLSafeTimedSerializer(signing_key, salt="samson-login")

    def signed_in():
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return False
        try:
            return sessions.loads(token, max_age=SESSION_SECONDS) == "samson"
        except BadSignature:
            return False

    def foreign_request():
        origin = request.headers.get("Origin")
        return ((origin and origin != request.host_url.rstrip("/")) or
                (request.headers.get("Sec-Fetch-Site") == "cross-site" and
                 request.method not in {"GET", "HEAD"}))

    @app.route("/login", methods=["GET", "POST"], endpoint="samson_login")
    def login():
        if request.method == "GET":
            if signed_in():
                return redirect(url_for("index"))
            return render_template_string(LOGIN_PAGE, error=None)
        if foreign_request():
            return render_template_string(LOGIN_PAGE, error="Open Samson directly at its shared link."), 403
        supplied = request.form.get("password", "").encode("utf-8")
        if not hmac.compare_digest(supplied, expected):
            return render_template_string(LOGIN_PAGE, error="That password didn’t match. Please try again."), 401
        response = redirect(url_for("index"), code=303)
        response.set_cookie(SESSION_COOKIE, sessions.dumps("samson"), max_age=SESSION_SECONDS,
                            secure=request.is_secure, httponly=True, samesite="Lax")
        return response

    @app.before_request
    def require_password():
        if request.endpoint == "samson_login":
            return
        # Keep explicit Basic credentials for API clients, but never challenge a
        # browser with a native login dialog. A valid cookie also overrides stale
        # credentials that the browser cached before form login was introduced.
        auth = request.authorization
        basic_valid = (auth and auth.type.lower() == "basic" and auth.username == "samson"
                       and hmac.compare_digest((auth.password or "").encode("utf-8"), expected))
        if not signed_in() and not basic_valid:
            if request.path == "/" and request.method in {"GET", "HEAD"}:
                return redirect(url_for("samson_login"))
            response = jsonify(success=False, error="Sign in to Samson to continue.")
            response.status_code = 401
            return response

        # Cookies and credentials can be attached automatically by browsers. Do not
        # let another website use them to print or control the Pi microphone.
        if foreign_request():
            return jsonify(success=False, error="Open Samson directly at its shared link."), 403

    @app.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response
