"""
Configuration file for the Ticket Printing Application
Adjust these values based on your printer setup
"""

import os

# Printer Configuration
PRINTER_TYPE = os.getenv('PRINTER_TYPE', 'usb')  # Options: 'usb', 'serial', 'network'

# USB Printer Settings
# To find your USB vendor and product IDs, run: lsusb
# Example output: Bus 001 Device 003: ID 0416:5011
USB_VENDOR = os.getenv('USB_VENDOR', '0x0416')   # Vendor ID (hex)
USB_PRODUCT = os.getenv('USB_PRODUCT', '0x5011')  # Product ID (hex)

# Serial Printer Settings
SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
SERIAL_BAUDRATE = os.getenv('SERIAL_BAUDRATE', '9600')

# Network Printer Settings
NETWORK_HOST = os.getenv('NETWORK_HOST', '192.168.1.100')
NETWORK_PORT = os.getenv('NETWORK_PORT', '9100')

# Application Settings
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '5000'))
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
