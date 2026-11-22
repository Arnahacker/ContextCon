@echo off
REM INVARIANT - Windows launcher. Double-click or: run.bat
python -m uvicorn invariant.app:app --reload --port 8000
