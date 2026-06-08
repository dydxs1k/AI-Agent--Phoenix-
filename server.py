"""
Феникс — веб-сервер
Запуск: uvicorn server:app --reload --port 8000
Зависимости: pip install fastapi uvicorn
"""

import json
import sys
import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# ── подключаем агента из того же каталога ────────────────────
sys.path.insert(0, str(Path(__file__).parent))
import agent as A   # agent.py

app = FastAPI(title="Феникс")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ── глобальные объекты агента (одна сессия на сервер) ─────────
_profile = A.AgentProfile()
_memory  = A.ConversationMemory(max_turns=30)
_rag     = A.RAGMemory()


# ════════════════════════════════════════════════════════════
#  REST — профиль, память, история
# ════════════════════════════════════════════════════════════

@app.get("/api/profile")
def get_profile():
    return _profile.data

@app.post("/api/profile")
async def set_profile(body: dict):
    for k, v in body.items():
        _profile.set(k, str(v))
    return {"ok": True}

@app.get("/api/memory")
def get_memory():
    return [{"idx": i, "text": r["text"], "ts": r["ts"], "source": r["source"]}
            for i, r in enumerate(_rag.list_all())]

@app.post("/api/memory")
async def add_memory(body: dict):
    ok = _rag.remember(body.get("text", ""), source="user")
    return {"ok": ok}

@app.delete("/api/memory/{idx}")
def delete_memory(idx: int):
    ok = _rag.forget(idx)
    return {"ok": ok}

@app.get("/api/history")
def get_history():
    return _memory.turns

@app.post("/api/clear")
def clear_history():
    _memory.turns.clear()
    _memory.step_log.clear()
    return {"ok": True}

@app.get("/api/thoughts_mode")
def get_thoughts_mode():
    return {"enabled": A._SHOW_THOUGHTS}

@app.post("/api/thoughts_mode")
async def set_thoughts_mode(body: dict):
    A._SHOW_THOUGHTS = bool(body.get("enabled", True))
    return {"ok": True, "enabled": A._SHOW_THOUGHTS}


# ════════════════════════════════════════════════════════════
#  WebSocket — чат со стримингом шагов
# ════════════════════════════════════════════════════════════

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_event_loop()

    try:
        while True:
            data   = await ws.receive_json()
            user_q = data.get("message", "").strip()
            if not user_q:
                continue

            await ws.send_json({"event": "user_echo", "text": user_q})

            # ── очередь для передачи мыслей из потока в async ──
            thought_queue: asyncio.Queue = asyncio.Queue()
            original_log = A._log

            def patched_log(msg: str, kind: str = "grey"):
                original_log(msg, kind)              # терминал как раньше
                loop.call_soon_threadsafe(
                    thought_queue.put_nowait,
                    {"event": "thought", "text": msg, "kind": kind}
                )

            A._log = patched_log

            # ── запускаем агента в отдельном потоке ────────────
            future = loop.run_in_executor(
                None,
                lambda: A.agent(user_q, _memory, _rag, _profile)
            )

            # ── сливаем мысли в браузер пока агент думает ──────
            while not future.done():
                try:
                    item = await asyncio.wait_for(
                        thought_queue.get(), timeout=0.1
                    )
                    await ws.send_json(item)
                except asyncio.TimeoutError:
                    pass

            # ── дочищаем очередь после завершения ──────────────
            A._log = original_log
            while not thought_queue.empty():
                await ws.send_json(thought_queue.get_nowait())

            # ── получаем ответ и отправляем ──────────────────
            try:
                answer = await future
                if not answer:
                    answer = "⚠️ Агент вернул пустой ответ."
                await ws.send_json({
                    "event": "answer",
                    "text":  str(answer),
                    "name":  _profile.get("name"),
                })
            except Exception as agent_err:
                await ws.send_json({
                    "event": "answer",
                    "text":  f"⚠️ Ошибка агента: {agent_err}",
                    "name":  _profile.get("name"),
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"event": "error", "text": str(e)})
        except Exception:
            pass
    finally:
        try:
            A._log = original_log
        except NameError:
            pass


# ════════════════════════════════════════════════════════════
#  Отдаём index.html
# ════════════════════════════════════════════════════════════

@app.get("/")
def root():
    html = Path(__file__).parent / "index.html"
    if html.exists():
        return FileResponse(html)
    return HTMLResponse("<h1>Положи index.html рядом с server.py</h1>")