"""
Paměťový systém agenta – ChromaDB + mxbai-embed-large
Ukládá poznatky, úkoly, brand info. Podporuje organické zapomínání.
"""

import os
import math
import chromadb
from typing import Optional, List
from langchain_ollama import OllamaEmbeddings
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Inicializace embeddings (lokální model)
embeddings = OllamaEmbeddings(
    model=os.getenv("MODEL_EMBED", "mxbai-embed-large:latest"),
    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
)

# ChromaDB klient
try:
    chroma_client = chromadb.HttpClient(
        host=os.getenv("CHROMA_HOST", "localhost"),
        port=int(os.getenv("CHROMA_PORT", 8000)),
    )
    print("✅ ChromaDB připojeno přes HTTP")
except Exception:
    chroma_client = chromadb.PersistentClient(path="./chroma_data")
    print("✅ ChromaDB spuštěno lokálně (./chroma_data)")

collection = chroma_client.get_or_create_collection(
    name=os.getenv("CHROMA_COLLECTION", "agent_memory"),
    metadata={"hnsw:space": "cosine"},
)

# Triviální fráze, které nemá cenu ukládat
_TRIVIAL_PATTERNS = [
    "vytvárim", "vytvářím", "zpracováno", "produkt vytvoren", "draft vytvořen",
    "předávám specialistovi", "přemýšlím", "ok", "hotovo", "done",
]


def _recency_weight(timestamp_str: str) -> float:
    """Vypočítá váhu čerstvosti: 1.0 = dneska, klesá k 0.3 za 30+ dní."""
    try:
        ts = datetime.fromisoformat(timestamp_str)
        age_days = (datetime.now() - ts).total_seconds() / 86400
        # Sigmoid: 1.0 pro nové, ~0.5 pro 14 dní, ~0.3 pro 30+ dní
        return max(0.3, 1.0 / (1.0 + math.exp((age_days - 14) / 7)))
    except Exception:
        return 0.5  # Neznámé timestamp = střední váha


# ═══════════════════════════════════════════════════════════
# CORE MEMORY
# ═══════════════════════════════════════════════════════════

def save_memory(content: str, category: str = "general", metadata: dict = None) -> Optional[str]:
    """Uloží poznatek do dlouhodobé paměti.
    Přeskočí triviální obsah a duplicity (cosine > 0.85)."""
    if len(content) < 30:
        return None
    content_lower = content.lower()
    if any(p in content_lower for p in _TRIVIAL_PATTERNS):
        return None

    embedding = embeddings.embed_query(content)

    # Dedup check
    try:
        existing = collection.query(query_embeddings=[embedding], n_results=1)
        if existing["distances"][0]:
            if existing["distances"][0][0] < 0.15:
                return None
    except Exception:
        pass

    timestamp = datetime.now().isoformat()
    doc_id = f"{category}_{timestamp}"

    meta = {
        "category": category,
        "timestamp": timestamp,
        "last_accessed": timestamp,
        **(metadata or {}),
    }

    collection.add(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[content],
        metadatas=[meta],
    )
    return doc_id


def search_memory(query: str, n_results: int = 5, category: str = None, min_relevance: float = 0.3):
    """Vyhledá relevantní vzpomínky. Váhuje čerstvostí (novější = vyšší skóre)."""
    query_embedding = embeddings.embed_query(query)
    where_filter = {"category": category} if category else None

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where_filter,
    )

    if not results["documents"][0]:
        return []

    memories = []
    ids_to_update = []

    for doc, meta, distance, doc_id in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
        results["ids"][0],
    ):
        cosine_relevance = 1 - distance
        # Váha čerstvosti: nové vzpomínky mají bonus
        recency = _recency_weight(meta.get("timestamp", ""))
        weighted_relevance = round(cosine_relevance * (0.7 + 0.3 * recency), 3)

        if weighted_relevance < min_relevance:
            continue

        memories.append({
            "content": doc,
            "category": meta.get("category"),
            "timestamp": meta.get("timestamp"),
            "relevance": weighted_relevance,
        })
        ids_to_update.append(doc_id)

    # Aktualizuj last_accessed pro vrácené výsledky
    if ids_to_update:
        now = datetime.now().isoformat()
        try:
            for doc_id in ids_to_update:
                existing = collection.get(ids=[doc_id])
                if existing["metadatas"]:
                    updated_meta = existing["metadatas"][0].copy()
                    updated_meta["last_accessed"] = now
                    collection.update(ids=[doc_id], metadatas=[updated_meta])
        except Exception:
            pass  # Non-critical

    return memories


# ═══════════════════════════════════════════════════════════
# TASK SYSTEM
# ═══════════════════════════════════════════════════════════

def save_task(text: str) -> Optional[str]:
    """Uloží nový úkol."""
    timestamp = datetime.now().isoformat()
    doc_id = f"task_{timestamp}"
    embedding = embeddings.embed_query(text)

    collection.add(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[{
            "category": "task",
            "status": "open",
            "timestamp": timestamp,
            "last_accessed": timestamp,
        }],
    )
    return doc_id


