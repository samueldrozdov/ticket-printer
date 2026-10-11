"""Render chat tickets once for both the thermal printer and browser preview."""
import base64
import io
import math
from functools import lru_cache
from pathlib import Path

from barcode.writer import ImageWriter
from PIL import Image, ImageChops, ImageDraw, ImageFont

from ble_printer import IMAGE_MAX_WIDTH, encode_raster, prepare_thermal_image

CELL_WIDTH = 12
LINE_HEIGHT = 24
STANDARD_SEPARATOR = '-' * 32
DEFAULT_FEED_LINES = 6
MAX_FEED_LINES = 12
DEFAULT_FONT_FAMILY = 'mono'
DEFAULT_FONT_SIZE = 'medium'
FONT_SIZES = {'small': 16, 'medium': 20, 'large': 28}
FONT_FILES = {'sans': 'DejaVuSans.ttf', 'serif': 'DejaVuSerif.ttf'}


def validate_typography(font_family, font_size):
    if not isinstance(font_family, str) or font_family not in ('mono', 'sans', 'serif'):
        raise ValueError('Choose a Monospace, Sans, or Serif font')
    if not isinstance(font_size, str) or font_size not in FONT_SIZES:
        raise ValueError('Choose a small, medium, or large font size')
    return font_family, font_size


@lru_cache(maxsize=9)
def ticket_font(font_family=DEFAULT_FONT_FAMILY, font_size=DEFAULT_FONT_SIZE):
    # python-escpos already depends on python-barcode, which ships this font.
    # Use the bundled font so a Pi and a development machine render identically.
    validate_typography(font_family, font_size)
    path = ImageWriter().font_path if font_family == 'mono' else Path(__file__).parent / 'fonts' / FONT_FILES[font_family]
    return ImageFont.truetype(str(path), FONT_SIZES[font_size])


def ticket_lines(text, width, cell_width=CELL_WIDTH, font=None):
    """Preserve whitespace, wrapping by fixed columns or proportional glyph width."""
    columns = max(1, width // cell_width)
    text = text.replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)
    # Control characters are not printer commands and must not change the layout.
    text = ''.join(char if char == '\n' or char.isprintable() else '?' for char in text)
    lines = []
    for line in text.split('\n'):
        if font is None:
            lines.extend([line[start:start + columns] for start in range(0, len(line), columns)] or [''])
            continue
        current = ''
        for char in line:
            candidate = current + char
            left, _, right, _ = font.getbbox(candidate)
            measured_width = max(font.getlength(candidate), right) - min(0, left)
            if current and measured_width > width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return lines


def validate_feed_lines(feed_lines):
    if type(feed_lines) is not int or not 0 <= feed_lines <= MAX_FEED_LINES:
        raise ValueError(f'Space after message must be a whole number from 0 to {MAX_FEED_LINES} lines')
    return feed_lines


def render_separator(width):
    """Render the standard dashed separator as one fixed-size row."""
    separator = Image.new('1', (width, LINE_HEIGHT), 1)
    draw = ImageDraw.Draw(separator)
    font = ticket_font()
    for column, char in enumerate(STANDARD_SEPARATOR[:width // CELL_WIDTH]):
        draw.text((column * CELL_WIDTH, 0), char, font=font, fill=0, anchor='la')
    return separator


def render_ticket(text, photo=None, feed_lines=DEFAULT_FEED_LINES,
                  font_family=DEFAULT_FONT_FAMILY, font_size=DEFAULT_FONT_SIZE,
                  include_separator=False):
    """Return the full 1-bit ticket, with no height limit on text."""
    width = IMAGE_MAX_WIDTH
    if width < CELL_WIDTH or width % 8:
        raise ValueError('IMAGE_MAX_WIDTH must be a multiple of 8 and at least 16')
    validate_typography(font_family, font_size)
    font = ticket_font(font_family, font_size)
    cell_width = round(CELL_WIDTH * font.size / FONT_SIZES[DEFAULT_FONT_SIZE])
    line_height = math.ceil(LINE_HEIGHT * font.size / FONT_SIZES[DEFAULT_FONT_SIZE])
    lines = ticket_lines(text, width, cell_width, font if font_family != 'mono' else None)
    photo = prepare_thermal_image(photo, max_width=width) if photo is not None else None
    separator = render_separator(width) if include_separator else None
    text_top = separator.height if separator is not None else 0
    text_height = text_top + len(lines) * line_height
    height = text_height + (photo.height if photo is not None else 0) + validate_feed_lines(feed_lines) * LINE_HEIGHT
    ticket = Image.new('1', (width, height), 1)
    if separator is not None:
        ticket.paste(separator, (0, 0))
    draw = ImageDraw.Draw(ticket)
    for row, line in enumerate(lines):
        top = text_top + row * line_height
        if font_family == 'mono':
            for column, char in enumerate(line):
                draw.text((column * cell_width, top), char,
                          font=font, fill=0, anchor='la')
        else:
            left = font.getbbox(line)[0]
            draw.text((max(0, -left), top), line, font=font, fill=0, anchor='la')
    if photo is not None:
        ticket.paste(photo, ((width - photo.width) // 2, text_height))
    return ticket


def ticket_preview(ticket, text):
    output = io.BytesIO()
    ticket.save(output, format='PNG')
    return {
        'image': 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii'),
        'width': ticket.width,
        'height': ticket.height,
        'text': text,
    }


def ticket_payload(ticket):
    # Sending blank margins as full-width raster data delays the final feed and
    # can create a second, visibly paused print section. ESC J advances paper
    # directly. Keep whole 24-dot lines so clone printers' minimum feed applies
    # consistently, and retain one raster row even for an entirely white image.
    ink = ImageChops.invert(ticket.convert('L')).getbbox()
    blank_rows = ticket.height - (ink[3] if ink else 0)
    feed_rows = min(blank_rows // LINE_HEIGHT, (ticket.height - 1) // LINE_HEIGHT) * LINE_HEIGHT
    content_height = ticket.height - feed_rows
    # Short content bands still protect the printer's raster buffer.
    bands = [encode_raster(ticket.crop((0, top, ticket.width, min(top + 256, content_height))))
             for top in range(0, content_height, 256)]
    feed = b''.join(b'\x1bJ' + bytes([min(240, feed_rows - top)])
                    for top in range(0, feed_rows, 240))
    return b'\x1b@\x1ba\x00' + b''.join(bands) + feed + b'\x1dV\x00'
