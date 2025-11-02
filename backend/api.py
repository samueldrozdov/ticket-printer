#!/usr/bin/env python3
"""
Ticket Printing API for Raspberry Pi
This API connects to the physical printer and should be hosted on the device with the printer.
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import logging
from escpos.printer import Usb, Serial, Network
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend on different domain

# Configuration
PRINTER_TYPE = os.getenv('PRINTER_TYPE', 'usb')  # 'usb', 'serial', 'network', or 'bluetooth'
USB_VENDOR = int(os.getenv('USB_VENDOR', '0x0416'), 16) if os.getenv('USB_VENDOR') else None
USB_PRODUCT = int(os.getenv('USB_PRODUCT', '0x5011'), 16) if os.getenv('USB_PRODUCT') else None
SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')  # Default serial port
NETWORK_HOST = os.getenv('NETWORK_HOST', '192.168.1.100')

def get_printer():
    """Initialize and return the printer based on configuration"""
    try:
        if PRINTER_TYPE == 'usb':
            if USB_VENDOR and USB_PRODUCT:
                return Usb(USB_VENDOR, USB_PRODUCT)
            else:
                return Usb(0x0416, 0x5011)
        elif PRINTER_TYPE == 'serial' or PRINTER_TYPE == 'bluetooth':
            port = SERIAL_PORT
            if PRINTER_TYPE == 'bluetooth':
                port = '/dev/rfcomm0'
            return Serial(devfile=port, baudrate=9600)
        elif PRINTER_TYPE == 'network':
            return Network(NETWORK_HOST)
        else:
            raise ValueError(f"Unknown printer type: {PRINTER_TYPE}")
    except Exception as e:
        logger.error(f"Failed to initialize printer: {e}")
        return None

def format_ticket(printer, from_name, question):
    """Format and print the ticket"""
    try:
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        date_str = now.strftime("%B %d, %Y")
        
        # Print ticket format
        printer.set(align='center', font='a', width=2, height=2, bold=True)
        printer.text("================================\n")
        printer.text("TICKET\n")
        
        printer.set(align='center', font='a', width=1, height=1, bold=False)
        printer.text("--------------------------------\n")
        
        printer.set(align='left', font='a', width=1, height=1, bold=True)
        printer.text(f"From: {from_name}\n")
        
        printer.set(align='left', font='a', width=1, height=1, bold=False)
        printer.text(f"Time: {time_str}\n")
        printer.text(f"Date: {date_str}\n")
        
        printer.text("--------------------------------\n")
        
        printer.set(align='left', font='a', width=1, height=1, bold=True)
        printer.text(f"Question/Comment\n")
        
        printer.set(align='left', font='a', width=1, height=1, bold=False)
        printer.text(f"{question}\n")
        
        printer.text("--------------------------------\n")
        
        printer.set(align='center', font='a', width=2, height=2, bold=True)
        printer.text("================================\n")
        
        printer.text("\n\n")
        printer.cut()
        
        return True
    except Exception as e:
        logger.error(f"Error printing ticket: {e}")
        return False

@app.route('/submit_ticket', methods=['POST'])
def submit_ticket():
    """Handle ticket submission"""
    try:
        data = request.json
        from_name = data.get('from_name', 'Anonymous')
        question = data.get('question', '')
        
        if not question.strip():
            return jsonify({'success': False, 'error': 'Question/Comment cannot be empty'}), 400
        
        printer = get_printer()
        
        if printer is None:
            return jsonify({'success': False, 'error': 'Printer not available'}), 500
        
        success = format_ticket(printer, from_name, question)
        
        if success:
            logger.info(f"Ticket printed successfully from: {from_name}")
            return jsonify({'success': True, 'message': 'Ticket printed successfully'})
        else:
            return jsonify({'success': False, 'error': 'Failed to print ticket'}), 500
            
    except Exception as e:
        logger.error(f"Error processing ticket submission: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    try:
        printer = get_printer()
        printer_status = printer is not None
        return jsonify({
            'status': 'healthy',
            'printer_connected': printer_status
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)


