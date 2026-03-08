"""
Chytré přepínání modelů – zkusí cloud, při chybě přepne na lokální.
Pamatuje si stav (cloud dostupný / nedostupný) aby zbytečně nezkoušel.
"""

import os
import time
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Stav cloud dostupnosti – pamatuje se po dobu běhu
_cloud_status = {
    "available": None,      # None = neznámý, True/False = otestovaný
    "last_check": 0,
    "retry_after": 3600,    # Za hodinu zkus cloud znovu
}


def _test_cloud_model(model_name: str) -> bool:
    """Otestuje jestli cloud model odpovídá."""
    try:
        model = ChatOllama(
            model=model_name,
            base_url=OLLAMA_URL,
            temperature=0,
        )
        # Krátký testovací dotaz
        model.invoke([HumanMessage(content="Hi")], config={"timeout": 5})
        return True
    except Exception:
        return False


def get_best_model(prefer_cloud: bool = True) -> ChatOllama:
    """
    Vrátí nejlepší dostupný model.
    
    Logika:
    1. Pokud prefer_cloud a cloud nebyl nedávno zakázán → zkus cloud
    2. Pokud cloud selže nebo je zakázán → použij llama3.1:8b
    3. Každou hodinu znovu zkusí cloud (limit se mohl obnovit)
    """
    cloud_model = os.getenv("MODEL_ORCHESTRATOR_CLOUD", "qwen3.5:cloud")
    local_model = os.getenv("MODEL_FAST", "llama3.1:8b")
    now = time.time()

    # Zkus cloud znovu po uplynutí retry_after
    if _cloud_status["available"] is False:
        elapsed = now - _cloud_status["last_check"]
        if elapsed > _cloud_status["retry_after"]:
            _cloud_status["available"] = None  # Reset – zkusíme znovu

    if prefer_cloud and _cloud_status["available"] is not False:
        if _cloud_status["available"] is None:
            # Otestuj cloud
            is_up = _test_cloud_model(cloud_model)
            _cloud_status["available"] = is_up
            _cloud_status["last_check"] = now

            if is_up:
                print(f"☁️  Cloud model [{cloud_model}] dostupný")
            else:
                print(f"⚡ Cloud nedostupný – přepínám na [{local_model}]")

        if _cloud_status["available"]:
            return ChatOllama(
                model=cloud_model,
                base_url=OLLAMA_URL,
                temperature=0.3,
            )

    # Lokální fallback
    return ChatOllama(
        model=local_model,
        base_url=OLLAMA_URL,
        temperature=0.3,
    )


def get_model_status() -> dict:
    """Vrátí aktuální stav modelů pro diagnostiku."""
    return {
        "cloud_available": _cloud_status["available"],
        "last_check": _cloud_status["last_check"],
        "orchestrator_cloud": os.getenv("MODEL_ORCHESTRATOR_CLOUD"),
        "orchestrator_local": os.getenv("MODEL_FAST"),
        "coding": os.getenv("MODEL_CODING"),
        "embed": os.getenv("MODEL_EMBED"),
    }
