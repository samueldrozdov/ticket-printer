# Deployment Guide for Ticket Printer App

This guide covers multiple deployment options for your ticket printer application.

## Quick Deployment Options

### Option 1: Deploy to Raspberry Pi (Recommended)

#### Prerequisites
- Raspberry Pi with Raspberry Pi OS installed
- Netum 58mm thermal printer
- USB cable to connect printer to Pi

#### Step 1: Transfer Files to Raspberry Pi

Choose one of these methods:

**Method A: Using USB Flash Drive**
```bash
# On your Mac:
# 1. Copy the entire folder to a USB drive
cp -r /path/to/ticket-printer-app /Volumes/YOUR_USB_NAME/

# 2. Insert USB into Raspberry Pi
# 3. On the Pi, copy files to home directory:
cp -r /media/pi/*/ticket-printer-app ~/
cd ~/ticket-printer-app
```

**Method B: Using SCP (Network Transfer)**
```bash
# On your Mac, from the project directory:
scp -r /path/to/ticket-printer-app pi@raspberrypi.local:/home/pi/

# Then SSH into the Pi:
ssh pi@raspberrypi.local
cd ~/ticket-printer-app
```

**Method C: Using Git**
```bash
# On your Mac:
cd /path/to/ticket-printer-app
git init
git add .
git commit -m "Initial commit"
# Create a repo on GitHub and push
git remote add origin YOUR_GITHUB_URL
git push -u origin main

# On Raspberry Pi:
git clone YOUR_GITHUB_URL
cd ticket-printer
```

#### Step 2: Run Setup Script

```bash
# Make sure you're in the project directory
cd ~/ticket-printer-app

# Make the setup script executable
chmod +x setup.sh

# Run the setup
./setup.sh
```

This will:
- Install Python and system dependencies
- Install printer drivers
- Install Python packages
- Set up permissions
- Create a systemd service

#### Step 3: Connect and Configure Printer

```bash
# Connect your printer via USB
# Find the printer's USB ID:
sudo lsusb
```

You should see something like:
```
Bus 001 Device 003: ID 0416:5011 Netum printer
```

#### Step 4: Update Configuration (if needed)

If your printer has different USB IDs, edit `app.py`:

```bash
nano app.py
```

Look for lines 19-20:
```python
USB_VENDOR = int(os.getenv('USB_VENDOR', '0x0416'), 16)
USB_PRODUCT = int(os.getenv('USB_PRODUCT', '0x5011'), 16)
```

Replace `0x0416` and `0x5011` with your printer's IDs from `lsusb`.

#### Step 5: Test Printer Connection

```bash
python3 -c "
from escpos.printer import Usb
p = Usb(0x0416, 0x5011)
p.text('Test print')
p.cut()
"
```

#### Step 6: Start the Application

**Option A: Run Manually (for testing)**
```bash
python3 app.py
```

**Option B: Run as a Service (starts on boot)**
```bash
sudo systemctl start ticket-printer
sudo systemctl enable ticket-printer
sudo systemctl status ticket-printer
```

#### Step 7: Get Raspberry Pi IP Address

```bash
hostname -I
```

Access from any device: `http://YOUR_PI_IP:5000`

### Option 2: Local Testing (without Printer)

Test the web interface locally:

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run the app
python3 app.py
```

Open browser to: `http://localhost:5000`

Note: Without a printer connected, the print operations will fail, but you can test the web interface.

### Option 3: Deploy with Different Printer Types

#### Bluetooth Printer Setup

```bash
# On Raspberry Pi, pair Bluetooth printer:
sudo bluetoothctl
scan on
# Wait to see your printer, then:
pair MAC_ADDRESS
trust MAC_ADDRESS
exit

# Bind to serial port:
sudo rfcomm bind /dev/rfcomm0 MAC_ADDRESS

# Set environment variables:
export PRINTER_TYPE=bluetooth
export SERIAL_PORT=/dev/rfcomm0

# Run the app
python3 app.py
```