def list_tasks(status: str = "open") -> List[dict]:
    """Vrátí seznam úkolů podle statusu."""
    try:
        results = collection.get(
            where={"$and": [{"category": "task"}, {"status": status}]},
        )
        if not results["documents"]:
            return []

        tasks = []
        for doc, meta, doc_id in zip(
            results["documents"],
            results["metadatas"],
            results["ids"],
        ):
            tasks.append({
                "id": doc_id,
                "text": doc,
                "status": meta.get("status", "open"),
                "created": meta.get("timestamp", ""),
            })
        return tasks
    except Exception:
        return []


def complete_task(query: str) -> Optional[str]:
    """Najde úkol podle dotazu a označí jako done. Vrátí text úkolu."""
    query_embedding = embeddings.embed_query(query)

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=3,
            where={"$and": [{"category": "task"}, {"status": "open"}]},
        )

        if not results["documents"][0]:
            return None

        # Vezmi nejlepší shodu
        best_id = results["ids"][0][0]
        best_doc = results["documents"][0][0]
        best_meta = results["metadatas"][0][0].copy()
        best_meta["status"] = "done"
        best_meta["last_accessed"] = datetime.now().isoformat()

        collection.update(ids=[best_id], metadatas=[best_meta])
        return best_doc

    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# SELECTIVE DELETION & DECAY
# ═══════════════════════════════════════════════════════════

def forget_about(topic: str, max_delete: int = 5) -> int:
    """Smaže vzpomínky o daném tématu. Vrátí počet smazaných."""
    query_embedding = embeddings.embed_query(topic)

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=max_delete,
        )

        if not results["ids"][0]:
            return 0

        # Smaž jen ty s relevancí > 0.4 (aby se nesmazalo něco úplně jiného)
        ids_to_delete = []
        for doc_id, distance in zip(results["ids"][0], results["distances"][0]):
            relevance = 1 - distance
            if relevance > 0.4:
                ids_to_delete.append(doc_id)

        if ids_to_delete:
            collection.delete(ids=ids_to_delete)

        return len(ids_to_delete)

    except Exception:
        return 0


def cleanup_old_memories(max_age_days: int = 90, max_unused_days: int = 30) -> int:
    """Smaže staré nepoužívané vzpomínky. Volat 1× za spuštění."""
    try:
        all_data = collection.get()
        if not all_data["ids"]:
            return 0

        now = datetime.now()
        ids_to_delete = []

        for doc_id, meta in zip(all_data["ids"], all_data["metadatas"]):
            # Přeskoč úkoly — ty nechceme automaticky mazat
            if meta.get("category") == "task":
                continue
            # Přeskoč user preferences — ty jsou důležité
            if meta.get("category") == "user_preference":
                continue

            try:
                created = datetime.fromisoformat(meta.get("timestamp", ""))
                age = (now - created).days

                last_accessed_str = meta.get("last_accessed", meta.get("timestamp", ""))
                last_accessed = datetime.fromisoformat(last_accessed_str)
                unused_days = (now - last_accessed).days

                # Smaž pokud: starší než max_age A nepoužívané déle než max_unused
                if age > max_age_days and unused_days > max_unused_days:
                    ids_to_delete.append(doc_id)
            except Exception:
                continue

        if ids_to_delete:
            collection.delete(ids=ids_to_delete)

        return len(ids_to_delete)

    except Exception:
        return 0


def get_brand_context() -> str:
    """Vrátí brand kontext ze souboru .env (jen pokud je vyplněný)."""
    brand_name = os.getenv('BRAND_NAME', '')
    brand_tone = os.getenv('BRAND_TONE', '')
    brand_audience = os.getenv('BRAND_AUDIENCE', '')

    parts = []
    if brand_name and '[' not in brand_name and brand_name != 'Neznámá':
        parts.append(f"ZNAČKA: {brand_name}")
    if brand_tone and '[' not in brand_tone:
        parts.append(f"TÓN: {brand_tone}")
    if brand_audience and '[' not in brand_audience:
        parts.append(f"CÍLOVÁ SKUPINA: {brand_audience}")

    if not parts:
        return ""

    brand_memories = search_memory("značka brand marketing", n_results=2, category="brand")
    if brand_memories:
        parts.append("\nNaučené poznatky o značce:")
        for m in brand_memories:
            parts.append(f"- {m['content']}")

    return "\n".join(parts)


def get_memory_stats() -> dict:
    """Vrátí statistiky paměti pro diagnostiku."""
    try:
        count = collection.count()
        tasks = list_tasks("open")
        return {
            "total_memories": count,
            "open_tasks": len(tasks),
            "collection": collection.name,
        }
    except Exception as e:
        return {"error": str(e)}

