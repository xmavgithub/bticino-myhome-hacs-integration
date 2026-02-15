#!/bin/bash

# Script to view test environment logs

echo "📊 Log Home Assistant - MyHOME Integration"
echo "=========================================="
echo ""

if docker ps --format '{{.Names}}' | grep -q '^homeassistant-dev$'; then
    echo "Press Ctrl+C to exit"
    echo ""
    docker-compose logs -f homeassistant
else
    echo "❌ Container is not running!"
    echo ""
    echo "Start the test environment first:"
    echo "   ./start_test.sh"
    exit 1
fi
