"""
╔══════════════════════════════════════════════════════════╗
║                   ИИ-АГЕНТ «ФЕНИКС» v0.2                 ║
║  ✦ Память  ✦ Multi-step  ✦ Web+File  ✦ Parallel  ✦ JSON  ║
╚══════════════════════════════════════════════════════════╝
"""

import ast
import json
import operator as op
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from duckduckgo_search import DDGS


# ═══════════════════════════════════════════════════════════
#ПАМЯТЬ (ConversationMemory)
# ═══════════════════════════════════════════════════════════

class ConversationMemory:
    """Хранит историю диалога + краткосрочный контекст шагов."""

    def __init__(self, max_turns: int = 20):
        self.turns: list[dict] = []          # [{"role": ..., "content": ...}]
        self.step_log: list[dict] = []       # журнал шагов текущей задачи
        self.max_turns = max_turns

    # ── публичный API ────────────────────────────────────────
    def add(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content, "ts": _now()})
        if len(self.turns) > self.max_turns * 2:
            self.turns = self.turns[-self.max_turns * 2:]   # скользящее окно

    def log_step(self, step: int, tool: str, input_: str, result: str) -> None:
        self.step_log.append({
            "step": step, "tool": tool,
            "input": input_, "result": result[:300],
        })

    def clear_steps(self) -> None:
        self.step_log = []

    def context_block(self) -> str:
        """Последние N диалоговых ходов в виде строки для промпта."""
        recent = self.turns[-10:]
        return "\n".join(f"[{t['role'].upper()}]: {t['content']}" for t in recent)

    def steps_block(self) -> str:
        return json.dumps(self.step_log, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════
# ИНСТРУМЕНТЫ
# ═══════════════════════════════════════════════════════════

# ── Калькулятор ─────────────────────────────────────────────
_ALLOWED_OPS = {
    ast.Add: op.add,  ast.Sub: op.sub,
    ast.Mult: op.mul, ast.Div: op.truediv,
    ast.Pow: op.pow,  ast.USub: op.neg,
    ast.Mod: op.mod,  ast.FloorDiv: op.floordiv,
}

def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp):
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Недопустимое выражение: {ast.dump(node)}")

def tool_calculator(expr: str) -> dict:
    try:
        result = _safe_eval(ast.parse(expr.strip(), mode="eval").body)
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Веб-поиск (DuckDuckGo) ──────────────────────────────────
def tool_search(query: str, max_results: int = 5) -> dict:
    try:
        with DDGS() as ddgs:
            hits = ddgs.text(query, max_results=max_results)
        results = [{"title": r["title"], "url": r["href"], "snippet": r["body"]}
                   for r in hits]
        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Чтение файла ────────────────────────────────────────────
