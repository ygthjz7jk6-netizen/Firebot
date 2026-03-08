"""
WooCommerce specialista — správa e-shopu přes REST API
Umí: produkty, fotky, sklad, ceny, slevy, kategorie, štítky, objednávky, varianty
"""

import os
import httpx
import base64
import sys
from dotenv import load_dotenv

base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(base_dir, '.env'))

WC_URL = os.getenv("WC_URL", "").rstrip("/")
WC_KEY = os.getenv("WC_KEY", "")
WC_SECRET = os.getenv("WC_SECRET", "")
WP_USER = os.getenv("WP_USER", "")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "").replace(" ", "")

# Auth hlavičky
def wc_auth():
    """WooCommerce Consumer Key/Secret autentizace."""
    return (WC_KEY, WC_SECRET)

def wp_auth_header():
    """WordPress Basic Auth pro media upload."""
    token = base64.b64encode(f"agent-bnb:{WP_APP_PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# ── PRODUKTY ─────────────────────────────────────────────────────────────────

def create_product(
    name: str,
    description: str,
    price: str,
    stock_quantity: int = None,
    categories: list[str] = None,
    tags: list[str] = None,
    status: str = "draft",
) -> dict:
    """
    Vytvoří nový produkt ve WooCommerce.
    
    Args:
        name: Název produktu
        description: Popis produktu (HTML povoleno)
        price: Cena jako string, např. "299.00"
        stock_quantity: Počet kusů na skladě (None = neomezeno)
        categories: Seznam názvů kategorií
        tags: Seznam štítků
        status: "draft" nebo "publish"
    
    Returns:
        dict s id, permalink a dalšími daty nového produktu
    """
    payload = {
        "name": name,
        "description": description,
        "regular_price": str(price),
        "status": status,
        "manage_stock": stock_quantity is not None,
    }

    if stock_quantity is not None:
        payload["stock_quantity"] = stock_quantity

    if categories:
        cat_ids = _get_or_create_categories(categories)
        payload["categories"] = [{"id": cid} for cid in cat_ids]

    if tags:
        tag_ids = _get_or_create_tags(tags)
        payload["tags"] = [{"id": tid} for tid in tag_ids]

    r = httpx.post(
        f"{WC_URL}/wp-json/wc/v3/products",
        auth=wc_auth(),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def update_product(product_id: int, **kwargs) -> dict:
    """
    Aktualizuje existující produkt.
    
    Příklad: update_product(123, regular_price="399.00", stock_quantity=50)
    """
    r = httpx.put(
        f"{WC_URL}/wp-json/wc/v3/products/{product_id}",
        auth=wc_auth(),
        json=kwargs,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def update_variation(product_id: int, variant_id: int, **kwargs) -> dict:
    """
    Aktualizuje existující variantu produktu.
    """
    r = httpx.put(
        f"{WC_URL}/wp-json/wc/v3/products/{product_id}/variations/{variant_id}",
        auth=wc_auth(),
        json=kwargs,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_product(product_id: int) -> dict:
    """Načte detail produktu."""
    r = httpx.get(
        f"{WC_URL}/wp-json/wc/v3/products/{product_id}",
        auth=wc_auth(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def list_products(per_page: int = 20, page: int = 1, search: str = None) -> list:
    """Vypíše seznam produktů."""
    params = {"per_page": per_page, "page": page}
    if search:
        params["search"] = search

    r = httpx.get(
        f"{WC_URL}/wp-json/wc/v3/products",
        auth=wc_auth(),
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ── SKLAD ─────────────────────────────────────────────────────────────────────

def update_stock(product_id: int, quantity: int, operation: str = "add", variant_id: int = None) -> dict:
    """
    Aktualizuje sklad produktu nebo varianty.
    
    Args:
        product_id: ID produktu
        quantity: Počet kusů
        operation: "add" = přidej (výchozí), "set" = nastav přesně, "subtract" = odeber
        variant_id: ID varianty (volitelné)
    """
    if operation != "set":
        if variant_id:
            # Get variant stock
            r = httpx.get(f"{WC_URL}/wp-json/wc/v3/products/{product_id}/variations/{variant_id}", auth=wc_auth(), timeout=30)
            r.raise_for_status()
            current = r.json()
        else:
            current = get_product(product_id)
            
        current_qty = current.get("stock_quantity") or 0
        if operation == "add":
            quantity = current_qty + quantity
        elif operation == "subtract":
            quantity = max(0, current_qty - quantity)

    if variant_id:
        return update_variation(
            product_id,
            variant_id,
            manage_stock=True,
            stock_quantity=quantity,
        )
    else:
        return update_product(
            product_id,
            manage_stock=True,
            stock_quantity=quantity,
        )


# ── CENY A SLEVY ──────────────────────────────────────────────────────────────

def update_price(product_id: int, regular_price: str, sale_price: str = None) -> dict:
    """
    Aktualizuje cenu produktu.
    
    Args:
        regular_price: Běžná cena, např. "499.00"
        sale_price: Slevová cena (None = žádná sleva)
    """
    payload = {"regular_price": str(regular_price)}
    if sale_price:
        payload["sale_price"] = str(sale_price)
    else:
        payload["sale_price"] = ""  # Zruší slevu

    return update_product(product_id, **payload)


# ── FOTKY ─────────────────────────────────────────────────────────────────────

def upload_image(image_path: str, alt_text: str = "") -> int:
    """
    Nahraje obrázek do WordPress Media Library.
    
    Returns:
        ID nahraného média
    """
    with open(image_path, "rb") as f:
        image_data = f.read()

    filename = os.path.basename(image_path)
    ext = filename.rsplit(".", 1)[-1].lower()
    mime_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    mime = mime_types.get(ext, "image/jpeg")

    headers = {
        **wp_auth_header(),
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime,
    }

    r = httpx.post(
        f"{WC_URL}/wp-json/wp/v2/media",
        headers=headers,
        content=image_data,
        timeout=60,
    )
    r.raise_for_status()
    media = r.json()

    # Nastav alt text pokud je zadán
    if alt_text:
        httpx.post(
            f"{WC_URL}/wp-json/wp/v2/media/{media['id']}",
            headers={**wp_auth_header(), "Content-Type": "application/json"},
            json={"alt_text": alt_text},
            timeout=15,
        )

    return media["id"]


def set_product_images(product_id: int, image_paths: list[str], alt_texts: list[str] = None) -> dict:
    """
    Nahraje fotky a přiřadí je k produktu.
    První fotka = hlavní obrázek, ostatní = galerie.
    
    Args:
        image_paths: Seznam cest k obrázkům
        alt_texts: Seznam alt textů (volitelné)
    """
    images = []
    for i, path in enumerate(image_paths):
        alt = (alt_texts[i] if alt_texts and i < len(alt_texts) else "")
        media_id = upload_image(path, alt)
        images.append({"id": media_id})

    return update_product(product_id, images=images)


# ── VARIANTY ──────────────────────────────────────────────────────────────────

def create_variation(product_id: int, attributes: dict, price: str, stock: int = None) -> dict:
    """
    Vytvoří variantu produktu (např. velikost, barva).
    
    Args:
        product_id: ID nadřazeného produktu (musí být typu "variable")
        attributes: Slovník atributů, např. {"Velikost": "M", "Barva": "Modrá"}
        price: Cena varianty
        stock: Sklad varianty
    
    Příklad:
        create_variation(123, {"Velikost": "XL"}, "599.00", stock=10)
    """
    payload = {
        "regular_price": str(price),
        "attributes": [
            {"name": k, "option": v}
            for k, v in attributes.items()
        ],
    }

    if stock is not None:
        payload["manage_stock"] = True
        payload["stock_quantity"] = stock

    r = httpx.post(
        f"{WC_URL}/wp-json/wc/v3/products/{product_id}/variations",
        auth=wc_auth(),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def list_variations(product_id: int) -> list:
    """Vypíše všechny varianty produktu."""
    r = httpx.get(
        f"{WC_URL}/wp-json/wc/v3/products/{product_id}/variations",
        auth=wc_auth(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ── OBJEDNÁVKY ────────────────────────────────────────────────────────────────

def list_orders(status: str = "any", per_page: int = 20) -> list:
    """
    Vypíše objednávky.
    
    Status: "pending", "processing", "completed", "cancelled", "any"
    """
    r = httpx.get(
        f"{WC_URL}/wp-json/wc/v3/orders",
        auth=wc_auth(),
        params={"status": status, "per_page": per_page},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def update_order_status(order_id: int, status: str) -> dict:
    """
    Aktualizuje stav objednávky.
    
    Status: "pending", "processing", "completed", "cancelled", "refunded"
    """
    r = httpx.put(
        f"{WC_URL}/wp-json/wc/v3/orders/{order_id}",
        auth=wc_auth(),
        json={"status": status},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ── KATEGORIE A ŠTÍTKY ────────────────────────────────────────────────────────

def _get_or_create_categories(names: list[str]) -> list[int]:
    """Vrátí ID kategorií, vytvoří chybějící."""
    ids = []
    for name in names:
        r = httpx.get(
            f"{WC_URL}/wp-json/wc/v3/products/categories",
            auth=wc_auth(),
            params={"search": name},
            timeout=15,
        )
        existing = r.json()
        if existing:
            ids.append(existing[0]["id"])
        else:
            r2 = httpx.post(
                f"{WC_URL}/wp-json/wc/v3/products/categories",
                auth=wc_auth(),
                json={"name": name},
                timeout=15,
            )
            ids.append(r2.json()["id"])
    return ids


def _get_or_create_tags(names: list[str]) -> list[int]:
    """Vrátí ID štítků, vytvoří chybějící."""
    ids = []
    for name in names:
        r = httpx.get(
            f"{WC_URL}/wp-json/wc/v3/products/tags",
            auth=wc_auth(),
            params={"search": name},
            timeout=15,
        )
        existing = r.json()
        if existing:
            ids.append(existing[0]["id"])
        else:
            r2 = httpx.post(
                f"{WC_URL}/wp-json/wc/v3/products/tags",
                auth=wc_auth(),
                json={"name": name},
                timeout=15,
            )
            ids.append(r2.json()["id"])
    return ids


# ── RYCHLÝ TEST ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🧪 Test WooCommerce připojení...")
    try:
        products = list_products(per_page=1)
        print(f"✅ Připojení OK — nalezeno produktů: {len(products)}")
    except Exception as e:
        print(f"❌ Chyba: {e}")
