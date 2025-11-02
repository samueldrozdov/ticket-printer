# Quick Start: Deploy to Netlify

This guide will get your ticket printer app deployed to Netlify via GitHub in under 10 minutes.

## 🚀 Quick Deploy Steps

### 1. Push to GitHub (2 min)

```bash
# If not already a git repo
git init
git add .
git commit -m "Initial commit"

# Push to GitHub (create repo first on GitHub.com)
git remote add origin https://github.com/YOUR_USERNAME/ticket-printer-app.git
git branch -M main
git push -u origin main
```

### 2. Deploy to Netlify (3 min)

1. Go to [netlify.com](https://netlify.com) and sign up
2. Click "Add new site" → "Import an existing project"
3. Connect to GitHub and select your repo
4. **Build settings:**
   - Build command: `echo "No build required"`
   - Publish directory: `frontend`
5. Click "Deploy site"
6. Your site will be live in ~30 seconds! 🎉

### 3. Set Up Raspberry Pi Backend (5 min)

```bash
# SSH into Raspberry Pi
ssh pi@raspberrypi.local

# Clone the repo
git clone https://github.com/YOUR_USERNAME/ticket-printer-app.git
cd ticket-printer-app/backend

# Install dependencies
pip3 install -r requirements.txt

# Find your printer
sudo lsusb  # Note the IDs

# Run the API
python3 api.py
```

### 4. Expose API to Internet

**Option A: Quick Test with ngrok**

```bash
# On Raspberry Pi
# Download ngrok
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm.tgz
tar -xvzf ngrok-v3-stable-linux-arm.tgz
sudo mv ngrok /usr/local/bin/

# Run ngrok
ngrok http 5000
# Copy the https URL (e.g., https://abc123.ngrok.io)
```

**Option B: Persistent with Cloudflare Tunnel**

```bash
# On Raspberry Pi
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/

# Run tunnel
cloudflared tunnel --url http://localhost:5000
# Copy the https URL
```

### 5. Connect Frontend to Backend

Edit `frontend/index.html` line 196:
```javascript
const productionApiUrl = 'https://YOUR-TUNNEL-URL.ngrok.io';
```

Or set Netlify environment variable:
1. Netlify dashboard → Site settings → Environment variables
2. Add: `REACT_APP_API_URL` = `https://YOUR-TUNNEL-URL.ngrok.io`
3. Redeploy

## ✅ Test It!

1. Open your Netlify site
2. Fill out the form
3. Submit a ticket
4. Watch it print! 🎊

## 📁 Project Structure

```
ticket-printer-app/
├── frontend/          # Static HTML for Netlify
│   └── index.html
├── backend/           # Flask API for Raspberry Pi
│   ├── api.py
│   └── requirements.txt
├── app.py            # Original full-stack version
├── netlify.toml      # Netlify config
└── GITHUB_DEPLOYMENT.md  # Detailed guide
```

## 🔧 Configuration

### For USB Printer:
Edit `backend/api.py`:
```python
USB_VENDOR = int(os.getenv('USB_VENDOR', '0x0416'), 16)
USB_PRODUCT = int(os.getenv('USB_PRODUCT', '0x5011'), 16)
```

### For Network Printer:
```bash
export PRINTER_TYPE=network
export NETWORK_HOST=192.168.1.100
```

## 🛠️ Troubleshooting

**Frontend loads but can't print:**
- Check ngrok is running
- Verify API URL in frontend code
- Test: `curl https://your-tunnel-url/health`

**Backend not running:**
```bash
# Check status
sudo systemctl status ticket-printer

# View logs
sudo journalctl -u ticket-printer -f

# Restart
sudo systemctl restart ticket-printer
```

**Printer issues:**
```bash
# Test printer
python3 -c "from escpos.printer import Usb; p = Usb(0x0416, 0x5011); p.text('Test'); p.cut()"

# Fix permissions
sudo usermod -a -G lp,dialout pi
# Then log out and back in
```

## 📚 More Info

- Full deployment guide: `GITHUB_DEPLOYMENT.md`
- Raspberry Pi setup: `DEPLOYMENT.md`
- Original README: `README.md`

## 🎯 What You Get

✅ Beautiful web interface hosted on Netlify  
✅ Accessible from anywhere  
✅ Raspberry Pi backend handles printing  
✅ Secure tunneling (ngrok or Cloudflare)  
✅ Free hosting (Netlify free tier)  
✅ Auto-deploy from GitHub  

## 🔐 Security Tips

1. Add API key authentication (see `GITHUB_DEPLOYMENT.md`)
2. Use HTTPS (automatic with ngrok/Cloudflare)
3. Consider rate limiting for production
4. Keep your tunnel URL private

---

**Questions?** See the detailed guides:
- `GITHUB_DEPLOYMENT.md` - Full deployment setup
- `DEPLOYMENT.md` - Raspberry Pi setup


