"""
Nástroj pro zpracování produktových fotek
- Moondream rozpozná produkt a barvu
- Pillow zkomprimuje fotku
- WooCommerce API přiřadí fotku ke správné variantě
"""

import os
import json
import re
import time
import httpx
import base64
from typing import Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
from dotenv import load_dotenv
import imagehash
from PIL import Image

base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(base_dir, '.env'))

WC_URL = os.getenv("WC_URL", "").rstrip("/")
WC_KEY = os.getenv("WC_KEY", "")
WC_SECRET = os.getenv("WC_SECRET", "")
WP_USER = "agent-bnb"
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "").replace(" ", "")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


# ── ROZPOZNÁNÍ OBRÁZKU ────────────────────────────────────────────────────────

def analyze_image(image_path: str) -> dict:
    """
    Použije Moondream k rozpoznání produktu na fotce.
    Vrátí dict s product_type, color, description.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        return {"error": f"Soubor nenalezen: {image_path}"}

    # Načti obrázek a KONVERTUJ na JPEG in-memory (Moondream nezvládá WebP!)
    import io
    from PIL import Image as PILImage
    try:
        img = PILImage.open(image_path).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        image_data = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        return {"error": f"Nelze načíst obrázek: {e}"}

    prompt = """Look at this product photo carefully. What do you see?
