# Netlify Deployment Steps

## Your Repository
✅ GitHub: https://github.com/YOUR_USERNAME/ticket-printer-app

## Deployment Settings

**Site name:** (choose any name, e.g., `ticket-printer-app`)

**Build settings:**
- **Base directory:** (leave blank)
- **Build command:** `echo "No build required"`
- **Publish directory:** `frontend`

**Environment variables:** (optional for now)
- Can add later if needed

## After Deployment

Your Netlify site will be live at:
`https://YOUR-SITE-NAME.netlify.app`

## Make Sure These Are Running

### 1. Raspberry Pi - ngrok Tunnel
The ngrok tunnel must be running on your Raspberry Pi:
```bash
# Should show the tunnel is active
ngrok http 5000
```

Your URL: `https://your-ngrok-url.ngrok-free.dev`
   - Replace with your actual ngrok URL

### 2. Raspberry Pi - Flask Backend
Your Flask app should be running:
```bash
python3 app.py
```

Or if you've set it up as a service:
```bash
sudo systemctl status ticket-printer
```

### 3. Test the Connection

Once deployed to Netlify:
1. Visit your Netlify URL
2. Fill out the form
3. Submit a ticket
4. Check your Raspberry Pi printer - it should print!

## Verify Backend is Working

Test your backend API directly:
```bash
curl https://your-ngrok-url.ngrok-free.dev/health
```
   - Replace with your actual ngrok URL

Should return:
```json
{"status": "healthy", "printer_connected": true}
```

## Troubleshooting

### Frontend can't reach backend
- Check ngrok is running: `ngrok http 5000`
- Verify API URL in frontend/index.html (line 196)
- Check CORS is enabled in app.py

### Backend not responding
- Check Flask app is running: `python3 app.py`
- Verify printer is connected: `sudo lsusb`
- Check permissions: `sudo usermod -a -G lp,dialout pi`

### Can't deploy to Netlify
- Make sure you're deploying the `frontend/` folder
- Check build settings match the instructions
- Review Netlify deploy logs for errors

