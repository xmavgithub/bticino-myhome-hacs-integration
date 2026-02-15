#!/bin/bash

# Script to start the MyHOME test environment

set -e

echo "🏠 MyHOME Integration - Test Environment"
echo "========================================"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running!"
    echo "   Start Docker Desktop and try again."
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Create directory if missing
if [ ! -d "ha_data" ]; then
    echo "📁 Creating ha_data directory..."
    mkdir -p ha_data
fi

# Check whether the container already exists
if docker ps -a --format '{{.Names}}' | grep -q '^homeassistant-dev$'; then
    echo "🔄 Existing container found"

    # Check whether it is running
    if docker ps --format '{{.Names}}' | grep -q '^homeassistant-dev$'; then
        echo "⚠️  Container already running!"
        echo ""
        echo "Options:"
        echo "  1. Open browser: http://localhost:8123"
        echo "  2. Show logs: docker-compose logs -f"
        echo "  3. Restart: docker-compose restart"
        echo "  4. Stop: docker-compose down"
        exit 0
    else
        echo "🚀 Starting existing container..."
        docker-compose up -d
    fi
else
    echo "🆕 First startup - downloading Home Assistant image..."
    echo "   (this may take a few minutes)"
    echo ""
    docker-compose up -d
fi

echo ""
echo "⏳ Waiting for Home Assistant to start..."
sleep 5

# Check whether the container is running
if docker ps --format '{{.Names}}' | grep -q '^homeassistant-dev$'; then
    echo ""
    echo "✅ Home Assistant started successfully!"
    echo ""
    echo "📋 Info:"
    echo "   URL:  http://localhost:8123"
    echo "   Logs: docker-compose logs -f homeassistant"
    echo ""
    echo "🔧 Configuration:"
    echo "   Custom Components: ./custom_components/bticino_myhome"
    echo "   Integration Config: stored in Home Assistant storage"
    echo "   HA Config:         ./config/configuration.yaml"
    echo ""
    echo "📖 Full guide: ./TEST_SETUP.md"
    echo ""
    echo "🌐 Opening browser..."

    # Open the browser (macOS)
    if command -v open &> /dev/null; then
        sleep 3
        open http://localhost:8123
    fi

    echo ""
    echo "📊 View live logs:"
    echo "   docker-compose logs -f homeassistant"
    echo ""
else
    echo ""
    echo "❌ Failed to start container!"
    echo ""
    echo "Check logs:"
    echo "   docker-compose logs homeassistant"
    exit 1
fi
