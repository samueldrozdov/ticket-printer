import unittest
from unittest.mock import patch

from PIL import Image

import ble_printer
from ticket_layout import ticket_lines, render_ticket, ticket_payload, ticket_font


class TicketLayoutTests(unittest.TestCase):
    def test_wrap_preserves_blank_lines_indentation_and_long_words(self):
        self.assertEqual(ticket_lines('A' * 33 + '\n\n  indent\r\nend\n', 384),
                         ['A' * 32, 'A', '', '  indent', 'end', ''])

    def test_tabs_and_controls_cannot_change_the_printer_layout(self):
        self.assertEqual(ticket_lines('a\tb\x1b@', 384), ['a   b?@'])

    def test_proportional_fonts_wrap_wide_and_narrow_glyphs_without_losing_text(self):
        text = 'WWWW  iii café jgy AV ' * 20
        for family in ['sans', 'serif']:
            for size in ['small', 'medium', 'large']:
                with self.subTest(family=family, size=size):
                    font = ticket_font(family, size)
                    lines = ticket_lines(text, 384, font=font)
                    self.assertEqual(''.join(lines), text)
                    self.assertGreater(len(lines), 1)
                    for line in lines:
                        left, _, right, _ = font.getbbox(line)
                        self.assertLessEqual(max(font.getlength(line), right) - min(0, left), 384)

    def test_font_sizes_change_the_rendered_layout_and_fonts_have_distinct_pixels(self):
        text = 'Read this reminder.\n' * 4
        renders = []
        for family in ['mono', 'sans', 'serif']:
            images = [render_ticket(text, font_family=family, font_size=size)
                      for size in ['small', 'medium', 'large']]
            self.assertLess(images[0].height, images[1].height)
            self.assertLess(images[1].height, images[2].height)
            self.assertTrue(all(image.width == 384 for image in images))
            renders.append(images[1].tobytes())
        self.assertEqual(len(set(renders)), 3)

    def test_separator_is_one_standard_row_independent_of_message_typography(self):
        standard = render_ticket('-' * 32, feed_lines=0)
        self.assertEqual(standard.size, (384, 24))
        # Dashes in the user's message still follow the selected typography.
        text = 'A message\n' + '-' * 32
        for family in ['mono', 'sans', 'serif']:
            for size in ['small', 'medium', 'large']:
                for photo in [None, Image.new('RGB', (100, 50), 'black')]:
                    with self.subTest(family=family, size=size, photo=photo is not None):
                        body = render_ticket(text, photo, font_family=family, font_size=size)
                        ticket = render_ticket(text, photo, font_family=family, font_size=size,
                                               include_separator=True)
                        self.assertEqual(ticket.size, (body.width, body.height + 24))
                        self.assertEqual(ticket.crop((0, 0, ticket.width, 24)).tobytes(), standard.tobytes())
                        self.assertEqual(ticket.crop((0, 24, ticket.width, ticket.height)).tobytes(),
                                         body.tobytes())

    def test_narrow_and_tall_photos_still_have_at_least_one_pixel(self):
        image = ble_printer.prepare_thermal_image(Image.new('RGB', (1, 1600)))
        self.assertEqual(image.size, (1, 800))

    def test_odd_width_raster_padding_is_white(self):
        # Only the real black pixel may print; the seven padding bits stay off.
        self.assertEqual(ble_printer.encode_raster(Image.new('1', (1, 1), 0)),
                         b'\x1dv0\x00\x01\x00\x01\x00\x80')

    def test_ble_transport_sends_prepared_ticket_bytes_unchanged(self):
        payload = ticket_payload(render_ticket('hello\n'))
        with patch.object(ble_printer, '_print_in_process') as write:
            ble_printer.ble_print_raster_ticket('printer', payload)
        write.assert_called_once_with('printer', payload,
                                     ble_printer.BLE_IMAGE_CHUNK_SIZE,
                                     ble_printer.BLE_IMAGE_WRITE_GAP_SEC)


if __name__ == '__main__':
    unittest.main()
