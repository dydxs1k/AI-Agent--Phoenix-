"""
╔══════════════════════════════════════════════════════════════╗
║           ИИ-АГЕНТ «ФЕНИКС» v0.4  —  Max Performance         ║
║  ✦ RAG-память  ✦ run_python  ✦ Стриминг  ✦ TTL-кэш  ✦ Web  ║
╚══════════════════════════════════════════════════════════════╝
# ──────────────────────────────────────────────────────────────
#  СТАНДАРТНАЯ БИБЛИОТЕКА
# ──────────────────────────────────────────────────────────────
import ast
import hashlib
import json
import operator as op
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

_MISSING: list[str] = []

try:
    import numpy as np
except ImportError:
    np = None                           # type: ignore[assignment]
    _MISSING.append("numpy")

import requests                         # входит в стандартный pip

# python-dotenv -- загрузка .env файла (pip install python-dotenv)
try:
    from dotenv import load_dotenv      # type: ignore[import]
    load_dotenv()
except ImportError:
    pass

try:
    from bs4 import BeautifulSoup       # type: ignore[import]  # pip install beautifulsoup4
    _BS4_OK = True
except ImportError:
    BeautifulSoup = None                # type: ignore[assignment,misc]
    _BS4_OK = False
    _MISSING.append("beautifulsoup4")

try:
    from duckduckgo_search import DDGS  # pip install duckduckgo-search
except ImportError:
    DDGS = None                         # type: ignore[assignment,misc]
    _MISSING.append("duckduckgo-search")

# Опциональный rich — подсветка кода в терминале
try:
    from rich.console import Console    # type: ignore[import]  # pip install rich
    from rich.syntax import Syntax      # type: ignore[import]
    _RICH: Optional[Console] = Console()
except ImportError:
    _RICH = None

# Colorama — ANSI-цвета на Windows (pip install colorama)
try:
    import colorama                     # type: ignore[import]
    colorama.init(autoreset=True)       # ← включает ANSI на Windows 10
    _COLORAMA_OK = True
except ImportError:
    _COLORAMA_OK = False
    _MISSING.append("colorama")

# ══════════════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ
# ══════════════════════════════════════════════════════════════

OLLAMA_URL    = os.getenv("OLLAMA_URL",  "http://localhost:11434")
LLM_MODEL     = os.getenv("LLM_MODEL",   "llama3")
LLM_TIMEOUT   = int(os.getenv("LLM_TIMEOUT", "90"))

PROFILE_PATH  = Path("agent_profile.json")
RAG_PATH      = Path("agent_rag_memory.json")

SANDBOX_TIMEOUT   = 15      # секунды на выполнение Python-кода
CACHE_TTL_SEARCH  = 300     # секунды кэша поиска (5 мин)
CACHE_TTL_BROWSE  = 600     # секунды кэша страниц (10 мин)
CACHE_TTL_FILE    = 60      # секунды кэша файлов

MAX_RAG_RESULTS   = 4       # сколько фактов подбирать из долгосрочной памяти
RAG_EMBED_DIM     = 1       # заглушка до запуска; Ollama вернёт реальный размер


# ══════════════════════════════════════════════════════════════
#  🪪  ПРОФИЛЬ АГЕНТА
# ══════════════════════════════════════════════════════════════

PROFILE_FIELDS: list[tuple[str, str, str]] = [
    ("name",        "Имя",       "Как зовут агента?"),
    ("version",     "Версия",    "Версия (напр. 3.0)"),
    ("description", "Описание",  "Краткое описание"),
    ("author",      "Автор",     "Кто создал агента?"),
    ("language",    "Язык",      "Основной язык общения"),
    ("personality", "Характер",  "Стиль поведения"),
    ("skills",      "Умения",    "Ключевые навыки через запятую"),
    ("motto",       "Девиз",     "Любимая фраза"),
]

DEFAULT_PROFILE = {
    "name":        "Феникс",
    "version":     "0.4",
    "description": "Умный ИИ-агент с RAG-памятью, выполнением кода, браузером и стримингом",
    "author":      "Дима Кузьменко, также известен как Дед либо DyDxS1k/The Disgraced One.",
    "language":    "Русский/Украинский",
    "personality": "Дружелюбный, точный, инициативный",
    "skills":      "Поиск, вычисления, код, файлы, браузер, долгосрочная RAG-память",
    "motto":       "Думаю, действую, запоминаю. В случае ошибки улучшаюсь.",
}


class AgentProfile:
    def __init__(self, path: Path = PROFILE_PATH):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return {**DEFAULT_PROFILE,
                        **json.loads(self.path.read_text("utf-8"))}
            except Exception:
                pass
        return dict(DEFAULT_PROFILE)

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def get(self, key: str) -> str:
        return self.data.get(key, "—")

    def set(self, key: str, value: str):
        self.data[key] = value.strip()
        self.save()

    def display(self):
        W = 56
        print()
        print("  ╔" + "═" * W + "╗")
        print(f"  ║{'🤖  КАРТОЧКА АГЕНТА':^{W}}║")
        print("  ╠" + "═" * W + "╣")
        for key, label, _ in PROFILE_FIELDS:
            val = self.data.get(key, "—")
            max_v = W - len(label) - 4
            if len(val) > max_v:
                val = val[:max_v - 1] + "…"
            print(f"  ║  \033[1;33m{label}\033[0m: {val:<{W - len(label) - 4}}║")
        print("  ╠" + "═" * W + "╣")
        print(f"  ║  \033[90mФайл: {str(self.path):<{W - 7}}\033[0m║")
        print("  ╚" + "═" * W + "╝\n")

    def edit_interactive(self):
        print("\n  \033[1;36m✏️  Редактор профиля\033[0m  (Enter = без изменений, q = выйти)\n")
        for i, (key, label, hint) in enumerate(PROFILE_FIELDS, 1):
            cur = self.data.get(key, "")
            try:
                print(f"  \033[90m[{i}/{len(PROFILE_FIELDS)}]\033[0m \033[1m{label}\033[0m  \033[90m({hint})\033[0m")
                print(f"  Сейчас: \033[33m{cur}\033[0m")
                nv = input("  Новое: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n  ⚠️  Прервано."); break
            if nv.lower() == "q":
                print("  ✋ Выход."); break
            if nv:
                self.set(key, nv)
                print("  \033[32m✔ Сохранено\033[0m\n")
            else:
                print("  \033[90m— без изменений\033[0m\n")
        print("  \033[1;32m💾 Профиль сохранён.\033[0m")
        self.display()

    def edit_field(self, hint: str):
        m = next(((k, l, h) for k, l, h in PROFILE_FIELDS
                  if hint.lower() in k.lower() or hint.lower() in l.lower()), None)
        if not m:
            print(f"  ⚠️  Поле «{hint}» не найдено. Доступные: "
                  + ", ".join(k for k, _, _ in PROFILE_FIELDS))
            return
        key, label, desc = m
        print(f"\n  \033[1m{label}\033[0m  ({desc})\n  Сейчас: \033[33m{self.data.get(key,'')}\033[0m")
        try:
            nv = input("  Новое: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  ✋ Отменено."); return
        if nv:
            self.set(key, nv)
            print(f"  \033[32m✔ «{label}» → {nv}\033[0m")
        else:
            print("  — без изменений")


# ══════════════════════════════════════════════════════════════
#  🗄️  TTL-КЭШ ИНСТРУМЕНТОВ
# ══════════════════════════════════════════════════════════════

class TTLCache:
    """
    Простой потокобезопасный кэш с истечением срока.
    Ключ = sha256 от (tool_name + JSON(args)).
    """
    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(tool: str, kwargs: dict) -> str:
        raw = tool + json.dumps(kwargs, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, tool: str, kwargs: dict, ttl: float) -> "tuple[bool, Any]":
        k = self._key(tool, kwargs)
        with self._lock:
            if k in self._store:
                val, ts = self._store[k]
                if time.time() - ts < ttl:
                    return True, val
        return False, None

    def set(self, tool: str, kwargs: dict, value) -> None:
        k = self._key(tool, kwargs)
        with self._lock:
            self._store[k] = (value, time.time())

    def clear(self):
        with self._lock:
            self._store.clear()

_CACHE = TTLCache()


# ══════════════════════════════════════════════════════════════
#  🧠  RAG — ДОЛГОСРОЧНАЯ ВЕКТОРНАЯ ПАМЯТЬ
# ══════════════════════════════════════════════════════════════

def _get_embedding(text: str) -> Optional[Any]:
    """Получить эмбеддинг через Ollama /api/embeddings."""
    try:
        r = requests.post(f"{OLLAMA_URL}/api/embeddings",
                          json={"model": LLM_MODEL, "prompt": text},
                          timeout=30)
        r.raise_for_status()
        vec = np.array(r.json()["embedding"], dtype=np.float32)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec
    except Exception:
        return None


def _cosine(a: Any, b: Any) -> float:
    return float(np.dot(a, b))          # уже нормализованы


class RAGMemory:
    """
    Долгосрочная семантическая память.
    Хранит факты + их эмбеддинги в JSON-файле.
    При поиске выбирает top-k по косинусному сходству.

    Формат записи:
        {"text": "...", "ts": "...", "embedding": [...], "source": "..."}
    """

    def __init__(self, path: Path = RAG_PATH, top_k: int = MAX_RAG_RESULTS):
        self.path  = path
        self.top_k = top_k
        self.records: list[dict] = self._load()
        self._lock = threading.Lock()

    # ── I/O ──────────────────────────────────────────────────
    def _load(self) -> list[dict]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text("utf-8"))
            except Exception:
                pass
        return []

    def _save(self):
        self.path.write_text(
            json.dumps(self.records, ensure_ascii=False, indent=2),
            encoding="utf-8")

    # ── публичный API ────────────────────────────────────────
    def remember(self, text: str, source: str = "dialog") -> bool:
        """Добавить новый факт в долгосрочную память."""
        vec = _get_embedding(text)
        if vec is None:
            return False            # Ollama недоступна — молча пропускаем
        record = {
            "text":      text.strip(),
            "ts":        _now_full(),
            "source":    source,
            "embedding": vec.tolist(),
        }
        with self._lock:
            self.records.append(record)
            self._save()
        return True

    def search(self, query: str) -> list[dict]:
        """Найти top-k самых релевантных фактов."""
        qvec = _get_embedding(query)
        if qvec is None or not self.records:
            return []
        scored = []
        with self._lock:
            for r in self.records:
                vec = np.array(r["embedding"], dtype=np.float32)
                scored.append((_cosine(qvec, vec), r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:self.top_k]]

    def forget(self, idx: int) -> bool:
        """Удалить запись по индексу."""
        with self._lock:
            if 0 <= idx < len(self.records):
                self.records.pop(idx)
                self._save()
                return True
        return False

    def list_all(self) -> list[dict]:
        with self._lock:
            return list(self.records)

    def rag_block(self, query: str) -> str:
        """Строка для вставки в промпт: релевантные воспоминания."""
        hits = self.search(query)
        if not hits:
            return ""
        lines = ["=== 🧠 Долгосрочная память (релевантное) ==="]
        for h in hits:
            lines.append(f"  [{h['ts']}] {h['text']}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
#  💬  КРАТКОСРОЧНАЯ ПАМЯТЬ (диалог текущей сессии)
# ══════════════════════════════════════════════════════════════

class ConversationMemory:
    def __init__(self, max_turns: int = 20):
        self.turns:    list[dict] = []
        self.step_log: list[dict] = []
        self.max_turns = max_turns

    def add(self, role: str, content: str):
        self.turns.append({"role": role, "content": content, "ts": _now()})
        if len(self.turns) > self.max_turns * 2:
            self.turns = self.turns[-self.max_turns * 2:]

    def log_step(self, step: int, tool: str, inp: str, result: str):
        self.step_log.append({"step": step, "tool": tool,
                               "input": inp, "result": result[:400]})

    def clear_steps(self):
        self.step_log = []

    def context_block(self) -> str:
        return "\n".join(
            f"[{t['role'].upper()}]: {t['content']}"
            for t in self.turns[-10:])


# ══════════════════════════════════════════════════════════════
#  🔧  ИНСТРУМЕНТЫ
# ══════════════════════════════════════════════════════════════

# ── Калькулятор ──────────────────────────────────────────────
_OPS = {
    ast.Add: op.add,  ast.Sub: op.sub,
    ast.Mult: op.mul, ast.Div: op.truediv,
    ast.Pow: op.pow,  ast.USub: op.neg,
    ast.Mod: op.mod,  ast.FloorDiv: op.floordiv,
}

def _safe_eval(node):
    if isinstance(node, ast.Constant): return node.value
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Недопустимо: {ast.dump(node)}")

def tool_calculator(expr: str) -> dict:
    try:
        return {"ok": True, "result": _safe_eval(ast.parse(expr.strip(), mode="eval").body)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Веб-поиск ────────────────────────────────────────────────
def tool_search(query: str, max_results: int = 5) -> dict:
    hit, val = _CACHE.get("search", {"query": query}, CACHE_TTL_SEARCH)
    if hit:
        _log("  [кэш] search")
        return val
    try:
        with DDGS() as d:
            res = [{"title": r["title"], "url": r["href"], "snippet": r["body"]}
                   for r in d.text(query, max_results=max_results)]
        result = {"ok": True, "results": res}
        _CACHE.set("search", {"query": query}, result)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Браузер (читает полную страницу) ─────────────────────────
def tool_browse(url: str, max_chars: int = 6000) -> dict:
    hit, val = _CACHE.get("browse", {"url": url}, CACHE_TTL_BROWSE)
    if hit:
        _log("  [кэш] browse")
        return val
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PhoenixAgent/3.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = re.sub(r"\s{3,}", "\n\n", soup.get_text(" ")).strip()
        result = {"ok": True, "url": url, "content": text[:max_chars],
                  "truncated": len(text) > max_chars}
        _CACHE.set("browse", {"url": url}, result)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Чтение файла ─────────────────────────────────────────────
def tool_read_file(path: str, max_chars: int = 6000) -> dict:
    hit, val = _CACHE.get("read_file", {"path": path}, CACHE_TTL_FILE)
    if hit:
        _log("  [кэш] read_file")
        return val
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return {"ok": False, "error": f"Файл не найден: {path}"}
        text = p.read_text(encoding="utf-8", errors="replace")
        result = {"ok": True, "content": text[:max_chars],
                  "truncated": len(text) > max_chars, "size": p.stat().st_size}
        _CACHE.set("read_file", {"path": path}, result)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Запись файла ─────────────────────────────────────────────
def tool_write_file(path: str, content: str) -> dict:
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "written_bytes": len(content.encode())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 🐍  run_python — изолированное выполнение кода ──────────
_PYTHON = sys.executable
_BANNED = re.compile(
    r"\b(os\.system|subprocess|shutil\.rmtree|open\s*\(.*[\"\'](w|a)[\"\']\s*\)|"
    r"__import__|importlib|socket|requests|urllib|httpx|ftplib|smtplib)\b"
)

def tool_run_python(code: str, timeout: int = SANDBOX_TIMEOUT) -> dict:
    """
    Запускает Python-код в дочернем процессе с таймаутом.
    Базовая фильтрация опасных операций.
    Возвращает stdout + stderr + код возврата.
    """
    # ── проверка на запрещённые паттерны ──────────────────────
    if _BANNED.search(code):
        return {"ok": False,
                "error": "Код содержит запрещённые операции (сеть/ФС/процессы)."}

    # ── записываем во временный файл ──────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w",
                                     encoding="utf-8", delete=False) as f:
        f.write(textwrap.dedent(code))
        tmp = f.name

    try:
        proc = subprocess.run(
            [_PYTHON, tmp],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        return {
            "ok":       proc.returncode == 0,
            "stdout":   proc.stdout[:3000],
            "stderr":   proc.stderr[:1000],
            "exit_code": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Таймаут ({timeout}s) превышен."}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        Path(tmp).unlink(missing_ok=True)


# ── Запомнить факт ────────────────────────────────────────────
# (инструмент для агента — добавить в RAG-память)
def tool_remember(text: str, rag: "RAGMemory") -> dict:
    ok = rag.remember(text, source="agent")
    return {"ok": ok, "stored": text if ok else None}


# ── Реестр и схема ────────────────────────────────────────────
def make_tools(rag: "RAGMemory") -> dict:
    return {
        "calculator":  tool_calculator,
        "search":      tool_search,
        "browse":      tool_browse,
        "read_file":   tool_read_file,
        "write_file":  tool_write_file,
        "run_python":  tool_run_python,
        "remember":    lambda text: tool_remember(text, rag),
        "none":        lambda **_: {"ok": True},
    }

TOOLS_SCHEMA = """
Доступные инструменты:
  • calculator  — вычислить выражение.        input: {"expr": "2**10 + 5"}
  • search      — поиск в интернете.          input: {"query": "...", "max_results": 5}
  • browse      — прочитать веб-страницу.     input: {"url": "https://..."}
  • read_file   — прочитать файл.             input: {"path": "/path/to/file"}
  • write_file  — записать файл.              input: {"path": "...", "content": "..."}
  • run_python  — выполнить Python-код.       input: {"code": "print(2+2)"}
  • remember    — сохранить факт навсегда.    input: {"text": "важный факт"}
  • none        — ответить напрямую.
