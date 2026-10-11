"""Fetch a validated meme through Samson, independent of browser CORS rules."""

import base64
import io
import json
import logging
import random
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from flask import Blueprint, jsonify, request
from PIL import Image


logger = logging.getLogger(__name__)
PROVIDER_URL = "https://meme-api.com/gimme/memes/5"
PROVIDER_HOSTS = {"meme-api.com"}
IMAGE_HOSTS = {"i.redd.it", "preview.redd.it", "i.imgur.com"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
FETCH_SECONDS = 12
IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}


def allowed_url(url, hosts):
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > 4096:
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.hostname in hosts and parsed.port in (None, 443) and
                not parsed.username and not parsed.password and
                not any(ord(character) < 32 for character in url))
    except ValueError:
        return False


class _SafeRedirect(HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl, self.hosts):
            raise ValueError("Unsupported image redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, hosts, byte_limit, deadline):
    if not allowed_url(url, hosts):
        raise ValueError("Unsupported meme source")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Meme download deadline exceeded")
    # Do not forward the browser's cookies, password, or other request headers.
    upstream = Request(url, headers={"User-Agent": "Samson/1.0", "Accept": "application/json,image/*"})
    opener = build_opener(_SafeRedirect(hosts))
    with opener.open(upstream, timeout=min(4, remaining)) as response:
        if int(response.headers.get("Content-Length", "0")) > byte_limit:
            raise ValueError("Meme source is too large")
        body = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Meme download deadline exceeded")
            chunk = response.read1(min(65536, byte_limit + 1 - len(body)))
            if not chunk:
                return bytes(body)
            body.extend(chunk)
            if len(body) > byte_limit:
                raise ValueError("Meme source is too large")


class MemeUnavailable(RuntimeError):
    pass


class MemeSource:
    def __init__(self):
        # Even an unresponsive upstream can occupy at most two HTTP workers.
        self._slots = threading.BoundedSemaphore(2)

    def get(self, exclude=""):
        if not self._slots.acquire(blocking=False):
            raise MemeUnavailable("Meme requests are busy. Try again shortly.")
        try:
            return self._fetch(exclude)
        except MemeUnavailable:
            raise
        except Exception as error:
            logger.warning("Meme provider unavailable: %s", type(error).__name__)
            raise MemeUnavailable("Couldn’t load a random meme. Try again.") from error
        finally:
            self._slots.release()

    def _fetch(self, exclude):
        deadline = time.monotonic() + FETCH_SECONDS
        # One retry for a transient failure of the listing, within the same budget.
        for attempt in range(2):
            try:
                listing = json.loads(download(PROVIDER_URL, PROVIDER_HOSTS, 256 * 1024, deadline))
                if not isinstance(listing, dict) or not isinstance(listing.get("memes"), list):
                    raise ValueError("Invalid meme listing")
                break
            except Exception:
                if attempt or time.monotonic() >= deadline:
                    raise
        choices = [meme for meme in listing["memes"][:5] if isinstance(meme, dict) and
                   meme.get("nsfw") is False and meme.get("spoiler") is False and
                   allowed_url(meme.get("url"), IMAGE_HOSTS) and meme["url"] != exclude]
        random.shuffle(choices)
        for meme in choices:
            previews = meme.get("preview", [])
            urls = [meme["url"]] + (list(reversed(previews)) if isinstance(previews, list) else [])
            urls = list(dict.fromkeys(url for url in urls if allowed_url(url, IMAGE_HOSTS)))[:2]
            for url in urls:
                try:
                    data = download(url, IMAGE_HOSTS, MAX_IMAGE_BYTES, deadline)
                    with Image.open(io.BytesIO(data)) as image:
                        mime = IMAGE_TYPES.get(image.format)
                        if not mime or image.width * image.height > MAX_IMAGE_PIXELS:
                            raise ValueError("Unsupported meme image")
                        if getattr(image, "is_animated", False):
                            raise ValueError("Animated memes are not supported")
                        image.load()  # Reject corrupt images before changing the user's draft.
                    title = meme.get("title")
                    return {"image": f"data:{mime};base64," + base64.b64encode(data).decode("ascii"),
                            "title": title[:300] if isinstance(title, str) else "Random meme", "url": meme["url"]}
                except Exception as error:
                    logger.info("Skipping unavailable meme image: %s", type(error).__name__)
                    if time.monotonic() >= deadline:
                        raise
        raise MemeUnavailable("No new meme could be loaded. Try again.")


def create_meme_blueprint(source=None):
    source = source if source is not None else MemeSource()
    api = Blueprint("memes", __name__)

    @api.get("/random-meme")
    def random_meme():
        try:
            # This value only excludes a previous result; it is never fetched.
            result = source.get(request.args.get("exclude", "")[:4096])
            response = jsonify(success=True, **result)
        except MemeUnavailable as error:
            response = jsonify(success=False, error=str(error))
            response.status_code = 503
        response.headers["Cache-Control"] = "no-store"
        return response

    return api
