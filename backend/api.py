#!/usr/bin/env python3
"""
Ticket Printing API for Raspberry Pi
This API connects to the physical printer and should be hosted on the device with the printer.
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import logging
import base64
import io
from escpos.printer import Usb, Serial, Network
from PIL import Image
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

def process_image_for_printing(image_base64, max_width=384):
    """Process base64 image for thermal printer"""
    try:
        # Remove data URL prefix if present (e.g., "data:image/png;base64,")
        if ',' in image_base64:
            image_base64 = image_base64.split(',')[1]
        
        # Decode base64 to bytes
        image_data = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if necessary (handles RGBA, P mode, etc.)
        if image.mode in ('RGBA', 'P'):
            # Create white background for transparency
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'RGBA':
                background.paste(image, mask=image.split()[3])
            else:
                background.paste(image)
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Resize to fit printer width while maintaining aspect ratio
        if image.width > max_width:
            ratio = max_width / image.width
            new_height = int(image.height * ratio)
            image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)
        
        return image
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        return None


def format_ticket(printer, from_name, question, image=None):
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
        
        # Print image if provided
        if image is not None:
            printer.text("--------------------------------\n")
            printer.set(align='center')
            printer.image(image)
        
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
        image_base64 = data.get('image')  # Optional base64 image
        
        if not question.strip():
            return jsonify({'success': False, 'error': 'Question/Comment cannot be empty'}), 400
        
        printer = get_printer()
        
        if printer is None:
            return jsonify({'success': False, 'error': 'Printer not available'}), 500
        
        # Process image if provided
        processed_image = None
        if image_base64:
            processed_image = process_image_for_printing(image_base64)
            if processed_image is None:
                logger.warning("Failed to process image, printing without it")
        
        success = format_ticket(printer, from_name, question, processed_image)
        
        if success:
            has_image = processed_image is not None
            logger.info(f"Ticket printed successfully from: {from_name} (with image: {has_image})")
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
    app.run(host='0.0.0.0', port=5001, debug=False)