"""


# ══════════════════════════════════════════════════════════════
#  ⚡  ПАРАЛЛЕЛЬНЫЙ ЗАПУСК ИНСТРУМЕНТОВ
# ══════════════════════════════════════════════════════════════

def run_tools_parallel(calls: list[dict], tools: dict) -> list[dict]:
    results = [None] * len(calls)
    lock    = threading.Lock()

    def _run(idx: int, call: dict):
        name = call.get("tool", "none")
        inp  = call.get("input", {})
        fn   = tools.get(name)
        if fn is None:
            res = {"ok": False, "error": f"Неизвестный инструмент: {name}"}
        else:
            try:
                res = fn(**inp) if isinstance(inp, dict) else fn(inp)
            except Exception as e:
                res = {"ok": False, "error": str(e)}
        with lock:
            results[idx] = {"tool": name, "input": inp, "output": res}

    with ThreadPoolExecutor(max_workers=min(len(calls), 6)) as pool:
        fts = [pool.submit(_run, i, c) for i, c in enumerate(calls)]
        for f in as_completed(fts):
            f.result()
    return results


# ══════════════════════════════════════════════════════════════
#  📊  СЧЁТЧИК ТОКЕНОВ
# ══════════════════════════════════════════════════════════════

class TokenStats:
    def __init__(self):
        self.prompt_tokens:    int = 0
        self.generated_tokens: int = 0
        self.calls:            int = 0

    def add(self, prompt: int, generated: int):
        self.prompt_tokens    += prompt
        self.generated_tokens += generated
        self.calls            += 1

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.generated_tokens

    def display(self):
        print(f"  [90m📊 Токены: +{self.generated_tokens} генерировано | промпт {self.prompt_tokens} | итого {self.total} | вызовов {self.calls}[0m")

    def reset(self):
        self.prompt_tokens = self.generated_tokens = self.calls = 0

_STATS = TokenStats()


# ══════════════════════════════════════════════════════════════
#  🤖  LLM — OLLAMA С РЕТРАЯМИ + СТРИМИНГОМ
# ══════════════════════════════════════════════════════════════

def _llm_request(payload: dict, timeout: int = LLM_TIMEOUT,
                 retries: int = 3) -> requests.Response:
    """POST к Ollama с экспоненциальным backoff."""
    delay = 1.0
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(f"{OLLAMA_URL}/api/generate",
                              json=payload, timeout=timeout, stream=payload.get("stream", False))
            r.raise_for_status()
            return r
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    raise last_err


def ask_llm(prompt: str, system: str = "") -> str:
    """Обычный (не стриминговый) запрос — возвращает полный ответ."""
    full = f"{system}\n\n{prompt}" if system else prompt
    try:
        r    = _llm_request({"model": LLM_MODEL, "prompt": full, "stream": False})
        data = r.json()
        _STATS.add(
            prompt    = data.get("prompt_eval_count", 0),
            generated = data.get("eval_count", 0),
        )
        return data["response"]
    except Exception as e:
        return json.dumps({"error": str(e)})


def ask_llm_stream(prompt: str, system: str = "",
                   prefix: str = "") -> str:
    """
    Стриминговый запрос — выводит токены по мере генерации,
    возвращает собранную строку целиком.
    """
    full = f"{system}\n\n{prompt}" if system else prompt
    collected = []
    try:
        r = _llm_request({"model": LLM_MODEL, "prompt": full, "stream": True},
                         timeout=LLM_TIMEOUT)
        print(prefix, end="", flush=True)
        for line in r.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except Exception:
                continue
            token = chunk.get("response", "")
            print(token, end="", flush=True)
            collected.append(token)
            if chunk.get("done"):
                break
        print()    # перевод строки после стрима
    except Exception as e:
        err = f"[Ошибка стриминга: {e}]"
        print(err)
        return err
    return "".join(collected)


# ══════════════════════════════════════════════════════════════
#  🧩  JSON-ПАРСЕР ОТВЕТОВ
# ══════════════════════════════════════════════════════════════

def parse_json(raw: str) -> dict | None:
    text = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            try:
                return json.loads(text[s:e + 1])
            except Exception:
                pass
    return None


# ══════════════════════════════════════════════════════════════
#  🔁  СИСТЕМНЫЙ ПРОМПТ
# ══════════════════════════════════════════════════════════════

def build_system_prompt(profile: AgentProfile) -> str:
    return f"""Ты — ИИ-агент «{profile.get("name")}» v{profile.get("version")}.
{profile.get("description")}.
Характер: {profile.get("personality")}.
Девиз: {profile.get("motto")}.

