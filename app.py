#!/usr/bin/env python3
"""
Ticket Printing Application for 58mm Thermal Printer
Supports: usb, serial, network, bluetooth (classic rfcomm), ble (BLE GATT)
"""
from flask import Flask, request, render_template, jsonify, copy_current_request_context, has_request_context
from flask_cors import CORS
from datetime import datetime
from functools import wraps
import logging
import os
import base64
import io
import platform
from pathlib import Path

from escpos.printer import Usb, Serial, Network
from escpos.exceptions import USBNotFoundError
from usb.core import NoBackendError
from PIL import Image

from dotenv import load_dotenv
load_dotenv()

from ble_printer import ble_print_text, ble_print_text_with_image, ble_is_available, process_image_base64
from ble_printer import ble_print_raster_ticket
from ticket_layout import (DEFAULT_FEED_LINES, DEFAULT_FONT_FAMILY, DEFAULT_FONT_SIZE, STANDARD_SEPARATOR,
                           render_ticket, ticket_payload, ticket_preview, validate_feed_lines, validate_typography)
from microphone import create_microphone_blueprint, microphone_from_environment
from remote_access import configure_remote_access
from print_history import PrintHistory
from printer_worker import PrinterUnavailable, PrinterWorker, timeout_setting
from memes import create_meme_blueprint

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# One admitted printer operation can wait; other HTTP requests never queue on it.
_printer_worker = PrinterWorker()
PRINTER_OPERATION_TIMEOUT = timeout_setting("PRINTER_OPERATION_TIMEOUT", 90)
PRINTER_CHECK_TIMEOUT = timeout_setting("PRINTER_CHECK_TIMEOUT", 5)


