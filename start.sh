#!/bin/bash

echo "🚀 Spouštím agenta..."
echo ""

# Zkontroluj Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 nenalezen. Nainstaluj přes: brew install python"
    exit 1
fi

# Zkontroluj Ollama
if ! curl -s http://localhost:11434 > /dev/null; then
    echo "⚠️  Ollama neběží – spouštím..."
    open -a Ollama
    sleep 3
fi

# Vytvoř virtual environment pokud neexistuje
if [ ! -d "venv" ]; then
    echo "📦 Vytvářím virtuální prostředí..."
    python3 -m venv venv
fi

# Aktivuj venv a nainstaluj závislosti
source venv/bin/activate

echo "📦 Kontroluji závislosti..."
pip install -q -r requirements.txt

# Spusť n8n přes Docker
if command -v docker &> /dev/null; then
    if ! docker ps | grep -q n8n; then
        echo "🔧 Spouštím n8n..."
        docker compose up -d
        echo "✅ n8n dostupné na: http://localhost:5678"
    else
        echo "✅ n8n už běží"
    fi
fi

echo ""
echo "✅ Vše připraveno!"
echo ""

# Zvol mód: --ui = webové UI (nativní okno), jinak CLI
if [ "$1" = "--ui" ] || [ "$1" = "ui" ]; then
    echo "🖥️  Spouštím originální Nativní Mac aplikaci..."
    open Firebot.app
else
    echo "💻 Spouštím CLI mód (pro nativní UI: ./start.sh --ui)"
    python3 orchestrator.py
fi

