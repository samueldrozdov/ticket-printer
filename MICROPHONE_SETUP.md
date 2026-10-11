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
for its API, or open **+ → Passive Listening** in the chat to choose the cadence and
duration. The listening bar always exposes **Stop**; closing the page leaves the
Pi listening until stopped or the duration expires.

Both modes display an animated sound icon measured from the Pi's microphone,
updating about four times per second. The bars grow with incoming volume and
settle during quiet audio. If samples or the connection are unavailable, the bars
reset and dim. Sound, quiet, and unavailable states are described to screen readers.
Activity does not guarantee recognizable speech. Only level measurements reach
the browser; microphone audio stays on the Pi.

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

## Upgrade to local speech and sound recognition

For room listening, use the optional **Sherpa** backend. It runs two quantized
models on the Pi: an English streaming Zipformer trained on LibriSpeech and
GigaSpeech, and a small AudioSet sound classifier. Recognized sounds appear as
labels such as **[dog barking]** alongside speech. Review mode keeps them in the
draft; **Listen & print** prints them at the selected cadence.

```bash
python -m pip install -r requirements-listening.txt
python install_listening_models.py
```

Set these values in the Pi's existing `.env`, then restart the app service:

```dotenv
MICROPHONE_BACKEND=sherpa
SOUND_EVENT_THRESHOLD=0.6
SPEECH_ENHANCEMENT=false
```

The installer downloads pinned model files from the official Sherpa releases and
verifies their SHA-256 checksums. Downloads happen only during setup. Recognition
is entirely local: no audio is uploaded or saved, and network access is not needed
after installation. `LISTENING_MODELS_PATH` can override the local model folder.
To revert, set `MICROPHONE_BACKEND=vosk` and restart; keep the old Vosk model installed.

Sound labels are estimates, not guaranteed detections. The default allowlist
includes barking, meowing, birds, laughter, coughing, sneezing, clapping, knocking,
doorbells, phone ringing, sirens, and smoke-alarm sounds. Generic classes such as
“animal” and low-confidence predictions are ignored. A continuous sound gets one
label; two quiet classification windows rearm it, with at least 15 seconds between
repeated labels. This is not a safety or emergency-monitoring system.

**Distance:** software cannot restore speech that the microphone cannot capture
clearly. For voices and sounds around the room, put the Go Mic in its **omni
(circle)** pattern, off the printer's vibrating surface and away from the Pi's
fan. For one speaker in a known direction, use cardioid and face its front toward
them. Avoid the **−10 dB** pad for quiet, distant voices. Check performance from
the actual speaking position before relying on it; room echo and noise matter.

Optional GTCRN speech enhancement can be installed with
`python install_listening_models.py --with-enhancement`, then enabled with
`SPEECH_ENHANCEMENT=true`. It only processes the speech branch; sound labels always
use the original audio. It is off by default because it made the quiet-speech
benchmark worse and nearly doubled processing time on the deployed Pi 4.

On the deployed 4 GB Raspberry Pi 4, the tested speech-plus-sound pipeline ran at
approximately **0.5 seconds of processing per second of audio**, using about
**434 MB peak memory** in the evaluation process. Public speech, attenuated speech
with added noise, barking, silence, and speech followed by barking were checked.
These are sample checks, not a measured room-distance or accuracy guarantee.

Model sources and APIs:
[English speech model](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html#csukuangfj-sherpa-onnx-streaming-zipformer-en-2023-06-21-english),
[sound classifier](https://k2-fsa.github.io/sherpa/onnx/audio-tagging/pretrained_models.html),
[Go Mic pickup patterns](https://samsontech.com/products/microphones/usb-microphones/gomic/).

## Troubleshooting

- **Some audio was missed:** the microphone reported an input-buffer overflow.
  Recording continues, with a warning to check for missing words. This does not
  mean the USB microphone disconnected. The app logs the overflow without saving
  audio or transcript content. If recognition itself cannot keep up and fills
  the bounded audio queue, recording stops with a separate overload message.
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
