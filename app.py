#!/usr/bin/env python3
"""
Ticket Printing Application for 58mm Thermal Printer
Supports: usb, serial, network, bluetooth (classic rfcomm), ble (BLE GATT)
"""
from flask import Flask, request, render_template, jsonify
from datetime import datetime
import logging
import os

from escpos.printer import Usb, Serial, Network
from ble_printer import ble_print_text, ble_is_available

from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
PRINTER_TYPE = os.getenv("PRINTER_TYPE", "usb")  # usb, serial, network, bluetooth, ble

USB_VENDOR = int(os.getenv("USB_VENDOR", "0x0416"), 16) if os.getenv("USB_VENDOR") else None
USB_PRODUCT = int(os.getenv("USB_PRODUCT", "0x5011"), 16) if os.getenv("USB_PRODUCT") else None

SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
NETWORK_HOST = os.getenv("NETWORK_HOST", "192.168.1.100")

BLE_PRINTER_ADDR = os.getenv("BLE_PRINTER_ADDR", "").strip()


def build_ticket_text(from_name: str, question: str) -> str:
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%B %d, %Y")

    lines = [
        "================================",
        "TICKET",
        "--------------------------------",
        f"From: {from_name}",
        f"Time: {time_str}",
        f"Date: {date_str}",
        "--------------------------------",
        "Question/Comment",
        question.strip(),
        "--------------------------------",
        "================================",
    ]
    return "\n".join(lines) + "\n"


def get_printer():
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
        return None


def format_ticket_escpos(printer, from_name: str, question: str) -> bool:
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


@app.route("/submit_ticket", methods=["POST"])
def submit_ticket():
    try:
        data = request.json or {}
        from_name = data.get("from_name", "Anonymous")
        question = data.get("question", "")

        if not question.strip():
            return jsonify({"success": False, "error": "Question/Comment cannot be empty"}), 400

        # ✅ BLE path (your printer)
        if PRINTER_TYPE == "ble":
            if not BLE_PRINTER_ADDR:
                return jsonify({"success": False, "error": "BLE_PRINTER_ADDR is not set"}), 500

            text = build_ticket_text(from_name, question)
            ble_print_text(BLE_PRINTER_ADDR, text)

            logger.info(f"Ticket printed successfully over BLE from: {from_name}")
            return jsonify({"success": True, "message": "Ticket printed successfully (BLE)"}), 200

        # Everything else uses escpos printers
        printer = get_printer()
        if printer is None:
            return jsonify({"success": False, "error": "Printer not available"}), 500

        ok = format_ticket_escpos(printer, from_name, question)
        if ok:
            logger.info(f"Ticket printed successfully from: {from_name}")
            return jsonify({"success": True, "message": "Ticket printed successfully"}), 200

        return jsonify({"success": False, "error": "Failed to print ticket"}), 500

    except Exception as e:
        logger.error(f"Error processing ticket submission: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    try:
        if PRINTER_TYPE == "ble":
            return jsonify({
                "status": "healthy",
                "printer_connected": bool(BLE_PRINTER_ADDR) and ble_is_available(BLE_PRINTER_ADDR),
                "printer_type": "ble"
            })

        printer = get_printer()
        return jsonify({
            "status": "healthy",
            "printer_connected": printer is not None,
            "printer_type": PRINTER_TYPE
        })

    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


if __name__ == "__main__":
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=DEBUG)
