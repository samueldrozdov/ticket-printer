# Speak, review, and print

Plug the Samson Go Mic into a USB port on the **Raspberry Pi**. The Pi converts
speech to text locally with Vosk; the browser lets you review and edit it before
pressing **Print**. The printer keeps its existing Bluetooth connection.

You can use the page from your Mac or from the Pi's desktop. **Record on Pi** always
uses the Pi's USB microphone. Each recording requires a button press and stops
after at most 30 seconds. Audio is held in memory, never uploaded or saved to disk.
The app retains up to eight recent transcripts in memory until restart. Printing
is a separate action in this review flow.

An opt-in backend mode can also listen continuously and print at a chosen cadence,
with a duration limit or manual stop. See [LIVE_PRINT_API.md](LIVE_PRINT_API.md)
for its API, or open **+ → Listen & print** in the chat to choose the cadence and
duration. The listening bar always exposes **Stop**; closing the page leaves the
Pi listening until stopped or the duration expires.

## 1. Reconnect to the Pi

Power it on and plug in the microphone. If you previously used a remote desktop:

- For Raspberry Pi Connect, sign in at <https://connect.raspberrypi.com>, find the
  Pi, and choose **Connect via → Screen sharing** or **Remote shell**.
- For VNC, use the saved Pi connection in your VNC viewer.
- If neither is configured, connect a monitor and keyboard. On the Pi, open a
  terminal and run `sudo raspi-config`; enable **Interface Options → SSH**.
  Connect the Pi and Mac to the same network.

In a terminal on the Pi, run these separately:

```bash
whoami
hostname -I
```

The first prints your username; the second prints the network addresses. From a
Mac terminal, connect using those values, for example `ssh alice@192.168.1.42`.
Use your existing Pi password if prompted. Do not re-image the SD card to regain
access: that would replace the existing setup.

[Official remote access guide](https://www.raspberrypi.com/documentation/computers/remote-access.html)
and [Raspberry Pi Connect guide](https://www.raspberrypi.com/documentation/services/connect.html).

## 2. Install microphone support on the Pi

First copy this updated project to the Pi, preserving its existing `.env` printer
settings. Run these commands **inside the project directory on the Pi**. Use
Python 3.9 or newer and the root `app.py`; the older `backend/api.py` does not
provide microphone or generic `/print` routes.

```bash
sudo apt-get update
sudo apt-get install -y python3-venv libportaudio2 alsa-utils unzip curl
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt -r requirements-microphone.txt
```

Download and extract the small English speech model once (about 40 MB):

```bash
mkdir -p models
curl --fail --location https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip -o models/vosk-model-small-en-us-0.15.zip
unzip -n models/vosk-model-small-en-us-0.15.zip -d models
```

After installation, speech recognition works without internet access. Other
languages are available on the [Vosk model page](https://alphacephei.com/vosk/models).

## 3. Check the microphone and enable it

```bash
arecord -l
python -m sounddevice
```

Look for a Samson/Go Mic input device. Edit the existing `.env` file (or create
one) and add:

```dotenv
MICROPHONE_ENABLED=true
MICROPHONE_DEVICE=Samson
DEBUG=False
```

`MICROPHONE_DEVICE` accepts a unique part of the input's name or its numeric ID
from **`python -m sounddevice`**. ALSA card numbers from `arecord -l` are different.
If `Samson` matches multiple inputs or none, use the exact device ID shown.
The app records mono 16-bit audio at that device's default sample rate.

The model defaults to `models/vosk-model-small-en-us-0.15` beside `app.py`.
For a different location, set `VOSK_MODEL_PATH` to its extracted directory.

For one speaker, set the Go Mic to cardioid and speak toward its front logo.
[Samson's setup instructions](https://samsontech.zendesk.com/hc/en-us/articles/360050013153-Go-Mic-Quick-Start).

## 4. Start and use the app

```bash
source venv/bin/activate
python app.py
```

If a printer service is already running, update it to run this project's root
`app.py` with `venv/bin/python`, then restart that service instead of launching a
second copy. Recording uses one process; do not deploy multiple application
workers against the same USB microphone.

Open `http://PI_ADDRESS:5000` in a browser (substitute the Pi's address):

1. Click the microphone button to the right of **Message Pi**.
2. Wait until the message box says **Listening**, then speak into the Go Mic.
3. Click the stop button, or wait for the 30-second limit.
4. Review and edit the transcription in the same message box. Existing text is preserved.
5. Click the blue send arrow when ready. Nothing prints just from recording.

To check this flow before using paper, launch with `TEST_MODE=true python app.py`.
This still uses the real Pi microphone but logs the print instead of using the
printer. Restart without `TEST_MODE=true` for physical printing.

## Troubleshooting

- **Microphone is not enabled:** set `MICROPHONE_ENABLED=true` and restart the app,
  then reload the page.
- **No input device / cannot open microphone:** check the USB cable, run
  `python -m sounddevice` in the app's virtual environment and under the same user,
  and correct `MICROPHONE_DEVICE`. Close other apps that have exclusive audio access.
- **Speech model missing:** point `VOSK_MODEL_PATH` at the extracted model folder,
  not the ZIP file or its parent `models` directory.
- **Permission denied when running as a service:** ensure that service's user can
  access the Pi's audio devices. On Raspberry Pi OS, add that user to the `audio`
  group with `sudo usermod -aG audio YOUR_PI_USERNAME`, then restart the service
  (or log out and back in for interactive sessions).
- **No speech detected:** check the mic's position and capture level with
  `alsamixer` (F6 selects the USB card). Short recordings, background noise, and
  unfamiliar words can affect recognition; edit the text before printing.
- **Page reports microphone unavailable:** use the updated root `app.py` and the
  matching frontend. A static hosted frontend needs its API URL set to the Pi's
  reachable API as before.
- **Separate frontend origin:** set `MICROPHONE_ALLOWED_ORIGINS` to the frontend's
  exact origin (for example `https://your-site.netlify.app`) and restart. Multiple
  origins can be comma-separated. Same-origin requests work without this setting.

Without a configured password, use this app on a trusted local network. For
access from other networks, follow [REMOTE_ACCESS.md](REMOTE_ACCESS.md): it adds
password protection to all routes and keeps origin checks working over HTTPS.
The origin check alone is not login protection.

## Developer checks

```bash
python -m unittest discover -s tests -v
```

The tests simulate microphone audio and printing. A real microphone and printer
still need an end-to-end check on the Pi.
