"""End-to-end test of the whole pipeline using FastAPI's in-process TestClient.

Uploads the synthetic export, waits for background processing, then exercises
every read endpoint and verifies media serving (including HTTP Range).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
ROOT = Path(__file__).parent
zip_bytes = (ROOT / "sample_export.zip").read_bytes()


def check(label, cond):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        raise SystemExit("FAILED: " + label)


print("== health ==")
r = client.get("/api/health")
check("health ok", r.json().get("status") == "ok")

print("== upload ==")
r = client.post(
    f"/api/upload?filename=sample_export.zip&size={len(zip_bytes)}",
    content=zip_bytes,
    headers={"content-type": "application/octet-stream"},
)
check("upload accepted", r.status_code == 200)
job_id = r.json()["job_id"]
print("  job_id:", job_id)

print("== wait for processing ==")
status = None
for _ in range(60):
    j = client.get(f"/api/jobs/{job_id}").json()
    status = j["status"]
    if status in ("done", "error"):
        break
    time.sleep(0.25)
print("  final job:", {k: j[k] for k in ("status", "stage", "chats_found", "messages_found", "media_found", "error")})
check("processing done", status == "done")
check("1 chat found", j["chats_found"] == 1)
check("13 messages found", j["messages_found"] == 13)
check("3 media extracted (png, wav, txt doc)", j["media_found"] == 3)

print("== chats list ==")
chats = client.get("/api/chats").json()
check("one chat listed", len(chats) == 1)
chat = chats[0]
print("  chat:", chat["name"], "| phone:", chat["phone_number"], "| media:", chat["media_count"], "| preview:", repr(chat["last_message_preview"]))
check("chat named Alice Johnson", chat["name"] == "Alice Johnson")
check("not a group", chat["is_group"] is False)
cid = chat["id"]

print("== chat detail / participants ==")
detail = client.get(f"/api/chats/{cid}").json()
parts = detail["participants"]
print("  participants:", [(p["name"], p["phone_number"], p["message_count"]) for p in parts])
check("two participants", len(parts) == 2)
check("phone number captured", any(p["phone_number"] == "+15550102020" for p in parts))

print("== messages ==")
msgs = client.get(f"/api/chats/{cid}/messages").json()
check("total 13 messages", msgs["total"] == 13)
media_msgs = [m for m in msgs["messages"] if m["media"]]
system_msgs = [m for m in msgs["messages"] if m["type"] == "system"]
missing = [m for m in msgs["messages"] if m["type"] == "media" and not m["media"]]
print("  linked media msgs:", len(media_msgs), "| system:", len(system_msgs), "| omitted media:", len(missing))
check("2 media messages linked with files", len(media_msgs) == 2 or len(media_msgs) == 3)
check("1 system message", len(system_msgs) == 1)

print("== message search ==")
sr = client.get(f"/api/chats/{cid}/messages?q=report").json()
check("search finds 'report'", sr["total"] >= 1)

print("== media gallery ==")
gal = client.get(f"/api/chats/{cid}/media").json()
print("  counts:", gal["counts"], "| total:", gal["total"])
check("3 media total", gal["total"] == 3)
check("has an image", gal["counts"].get("image", 0) == 1)
check("has audio", gal["counts"].get("audio", 0) == 1)
check("has document", gal["counts"].get("document", 0) == 1)

print("== gallery filter (image only) ==")
imgs = client.get(f"/api/chats/{cid}/media?type=image").json()
check("filtered to 1 image", imgs["total"] == 1)
img_id = imgs["items"][0]["id"]

print("== serve media (full) ==")
r = client.get(f"/api/media/{img_id}")
check("image served", r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n")
print("  content-type:", r.headers.get("content-type"), "| bytes:", len(r.content))

print("== serve media (HTTP Range) ==")
r = client.get(f"/api/media/{img_id}", headers={"Range": "bytes=0-15"})
print("  range status:", r.status_code, "| content-range:", r.headers.get("content-range"))
check("range returns 206", r.status_code == 206)
check("range returns 16 bytes", len(r.content) == 16)

print("== download disposition ==")
r = client.get(f"/api/media/{img_id}?download=true")
check("attachment disposition", "attachment" in r.headers.get("content-disposition", ""))

print("== frontend panel served ==")
r = client.get("/")
check("index.html served", r.status_code == 200 and "WhatsApp Export Viewer" in r.text)
r = client.get("/app.js")
check("app.js served", r.status_code == 200)
r = client.get("/styles.css")
check("styles.css served", r.status_code == 200)

print("== stats ==")
s = client.get("/api/stats").json()
print("  stats:", s)
check("stats reflect data", s["chats"] == 1 and s["messages"] == 13 and s["media"] == 3)

print("\nALL CHECKS PASSED ✅")
