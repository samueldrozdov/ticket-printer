# Ticket Printer Application

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A web-based ticket submission system that automatically prints tickets on ESC/POS thermal printers connected to a Raspberry Pi. Users can submit tickets through a simple web interface, which are then automatically printed with timestamps and formatted output.

Perfect for:
- Q&A sessions and feedback collection at events
- Anonymous comment boards
- Interactive installations
- Physical message boards

## Things to Buy (Affiliate links)

-Printer: (https://amzn.to/43Vx9DT)

-Raspberry Pi Kit: (https://amzn.to/3XoAZli)

-Receipt Paper: (https://amzn.to/4ag6q8Y)

-You’ll also need a monitor that supports HDMI input. Most do, but here’s a cheap one if you need it: (https://amzn.to/4rsK620)

-Plus a keyboard and mouse, I use this Bluetooth set: (https://amzn.to/4akjutW)

## Description

This application provides a complete solution for collecting and printing tickets in physical form. It consists of:

- **Web Interface**: A responsive frontend served by the Raspberry Pi
- **Backend API**: A Flask-based API running on Raspberry Pi that handles printer communication
- **Multiple Printer Support**: Works with USB, Serial, Network, and Bluetooth-connected printers
- **Print History**: Automatically save tickets on the server and show them when the website opens
- **Remote Access**: Password-protected access through an HTTPS tunnel

The current installation runs the website and API together on the Raspberry Pi.
Older Netlify integration files remain in the repository; see the
[legacy notes](README_NETLIFY.md) for their limitations.

## Features

- 📝 Simple web interface for ticket submission
- 🖨️ Automatic printing on Netum 58mm thermal printer
- ⏰ Timestamp and date stamping
- 💾 Persistent print history with text, timestamps, and ticket previews
- 🌐 Accessible from any device on your network
- 🔒 Password-protected remote access

## Quick Start

**Deploying an update?** Follow [DEPLOYMENT.md](DEPLOYMENT.md), the current
GitHub → Raspberry Pi runbook. It covers testing, publishing, updating the Pi,
restarting the app without changing the public link, and checking the result.

Sending a chat message clears the composer immediately, so you can send the next
message while Samson prints. Each sent message, photo, meme, or vocab word appears
on your side of the conversation, followed directly by Samson’s ticket preview.
Chat message timestamps show only the time, such as `9:14 PM`, and the chat
separator uses `Today · 9:14 PM`. Printed tickets use `9:14 PM on 10/10/2026`.
Messages print in the order sent; keep the page open until queued messages finish.
Unconfirmed messages stay visible with their error directly underneath.

Open Samson’s settings and choose **Message spacing** to set the extra blank
paper after sent text or photo messages: **S** (3 lines), **M** (6 lines, default),
or **L** (12 lines). This
preference is saved in your browser for each server and applies when you send
each message. Ticket previews and saved history show the same spacing.

The **Font** selector offers Monospace (the original font), Sans, and Serif.
**Font size** offers S, M (the original size), and L. These settings are also
saved per browser and server, and apply to sent messages and photo captions.
Long text wraps to fit the paper; ticket previews and history preserve the
printed font and size. The dashed separator stays at its original size on one
row for every font choice. Additional fonts and their license are bundled in `fonts/`.

The website loads saved print history automatically when opened, including chat
tickets, photos, and **Passive Listening** output. Use **Load older tickets** to browse
earlier prints; saved paper previews appear directly in the history. Failed attempts
and test previews have separate labels. Opening history never reprints a ticket.

History is stored by `app.py` in `data/print-history.sqlite3` on the server, so it
survives browser refreshes and app/Pi restarts and is shared across devices. Keep
that file when deploying or backing up the app. Set `PRINT_HISTORY_PATH` to use a
different persistent location. `/history?before=ID&limit=30` provides paginated
history (maximum 100 entries per request); the existing remote password protects
it. History starts with this update; earlier prints cannot be reconstructed.
The legacy standalone `backend/api.py` does not provide this feature.

To use Samson from cellular or another Wi-Fi network, see
[password-protected remote access](REMOTE_ACCESS.md). Run the website and API on
the Pi behind an HTTPS tunnel; the Pi stays online beside the printer.

For the Samson USB microphone → review text → print workflow, see
[MICROPHONE_SETUP.md](MICROPHONE_SETUP.md). It runs speech recognition locally on
the Pi and uses the root `app.py` application.
Both recording modes show an animated sound icon that reacts to microphone volume,
so you can see whether Samson is picking up audio before words appear.

For continuous listening, choose **+ → Passive Listening** in the chat. Set the print
cadence and optional duration, then use **Stop** in the listening bar to turn it
off. Each session prints a continuous strip with one separator and optional date
at the start; later increments append text without extra gaps or cuts. See
[LIVE_PRINT_API.md](LIVE_PRINT_API.md) for the API and recovery behavior.

See [QUICK_START.md](QUICK_START.md) for an overview and
[DEPLOYMENT.md](DEPLOYMENT.md) for the complete deployment procedure.

For detailed setup instructions, continue reading below.

## Configuration

Before starting, you'll need to configure the following:

### Current Pi installation

Keep the Pi's existing `.env` with its password, printer, and microphone settings.
The website uses the API at the same origin; leave `productionApiUrl` at its
placeholder and `window._env.REACT_APP_API_URL` unset. The current chat and local
print history do not require reCAPTCHA or Convex.

See [REMOTE_ACCESS.md](REMOTE_ACCESS.md) for password setup and `env.example` for
available settings. Older split-hosting configuration is described in
[legacy Netlify notes](README_NETLIFY.md).

## Setup Instructions

These steps describe a fresh local installation. For the existing `sd-pi`
deployment, use [DEPLOYMENT.md](DEPLOYMENT.md) instead.

### 1. Install Dependencies

On your Raspberry Pi 4B, install the required Python packages:

```bash
# Install Python packages
pip3 install -r requirements.txt

# Install system dependencies for USB printer
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev libusb-1.0-0-dev

# For USB printer access (important!)
sudo usermod -a -G lp dialout pi
sudo apt-get install -y printer-driver-all
```

### 2. Connect Your Printer

#### For USB Connection:
1. Plug in your Netum thermal printer via USB
2. Find the USB vendor and product IDs:
   ```bash
   lsusb
   ```
   You should see something like: `Bus 001 Device 003: ID 0416:5011`
3. The first 4 digits (0416) are the vendor ID
4. The last 4 digits (5011) are the product ID
5. Update the values in `app.py` if needed

#### For Serial/GPIO Connection:
If your printer is connected via GPIO serial pins:
```bash
sudo raspi-config
# Navigate to Interface Options > Serial Port > Enable
```

### 3. Configure the Application

Edit the configuration in `app.py` or set environment variables:

```bash
# For USB printer (default)
export PRINTER_TYPE=usb
export USB_VENDOR=0x0416
export USB_PRODUCT=0x5011

# For serial printer
export PRINTER_TYPE=serial
export SERIAL_PORT=/dev/ttyAMA0

# For network printer
export PRINTER_TYPE=network
export NETWORK_HOST=192.168.1.100
```

### 4. Run the Application

```bash
python3 app.py
```

The application will start on `http://0.0.0.0:5000`

### 5. Access from Other Devices

Find your Raspberry Pi's IP address:
```bash
hostname -I
```

Then access the web interface from any device on your network:
```
http://[RASPBERRY_PI_IP]:5000
```

### 6. Run as a Service

The installed Pi already runs `serve_remote.py` under `ticket-printer.service`
with a separate `samson-tunnel.service`. Use [DEPLOYMENT.md](DEPLOYMENT.md) for
updates. For a new installation, follow the service configuration in
[REMOTE_ACCESS.md](REMOTE_ACCESS.md#keep-the-same-link-after-a-restart).
Only one application process should control the printer and microphone.

## Usage

1. Run the root `app.py` and open `http://[YOUR_PI_IP]:5000`.
2. Type in **Message Samson** and click the blue send arrow. Enter sends;
   Shift+Enter adds a new line.
3. Use **+** to add a **Photo**, **Vocab Word**, **Random Quote**, or **Random Meme**. Vocab Word adds
   a random word and its definition; Random Meme attaches a random still meme image.
   Vocab Word includes backup definitions for offline use; Random Meme needs an
   internet connection. Samson fetches and validates meme images on the server,
   trying another image when one is animated, missing, too large, or corrupt. This avoids
   image-host browser restrictions; failures keep the existing draft and photo.
   Both let you review the draft before sending. Image
   previews and optional captions share the message box and print together as one
   ticket. Printed photos and memes fill the printable paper width while keeping
   their proportions, with the same spacing below the date as text messages.
   Ticket previews and saved history use that same layout.
   You can also drop or paste an image into the box.
   **Random Quote** adds one of 16 bundled quotes with its author to your draft,
   works offline, and avoids repeating the previous quote while the page is open.
   Review or edit it, then send to print with your current settings. Existing text
   and photos are preserved; if the quote would exceed the 1,000-character limit,
   shorten your draft and try again.
4. Use the microphone button to record on the Pi. Review the transcript in the
   message box, then send it. See [microphone setup](MICROPHONE_SETUP.md).
5. Watch the conversation for print confirmations. Failed requests keep your
   draft; check the printer before resending if a response was lost.

The page supports light and dark mode and phone screens. The profile dot turns
green only when a printer is available and test mode is off. The microphone
button’s tooltip shows its availability.
Conversation history stays in the current page and resets when you reload.

Click **Samson** at the top to open settings and connection info for the Pi,
microphone, and printer. **Include date** adds the date and time to printed tickets;
it defaults to on and is remembered in this browser. Changes apply to new chat
tickets (including photos) and newly started Passive Listening sessions.
Connection info identifies the server as a Raspberry Pi only when its hardware
reports that identity. A local Mac or another computer is labeled as a server,
with its address, printer connection type, and a reason if printing needs setup.
**Check again** refreshes these checks without printing. To use the printer on
your Pi, open Samson at the Pi’s address or configure the frontend’s API URL.

To preview without using paper, run `TEST_MODE=true python app.py`. The chat labels
these messages as logged in test mode and shows the same ticket preview. The
tilted, torn-paper card contains the actual black-and-white bitmap sent to the
printer, including the Pi's timestamp, complete wrapped text, and processed photo.
Chat tickets are rendered once on the Pi and sent as raster graphics on every
printer connection; long messages are split into bands without shrinking or
truncating them. Trailing blank lines use compact paper-feed commands instead of
full-width white raster data, preserving the selected spacing without an extra
image transfer. Raster text can take longer to transfer over BLE than native text.
If another job owns the printer, Send shows **Waiting for printer…** and waits
for admission for roughly a minute. A message rejected throughout that wait is
labeled **Not sent**. Failed or uncertain prints are never automatically resent.
`IMAGE_MAX_WIDTH` sets the printable dot width (384 by default); the image height,
contrast, and dithering settings apply to attached photos, not the whole ticket.
Physical paper margins, tear position, and ink density depend on the printer.
A separate static deployment should publish
the complete `frontend/` directory, including `chat.css` and `chat.js`.

## Ticket Format

The tickets are printed in this format:

```
================================
TICKET
--------------------------------
From: [Name]
Time: [Current Time]
Date: [Current Date]
--------------------------------
Question/Comment
[Your message]
--------------------------------
================================
```

## Troubleshooting

### Printer Not Detected

If the printer is not detected:
1. Check USB connection
2. Verify printer is powered on
3. Run `lsusb` to see if the device is recognized
4. Try different USB ports
5. Check permissions: `sudo chmod 666 /dev/bus/usb/00X/00Y`

### Permission Errors

If you get permission errors:
```bash
sudo usermod -a -G lp,dialout pi
sudo chmod 666 /dev/ttyUSB0  # or /dev/ttyAMA0 for GPIO
# Then log out and log back in
```

### Test Printer Connection

You can test the printer connection:
```bash
python3 << EOF
from escpos.printer import Usb
p = Usb(0x0416, 0x5011)
p.text("Test print\n")
p.cut()
EOF
```

### View Logs

If running as a service:
```bash
sudo journalctl -u ticket-printer -f
```

## API Endpoints

- `GET /` - Web interface
- `POST /print` - Print a chat message: `{"type":"text","content":"Hello Pi"}`,
  or a photo: `{"type":"image","content":"data:image/png;base64,...","caption":"Optional message"}`.
  Messages and captions support up to 1,000 characters.
  Successful responses include `test_mode` and `preview` with a PNG data URL in
  `image`, pixel `width`/`height`, and the full formatted `text` for accessibility.
  Update the Pi backend and frontend together to enable the matching previews.
- `POST /submit_ticket` - Submit a ticket to print
  - Body: `{"from_name": "John Doe", "question": "Your question here"}`
- `GET /health` - Health check endpoint

## Requirements

- Python 3.7+
- Netum 58mm ESC/POS thermal printer (https://amzn.to/43Vx9DT)
- Raspberry Pi 4B (https://amzn.to/4ooA5jS)
- 58mm Receipt Paper (https://amzn.to/4ag6q8Y)
- Flask web framework
- python-escpos library

## Deployment Options

This application supports multiple deployment configurations:

### Local Only (Raspberry Pi)
- Run `app.py` directly on the Raspberry Pi
- Access via local network: `http://[PI_IP]:5000`

### Password-protected remote access (Current installation)

- The app and tunnel run as separate services on the Pi.
- Open the HTTPS link from `samson-link` and enter the configured password.
- See [DEPLOYMENT.md](DEPLOYMENT.md) for updates and
  [REMOTE_ACCESS.md](REMOTE_ACCESS.md) for initial setup and a persistent URL.

### Separate frontend on Netlify (Legacy)

The old standalone API does not provide the current frontend's full feature set.
See [legacy Netlify notes](README_NETLIFY.md) before reusing those files.

## Environment Variables

On an existing Pi, edit its current `.env` instead of replacing it.
For a new installation only:

```bash
cp env.example .env
# Edit .env with your settings
```

Key variables:
- `PRINTER_TYPE` - Type of printer connection (usb, serial, network, bluetooth)
- `USB_VENDOR` / `USB_PRODUCT` - USB printer IDs (find with `lsusb`)
- `RECAPTCHA_SITE_KEY` - Your Google reCAPTCHA site key
- `CONVEX_DEPLOYMENT` - Convex database URL (optional)

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to contribute to this project.

## Code of Conduct

This project adheres to a Code of Conduct that all contributors are expected to follow. Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before participating.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a detailed history of changes and versions.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

Feel free to modify and use as needed!
