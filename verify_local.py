"""Boot the real uvicorn server in a thread, hit it over HTTP, then exit.

Proves the exact local run path (uvicorn serving the ASGI app on a TCP port)
works end-to-end, not just the in-process TestClient.
"""
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

import uvicorn  # noqa: E402
from app.main import app  # noqa: E402

PORT = 8022
config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
server = uvicorn.Server(config)


def run():
    server.run()


t = threading.Thread(target=run, daemon=True)
t.start()

# Wait for startup.
for _ in range(50):
    if server.started:
        break
    time.sleep(0.1)


def get(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=10) as r:
        return r.status, r.read()


def post_zip(path, data):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=data,
        headers={"Content-Type": "application/octet-stream"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read()


ok = True


def check(label, cond):
    global ok
    print(("  PASS " if cond else "  FAIL ") + label)
    ok = ok and cond


print("Real uvicorn server started on 127.0.0.1:%d\n" % PORT)

s, body = get("/")
check("panel / served (200, has title)", s == 200 and b"WhatsApp Export Viewer" in body)
s, body = get("/app.js")
check("/app.js served", s == 200 and len(body) > 1000)
s, body = get("/styles.css")
check("/styles.css served", s == 200)
s, body = get("/api/health")
check("/api/health ok", b"ok" in body)

zip_bytes = (Path(__file__).parent / "sample_export.zip").read_bytes()
s, body = post_zip(f"/api/upload?filename=sample_export.zip&size={len(zip_bytes)}", zip_bytes)
check("upload accepted over HTTP", s == 200 and b"job_id" in body)

time.sleep(3)  # let background processing finish
s, body = get("/api/chats")
import json
chats = json.loads(body)
check("chat parsed & listed", len(chats) == 1 and chats[0]["name"] == "Alice Johnson")
if chats:
    cid = chats[0]["id"]
    s, body = get(f"/api/chats/{cid}/media")
    media = json.loads(body)
    check("media extracted (3)", media["total"] == 3)

server.should_exit = True
time.sleep(0.5)
print("\n" + ("ALL LOCAL HTTP CHECKS PASSED \u2705" if ok else "SOME CHECKS FAILED \u274c"))
sys.exit(0 if ok else 1)
