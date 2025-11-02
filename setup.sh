#!/bin/bash

echo "🚀 Setting up Ticket Printer Application"
echo "=========================================="
echo ""

# Check if running on Raspberry Pi
if ! grep -q "Raspberry" /proc/cpuinfo 2>/dev/null; then
    echo "⚠️  Warning: This script is designed for Raspberry Pi"
    echo "   You can still proceed, but some steps may need adjustment"
    echo ""
fi

# Update system packages
echo "📦 Updating system packages..."
sudo apt-get update

# Install Python dependencies
echo "🐍 Installing Python dependencies..."
sudo apt-get install -y python3-pip python3-dev libusb-1.0-0-dev

# Install printer drivers
echo "🖨️  Installing printer drivers..."
sudo apt-get install -y printer-driver-all

# Install Python packages
echo "📚 Installing Python packages..."
pip3 install -r requirements.txt

# Add user to lp and dialout groups for printer access
echo "👤 Setting up permissions..."
sudo usermod -a -G lp,dialout $USER

# Create systemd service file
echo "⚙️  Creating systemd service..."
sudo tee /etc/systemd/system/ticket-printer.service > /dev/null <<EOF
[Unit]
Description=Ticket Printer Application
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=/usr/bin/python3 $(pwd)/app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
sudo systemctl daemon-reload

echo ""
echo "✅ Setup complete!"
echo ""
echo "📝 Next steps:"
echo "1. Connect your Netum thermal printer to the Raspberry Pi"
echo "2. Find your printer's USB vendor/product IDs:"
echo "   sudo lsusb"
echo "3. Update the printer configuration in app.py if needed"
echo "4. Start the application:"
echo "   python3 app.py"
echo ""
echo "Or run as a service:"
echo "   sudo systemctl start ticket-printer"
echo "   sudo systemctl enable ticket-printer"
echo ""
echo "Then access the web interface at:"
echo "   http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "⚠️  You may need to log out and log back in for group permissions to take effect."
echo ""
