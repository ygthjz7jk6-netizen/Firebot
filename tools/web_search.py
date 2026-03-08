import os
import json
from tavily import TavilyClient
from dotenv import load_dotenv

# Načti proměnné prostředí
load_dotenv()

def tavily_search(query: str, max_results: int = 4) -> str:
    """
    Provede vyhledávání na internetu pomocí Tavily API.
    Vrátí zformátovaný textový výsledek připravený pro LLM.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    
    if not api_key or "xxxxxx" in api_key:
        return "❌ Chyba: TAVILY_API_KEY není správně nastaven v souboru .env. Zaregistrujte se na tavily.com a uložte svůj klíč."

    try:
        # Inicializace klienta
        client = TavilyClient(api_key=api_key)
        
        # Provedení základního vyhledávání s pokročilými informacemi (obsah stránek)
        response = client.search(
            query=query, 
            search_depth="advanced", 
            max_results=max_results,
            include_answer=False,
            include_raw_content=False
        )
        
        results = response.get("results", [])
        
        if not results:
            return f"❓ Nenalezeno žádné relevantní info k dotazu: '{query}'"
            
        # Zformátování výstupu pro LLM
        formatted_output = f"Vyhledáno klíčové slovo: '{query}'\nVýsledky hledání:\n\n"
        
        for idx, res in enumerate(results, 1):
            title = res.get("title", "Bez názvu")
            url = res.get("url", "#")
            content = res.get("content", "")
            
            formatted_output += f"[{idx}] {title}\nZdroj: {url}\nObsah: {content}\n---\n"
            
        return formatted_output
        
    except Exception as e:
        return f"❌ Pokus o připojení k internetu selhal: {str(e)}"

# Testování napřímo
if __name__ == "__main__":
    print(tavily_search("Co je to AI agent LangGraph?"))
