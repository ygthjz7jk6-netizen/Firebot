import urllib.request
import json
import urllib.parse

def ddg_api(query):
    url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            results = []
            if data.get('AbstractText'):
                results.append(data['AbstractText'])
            for topic in data.get('RelatedTopics', []):
                if 'Text' in topic:
                    results.append(topic['Text'])
            return "\n".join(results[:5]) if results else "Nic nenalezeno přes Lite API."
    except Exception as e:
        return str(e)

print(ddg_api("Praha"))
