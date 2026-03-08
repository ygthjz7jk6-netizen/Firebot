"""
Hlavní orchestrátor – LangGraph multi-agent systém
Spuštění: python orchestrator.py
"""

import os
import sys
import httpx
import json
from typing import TypedDict, Annotated
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Lokální moduly
sys.path.insert(0, os.path.dirname(__file__))
from memory.chroma_memory import (save_memory, search_memory, get_brand_context, get_memory_stats,
                                  save_task, list_tasks, complete_task, forget_about, cleanup_old_memories)
from specialists.router import get_specialist, route_to_specialist
from specialists.model_switcher import get_best_model, get_model_status
from tools.woocommerce import create_product, update_stock, update_price, list_orders, list_products, get_product
from tools.image_processor import process_product_image, process_folder
from tools.order_watcher import check_new_orders, format_orders_summary, check_orders_on_demand, start_order_scheduler
from tools.web_search import tavily_search, ddg_search
from tools.social_trends import get_tiktok_trends, get_ig_trends
from tools.science_api import search_pubmed

base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, '.env'))

console = Console()
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")



# === WORDPRESS TOOL ===
def wp_create_post(title: str, content: str, status: str = "draft") -> dict:
    """
    Pošle článek do WordPressu přes n8n webhook.
    Vrátí dict s výsledkem: {"ok": True, "url": "...", "id": 123} nebo {"ok": False, "error": "..."}
    """
    n8n_url = os.getenv("N8N_WEBHOOK_WP", "http://localhost:5678/webhook/wordpress")
    
    try:
        response = httpx.post(
            n8n_url,
            json={"title": title, "content": content, "status": status},
            timeout=30,
        )
        if response.status_code == 200:
            data = response.json()
            post_url = data.get("link", "")
            post_id = data.get("id", "")
            console.print(f"  [green]✅ WordPress draft vytvořen: {post_url}[/green]")
            return {"ok": True, "url": post_url, "id": post_id}
        else:
            console.print(f"  [red]❌ WordPress chyba: {response.status_code}[/red]")
            return {"ok": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        console.print(f"  [red]❌ n8n nedostupné: {e}[/red]")
        return {"ok": False, "error": str(e)}


def process_images_tool(path: str, webp_only: bool = False) -> dict:
    """
    Zpracuje fotky: pokud složka, vytvoří produkt a varianty automaticky.
    Pokud soubor, zpracuje jednu fotku.
    webp_only=True → zpracuj pouze .webp soubory (přeskoč JPG/PNG originály)
    """
    from pathlib import Path
    path_obj = Path(path)
    
    try:
        if path_obj.is_dir():
            results = process_folder(path, auto_create=True, webp_only=webp_only)
            ok_count = sum(1 for r in results if r.get("ok"))
            console.print(f"  [green]✅ Zpracováno {ok_count}/{len(results)} fotek[/green]")
            return {"ok": True, "results": results}
        else:
            result = process_product_image(path)
            if result.get("ok"):
                console.print(f"  [green]✅ Obrázek zpracován: {result.get('assigned_to', 'galerie')}[/green]")
            else:
                console.print(f"  [red]❌ Chyba: {result.get('error', 'neznámá')}[/red]")
            return result
    except Exception as e:
        console.print(f"  [red]❌ Chyba: {e}[/red]")
        return {"ok": False, "error": str(e)}


def wc_create_product(name: str, price: str, description: str = "", status: str = "draft") -> dict:
    """
    Vytvori produkt primo pres WooCommerce REST API (bez n8n).
    Vraci dict s id a url produktu.
    """
    import base64
    wc_url = os.getenv("WC_URL", "").rstrip("/")
    wc_key = os.getenv("WC_KEY", "")
    wc_secret = os.getenv("WC_SECRET", "")
    try:
        response = httpx.post(
            f"{wc_url}/wp-json/wc/v3/products",
            auth=(wc_key, wc_secret),
            json={"name": name, "regular_price": str(price), "description": description, "status": status},
            timeout=30,
        )
        if response.status_code == 201:
            data = response.json()
            product_id = data.get("id", "")
            product_url = data.get("permalink", "")
            console.print(f"  [green]Produkt vytvoren: {name} (ID: {product_id})[/green]")
            return {"ok": True, "id": product_id, "url": product_url}
        else:
            return {"ok": False, "error": f"HTTP {response.status_code}: {response.text[:100]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def wc_query(query: str) -> str:
    """
    Zpracuje dotaz na e-shop přímo přes WooCommerce API.
    Vrátí textovou odpověď s reálnými daty.
    """
    import re
    from tools.woocommerce import list_products, list_orders, update_stock, update_price

    query_lower = query.lower()

    try:
        # Počet / seznam produktů
        if any(w in query_lower for w in ["kolik", "seznam", "produktů", "produkt"]):
            products = list_products(per_page=100)
            count = len(products)
            names = [f"- {p['name']} (ID: {p['id']}, cena: {p.get('price','?')} Kč, sklad: {p.get('stock_quantity','neomezeno')})" for p in products[:10]]
            result = "Mas " + str(count) + " produktu v e-shopu:\n" + "\n".join(names)
            if count > 10:
                result += "\n... a dalsich " + str(count - 10) + " produktu."
            return result

        # Objednávky
        if any(w in query_lower for w in ["objednávk", "objednavk"]):
            status = "processing" if "nevyřízené" in query_lower or "cekajici" in query_lower else "any"
            orders = list_orders(status=status, per_page=10)
            if not orders:
                return "Žádné objednávky nenalezeny."
            lines = [f"- Obj. #{o['id']} | {o['billing']['first_name']} {o['billing']['last_name']} | {o['total']} Kč | stav: {o['status']}" for o in orders]
            return "Nalezeno " + str(len(orders)) + " objednavek:\n" + "\n".join(lines)

        # Vytvoreni produktu
        if any(w in query_lower for w in ["pridej", "vytvor", "novy produkt", "vloz produkt"]):
            return "VYTVOR_PRODUKT"

        return None  # Nerozpoznany dotaz - nech specialistu

    except Exception as e:
        return f"Chyba při komunikaci s e-shopem: {e}"


def extract_title(text: str) -> str:
    """Extrahuje titulek z vygenerovaného textu (první nadpis nebo první řádek)."""
    import re
    # Hledej markdown nadpis ## nebo **
    match = re.search(r'^#{1,3}\s*(.+)$', text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    match = re.search(r'^\*\*(.+)\*\*', text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    # Fallback: první neprázdný řádek
    for line in text.split('\n'):
        line = line.strip()
        if len(line) > 5:
            return line[:80]
    return "Článek od agenta"

# === STAV AGENTA ===
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    current_specialist: str
    task_summary: str
    use_memory: bool
    publish_to_wp: bool
    pending_steps: list       # Zbývající kroky plánu
    current_plan: str         # Popis celého plánu
    step_results: list        # Výsledky hotových kroků


# === SYSTÉMOVÝ PROMPT ORCHESTRÁTORU ===
def build_orchestrator_prompt(query: str) -> str:
    brand = get_brand_context()
    memories = search_memory(query, n_results=3)

    memory_text = ""
    if memories:
        memory_text = "\nHISTORICKÉ POZNATKY (pro kontext, NE aktuální úkoly):\n"
        for m in memories:
            memory_text += f"- [{m['category']}] {m['content']}\n"

    brand_section = f"\n{brand}\n" if brand else ""

    return f"""Jsi orchestrátor multi-agentního systému. Rozhoduj a deleguj — nepíšeš obsah sám.
{brand_section}{memory_text}
DŮLEŽITÁ PRAVIDLA:
1. REŠ JEN TO CO UŽIVATEL PRÁVĚ ŘEKL. Nevymýšlej úkoly, neseznamuj co "je potřeba udělat".
2. Vzpomínky výše jsou HISTORIE — NE tvé aktuální úkoly. Neprezentuj je jako úkoly.
3. Pokud uživatel řekne něco co nechápeš, zeptej se. Nehádej.
4. Odpovídej stručně a k věci.

PRAVIDLA DELEGOVÁNÍ:
- článek/blog/text/SEO → DELEGUJ→wordpress
- kód/skript/python → DELEGUJ→coding
- marketing/reklama → DELEGUJ→marketing
- sociální sítě/tiktok/instagram/trendy → DELEGUJ→social_media
- věda/výzkum materiálů/biologie/pubmed → DELEGUJ→science
- analýza/obecný výzkum → DELEGUJ→research
- produkt/sklad/e-shop → DELEGUJ→woocommerce
- hledání na internetu/nejnovější info → DELEGUJ→web
- otázka na systém → odpověz sám
- ostatní → DELEGUJ→fast

Formát: DELEGUJ→[specialist]: [přesný úkol]
Pokud chce publikovat na web, přidej: PUBLIKUJ_NA_WP
"""



# === DECOMPOSE COMPLEX TASKS ===
def decompose_task(request: str) -> list:
    """Rozloží složitý požadavek na kroky. Vrátí seznam dict s kroky."""
    model = get_best_model(prefer_cloud=True)
    response = model.invoke([
        SystemMessage(content="""Rozlož požadavek na jednoduché kroky. Každý krok musí být nezávislý a realizovatelný.
Formát: vrať POUZE JSON pole, nic jiného. Každý prvek má "step" (popis) a "specialist" (kdo to udělá).

Dostupní specialisté:
- image_processor: zpracování fotek (optimalizace, resize, přiřazení)
- wordpress: psaní textů, článků, popisků
- woocommerce: vytváření produktů, nastavení cen, sklad
- marketing: slogany, reklama
- social_media: trendy na sítích (TikTok, Instagram)
- science: odborný vědecký výzkum (PubMed, biomateriály, studie)
- research: analýza, obecný výzkum
- coding: programování, skripty
- web: hledání informací na internetu

Příklad odpovědi:
[{"step": "Zpracovat a optimalizovat fotky ze složky", "specialist": "image_processor"}, {"step": "Napsat popis produktu", "specialist": "wordpress"}]

Maximálně 6 kroků. Vrať POUZE JSON, žádný text kolem."""),
        HumanMessage(content=request),
    ])

    import json as _json
    try:
        # Zkus parsovat JSON z odpovědi
        content = response.content.strip()
        # Odstraň markdown bloky pokud LLM obalí do ```json...```
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        steps = _json.loads(content)
        if isinstance(steps, list) and len(steps) > 0:
            return steps[:8]  # Max 8 kroků
    except Exception:
        pass
    return []  # Fallback — nelze rozložit


# === UZLY GRAFU ===

def orchestrator_node(state: AgentState) -> AgentState:
    """Hlavní mozek – rozhoduje co dál."""

    # === AUTO-PLAN: Pokud máme pending_steps, zpracuj další ===
    pending = state.get("pending_steps", [])
    step_results = state.get("step_results", [])

    if pending:
        next_step = pending[0]
        remaining = pending[1:]
        total = len(step_results) + len(pending)
        current_num = len(step_results) + 1

        step_text = next_step.get("step", "")
        specialist = next_step.get("specialist", "fast")

        # image_processor se řeší přímo, ne přes specialistu
        if specialist == "image_processor":
            # Extrahuj cestu z original plánu
            import re
            path_match = re.search(r'/[^\s,)]+', state.get("current_plan", ""))
            if path_match:
                path = path_match.group(0).rstrip('.,;:)]}')
                console.print(f"  [cyan]▶ Krok {current_num}/{total}: {step_text}[/cyan]")
                result = process_images_tool(path, webp_only=True)
                step_results.append({"step": step_text, "result": "Fotky zpracovány"})
                console.print(f"  [green]✅ Krok {current_num}/{total} hotov[/green]")
                return {
                    **state,
                    "pending_steps": remaining,
                    "step_results": step_results,
                    "current_specialist": "done" if not remaining else "next_step",
                    "messages": state["messages"] + [AIMessage(content=f"✅ Krok {current_num}/{total}: {step_text} — hotovo")],
                }

        console.print(f"  [cyan]▶ Krok {current_num}/{total}: {step_text}[/cyan]")
        return {
            **state,
            "pending_steps": remaining,
            "step_results": step_results,
            "current_specialist": specialist,
            "task_summary": step_text,
            "messages": state["messages"] + [AIMessage(content=f"▶ Krok {current_num}/{total}: {step_text}")],
        }

    # Pokud jsme právě dokončili plán (step_results neprázdné, pending prázdné)
    if step_results and not pending:
        summary = "\n".join(f"  ✅ {r['step']}" for r in step_results)
        plan_name = state.get("current_plan", "Plán")
        save_memory(f"Dokončený plán: {plan_name}", category="plan")
        return {
            **state,
            "current_specialist": "done",
            "step_results": [],
            "current_plan": "",
            "messages": state["messages"] + [AIMessage(content=f"🎉 Plán dokončen!\n{summary}")],
        }

    last_message = state["messages"][-1].content
    
    import re
    query_lower = last_message.lower()

    # === PRIMY ROUTING BEZ MODELU - rychly a levny ===

    # -1. PRIORITA: Explicitní 'zapamatuj' = ulož do paměti
    if query_lower.startswith("zapamatuj"):
        content = last_message.split(" ", 1)[-1] if " " in last_message else last_message
        if content.lower().startswith("si "):
            content = content[3:]
        doc_id = save_memory(content, category="user_preference")
        if doc_id:
            console.print(f"  [green]🧠 Zapamatováno![/green]")
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content=f"🧠 Zapamatováno: {content}")],
            }
        else:
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content="🧠 Toto už mám v paměti.")],
            }

    # -0.9 PRIORITA: Úkoly
    if query_lower.startswith("úkol:") or query_lower.startswith("ukol:"):
        task_text = last_message.split(":", 1)[-1].strip()
        if task_text:
            save_task(task_text)
            console.print(f"  [green]✅ Úkol uložen[/green]")
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content=f"✅ Úkol uložen: {task_text}")],
            }

    if query_lower in ["úkoly", "ukoly", "tasks", "seznam úkolů"]:
        tasks = list_tasks("open")
        if tasks:
            task_list = "\n".join(f"  {i+1}. {t['text']}" for i, t in enumerate(tasks))
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content=f"📋 Otevřené úkoly ({len(tasks)}):\n{task_list}")],
            }
        else:
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content="📋 Žádné otevřené úkoly.")],
            }

    if query_lower.startswith("hotovo:") or query_lower.startswith("done:"):
        task_query = last_message.split(":", 1)[-1].strip()
        completed = complete_task(task_query)
        if completed:
            console.print(f"  [green]✅ Úkol dokončen[/green]")
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content=f"✅ Hotovo: {completed}")],
            }
        else:
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content="❌ Nenalezen žádný odpovídající otevřený úkol.")],
            }

    # -0.8 PRIORITA: 'zapomeň [téma]' = selektivní mazání
    if query_lower.startswith("zapomeň") or query_lower.startswith("zapomen"):
        topic = last_message.split(" ", 1)[-1].strip() if " " in last_message else ""
        if topic:
            deleted = forget_about(topic)
            if deleted > 0:
                console.print(f"  [yellow]🗑️  Smazáno {deleted} vzpomínek o '{topic}'[/yellow]")
                return {
                    **state,
                    "current_specialist": "done",
                    "messages": state["messages"] + [AIMessage(content=f"🗑️ Zapomenuto — smazáno {deleted} vzpomínek o '{topic}'.")],
                }
            else:
                return {
                    **state,
                    "current_specialist": "done",
                    "messages": state["messages"] + [AIMessage(content=f"🧠 Nic o '{topic}' jsem nenašel.")],
                }
        else:
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content="Použití: `zapomeň [téma]` — např. `zapomeň tričko`")],
            }

    # -0.7 PRIORITA: 'smaž paměť' = nuclear wipe
    if any(w in query_lower for w in ["smaž paměť", "smaz pamet", "vymaž paměť", "vymaz pamet", "reset paměť", "reset pamet"]):
        try:
            from memory.chroma_memory import collection
            all_ids = collection.get()["ids"]
            if all_ids:
                collection.delete(ids=all_ids)
                console.print(f"  [yellow]🗑️  Smazáno {len(all_ids)} vzpomínek[/yellow]")
                return {
                    **state,
                    "current_specialist": "done",
                    "messages": state["messages"] + [AIMessage(content=f"🗑️ Paměť vyčištěna — smazáno {len(all_ids)} vzpomínek.")],
                }
            else:
                return {
                    **state,
                    "current_specialist": "done",
                    "messages": state["messages"] + [AIMessage(content="🧠 Paměť je už prázdná.")],
                }
        except Exception as e:
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content=f"❌ Chyba: {e}")],
            }

    # -0.5 Auto-detekce uživatelských preferencí (barva, rozměr, materiál...)
    pref_keywords = ["chci", "potřebuju", "potřebuji", "preferuju", "preferuji",
                     "barva", "rozměr", "materiál", "styl", "velikost",
                     "mám rád", "líbí se mi", "nechci", "neříkej", "pamatuj"]
    if any(w in query_lower for w in pref_keywords) and len(last_message) > 20:
        save_memory(last_message, category="user_preference")

    # 0. PRIORITA: Zpracovani obrazku - musí být PRVNÍ!
    if any(w in query_lower for w in ["zpracuj", "zpracovat", "fotku", "obrazek", "fotka", "fotky", "obrazky", "složku", "slozku"]):
        # Extrahuj cestu - hledej cokoliv co vypadá jako cesta (obsahuje /)
        import re
        from pathlib import Path
        
        path_matches = re.findall(r"/[^\s]+", query_lower)
        path = None
        
        # Vezmi první cestu, která existuje
        for potential_path in path_matches:
            clean_path = potential_path.rstrip('.,;:)]}')
            if Path(clean_path).exists():
                path = clean_path
                break
        
        # Pokud žádná cesta neexistuje, vezmi první hledanou
        if not path and path_matches:
            path = path_matches[0].rstrip('.,;:)]}')
        
        if path:
            # Detekce WebP-only módu
            use_webp_only = "webp" in query_lower
            mode_label = " (pouze WebP)" if use_webp_only else ""
            console.print(f"  [yellow]🔄 Zpracovávám fotky ze složky: {path}{mode_label}[/yellow]")
            result = process_images_tool(path, webp_only=use_webp_only)
            save_memory(f"Zpracovány obrázky z {path}", category="woocommerce")
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content=f"✅ Zpracováno:\n{json.dumps(result, ensure_ascii=False, indent=2)}")],
            }

    # 1. Vytvoreni produktu - pouze pokud se NEMNOŽ o zpracování fotek
    if any(w in query_lower for w in ["přidej", "pridej", "vloz", "vlož", "nový", "novy"]) and any(w in query_lower for w in ["produkt", "položku", "item"]) and "/" not in query_lower:
        return {
            **state,
            "current_specialist": "woocommerce",
            "task_summary": last_message,
            "publish_to_wp": False,
            "messages": state["messages"] + [AIMessage(content="Vytvarim produkt...")],
        }

    # 2. On-demand kontrola objednávek — vždy ukáže posledních 10 + označí nové
    new_order_keywords = ["nové objednávky", "nove objednavky", "nová objednávka", "nova objednavka",
                          "přišly objednávky", "prisly objednavky", "zkontroluj objednávky", "zkontroluj objednavky",
                          "objednávky", "objednavky", "ukáž objednávky", "ukaz objednavky"]
    if any(w in query_lower for w in new_order_keywords):
        answer = check_orders_on_demand(per_page=10)
        return {
            **state,
            "current_specialist": "done",
            "messages": state["messages"] + [AIMessage(content=answer)],
        }

    wc_read_keywords = ["kolik", "seznam produkt", "objednavk", "objednavek", "objednávk", "objednávek"]
    if any(w in query_lower for w in wc_read_keywords):
        wc_answer = wc_query(last_message)
        if wc_answer:
            save_memory(wc_answer[:300], category="woocommerce")
            return {
                **state,
                "current_specialist": "done",
                "messages": state["messages"] + [AIMessage(content=wc_answer)],
            }

    # === KEYWORD ROUTING — přeskočí LLM pokud je jasné kam delegovat ===
    keyword_routes = {
        "wordpress": ["článek", "clanek", "blog", "post", "publikuj", "napiš článek", "napis clanek", "úvod", "text na web", "seo text"],
        "coding": ["kód", "kod", "skript", "python", "funkce", "program", "code", "bash", "automatizace", "naprogramuj"],
        "marketing": ["marketing", "reklama", "kampaň", "kampan", "slogan", "brand", "newsletter"],
        "social_media": ["tiktok", "instagram", "ig", "virál", "trendy", "sociální sítě"],
        "science": ["věda", "vědeck", "biomateriál", "pubmed", "studie", "odborný", "materiál"],
        "research": ["analyzuj", "výzkum", "vyzkum", "rešerše", "reserse", "porovnej"],
        "web": ["hledej", "vyhledej", "internet", "zjisti na webu", "najdi info", "najdi na internetu", "nejnovější", "kdo vyhrál", "počasí", "hledat", "vyhledat"],
        "woocommerce": ["produkt", "sklad", "cena", "sleva", "objednávka", "objednávky", "objednavka", "objednavky", "objednávk", "varianta", "e-shop", "eshop", "woocommerce"],
    }
    
    matched_specialist = None
    for spec, keywords in keyword_routes.items():
        if any(w in query_lower for w in keywords):
            matched_specialist = spec
            break
    
    if matched_specialist:
        publish = any(w in query_lower for w in ["publikuj", "zveřejni", "na web"])
        console.print(f"  [dim]⚡ Keyword routing → {matched_specialist}[/dim]")
        return {
            **state,
            "current_specialist": matched_specialist,
            "task_summary": last_message,
            "publish_to_wp": publish,
            "messages": state["messages"] + [AIMessage(content=f"🔀 Předávám specialistovi: **{matched_specialist}**")],
        }

    # === VOLANI MODELU — jen pro nejednoznačné dotazy ===
    system_prompt = build_orchestrator_prompt(last_message)
    model = get_best_model(prefer_cloud=True)
    response = model.invoke([
        SystemMessage(content=system_prompt),
        *state["messages"][-6:],
    ])

    # Detekuj delegování
    content = response.content
    deleguj_match = re.search(r"DELEGUJ[\u2192>]([a-zA-Z]+):\s*(.+)", content)
    if deleguj_match:
        specialist_name = deleguj_match.group(1).strip()
        task = deleguj_match.group(2).strip() or last_message
        publish = "PUBLIKUJ_NA_WP" in content
        
        return {
            **state,
            "current_specialist": specialist_name,
            "task_summary": task,
            "publish_to_wp": publish,
            "messages": state["messages"] + [AIMessage(content=f"🔀 Předávám specialistovi: **{specialist_name}**")],
        }

    # Detekuj složitý úkol — pokud model neví kam delegovat a zpráva je dlouhá
    complex_indicators = [" a ", " pak ", " potom ", " taky ", " napiš ", " vytvoř ", " zpracuj "]
    if len(last_message) > 50 and sum(1 for w in complex_indicators if w in query_lower) >= 2:
        console.print(f"  [yellow]🧩 Rozpoznán složitý úkol — vytvářím plán...[/yellow]")
        steps = decompose_task(last_message)
        if steps:
            step_list = "\n".join(f"  {i+1}. {s['step']} ({s['specialist']})" for i, s in enumerate(steps))
            console.print(f"  [cyan]📋 Plán ({len(steps)} kroků):[/cyan]")
            for i, s in enumerate(steps):
                console.print(f"    {i+1}. {s['step']}")
                save_task(s['step'])
            return {
                **state,
                "pending_steps": steps,
                "step_results": [],
                "current_plan": last_message,
                "current_specialist": "next_step",
                "messages": state["messages"] + [AIMessage(content=f"📋 Vytvořen plán ({len(steps)} kroků):\n{step_list}\n\nZačínám...")],
            }

    # Ulož do paměti pokud je to hodnotné
    if len(content) > 100:
        save_memory(content, category="conversation")

    return {
        **state,
        "current_specialist": "done",
        "messages": state["messages"] + [response],
    }