#### Serial/GPIO Printer Setup

```bash
# Enable serial interface:
sudo raspi-config
# Navigate to: Interface Options > Serial Port > Enable

# Set environment variables:
export PRINTER_TYPE=serial
export SERIAL_PORT=/dev/ttyAMA0

# Run the app
python3 app.py
```

#### Network Printer Setup

```bash
# Set environment variables:
export PRINTER_TYPE=network
export NETWORK_HOST=192.168.1.100

# Run the app
python3 app.py
```

## Production Configuration

### Running as a System Service

The setup script creates a systemd service. To manage it:

```bash
# Start the service
sudo systemctl start ticket-printer

# Stop the service
sudo systemctl stop ticket-printer

# Restart the service
sudo systemctl restart ticket-printer

# Check status
sudo systemctl status ticket-printer

# View logs
sudo journalctl -u ticket-printer -f

# Enable on boot
sudo systemctl enable ticket-printer

# Disable on boot
sudo systemctl disable ticket-printer
```

### Configuration via Environment Variables

Create a `.env` file or set systemd environment:

```bash
sudo systemctl edit ticket-printer
```

Add:
```ini
[Service]
Environment="PRINTER_TYPE=usb"
Environment="USB_VENDOR=0x0416"
Environment="USB_PRODUCT=0x5011"
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl restart ticket-printer
```

## Troubleshooting

### Permission Errors

```bash
# Add user to printer groups
sudo usermod -a -G lp,dialout pi

# Fix USB permissions temporarily
sudo chmod 666 /dev/bus/usb/*/*

# Log out and back in for group changes to take effect
```

### Printer Not Detected

1. Check USB connection:
   ```bash
   sudo lsusb
   ```

2. Check permissions:
   ```bash
   ls -l /dev/ttyUSB0  # or relevant device
   sudo chmod 666 /dev/ttyUSB0
   ```

3. Try different USB ports

4. Verify USB vendor/product IDs match configuration

### Service Won't Start

```bash
# Check service status
sudo systemctl status ticket-printer

# View detailed logs
sudo journalctl -u ticket-printer -n 50

# Try running manually to see errors
cd ~/ticket-printer-app
python3 app.py
```

### Can't Access Web Interface

1. Check if app is running:
   ```bash
   ps aux | grep app.py
   ```

2. Check if port 5000 is in use:
   ```bash
   sudo netstat -tulpn | grep 5000
   ```

3. Check firewall:
   ```bash
   sudo ufw allow 5000/tcp
   ```

4. Verify IP address:
   ```bash
   hostname -I
   ```

### Bluetooth Issues

```bash
# Check if device is paired
bluetoothctl devices

# Check rfcomm binding
rfcomm

# Rebind if needed
sudo rfcomm bind /dev/rfcomm0 MAC_ADDRESS
```

## Health Check

Test if the service is working:

```bash
# From the Raspberry Pi or network:
curl http://localhost:5000/health
```

Should return:
```json
{
  "status": "healthy",
  "printer_connected": true
}
```

## Updating the Application

```bash
# Stop the service
sudo systemctl stop ticket-printer

# Pull latest changes (if using git)
git pull

# Or update files manually
# Copy new files to ~/ticket-printer-app/

# Install new dependencies (if any)
pip3 install -r requirements.txt

# Restart service
sudo systemctl start ticket-printer
```

## Security Considerations

1. Change default Flask debug mode for production
2. Consider adding authentication if exposed to internet
3. Use HTTPS for production deployments
4. Set up firewall rules appropriately

## Success Checklist

- [ ] Files transferred to Raspberry Pi
- [ ] Dependencies installed
- [ ] Printer connected and detected
- [ ] Configuration updated with correct printer IDs
- [ ] Test print successful
- [ ] Application running (manually or as service)
- [ ] Web interface accessible from network
- [ ] Can submit and print tickets successfully

## Need Help?

Check the main README.md for more detailed information and troubleshooting tips.


