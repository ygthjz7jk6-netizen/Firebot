# 🔥 Firebot - Autonomní Systém

Firebot je multi-agentní AI systém s nativní macOS aplikací a webovým rozhraním. Původně běžel čistě v terminálu, nyní funguje jako aplikace s vlastním oknem, notifikacemi pro objednávky a propracovaným chatovým UI.

## Struktura projektu
```
agent/
├── Firebot.app/             ← Nativní macOS aplikace (PyInstaller launcher)
├── orchestrator.py          ← Hlavní mozek a LangGraph workflow
├── ui.py                    ← FastAPI backend, servírující UI a web sockety
├── app_window.py            ← Spouštěč okna (webview) a backendu
├── firebot_launcher.py      ← Zdrojový kód pro Firebot.app bundle
├── static/                  ← Front-end soubory (HTML, CSS, ikony)
├── specialists/             ← Agenti s vlastními LLM (router.py)
├── memory/                  ← Dlouhodobá ChromaDB paměť
├── tools/                   ← Nástroje (WooCommerce, Order Watcher, Image Processor)
├── .env                     ← Nastavení, API klíče a brand info
└── requirements.txt         ← Závislosti Pythonu
```

## Rychlý start

### 1. Spuštění aplikace
Prostě dvakrát klikněte na **`Firebot.app`** ve složce `agent`. 
Aplikace automaticky nastartuje lokální backend, načte modely z Ollamy a otevře okno chatu. Pokud zavřete hlavní okno, aplikace se plně ukončí.

### 2. Spuštění pro vývojáře (z terminálu)
```bash
cd agent
source venv/bin/activate
python3 app_window.py
```

### 3. Konfigurace (`.env`)
Ujistěte se, že máte v `.env` vyplněno:
- `BRAND_NAME`
- `WC_URL`, `WC_KEY`, `WC_SECRET` (pro spojení s WooCommerce)
- `N8N_WEBHOOK_WP` (pro odesílání článků)

---

## Architektura a Možnosti

Firebot používá architekturu **LangGraph**. Místo jednoho velkého LLM modelu je práce rozdělena mezi úzce specializované agenty ("Specialisté").

### 🔹 Specialisté a Modely
| Specialista | Výchozí Model | Kdy se použije |
|-------------|---------------|----------------|
| **Orchestrátor** | `qwen3.5:cloud` | Hlavní rozcestník, detekce záměru a generální chat. |
| **WooCommerce** | `llama3.1:8b` | Vytváření produktů, kontrola skladu, objednávky. |
| **WordPress** | `gemma2:9b` | Psaní SEO článků a textů na blog. Tvořivý Google model. |
| **Marketing** | `gemma2:9b` | Reklamní texty a kampaně. |
| **Research**   | `qwen2.5:7b`| Rešerše a logická analytika informací. |
| **Coding** | `devstral-small-2`| Automatizace, skripty, úpravy pythonu. |
| **Fast** | `llama3.1:8b` | Běžný stručný chat a jednoduché dotazy. |

### 🔹 Paměť (ChromaDB)
Firebot si pamatuje:
- Osobní preference (barvy, styly, velikosti).
- Historii konverzací a vytvořené úkoly.
- Předchozí úpravy produktů a obsah webu.

### 🔹 Automatická kontrola objednávek
V pozadí běží `tools/order_watcher.py`, který se každých 60 vteřin dotazuje WooCommerce API. Pokud detekuje novou objednávku (status `processing`), pošle notifikaci přímo do chatu (přes WebSockets) do pravého panelu widgetu.

---

## Časté Dotazy a Problémy

**1. Ollama nereaguje (modely nefungují)**
- Otevřete terminál a napište `ollama serve`. Pokud vám chybí nějaký model, stáhněte ho pomocí `ollama pull jméno_modelu`.

**2. Aplikace se nespustí nebo se po spuštění ihned zavře**
- Firebot potřebuje funkční lokální Python venv a proměnné v `.env`. Zkuste aplikaci spustit z terminálu (`python3 app_window.py`), abyste viděli logy s chybovým hlášením.

**3. Jak aplikaci vymazat paměť?**
- Napište do chatu: *"zapomeň téma X"* nebo absolutní formát *"smaž paměť"*.