{TOOLS_SCHEMA}

Отвечай СТРОГО одним JSON-объектом (без текста снаружи):
{{
  "thought":        "<рассуждение>",
  "parallel_calls": [{{"tool":"<name>","input":{{...}},"reason":"<зачем>"}}],
  "final_answer":   "<ответ>"        // только если готов финальный ответ
}}

Правила:
• parallel_calls может содержать несколько вызовов — они выполнятся параллельно.
• Если ответ готов — заполни final_answer, оставь parallel_calls пустым [].
• Используй инструмент remember, когда узнаёшь важный факт о пользователе.
• Никогда не выходи за пределы JSON.
"""


# ══════════════════════════════════════════════════════════════
#  🔁  АГЕНТ — MULTI-STEP ReAct-ЦИКЛ
# ══════════════════════════════════════════════════════════════

def agent(user_input: str,
          memory:  ConversationMemory,
          rag:     RAGMemory,
          profile: AgentProfile,
          max_steps: int = 5) -> str:

    memory.add("user", user_input)
    memory.clear_steps()

    tools         = make_tools(rag)
    system_prompt = build_system_prompt(profile)
    rag_context   = rag.rag_block(user_input)
    accumulated:  list[dict] = []

    for step in range(1, max_steps + 1):
        prompt = f"""
{rag_context}

