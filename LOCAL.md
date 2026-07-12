# Running the panel on your local PC

Running locally is the best option for personal use: unlimited storage (your own
disk), no upload size limits, no cost, and your chat data never leaves your machine.
You open it in your browser at **http://localhost:8000**.

Pick whichever method suits you.

---

## Windows — one click (easiest)

1. Install **Python 3.10+** from <https://www.python.org/downloads/> — during setup,
   tick **"Add python.exe to PATH"**.
2. Double-click **`start.bat`** in the project folder.
   - First run creates a virtual environment and installs dependencies (takes a minute).
   - Your browser opens automatically at http://localhost:8000.
3. Leave the black window open while you use it. Close it (or press Ctrl+C) to stop.

## macOS / Linux — one command

1. Make sure Python 3.10+ is installed (`python3 --version`).
2. In a terminal, from the project folder:
   ```bash
   ./run.sh
   ```
   (First run sets everything up.) Then open http://localhost:8000.

## Docker — one command (any OS with Docker)

```bash
docker compose up --build
```
Then open http://localhost:8000. Uploaded media + the database persist in the
`storage/` folder next to the compose file. Stop with `Ctrl+C` (or `docker compose down`).

---

## Manual setup (if you prefer to see each step)

```bash
cd backend
python -m venv .venv

# Windows:
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# macOS / Linux:
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

---

## Tips

- **View from your phone / another device on the same Wi-Fi:** start it bound to all
  interfaces, then browse to `http://<your-pc-ip>:8000`:
  ```bash
  ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
  ```
  (On Windows, `start.bat` uses `127.0.0.1`; change it to `0.0.0.0` for LAN access.)
- **Where is my data?** In the `storage/` folder: `whatsapp.db` (metadata) and
  `media/<job>/<chat>/` (extracted files). Delete the folder to wipe everything, or
  use the trash icon on an upload inside the panel.
- **Big exports:** locally there are no proxy limits, so 20 GB uploads work directly
  through uvicorn. Just make sure you have enough free disk space for the extracted media.
- **Port already in use?** Change `--port 8000` to another number (e.g. `8080`).
- **Export a chat from WhatsApp:** open a chat → menu → *Export chat* → *Include media*
  → share/save the `.zip` → upload it in the panel.
