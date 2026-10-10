import base64
import importlib.util
import os
import threading
import time
import unittest
from http.cookies import SimpleCookie
from http.client import HTTPConnection
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from unittest.mock import Mock, patch

from flask import Flask, jsonify

from microphone import create_microphone_blueprint
from remote_access import SESSION_COOKIE, SESSION_SECONDS, configure_remote_access, remote_password
from serve_remote import create_remote_server


PASSWORD = "test-only-password-for-samson"


def credentials(password=PASSWORD, username="samson"):
    value = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {value}"}


def protected_app(password=PASSWORD):
    app = Flask(__name__)
    with patch.dict(os.environ, {"SAMSON_PASSWORD": password, "SAMSON_REMOTE_ACCESS": "true"}):
        configure_remote_access(app)
    mic = Mock(enabled=True)
    mic.start.return_value = {"id": "recording", "state": "recording"}
    app.register_blueprint(create_microphone_blueprint(mic))
    printed = Mock()

    @app.post("/print")
    def print_ticket():
        printed()
        return jsonify(success=True)

    @app.get("/")
    def index():
        return "Samson"

    return app, mic, printed


class RemoteAccessTests(unittest.TestCase):
    def setUp(self):
        self.app, self.mic, self.printed = protected_app()
        self.client = self.app.test_client()

    def test_remote_mode_requires_a_strong_password(self):
        for password in ("", "short", " " * 20):
            with self.subTest(password=password), self.assertRaises(ValueError):
                remote_password({"SAMSON_REMOTE_ACCESS": "true", "SAMSON_PASSWORD": password})
        self.assertEqual(remote_password({"SAMSON_REMOTE_ACCESS": "true", "SAMSON_PASSWORD": PASSWORD}), PASSWORD)

    def test_local_mode_remains_optional_but_configured_password_is_always_checked(self):
        self.assertEqual(remote_password({}), "")
        self.assertEqual(remote_password({"SAMSON_PASSWORD": PASSWORD}), PASSWORD)
        app = Flask(__name__)
        with patch.dict(os.environ, {"SAMSON_PASSWORD": "", "SAMSON_REMOTE_ACCESS": "false"}):
            configure_remote_access(app)
        self.assertEqual(app.test_client().get("/missing").status_code, 404)

    def test_all_routes_require_auth_before_any_hardware_action(self):
        for method, path in [("GET", "/"), ("GET", "/index.html"), ("GET", "/chat.js"),
                             ("GET", "/health"), ("GET", "/history"), ("GET", "/history.js"),
                             ("POST", "/print"), ("POST", "/submit_ticket"),
                             ("GET", "/microphone"), ("POST", "/microphone/start"),
                             ("GET", "/microphone/session-id"), ("GET", "/microphone/live"),
                             ("POST", "/microphone/live/start"),
                             ("POST", "/microphone/live/session-id/stop")]:
            with self.subTest(path=path):
                response = self.client.open(path, method=method, json={})
                self.assertEqual(response.status_code, 302 if path == "/" else 401)
                self.assertNotIn("WWW-Authenticate", response.headers)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.mic.mock_calls, [])
        self.printed.assert_not_called()

    def test_invalid_credentials_are_rejected(self):
        for headers in (credentials("wrong"), credentials(username="other"),
                        {"Authorization": "Basic invalid!"}, {"Authorization": "Bearer token"},
                        credentials("é" * 16)):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.get("/health", headers=headers).status_code, 401)

    def test_valid_credentials_allow_page_print_and_microphone(self):
        self.assertEqual(self.client.get("/", headers=credentials()).status_code, 200)
        self.assertEqual(self.client.post("/print", json={}, headers=credentials()).status_code, 200)
        self.assertEqual(self.client.post("/microphone/start", json={}, headers=credentials()).status_code, 202)
        self.printed.assert_called_once()
        self.mic.start.assert_called_once()

    def test_other_websites_cannot_use_cached_credentials(self):
        for headers in ({"Origin": "https://other.example"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"}):
            for path in ("/print", "/microphone/start"):
                with self.subTest(path=path, headers=headers):
                    response = self.client.post(path, json={}, headers={**credentials(), **headers})
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.printed.assert_not_called()
        self.mic.start.assert_not_called()

    def test_browser_gets_a_form_without_a_native_password_prompt(self):
        response = self.client.get("/", headers=credentials("stale"), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome to Samson", response.data)
        self.assertIn(b'autocomplete="current-password"', response.data)
        self.assertNotIn("WWW-Authenticate", response.headers)
        self.assertNotIn(PASSWORD.encode(), response.data)

    def test_wrong_form_password_does_not_create_session_or_repeat_browser_prompt(self):
        response = self.client.post("/login", data={"password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertIn(b"Please try again", response.data)
        self.assertNotIn("WWW-Authenticate", response.headers)
        self.assertNotIn("Set-Cookie", response.headers)
        self.assertEqual(self.client.post("/print", json={}).status_code, 401)
        self.printed.assert_not_called()

    def login(self):
        response = self.client.post("/login", data={"password": PASSWORD},
                                    base_url="https://samson.example",
                                    headers={"Origin": "https://samson.example"})
        self.assertEqual(response.status_code, 303)
        return response

    def test_form_session_authenticates_page_and_hardware_despite_stale_basic_password(self):
        response = self.login()
        cookie = response.headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
            self.assertIn(flag, cookie)
        self.assertNotIn(PASSWORD, cookie)
        headers = {**credentials("stale"), "Origin": "https://samson.example"}
        self.assertEqual(self.client.get("/", base_url="https://samson.example", headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/print", json={}, base_url="https://samson.example", headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/microphone/start", json={}, base_url="https://samson.example", headers=headers).status_code, 202)
        self.assertEqual(self.client.get("/login", base_url="https://samson.example").status_code, 302)
        self.printed.assert_called_once()
        self.mic.start.assert_called_once()

    def test_session_cannot_authorize_cross_site_hardware_requests(self):
        self.login()
        for headers in ({"Origin": "https://other.example"}, {"Sec-Fetch-Site": "cross-site"}):
            response = self.client.post("/print", json={}, base_url="https://samson.example", headers=headers)
            self.assertEqual(response.status_code, 403)
        self.printed.assert_not_called()

    def test_cross_site_form_login_is_rejected(self):
        for headers in ({"Origin": "https://other.example"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"}):
            response = self.client.post("/login", data={"password": PASSWORD}, headers=headers)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("Set-Cookie", response.headers)

    def test_expired_session_requires_sign_in(self):
        self.login()
        with patch("itsdangerous.timed.time.time", return_value=time.time() + SESSION_SECONDS + 1):
            response = self.client.post("/print", json={}, base_url="https://samson.example")
        self.assertEqual(response.status_code, 401)
        self.printed.assert_not_called()

    def test_modified_session_is_rejected(self):
        token = SimpleCookie(self.login().headers["Set-Cookie"])[SESSION_COOKIE].value
        self.client.set_cookie(SESSION_COOKIE, token + "tampered", domain="samson.example")
        self.assertEqual(self.client.post("/print", json={}, base_url="https://samson.example").status_code, 401)
        self.printed.assert_not_called()

    def test_session_survives_restart_but_not_password_change(self):
        token = SimpleCookie(self.login().headers["Set-Cookie"])[SESSION_COOKIE].value
        for password, status in ((PASSWORD, 200), ("changed-test-password", 401)):
            app, _, printed = protected_app(password)
            client = app.test_client()
            client.set_cookie(SESSION_COOKIE, token)
            self.assertEqual(client.post("/print", json={}).status_code, status)
            self.assertEqual(printed.call_count, int(status == 200))

    def test_same_origin_and_private_response_headers(self):
        response = self.client.post("/print", json={}, base_url="https://samson.example",
                                    headers={**credentials(), "Origin": "https://samson.example"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    def test_direct_local_app_does_not_trust_forwarded_scheme(self):
        response = self.client.post("/microphone/start", json={}, base_url="http://samson.example",
                                   headers={**credentials(), "Origin": "https://samson.example",
                                            "X-Forwarded-Proto": "https"})
        self.assertEqual(response.status_code, 403)
        self.mic.start.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec("waitress"), "Install requirements-remote.txt for tunnel tests")
class TunnelProxyTests(unittest.TestCase):
    def setUp(self):
        app, self.mic, _ = protected_app()
        self.server = create_remote_server(app, 0)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.effective_port}"
        self.addCleanup(self.stop)

    def stop(self):
        self.server.task_dispatcher.shutdown()
        # Close sockets in the event-loop thread, after request workers finish.
        self.server.trigger.pull_trigger(lambda: self.server.asyncore.close_all(map=self.server._map))
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())

    def post_microphone(self, **headers):
        request = Request(self.url + "/microphone/start", data=b"{}",
                          headers={"Host": "samson.example", "Content-Type": "application/json", **headers})
        try:
            return urlopen(request, timeout=5)
        except HTTPError as error:
            return error

    def test_https_tunnel_preserves_same_origin_for_microphone(self):
        with self.post_microphone(**credentials(), Origin="https://samson.example",
                                  **{"X-Forwarded-Proto": "https"}) as response:
            self.assertEqual(response.status, 202)
        self.mic.start.assert_called_once()

    def test_tunnel_still_requires_password(self):
        with self.post_microphone(Origin="https://samson.example",
                                  **{"X-Forwarded-Proto": "https"}) as response:
            self.assertEqual(response.status, 401)
        self.mic.start.assert_not_called()

    def test_form_login_through_https_proxy_sets_secure_cookie_and_authenticates_api(self):
        connection = HTTPConnection("127.0.0.1", self.server.effective_port, timeout=5)
        self.addCleanup(connection.close)
        connection.request("POST", "/login", body=urlencode({"password": PASSWORD}), headers={
            "Host": "samson.example", "Origin": "https://samson.example",
            "X-Forwarded-Proto": "https", "Content-Type": "application/x-www-form-urlencoded"})
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 303)
        cookie = response.getheader("Set-Cookie")
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        token = SimpleCookie(cookie)[SESSION_COOKIE].value
        with self.post_microphone(Cookie=f"{SESSION_COOKIE}={token}", Origin="https://samson.example",
                                  **{"X-Forwarded-Proto": "https"}) as response:
            self.assertEqual(response.status, 202)
        self.mic.start.assert_called_once()

    def test_forwarded_host_cannot_authorize_a_foreign_origin(self):
        with self.post_microphone(**credentials(), Origin="https://other.example",
                                  **{"X-Forwarded-Proto": "https", "X-Forwarded-Host": "other.example"}) as response:
            self.assertEqual(response.status, 403)
        self.mic.start.assert_not_called()
