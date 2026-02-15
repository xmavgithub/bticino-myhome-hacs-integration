#!/bin/bash

# Script per avviare l'ambiente di test MyHOME

set -e

echo "🏠 MyHOME Integration - Test Environment"
echo "========================================"
echo ""

# Controlla se Docker è in esecuzione
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker non è in esecuzione!"
    echo "   Avvia Docker Desktop e riprova."
    exit 1
fi

echo "✅ Docker è in esecuzione"
echo ""

# Crea directory se non esiste
if [ ! -d "ha_data" ]; then
    echo "📁 Creazione directory ha_data..."
    mkdir -p ha_data
fi

# Controlla se il container esiste già
if docker ps -a --format '{{.Names}}' | grep -q '^homeassistant-dev$'; then
    echo "🔄 Container esistente trovato"

    # Controlla se è in esecuzione
    if docker ps --format '{{.Names}}' | grep -q '^homeassistant-dev$'; then
        echo "⚠️  Container già in esecuzione!"
        echo ""
        echo "Opzioni:"
        echo "  1. Apri il browser: http://localhost:8123"
        echo "  2. Vedi i log: docker-compose logs -f"
        echo "  3. Riavvia: docker-compose restart"
        echo "  4. Ferma: docker-compose down"
        exit 0
    else
        echo "🚀 Avvio container esistente..."
        docker-compose up -d
    fi
else
    echo "🆕 Primo avvio - download immagine Home Assistant..."
    echo "   (potrebbe richiedere qualche minuto)"
    echo ""
    docker-compose up -d
fi

echo ""
echo "⏳ Attendo avvio Home Assistant..."
sleep 5

# Controlla se il container è in esecuzione
if docker ps --format '{{.Names}}' | grep -q '^homeassistant-dev$'; then
    echo ""
    echo "✅ Home Assistant avviato con successo!"
    echo ""
    echo "📋 Informazioni:"
    echo "   URL:  http://localhost:8123"
    echo "   Logs: docker-compose logs -f homeassistant"
    echo ""
    echo "🔧 Configurazione:"
    echo "   Custom Components: ./custom_components/myhome"
    echo "   Config File:       ./config/myhome.yaml"
    echo "   HA Config:         ./config/configuration.yaml"
    echo ""
    echo "📖 Guida completa: ./TEST_SETUP.md"
    echo ""
    echo "🌐 Apertura browser..."

    # Apri il browser (macOS)
    if command -v open &> /dev/null; then
        sleep 3
        open http://localhost:8123
    fi

    echo ""
    echo "📊 Visualizza i log in tempo reale:"
    echo "   docker-compose logs -f homeassistant"
    echo ""
else
    echo ""
    echo "❌ Errore nell'avvio del container!"
    echo ""
    echo "Controlla i log:"
    echo "   docker-compose logs homeassistant"
    exit 1
fi
