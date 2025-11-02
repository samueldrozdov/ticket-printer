# Contributing to Ticket Printer App

Thank you for your interest in contributing to the Ticket Printer App! This document provides guidelines and instructions for contributing.

## How to Contribute

### Reporting Bugs

If you find a bug, please create an issue with:
- A clear, descriptive title
- Steps to reproduce the bug
- Expected behavior vs actual behavior
- Your environment details (OS, Python version, printer model, etc.)
- Any error messages or logs

### Suggesting Features

Feature suggestions are welcome! Please create an issue with:
- A clear description of the feature
- Use case and why it would be useful
- Possible implementation approach (if you have ideas)

### Pull Requests

1. **Fork the repository** and create a new branch from `main`
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the code style guidelines below

3. **Test your changes** thoroughly:
   - Test with different printer types if possible
   - Verify frontend and backend integration
   - Check for any breaking changes

4. **Update documentation** if needed:
   - Update README.md if you changed setup instructions
   - Add comments to complex code sections
   - Update CHANGELOG.md with your changes

5. **Commit your changes** with clear, descriptive commit messages
   ```bash
   git commit -m "Add feature: description of what you added"
   ```

6. **Push to your fork** and create a Pull Request
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Submit the PR** with:
   - Clear description of changes
   - Reference to related issues (if any)
   - Screenshots or examples (if applicable)

## Code Style

### Python

- Follow PEP 8 style guide
- Use meaningful variable and function names
- Add docstrings to functions and classes
- Keep functions focused and single-purpose
- Use 4 spaces for indentation

### JavaScript

- Use meaningful variable names
- Add comments for complex logic
- Follow consistent formatting
- Use modern ES6+ features where appropriate

### Documentation

- Update README.md for user-facing changes
- Keep comments clear and concise
- Document complex algorithms or workarounds

## Project Structure

```
ticket-printer-app/
├── app.py              # Standalone Flask app
├── backend/
│   ├── api.py         # API-only version for Netlify deployments
│   └── requirements.txt
├── frontend/
│   └── index.html     # Frontend UI
├── netlify/
│   └── functions/     # Netlify serverless functions
├── templates/         # Flask templates (for standalone version)
├── requirements.txt   # Python dependencies
└── README.md         # Main documentation
```

## Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/ticket-printer-app.git
   cd ticket-printer-app
   ```

2. **Set up Python environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **For frontend development**
   - Edit `frontend/index.html` directly
   - Test with local backend: `python3 backend/api.py`

4. **Test your changes**
   ```bash
   # Test backend
   python3 backend/api.py
   
   # Or test standalone
   python3 app.py
   ```

## Areas for Contribution

We're particularly interested in contributions for:

- **Printer compatibility**: Support for more printer models and connection types
- **UI/UX improvements**: Better user interface and experience
- **Documentation**: Improving setup guides and troubleshooting
- **Error handling**: Better error messages and recovery
- **Testing**: Unit tests and integration tests
- **Security**: Security improvements and best practices
- **Internationalization**: Multi-language support

## Questions?

If you have questions about contributing, feel free to:
- Open an issue with the `question` label
- Ask in discussions (if enabled)

## Code of Conduct

Please be respectful and constructive in all interactions. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for details.

Thank you for contributing! 🎉

