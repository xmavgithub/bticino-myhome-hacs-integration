#!/bin/bash

# Script per visualizzare i log del test environment

echo "📊 Log Home Assistant - MyHOME Integration"
echo "=========================================="
echo ""

if docker ps --format '{{.Names}}' | grep -q '^homeassistant-dev$'; then
    echo "Premi Ctrl+C per uscire"
    echo ""
    docker-compose logs -f homeassistant
else
    echo "❌ Container non in esecuzione!"
    echo ""
    echo "Avvia prima l'ambiente di test:"
    echo "   ./start_test.sh"
    exit 1
fi
