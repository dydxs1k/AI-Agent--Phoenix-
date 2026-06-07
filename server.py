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
    try:
        while True:
            data   = await ws.receive_json()
            user_q = data.get("message", "").strip()
            if not user_q:
                continue

            # ── перехватываем _log и ask_llm для стриминга ────
            log_orig = A._log.__code__

            async def send(event: str, payload: dict):
                await ws.send_json({"event": event, **payload})

            await send("user_echo", {"text": user_q})

            # патчим _log чтобы шаги шли в браузер
            original_log = A._log

            def patched_log(msg: str, kind: str = "grey"):
                original_log(msg, kind)           # терминал
                asyncio.get_event_loop().call_soon_threadsafe(
                    lambda m=msg, k=kind: asyncio.ensure_future(
                        send("thought", {"text": m, "kind": k})
                    )
                )
            A._log = patched_log

            try:
                loop   = asyncio.get_event_loop()
                answer = await loop.run_in_executor(
                    None,
                    lambda: A.agent(user_q, _memory, _rag, _profile)
                )
            finally:
                A._log = original_log

            await send("answer", {"text": answer,
                                   "name": _profile.get("name")})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"event": "error", "text": str(e)})
        except Exception:
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