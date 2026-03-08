import sys
import json
import httpx
from dotenv import load_dotenv
import os

load_dotenv()

WC_URL = os.getenv("WC_URL")
WC_KEY = os.getenv("WC_KEY")
WC_SECRET = os.getenv("WC_SECRET")

def get_variation_meta(product_id: int, variation_id: int):
    url = f"{WC_URL}/wp-json/wc/v3/products/{product_id}/variations/{variation_id}"
    print(f"📡 Fetching: {url}")
    r = httpx.get(
        url,
        auth=(WC_KEY, WC_SECRET),
        timeout=30,
    )
    if r.status_code != 200:
        print(f"❌ Error: {r.status_code}")
        print(r.text)
        return
        
    data = r.json()
    print("\n📦 Variation Meta Data:\n" + "="*40)
    for meta in data.get("meta_data", []):
        print(f"Key: {meta.get('key')} -> Value: {meta.get('value')}")
    print("="*40)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 check_meta.py <product_id> <variation_id>")
        sys.exit(1)
        
    pid = int(sys.argv[1])
    vid = int(sys.argv[2])
    get_variation_meta(pid, vid)
