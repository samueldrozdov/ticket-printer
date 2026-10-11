# Samson quick start

The current website and API run together on the Raspberry Pi. Open the public
HTTPS link shown by `samson-link` on the Pi and sign in with its configured
password. The Pi must stay online and connected to the printer and microphone.

To publish updates, follow [DEPLOYMENT.md](DEPLOYMENT.md):

1. Review and test the completed changes on the development computer.
2. Commit and push them to GitHub; record the commit ID.
3. Install that exact commit in `/home/sd/ticket-printer-os` on the Pi.
4. Wait for printing/listening to finish, then restart `ticket-printer.service`.
5. Preserve any draft, reload the website, and verify the change.

A GitHub push does not automatically update the Pi. Keep `samson-tunnel.service`
running during app updates to preserve the current public URL.

- [Initial remote access setup](REMOTE_ACCESS.md)
- [Local speech and sound recognition](MICROPHONE_SETUP.md#upgrade-to-local-speech-and-sound-recognition)
- [Using the website](README.md#quick-start)
