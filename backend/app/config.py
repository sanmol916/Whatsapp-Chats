"""Application configuration and storage paths.

All paths are resolved relative to the project root so the tool is portable.
"""
from __future__ import annotations

import os
from pathlib import Path

# backend/app/config.py -> project root is two levels up from `app`
BACKEND_DIR = Path(__file__).resolve().parent.parent          # .../backend
PROJECT_ROOT = BACKEND_DIR.parent                             # .../whatsapp-viewer

# Allow overriding the storage location via env var (useful for mounting a big disk).
STORAGE_DIR = Path(os.environ.get("WA_STORAGE_DIR", PROJECT_ROOT / "storage"))

UPLOAD_DIR = STORAGE_DIR / "uploads"     # raw uploaded zips (temporary)
MEDIA_DIR = STORAGE_DIR / "media"        # extracted media, organised per chat
DB_PATH = STORAGE_DIR / "whatsapp.db"

STATIC_DIR = BACKEND_DIR / "static"

# Streaming chunk size used for both upload writes and zip extraction (8 MB).
CHUNK_SIZE = 8 * 1024 * 1024

# Media larger than this are still stored, but flagged; kept generous for videos.
MAX_SINGLE_MEDIA_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB per single file

# File extension buckets used to classify media for the gallery.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".3gp", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO_EXTS = {".opus", ".ogg", ".mp3", ".m4a", ".aac", ".wav", ".amr"}
STICKER_EXTS = {".webp"}  # WhatsApp stickers are webp; disambiguated by filename hints
DOC_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".zip", ".apk", ".vcf"}


def ensure_dirs() -> None:
    """Create all storage directories if they do not exist."""
    for path in (STORAGE_DIR, UPLOAD_DIR, MEDIA_DIR):
        path.mkdir(parents=True, exist_ok=True)


def classify_extension(filename: str) -> str:
    """Return a media_type string based on the file extension."""
    ext = Path(filename).suffix.lower()
    name = filename.lower()
    if ext in IMAGE_EXTS:
        # WhatsApp stickers are webp files usually named STK-*
        if ext == ".webp" and ("sticker" in name or name.startswith("stk")):
            return "sticker"
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in DOC_EXTS:
        return "document"
    return "document"
