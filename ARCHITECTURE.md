# Architektura aplikace Firebot

Tento dokument je určen vývojářům a slouží jako technický přehled, jak funguje celý systém pod povrchem.

## 1. Architektura Systému

Firebot funguje jako lokální multi-agentní AI asistent, který spojuje různé velké jazykové modely (LLM) běžící pomocí Ollama, paměťový vektorový mechanismus (ChromaDB) a sadu externích webhooků/API volání.

*   **Přední vrstva (UI)**: Zabezpečena knihovnou `pywebview` přes skript `app_window.py`. Spouští lehké prohlížečové okno bez ovládacích prvků nad FastAPI backendem běžícím na portu 8899.
*   **Aplikace macOS**: Kód `firebot_launcher.py` dynamicky volá stávající Python moduly z `venv` a vytváří izolovaný spouštěcí proces pomocí PyInstalleru (ve слоžce `Firebot.app`).
*   **Orchestrace (LangGraph)**: Backend nepoužívá jediný LLM model k řešení všech úkolů. Místo toho využívá `langgraph`, kde `orchestrator.py` analyzuje dotaz uživatele a směřuje ho na příslušného "Specialistu" (WordPress agent, WooCommerce agent, atd.).

## 2. Jádrové Součásti

### 2.1 Backend / API (`ui.py`)
Systém využívá **FastAPI**. Jsou zde tři důležité routy:
- `/` a `/menubar`: Zobrazují statické HTML pro chat a boční panel (widget).
- `/chat`: Cílový bod (POST) pro uživatelská zadání chatu. Požadavky jsou zde zpracovávány orchestátory.
- `/ws/orders`: WebSocket spojení určené na reálnou aktualizaci objednávek. Objednávky se kontrolují ve smyčce co minutu (`tools/order_watcher.py`).

### 2.2 LangGraph Orchestrátor (`orchestrator.py`)
Toto je hlavní stavový graf agenta:
1.  **Orchestrator Node**: Rozhoduje, koho pro daný dotaz povolat. Detekuje systémové příkazy (např. *smaž paměť*) a ihned je provádí, aby ušetřil využití modelu. Pokud je požadavek složitější ("rozloženo na kroky"), zavolá model, který úkol rozdělí do `pending_steps`.
2.  **Specialist Node**: Zavolaný pouze, pokud potřebujeme specializovanou odpověď (např. API volání na WooCommerce nebo generování SEO struktury).
3.  **End**: Výsledek se odesílá zpět uživateli, a nová konverzace a nastavení uloží do paměti.

### 2.3 Paměť (ChromaDB)
Každý nový dotaz a vygenerovaná konverzace se posílá do ChromaDB v `memory/chroma_memory.py`. Důležitá zjištění (jako barvy nebo osobní preference uživatele) se označují specifickou kategorií `user_preference` pro lepší budoucí dotazy modely.

### 2.4 WooCommerce Nástroje (`tools/woocommerce.py`)
Firebot komunikuje s e-shopem napřímo přes REST API – mění stavy skladů, edituje ceny, vypisuje objednávky. JSON výstupy ze Specialisty (`route_to_specialist`) jsou automaticky zparsovány a aplikovány.

## 3. Vývoj a Kompilace Appky (PyInstaller)
Protože macOS (Gatekeeper) neumožňuje snadno spouštět holé bash scripty reprezentující aplikace, obalili jsme běhové skripty pomocí Python modulu (`firebot_launcher.py`) a kompilujeme je. 

**Pro znovusestavení `Firebot.app`:**
Pokud změníte cesty ikony, nebo název skriptu, musíte spustit tento příkaz uvnitř složky `agent`:

```bash
# Vymaže minulý build
rm -rf build dist Firebot.app

# Vytvoření aplikace pomocí PyInstalleru
./venv/bin/pyinstaller \
  --name "Firebot" \
  --onedir \
  --windowed \
  --icon firebot_icon.icns \
  --noconfirm \
  --clean \
  firebot_launcher.py

# Přesunutí appky a schválení pro lokální běh (odstranění karantény)
cp -R dist/Firebot.app ./Firebot.app
xattr -dr com.apple.quarantine Firebot.app
codesign --force --deep --sign - Firebot.app
```

Tím zajistíte, že macOS povolí okno s Firebotem ihned po kliknutí v Docku.
