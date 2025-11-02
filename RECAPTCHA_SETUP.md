# reCAPTCHA Setup Instructions

## Get Your reCAPTCHA Site Key

1. Go to https://www.google.com/recaptcha/admin
2. Sign in with your Google account
3. Click "Create"
4. Fill out the form:
   - **Label**: Ticket Printer (or any name you choose)
   - **reCAPTCHA type**: Select "reCAPTCHA v2" → "I'm not a robot" Checkbox
   - **Domains**: Add:
     - `your-site-name.netlify.app` (your Netlify site)
     - `localhost` (for testing)
   - Accept terms
   - Click "Submit"

5. Copy your **Site key** (looks like: `6LcXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`)

## Set Netlify Environment Variable

1. Go to Netlify Dashboard
2. Your site → **Site settings** → **Environment variables**
3. Click **Add variable**
4. Key: `RECAPTCHA_SITE_KEY`
5. Value: Paste your site key
6. Click **Save**

## Test It

1. Netlify will auto-deploy with the new env var
2. Visit your site
3. You should see a reCAPTCHA checkbox
4. Try submitting a ticket - must check the box first!

## Local Development

For testing locally, the fallback in the code will use a placeholder. You can:
- Set the actual key temporarily in the code, OR
- Just comment out the reCAPTCHA validation for local testing

