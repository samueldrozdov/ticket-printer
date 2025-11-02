# Configure for Bluetooth Printer

## The Issue
The app is trying to use USB printer, but you have a BLUETOOTH printer.

## Solution: Change Configuration

### Step 1: Edit app.py on Raspberry Pi

```bash
# SSH to Pi
ssh pi@raspberrypi.local

# Go to app directory
cd /boot/firmware

# Edit app.py
sudo nano app.py
```

### Step 2: Change Printer Type

Find line 18 (around there):
```python
PRINTER_TYPE = os.getenv('PRINTER_TYPE', 'usb')
```

Change to:
```python
PRINTER_TYPE = os.getenv('PRINTER_TYPE', 'bluetooth')
```

Also check line 21 (SERIAL_PORT):
```python
SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/rfcomm0')
```

This should already be `/dev/rfcomm0` which is correct for Bluetooth.

Save: `Ctrl + X`, `Y`, `Enter`

### Step 3: Set Up Bluetooth Connection

Make sure Bluetooth is paired and connected.

#### Check if printer is paired:

```bash
bluetoothctl
devices
# Should show your printer
exit
```

#### If not paired, pair it:

```bash
# Enter bluetoothctl
bluetoothctl

# Scan for devices
scan on
# Wait to see your printer's MAC address

# Pair (replace MAC with your printer)
pair MAC:ADDRESS:OF:PRINTER

# Trust
trust MAC:ADDRESS:OF:PRINTER

# Exit
exit
```

#### Bind to serial port:

```bash
# Find your printer's MAC address
bluetoothctl devices

# Bind to rfcomm (replace MAC with your printer's MAC)
sudo rfcomm bind /dev/rfcomm0 MAC:ADDRESS:OF:PRINTER

# Verify it's bound
ls -la /dev/rfcomm0
```

Should show:
```
crw-rw---- 1 root dialout 216, 0 Oct 27 12:00 /dev/rfcomm0
```

### Step 4: Fix Permissions

```bash
sudo chmod 666 /dev/rfcomm0
sudo usermod -a -G dialout pi
```

You may need to log out and back in for group changes to take effect.

### Step 5: RESTART Flask

```bash
# Kill Flask
pkill -f app.py

# Start again
python3 app.py
```

### Step 6: Test the Connection

From your Mac:
```bash
curl https://your-ngrok-url.ngrok-free.dev/health
   - Replace with your actual ngrok URL
```

Should return printer_connected: true

Then try submitting a ticket from Netlify!

---

## Alternative: Set via Environment Variable

Instead of editing the file, you can set environment variable:

```bash
# Stop Flask
pkill -f app.py

# Start with Bluetooth config
export PRINTER_TYPE=bluetooth
export SERIAL_PORT=/dev/rfcomm0
python3 app.py
```

---

## Quick Checklist

✅ Printer paired with Bluetooth  
✅ rfcomm bound to /dev/rfcomm0  
✅ Permission set (chmod 666 /dev/rfcomm0)  
✅ User in dialout group  
✅ app.py changed to 'bluetooth'  
✅ Flask restarted  
✅ Test from Netlify  

---

## Troubleshooting

### "No such file or directory" for rfcomm0

```bash
# Bind the port
sudo rfcomm bind /dev/rfcomm0 YOUR_PRINTER_MAC
```

### "Permission denied"

```bash
sudo chmod 666 /dev/rfcomm0
sudo usermod -a -G dialout pi
# Log out and back in
```

### "Connection refused"

```bash
# Unbind and rebind
sudo rfcomm unbind /dev/rfcomm0
sudo rfcomm bind /dev/rfcomm0 YOUR_PRINTER_MAC
```

### Printer not showing in bluetoothctl

```bash
# Make sure Bluetooth is on
sudo systemctl status bluetooth

# Turn on if needed
sudo systemctl start bluetooth
sudo systemctl enable bluetooth
```

