@echo off
chcp 65001 >nul
title Феникс — ИИ-Агент

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║        ИИ-Агент «Феникс» v0.5            ║
echo  ╚══════════════════════════════════════════╝
echo.

:: ── Проверка Python ────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Python не найден. Установи с https://python.org
    pause & exit /b 1
)

:: ── Проверка Ollama ─────────────────────────────────────────
ollama --version >nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Ollama не найдена. Установи с https://ollama.com
    pause & exit /b 1
)

:: ── Установка зависимостей (только если нужно) ──────────────
echo  [1/3] Проверка зависимостей...
pip install -q requests duckduckgo-search numpy beautifulsoup4 fastapi uvicorn rich 2>nul
echo  [OK]

:: ── Запуск Ollama ────────────────────────────────────────────
echo  [2/3] Запуск Ollama...
tasklist /fi "imagename eq ollama.exe" 2>nul | find /i "ollama.exe" >nul
if errorlevel 1 (
    start "" /min ollama serve
    timeout /t 3 /nobreak >nul
)
echo  [OK]

:: ── Выбор модели ─────────────────────────────────────────────
echo  Выбери модель:
echo.
echo    [1] llama3    (стандартная)
echo    [2] mistral   (Mistral 7B)
echo    [3] gemma     (Google Gemma)
echo.
set /p MODEL_CHOICE="  Введи номер модели (Enter = llama3): "

if "%MODEL_CHOICE%"=="2" (set MODEL=mistral)    else (
if "%MODEL_CHOICE%"=="3" (set MODEL=gemma)      else (
    set MODEL=llama3
))

echo  [OK] Модель: %MODEL%

:: ── Проверяем / скачиваем модель ─────────────────────────────
echo  Проверка модели %MODEL%...
ollama show %MODEL% >nul 2>&1
if errorlevel 1 (
    echo  Модель не найдена. Скачиваем %MODEL%...
    ollama pull %MODEL%
)
echo.

:: ── Прописываем модель в agent.py ─────────────────────────────
powershell -Command "(Get-Content agent.py) -replace 'LLM_MODEL\s*=\s*"[^"]+"', 'LLM_MODEL     = "%MODEL%"' | Set-Content agent.py"

:: ── Выбор режима ─────────────────────────────────────────────
echo  Выбери режим запуска:
echo.
echo    [1] Веб-интерфейс  (браузер)
echo    [2] Терминал       (консоль)
echo.
set /p MODE="  Введи 1 или 2: "

if "%MODE%"=="1" goto WEB
if "%MODE%"=="2" goto TERMINAL
echo  Неверный ввод, запускаю веб-интерфейс...
goto WEB

:: ════════════════════════════════════════════════════════════
:WEB
echo.
echo  [3/3] Запуск веб-сервера...
start "" /min cmd /c "uvicorn server:app --port 8000"
timeout /t 2 /nobreak >nul
start "" http://localhost:8000
echo  [OK] Браузер открыт → http://localhost:8000
echo.
echo  Закрой это окно чтобы остановить сервер.
echo  (Нажми Ctrl+C для выхода)
echo.
uvicorn server:app --port 8000
goto END

:: ════════════════════════════════════════════════════════════
:TERMINAL
echo.
echo  [3/3] Запуск агента в терминале...
echo.
python agent.py
goto END

:: ════════════════════════════════════════════════════════════
:END
echo.
echo  Феникс завершил работу.
pause