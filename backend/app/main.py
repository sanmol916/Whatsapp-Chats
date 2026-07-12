"""FastAPI application: streaming upload, chat/message APIs, media serving, panel."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime

import aiofiles
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import config
from .database import SessionLocal, init_db
from .models import Chat, Media, Message, Participant, UploadJob
from .processor import process_zip

config.ensure_dirs()
init_db()

app = FastAPI(title="WhatsApp Export Viewer", version="1.0.0")


def get_session() -> Session:
    return SessionLocal()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# --------------------------------------------------------------------------- #
#  Upload (streaming, large-file friendly)
# --------------------------------------------------------------------------- #
@app.post("/api/upload")
async def upload(
    request: Request,
    filename: str = Query("export.zip"),
    size: int = Query(0),
):
    """Stream the raw request body straight to disk in chunks.

    The client sends the zip as the raw request body (application/octet-stream),
    passing the original name and total size as query params. Nothing is buffered
    in memory, so multi-GB uploads are safe.
    """
    job_id = str(uuid.uuid4())
    safe = "".join(c for c in filename if c.isalnum() or c in "._- ").strip() or "export.zip"
    dest = config.UPLOAD_DIR / f"{job_id}_{safe}"

    session = get_session()
    try:
        job = UploadJob(
            id=job_id,
            original_filename=filename,
            stored_path=str(dest),
            status="uploading",
            total_bytes=size,
        )
        session.add(job)
        session.commit()
    finally:
        session.close()

    received = 0
    last_flush = 0
    try:
        async with aiofiles.open(dest, "wb") as out:
            async for chunk in request.stream():
                if not chunk:
                    continue
                await out.write(chunk)
                received += len(chunk)
                # Persist progress every ~32 MB to avoid hammering the DB.
                if received - last_flush > 32 * 1024 * 1024:
                    last_flush = received
                    s = get_session()
                    try:
                        s.query(UploadJob).filter(UploadJob.id == job_id).update(
                            {"bytes_received": received}
                        )
                        s.commit()
                    finally:
                        s.close()
    except Exception as exc:  # noqa: BLE001
        s = get_session()
        try:
            s.query(UploadJob).filter(UploadJob.id == job_id).update(
                {"status": "error", "error": f"Upload failed: {exc}"}
            )
            s.commit()
        finally:
            s.close()
        raise HTTPException(status_code=500, detail="Upload failed")

    s = get_session()
    try:
        s.query(UploadJob).filter(UploadJob.id == job_id).update(
            {"status": "uploaded", "bytes_received": received, "total_bytes": received}
        )
        s.commit()
    finally:
        s.close()

    # Kick off processing in a background daemon thread (won't block the response).
    threading.Thread(target=process_zip, args=(job_id,), daemon=True).start()

    return {"job_id": job_id, "bytes_received": received}


# --------------------------------------------------------------------------- #
#  Jobs
# --------------------------------------------------------------------------- #
def _job_dict(j: UploadJob) -> dict:
    return {
        "id": j.id,
        "original_filename": j.original_filename,
        "status": j.status,
        "bytes_received": j.bytes_received,
        "total_bytes": j.total_bytes,
        "progress": j.progress,
        "stage": j.stage,
        "error": j.error,
        "chats_found": j.chats_found,
        "messages_found": j.messages_found,
        "media_found": j.media_found,
        "created_at": _iso(j.created_at),
    }


@app.get("/api/jobs")
def list_jobs():
    s = get_session()
    try:
        jobs = s.execute(select(UploadJob).order_by(UploadJob.created_at.desc())).scalars().all()
        return [_job_dict(j) for j in jobs]
    finally:
        s.close()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    s = get_session()
    try:
        j = s.get(UploadJob, job_id)
        if not j:
            raise HTTPException(404, "Job not found")
        return _job_dict(j)
    finally:
        s.close()


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    """Delete a job together with all its chats, messages and media (DB + files)."""
    import shutil

    s = get_session()
    try:
        j = s.get(UploadJob, job_id)
        if not j:
            raise HTTPException(404, "Job not found")
        chat_ids = s.execute(select(Chat.id).where(Chat.job_id == job_id)).scalars().all()
        for cid in chat_ids:
            s.execute(delete(Message).where(Message.chat_id == cid))
            s.execute(delete(Media).where(Media.chat_id == cid))
            s.execute(delete(Participant).where(Participant.chat_id == cid))
        s.execute(delete(Chat).where(Chat.job_id == job_id))
        s.execute(delete(UploadJob).where(UploadJob.id == job_id))
        s.commit()
    finally:
        s.close()

    media_dir = config.MEDIA_DIR / job_id
    if media_dir.exists():
        shutil.rmtree(media_dir, ignore_errors=True)
    return {"deleted": job_id}


# --------------------------------------------------------------------------- #
#  Chats
# --------------------------------------------------------------------------- #
def _chat_dict(c: Chat) -> dict:
    return {
        "id": c.id,
        "job_id": c.job_id,
        "name": c.name,
        "phone_number": c.phone_number,
        "is_group": bool(c.is_group),
        "message_count": c.message_count,
        "media_count": c.media_count,
        "first_timestamp": _iso(c.first_timestamp),
        "last_timestamp": _iso(c.last_timestamp),
        "last_message_preview": c.last_message_preview,
    }


@app.get("/api/chats")
def list_chats(job_id: str | None = None, q: str | None = None):
    s = get_session()
    try:
        stmt = select(Chat)
        if job_id:
            stmt = stmt.where(Chat.job_id == job_id)
        if q:
            stmt = stmt.where(Chat.name.ilike(f"%{q}%"))
        stmt = stmt.order_by(Chat.last_timestamp.desc().nullslast(), Chat.id.desc())
        chats = s.execute(stmt).scalars().all()
        return [_chat_dict(c) for c in chats]
    finally:
        s.close()


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: int):
    s = get_session()
    try:
        c = s.get(Chat, chat_id)
        if not c:
            raise HTTPException(404, "Chat not found")
        parts = s.execute(
            select(Participant).where(Participant.chat_id == chat_id)
            .order_by(Participant.message_count.desc())
        ).scalars().all()
        data = _chat_dict(c)
        data["participants"] = [
            {
                "name": p.name,
                "phone_number": p.phone_number,
                "message_count": p.message_count,
            }
            for p in parts
        ]
        return data
    finally:
        s.close()


@app.get("/api/chats/{chat_id}/messages")
def get_messages(
    chat_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    q: str | None = None,
):
    s = get_session()
    try:
        c = s.get(Chat, chat_id)
        if not c:
            raise HTTPException(404, "Chat not found")

        stmt = select(Message).where(Message.chat_id == chat_id)
        if q:
            stmt = stmt.where(Message.content.ilike(f"%{q}%"))
        total = s.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        rows = s.execute(
            stmt.order_by(Message.seq).offset(offset).limit(limit)
        ).scalars().all()

        # Preload media for these messages.
        media_ids = [m.media_id for m in rows if m.media_id]
        media_map: dict[int, Media] = {}
        if media_ids:
            for md in s.execute(select(Media).where(Media.id.in_(media_ids))).scalars().all():
                media_map[md.id] = md

        # Determine the primary participants so the UI can pick an "outgoing" side.
        senders = sorted(
            {m.sender_name for m in rows if m.sender_name}
        )

        messages = []
        for m in rows:
            md = media_map.get(m.media_id) if m.media_id else None
            messages.append({
                "id": m.id,
                "seq": m.seq,
                "sender_name": m.sender_name,
                "sender_number": m.sender_number,
                "timestamp": _iso(m.timestamp),
                "type": m.message_type,
                "content": m.content,
                "media": None if not md else {
                    "id": md.id,
                    "type": md.media_type,
                    "mime": md.mime_type,
                    "filename": md.original_filename,
                    "size": md.size_bytes,
                    "url": f"/api/media/{md.id}",
                },
            })
        return {
            "chat_id": chat_id,
            "total": total,
            "offset": offset,
            "limit": limit,
            "senders": senders,
            "messages": messages,
        }
    finally:
        s.close()


# --------------------------------------------------------------------------- #
#  Media gallery + serving
# --------------------------------------------------------------------------- #
@app.get("/api/chats/{chat_id}/media")
def chat_media(
    chat_id: int,
    type: str | None = Query(None, description="image|video|audio|sticker|document"),
    offset: int = Query(0, ge=0),
    limit: int = Query(120, ge=1, le=500),
):
    s = get_session()
    try:
        stmt = select(Media).where(Media.chat_id == chat_id)
        if type:
            stmt = stmt.where(Media.media_type == type)
        total = s.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = s.execute(
            stmt.order_by(Media.id).offset(offset).limit(limit)
        ).scalars().all()
        # Counts per type for the gallery filter chips.
        counts_rows = s.execute(
            select(Media.media_type, func.count()).where(Media.chat_id == chat_id)
            .group_by(Media.media_type)
        ).all()
        counts = {t: n for t, n in counts_rows}
        return {
            "total": total,
            "counts": counts,
            "items": [
                {
                    "id": md.id,
                    "type": md.media_type,
                    "mime": md.mime_type,
                    "filename": md.original_filename,
                    "size": md.size_bytes,
                    "url": f"/api/media/{md.id}",
                }
                for md in rows
            ],
        }
    finally:
        s.close()


@app.get("/api/media/{media_id}")
def serve_media(media_id: int, download: bool = False):
    s = get_session()
    try:
        md = s.get(Media, media_id)
        if not md:
            raise HTTPException(404, "Media not found")
        path = md.stored_path
        disposition = "attachment" if download else "inline"
        # FileResponse handles HTTP Range requests -> video/audio seeking works.
        return FileResponse(
            path,
            media_type=md.mime_type,
            filename=md.original_filename,
            content_disposition_type=disposition,
        )
    finally:
        s.close()


# --------------------------------------------------------------------------- #
#  Stats + static panel
# --------------------------------------------------------------------------- #
@app.get("/api/stats")
def stats():
    s = get_session()
    try:
        return {
            "chats": s.execute(select(func.count()).select_from(Chat)).scalar_one(),
            "messages": s.execute(select(func.count()).select_from(Message)).scalar_one(),
            "media": s.execute(select(func.count()).select_from(Media)).scalar_one(),
            "jobs": s.execute(select(func.count()).select_from(UploadJob)).scalar_one(),
        }
    finally:
        s.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the WhatsApp-themed panel. Mounted last so /api/* wins.
config.STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="panel")
