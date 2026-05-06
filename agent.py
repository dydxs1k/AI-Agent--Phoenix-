from langchain.agents import initialize_agent, Tool
from langchain_community.llms import Ollama
from langchain.tools import DuckDuckGoSearchRun

# LLM (локальный!)
llm = Ollama(model="llama3")

# Поиск
search = DuckDuckGoSearchRun()

# Калькулятор
def calculator_tool(query: str):
    try:
        return str(eval(query))
    except Exception as e:
        return f"Ошибка: {e}"

tools = [
    Tool(
        name="Search",
        func=search.run,
        description="Поиск в интернете"
    ),
    Tool(
        name="Calculator",
        func=calculator_tool,
        description="Математика"
    )
]

agent = initialize_agent(
    tools,
    llm,
    agent="zero-shot-react-description",
    verbose=True
)

while True:
    user_input = input("Ты: ")
    if user_input.lower() == "exit":
        break
    
    response = agent.run(user_input)
    print("Агент:", response)