def specialist_node(state: AgentState) -> AgentState:
    """Volá správného specialistu."""
    specialist_name = state.get("current_specialist", "fast")
    task = state.get("task_summary", state["messages"][-2].content)

    model, system_prompt = get_specialist(specialist_name)

    console.print(f"  [dim]⚙️  Specialista [{specialist_name}] pracuje...[/dim]")

    response = model.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=task),
    ])

    # Ulož výsledek do paměti (save_memory automaticky přeskočí duplicity a triviální)
    category = specialist_name if specialist_name != "fast" else "general"
    if len(response.content) > 100:
        save_memory(response.content[:500], category=category)

    extra_messages = [response]

    # === WooCommerce: parsuj a proveď JSON akce ===
    if specialist_name == "woocommerce":
        import json as _json
        wc_results = []
        found_product_id = None
        found_product_name = None
        found_variant_id = None
        found_all_variants = []  # Seřazený seznam všech variant (pro multi-update)

        try:
            # Parsuj JSON z odpovědi
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            # Někdy model obalí do textu — zkus najít JSON pole
            if not content.startswith("["):
                import re
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    content = json_match.group(0)

            actions = _json.loads(content)
            if not isinstance(actions, list):
                actions = [actions]

            console.print(f"  [cyan]🔧 Provádím {len(actions)} akcí...[/cyan]")

            for i, act in enumerate(actions):
                action = act.get("action", "")
                console.print(f"    {i+1}. {action}...")

                try:
                    if action == "list_products":
                        result = list_products(search=act.get("search", ""))
                        if result and isinstance(result, list) and len(result) > 0:
                            found_product_id = result[0].get("id")
                            found_product_name = result[0].get("name", "")
                            wc_results.append(f"📦 Nalezeno: {found_product_name} (ID: {found_product_id})")
                            console.print(f"      → Nalezeno: {found_product_name} (ID: {found_product_id})")
                        else:
                            wc_results.append("❌ Produkt nenalezen")

                    elif action == "get_product":
                        pid = act.get("product_id")
                        if pid == "FOUND_ID" or pid is None:
                            pid = found_product_id
                        if pid:
                            result = get_product(int(pid))
                            wc_results.append(f"📦 {result.get('name')}: sklad={result.get('stock_quantity', '?')}, cena={result.get('regular_price', '?')} Kč")

                    elif action == "list_variations":
                        pid = act.get("product_id")
                        if pid == "FOUND_ID" or pid is None:
                            pid = found_product_id
                        if pid:
                            from tools.woocommerce import list_variations
                            variations = list_variations(int(pid))
                            if variations:
                                import re
                                task_lower = task.lower()

                                # Scóruj každou variantu podle shody s textem úkolu
                                scored = []
                                for var in variations:
                                    attrs = var.get("attributes", [])
                                    score = 0
                                    for a in attrs:
                                        opt = str(a.get("option", "")).lower()
                                        if opt and re.search(r'\b' + re.escape(opt) + r'\b', task_lower):
                                            score += 1
                                    scored.append((score, var))

                                # Seřaď podle skore (nejč astější zmínky první)
                                scored.sort(key=lambda x: -x[0])
                                found_all_variants = [v for _, v in scored]

                                # Primární varianta: nejlepší shoda
                                best = found_all_variants[0]
                                best_score = scored[0][0]
                                found_variant_id = best.get("id")
                                attr_str = ", ".join([str(a.get("option", "")) for a in best.get("attributes", [])])

                                if best_score > 0:
                                    wc_results.append(f"📦 Nalezena varianta: {attr_str} (ID: {found_variant_id})")
                                    console.print(f"      → Nalezena varianta: {attr_str} (ID: {found_variant_id})")
                                else:
                                    wc_results.append(f"📦 Nalezena varianta (první dostupná): {attr_str} (ID: {found_variant_id})")
                                    console.print(f"      → Použita první varianta: {attr_str} (ID: {found_variant_id})")

                                console.print(f"      → Celkem {len(found_all_variants)} variant uloženo pro multi-update")
                            else:
                                wc_results.append("❌ Produkt nemá žádné varianty")

                    elif action == "update_stock":
                        product_id = act.get("product_id")
                        variant_id = act.get("variant_id")
                        qty = act.get("quantity", 1)
                        op = act.get("operation", "add")

                        # Resolve product ID
                        if product_id == "FOUND_ID" or product_id is None:
                            product_id = found_product_id

                        # Resolve variant ID — podporuje i FOUND_VARIANT_ID_N (index)
                        if variant_id is None or variant_id == "FOUND_VARIANT_ID":
                            variant_id = found_variant_id
                        elif isinstance(variant_id, str) and variant_id.startswith("FOUND_VARIANT_ID_"):
                            # Extrahuj index: FOUND_VARIANT_ID_1 → index 0 (1-based)
                            try:
                                idx = int(variant_id.split("_")[-1]) - 1
                                if found_all_variants and 0 <= idx < len(found_all_variants):
                                    variant_id = found_all_variants[idx].get("id")
                                    attr_str = ", ".join([str(a.get("option", "")) for a in found_all_variants[idx].get("attributes", [])])
                                    console.print(f"      → Varianta #{idx+1}: {attr_str} (ID: {variant_id})")
                                else:
                                    wc_results.append(f"❌ Varianta na indexu {idx+1} nenalezena")
                                    continue
                            except (ValueError, IndexError):
                                variant_id = found_variant_id
                        
                        if product_id:
                            # Ensure product_id is an integer
                            product_id = int(product_id)
                            
                            # Call update_stock with variant_id if provided
                            if variant_id:
                                result = update_stock(product_id, qty, op, variant_id=int(variant_id))
                            else:
                                result = update_stock(product_id, qty, op)
                                
                            new_qty = result.get("stock_quantity", "?")
                            wc_results.append(f"✅ Sklad aktualizován: {op} {qty} ks → nyní {new_qty} ks")
                            console.print(f"      → Sklad: {op} {qty} ks → {new_qty} ks")
                        else:
                            wc_results.append("❌ Neznámé product_id")

                    elif action == "update_price":
                        pid = act.get("product_id") or found_product_id
                        if pid:
                            result = update_price(int(pid), act.get("regular_price", "0"), act.get("sale_price"))
                            wc_results.append(f"✅ Cena aktualizována: {act.get('regular_price')} Kč")

                    elif action == "create_product":
                        result = create_product(
                            name=act.get("name", "Nový produkt"),
                            description=act.get("description", ""),
                            price=act.get("price", "0"),
                            status=act.get("status", "draft"),
                        )
                        if result.get("ok"):
                            found_product_id = result.get("id")
                            wc_results.append(f"✅ Produkt vytvořen: {act.get('name')} (ID: {found_product_id})")

                    elif action == "create_variation":
                        pid = act.get("product_id") or found_product_id
                        if pid:
                            from tools.woocommerce import create_variation
                            result = create_variation(
                                int(pid),
                                act.get("attributes", {}),
                                act.get("price", "0"),
                                stock=act.get("stock"),
                            )
                            wc_results.append(f"✅ Varianta vytvořena")

                    elif action == "list_variations":
                        pid = act.get("product_id") or found_product_id
                        if pid:
                            from tools.woocommerce import list_variations
                            result = list_variations(int(pid))
                            if result:
                                var_list = ", ".join(f"ID:{v.get('id')} {v.get('attributes', [])}" for v in result[:5])
                                wc_results.append(f"📋 Varianty: {var_list}")

                    elif action == "list_orders":
                        from tools.order_watcher import check_orders_on_demand
                        per_page = act.get("per_page", 10)
                        api_answer = check_orders_on_demand(per_page=per_page)
                        wc_results.append(f"\n{api_answer}")

                except Exception as e:
                    wc_results.append(f"❌ Chyba v akci {action}: {e}")

        except (_json.JSONDecodeError, Exception):
            # Fallback — model nevrátil JSON → pokus se odpovědět přímo z API
            task_lower_fb = task.lower()
            if any(w in task_lower_fb for w in ["objednávk", "objednavk", "objednávky", "objednavky", "order"]):
                api_answer = check_orders_on_demand(per_page=10)
                extra_messages = [AIMessage(content=api_answer)]
                wc_results = ["(data z API)"]  # Flag aby se nepřeskočilo
            elif any(w in task_lower_fb for w in ["produkt", "sklad", "cena", "seznam"]):
                wc_answer = wc_query(task)
                if wc_answer:
                    extra_messages = [AIMessage(content=wc_answer)]
                    wc_results = ["(data z API)"]

        if wc_results:
            summary = "\n".join(wc_results)
            extra_messages = [AIMessage(content=f"🛒 **WooCommerce výsledky:**\n{summary}")]

    # === Web Search: parsuj JSON a hledej na netu ===
    if specialist_name == "web":
        import json as _json
        try:
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            if not content.startswith("[") and not content.startswith("{"):
                import re
                json_match = re.search(r'\[.*\]|\{.*\}', content, re.DOTALL)
                if json_match:
                    content = json_match.group(0)

            actions = _json.loads(content)
            if not isinstance(actions, list):
                actions = [actions]
                
            for act in actions:
                if act.get("action") == "web_search":
                    query = act.get("query", task)
                    console.print(f"  [cyan]🔍 Hledám na webu (DuckDuckGo): '{query}'...[/cyan]")
                    
                    search_results = ddg_search(query)
                    
                    console.print(f"  [cyan]🧠 Syntetizuji nalezená data...[/cyan]")
                    synthesis_response = model.invoke([
                        SystemMessage(content=f"Jsi asistent. Zeptali se tě: '{task}'. Našel jsi na internetu následující texty. Napiš uživateli velmi přímou, jasnou a přesnou odpověď na jeho otázku. Nepoužívej obecnou 'AI' omáčku. Odpověz v češtině:\n\n{search_results}"),
                        HumanMessage(content="Napiš stručně a jasně co jsi zjistil.")
                    ])
                    
                    extra_messages = [AIMessage(content=f"🌐 **Internet (DDG):**\n{synthesis_response.content}")]
                    break
        except Exception as e:
            console.print(f"  [red]❌ Chyba ve webovém hledání: {e}[/red]")
            extra_messages = [AIMessage(content=f"Nastal problém při vyhledávání na internetu: {e}")]

    # === Deep Research: Tavily pro Research agenta ===
    if specialist_name == "research":
        import json as _json
        try:
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            # Pokud model vrátil JSON s deep_research akcí
            if content.startswith("[") or content.startswith("{"):
                import re
                json_match = re.search(r'\[.*\]|\{.*\}', content, re.DOTALL)
                if json_match:
                    parsed = _json.loads(json_match.group(0))
                    if not isinstance(parsed, list):
                        parsed = [parsed]
                    
                    for act in parsed:
                        if act.get("action") == "deep_research":
                            query = act.get("query", task)
                            console.print(f"  [magenta]🔬 Provádím Deep Research (Tavily): '{query}'...[/magenta]")
                            
                            search_results = tavily_search(query, max_results=8) # Žádám o robustnější odpovědi
                            
                            console.print(f"  [magenta]🧠 Syntetizuji výzkumná data...[/magenta]")
                            synthesis_response = model.invoke([
                                SystemMessage(content=f"Jsi analytik dělající hlubokou rešerši úkolu: '{task}'. Našel jsi na internetu následující texty a zdroje. Vytvoř ucelenou, strukturovanou a logickou zprávu zjištěných faktů. Používej odrážky a formátování:\n\n{search_results}"),
                                HumanMessage(content="Sestav závěrečnou zprávu o svém zjištění.")
                            ])
                            
                            # Nahraď původní (JSON) odpověď syntetizovaným rešeršním výsledkem
                            response.content = f"🔬 **Výsledky hlubokého výzkumu:**\n\n{synthesis_response.content}"
                            extra_messages = [response]
                            break
        except Exception as e:
            pass # Pokud to nebyl JSON nebo se zhroutilo hledání, prostě nechte původní odpověď modelui

    # === Social Media Agent ===
    if specialist_name == "social_media":
        import json as _json
        try:
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            if content.startswith("[") or content.startswith("{"):
                import re
                json_match = re.search(r'\[.*\]|\{.*\}', content, re.DOTALL)
                if json_match:
                    parsed = _json.loads(json_match.group(0))
                    if not isinstance(parsed, list):
                        parsed = [parsed]
                    
                    for act in parsed:
                        if act.get("action") == "check_tiktok":
                            topic = act.get("topic", "")
                            console.print(f"  [magenta]📱 Hledám TikTok trendy: {topic} ...[/magenta]")
                            res_text = get_tiktok_trends(topic)
                            response.content = res_text
                            extra_messages = [response]
                            break
                        elif act.get("action") == "check_ig":
                            topic = act.get("topic", "")
                            console.print(f"  [magenta]📸 Hledám IG trendy: {topic} ...[/magenta]")
                            res_text = get_ig_trends(topic)
                            response.content = res_text
                            extra_messages = [response]
                            break
        except Exception as e:
            pass

    # === Science Agent ===
    if specialist_name == "science":
        import json as _json
        try:
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            if content.startswith("[") or content.startswith("{"):
                import re
                json_match = re.search(r'\[.*\]|\{.*\}', content, re.DOTALL)
                if json_match:
                    parsed = _json.loads(json_match.group(0))
                    if not isinstance(parsed, list):
                        parsed = [parsed]
                    
                    for act in parsed:
                        if act.get("action") == "pubmed_search":
                            query = act.get("query", "")
                            console.print(f"  [magenta]🔬 Hledám ve vědeckých studiích PubMed: '{query}' ...[/magenta]")
                            res_text = search_pubmed(query, max_results=5)
                            
                            console.print(f"  [magenta]🧠 Syntetizuji vědecká data...[/magenta]")
                            synthesis_response = model.invoke([
                                SystemMessage(content=f"Jsi vědecký specialista dělající rešerši úkolu: '{task}'. Našel jsi v databázi PubMed následující abstrakty. Vytvoř ucelenou odbornou zprávu a shrnutí. Používej odrážky a zachovej zmínky o PMIDs studií.\n\n{res_text}"),
                                HumanMessage(content="Sestav závěrečnou zprávu o svém zjištění z PubMed.")
                            ])
                            
                            response.content = synthesis_response.content
                            extra_messages = [response]
                            break
                        elif act.get("action") == "virtual_lab":
                            smiles = act.get("smiles", "")
                            console.print(f"  [magenta]🧪 Posílám '{smiles}' do Virtuální Laboratoře k analýze...[/magenta]")
                            from tools.virtual_lab import test_molecule
                            res_text = test_molecule(smiles)
                            
                            console.print(f"  [magenta]🧠 Zhodnocuji laboratorní výsledky...[/magenta]")
                            synthesis_response = model.invoke([
                                SystemMessage(content=f"Jsi vědecký inženýr. Navrhl jsi molekulu: '{smiles}'. Z Virtuální Laboratoře jsi obdržel tento protokol fyzikálně-chemických vlastností (Lipinského pravidla atd.). Zhodnoť, jestli je látka vhodným biomateriálem nebo léčivem, případně navrhni, co chemicky změnit pro zlepšení vlastností.\n\n{res_text}"),
                                HumanMessage(content="Vyhodnoť laboratorní zprávu a navrhni případnou úpravu struktury.")
                            ])
                            
                            response.content = synthesis_response.content
                            extra_messages = [response]
                            break
        except Exception as e:
            pass

    # Pokud jde o wordpress specialistu a uživatel chce publikovat → pošli na WP
    if specialist_name == "wordpress" and state.get("publish_to_wp", False):
        title = extract_title(response.content)
        wp_result = wp_create_post(title, response.content, status="draft")
        if wp_result["ok"]:
            extra_messages.append(AIMessage(
                content=f"\n📝 **Draft vytvořen ve WordPressu!**\nURL: {wp_result['url']}\nID: {wp_result['id']}"
            ))

    # Po dokončení kroku — označ krok jako hotový
    step_results = state.get("step_results", [])
    pending = state.get("pending_steps", [])
    task_text = state.get("task_summary", "")

    if task_text:
        step_results.append({"step": task_text, "result": response.content[:200]})
        # Označ task jako done
        complete_task(task_text)

    total = len(step_results) + len(pending)
    current_num = len(step_results)
    if total > 1:
        console.print(f"  [green]✅ Krok {current_num}/{total} hotov[/green]")

    return {
        **state,
        "step_results": step_results,
        "current_specialist": "done" if not pending else "next_step",
        "messages": state["messages"] + extra_messages,
    }


