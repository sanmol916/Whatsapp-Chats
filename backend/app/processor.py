"""Streaming zip processor.

Designed for very large archives (tens of GB):
  * The zip is read from disk with the stdlib `zipfile` (ZIP64 aware).
  * Each media entry is streamed to disk in CHUNK_SIZE blocks via copyfileobj,
    so a single 20 GB archive never needs more than a few MB of RAM.
  * Chat .txt files are small and parsed in full.
  * Progress is written back to the UploadJob row so the UI can poll it.
"""
from __future__ import annotations

import mimetypes
import posixpath
import re
import shutil
import zipfile
from pathlib import Path

from sqlalchemy import update

from . import config
from .database import SessionLocal
from .models import Chat, Media, Message, Participant, UploadJob
from .parser import guess_chat_name, parse_chat_text

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_name(name: str) -> str:
    """Reduce an arbitrary path to a safe basename (prevents zip-slip)."""
    base = posixpath.basename(name.replace("\\", "/"))
    base = _SAFE_RE.sub("_", base).strip("._") or "file"
    return base[:200]


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _update_job(session, job_id: str, **fields) -> None:
    session.execute(update(UploadJob).where(UploadJob.id == job_id).values(**fields))
    session.commit()


def process_zip(job_id: str) -> None:
    """Entry point run in a background thread."""
    session = SessionLocal()
    try:
        job = session.get(UploadJob, job_id)
        if job is None:
            return
        _update_job(session, job_id, status="processing", stage="Opening archive", progress=0)

        zip_path = Path(job.stored_path)
        if not zip_path.exists():
            _update_job(session, job_id, status="error", error="Uploaded file missing on disk")
            return

        try:
            zf = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile:
            _update_job(session, job_id, status="error", error="Not a valid zip archive")
            return

        with zf:
            entries = [e for e in zf.infolist() if not e.is_dir()]

            def _is_chat_txt(e: zipfile.ZipInfo) -> bool:
                lower = e.filename.lower()
                base = posixpath.basename(lower)
                return lower.endswith(".txt") and ("chat" in base or base == "_chat.txt")

            txt_entries = [e for e in entries if _is_chat_txt(e)]
            # Fallback: if nothing matched the "chat" heuristic, take any .txt.
            if not txt_entries:
                txt_entries = [e for e in entries if e.filename.lower().endswith(".txt")]
            media_entries = [e for e in entries if e not in txt_entries]

            # --- 1. Parse chat text files, create Chat/Participant/Message rows ---
            _update_job(session, job_id, stage="Parsing conversations")
            chat_dirs: list[tuple[str, int]] = []  # (dir_prefix, chat_id)
            # per chat: basename(lower) -> first message id needing media linkage
            pending_links: dict[int, dict[str, int]] = {}
            total_messages = 0

            for txt in txt_entries:
                text = _decode(zf.read(txt))
                parsed = parse_chat_text(text)
                if not parsed.messages:
                    continue

                real_senders = {s for s in parsed.senders if s}
                is_group = len(real_senders) > 2
                name = guess_chat_name(txt.filename)
                timestamps = [m.timestamp for m in parsed.messages if m.timestamp]

                chat = Chat(
                    job_id=job_id,
                    name=name,
                    is_group=1 if is_group else 0,
                    source_txt=txt.filename,
                    message_count=len(parsed.messages),
                    first_timestamp=min(timestamps) if timestamps else None,
                    last_timestamp=max(timestamps) if timestamps else None,
                )
                session.add(chat)
                session.flush()  # assign chat.id

                # Participants (name + number aggregation).
                part_map: dict[str, Participant] = {}
                for m in parsed.messages:
                    if m.message_type == "system" or not m.sender_name:
                        continue
                    p = part_map.get(m.sender_name)
                    if p is None:
                        p = Participant(
                            chat_id=chat.id,
                            name=m.sender_name,
                            phone_number=m.sender_number,
                            message_count=0,
                        )
                        part_map[m.sender_name] = p
                        session.add(p)
                    if not p.phone_number and m.sender_number:
                        p.phone_number = m.sender_number
                    p.message_count += 1

                # For a 1:1 chat, surface the "other" participant's number on the chat.
                if not is_group and part_map:
                    numbered = [p for p in part_map.values() if p.phone_number]
                    if numbered:
                        chat.phone_number = numbered[0].phone_number

                # Messages.
                links: dict[str, int] = {}
                last_preview = ""
                for seq, m in enumerate(parsed.messages):
                    msg = Message(
                        chat_id=chat.id,
                        seq=seq,
                        sender_name=m.sender_name,
                        sender_number=m.sender_number,
                        timestamp=m.timestamp,
                        message_type=m.message_type,
                        content=m.content,
                    )
                    session.add(msg)
                    session.flush()
                    if m.media_filename:
                        links.setdefault(_safe_name(m.media_filename).lower(), msg.id)
                    if m.message_type == "text" and m.content:
                        last_preview = m.content
                    elif m.message_type == "media":
                        last_preview = "\U0001F4CE Media"
                chat.last_message_preview = last_preview[:200]

                pending_links[chat.id] = links
                chat_dirs.append((posixpath.dirname(txt.filename), chat.id))
                total_messages += len(parsed.messages)

            session.commit()

            if not chat_dirs:
                _update_job(
                    session, job_id, status="error",
                    error="No WhatsApp chat text file (_chat.txt) found in the archive",
                )
                return

            # --- 2. Stream media out to disk, create Media rows, link messages ---
            def chat_for(entry_name: str) -> int:
                d = posixpath.dirname(entry_name)
                if len(chat_dirs) == 1:
                    return chat_dirs[0][1]
                best_id, best_len = chat_dirs[0][1], -1
                for prefix, cid in chat_dirs:
                    if (d == prefix or d.startswith(prefix + "/")) and len(prefix) > best_len:
                        best_id, best_len = cid, len(prefix)
                return best_id

            total_media_bytes = sum(e.file_size for e in media_entries) or 1
            done_bytes = 0
            media_count = 0
            media_per_chat: dict[int, int] = {}

            _update_job(
                session, job_id, stage="Extracting media",
                messages_found=total_messages, chats_found=len(chat_dirs),
            )

            for i, entry in enumerate(media_entries):
                cid = chat_for(entry.filename)
                dest_dir = config.MEDIA_DIR / job_id / str(cid)
                dest_dir.mkdir(parents=True, exist_ok=True)

                base = _safe_name(entry.filename)
                dest = dest_dir / base
                counter = 1
                while dest.exists():
                    dest = dest_dir / f"{dest.stem}_{counter}{dest.suffix}"
                    counter += 1

                # Stream copy the entry to disk in chunks.
                with zf.open(entry) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out, length=config.CHUNK_SIZE)

                mtype = config.classify_extension(base)
                mime = mimetypes.guess_type(base)[0] or "application/octet-stream"
                media = Media(
                    chat_id=cid,
                    original_filename=posixpath.basename(entry.filename),
                    stored_path=str(dest),
                    media_type=mtype,
                    mime_type=mime,
                    size_bytes=entry.file_size,
                )
                session.add(media)
                session.flush()

                # Link to the message that referenced this filename, if any.
                msg_id = pending_links.get(cid, {}).get(base.lower())
                if msg_id is None:
                    # try the original (pre-collision) basename
                    msg_id = pending_links.get(cid, {}).get(
                        _safe_name(entry.filename).lower()
                    )
                if msg_id is not None:
                    session.execute(
                        update(Message).where(Message.id == msg_id).values(media_id=media.id)
                    )

                media_count += 1
                media_per_chat[cid] = media_per_chat.get(cid, 0) + 1
                done_bytes += entry.file_size

                if i % 25 == 0 or i == len(media_entries) - 1:
                    progress = int(done_bytes / total_media_bytes * 100)
                    _update_job(
                        session, job_id, progress=min(progress, 99),
                        media_found=media_count,
                    )

            # --- 3. Finalise per-chat media counts ---
            for cid, cnt in media_per_chat.items():
                session.execute(update(Chat).where(Chat.id == cid).values(media_count=cnt))
            session.commit()

            _update_job(
                session, job_id, status="done", progress=100, stage="Complete",
                media_found=media_count, messages_found=total_messages,
                chats_found=len(chat_dirs),
            )

        # Remove the raw upload zip now that media is extracted (saves disk on big files).
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass

    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        try:
            _update_job(session, job_id, status="error", error=f"{type(exc).__name__}: {exc}")
        except Exception:
            pass
    finally:
        session.close()