=== История диалога ===
{memory.context_block()}

=== Результаты предыдущих шагов ===
{json.dumps(accumulated, ensure_ascii=False, indent=2) if accumulated else "нет"}

=== Вопрос пользователя ===
{user_input}

Шаг {step}/{max_steps}. Дай final_answer если данных уже достаточно.
"""
        raw    = ask_llm(prompt, system=system_prompt)
        parsed = parse_json(raw)

        if parsed is None:
            if step == max_steps:
                memory.add("assistant", raw.strip())
                return raw.strip()
            continue

        thought        = parsed.get("thought", "")
        parallel_calls = parsed.get("parallel_calls", [])
        final_answer   = parsed.get("final_answer", "")

        _log(f"[Шаг {step}] 💭 {thought}", kind="thought")

        if final_answer:
            _log(f"[Шаг {step}] ✅ Финальный ответ", kind="answer")
            memory.add("assistant", final_answer)
            return final_answer

        if parallel_calls:
            names = [c["tool"] for c in parallel_calls]
            _log(f"[Шаг {step}] ⚡ Параллельно: {names}", kind="tools")
            results = run_tools_parallel(parallel_calls, tools)
            for tr in results:
                memory.log_step(step, tr["tool"], str(tr["input"]), str(tr["output"]))
                accumulated.append(tr)
                out_preview = str(tr["output"])
                _log(f"         [{tr['tool']}] → {out_preview[:130]}{'…' if len(out_preview) > 130 else ''}", kind="tools")
        else:
            _log(f"[Шаг {step}] ⏳ Размышление без инструментов", kind="wait")

    # шаги исчерпаны — финальная сборка
    summary = f"""