def router_node(state: AgentState) -> str:
    """Rozhoduje kam jít dál."""
    specialist = state.get("current_specialist", "done")
    
    if specialist == "next_step":
        return "orchestrator"  # Smyčka — zpět na orchestrátor pro další krok
    elif specialist == "done" or specialist == "":
        return "end"
    elif specialist in ["coding", "wordpress", "marketing", "research", "fast", "woocommerce"]:
        return "specialist"
    else:
        return "end"


# === SESTAVENÍ GRAFU ===
def build_agent():
    workflow = StateGraph(AgentState)

    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("specialist", specialist_node)

    workflow.set_entry_point("orchestrator")

    workflow.add_conditional_edges(
        "orchestrator",
        router_node,
        {
            "specialist": "specialist",
            "orchestrator": "orchestrator",  # Smyčka pro auto-plan
            "end": END,
        },
    )
    # Po specialistovi → zpět na orchestrátor (smyčka pro kroky)
    workflow.add_conditional_edges(
        "specialist",
        router_node,
        {
            "orchestrator": "orchestrator",
            "end": END,
        },
    )

    return workflow.compile()


# === SPUŠTĚNÍ – interaktivní chat ===
def main():
    # Organické zapomínání: vyčisti staré nepoužívané vzpomínky při startu
    cleaned = cleanup_old_memories()
    if cleaned > 0:
        console.print(f"  [dim]🧹 Vyčištěno {cleaned} starých vzpomínek[/dim]")

    mem_stats = get_memory_stats()
    open_tasks = mem_stats.get('open_tasks', 0)
    task_info = f" | Úkoly: {open_tasks} otevřených" if open_tasks else ""
    console.print(Panel.fit(
        "[bold cyan]🤖 Autonomní Agent[/bold cyan]\n"
        f"[dim]Orchestrátor: auto (cloud → llama3.1:8b)\n"
        f"Paměť: ChromaDB ({mem_stats.get('total_memories', '?')} vzpomínek){task_info} | Specialisté: 6[/dim]",
        border_style="cyan"
    ))
    console.print("[dim]Příkazy: 'paměť' | 'úkoly' | 'úkol: ...' | 'hotovo: ...' | 'zapomeň ...' | 'exit'[/dim]\n")

    agent = build_agent()

    # Spusť automatický watcher nových objednávek (3x denně)
    start_order_scheduler(console, times=["08:00", "12:00", "20:00"])

    conversation_history = []
    conversation_summary = ""  # Sumarizace starších zpráv

    while True:
        try:
            user_input = console.input("[bold green]Ty:[/bold green] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Ukončuji...[/dim]")
            break

        if user_input.lower() in ["exit", "quit", "konec"]:
            console.print("[dim]Na shledanou![/dim]")
            break

        if not user_input:
            continue

        # Diagnostické příkazy
        if user_input.lower() in ["paměť", "pamet", "memory", "stats"]:
            stats = get_memory_stats()
            console.print(f"  🧠 Paměť: {stats.get('total_memories', '?')} vzpomínek")
            console.print(f"  📋 Úkoly: {stats.get('open_tasks', 0)} otevřených")
            console.print(f"  💬 Historie: {len(conversation_history)} zpráv")
            if conversation_summary:
                console.print(f"  📋 Souhrn: {conversation_summary[:100]}...")
            continue

        # Hledání v paměti
        if user_input.lower().startswith("vzpomeň") or user_input.lower().startswith("co víš"):
            query = user_input.split(" ", 1)[-1] if " " in user_input else user_input
            results = search_memory(query, n_results=5)
            if results:
                console.print(f"  🧠 Našel jsem {len(results)} vzpomínek:")
                for r in results:
                    console.print(f"    [{r['category']}] {r['content'][:100]}")
            else:
                console.print("  🧠 Nic jsem nenašel.")
            continue

        conversation_history.append(HumanMessage(content=user_input))

        # === Conversation Summarization ===
        if len(conversation_history) > 8:
            old_msgs = conversation_history[:-4]
            summary_text = "\n".join(
                f"{'Uživatel' if isinstance(m, HumanMessage) else 'Agent'}: {m.content[:150]}"
                for m in old_msgs[-6:]
            )
            conversation_summary = f"Předchozí konverzace: {summary_text}"
            conversation_history = conversation_history[-4:]

        # Připrav zprávy pro agenta
        messages_for_agent = []
        if conversation_summary:
            messages_for_agent.append(SystemMessage(content=f"SOUHRN KONVERZACE:\n{conversation_summary}"))
        messages_for_agent.extend(conversation_history[-6:])

        # Spusť agenta
        console.print("[dim]⏳ Přemýšlím...[/dim]")
        
        try:
            result = agent.invoke({
                "messages": messages_for_agent,
                "current_specialist": "",
                "task_summary": "",
                "use_memory": True,
                "publish_to_wp": False,
                "pending_steps": [],
                "current_plan": "",
                "step_results": [],
            })

            # Poslední zpráva od AI
            ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
            if ai_messages:
                final_response = ai_messages[-1].content
                conversation_history.append(AIMessage(content=final_response))
                
                console.print(Panel(
                    final_response,
                    title="[bold blue]Agent[/bold blue]",
                    border_style="blue",
                ))

        except KeyboardInterrupt:
            console.print("\n[yellow]⚡ Přerušeno (Ctrl+C) — zpět na prompt[/yellow]")
            continue

        except Exception as e:
            console.print(f"[red]❌ Chyba: {e}[/red]")
            console.print("[dim]Tip: Zkontroluj jestli Ollama běží na localhost:11434[/dim]")


if __name__ == "__main__":
    import signal
    # Dvojité Ctrl+C = okamžitý exit
    signal.signal(signal.SIGINT, lambda s, f: (
        print("\n⚡ Ukončuji..."),
        exit(0)
    ))
    main()

