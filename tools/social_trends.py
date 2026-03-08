import os
import urllib.request
import json
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

def get_tiktok_trends(keyword: str = "") -> str:
    """
    Získá virová videa z TikToku (skrze RapidAPI TikTok API).
    """
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key or "xxxxxx" in api_key:
        return "❌ Chyba: `RAPIDAPI_KEY` není nastaven v `.env`. Vytvoř si účet na rapidapi.com, odebírej 'TikTok Search' API a vlož klíč."

    # Příklad obvyklého endpointu na RapidAPI (např. 'tiktok-scraper7.p.rapidapi.com')
    # Pro produkci je nutné vybrat konkrétní API providera z RapidAPI hubu.
    host = "tiktok-scraper7.p.rapidapi.com"
    query = urllib.parse.quote(keyword if keyword else "viral")
    url = f"https://{host}/feed/search?keywords={query}&region=us&count=10"
    
    req = urllib.request.Request(url, headers={
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": host
    })
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            videos = data.get("data", {}).get("videos", [])
            
            if not videos:
                return f"❓ Nenalezena žádná virální videa pro: {keyword}"
                
            out = f"📱 **TikTok Trendy pro '{keyword}'**:\n\n"
            for idx, v in enumerate(videos[:5], 1):
                desc = v.get("title", "")
                play_count = v.get("play_count", 0)
                author = v.get("author", {}).get("nickname", "Neznámý")
                
                out += f"{idx}. {desc}\n👤 Autor: {author} | 👁 Zhlédnutí: {play_count}\n---\n"
            return out
            
    except Exception as e:
        return f"❌ Selhalo připojení na TikTok API: {str(e)}"

def get_ig_trends(hashtag: str = "") -> str:
    """
    Získá nejlepší příspěvky pro daný hashtag na Instagramu (přes RapidAPI).
    """
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key or "xxxxxx" in api_key:
         return "❌ Chyba: `RAPIDAPI_KEY` není nastaven v `.env`."

    # Náhledový endpoint (např. 'instagram-scraper-api2.p.rapidapi.com')
    host = "instagram-scraper-api2.p.rapidapi.com"
    tag = urllib.parse.quote(hashtag.replace("#", "") if hashtag else "viral")
    url = f"https://{host}/v1/hashtag?hashtag={tag}"
    
    req = urllib.request.Request(url, headers={
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": host
    })
    
    try:
         with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            items = data.get("data", {}).get("items", [])
            
            if not items:
                return f"❓ Nenalezeny příspěvky pro IG hashtag: #{hashtag}"
                
            out = f"📸 **Instagram Top příspěvky pro #{hashtag}**:\n\n"
            for idx, post in enumerate(items[:5], 1):
                caption = post.get("caption", {}).get("text", "")[:100] + "..."
                likes = post.get("like_count", 0)
                comments = post.get("comment_count", 0)
                
                out += f"{idx}. {caption}\n❤️ Lajky: {likes} | 💬 Komentáře: {comments}\n---\n"
            return out
    except Exception as e:
         return f"❌ Selhalo připojení na IG API: {str(e)}"
