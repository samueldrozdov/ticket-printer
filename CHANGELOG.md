# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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

