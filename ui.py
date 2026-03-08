"""
Agent Chat UI — FastAPI + WebSocket server
Spuštění: python ui.py
"""

import os
import sys
import json
import asyncio
import threading
from io import StringIO
from contextlib import redirect_stdout

# Path setup
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

from memory.chroma_memory import (
    save_memory, search_memory, get_memory_stats,
    save_task, list_tasks, complete_task, forget_about,
    cleanup_old_memories
)
from specialists.model_switcher import get_best_model
from dotenv import load_dotenv
from tools.woocommerce import list_orders

load_dotenv()

# Import orchestrator components
from orchestrator import build_agent, AgentState

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

app = FastAPI(title="Firebot Chat UI")

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Build agent once
agent = build_agent()
cleanup_old_memories()


@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/menubar")
async def menubar():
    return FileResponse(os.path.join(static_dir, "menubar.html"))


@app.get("/api/stats")
async def stats():
    try:
        s = get_memory_stats()
        return JSONResponse(s)
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/tasks")
async def tasks():
    try:
        open_tasks = list_tasks("open")
        done_tasks = list_tasks("done")
        return JSONResponse({"open": open_tasks, "done": done_tasks[-5:]})
    except Exception as e:
        return JSONResponse({"error": str(e)})


# Store conversation per connection
conversations = {}

