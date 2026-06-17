@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Phoenix AI Agent

echo.
echo ==========================================
echo Phoenix AI Agent v0.5
echo ==========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

ollama --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Ollama not found.
    pause
    exit /b 1
)

if not exist agent.py (
    echo [ERROR] agent.py not found in this folder.
    pause
    exit /b 1
)

echo [1/3] Installing dependencies...
python -m pip install requests duckduckgo-search numpy beautifulsoup4 fastapi uvicorn rich
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo [2/3] Starting Ollama...
tasklist /fi "imagename eq ollama.exe" 2>nul | find /i "ollama.exe" >nul
if errorlevel 1 (
    start "" /min ollama serve
    timeout /t 5 /nobreak >nul
)

echo.
echo Choose model:
echo.
echo [1] llama3
echo [2] mistral
echo [3] gemma
echo.
set /p MODEL_CHOICE=Enter model number, default 1: 

set "MODEL=llama3"
if "%MODEL_CHOICE%"=="2" set "MODEL=mistral"
if "%MODEL_CHOICE%"=="3" set "MODEL=gemma"

echo.
echo Selected model: %MODEL%
echo.

ollama show %MODEL% >nul 2>&1
if errorlevel 1 (
    echo Model not found. Pulling %MODEL%...
    ollama pull %MODEL%
    if errorlevel 1 (
        echo [ERROR] Failed to pull model.
        pause
        exit /b 1
    )
)

echo Updating model in agent.py...
python -c "from pathlib import Path; import re; p=Path('agent.py'); s=p.read_text(encoding='utf-8'); q=chr(34); s=re.sub('LLM_MODEL\\s*=\\s*'+q+'[^'+q+']+'+q, 'LLM_MODEL     = '+q+'%MODEL%'+q, s); p.write_text(s, encoding='utf-8')"

if errorlevel 1 (
    echo [ERROR] Failed to update agent.py.
    pause
    exit /b 1
)

echo.
echo Choose mode:
echo.
echo [1] Web interface
echo [2] Terminal
echo.
set /p MODE=Enter 1 or 2: 

if "%MODE%"=="2" goto TERMINAL
goto WEB

:WEB
if not exist server.py (
    echo [ERROR] server.py not found.
    pause
    exit /b 1
)

echo.
echo [3/3] Starting web server...
echo Open in browser: http://localhost:8000
start "" http://localhost:8000
python -m uvicorn server:app --port 8000
goto END

:TERMINAL
echo.
echo [3/3] Starting terminal agent...
python agent.py
goto END

:END
echo.
echo Phoenix finished.
pause