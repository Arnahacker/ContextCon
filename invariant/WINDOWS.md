# Running on Windows (cmd)

```cmd
tar -xf invariant-starter.zip
cd invariant
pip install -r requirements.txt
copy .env.example .env
run.bat
```

Then open http://localhost:8000

Tests:
```cmd
pytest -q
```

Notes:
- `tar -xf` works on Windows 10 build 17063 and later. On anything older,
  right-click the zip and "Extract All".
- If `python` is not found, try `py -m uvicorn invariant.app:app --reload --port 8000`.
- `.env` is read by `invariant/__init__.py`, not by the shell, so it works the
  same on cmd, PowerShell and bash. Edit it in Notepad; no quotes needed.
- Stop the server with Ctrl+C.
- With `.env` left blank it runs on mocks. That is the intended starting state.