async def broadcast_orders():
    """Poll WooCommerce and send to all connected clients."""
    while True:
        try:
            orders = list_orders(status="processing", per_page=5)
            formatted = []
            for o in orders:
                formatted.append({
                    "id": o["id"],
                    "customer": f"{o['billing']['first_name']} {o['billing']['last_name']}",
                    "products": ", ".join([i["name"] for i in o["line_items"]])
                })
            
            # Send to all
            msg = {"type": "orders_update", "orders": formatted}
            for conn_id in list(conversations.keys()):
                try:
                    ws_obj = conversations[conn_id].get("ws")
                    if ws_obj:
                        await ws_obj.send_json(msg)
                except:
                    pass
        except Exception as e:
            print(f"Error polling orders: {e}")
            
        await asyncio.sleep(60)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    conn_id = id(ws)
    conversations[conn_id] = {
        "history": [],
        "summary": "",
        "ws": ws
    }

    # Send initial stats
    try:
        stats = get_memory_stats()
        tasks = list_tasks("open")
        await ws.send_json({
            "type": "init",
            "stats": stats,
            "tasks": [{"text": t["text"], "status": t["status"]} for t in tasks],
        })
    except Exception:
        pass

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "message":
                user_text = data.get("text", "").strip()
                if not user_text:
                    continue

                conv = conversations[conn_id]
                history = conv["history"]

                # Handle meta commands directly
                text_lower = user_text.lower()

                # Memory stats
                if text_lower in ["paměť", "pamet", "memory", "stats"]:
                    s = get_memory_stats()
                    await ws.send_json({
                        "type": "response",
                        "text": f"🧠 Paměť: {s.get('total_memories', '?')} vzpomínek\n📋 Úkoly: {s.get('open_tasks', 0)} otevřených",
                    })
                    continue

                # Tasks
                if text_lower in ["úkoly", "ukoly", "tasks"]:
                    t = list_tasks("open")
                    if t:
                        task_list = "\n".join(f"{i+1}. {x['text']}" for i, x in enumerate(t))
                        await ws.send_json({"type": "response", "text": f"📋 Otevřené úkoly ({len(t)}):\n{task_list}"})
                    else:
                        await ws.send_json({"type": "response", "text": "📋 Žádné otevřené úkoly."})
                    continue

                if text_lower.startswith("úkol:") or text_lower.startswith("ukol:"):
                    task_text = user_text.split(":", 1)[-1].strip()
                    if task_text:
                        save_task(task_text)
                        await ws.send_json({"type": "response", "text": f"✅ Úkol uložen: {task_text}"})
                    continue

                if text_lower.startswith("hotovo:") or text_lower.startswith("done:"):
                    q = user_text.split(":", 1)[-1].strip()
                    done = complete_task(q)
                    if done:
                        await ws.send_json({"type": "response", "text": f"✅ Hotovo: {done}"})
                    else:
                        await ws.send_json({"type": "response", "text": "❌ Úkol nenalezen."})
                    continue

                if text_lower.startswith("zapomeň") or text_lower.startswith("zapomen"):
                    topic = user_text.split(" ", 1)[-1].strip() if " " in user_text else ""
                    if topic:
                        deleted = forget_about(topic)
                        await ws.send_json({"type": "response", "text": f"🗑️ Smazáno {deleted} vzpomínek o '{topic}'." if deleted else f"🧠 Nic o '{topic}' nenalezeno."})
                    else:
                        await ws.send_json({"type": "response", "text": "Použití: `zapomeň [téma]`"})
                    continue

                if text_lower.startswith("vzpomeň") or text_lower.startswith("co víš"):
                    query = user_text.split(" ", 1)[-1] if " " in user_text else user_text
                    results = search_memory(query, n_results=5)
                    if results:
                        lines = [f"- [{r['category']}] {r['content'][:100]}" for r in results]
                        await ws.send_json({"type": "response", "text": f"🧠 Nalezeno {len(results)} vzpomínek:\n" + "\n".join(lines)})
                    else:
                        await ws.send_json({"type": "response", "text": "🧠 Nic nenalezeno."})
                    continue

                # Add to history
                history.append(HumanMessage(content=user_text))

                # Summarize if needed
                if len(history) > 8:
                    old = history[:-4]
                    summary_text = "\n".join(
                        f"{'User' if isinstance(m, HumanMessage) else 'Agent'}: {m.content[:150]}"
                        for m in old[-6:]
                    )
                    conv["summary"] = f"Předchozí konverzace: {summary_text}"
                    conv["history"] = history[-4:]
                    history = conv["history"]

                # Build messages
                messages = []
                if conv["summary"]:
                    messages.append(SystemMessage(content=f"SOUHRN:\n{conv['summary']}"))
                messages.extend(history[-6:])

                # Send thinking indicator
                await ws.send_json({"type": "thinking"})

                # Run agent in threadpool (blocking LLM calls)
                loop = asyncio.get_event_loop()

                def run_agent():
                    """Run agent synchronously."""
                    import io
                    log_capture = io.StringIO()

                    # Capture Rich console output
                    from rich.console import Console
                    capture_console = Console(file=log_capture, force_terminal=False, no_color=True)

                    result = agent.invoke({
                        "messages": messages,
                        "current_specialist": "",
                        "task_summary": "",
                        "use_memory": True,
                        "publish_to_wp": False,
                        "pending_steps": [],
                        "current_plan": "",
                        "step_results": [],
                    })

                    ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
                    response_text = ai_msgs[-1].content if ai_msgs else "..."

                    return response_text, log_capture.getvalue()

                try:
                    response_text, logs = await loop.run_in_executor(None, run_agent)
                except Exception as e:
                    response_text = f"❌ Chyba: {e}"
                    logs = str(e)

                # Add to history
                history.append(AIMessage(content=response_text))

                # Send response + logs
                await ws.send_json({
                    "type": "response",
                    "text": response_text,
                })

                if logs.strip():
                    await ws.send_json({
                        "type": "log",
                        "text": logs.strip(),
                    })

                # Send updated stats
                try:
                    s = get_memory_stats()
                    t = list_tasks("open")
                    await ws.send_json({
                        "type": "stats_update",
                        "stats": s,
                        "tasks": [{"text": x["text"], "status": x["status"]} for x in t],
                    })
                except Exception:
                    pass

    except WebSocketDisconnect:
        del conversations[conn_id]
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "text": str(e)})
        except Exception:
            pass
        if conn_id in conversations:
            del conversations[conn_id]


if __name__ == "__main__":
    port = int(os.getenv("UI_PORT", "8899"))
    print(f"\n🤖 Firebot Chat UI → http://localhost:{port}\n")

    # Start background tasks
    @app.on_event("startup")
    async def startup_event():
        asyncio.create_task(broadcast_orders())

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
