import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request

from flask import Flask
from PIL import Image

from memes import (IMAGE_HOSTS, MAX_IMAGE_BYTES, MemeSource, MemeUnavailable, PROVIDER_URL,
                   _SafeRedirect, allowed_url, create_meme_blueprint, download)
from remote_access import configure_remote_access


def meme(name, **fields):
    return dict(title=name, url=f'https://i.redd.it/{name}.png', nsfw=False, spoiler=False, **fields)


class MemeTests(unittest.TestCase):
    def setUp(self):
        image = io.BytesIO()
        Image.new('RGB', (12, 12), 'white').save(image, 'PNG')
        self.image = image.getvalue()
        shuffle = patch('memes.random.shuffle', side_effect=lambda values: None)
        shuffle.start()
        self.addCleanup(shuffle.stop)

    def test_bad_image_is_skipped_and_a_valid_image_is_returned_as_embedded_data(self):
        entries = [meme('missing'), meme('corrupt'), meme('working')]
        def fetch(url, *_):
            if url == PROVIDER_URL:
                return json.dumps({'memes': entries}).encode()
            if 'missing' in url:
                raise OSError('404')
            return b'<html>unavailable</html>' if 'corrupt' in url else self.image
        with patch('memes.download', side_effect=fetch) as upstream:
            result = MemeSource().get()
        self.assertEqual(upstream.call_count, 4)
        self.assertEqual(result['url'], entries[2]['url'])
        self.assertEqual(result['image'], 'data:image/png;base64,' + base64.b64encode(self.image).decode())

    def test_preview_is_used_when_the_original_cannot_be_downloaded(self):
        entry = meme('large', preview=['https://preview.redd.it/small.png'])
        def fetch(url, *_):
            if url == PROVIDER_URL:
                return json.dumps({'memes': [entry]}).encode()
            if url == entry['url']:
                raise ValueError('Too large')
            self.assertEqual(url, entry['preview'][0])
            return self.image
        with patch('memes.download', side_effect=fetch):
            self.assertEqual(MemeSource().get()['url'], entry['url'])

    def test_flagged_previous_and_unsupported_urls_are_never_downloaded(self):
        entries = [dict(meme('nsfw'), nsfw=True), dict(meme('spoiler'), spoiler=True), meme('previous'),
                   dict(meme('private'), url='http://127.0.0.1/private'), meme('new')]
        def fetch(url, *_):
            if url == PROVIDER_URL:
                return json.dumps({'memes': entries}).encode()
            self.assertEqual(url, entries[-1]['url'])
            return self.image
        with patch('memes.download', side_effect=fetch) as upstream:
            result = MemeSource().get(exclude=entries[2]['url'])
        self.assertEqual(upstream.call_count, 2)
        self.assertEqual(result['url'], entries[-1]['url'])

    def test_listing_retries_once_then_returns_a_friendly_error(self):
        with patch('memes.download', side_effect=[OSError('Temporary failure'),
                   json.dumps({'memes': [meme('ok')]}).encode(), self.image]):
            self.assertEqual(MemeSource().get()['title'], 'ok')
        for data in (b'not json', b'{"memes":null}', b'{"memes":[null,42]}'):
            with self.subTest(data=data), patch('memes.download', return_value=data) as upstream:
                with self.assertRaises(MemeUnavailable):
                    MemeSource().get()
                self.assertLessEqual(upstream.call_count, 2)

    def test_slow_provider_cannot_occupy_all_web_workers(self):
        source = MemeSource()
        release = threading.Event()
        entered = threading.Barrier(3)
        def stall(*_):
            entered.wait(timeout=2)
            release.wait(timeout=3)
            return {'title': 'Done'}
        with patch.object(source, '_fetch', side_effect=stall), ThreadPoolExecutor(max_workers=2) as callers:
            work = [callers.submit(source.get) for _ in range(2)]
            try:
                entered.wait(timeout=2)
                with self.assertRaisesRegex(MemeUnavailable, 'busy'):
                    source.get()
            finally:
                release.set()
            self.assertTrue(all(job.result(timeout=2)['title'] == 'Done' for job in work))
        with patch.object(source, '_fetch', return_value={'title': 'Recovered'}):
            self.assertEqual(source.get()['title'], 'Recovered')

    def test_download_limits_bytes_even_without_content_length_and_never_forwards_credentials(self):
        for headers, body in [({'Content-Length': str(MAX_IMAGE_BYTES + 1)}, b''), ({}, b'12345')]:
            response = io.BytesIO(body)
            response.headers = headers
            opener = Mock()
            opener.open.return_value = response
            with patch('memes.build_opener', return_value=opener), self.assertRaisesRegex(ValueError, 'large'):
                download('https://i.redd.it/test.png', IMAGE_HOSTS, 4, time.monotonic() + 2)
            request = opener.open.call_args.args[0]
            self.assertFalse(request.has_header('Authorization'))
            self.assertFalse(request.has_header('Cookie'))

    def test_download_and_redirect_validation_prevent_an_open_proxy(self):
        for url in ['http://i.redd.it/a.png', 'https://localhost/a.png', 'https://i.redd.it.evil.test/a.png',
                    'https://user:password@i.redd.it/a.png', 'https://i.redd.it:5000/a.png']:
            self.assertFalse(allowed_url(url, IMAGE_HOSTS))
            with self.assertRaises(ValueError):
                _SafeRedirect(IMAGE_HOSTS).redirect_request(Request('https://i.redd.it/a.png'), None,
                                                          302, '', {}, url)
        with patch('memes.build_opener') as opener, self.assertRaises(TimeoutError):
            download('https://i.redd.it/a.png', IMAGE_HOSTS, 100, time.monotonic() - 1)
        opener.assert_not_called()

    def test_large_pixel_dimensions_are_rejected(self):
        with patch('memes.download', side_effect=[json.dumps({'memes': [meme('large')]}).encode(), self.image]), \
                patch('memes.MAX_IMAGE_PIXELS', 100):
            with self.assertRaises(MemeUnavailable):
                MemeSource().get()

    def test_route_requires_existing_auth_and_never_fetches_the_exclude_parameter(self):
        app = Flask(__name__)
        source = Mock()
        source.get.return_value = {'title': 'Meme', 'url': 'https://i.redd.it/a.png', 'image': 'data:image/png;base64,a'}
        with patch.dict(os.environ, {'SAMSON_PASSWORD': 'test-password-for-memes', 'SAMSON_REMOTE_ACCESS': 'true'}):
            configure_remote_access(app)
        app.register_blueprint(create_meme_blueprint(source))
        client = app.test_client()
        self.assertEqual(client.get('/random-meme').status_code, 401)
        source.get.assert_not_called()
        auth = {'Authorization': 'Basic ' + base64.b64encode(b'samson:test-password-for-memes').decode()}
        response = client.get('/random-meme?exclude=http://127.0.0.1/private', headers=auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        source.get.assert_called_once_with('http://127.0.0.1/private')
        source.get.side_effect = MemeUnavailable('Temporarily unavailable; draft kept')
        self.assertEqual(client.get('/random-meme', headers=auth).status_code, 503)
