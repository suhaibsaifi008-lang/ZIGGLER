@echo off
title ZIGGLER Launcher
cd /d "%~dp0evo"

REM ---- 1. FreeLLMAPI gateway (skip if already running) ----
netstat -ano | findstr ":3001" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo [ziggler] starting FreeLLMAPI gateway on :3001 ...
    start "FreeLLMAPI Gateway" /min cmd /c "cd /d C:\Users\Mohd Suhaib\AppData\Local\Temp\opencode\freellmapi\server && npm run dev"
) else (
    echo [ziggler] gateway already running on :3001
)

REM ---- 2. Web test harness on :8765 ----
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo [ziggler] starting web harness on http://127.0.0.1:8765 ...
    start "Ziggler Web" /min cmd /c "set PYTHONPATH=%~dp0&& python evo\webui\server.py --port 8765"
) else (
    echo [ziggler] web harness already running
)

timeout /t 4 /nobreak >nul
start "" http://127.0.0.1:8765
echo [ziggler] ready. This window can be closed.
