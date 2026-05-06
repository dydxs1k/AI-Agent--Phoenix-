import requests
from duckduckgo_search import DDGS
import ast
import operator as op

# ===== LLM (Ollama) =====
def ask_llm(prompt: str) -> str:
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "llama3",
            "prompt": prompt,
            "stream": False
        }
    )
    return response.json()["response"]


# ===== Сalculator =====
allowed_operators = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.USub: op.neg,
}

def safe_eval(node):
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.BinOp):
        return allowed_operators[type(node.op)](
            safe_eval(node.left),
            safe_eval(node.right)
        )

    if isinstance(node, ast.UnaryOp):
        return allowed_operators[type(node.op)](safe_eval(node.operand))

    raise ValueError("Unsupported expression")

def calculator(expr: str):
    try:
        node = ast.parse(expr, mode='eval').body
        return str(safe_eval(node))
    except Exception as e:
        return f"Ошибка: {e}"


# ===== Search tool =====
def search(query: str):
    with DDGS() as ddgs:
        results = ddgs.text(query, max_results=3)
        return "\n".join([f"{r['title']} - {r['href']}" for r in results])


# ===== Agent logic =====
def agent(user_input: str):
    prompt = f"""
Ты ИИ-агент с инструментами.

Доступные инструменты:
1. search(query)
2. calculator(expr)

ВАЖНО: отвечай ТОЛЬКО в формате:

TOOL: search | calculator | none
INPUT: ...

Если TOOL = none:
ANSWER: ...

Вопрос пользователя:
{user_input}
"""

    decision = ask_llm(prompt)

    lines = decision.splitlines()

    tool = None
    input_data = None
    answer = None

    for line in lines:
        if line.startswith("TOOL:"):
            tool = line.replace("TOOL:", "").strip()

        if line.startswith("INPUT:"):
            input_data = line.replace("INPUT:", "").strip()

        if line.startswith("ANSWER:"):
            answer = line.replace("ANSWER:", "").strip()

    # ===== routing =====
    if tool == "search":
        return search(input_data or user_input)

    if tool == "calculator":
        return calculator(input_data or user_input)

    if answer:
        return answer

    return decision


# ===== Run loop =====
print('ИИ-агент "Феникс" запущен. Слушаю ваш вопрос.')
print('Напиши "exit" для выхода\n')

while True:
    user_input = input("Ты: ")

    if user_input.lower() == "exit":
        break

    print("Агент:", agent(user_input))