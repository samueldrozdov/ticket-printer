import base64
import io
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from ticket_layout import render_ticket, ticket_payload

import app as printer_app


def preview_image(response):
    return Image.open(io.BytesIO(base64.b64decode(response.json['preview']['image'].split(',')[1])))


def printed_image(payload):
    """Independently decode the actual ESC/POS stream to check preview parity."""
    assert payload[:5] == b'\x1b@\x1ba\x00'
    offset = 5
    bands = []
    while payload[offset:offset + 4] == b'\x1dv0\x00':
        width_bytes = int.from_bytes(payload[offset + 4:offset + 6], 'little')
        height = int.from_bytes(payload[offset + 6:offset + 8], 'little')
        end = offset + 8 + width_bytes * height
        pixels = bytes(value ^ 255 for value in payload[offset + 8:end])
        bands.append(Image.frombytes('1', (width_bytes * 8, height), pixels))
        offset = end
    while payload[offset:offset + 2] == b'\x1bJ':
        bands.append(Image.new('1', (bands[0].width, payload[offset + 2]), 1))
        offset += 3
    assert payload[offset:] == b'\x1dV\x00', 'Expected exactly one final cut and no extra commands'
    image = Image.new('1', (bands[0].width, sum(band.height for band in bands)))
    top = 0
    for band in bands:
        image.paste(band, (0, top))
        top += band.height
    return image


class ChatPrintTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        history = patch.object(printer_app, 'print_history', printer_app.PrintHistory(Path(directory.name) / 'history.sqlite3'))
        history.start()
        self.addCleanup(history.stop)
        self.client = printer_app.app.test_client()
        image = io.BytesIO()
        # Color and gray pixels exercise resizing, contrast, and dithering.
        photo = Image.new('RGB', (768, 96), '#3d72ac')
        photo.paste('#999999', (0, 0, 384, 48))
        photo.paste('white', (384, 48, 768, 96))
        photo.save(image, 'PNG')
        self.photo = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
        self.test_mode = patch.object(printer_app, 'TEST_MODE', False)
        self.test_mode.start()
        self.addCleanup(self.test_mode.stop)

    def test_chat_assets_are_served_by_the_pi(self):
        for path, content_type in [('/', 'text/html'), ('/chat.css', 'text/css'),
                                   ('/chat.js', 'javascript'), ('/history.js', 'javascript'),
                                   ('/live-listening.js', 'javascript')]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(content_type, response.content_type)
                response.close()

    def assert_preview_matches_print(self, response, payload):
        preview = preview_image(response)
        printed = printed_image(payload)
        self.assertEqual(preview.size, printed.size)
        self.assertEqual(preview.tobytes(), printed.tobytes())
        self.assertEqual(preview.size, (response.json['preview']['width'], response.json['preview']['height']))

    def test_text_preview_is_the_exact_ble_raster_with_one_timestamp(self):
        with patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', 'test-printer'), \
                patch.object(printer_app, 'format_date_string', return_value='9:05:17 AM on 10/10/2026') as date, \
                patch.object(printer_app, 'ble_print_raster_ticket') as transport:
            result = self.client.post('/print', json={'type': 'text', 'content': 'Hello Pi'})
        self.assertEqual(result.status_code, 200)
        date.assert_called_once()
        transport.assert_called_once()
        self.assertEqual(transport.call_args.args[0], 'test-printer')
        self.assert_preview_matches_print(result, transport.call_args.args[1])
        self.assertEqual(result.json['preview']['text'], '--------------------------------\n9:05:17 AM on 10/10/2026\n\nHello Pi\n\n')
        self.assertFalse(result.json['test_mode'])

    def test_ble_photo_and_caption_are_one_print_operation(self):
        with patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', 'test-printer'), \
                patch.object(printer_app, 'ble_print_raster_ticket') as print_image, \
                patch.object(printer_app, 'ble_print_text') as print_text:
            result = self.client.post('/print', json={
                'type': 'image', 'content': self.photo, 'caption': 'A little reminder'
            })
        self.assertEqual(result.status_code, 200)
        print_image.assert_called_once()
        self.assertEqual(print_image.call_args.args[0], 'test-printer')
        self.assertIn('A little reminder', result.json['preview']['text'])
        self.assert_preview_matches_print(result, print_image.call_args.args[1])
        preview = preview_image(result)
        # The 768 x 96 photo fits at 384 x 48, immediately above the 72-dot feed.
        photo_pixels = preview.crop((0, preview.height - 120, preview.width, preview.height - 72))
        self.assertEqual(photo_pixels.getextrema(), (0, 255))
        print_text.assert_not_called()

    def test_date_can_be_omitted_from_text_and_photo_without_changing_preview_parity(self):
        for body in [{'type': 'text', 'content': 'No date, please'},
                     {'type': 'image', 'content': self.photo, 'caption': 'No date, please'},
                     {'type': 'image', 'content': self.photo}]:
            with self.subTest(type=body['type'], caption=body.get('caption')), \
                    patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                    patch.object(printer_app, 'BLE_PRINTER_ADDR', 'test-printer'), \
                    patch.object(printer_app, 'format_date_string') as date, \
                    patch.object(printer_app, 'ble_print_raster_ticket') as transport:
                response = self.client.post('/print', json={**body, 'include_date': False})
                self.assertEqual(response.status_code, 200)
                date.assert_not_called()
                text = body['content'] if body['type'] == 'text' else body.get('caption', '')
                self.assertEqual(response.json['preview']['text'], f'--------------------------------\n{text}\n\n')
                self.assert_preview_matches_print(response, transport.call_args.args[1])

    def test_date_preference_must_be_boolean_before_printing(self):
        with patch.object(printer_app, 'get_printer') as printer, \
                patch.object(printer_app, 'ble_print_raster_ticket') as transport:
            for value in ['false', 0, 1, None, []]:
                response = self.client.post('/print', json={'content': 'Hello', 'include_date': value})
                self.assertEqual(response.status_code, 400)
            printer.assert_not_called()
            transport.assert_not_called()

    def test_message_spacing_changes_only_blank_feed_and_matches_both_transports(self):
        for transport_type in ['usb', 'ble']:
            for body in [{'type': 'text', 'content': 'Hello'},
                         {'type': 'image', 'content': self.photo, 'caption': 'Hello'}]:
                with self.subTest(transport=transport_type, kind=body['type']), \
                        patch.object(printer_app, 'PRINTER_TYPE', transport_type), \
                        patch.object(printer_app, 'BLE_PRINTER_ADDR', 'test-printer'), \
                        patch.object(printer_app, 'ble_print_raster_ticket') as bluetooth, \
                        patch.object(printer_app, 'get_printer', return_value=Mock()) as device:
                    images = []
                    for lines in [0, 3, 10]:
                        response = self.client.post('/print', json={**body, 'include_date': False, 'feed_lines': lines})
                        self.assertEqual(response.status_code, 200)
                        payload = bluetooth.call_args.args[1] if transport_type == 'ble' else device.return_value._raw.call_args.args[0]
                        self.assert_preview_matches_print(response, payload)
                        images.append(preview_image(response))
                    content, normal, longest = images
                    self.assertEqual(normal.height - content.height, 72)
                    self.assertEqual(longest.height - content.height, 240)
                    self.assertEqual(longest.crop((0, 0, content.width, content.height)).tobytes(), content.tobytes())
                    self.assertEqual(longest.crop((0, content.height, longest.width, longest.height)).getextrema(), (255, 255))
                    default = self.client.post('/print', json={**body, 'include_date': False})
                    self.assertEqual(preview_image(default).tobytes(), normal.tobytes())

    def test_invalid_message_spacing_is_rejected_before_any_print_or_history_record(self):
        with patch.object(printer_app, 'get_printer') as printer, \
                patch.object(printer_app, 'ble_print_raster_ticket') as bluetooth, \
                patch.object(printer_app.print_history, 'record') as history:
            for value in [-1, 11, 1.5, '3', True, False, None, [], {}]:
                with self.subTest(value=value):
                    response = self.client.post('/print', json={'content': 'Hello', 'feed_lines': value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn('0 to 10', response.json['error'])
            printer.assert_not_called()
            bluetooth.assert_not_called()
            history.assert_not_called()

    def test_blank_margin_uses_compact_feed_and_preserves_exact_ticket_pixels(self):
        payloads = []
        for lines in [0, 3, 10]:
            ticket = render_ticket('Feed test\n', feed_lines=lines)
            payload = ticket_payload(ticket)
            reconstructed = printed_image(payload)
            self.assertEqual(reconstructed.size, ticket.size)
            self.assertEqual(reconstructed.tobytes(), ticket.tobytes())
            payloads.append(payload)
        # Ten extra blank lines used to require 11,520 bytes of raster data.
        self.assertLessEqual(len(payloads[-1]) - len(payloads[0]), 3)

    def test_white_tickets_and_long_content_preserve_feed_and_band_boundaries(self):
        for ticket in [Image.new('1', (384, height), 1) for height in [1, 24, 240, 480, 601]] + [
                render_ticket(('Long ticket\n' * 40) + 'Last line', feed_lines=10)]:
            with self.subTest(height=ticket.height):
                payload = ticket_payload(ticket)
                reconstructed = printed_image(payload)
                self.assertEqual(reconstructed.size, ticket.size)
                self.assertEqual(reconstructed.tobytes(), ticket.tobytes())

    def test_background_print_honors_date_preference(self):
        with patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', 'test-printer'), \
                patch.object(printer_app, 'format_date_string', return_value='TIMESTAMP'), \
                patch.object(printer_app, 'ble_print_text') as transport:
            printer_app.print_text_content('Spoken words', include_date=False)
            self.assertNotIn('TIMESTAMP', transport.call_args.args[1])
            self.assertIn('Spoken words', transport.call_args.args[1])
            printer_app.print_text_content('Spoken words', include_date=True)
            self.assertIn('TIMESTAMP', transport.call_args.args[1])

    def test_font_choices_match_the_printer_and_saved_preview_for_text_and_photos(self):
        for transport_type in ['usb', 'ble']:
            for family in ['mono', 'sans', 'serif']:
                for size in ['small', 'medium', 'large']:
                    for body in [{'content': 'Wide WWW and narrow iii.\nA message with café and descenders: jgy.'},
                                 {'type': 'image', 'content': self.photo, 'caption': 'A photo with a caption'}]:
                        with self.subTest(transport=transport_type, family=family, size=size, kind=body.get('type', 'text')), \
                                patch.object(printer_app, 'PRINTER_TYPE', transport_type), \
                                patch.object(printer_app, 'BLE_PRINTER_ADDR', 'test-printer'), \
                                patch.object(printer_app, 'ble_print_raster_ticket') as bluetooth, \
                                patch.object(printer_app, 'get_printer', return_value=Mock()) as device:
                            response = self.client.post('/print', json={**body, 'font_family': family, 'font_size': size})
                            self.assertEqual(response.status_code, 200)
                            payload = bluetooth.call_args.args[1] if transport_type == 'ble' else device.return_value._raw.call_args.args[0]
                            self.assert_preview_matches_print(response, payload)
                            saved = self.client.get('/history?limit=1').json['entries'][0]
                            self.assertEqual(saved['preview'], response.json['preview'])

    def test_invalid_font_choices_are_rejected_before_printing(self):
        with patch.object(printer_app, 'get_printer') as printer, \
                patch.object(printer_app, 'ble_print_raster_ticket') as bluetooth, \
                patch.object(printer_app.print_history, 'record') as history:
            for field in ['font_family', 'font_size']:
                for value in [None, True, 20, [], {}, '', '../../font.ttf', 'unsupported']:
                    with self.subTest(field=field, value=value):
                        response = self.client.post('/print', json={'content': 'Hello', field: value})
                        self.assertEqual(response.status_code, 400)
            printer.assert_not_called()
            bluetooth.assert_not_called()
            history.assert_not_called()

    def test_escpos_caption_and_photo_share_one_cut(self):
        printer = Mock()
        with patch.object(printer_app, 'PRINTER_TYPE', 'usb'), \
                patch.object(printer_app, 'get_printer', return_value=printer):
            result = self.client.post('/print', json={
                'type': 'image', 'content': self.photo, 'caption': 'From the chat'
            })
        self.assertEqual(result.status_code, 200)
        self.assertIn('From the chat', result.json['preview']['text'])
        printer._raw.assert_called_once()
        self.assert_preview_matches_print(result, printer._raw.call_args.args[0])
        printer.close.assert_called_once()

    def test_photo_without_caption_remains_supported(self):
        with patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', 'test-printer'), \
                patch.object(printer_app, 'ble_print_raster_ticket') as print_image:
            result = self.client.post('/print', json={'type': 'image', 'content': self.photo})
        self.assertEqual(result.status_code, 200)
        print_image.assert_called_once()
        self.assert_preview_matches_print(result, print_image.call_args.args[1])

    def test_invalid_messages_are_rejected_before_touching_printer(self):
        invalid = [
            {'type': 'audio', 'content': 'hello'},
            {'type': 'text', 'content': '   '},
            {'type': 'text', 'content': 42},
            {'type': 'text', 'content': 'x' * 1001},
            {'type': 'image', 'content': self.photo, 'caption': 'x' * 1001},
            {'type': 'image', 'content': self.photo, 'caption': ['bad']},
            ['invalid'],
        ]
        with patch.object(printer_app, 'get_printer') as get_printer, \
                patch.object(printer_app, 'print_text_content') as print_text, \
                patch.object(printer_app, 'ble_print_raster_ticket') as print_image:
            for body in invalid:
                with self.subTest(body_type=type(body).__name__):
                    self.assertEqual(self.client.post('/print', json=body).status_code, 400)
            get_printer.assert_not_called()
            print_text.assert_not_called()
            print_image.assert_not_called()

    def test_corrupt_image_cannot_be_confirmed_as_printed(self):
        with patch.object(printer_app, 'PRINTER_TYPE', 'usb'), \
                patch.object(printer_app, 'get_printer') as get_printer:
            result = self.client.post('/print', json={'type': 'image', 'content': 'not an image'})
        self.assertEqual(result.status_code, 400)
        self.assertFalse(result.json['success'])
        get_printer.assert_not_called()

    def test_test_mode_rejects_corrupt_images_too(self):
        with patch.object(printer_app, 'TEST_MODE', True):
            result = self.client.post('/print', json={'type': 'image', 'content': 'not an image'})
        self.assertEqual(result.status_code, 400)

    def test_test_mode_is_explicit_for_both_message_types(self):
        with patch.object(printer_app, 'TEST_MODE', True), \
                patch.object(printer_app, 'get_printer') as get_printer, \
                patch.object(printer_app, 'ble_print_raster_ticket') as print_image:
            for body in [{'type': 'text', 'content': 'Hello'},
                         {'type': 'image', 'content': self.photo, 'caption': 'Photo'}]:
                result = self.client.post('/print', json=body)
                self.assertEqual(result.status_code, 200)
                self.assertTrue(result.json['test_mode'])
                self.assertEqual(preview_image(result).mode, '1')
            self.assertTrue(self.client.get('/health').json['test_mode'])
            get_printer.assert_not_called()
            print_image.assert_not_called()

    def test_long_text_is_not_truncated_or_resized(self):
        content = ('Long message with line breaks.\n' * 30) + 'THE END'
        with patch.object(printer_app, 'PRINTER_TYPE', 'ble'), \
                patch.object(printer_app, 'BLE_PRINTER_ADDR', 'test-printer'), \
                patch.object(printer_app, 'ble_print_raster_ticket') as transport:
            result = self.client.post('/print', json={'content': content})
        self.assertEqual(result.status_code, 200)
        self.assertIn(content, result.json['preview']['text'])
        self.assertGreater(preview_image(result).height, 800)
        self.assert_preview_matches_print(result, transport.call_args.args[1])

    def test_failed_print_closes_device_and_returns_no_preview(self):
        printer = Mock()
        printer._raw.side_effect = RuntimeError('USB unplugged')
        with patch.object(printer_app, 'PRINTER_TYPE', 'usb'), \
                patch.object(printer_app, 'get_printer', return_value=printer):
            result = self.client.post('/print', json={'content': 'Keep my draft'})
        self.assertEqual(result.status_code, 500)
        self.assertFalse(result.json['success'])
        self.assertNotIn('preview', result.json)
        printer.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
