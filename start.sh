#!/bin/bash
# Феникс — запуск на Linux/macOS

BOLD='\033[1m'; AMBER='\033[33m'; GREEN='\033[32m'; RED='\033[31m'; NC='\033[0m'

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║        ИИ-Агент «Феникс» v0.5            ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Проверка Python ──────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo -e "  ${RED}[ОШИБКА]${NC} python3 не найден"
    exit 1
fi

# ── Проверка Ollama ──────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo -e "  ${RED}[ОШИБКА]${NC} Ollama не найдена → https://ollama.com"
    exit 1
fi

# ── Зависимости ──────────────────────────────────────────────
echo -e "  ${AMBER}[1/3]${NC} Проверка зависимостей..."
pip install -q requests duckduckgo-search numpy beautifulsoup4 fastapi uvicorn rich "uvicorn[standard]" --break-system-packages 2>/dev/null
echo -e "  ${GREEN}[OK]${NC}"

# ── Запуск Ollama если не запущена ───────────────────────────
echo -e "  ${AMBER}[2/3]${NC} Проверка Ollama..."
if ! pgrep -x "ollama" > /dev/null; then
    ollama serve &>/dev/null &
    sleep 2
fi
echo -e "  ${GREEN}[OK]${NC}"

# ── Выбор модели ─────────────────────────────────────────────
echo ""
echo "  Выбери модель:"
echo ""
echo "    [1] llama3   (стандартная)"
echo "    [2] mistral  (Mistral 7B)"
echo "    [3] gemma    (Google Gemma)"
echo ""
read -p "  Номер модели (Enter = llama3): " MODEL_CHOICE

case "$MODEL_CHOICE" in
  2) MODEL="mistral" ;;
  3) MODEL="gemma"   ;;
  *) MODEL="llama3"  ;;
esac

echo -e "  ${GREEN}[OK]${NC} Модель: ${AMBER}${MODEL}${NC}"

# ── Проверяем / скачиваем модель ─────────────────────────────
if ! ollama show "$MODEL" &>/dev/null; then
    echo -e "  Модель не найдена. Скачиваем ${MODEL}..."
    ollama pull "$MODEL"
fi
echo ""

# ── Прописываем модель в agent.py ────────────────────────────
sed -i "s/LLM_MODEL *= *.*/LLM_MODEL = \"${MODEL}\"/" agent.py

# ── Выбор режима ─────────────────────────────────────────────
echo "  Выбери режим:"
echo ""
echo "    [1] Веб-интерфейс  (браузер)"
echo "    [2] Терминал       (консоль)"
echo ""
read -p "  Введи 1 или 2: " MODE

case "$MODE" in
  1)
    echo ""
    echo -e "  ${AMBER}[3/3]${NC} Запуск веб-сервера..."
    python3 -m uvicorn server:app --port 8000 &
    sleep 1
    # открываем браузер
    if command -v xdg-open &>/dev/null; then
        xdg-open http://localhost:8000
    elif command -v open &>/dev/null; then
        open http://localhost:8000
    fi
    echo -e "  ${GREEN}[OK]${NC} → http://localhost:8000"
    echo ""
    echo "  Нажми Ctrl+C для остановки сервера."
    wait
    ;;
  2)
    echo ""
    echo -e "  ${AMBER}[3/3]${NC} Запуск агента в терминале..."
    echo ""
    python3 agent.py
    ;;
  *)
    echo "  Неверный ввод. Запускаю терминал..."
    python3 agent.py
    ;;
esac

echo ""
echo "  Феникс завершил работу."