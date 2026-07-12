# WhatsApp Export Viewer — Panel

Upload a WhatsApp "Export chat" **.zip**, and this tool parses it and lets you
browse the conversation exactly like WhatsApp — chat bubbles, contact names &
numbers, media inline, plus a dedicated **Media gallery**. Built to ingest very
large archives (tens of GB) without loading them into memory.

This is the **panel** (the admin/processing tool). A public-facing frontend
service can be layered on top of the same API later.

## Features

- **Streaming uploads** — the zip is written straight to disk in 8 MB chunks; a
  20 GB archive never sits in RAM.
- **Streaming extraction** — media is streamed out of the zip entry-by-entry, so
  processing is also memory-safe. Progress is reported live.
- **Robust parser** — handles both iOS (`[2023-01-15, 10:30:45] Name:`) and
  Android (`15/01/2023, 10:30 - Name:`) formats, multi-line messages, system
  notices, phone-number-only senders, and media attachments.
- **WhatsApp-style UI** — chat list, bubbles (incoming/outgoing), day separators,
  contact names + numbers, links, and media.
- **Media gallery** — every photo, video, audio note, sticker and document in one
  place, filterable by type. Videos/audio stream with HTTP range support (seeking).
- **Multi-upload management** — track jobs, see progress, delete an upload (and all
  its data) from the panel.

## Run

```bash
./run.sh
# then open http://127.0.0.1:8000
```

Or manually:

```bash
cd backend
python -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## How to export a chat from WhatsApp

Open a chat → **⋮ / contact name** → **Export chat** → **Include media** →
share the resulting **.zip** → upload it in the panel.

## API (used by the panel, ready for a future frontend)

| Method | Path | Purpose |
|--------|------|---------|
| POST   | `/api/upload?filename=&size=` | Stream a zip (raw body) → returns `job_id` |
| GET    | `/api/jobs` / `/api/jobs/{id}` | List / poll processing jobs |
| DELETE | `/api/jobs/{id}` | Delete a job and all its data |
| GET    | `/api/chats?job_id=&q=` | List chats |
| GET    | `/api/chats/{id}` | Chat detail + participants |
| GET    | `/api/chats/{id}/messages?offset=&limit=&q=` | Paginated messages |
| GET    | `/api/chats/{id}/media?type=` | Media gallery (image/video/audio/sticker/document) |
| GET    | `/api/media/{id}?download=` | Serve a media file (range-enabled) |
| GET    | `/api/stats` | Totals |

## Storage layout

```
storage/
  whatsapp.db          # SQLite metadata (chats, messages, participants, media, jobs)
  uploads/             # raw zip while uploading (deleted after extraction)
  media/<job>/<chat>/  # extracted media files
```

Set `WA_STORAGE_DIR=/mnt/bigdisk` to store data on a larger volume.

## Architecture

```
backend/app/
  config.py     paths, chunk size, media classification
  database.py   SQLite engine (WAL) + session factory
  models.py     ORM: UploadJob, Chat, Participant, Message, Media
  parser.py     WhatsApp .txt parser (iOS + Android)
  processor.py  streaming zip -> DB + media on disk (runs in a background thread)
  main.py       FastAPI app: upload, chats, messages, media, static panel
backend/static/ index.html, styles.css, app.js  (the WhatsApp-themed panel)
```

## Notes / next steps

- Which side is "you" is auto-detected for 1:1 chats (the participant that isn't
  the chat name). You can change it per chat via the **Info** tab → "Set as you".
- For production behind Nginx, raise `client_max_body_size` and proxy timeouts to
  allow large uploads.
