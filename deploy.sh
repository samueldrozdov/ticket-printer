#!/bin/bash

echo "🚀 Ticket Printer Application - Deployment Script"
echo "=================================================="
echo ""

# Detect platform
if [[ "$OSTYPE" == "linux-gnu"* ]] && grep -q "Raspberry" /proc/cpuinfo 2>/dev/null; then
    PLATFORM="raspberry-pi"
    echo "✅ Detected: Raspberry Pi"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="macos"
    echo "✅ Detected: macOS (Local Development)"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    PLATFORM="linux"
    echo "✅ Detected: Linux"
else
    PLATFORM="unknown"
    echo "⚠️  Unknown platform"
fi

echo ""
read -p "Do you want to deploy to Raspberry Pi? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "📤 Preparing deployment to Raspberry Pi..."
    echo ""
    
    # Check if files exist
    if [ ! -f "app.py" ]; then
        echo "❌ Error: app.py not found. Make sure you're in the right directory."
        exit 1
    fi
    
    # Create deployment package
    echo "📦 Creating deployment package..."
    tar -czf ticket-printer-app.tar.gz \
        app.py \
        config.py \
        requirements.txt \
        setup.sh \
        README.md \
        DEPLOYMENT.md \
        templates/
    
    echo "✅ Created: ticket-printer-app.tar.gz"
    echo ""
    echo "📝 Next steps:"
    echo "1. Copy ticket-printer-app.tar.gz to your Raspberry Pi (via USB, SCP, etc.)"
    echo "2. SSH into your Raspberry Pi"
    echo "3. Extract: tar -xzf ticket-printer-app.tar.gz"
    echo "4. Run: cd ticket-printer-app && chmod +x setup.sh && ./setup.sh"
    echo ""
    echo "Or transfer directly via SCP:"
    read -p "Enter Raspberry Pi IP or hostname (e.g., pi@192.168.1.100): " PI_ADDRESS
    if [ ! -z "$PI_ADDRESS" ]; then
        echo "📤 Transferring files to $PI_ADDRESS..."
        scp ticket-printer-app.tar.gz $PI_ADDRESS:/home/pi/
        echo ""
        echo "✅ Files transferred!"
        echo ""
        echo "📝 To complete setup on Raspberry Pi:"
        echo "  ssh $PI_ADDRESS"
        echo "  tar -xzf ticket-printer-app.tar.gz"
        echo "  cd ticket-printer-app"
        echo "  ./setup.sh"
    fi
    
else
    echo "🧪 Setting up for local development/testing..."
    echo ""
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        echo "❌ Python 3 is not installed. Please install it first."
        exit 1
    fi
    
    echo "✅ Python 3 found: $(python3 --version)"
    
    # Create virtual environment
    if [ ! -d "venv" ]; then
        echo "📦 Creating virtual environment..."
        python3 -m venv venv
    fi
    
    echo "🔄 Activating virtual environment..."
    source venv/bin/activate
    
    echo "📚 Installing dependencies..."
    pip install -r requirements.txt
    
    echo ""
    echo "✅ Setup complete!"
    echo ""
    echo "To run the application:"
    echo "  source venv/bin/activate"
    echo "  python3 app.py"
    echo ""
    echo "Or simply:"
    echo "  ./run.sh"
    echo ""
    
    # Create a simple run script
    cat > run.sh << 'EOF'
#!/bin/bash
if [ -d "venv" ]; then
    source venv/bin/activate
fi
python3 app.py
EOF
    chmod +x run.sh
    echo "✅ Created run.sh for easy startup"
fi

echo ""
echo "🎉 Deployment preparation complete!"
echo ""


