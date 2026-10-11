# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Feed trailing blank paper with compact ESC/POS commands instead of slow raster
  transfers, preserving the preview and selected margin.
- Wait for a busy printer before sending the next message, and distinguish
  messages that never started from uncertain print outcomes.
- Continue recording after recoverable microphone input overflows, warn about
  missing audio, and distinguish transcription overload from a stopped USB stream.
- Reuse an existing BlueZ printer connection when the connected printer stops
  advertising, and wait briefly when a status check rejects a new print before it starts.
- Respect Bluetooth packet limits, time out stalled writes, and stop stuck
  Bluetooth processes so printing can recover without restarting the website.
- Describe HTML gateway failures as connection errors while preserving the
  unconfirmed message, rather than suggesting an incorrect API address.
- Fetch random memes through Samson to avoid image-host browser restrictions,
  with alternate images, bounded downloads, and draft preservation on failure.
- Isolate printer operations from web workers, bound print and connection-check
  waits, and report busy or stalled hardware without blocking the website.
- Keep each ticket preview or print error directly below its sender’s message,
  including photos, random memes, and vocab words, when multiple sends are queued.
- Clear the composer immediately on Send and queue messages in order, so users
  can send back to back without waiting for printing or losing their next draft.
- Replaced browser password popups with a mobile-friendly sign-in page and
  signed sessions, so stale browser credentials no longer cause a login loop.
- Kept the tilted, torn-paper ticket card and replaced its placeholder content
  with the exact raster sent to the printer, including full text, timestamps,
  and processed photos. Test mode now shows the same preview without printing.
- Named the chat contact Samson and added a portrait avatar.
- Replaced the tabbed form with a responsive conversation with Samson, including
  print confirmations, inline photo attachments, and recording in the composer.
- Added optional image captions to `/print` so a photo and message share one ticket.
- Exposed frontend assets through Flask and made test-mode confirmations explicit.

### Added
- Add an optional offline Sherpa listening backend with streaming English speech
  recognition and confidence-filtered, deduplicated sound labels on tickets.
- Add a checksum-verified model installer and optional speech-only noise reduction.
- Added password-protected remote access, a single-process server for HTTPS
  tunnels, and a command to create a temporary Cloudflare link from the Pi.
- Added **Listen & print** to the plus menu with custom print cadence, timed or
  indefinite listening, status recovery after refresh, and manual Stop.
- Initial open source release
- Web-based ticket submission interface
- Support for USB, Serial, Network, and Bluetooth printer connections
- reCAPTCHA spam protection
- Optional Convex database integration for logging tickets
- Netlify deployment support
- Raspberry Pi backend API
- Systemd service configuration for auto-start
- Comprehensive documentation and setup guides

### Features
- **Printer Support**: USB, Serial/GPIO, Network, and Bluetooth connections
- **Multiple Deployment Options**: 
  - Standalone Flask app on Raspberry Pi
  - Frontend on Netlify + Backend on Raspberry Pi
- **Database Integration**: Optional Convex database logging
- **Spam Protection**: Google reCAPTCHA integration
- **Auto-restart**: Systemd service with auto-restart on failure

### Documentation
- Main README with setup instructions
- Netlify deployment guide
- GitHub deployment guide
- Bluetooth printer setup guide
- Convex database setup guides
- Quick start guide
- Environment variable examples

## [1.0.0] - Initial Release

### Added
- Core ticket printing functionality
- Web interface for ticket submission
- ESC/POS thermal printer support
- Timestamp and date stamping
- Health check endpoint
- Error handling and logging

---

## Release Notes

### Version 1.0.0
Initial release of the Ticket Printer Application. Supports basic ticket printing with a web interface on Raspberry Pi, with optional Netlify frontend deployment.

---

**Note**: Future releases will be documented here with specific version numbers and dates.
