# Set Up Bluetooth Printer Connection

## The Problem
/dev/rfcomm0 doesn't exist - the printer isn't bound to Bluetooth yet.

## Solution: Bind Bluetooth Printer to rfcomm

### Step 1: Find Your Printer's MAC Address

```bash
# Enter bluetooth control
bluetoothctl

# Start scanning
scan on
# Wait 10-15 seconds to see devices

# Look for your printer in the list
# Should see something like:
# Device AA:BB:CC:DD:EE:FF Netum Printer

# Note the MAC address (AA:BB:CC:DD:EE:FF)
# Exit scanning
scan off

# Exit bluetoothctl
exit
```

### Step 2: Pair the Printer

```bash
bluetoothctl

# Pair with your printer (replace MAC with actual address)
pair AA:BB:CC:DD:EE:FF

# If asked for PIN, try 0000 or 1234 (common defaults)

# Trust the device
trust AA:BB:CC:DD:EE:FF

# Exit
exit
```

### Step 3: Bind to rfcomm

```bash
# Bind printer to rfcomm0 (replace MAC with actual)
sudo rfcomm bind /dev/rfcomm0 AA:BB:CC:DD:EE:FF

# Verify it's bound
ls -la /dev/rfcomm0

# Should show something like:
# crw-rw---- 1 root dialout 216, 0 Oct 27 12:00 /dev/rfcomm0
```

### Step 4: Fix Permissions

```bash
# Change permissions so the service can access it
sudo chmod 666 /dev/rfcomm0

# Add user to dialout group
sudo usermod -a -G dialout $USER

# You may need to log out and back in for group change
```

### Step 5: Make Binding Persistent

The binding is temporary and will be lost on reboot. To make it permanent:

```bash
# Edit rc.local to auto-bind on boot
sudo nano /etc/rc.local
```

Add this line BEFORE `exit 0`:
```bash
rfcomm bind /dev/rfcomm0 AA:BB:CC:DD:EE:FF &
```

Save: `Ctrl + X`, `Y`, `Enter`

### Step 6: Restart Flask Service

```bash
sudo systemctl restart ticket-api
sudo systemctl status ticket-api
```

Now try printing from Netlify!

---

## Troubleshooting

### "Device not found" or "No such device"

```bash
# Make sure printer is powered on and in pairing mode
# Try scanning again
bluetoothctl
scan on
```

### "Can't bind to rfcomm0"

```bash
# If rfcomm0 is already bound to something, unbind first:
sudo rfcomm unbind /dev/rfcomm0

# Then bind again
sudo rfcomm bind /dev/rfcomm0 AA:BB:CC:DD:EE:FF
```

### "Permission denied"

```bash
# Fix permissions
sudo chmod 666 /dev/rfcomm0
sudo chown root:dialout /dev/rfcomm0
```

### Check Status

```bash
# See what rfcomm devices are bound
rfcomm

# Should show something like:
# rfcomm0: AA:BB:CC:DD:EE:FF -> /dev/rfcomm0
```

---

## Alternative: Use Already Paired Device

If you've already paired the printer before, just bind it:

```bash
# List paired devices
bluetoothctl devices

# Find your printer's MAC address

# Bind to rfcomm
sudo rfcomm bind /dev/rfcomm0 YOUR_PRINTER_MAC

# Test
ls -la /dev/rfcomm0
```

