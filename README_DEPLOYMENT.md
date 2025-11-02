# 🚀 Quick Deployment Guide

This guide will help you deploy the ticket printer app in 3 simple methods.

## Method 1: Automated Deployment (Easiest)

```bash
# Make the script executable
chmod +x deploy.sh

# Run the deployment script
./deploy.sh
```

This will guide you through the deployment process.

## Method 2: Raspberry Pi Deployment

### Quick Start:

```bash
# 1. Transfer files to Raspberry Pi (choose one):
#    A. Via USB drive - copy folder to USB, insert into Pi
#    B. Via SCP:
scp -r . pi@raspberrypi.local:/home/pi/ticket-printer-app

# 2. SSH into Raspberry Pi
ssh pi@raspberrypi.local

# 3. Navigate to folder
cd ~/ticket-printer-app

# 4. Run setup
chmod +x setup.sh
./setup.sh

# 5. Connect printer and start
python3 app.py
```

## Method 3: Local Testing

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run locally
python3 app.py

# Open browser
open http://localhost:5000
```

## Next Steps

1. **Connect your printer** to the Raspberry Pi via USB
2. **Find printer ID**:
   ```bash
   sudo lsusb
   ```
3. **Update config** in `app.py` if needed
4. **Test print**:
   ```bash
   python3 -c "from escpos.printer import Usb; p = Usb(0x0416, 0x5011); p.text('Test'); p.cut()"
   ```
5. **Start service** (optional):
   ```bash
   sudo systemctl start ticket-printer
   sudo systemctl enable ticket-printer
   ```
6. **Access web interface**:
   ```
   http://YOUR_PI_IP:5000
   ```

## Full Documentation

See `DEPLOYMENT.md` for detailed deployment instructions.

## Troubleshooting

### Permission Errors
```bash
sudo usermod -a -G lp,dialout $USER
# Log out and back in
```

### Printer Not Found
```bash
sudo lsusb  # Check if printer is detected
sudo chmod 666 /dev/ttyUSB0  # Fix permissions
```

### Service Won't Start
```bash
sudo systemctl status ticket-printer
sudo journalctl -u ticket-printer -f
```

## Configuration

Set environment variables to configure printer type:

```bash
# USB Printer (default)
export PRINTER_TYPE=usb
export USB_VENDOR=0x0416
export USB_PRODUCT=0x5011

# Serial/GPIO Printer
export PRINTER_TYPE=serial
export SERIAL_PORT=/dev/ttyAMA0

# Bluetooth Printer
export PRINTER_TYPE=bluetooth
export SERIAL_PORT=/dev/rfcomm0

# Network Printer
export PRINTER_TYPE=network
export NETWORK_HOST=192.168.1.100

# Then run
python3 app.py
```

For detailed configuration, see the full `DEPLOYMENT.md` guide.


