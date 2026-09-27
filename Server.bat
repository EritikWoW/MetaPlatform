@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m src.scripts.run_runtime_server_cmd --host 127.0.0.1 --port 8765
) else (
  py -3.13 -m src.scripts.run_runtime_server_cmd --host 127.0.0.1 --port 8765
)
