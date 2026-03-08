import os
import json
from tavily import TavilyClient
from dotenv import load_dotenv

# Načti proměnné prostředí
load_dotenv()

def tavily_search(query: str, max_results: int = 6) -> str:
    """
    Provede vyhledávání na internetu pomocí Tavily API.
    Vrátí zformátovaný textový výsledek připravený pro LLM.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    
    if not api_key or "xxxxxx" in api_key:
        return "❌ Chyba: TAVILY_API_KEY není správně nastaven v souboru .env."

    try:
        # Inicializace klienta
        client = TavilyClient(api_key=api_key)
        
        # Provedení základního vyhledávání s pokročilými informacemi
        response = client.search(
            query=query, 
            search_depth="advanced", 
            max_results=max_results,
            include_answer=True,
            include_raw_content=False
        )
        
        results = response.get("results", [])
        answer = response.get("answer")
        
        if not results and not answer:
            return f"❓ Tavily nenalezlo žádné relevantní info k dotazu: '{query}'"
            
        formatted_output = f"Vyhledáno přes Tavily: '{query}'\n"
        if answer:
            formatted_output += f"PŘÍMÁ ODPOVĚĎ: {answer}\n\n"
        
        formatted_output += "Výsledky hledání:\n\n"
        
        for idx, res in enumerate(results, 1):
            title = res.get("title", "Bez názvu")
            url = res.get("url", "#")
            content = res.get("content", "")
            formatted_output += f"[{idx}] {title}\nZdroj: {url}\nObsah: {content}\n---\n"
            
        return formatted_output
        
    except Exception as e:
        return f"❌ Tavily selhalo: {str(e)}"

def ddg_search(query: str, max_results: int = 5) -> str:
    """
    Rychlé hledání přes DuckDuckGo. FIX #7: Přidána robustnější konfigurace.
    """
    try:
        from duckduckgo_search import DDGS
        
        # FIX #7: Zkusíme hledat bez regionu a s jinými parametry pro vyšší šanci na úspěch
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            
            if not results:
                # Zkusíme ještě jednou s jiným dotazem (bez diakritiky) jako fallback
                import unicodedata
                query_no_diacritics = ''.join(c for c in unicodedata.normalize('NFD', query) if unicodedata.category(c) != 'Mn')
                if query_no_diacritics != query:
                    results = list(ddgs.text(query_no_diacritics, max_results=max_results))

            if not results:
                return f"❓ DuckDuckGo nenalezlo žádné relevantní info k dotazu: '{query}'"
                
            formatted_output = f"Vyhledáno přes DuckDuckGo: '{query}'\nVýsledky hledání:\n\n"
            for idx, res in enumerate(results, 1):
                title = res.get('title', 'Bez názvu')
                body = res.get('body', '')
                url = res.get('href', '#')
                formatted_output += f"[{idx}] {title}\nZdroj: {url}\nObsah: {body}\n---\n"
                
            return formatted_output
            
    except Exception as e:
        return f"❌ DuckDuckGo selhalo: {str(e)}"

def web_search_unified(query: str, max_results: int = 6) -> str:
    """
    Fix #7: Hlavní vyhledávací funkce, která inteligentně volí mezi Tavily a DDG.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    
    # Pokud máme Tavily klíč, použijeme ho jako primární (je mnohem spolehlivější)
    if api_key and "xxxxxx" not in api_key:
        result = tavily_search(query, max_results=max_results)
        if "❓" not in result and "❌" not in result:
            return result
            
    # Fallback na DuckDuckGo
    return ddg_search(query, max_results=max_results)

# Testování napřímo
if __name__ == "__main__":
    print(web_search_unified("počasí v Trutnově dnes"))