def tool_read_file(path: str, max_chars: int = 4000) -> dict:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return {"ok": False, "error": f"Файл не найден: {path}"}
        text = p.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        return {
            "ok": True,
            "content": text[:max_chars],
            "truncated": truncated,
            "size_bytes": p.stat().st_size,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Запись файла ────────────────────────────────────────────
def tool_write_file(path: str, content: str) -> dict:
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "written_bytes": len(content.encode())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


#Реестр инструментов ─────────────────────────────────────
TOOLS: dict[str, callable] = {
    "calculator":  tool_calculator,
    "search":      tool_search,
    "read_file":   tool_read_file,
    "write_file":  tool_write_file,
    "none":        lambda **_: {"ok": True, "result": None},
}

TOOLS_SCHEMA = """
Доступные инструменты (tool):
  • calculator  — вычислить математическое выражение. input: {"expr": "2+2"}
  • search      — поиск в интернете.                  input: {"query": "...", "max_results": 3}
  • read_file   — прочитать файл.                     input: {"path": "/path/to/file"}
  • write_file  — записать файл.                      input: {"path": "...", "content": "..."}
  • none        — ответить напрямую, инструменты не нужны.
"""


# ═══════════════════════════════════════════════════════════
# ПАРАЛЛЕЛЬНЫЙ ЗАПУСК ИНСТРУМЕНТОВ
# ═══════════════════════════════════════════════════════════

def run_tools_parallel(calls: list[dict]) -> list[dict]:
    """
    calls = [{"tool": "search", "input": {...}, "reason": "..."}, ...]
    Запускает все вызовы параллельно, возвращает результаты в том же порядке.
    """
    results = [None] * len(calls)
    lock = threading.Lock()

    def _run(idx: int, call: dict):
        tool_name = call.get("tool", "none")
        inp = call.get("input", {})
        fn = TOOLS.get(tool_name)
        if fn is None:
            res = {"ok": False, "error": f"Неизвестный инструмент: {tool_name}"}
        else:
            try:
                res = fn(**inp) if isinstance(inp, dict) else fn(inp)
            except Exception as e:
                res = {"ok": False, "error": str(e)}
        with lock:
            results[idx] = {"tool": tool_name, "input": inp, "output": res}

    with ThreadPoolExecutor(max_workers=min(len(calls), 6)) as pool:
        futures = [pool.submit(_run, i, c) for i, c in enumerate(calls)]
        for f in as_completed(futures):
            f.result()   # пробрасываем исключения (если есть)

    return results


# ═══════════════════════════════════════════════════════════
# LLM (Ollama)
# ═══════════════════════════════════════════════════════════

def ask_llm(prompt: str, system: str = "") -> str:
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "llama3", "prompt": full_prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["response"]
    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════
# JSON-ПАРСЕР ОТВЕТОВ LLM
# ═══════════════════════════════════════════════════════════

def parse_json_response(raw: str) -> dict | None:
    """Безопасный парсинг JSON из ответа LLM (с зачисткой markdown-фенсов)."""
    text = raw.strip()
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
    text = text.strip("` \n")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # попытка найти первый {...} в тексте
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass
    return None


# ═══════════════════════════════════════════════════════════
# MULTI-STEP REASONING  (ReAct-цикл)
# ═══════════════════════════════════════════════════════════

SYSTEM_PROMPT = f"""Ты — ИИ-агент «Феникс». Ты рассуждаешь пошагово и вызываешь инструменты.

{TOOLS_SCHEMA}

Отвечай СТРОГО одним JSON-объектом — без текста вокруг него.

Формат ответа на каждом шаге:
{{
  "thought": "<твои рассуждения>",
  "parallel_calls": [           // ← массив вызовов (может быть пустым)
    {{"tool": "<name>", "input": {{...}}, "reason": "<зачем>"}},
    ...
  ],
  "final_answer": "<ответ>"    // ← заполнить ТОЛЬКО если шаг последний
}}

Правила:
• Если нужны инструменты — заполни parallel_calls (можно несколько сразу).
• Если ответ уже готов — заполни final_answer и оставь parallel_calls пустым.
• Никогда не выходи за пределы JSON.
"""

def agent(user_input: str, memory: ConversationMemory, max_steps: int = 5) -> str:
    memory.add("user", user_input)
    memory.clear_steps()

    accumulated_results: list[dict] = []   # результаты всех шагов

    for step in range(1, max_steps + 1):
        # строим промпт
        prompt = f"""
=== История диалога ===
{memory.context_block()}

=== Результаты предыдущих шагов (шаг {step}) ===
{json.dumps(accumulated_results, ensure_ascii=False, indent=2) if accumulated_results else "нет"}

=== Задача пользователя ===
{user_input}

Шаг {step} из {max_steps}. Если уже достаточно данных — дай final_answer.
"""
        raw = ask_llm(prompt, system=SYSTEM_PROMPT)
        parsed = parse_json_response(raw)

        # защита от нераспарсенного ответа
        if parsed is None:
            if step == max_steps:
                answer = raw.strip()
                memory.add("assistant", answer)
                return answer
            continue   # пробуем ещё раз

        thought       = parsed.get("thought", "")
        parallel_calls = parsed.get("parallel_calls", [])
        final_answer  = parsed.get("final_answer", "")

        _log(f"[Шаг {step}] 💭 {thought}")

        # финальный ответ
        if final_answer:
            _log(f"[Шаг {step}] ✅ Финальный ответ получен")
            memory.add("assistant", final_answer)
            return final_answer

        # параллельный запуск инструментов
        if parallel_calls:
            _log(f"[Шаг {step}] ⚡ Параллельный запуск: "
                 f"{[c['tool'] for c in parallel_calls]}")
            tool_results = run_tools_parallel(parallel_calls)

            for i, tr in enumerate(tool_results):
                memory.log_step(step, tr["tool"], str(tr["input"]), str(tr["output"]))
                accumulated_results.append(tr)
                _log(f"         [{tr['tool']}] → "
                     f"{str(tr['output'])[:120]}{'…' if len(str(tr['output'])) > 120 else ''}")
        else:
            # LLM думает, но не вызывает инструменты и не даёт ответа
            _log(f"[Шаг {step}] ⏳ Промежуточное размышление без инструментов")

    #исчерпаны шаги — попросим LLM подвести итог
    summary_prompt = f"""
На основе собранных данных:
{json.dumps(accumulated_results, ensure_ascii=False, indent=2)}

Вопрос: {user_input}

Дай финальный ответ пользователю на русском языке.
Ответь СТРОГО JSON: {{"thought": "...", "parallel_calls": [], "final_answer": "..."}}
"""
    raw = ask_llm(summary_prompt, system=SYSTEM_PROMPT)
    parsed = parse_json_response(raw)
    answer = (parsed or {}).get("final_answer", raw.strip())
    memory.add("assistant", answer)
    return answer


# УТИЛИТЫ

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")

def _log(msg: str) -> None:
    print(f"  \033[90m{msg}\033[0m")   # серый цвет для служебных сообщений


# ═══════════════════════════════════════════════════════════
# ГЛАВНЫЙ ЦИКЛ
# ═══════════════════════════════════════════════════════════

BANNER = """
╔══════════════════════════════════════════════════════════╗
║                  ИИ-Агент «Феникс» v0.2                  ║
║   Команды: exit | clear (очистить память) | history      ║
╚══════════════════════════════════════════════════════════╝
"""

def main():
    print(BANNER)
    memory = ConversationMemory(max_turns=30)

    while True:
        try:
            user_input = input("\n\033[1;36mТы:\033[0m ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Пока!")
            break

        if not user_input:
            continue

        # ── служебные команды ──────────────────────────────────
        if user_input.lower() == "exit":
            print("👋 До свидания!")
            break

        if user_input.lower() == "clear":
            memory.turns.clear()
            memory.step_log.clear()
            print("🧹 Память очищена.")
            continue

        if user_input.lower() == "history":
            if not memory.turns:
                print("📭 История пуста.")
            else:
                for t in memory.turns:
                    role_label = "🧑 Ты" if t["role"] == "user" else "🤖 Агент"
                    print(f"  [{t['ts']}] {role_label}: {t['content'][:120]}")
            continue

        # ── основной вызов ─────────────────────────────────────
        print()
        answer = agent(user_input, memory)
        print(f"\n\033[1;32mАгент:\033[0m {answer}")


if __name__ == "__main__":
    main()