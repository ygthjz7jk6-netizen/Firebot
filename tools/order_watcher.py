"""
Order Watcher — automatická kontrola nových objednávek WooCommerce
Kontroluje 3× denně (ráno, poledne, večer) a na přímý dotaz.
"""

import os
import sys
import json
import threading
import time
from datetime import datetime

base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEEN_ORDERS_FILE = os.path.join(base_dir, "memory", "seen_orders.json")


def _load_seen_ids() -> set:
    """Načte ID objednávek, které agent již viděl."""
    try:
        with open(SEEN_ORDERS_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_seen_ids(ids: set):
    """Uloží aktuální sadu viděných ID."""
    os.makedirs(os.path.dirname(SEEN_ORDERS_FILE), exist_ok=True)
    with open(SEEN_ORDERS_FILE, "w") as f:
        json.dump(sorted(ids), f)


def check_new_orders() -> list:
    """
    Porovná aktuální objednávky se seznamem viděných.
    Vrátí seznam NOVÝCH objednávek (dict), označí je jako viděné.
    """
    try:
        from tools.woocommerce import list_orders
        orders = list_orders(status="any", per_page=50)
    except Exception as e:
        return []

    seen = _load_seen_ids()
    new_orders = [o for o in orders if str(o.get("id")) not in seen]

    # Označ všechny jako viděné
    all_ids = seen | {str(o.get("id")) for o in orders}
    _save_seen_ids(all_ids)

    return new_orders


def format_orders_summary(all_orders: list, new_ids: set) -> str:
    """Naformátuje přehled objednávek — nové jsou označeny ⭐."""
    if not all_orders:
        return "📭 Žádné objednávky v e-shopu."

    new_count = sum(1 for o in all_orders if str(o.get("id")) in new_ids)
    header = f"🛒 **Objednávky** ({len(all_orders)} celkem"
    if new_count:
        header += f", z toho {new_count} nových ⭐"
    header += "):"

    lines = [header]
    for o in all_orders:
        billing = o.get("billing", {})
        name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip() or "Anonymní"
        total = o.get("total", "?")
        status = o.get("status", "?")
        order_id = o.get("id", "?")
        date_raw = o.get("date_created", "")
        date = date_raw[:16].replace("T", " ") if date_raw else "?"
        star = "⭐" if str(order_id) in new_ids else "  "
        lines.append(f"  {star} #{order_id} | {name} | {total} Kč | {status} | {date}")

    return "\n".join(lines)


def _is_unshipped_packeta(order_data: dict) -> bool:
    """Zjistí, zda objednávka čeká na podání do Zásilkovny (nemá packet_id)."""
    lines = order_data.get("shipping_lines", [])
    if not lines:
        return True # Neni to zasilkovna, asi neco jineho (nefiltrujeme)
        
    packeta = lines[0].get("packeta")
    if packeta:
        packet_id = packeta.get("packet_id")
        # Pokud má packet_id delší než 1, je už odesláno
        if packet_id and len(str(packet_id)) > 1:
            return False
            
    return True


def check_new_orders() -> list:
    """
    Porovná aktuální objednávky se seznamem viděných.
    Vrátí seznam NOVÝCH objednávek (dict), označí je jako viděné.
    Nyní filtruje pouze neodeslané Zásilkovna objednávky.
    """
    try:
        from tools.woocommerce import list_orders
        orders = list_orders(status="any", per_page=50)
    except Exception as e:
        return []

    # Filtr: Pouze neodeslané
    orders = [o for o in orders if _is_unshipped_packeta(o)]

    seen = _load_seen_ids()
    new_orders = [o for o in orders if str(o.get("id")) not in seen]

    # Označ všechny zobrazené jako viděné
    all_ids = seen | {str(o.get("id")) for o in orders}
    _save_seen_ids(all_ids)

    return new_orders


def check_orders_on_demand(per_page: int = 20) -> str:
    """
    On-demand kontrola — vždy zobrazí neodeslané objednávky.
    Nové (dosud neviděné) jsou označeny ⭐.
    """
    try:
        from tools.woocommerce import list_orders
        # Načteme víc, abychom po odfiltrování měli rozumný počet
        orders = list_orders(status="any", per_page=max(50, per_page * 2))
    except Exception as e:
        return f"❌ Chyba při načítání objednávek: {e}"

    # Filtr: Pouze neodeslané
    orders = [o for o in orders if _is_unshipped_packeta(o)]
    orders = orders[:per_page] # Oříznout na požadovaný počet

    seen = _load_seen_ids()
    new_ids = {str(o.get("id")) for o in orders if str(o.get("id")) not in seen}

    # Ulož všechny jako viděné
    all_ids = seen | {str(o.get("id")) for o in orders}
    _save_seen_ids(all_ids)

    return format_orders_summary(orders, new_ids)


def _scheduler_loop(console, times: list):
    """Daemon smyčka — každou minutu kontroluje jestli je čas na check."""
    last_run = {}
    while True:
        now = datetime.now().strftime("%H:%M")
        for t in times:
            if now == t and last_run.get(t) != datetime.now().date():
                last_run[t] = datetime.now().date()
                try:
                    new_orders = check_new_orders()
                    # For scheduler, we only care about truly new orders, not a full summary
                    if new_orders:
                        new_ids = {str(o.get("id")) for o in new_orders}
                        msg = format_orders_summary(new_orders, new_ids)
                    else:
                        msg = "✅ Žádné nové objednávky."
                    console.print(f"\n[bold yellow]⏰ Automatická kontrola ({t}):[/bold yellow]")
                    console.print(f"[cyan]{msg}[/cyan]\n")
                    console.print("[bold green]Ty:[/bold green] ", end="")  # Re-prompt
                except Exception as e:
                    console.print(f"\n[red]❌ Chyba při kontrole objednávek: {e}[/red]\n")
        time.sleep(30)  # Kontroluje každých 30 sekund


def start_order_scheduler(console, times: list = None):
    """
    Spustí daemon thread pro automatickou kontrolu objednávek.
    
    Args:
        console: Rich Console instance
        times: Seznam časů ve formátu HH:MM, default ["08:00", "12:00", "20:00"]
    """
    if times is None:
        times = ["08:00", "12:00", "20:00"]

    thread = threading.Thread(
        target=_scheduler_loop,
        args=(console, times),
        daemon=True,
        name="OrderWatcher",
    )
    thread.start()
    times_str = ", ".join(times)
    console.print(f"[dim]🔔 Order watcher spuštěn (kontrola v {times_str})[/dim]")
    return thread