def serialized_print(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        def operation():
            return function(*args, **kwargs)
        http_request = has_request_context()
        if http_request:
            operation = copy_current_request_context(operation)
        try:
            return _printer_worker.run(operation, timeout=PRINTER_OPERATION_TIMEOUT)
        except PrinterUnavailable as error:
            if not http_request:
                raise
            return jsonify(success=False, error=str(error), printer_state=error.state), error.status
    return wrapped

app = Flask(__name__, template_folder='frontend', static_folder='frontend', static_url_path='')
configure_remote_access(app)
app.register_blueprint(create_meme_blueprint())
if not app.config["SAMSON_PASSWORD_REQUIRED"]:
    CORS(app)  # Separate frontends are supported in the original local mode.

# Configuration
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"  # Set to 'true' to test without a printer
PRINTER_TYPE = os.getenv("PRINTER_TYPE", "usb")  # usb, serial, network, bluetooth, ble

USB_VENDOR = int(os.getenv("USB_VENDOR", "0x0416"), 16) if os.getenv("USB_VENDOR") else None
USB_PRODUCT = int(os.getenv("USB_PRODUCT", "0x5011"), 16) if os.getenv("USB_PRODUCT") else None

SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
NETWORK_HOST = os.getenv("NETWORK_HOST", "192.168.1.100")

BLE_PRINTER_ADDR = os.getenv("BLE_PRINTER_ADDR", "").strip()
print_history = PrintHistory(os.getenv("PRINT_HISTORY_PATH", str(Path(__file__).parent / "data" / "print-history.sqlite3")))

app.register_blueprint(create_microphone_blueprint(
    microphone_from_environment(print_text=lambda text, **options: print_text_content(text, return_history=True, **options)),
    allowed_origins={origin.strip().rstrip('/') for origin in
                     os.getenv('MICROPHONE_ALLOWED_ORIGINS', '').split(',') if origin.strip()},
    test_mode=TEST_MODE,
))


def build_ticket_text(from_name: str, question: str) -> str:
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%B %d, %Y")

    # lines = [
    #     "================================",
    #     "TICKET",
    #     "--------------------------------",
    #     f"From: {from_name}",
    #     f"Time: {time_str}",
    #     f"Date: {date_str}",
    #     "--------------------------------",
    #     "Question/Comment",
    #     question.strip(),
    #     "--------------------------------",
    #     "================================",
    # ]
    lines = [
        "    .  *  .   *   .  *  .",
        "  *    ✦ PROPHECY ✦    *",
        "    .  *  .   *   .  *  .",
        "",
        f"  The Oracle speaks for:",
        f"  ☽ {from_name}",
        f"  ☆ {time_str} on {date_str}",
        "",
        "  ═══════════════════════════",
        "  The spirits whisper:",
        "",
        question.strip(),
        "",
        "  ═══════════════════════════",
        "    ∴ May wisdom guide you ∴",
        "    .  *  .   *   .  *  .",
    ]
    return "\n".join(lines) + "\n"


def format_date_string() -> str:
    """Format current date/time as '7:22:00 PM on 12/12/2025'"""
    now = datetime.now()
    # Use lstrip to remove leading zeros for cross-platform compatibility
    hour = now.strftime("%I").lstrip("0")
    minute = now.strftime("%M")
    second = now.strftime("%S")
    ampm = now.strftime("%p")
    month = str(now.month)
    day = str(now.day)
    year = now.strftime("%Y")
    return f"{hour}:{minute}:{second} {ampm} on {month}/{day}/{year}"


def build_print_content(content: str, include_separator: bool = True, include_date: bool = True) -> str:
    """Build the final print content with optional separator and date"""
    lines = []
    
    if include_separator:
        lines.append(STANDARD_SEPARATOR)
    
    if include_date:
        lines.append(format_date_string())
        lines.append("")  # blank line after date
    
    lines.append(content.strip())
    lines.append("")  # trailing newline for spacing
    
    return "\n".join(lines) + "\n"


def get_printer(raise_errors=False):
    """
    Initialize and return an escpos printer object for non-BLE modes.
    IMPORTANT: BLE printing does NOT use this (it doesn't return a device).
    """
    try:
        if PRINTER_TYPE == "usb":
            if USB_VENDOR and USB_PRODUCT:
                return Usb(USB_VENDOR, USB_PRODUCT)
            return Usb(0x0416, 0x5011)

        if PRINTER_TYPE == "serial":
            return Serial(devfile=SERIAL_PORT, baudrate=9600)

        if PRINTER_TYPE == "bluetooth":
            # Classic Bluetooth SPP via rfcomm (NOT BLE)
            return Serial(devfile="/dev/rfcomm0", baudrate=9600)

        if PRINTER_TYPE == "network":
            return Network(NETWORK_HOST)

        if PRINTER_TYPE == "ble":
            # BLE does not use escpos Serial/Usb objects
            return None

        raise ValueError(f"Unknown printer type: {PRINTER_TYPE}")

    except Exception as e:
        logger.error(f"Failed to initialize printer: {e}")
        if PRINTER_TYPE == "bluetooth":
            logger.error("Try running: sudo rfcomm bind /dev/rfcomm0 [PRINTER_MAC_ADDRESS]")
        if raise_errors:
            raise
        return None


@serialized_print
def print_text_content(content, include_date=True, return_history=False):
    """Shared printer operation; background workers do not need a Flask context."""
    text = build_print_content(content, include_date=include_date)
    with print_history.record(source="listening", text=content.strip(), test_mode=TEST_MODE) as history_id:
        message = _print_text(text)
    return {"message": message, "history_id": history_id} if return_history else message


def _print_text(text):
    if TEST_MODE:
        logger.info("TEST MODE - Would print text: %s", text)
        return "Ticket logged in test mode; no paper printed."
    if PRINTER_TYPE == "ble":
        if not BLE_PRINTER_ADDR:
            raise RuntimeError("BLE_PRINTER_ADDR is not set")
        ble_print_text(BLE_PRINTER_ADDR, text)
        return "Printed successfully (BLE)"
    printer = get_printer()
    if printer is None:
        raise RuntimeError("Printer not available")
    try:
        printer.set(align="left", font="a", width=1, height=1, bold=False)
        printer.text(text)
        printer.text("\n\n")
        printer.cut()
    finally:
        printer.close()
    return "Printed successfully"


def format_ticket_escpos(printer, from_name: str, question: str, image: Image.Image = None) -> bool:
    """
    Original rich formatting (uses python-escpos methods).
    Works for usb/serial/network/bluetooth(classic).
    """
    try:
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        date_str = now.strftime("%B %d, %Y")

        printer.set(align="center", font="a", width=2, height=2, bold=True)
        printer.text("================================\n")
        printer.text("TICKET\n")

        printer.set(align="center", font="a", width=1, height=1, bold=False)
        printer.text("--------------------------------\n")

        printer.set(align="left", font="a", width=1, height=1, bold=True)
        printer.text(f"From: {from_name}\n")

        printer.set(align="left", font="a", width=1, height=1, bold=False)
        printer.text(f"Time: {time_str}\n")
        printer.text(f"Date: {date_str}\n")

        printer.text("--------------------------------\n")

        printer.set(align="left", font="a", width=1, height=1, bold=True)
        printer.text("Question/Comment\n")

        printer.set(align="left", font="a", width=1, height=1, bold=False)
        printer.text(f"{question}\n")

        # Print image if provided
        if image is not None:
            printer.text("--------------------------------\n")
            printer.set(align="center")
            printer.image(image)

        printer.text("--------------------------------\n")

        printer.set(align="center", font="a", width=2, height=2, bold=True)
        printer.text("================================\n")

        printer.text("\n\n")
        printer.cut()
        return True

    except Exception as e:
        logger.error(f"Error printing ticket: {e}")
        return False


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/history", methods=["GET"])
def history():
    try:
        before = int(request.args["before"]) if "before" in request.args else None
        limit = int(request.args.get("limit", "30"))
        if (before is not None and not 0 < before <= 9223372036854775807) or not 1 <= limit <= 100:
            raise ValueError
    except ValueError:
        response = jsonify(success=False, error="Use a positive before ID and a limit from 1 to 100.")
        response.status_code = 400
    else:
        try:
            response = jsonify(success=True, **print_history.page(before=before, limit=limit))
        except Exception:
            logger.exception("Could not load print history")
            response = jsonify(success=False, error="Couldn’t load print history. Try again.")
            response.status_code = 503
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/submit_ticket", methods=["POST"])
@serialized_print
def submit_ticket():
    try:
        data = request.json or {}
        if not isinstance(data, dict):
            return jsonify(success=False, error="A JSON object is required"), 400
        from_name = data.get("from_name", "Anonymous")
        question = data.get("question", "")
        image_base64 = data.get("image")  # Optional base64 image

        if not isinstance(from_name, str) or not isinstance(question, str) or not question.strip():
            return jsonify({"success": False, "error": "Question/Comment cannot be empty"}), 400

        processed_image = process_image_base64(image_base64) if image_base64 else None
        text = build_ticket_text(from_name, question)
        # Legacy tickets use device text commands; keep the content and processed
        # image without claiming the raster preview is an exact paper rendering.
        preview = ticket_preview(processed_image, text) if processed_image is not None else None
        if preview:
            preview["image_only"] = True
        with print_history.record(source="ticket", kind="image" if processed_image else "text",
                                  text=f"From: {from_name}\n{question.strip()}", preview=preview,
                                  test_mode=TEST_MODE) as history_id:
            if TEST_MODE:
                logger.info("TEST MODE - Ticket would be printed: %s", text)
                message = "Ticket logged (TEST MODE - no printer)"
            elif PRINTER_TYPE == "ble":
                if not BLE_PRINTER_ADDR:
                    raise RuntimeError("BLE_PRINTER_ADDR is not set")
                if processed_image is not None:
                    ble_print_text_with_image(BLE_PRINTER_ADDR, text, processed_image)
                else:
                    ble_print_text(BLE_PRINTER_ADDR, text)
                message = "Ticket printed successfully (BLE)"
            else:
                printer = get_printer()
                if printer is None:
                    raise RuntimeError("Printer not available")
                try:
                    ok = format_ticket_escpos(printer, from_name, question, processed_image)
                finally:
                    printer.close()
                if not ok:
                    raise RuntimeError("Failed to print ticket")
                message = "Ticket printed successfully"
        return jsonify(success=True, message=message, test_mode=TEST_MODE, history_id=history_id), 200

    except Exception as e:
        logger.error(f"Error processing ticket submission: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/print", methods=["POST"])
@serialized_print
def print_content():
    """Print text or an image with an optional caption as one ticket."""
    try:
        data = request.json or {}
        if not isinstance(data, dict):
            return jsonify({"success": False, "error": "A JSON object is required"}), 400
        print_type = data.get("type", "text")  # 'text' or 'image'
        content = data.get("content", "")
        caption = data.get("caption", "")
        include_date = data.get("include_date", True)
        try:
            feed_lines = validate_feed_lines(data.get("feed_lines", DEFAULT_FEED_LINES))
            font_family, font_size = validate_typography(data.get("font_family", DEFAULT_FONT_FAMILY),
                                                         data.get("font_size", DEFAULT_FONT_SIZE))
        except ValueError as error:
            return jsonify(success=False, error=str(error)), 400

        if type(include_date) is not bool:
            return jsonify({"success": False, "error": "Include date must be a boolean"}), 400
        if print_type not in ("text", "image"):
            return jsonify({"success": False, "error": "Type must be text or image"}), 400
        if not isinstance(content, str) or not content.strip():
            return jsonify({"success": False, "error": "Content cannot be empty"}), 400
        if not isinstance(caption, str):
            return jsonify({"success": False, "error": "Caption must be text"}), 400
        if len(caption) > 1000 or (print_type == "text" and len(content) > 1000):
            return jsonify({"success": False, "error": "Text must be 1,000 characters or fewer"}), 400
        caption = caption.strip()

        processed_image = None
        if print_type == "image":
            processed_image = process_image_base64(content)
            if processed_image is None:
                return jsonify({"success": False, "error": "Failed to process image"}), 400

        # Build the timestamp and layout exactly once. The response contains the
        # same pixels sent to the printer, including wrapped text and processed photos.
        text = build_print_content(content if print_type == "text" else caption,
                                   include_separator=False, include_date=include_date)
        ticket = render_ticket(text, processed_image, feed_lines=feed_lines,
                               font_family=font_family, font_size=font_size, include_separator=True)
        text = STANDARD_SEPARATOR + '\n' + text
        preview = ticket_preview(ticket, text)
        payload = ticket_payload(ticket)

        with print_history.record(source="chat", kind=print_type,
                                  text=content.strip() if print_type == "text" else caption,
                                  preview=preview, test_mode=TEST_MODE) as history_id:
            if TEST_MODE:
                logger.info("TEST MODE - Would print %s ticket:\n%s", print_type, text)
                message = "Ticket logged in test mode; no paper printed."
            elif PRINTER_TYPE == "ble":
                if not BLE_PRINTER_ADDR:
                    raise RuntimeError("BLE_PRINTER_ADDR is not set")
                ble_print_raster_ticket(BLE_PRINTER_ADDR, payload)
                message = "Printed successfully (BLE)"
            else:
                printer = get_printer()
                if printer is None:
                    raise RuntimeError("Printer not available")
                try:
                    printer._raw(payload)
                finally:
                    printer.close()
                message = "Printed successfully"

        return jsonify(success=True, message=message, test_mode=TEST_MODE, preview=preview, history_id=history_id), 200

    except Exception as e:
        logger.error(f"Error processing print request: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def server_identity():
    """Identify the actual server hardware; a reachable URL alone is not a Pi."""
    for filename in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            if "raspberry pi" in Path(filename).read_text().lower():
                return {"kind": "raspberry_pi", "name": "Raspberry Pi"}
        except (OSError, UnicodeError):
            pass
    return {"kind": "computer", "name": {"Darwin": "Mac", "Windows": "Windows PC",
            "Linux": "Linux computer"}.get(platform.system(), "Computer")}


def _check_printer():
    connected = False
    state, message = "disconnected", "Check the printer’s power and connection to this server."
    try:
        if TEST_MODE:
            state, message = "test_mode", "Tickets are previewed only. No paper will print."
        elif PRINTER_TYPE == "ble":
            if not BLE_PRINTER_ADDR:
                state, message = "setup_required", "Set the Bluetooth printer address on this server."
            else:
                connected = ble_is_available(BLE_PRINTER_ADDR)
                state = "available" if connected else "disconnected"
                message = "Printer found over Bluetooth." if connected else \
                    "Printer not found. Turn it on and keep it near this server."
        else:
            printer = get_printer(raise_errors=True)
            if printer is not None:
                printer.close()
                connected = True
                state, message = "ready", "Printer connection is ready."
    except NoBackendError:
        state, message = "setup_required", "USB support is unavailable on this server."
    except USBNotFoundError:
        message = "USB printer not found. Check its power, cable, and configured printer ID."
    except PermissionError:
        state, message = "setup_required", "Allow this server to access the printer, then check again."
    except ValueError:
        state, message = "setup_required", "Check the printer connection settings on this server."
    except Exception as error:
        logger.warning("Printer health check failed: %s", error)
        state, message = "unavailable", "Couldn’t check the printer. Check its connection and try again."
    return connected, state, message


@app.route("/health", methods=["GET"])
def health():
    try:
        if TEST_MODE:
            connected, state, message = False, "test_mode", "Tickets are previewed only. No paper will print."
        else:
            connected, state, message = _printer_worker.run(
                _check_printer, timeout=PRINTER_CHECK_TIMEOUT, kind="check")
    except PrinterUnavailable as error:
        connected, state, message = False, error.state, str(error)
    response = jsonify(service="samson", status="healthy", server=server_identity(),
                       printer_connected=connected, printer_type=PRINTER_TYPE, test_mode=TEST_MODE,
                       printer_state=state, printer_message=message)
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    DEBUG = os.getenv("DEBUG", "false").lower() == "true" and not app.config["SAMSON_PASSWORD_REQUIRED"]
    app.run(host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "5000")), debug=DEBUG)
