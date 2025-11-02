# Deploy to Netlify via GitHub

This guide will help you deploy the frontend to Netlify and connect it to your Raspberry Pi backend.

## Architecture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   Netlify       │         │   Tunneling     │         │   Raspberry Pi  │
│   (Frontend)    │─────────▶│   Service       │─────────▶│   (API + Printer)│
│                 │         │   (ngrok/etc)   │         │                 │
└─────────────────┘         └─────────────────┘         └─────────────────┘
```

## Step 1: Set Up GitHub Repository

```bash
# Initialize git if not already done
git init

# Add all files (except those in .gitignore)
git add .
git commit -m "Initial commit - Ticket printer app"

# Create a repository on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/ticket-printer-app.git
git branch -M main
git push -u origin main
```

Create a `.gitignore` file:

```bash
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
ENV/

# Node (if you add frontend build tools)
node_modules/
npm-debug.log*

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Project specific
*.log
EOF
```

## Step 2: Deploy Frontend to Netlify

### Option A: Automatic Deployment via GitHub

1. Go to [Netlify](https://www.netlify.com/)
2. Sign up/Login
3. Click "Add new site" → "Import an existing project"
4. Connect to GitHub
5. Select your repository
6. Configure build settings:
   - **Build command**: `echo "No build required"`
   - **Publish directory**: `frontend`
7. Click "Deploy site"

### Option B: Netlify CLI

```bash
# Install Netlify CLI
npm install -g netlify-cli

# Login to Netlify
netlify login

# Deploy
netlify deploy --prod --dir=frontend
```

## Step 3: Set Up Raspberry Pi Backend

### Install Dependencies

```bash
# SSH into your Raspberry Pi
ssh pi@raspberrypi.local

# Clone the repository (or upload files)
git clone https://github.com/YOUR_USERNAME/ticket-printer-app.git
cd ticket-printer-app/backend

# Install dependencies
pip3 install -r requirements.txt
```

### Configure Printer

```bash
# Find your printer
sudo lsusb

# Edit api.py if needed to set correct vendor/product IDs
nano api.py
```

### Run the API

```bash
# Test run
python3 api.py

# Or run as a service
sudo cp ticket-printer.service /etc/systemd/system/
sudo systemctl enable ticket-printer
sudo systemctl start ticket-printer
```

## Step 4: Expose Raspberry Pi to Internet

You need to expose your Raspberry Pi's API to the internet so Netlify can reach it.

### Option 1: ngrok (Easiest for Testing)

```bash
# On Raspberry Pi, install ngrok
# Download from https://ngrok.com/download
# For Raspberry Pi:
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm.tgz
tar -xvzf ngrok-v3-stable-linux-arm.tgz
sudo cp ngrok /usr/local/bin/

# Start ngrok tunnel
ngrok http 5000

# Note the forwarding URL (e.g., https://abc123.ngrok.io)
```

### Option 2: Cloudflare Tunnel (Free, Recommended)

```bash
# On Raspberry Pi
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/

# Start tunnel
cloudflared tunnel --url http://localhost:5000

# Note the tunnel URL
```

### Option 3: Expose Via Router (More Complex)

1. Forward port 5000 on your router to your Raspberry Pi
2. Set up dynamic DNS (e.g., duckdns.org)
3. Use your domain name to access the API

## Step 5: Connect Frontend to Backend

### Configure Netlify Environment Variable

1. Go to Netlify dashboard
2. Select your site
3. Go to Site Settings → Environment variables
4. Add: `REACT_APP_API_URL` = `https://your-ngrok-or-tunnel-url`
5. Redeploy the site

### Or Update Frontend Code

Edit `frontend/index.html` and replace the API URL:

```javascript
const productionApiUrl = 'https://your-tunnel-url.com';
```

Then commit and push:
```bash
git add frontend/index.html
git commit -m "Update API URL"
git push
```

Netlify will automatically redeploy.

## Step 6: Test the Deployment

1. Open your Netlify site URL
2. Fill out the form
3. Click "Print Ticket"
4. Your Raspberry Pi should print the ticket!

## Step 7: Keep It Running

### For ngrok (temporary tunnels)

Create a systemd service to keep ngrok running:

```bash
sudo nano /etc/systemd/system/ngrok.service
```

Add:
```ini
[Unit]
Description=ngrok tunnel
After=network.target

[Service]
ExecStart=/usr/local/bin/ngrok http 5000 --log=stdout
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl enable ngrok
sudo systemctl start ngrok
```

### For Cloudflare Tunnel (persistent)

```bash
# Create systemd service
sudo nano /etc/systemd/system/cloudflared.service
```

Add:
```ini
[Unit]
Description=Cloudflare tunnel
After=network.target

[Service]
ExecStart=/usr/local/bin/cloudflared tunnel --url http://localhost:5000
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

## Security Considerations

1. **Add authentication** to your API
2. **Use HTTPS** for the tunnel
3. **Rate limit** API requests
4. **Add CORS restrictions** if needed
5. **Use environment variables** for sensitive data

## Troubleshooting

### Frontend can't reach backend

1. Check that your tunnel is running: `ps aux | grep ngrok`
2. Verify the API URL in Netlify environment variables
3. Test the API directly: `curl https://your-tunnel-url/health`

### Backend not responding

1. Check if API is running: `sudo systemctl status ticket-printer`
2. Check logs: `sudo journalctl -u ticket-printer -f`
3. Verify printer is connected

### Printing doesn't work

1. Check printer connection: `sudo lsusb`
2. Verify permissions: `sudo usermod -a -G lp,dialout pi`
3. Test printer: `python3 -c "from escpos.printer import Usb; p = Usb(0x0416, 0x5011); p.text('Test'); p.cut()"`

## Success Checklist

- [ ] Frontend deployed to Netlify
- [ ] Backend API running on Raspberry Pi
- [ ] Tunnel service configured and running
- [ ] API URL configured in Netlify
- [ ] Printer connected and working
- [ ] Can submit tickets from Netlify site
- [ ] Tickets print successfully on Raspberry Pi

## Advanced: Add Authentication

For production use, add authentication to protect your API:

```python
# In backend/api.py
from functools import wraps
import os

API_KEY = os.getenv('API_KEY', 'your-secret-key')

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.headers.get('X-API-Key') != API_KEY:
            return jsonify({'error': 'Invalid API key'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/submit_ticket', methods=['POST'])
@require_api_key
def submit_ticket():
    # ... existing code
```

Then update frontend to send API key:
```javascript
headers: {
    'Content-Type': 'application/json',
    'X-API-Key': 'your-secret-key'
}
```