Respond with ONLY a valid JSON object, no other text:
{
  "product_type": "hat",
  "color": "red-blue",
  "color_czech": "červeno-modrá",
  "variant_label": "červeno-modrý vzor",
  "description": "Háčkovaná čepice s červeno-modrým vzorem"
}
Rules:
- product_type: what is the product? (hat, belt, t-shirt, headband, keychain, bag, etc.)
- color: the dominant colors you see, in English, lowercase. If multicolored, join with dash: "red-blue-green"
- color_czech: same colors in Czech, joined with dash if multiple: "červeno-modro-zelená"
- variant_label: short Czech label to distinguish this variant from others (e.g. "modrý vzor", "přírodní hnědá", "černo-bílé pruhy")
- description: one sentence about the product in Czech
Respond with ONLY the JSON, nothing else."""

    fallback = {
        "product_type": "other",
        "color": "unknown",
        "color_czech": "neznámá",
        "description": "",
    }

    try:
        response = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "moondream",
                "prompt": prompt,
                "images": [image_data],
                "stream": False,
            },
            timeout=60,
        )
        result = response.json().get("response", "")

        # Debug: ukaž raw odpověď (první spuštění)
        # print(f"  🔬 Moondream raw ({Path(image_path).name}): {result[:150]}")

        # Strategie 1: Najdi vnořený JSON objekt (greedy)
        json_match = re.search(r"\{[^{}]*\}", result, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                # Ověř že obsahuje klíčové pole a doplň chybějící
                if "color" in parsed or "product_type" in parsed:
                    parsed.setdefault("product_type", "other")
                    parsed.setdefault("color", "unknown")
                    parsed.setdefault("color_czech", "neznámá")
                    parsed.setdefault("variant_label", "")
                    parsed.setdefault("description", "")
                    return parsed
            except json.JSONDecodeError:
                pass

        # Strategie 2: Celý rozsah { ... } (pro vnořené objekty)
        json_match2 = re.search(r"\{.*\}", result, re.DOTALL)
        if json_match2 and json_match2.group() != (json_match.group() if json_match else ""):
            try:
                parsed = json.loads(json_match2.group())
                if "color" in parsed or "product_type" in parsed:
                    parsed.setdefault("product_type", "other")
                    parsed.setdefault("color", "unknown")
                    parsed.setdefault("color_czech", "neznámá")
                    parsed.setdefault("variant_label", "")
                    parsed.setdefault("description", "")
                    return parsed
            except json.JSONDecodeError:
                pass

        # Strategie 3: Extrahuj VŠECHNY klíčové hodnoty regexem (záchranná síť)
        color_match = re.search(r'"color"\s*:\s*"([^"]+)"', result)
        type_match = re.search(r'"product_type"\s*:\s*"([^"]+)"', result)
        czech_match = re.search(r'"color_czech"\s*:\s*"([^"]+)"', result)
        label_match = re.search(r'"variant_label"\s*:\s*"([^"]+)"', result)
        desc_match = re.search(r'"description"\s*:\s*"([^"]+)"', result)
        
        if color_match or type_match:
            return {
                "product_type": type_match.group(1) if type_match else "other",
                "color": color_match.group(1) if color_match else "unknown",
                "color_czech": czech_match.group(1) if czech_match else "neznámá",
                "variant_label": label_match.group(1) if label_match else "",
                "description": desc_match.group(1) if desc_match else result[:100],
            }

        # Fallback - VŽDYCKY vrátí všechny klíče
        fallback["description"] = result[:100]
        return fallback
    except Exception as e:
        fallback["description"] = str(e)
        return fallback


def _extract_hue_histogram(img_path, bins=36, crop_pct=0.30, sat_threshold=0.25, res=128) -> list:
    """Extrahuje histogram Hue kanálu z HSV prostoru.
    Vysoký saturation threshold (0.25) odfiltruje pozadí a nevýrazné oblasti,
    zachová jen sytě barevné pixely (příze) — ty co rozlišují produkty.
    Offline: 7/8 správných párů na testovacích čepicích."""
    try:
        from PIL import Image
        img = Image.open(img_path).convert("RGB")
        w, h = img.size
        img = img.crop((int(w*crop_pct), int(h*crop_pct), int(w*(1-crop_pct)), int(h*(1-crop_pct))))
        img = img.resize((res, res))
        pixels = list(img.getdata())
        
        hist = [0] * bins
        valid = 0
        
        for r, g, b in pixels:
            r_n, g_n, b_n = r/255.0, g/255.0, b/255.0
            mx = max(r_n, g_n, b_n)
            mn = min(r_n, g_n, b_n)
            diff = mx - mn
            sat = diff / mx if mx > 0 else 0
            
            # Přeskoč šedé, bílé, černé a nízko-saturované pixely
            if sat < sat_threshold or mx < 0.08:
                continue
            valid += 1
            
            if diff == 0:
                h_val = 0
            elif mx == r_n:
                h_val = (60 * ((g_n - b_n) / diff) + 360) % 360
            elif mx == g_n:
                h_val = (60 * ((b_n - r_n) / diff) + 120) % 360
            else:
                h_val = (60 * ((r_n - g_n) / diff) + 240) % 360
            
            bin_idx = int(h_val / (360 / bins)) % bins
            hist[bin_idx] += 1
        
        if valid > 0:
            hist = [h / valid for h in hist]
        return hist
    except Exception:
        return None


def _hue_distance(h1: list, h2: list) -> float:
    """Chi-squared vzdálenost mezi dvěma hue histogramy. Menší = podobnější."""
    if not h1 or not h2 or len(h1) != len(h2):
        return 9999.0
    dist = 0.0
    for a, b in zip(h1, h2):
        if a + b > 0:
            dist += (a - b) ** 2 / (a + b)
    return dist


# ── VYTVOŘENÍ PRODUKTU ─────────────────────────────────────────────────────────────────────

def _resolve_attribute_name(product_name: str) -> str:
    """
    Ověří existující atributy ve WooCommerce a vrátí správný název.
    Pokud 'Barva' už existuje a je použitá jinými produkty,
    vytvoří unikátní název (např. 'Barva čepic').
    """
    from tools.woocommerce import wc_auth, WC_URL
    import httpx
    
    try:
        # Načti globální atributy
        r = httpx.get(
            f"{WC_URL}/wp-json/wc/v3/products/attributes",
            auth=wc_auth(),
            timeout=15,
        )
        r.raise_for_status()
        attributes = r.json()
        
        existing_names = [a["name"] for a in attributes]
        print(f"🔍 Existující atributy: {existing_names}")
        
        if "Barva" not in existing_names:
            # Barva neexistuje → použij ji
            print(f"✅ Atribut 'Barva' volný — používám")
            return "Barva"
        
        # Barva existuje → zkontroluj jestli je to problém
        # Najdi ID atributu Barva
        barva_attr = next(a for a in attributes if a["name"] == "Barva")
        attr_id = barva_attr["id"]
        
        # Kolik produktů ji používá? (Check terms/options)
        r2 = httpx.get(
            f"{WC_URL}/wp-json/wc/v3/products/attributes/{attr_id}/terms",
            auth=wc_auth(),
            timeout=15,
        )
        terms = r2.json() if r2.status_code == 200 else []
        
        if terms:
            # Barva se aktivně používá → vytvoř unikátní název
            # Mapování product_name na česky genitiv pro hezký název
            genitiv_map = {
                "Čepice": "čepic",
                "Pásek": "pásků",
                "Tričko": "triček",
                "Čelenka": "čelenek",
                "Klíčenka": "klíčenek",
                "Taška": "tašek",
                "Produkt": "produktu",
            }
            suffix = genitiv_map.get(product_name, product_name.lower())
            unique_name = f"Barva {suffix}"
            
            # Ověř že ani tento název neexistuje
            if unique_name in existing_names:
                print(f"✅ Atribut '{unique_name}' už existuje — používám")
                return unique_name
            
            print(f"⚠️  Atribut 'Barva' už existuje ({len(terms)} hodnot) → používám '{unique_name}'")
            return unique_name
        else:
            # Barva existuje ale nemá žádné termy → klidně ji použij
            print(f"✅ Atribut 'Barva' existuje ale prázdný — používám")
            return "Barva"
        
    except Exception as e:
        print(f"⚠️  Nelze ověřit atributy ({e}) — používám 'Barva'")
        return "Barva"


def create_product_from_analysis(analysis: dict, color_options: list = None, price: str = "299.00") -> int:
    """
    Vytvoří nový VARIABILNÍ produkt ve WooCommerce na základě analýzy obrázku.
    Automaticky ověří název atributu (Barva vs. Barva čepic) aby nedošlo ke kolizi.
    
    Args:
        analysis: Dict z analyze_image()
        color_options: Seznam barev pro atribut (např. ["modrá", "červená"])
        price: Výchozí cena
    
    Returns:
        ID nového produktu
    """
    from tools.woocommerce import wc_auth, WC_URL
    import httpx
    
    product_type = analysis.get("product_type", "other")
    description = analysis.get("description", "Produkt rozpoznaný z obrázku")
    
    # Mapování typů na názvy
    type_names = {
        "belt": "Pásek",
        "t-shirt": "Tričko",
        "hat": "Čepice",
        "headband": "Čelenka",
        "keychain": "Klíčenka",
        "bag": "Taška",
        "other": "Produkt"
    }
    
    name = type_names.get(product_type, product_type.capitalize() if product_type else "Produkt")
    
    # Ověř správný název atributu (Barva vs. Barva čepic)
    attr_name = _resolve_attribute_name(name)
    
    # Připrav options pro atribut
    options = color_options if color_options else []
    
    # Vytvoř VARIABILNÍ produkt s atributem + všechny barvy
    payload = {
        "name": name,
        "type": "variable",
        "description": description,
        "status": "draft",
        "attributes": [
            {
                "name": attr_name,
                "visible": True,
                "variation": True,
                "options": options,
            }
        ],
    }
    
    print(f"🏭 Vytvářím variabilní produkt: {name} | atribut: {attr_name} | barvy: {options}")
    
    try:
        r = httpx.post(
            f"{WC_URL}/wp-json/wc/v3/products",
            auth=wc_auth(),
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        product = r.json()
        # Ulož attr_name do produktu pro pozdější použití při vytváření variant
        product["_attr_name"] = attr_name
        print(f"✅ Vytvořen VARIABILNÍ produkt: {name} (ID: {product['id']}) | atribut: {attr_name}")
        return product["id"], attr_name
    except Exception as e:
        print(f"Chyba při vytváření produktu: {e}")
        return None, "Barva"


# ── VYTVOŘENÍ VARIANT ─────────────────────────────────────────────────────────

def create_variants_from_colors(product_id: int, color_data: list, attr_name: str = "Barva", price: str = "299.00") -> dict:
    """
    Vytvoří varianty produktu podle barev z fotek.
    
    Args:
        product_id: ID produktu
        color_data: Seznam dictů s 'color', 'color_czech', 'variant_label'
        attr_name: Název atributu (např. 'Barva' nebo 'Barva čepic')
        price: Cena variant
    
    Returns:
        Slovník mapující { 'variant_label': variant_id }
    """
    from tools.woocommerce import create_variation
    
    variants = {}
    seen_labels = set()
    
    for data in color_data:
        # Použij variant_label, nebo fallback na color_czech
        label = data.get("variant_label") or data.get("color_czech", "neznámá")
        
        # Přeskoči chybné položky
        if not label or label == "neznámá":
            continue
        
        if label in seen_labels:
            continue
        seen_labels.add(label)
        
        try:
            variant = create_variation(
                product_id=product_id,
                attributes={attr_name: label},
                price=price,
                stock=10  # Výchozí sklad
            )
            variants[label] = variant["id"]
            print(f"✅ Vytvořena varianta: {label} (ID: {variant['id']})")
        except Exception as e:
            print(f"⚠️  Chyba při vytváření varianty {label}: {e}")
    
    return variants


# ── KOMPRESE OBRÁZKU ─────────────────────────────────────────────────────────

def compress_image(
    input_path: str,
    output_path: str = None,
    max_width: int = 1200,
    quality: int = 85,
    format: str = "WEBP",
) -> dict:
    """
    Zkomprimuje obrázek pomocí Pillow.

    Args:
        input_path: Cesta k původnímu obrázku
        output_path: Cesta k výstupu (None = přepíše originál)
        max_width: Maximální šířka v pixelech
        quality: Kvalita 1-100 (85 = dobrý poměr kvalita/velikost)
        format: WEBP / JPEG / PNG

    Returns:
        dict s original_size, compressed_size, ratio, output_path
    """
    try:
        from PIL import Image
    except ImportError:
        return {"error": "Pillow není nainstalován. Spusť: pip install Pillow"}

    input_path = Path(input_path)
    if not output_path:
        output_path = input_path.with_suffix(f".{format.lower()}")
    else:
        output_path = Path(output_path)

    original_size = input_path.stat().st_size

    with Image.open(input_path) as img:
        # Konvertuj na RGB (WebP nepodporuje RGBA)
        if img.mode in ("RGBA", "P") and format == "WEBP":
            img = img.convert("RGB")

        # Zmenši pokud je větší než max_width
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height))

        # Ulož
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, format=format, quality=quality, optimize=True)

    compressed_size = output_path.stat().st_size
    saving = round((1 - compressed_size / original_size) * 100, 1)

    return {
        "ok": True,
        "original_size": f"{original_size // 1024} KB",
        "compressed_size": f"{compressed_size // 1024} KB",
        "saving": f"{saving}%",
        "output_path": str(output_path),
        "dimensions": f"{img.width}x{img.height}",
    }


# ── NAHRÁNÍ DO WORDPRESSU ─────────────────────────────────────────────────────

def upload_image_to_wp(image_path: str, alt_text: str = "") -> int:
    """Nahraje obrázek do WordPress Media Library. Vrátí media ID."""
    image_path = Path(image_path)
    with open(image_path, "rb") as f:
        data = f.read()

    ext = image_path.suffix.lower().replace(".", "")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()

    r = httpx.post(
        f"{WC_URL}/wp-json/wp/v2/media",
        headers={
            "Authorization": f"Basic {token}",
            "Content-Disposition": f'attachment; filename="{image_path.name}"',
            "Content-Type": mime,
        },
        content=data,
        timeout=60,
    )
    r.raise_for_status()
    media_id = r.json()["id"]

    if alt_text:
        httpx.post(
            f"{WC_URL}/wp-json/wp/v2/media/{media_id}",
            headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
            json={"alt_text": alt_text},
            timeout=15,
        )
    return media_id


# ── PŘIŘAZENÍ K VARIANTĚ ──────────────────────────────────────────────────────

def find_matching_variant(product_id: int, color: str):
    """
    Najde variantu produktu podle barvy.
    Vrátí variantu nebo None.
    """
    r = httpx.get(
        f"{WC_URL}/wp-json/wc/v3/products/{product_id}/variations",
        auth=(WC_KEY, WC_SECRET),
        timeout=30,
    )
    variations = r.json()

    color_lower = color.lower()
    for var in variations:
        for attr in var.get("attributes", []):
            if color_lower in attr.get("option", "").lower():
                return var

    return None


def assign_image_to_variant(product_id: int, variation_id: int, media_id: int) -> dict:
    """Přiřadí (hlavní) obrázek k variantě produktu."""
    r = httpx.put(
        f"{WC_URL}/wp-json/wc/v3/products/{product_id}/variations/{variation_id}",
        auth=(WC_KEY, WC_SECRET),
        json={"image": {"id": media_id}},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def assign_gallery_image_to_variant(product_id: int, variation_id: int, media_id: int) -> dict:
    """
    Přiřadí další obrázek do specifické galerie varianty.
    Podporuje plugin: Product Gallery Slider & Additional Variation Images for WooCommerce (ode Codeixer).
    Plugin používá meta klíč 'wavi_value' pro ID dalších fotek oddělené čárkou.
    """
    # Nejdříve načti stávající metadata dané varianty
    r_get = httpx.get(
        f"{WC_URL}/wp-json/wc/v3/products/{product_id}/variations/{variation_id}",
        auth=(WC_KEY, WC_SECRET),
        timeout=30,
    )
    r_get.raise_for_status()
    variation_data = r_get.json()
    
    # Najdi dosavadní hodnotu wavi_value (pokud už nějaké fotky byly přiřazeny)
    meta_data = variation_data.get("meta_data", [])
    current_wavi = ""
    for meta in meta_data:
        if meta.get("key") == "wavi_value":
            current_wavi = meta.get("value", "")
            break
            
    # Přidej nové ID
    if current_wavi:
        new_wavi = f"{current_wavi},{media_id}"
    else:
        new_wavi = str(media_id)
        
    # Ulož zpět nová meta data
    r_put = httpx.put(
        f"{WC_URL}/wp-json/wc/v3/products/{product_id}/variations/{variation_id}",
        auth=(WC_KEY, WC_SECRET),
        json={
            "meta_data": [
                {
                    "key": "wavi_value",
                    "value": new_wavi
                }
            ]
        },
        timeout=30,
    )
    r_put.raise_for_status()
    return r_put.json()


def assign_image_to_product(product_id: int, media_id: int) -> dict:
    """Přiřadí obrázek přímo k produktu (jako hlavní nebo galerie)."""
    # Načti existující obrázky
    r = httpx.get(f"{WC_URL}/wp-json/wc/v3/products/{product_id}", auth=(WC_KEY, WC_SECRET), timeout=30)
    product = r.json()
    existing = product.get("images", [])
    existing_ids = [{"id": img["id"]} for img in existing]

    # Přidej nový
    all_images = existing_ids + [{"id": media_id}]

    r2 = httpx.put(
        f"{WC_URL}/wp-json/wc/v3/products/{product_id}",
        auth=(WC_KEY, WC_SECRET),
        json={"images": all_images},
        timeout=30,
    )
    r2.raise_for_status()
    return {"ok": True, "total_images": len(all_images)}


# ── HLAVNÍ FUNKCE ─────────────────────────────────────────────────────────────

def process_product_image(
    image_path: str,
    product_id: int = None,
    pre_analysis: dict = None,
    variant_id: int = None,
    is_variant_primary: bool = False
) -> dict:
    """
    Kompletní zpracování produktové fotky. Může přijmout předem hotovou analýzu.
    
    Args:
        image_path: Cesta k fotce
        product_id: ID produktu ve WooCommerce
        pre_analysis: Již vypočtená analýza (vyhne se dvojímu volání Moondream)
        variant_id: Specifické ID varianty, kam se má fotka přiřadit
        is_variant_primary: Je toto hlavní fotka varianty? (Ostatní jdou do galerie)
    """
    print(f"🔍 Zpracovávám fotku: {image_path}")

    # 1. Rozpoznání (analyzuj znovu, pouze pokud nemáme předchozí analýzu)
    if pre_analysis:
        analysis = pre_analysis
        print("✅ Používám předem hotovou analýzu pro tuto fotku.")
    else:
        analysis = analyze_image(image_path)
    
    if "error" in analysis:
        return {"ok": False, "step": "analyze", "error": analysis["error"]}

    print(f"✅ Rozpoznáno: {analysis.get('product_type')} | barva: {analysis.get('color_czech')}")
    print(f"   Popis: {analysis.get('description')}")

    # 2. Komprese (přeskoč pokud už je WebP)
    input_ext = Path(image_path).suffix.lower()
    if input_ext == ".webp":
        compressed_path = image_path
        compress_result = {"ok": True, "saving": "přeskočeno (už WebP)"}
        print(f"⏭  Přeskakuji kompresi — soubor je už WebP")
    else:
        compressed_path = str(Path(image_path).with_suffix(".webp"))
        compress_result = compress_image(image_path, compressed_path)
        if "error" in compress_result:
            print(f"⚠️  Komprese selhala: {compress_result['error']} — používám originál")
            compressed_path = image_path
        else:
            print(f"✅ Zkomprimováno: {compress_result['original_size']} → {compress_result['compressed_size']} (ušetřeno {compress_result['saving']})")

    # 3. Nahrání do WP
    alt_text = analysis.get("description", "")
    print(f"📤 Nahrávám do WordPress...")
    try:
        media_id = upload_image_to_wp(compressed_path, alt_text)
        print(f"✅ Nahráno (media ID: {media_id})")
    except Exception as e:
        return {"ok": False, "step": "upload", "error": str(e)}

    # 4. Přiřazení k produktu/variantě
    result = {
        "ok": True,
        "analysis": analysis,
        "media_id": media_id,
        "compressed": compress_result,
    }

    if product_id:
        if variant_id:
            # Nová Grouping logika
            if is_variant_primary:
                # Hlavní fotka varianty
                assign_image_to_variant(product_id, variant_id, media_id)
                # NEDÁVÁME už rovnou do globální galerie (aby nebyl bordel). Jen k variantě.
                result["assigned_to"] = f"varianta {variant_id} (hlavní)"
                print(f"✅ Přiřazeno k variantě {variant_id} jako hlavní náhled")
            else:
                # Ostatní fotky pro danou variantu -> DO GALERIE VARIANTY přes WAVI plugin!
                assign_gallery_image_to_variant(product_id, variant_id, media_id)
                result["assigned_to"] = f"varianta {variant_id} (galerie pluginu)"
                print(f"✅ Přidáno do Codeixer plugin galerie u varianty {variant_id}")
        else:
            # Původní Fallback logika: hledej podle názvu barvy
            color = analysis.get("variant_label") or analysis.get("color_czech", "")
            variant = find_matching_variant(product_id, color)

            if variant:
                assign_image_to_variant(product_id, variant["id"], media_id)
                # Oprav i fallback pro Codeixer - další u stejné barvy půjdou jako hlavní, to API přemaže, takže by se mělo ideálně v budoucnu předělat, 
                # ale pro teď je jistější poslat starší kód tak jak byl. (Pádá tam jen nouze zvenku)
                assign_image_to_product(product_id, media_id)
                result["assigned_to"] = f"varianta {variant['id']} (barva: {color})"
                print(f"✅ Přiřazeno k variantě {variant['id']}")
            else:
                assign_image_to_product(product_id, media_id)
                result["assigned_to"] = f"produkt {product_id} (galerie)"
                print(f"✅ Přidáno do hlavní galerie produktu {product_id}")

    return result


def _analyze_single(img_path) -> Optional[dict]:
    """Wrapper pro paralelní Moondream analýzu jedné fotky."""
    name = Path(img_path).name
    print(f"🔍 Analyzuji {name}...")
    analysis = analyze_image(str(img_path))
    if "error" in analysis:
        print(f"⚠️  Chyba analýzy {name}: {analysis['error']}")
        return None
    print(f"✅ Analyzováno {name}: {analysis.get('product_type')} / {analysis.get('color_czech')}")
    return {"path": img_path, "analysis": analysis}


def _process_single(
    img_path,
    product_id: int,
    pre_analysis: dict = None,
    variant_id: int = None,
    is_variant_primary: bool = False
) -> dict:
    """Wrapper pro paralelní zpracování (komprese + upload + přiřazení)."""
    print(f"\n--- {Path(img_path).name} ---")
    result = process_product_image(
        str(img_path),
        product_id=product_id,
        pre_analysis=pre_analysis,
        variant_id=variant_id,
        is_variant_primary=is_variant_primary
    )
    result["file"] = Path(img_path).name
    return result


def process_folder(folder_path: str, product_id: int = None, auto_create: bool = True, max_workers: int = 4, webp_only: bool = False) -> list:
    """
    Zpracuje všechny fotky ve složce PARALELNĚ.
    Podporuje Dual-Folder strategii (podsložky `detaily/` a `galerie/`).
    Detaily zakládají varianty, Galerie se k nim přiřazuje podle názvu.
    Pokud podsložky neexistují, spracuje celý adresář původním (ImageHash) způsobem.
    
    Args:
        folder_path: Cesta ke složce s fotkami
        product_id: ID existujícího produktu (None = auto vytvoření)
        auto_create: Zda automaticky vytvořit produkt a varianty
        max_workers: Počet paralelních vláken (výchozí 4)
        webp_only: True = zpracuj POUZE .webp soubory (přeskoč originály)
    
    Returns:
        Seznam výsledků
    """
    start_time = time.time()
    folder = Path(folder_path)
    
    # Detekce Dual-Folder strategie
    details_dir = folder / "detaily"
    gallery_dir = folder / "galerie"
    is_dual_folder = details_dir.exists() and gallery_dir.exists()
    
    if is_dual_folder:
        print(f"📁 Dual-Folder mód detekován. Vytvářím varianty z {details_dir.name} a galerie z {gallery_dir.name}")
        search_dirs = [details_dir, gallery_dir]
    else:
        print(f"📁 Standardní mód pro složku (vyžívám ImageHash pro deduplikaci)")
        search_dirs = [folder]

    # Posbíráme všechny fotky (i z podsložek, nebo jen hlavní)
    images = []
    gallery_images = set() # Pro udržení přehledu, co je v galerii (bypassing AI)
    
    for sdir in search_dirs:
        if not sdir.exists(): continue
            
        if webp_only:
            found = list(sdir.glob("*.webp"))
        else:
            jpg = list(sdir.glob("*.jpg")) + list(sdir.glob("*.jpeg"))
            png = list(sdir.glob("*.png"))
            webp = list(sdir.glob("*.webp"))
            
            originals = jpg + png
            original_stems = {img.stem for img in originals}
            unique_webp = [w for w in webp if w.stem not in original_stems]
            found = originals + unique_webp
            if len(webp) > len(unique_webp):
                skipped = len(webp) - len(unique_webp)
                print(f"⏭  Přeskočeno {skipped} WebP duplikátů ve {sdir.name} (originály existují)")
                
        images.extend(found)
        if sdir.name == "galerie":
            gallery_images.update([str(img) for img in found])

    if not images:
        print(f"❌ Žádné fotky nenalezeny")
        return []

    print(f"📁 Nalezeno celkem {len(images)} fotek")
    print(f"⚡ Paralelní zpracování ({max_workers} vláken)")
    
    # Pro auto-matching musíme analyzovat všechny fotky (i galerii)
    print(f"\n── Fáze 1: Analýza ({len(images)} fotek paralelně) ──")
    t1 = time.time()
    analyses = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_analyze_single, img): img for img in images}
        for future in as_completed(futures):
            result = future.result()
            if result:
                analyses.append(result)
    
    t1_elapsed = time.time() - t1
    print(f"⏱  Analýza hotová: {len(analyses)}/{len(images)} úspěšně za {t1_elapsed:.1f}s")
    
    if not analyses:
        print("❌ Žádná fotka nebyla úspěšně analyzována")
        return []
    
    if not analyses:
        print("❌ Žádná fotka nebyla úspěšně analyzována")
        return []
    
    # 2. Auto vytvoření produktu a variant (sekvenční — závisí na API)
    if product_id is None and auto_create:
        print("\n── Fáze 2: Vytvoření produktu + variant ──")
        first_analysis = analyses[0]["analysis"]
        
        color_data = []
        for a in analyses:
            img_path = a["path"]
            analysis = a["analysis"]
            
            # Extrahujeme hue histogram pro matching
            hue_hist = _extract_hue_histogram(img_path)
                
            color_data.append({
                "path": img_path,
                "color": analysis.get("color", "unknown"),
                "color_czech": analysis.get("color_czech", "neznámá"),
                "variant_label": analysis.get("variant_label", ""),
                "hue_hist": hue_hist,
                "is_gallery": str(img_path) in gallery_images
            })
        
        # Unikátní barvy/labely pro atribut vytažené POUZE z `detaily/`
        seen_labels = set()
        unique_colors_czech = []
        details_data = [cd for cd in color_data if not cd["is_gallery"]]
        
        if not details_data and not is_dual_folder:
            details_data = color_data
        
        valid_labels_found = False
        
        # Pojistka pro Dual-Folder: v detaily/ chceme vždy poměr 1 detail = 1 nová varianta.
        for idx, cd in enumerate(details_data):
            color = cd.get("color", "unknown")
            label = cd.get("variant_label") or cd.get("color_czech", "neznámá")
            
            # Pokud AI selhala u detailu, musíme mu nějaký label dát, abychom zaručili vytvoření varianty v WooCommerce!
            if label == "neznámá" or not label:
                label = f"Neznámá barva ({idx+1})"
                cd["color"] = f"variant-u-{idx+1}"
                
            valid_labels_found = True
            
            # Pokud label už existuje (AI řeklo dvakrát to samé pro dvě jiné fotky z detailů, např. 'Černá'),
            # násilně je odlišíme, abychom zaručili 1 fotka = 1 varianta.
            original_label = label
            counter = 2
            while label in seen_labels and is_dual_folder:
                label = f"{original_label} ({counter})"
                counter += 1
            
            seen_labels.add(label)
            unique_colors_czech.append(label)
            
            # Uložíme upravený (nebo zachovaný) label zpět do cd
            cd["variant_label"] = label
            cd["color_czech"] = label
            
        # Inteligentní FALLBACK + Shlukování (ImageHash) pro DETAILY (pouze pokud není dual-folder)
        if not valid_labels_found and details_data:
            print(f"⚠️  Žádné barvy nerozpoznány — používám vizuální shlukování (ImageHash) pro tvorbu variant")
            
            clusters = [] 
            variant_counter = 1
            
            for cd in details_data:
                h = cd.get("hash")
                assigned_cluster = None
                
                if h is not None:
                    for cluster in clusters:
                        if cluster["hash"] is not None and h - cluster["hash"] <= 10:
                            assigned_cluster = cluster
                            break
                            
                if assigned_cluster:
                    cd["color"] = f"variant-{assigned_cluster['id']}"
                    cd["color_czech"] = assigned_cluster["label"]
                    cd["variant_label"] = assigned_cluster["label"]
                else:
                    new_label = f"Varianta {variant_counter}"
                    clusters.append({"id": variant_counter, "label": new_label, "hash": h})
                    unique_colors_czech.append(new_label)
                    
                    cd["color"] = f"variant-{variant_counter}"
                    cd["color_czech"] = new_label
                    cd["variant_label"] = new_label
                    variant_counter += 1
        
        print(f"🎨 Varianty ({len(unique_colors_czech)}): {unique_colors_czech}")
        
        # Vytvoř variabilní produkt S VARIANTAMI v atributech
        product_id, attr_name = create_product_from_analysis(first_analysis, color_options=unique_colors_czech)
        if not product_id:
            print("❌ Nepodařilo se vytvořit produkt")
            return []
        
        # Teď vytvoř varianty POUZE na základě detail data a ulož si IDčka 
        # API volání WooCommerce k tvorbě variant pošleme pro unique variant labels
        variants_dict = create_variants_from_colors(product_id, details_data, attr_name=attr_name)
        print(f"✅ Vytvořeno {len(variants_dict)} variant")
        
        # Zmapujeme galerie na vygenerované varianty
        if is_dual_folder:
            print(f"\n── Fáze 2b: Balanced assignment (vizuální fingerprint) ──")
            print(f"📋 Dostupné varianty: {list(variants_dict.keys())}")
            
            gallery_items = [cd for cd in color_data if cd["is_gallery"]]
            
            if gallery_items and details_data:
                # Maximální počet galerií na variantu
                import math
                max_per_variant = math.ceil(len(gallery_items) / len(details_data))
                print(f"📊 {len(gallery_items)} galerií → {len(details_data)} variant (max {max_per_variant}/varianta)")
                
                # Vypočti CELOU matici vzdáleností
                all_pairs = []
                for gi, cd_gal in enumerate(gallery_items):
                    fp_gal = cd_gal["hue_hist"]
                    if fp_gal is None:
                        continue
                    for di, cd_det in enumerate(details_data):
                        fp_det = cd_det["hue_hist"]
                        if fp_det is None:
                            continue
                        dist = _hue_distance(fp_gal, fp_det)
                        all_pairs.append((dist, gi, di))
                
                # Seřaď podle vzdálenosti (nejlepší matche první)
                all_pairs.sort(key=lambda x: x[0])
                
                # Greedy přiřazení s kapacitním limitem
                assigned_gallery = set()  # indexy přiřazených galerií
                variant_counts = {}  # kolik galerií má každý detail index
                
                for dist, gi, di in all_pairs:
                    if gi in assigned_gallery:
                        continue
                    if variant_counts.get(di, 0) >= max_per_variant:
                        continue
                    
                    # Přiřaď!
                    cd_gal = gallery_items[gi]
                    cd_det = details_data[di]
                    assigned_label = cd_det["variant_label"]
                    
                    cd_gal["variant_label"] = assigned_label
                    cd_gal["color_czech"] = assigned_label
                    assigned_gallery.add(gi)
                    variant_counts[di] = variant_counts.get(di, 0) + 1
                    
                    gal_name = Path(cd_gal["path"]).name
                    print(f"  📸 {gal_name} → 🎯 balanced (dist: {dist:.4f}) → varianta '{assigned_label}'")
                
                # Případné nepřiřazené (fallback)
                for gi, cd_gal in enumerate(gallery_items):
                    if gi not in assigned_gallery:
                        cd_gal["variant_label"] = "neznámá"
                        gal_name = Path(cd_gal["path"]).name
                        print(f"  ⚠️  {gal_name} → nepřiřazeno")
                    
    else:
        # Pokud nešlo o auto_create, nemáme variants_dict
        variants_dict = {}

    # 3. PARALELNÍ zpracování (komprese + upload + přiřazení) VŠECH fotek (včetně galerie)
    print(f"\n── Fáze 3: Komprese + Upload ({len(images)} fotek paralelně) ──")
    t3 = time.time()
    
    # Path -> upravený Label (včetně matchingu z galerie na detaily)
    path_to_label = {str(cd["path"]): cd["variant_label"] for cd in color_data}

    # Príprava úkolů
    tasks = []
    
    for img_path in images:
        str_path = str(img_path)
        is_gallery_image = str_path in gallery_images
        
        raw_a = next((a["analysis"] for a in analyses if str(a["path"]) == str_path), {})
        pre_analysis = raw_a
        
        # Label získáme tak, jak ho vypočítala a svázala Fáze 2
        label = path_to_label.get(str_path, "Varianta 1")
        
        # Ikony z `detaily/` se stávají primární fotkou (zapadnu do WooCommerce na display)
        # Ostatní z `galerie/` jsou false -> padnou do WAVI pluginu
        is_primary = not is_gallery_image
        
        # Zpět na ID (vždy jen pro hlavní fotky)
        variant_id = variants_dict.get(label)
        
        tasks.append((img_path, pre_analysis, variant_id, is_primary))
        
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for img_path, pre_analysis, var_id, is_pri in tasks:
            futures.append(executor.submit(
                _process_single, 
                img_path, 
                product_id, 
                pre_analysis, 
                var_id, 
                is_pri
            ))
            
        for future in as_completed(futures):
            results.append(future.result())
    
    t3_elapsed = time.time() - t3
    print(f"⏱  Upload hotový za {t3_elapsed:.1f}s")

    ok = sum(1 for r in results if r.get("ok"))
    total_elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"✅ Zpracováno {ok}/{len(images)} fotek úspěšně")
    print(f"⏱  Celkový čas: {total_elapsed:.1f}s (analýza: {t1_elapsed:.1f}s, upload: {t3_elapsed:.1f}s)")
    if product_id:
        print(f"📦 Produkt: https://brandnewbrand.cz/produkt/?p={product_id}")
    return results


# ── TEST ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Použití:")
        print("  python3 tools/image_processor.py /cesta/k/fotce.jpg [product_id]")
        print("  python3 tools/image_processor.py /cesta/ke/slozce/ [product_id]")
        sys.exit(1)

    path = sys.argv[1]
    pid = int(sys.argv[2]) if len(sys.argv) > 2 else None

    if Path(path).is_dir():
        process_folder(path, pid)
    else:
        result = process_product_image(path, pid)
        print(f"\nVýsledek: {json.dumps(result, ensure_ascii=False, indent=2)}")
