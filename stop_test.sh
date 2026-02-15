#!/bin/bash

# Script per fermare l'ambiente di test MyHOME

echo "🛑 Arresto Home Assistant Test Environment"
echo "=========================================="
echo ""

if docker ps --format '{{.Names}}' | grep -q '^homeassistant-dev$'; then
    echo "📦 Arresto container..."
    docker-compose down

    echo ""
    echo "✅ Container arrestato!"
    echo ""
    echo "Per riavviare:"
    echo "   ./start_test.sh"
    echo ""
    echo "Per eliminare tutti i dati:"
    echo "   docker-compose down -v"
    echo "   rm -rf ha_data/"
else
    echo "ℹ️  Container non in esecuzione"
fi
