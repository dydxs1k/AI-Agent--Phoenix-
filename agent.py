import requests
from duckduckgo_search import DDGS

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


# ===== Tools =====
def search(query: str):
    with DDGS() as ddgs:
        results = ddgs.text(query, max_results=3)
        return "\n".join([r["title"] + " - " + r["href"] for r in results])


def calculator(expr: str):
    try:
        return str(eval(expr))
    except Exception as e:
        return f"Ошибка: {e}"


# ===== Agent logic =====
def agent(user_input: str):
    prompt = f"""
Ты ИИ-агент. У тебя есть инструменты:

1. search(query) - поиск в интернете
2. calculator(expr) - математика

Если нужно использовать инструмент — скажи КОРОТКО что сделать.

Вопрос пользователя:
{user_input}

Ответ:
"""
    decision = ask_llm(prompt)

    # простая логика маршрутизации
    if "search" in decision.lower():
        return search(user_input)

    if "calculator" in decision.lower():
        return calculator(user_input)

    return decision


# ===== Run loop =====
print('Я ИИ-помощник "Феникс". Слушаю ваш вопрос.')
while True:
    user_input = input("Ты: ")
    if user_input.lower() == "exit":
        break

    print("Агент:", agent(user_input))