Данные:
{json.dumps(accumulated, ensure_ascii=False, indent=2)}

Вопрос: {user_input}

Ответь СТРОГО JSON: {{"thought":"...","parallel_calls":[],"final_answer":"..."}}
"""
    raw    = ask_llm(summary, system=system_prompt)
    parsed = parse_json(raw)
    answer = (parsed or {}).get("final_answer", raw.strip())
    memory.add("assistant", answer)
    return answer


# ══════════════════════════════════════════════════════════════
#  🖨️  УТИЛИТЫ
# ══════════════════════════════════════════════════════════════

def _now()      -> str: return datetime.now().strftime("%H:%M:%S")
def _now_full() -> str: return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

_C = {
    "grey":   "\033[90m",
    "yellow": "\033[1;33m",
    "blue":   "\033[1;34m",
    "green":  "\033[1;32m",
    "reset":  "\033[0m",
}

def _log(msg: str, kind: str = "grey"):
    colors = {
        "thought": _C["yellow"],
        "tools":   _C["blue"],
        "answer":  _C["green"],
        "wait":    _C["grey"],
        "grey":    _C["grey"],
    }
    c = colors.get(kind, _C["grey"])
    print(f"  {c}{msg}{_C['reset']}")


def _print_help():
    print("""
  \033[1;33m📋 Команды:\033[0m
    \033[1mobо мне\033[0m               — карточка агента
    \033[1mредактировать профиль\033[0m  — изменить все поля
    \033[1mизменить <поле>\033[0m        — изменить одно поле
    \033[1mпамять\033[0m                — показать долгосрочную память
    \033[1mзапомни <факт>\033[0m         — вручную добавить факт в RAG
    \033[1mзабудь <номер>\033[0m         — удалить запись из RAG
    \033[1mclear cache\033[0m           — очистить кэш инструментов
    \033[1mhistory\033[0m               — история диалога сессии
    \033[1mclear\033[0m                 — очистить историю сессии
    \033[1mexport\033[0m                — сохранить диалог в .md файл
    \033[1mретрай\033[0m / \033[1mretry\033[0m        — повторить последний вопрос
    \033[1mтокены\033[0m                — статистика токенов сессии
    \033[1mмодель\033[0m                — текущая LLM-модель
    \033[1mhelp\033[0m                  — эта справка
    \033[1mexit\033[0m                  — выйти
""")


def _show_rag(rag: RAGMemory):
    records = rag.list_all()
    if not records:
        print("  📭 Долгосрочная память пуста.")
        return
    print(f"\n  \033[1;36m🧠 Долгосрочная память ({len(records)} записей):\033[0m")
    for i, r in enumerate(records):
        print(f"  [{i}] \033[90m{r['ts']}\033[0m  {r['text'][:100]}"
              f"{'…' if len(r['text']) > 100 else ''}")
    print()


def _export_history(memory: ConversationMemory, profile: AgentProfile) -> str:
    """Экспортирует историю диалога в .md файл."""
    if not memory.turns:
        print("  📭 История пуста.")
        return ""
    ts       = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"export_{ts}.md"
    lines    = [f"# Диалог с '{profile.get('name')}' -- {ts}\n"]
    for t in memory.turns:
        icon = "🧑" if t["role"] == "user" else "🤖"
        lines.append(f"### {icon} [{t['ts']}]\n{t['content']}\n")
    Path(filename).write_text("\n".join(lines), encoding="utf-8")
    print(f"  [32m✔ Экспортировано -> {filename}[0m")
    return filename


def build_banner(profile: AgentProfile) -> str:
    name, ver, motto = profile.get("name"), profile.get("version"), profile.get("motto")
    W = 60
    return "\n".join([
        "╔" + "═" * W + "╗",
        f"║  🤖  ИИ-Агент «{name}» v{ver}{' ' * max(0, W - 14 - len(name) - len(ver))}║",
        f"║  ✦ {motto[:W-6]:<{W-6}} ║",
        f"║  {'Команды: help | обо мне | память | запомни …':<{W}} ║",
        "╚" + "═" * W + "╝",
    ])


# ══════════════════════════════════════════════════════════════
#  🚀  ГЛАВНЫЙ ЦИКЛ
# ══════════════════════════════════════════════════════════════

def main():
    # ── проверка зависимостей при старте ──────────────────────
    if _MISSING:
        print("\n  ⚠️  Не установлены пакеты. Запусти:")
        print(f"  pip install {' '.join(_MISSING)}\n")

    profile = AgentProfile()
    memory  = ConversationMemory(max_turns=30)
    rag     = RAGMemory()
    _last_q = ''
    _STATS.reset()

    print("\n" + build_banner(profile) + "\n")

    while True:
        try:
            user_input = input("\n\033[1;36mТы:\033[0m ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Пока!"); break

        if not user_input:
            continue

        cmd = user_input.lower()

        # ── служебные команды ──────────────────────────────────
        if cmd == "exit":
            print(f"👋 До свидания! Я — {profile.get('name')}.")
            _STATS.display()
            break

        if cmd == "help":
            _print_help(); continue

        if cmd == "clear":
            memory.turns.clear(); memory.step_log.clear()
            print("🧹 История сессии очищена."); continue

        if cmd == "clear cache":
            _CACHE.clear()
            print("🧹 Кэш инструментов очищен."); continue

        if cmd == "history":
            if not memory.turns:
                print("📭 История пуста.")
            else:
                for t in memory.turns:
                    lbl = "🧑 Ты" if t["role"] == "user" else f"🤖 {profile.get('name')}"
                    print(f"  [{t['ts']}] {lbl}: {t['content'][:120]}")
            continue

        if cmd == 'export':
            _export_history(memory, profile); continue

        if cmd in ('ретрай', 'retry', 'повтори'):
            if not _last_q:
                print('  ⚠️  Нет предыдущего вопроса.'); continue
            user_input = _last_q
            print(f'  🔁 Повтор: {user_input}')

        if cmd in ('токены', 'tokens', 'статистика'):
            _STATS.display(); continue

        if cmd in ('модель', 'model'):
            print(f'  🤖 Модель: \033[1;33m{LLM_MODEL}\033[0m  '
                  f'({OLLAMA_URL})')
            continue

        # ── профиль ────────────────────────────────────────────
        if cmd in ("обо мне", "о себе", "профиль", "about"):
            profile.display(); continue

        if cmd in ("редактировать профиль", "изменить профиль", "редактировать"):
            profile.edit_interactive()
            print(f"\n  ✨ Имя теперь «{profile.get('name')}». Промпт обновлён.")
            continue

        if cmd.startswith("изменить "):
            profile.edit_field(user_input[9:].strip()); continue

        # ── 🧠 RAG-команды ────────────────────────────────────
        if cmd in ("память", "rag", "воспоминания"):
            _show_rag(rag); continue

        if cmd.startswith("запомни "):
            fact = user_input[8:].strip()
            ok = rag.remember(fact, source="user")
            print("  \033[32m✔ Запомнено.\033[0m" if ok else
                  "  ⚠️  Не удалось (Ollama недоступна?)."); continue

        if cmd.startswith("забудь "):
            try:
                idx = int(user_input.split()[1])
                if rag.forget(idx):
                    print(f"  🗑️  Запись [{idx}] удалена.")
                else:
                    print("  ⚠️  Запись не найдена.")
            except (ValueError, IndexError):
                print("  ⚠️  Укажите номер: забудь <номер>")
            continue

        # ── основной вызов агента ──────────────────────────────
        _last_q = user_input
        print()
        answer = agent(user_input, memory, rag, profile)
        print(f"\n\033[1;32m{profile.get('name')}:\033[0m {answer}")
        _STATS.display()


if __name__ == "__main__":
    main()