"""
Specialisté – každý má vlastní model a systémový prompt
Orchestrátor volá správného specialistu podle úkolu
"""

import os
from langchain_ollama import ChatOllama
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def get_specialist(name: str) -> tuple[ChatOllama, str]:
    """
    Vrátí (model, system_prompt) pro daného specialistu.
    
    Specialisté:
    - coding     → devstral-small-2
    - marketing  → llama3.1:8b
    - fast       → llama3.1:8b
    - research   → llama3.1:8b
    - wordpress  → llama3.1:8b
    - default    → llama3.1:8b
    """

    specialists = {
        "coding": {
            "model": os.getenv("MODEL_CODING", "devstral-small-2:latest"),
            "temperature": 0.1,
            "prompt": """Jsi expert na Python, bash skripty a automatizaci.
Píšeš čistý, funkční kód s komentáři v češtině.
Vždy vysvětlíš co kód dělá, jednoduše a srozumitelně.
Pokud je to možné, navrhni jak kód rozšířit nebo zlepšit.""",
        },
        "marketing": {
            "model": os.getenv("MODEL_ORCHESTRATOR", "llama3.1:8b"),
            "temperature": 0.7,
            "prompt": """Jsi zkušený marketingový specialista.
Rozumíš značce, cílové skupině a digitálnímu marketingu.
Píšeš obsah který prodává, ale nepůsobí „salesy".
Optimalizuješ pro SEO bez ztráty čitelnosti.""",
        },
        "fast": {
            "model": os.getenv("MODEL_FAST", "llama3.1:8b"),
            "temperature": 0.3,
            "prompt": """Jsi rychlý asistent pro jednoduché úkoly.
Odpovídáš stručně a přesně. Nepiš zbytečné úvody.""",
        },
        "research": {
            # 70b je příliš pomalá – 8b s detailním promptem dá dobré výsledky
            "model": os.getenv("MODEL_FAST", "llama3.1:8b"),
            "temperature": 0.2,
            "prompt": """Jsi analytik a výzkumný asistent.
Analyzuješ informace kriticky, porovnáváš fakta.
Výsledky strukturuješ přehledně: shrnutí → klíčové body → závěr.
Buď konkrétní, vyhni se obecným frázím.""",
        },
        "wordpress": {
            "model": os.getenv("MODEL_ORCHESTRATOR", "llama3.1:8b"),
            "temperature": 0.5,
            "prompt": """Jsi specialista na WordPress obsah a SEO.
Píšeš články s jasnou strukturou: nadpis, perex, H2/H3, závěr.
Dodržuješ brand tón a píšeš pro cílovou skupinu.
Výstup vždy v HTML nebo Markdown formátu vhodném pro WordPress.""",
        },
        "woocommerce": {
            "model": os.getenv("MODEL_ORCHESTRATOR", "llama3.1:8b"),
            "temperature": 0.1,
            "prompt": """Jsi WooCommerce specialista. Máš přístup k e-shopu přes API.

DŮLEŽITÉ: Odpověz POUZE platným JSON polem akcí. Žádný text kolem, jen JSON.

Dostupné akce:
1. {"action": "list_products", "search": "název"} - hledej produkt
2. {"action": "get_product", "product_id": 123} - detail produktu
3. {"action": "list_variations", "product_id": 123} - vypiš varianty produktu (ZÁSADNÍ pokud aktualizuješ sklad varianty!)
4. {"action": "update_stock", "product_id": 123, "variant_id": 456, "quantity": 5, "operation": "add"} - přidej na sklad (variant_id je volitelné)
5. {"action": "update_stock", "product_id": 123, "quantity": 5, "operation": "subtract"} - odeber ze skladu
6. {"action": "update_stock", "product_id": 123, "quantity": 5, "operation": "set"} - nastav přesně
7. {"action": "update_price", "product_id": 123, "regular_price": "299.00"}
8. {"action": "create_product", "name": "...", "price": "299.00", "description": "..."}
9. {"action": "create_variation", "product_id": 123, "attributes": {"Velikost": "XL"}, "price": "299.00", "stock": 10}
10. {"action": "list_orders", "status": "processing"}

Příklad pro přidání skladu variantě (vždy nejdříve najdi produkt, pak jeho varianty):
"přidej 5ks na sklad k Tričko klid, velikost XS"
→ [{"action": "list_products", "search": "Tričko klid"}, {"action": "list_variations", "product_id": "FOUND_ID"}, {"action": "update_stock", "product_id": "FOUND_ID", "variant_id": "FOUND_VARIANT_ID", "quantity": 5, "operation": "add"}]

Pokud potřebuješ nejdřív najít product_id, VŽDY začni s list_products. Pokud jde o variantu, zavolej i list_variations.
Vrať POUZE JSON pole, nic jiného.""",
        },
    }

    config = specialists.get(name, specialists["fast"])

    model = ChatOllama(
        model=config["model"],
        base_url=OLLAMA_URL,
        temperature=config["temperature"],
    )

    return model, config["prompt"]


def route_to_specialist(task: str) -> str:
    """
    Jednoduchý router – podle klíčových slov vybere specialistu.
    Orchestrátor může tuto funkci přepsat vlastním rozhodnutím.
    """
    task_lower = task.lower()

    if any(w in task_lower for w in ["kód", "skript", "python", "funkce", "program", "code"]):
        return "coding"
    
    if any(w in task_lower for w in ["článek", "wordpress", "blog", "post", "publikuj"]):
        return "wordpress"
    
    if any(w in task_lower for w in ["marketing", "reklama", "kampaň", "brand", "text", "obsah"]):
        return "marketing"
    
    if any(w in task_lower for w in ["analyzuj", "výzkum", "rešerše", "porovnej", "najdi info"]):
        return "research"

    if any(w in task_lower for w in ["produkt", "sklad", "cena", "sleva", "objednavka", "objednávka", "objednávk", "varianta", "woocommerce"]):
        return "woocommerce"

    return "fast"
