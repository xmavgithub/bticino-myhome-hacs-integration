#!/bin/bash

# Script to stop the MyHOME test environment

echo "🛑 Stopping Home Assistant Test Environment"
echo "=========================================="
echo ""

if docker ps --format '{{.Names}}' | grep -q '^homeassistant-dev$'; then
    echo "📦 Stopping container..."
    docker-compose down

    echo ""
    echo "✅ Container stopped!"
    echo ""
    echo "To start again:"
    echo "   ./start_test.sh"
    echo ""
    echo "To delete all data:"
    echo "   docker-compose down -v"
    echo "   rm -rf ha_data/"
else
    echo "ℹ️  Container is not running"
fi
