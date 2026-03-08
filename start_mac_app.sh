# start_mac_app.sh
# Spouštěč pro macOS .app bundle
# Používá Chrome App Mode pro nativní okno

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
DIR="/Users/theo/Desktop/Brand New Brand/agent"
cd "$DIR"

# Pokud už port 8899 běží, ukončíme ho
if lsof -Pi :8899 -sTCP:LISTEN -t >/dev/null ; then
    PID=$(lsof -Pi :8899 -sTCP:LISTEN -t | head -n 1)
    kill -9 $PID
fi

# Zkontroluj Ollama
if ! curl -s http://localhost:11434 > /dev/null; then
    open -a "Ollama"
    sleep 3
fi

source "$DIR/venv/bin/activate"

# Spusť backend na pozadí
python3 "$DIR/ui.py" &
SERVER_PID=$!

# Zajisti, aby se po ukončeni skriptu (např. zavření aplikace) ukončil i backend
trap "kill -9 $SERVER_PID || true" EXIT SIGINT SIGTERM

# Počkej chvíli, než UI nastartuje
sleep 2

# Pokus se otevřít okno přes Chrome Native App Mode (bez address barů)
if [ -d "/Applications/Google Chrome.app" ]; then
    open -W -na "Google Chrome" --args --app="http://localhost:8899"
else
    # Fallback na defaultní prohlížeč
    open -W "http://localhost:8899"
fi

# Aplikace bude držet otevřená do zavření backendu
wait $SERVER_PID
