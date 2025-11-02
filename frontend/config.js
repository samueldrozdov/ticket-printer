// API Configuration
// Set your Raspberry Pi API URL here
// When deployed to Netlify, this will be set via environment variables

const API_CONFIG = {
    // For local development
    LOCAL_API_URL: 'http://localhost:5000',
    
    // For production (replace with your Raspberry Pi URL)
    // Options:
    // 1. If using ngrok: 'https://your-ngrok-url.ngrok.io'
    // 2. If using Cloudflare Tunnel: 'https://your-tunnel-url.trycloudflare.com'
    // 3. If Raspberry Pi is exposed: 'http://your-pi-ip:5000'
    PRODUCTION_API_URL: ''
};

// Get the appropriate API URL
function getApiUrl() {
    // Check if we're in production
    if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
        // In production
        return API_CONFIG.PRODUCTION_API_URL || '/api'; // fallback to proxy
    } else {
        // In local development
        return API_CONFIG.LOCAL_API_URL;
    }
}

// Export the function
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { getApiUrl };
}


