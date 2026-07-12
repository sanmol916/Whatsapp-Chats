"""WhatsApp chat export parser.

Handles the two main export dialects:

  iOS      [2023-01-15, 10:30:45] John Doe: Hello
           [15/01/2023, 10:30:45 PM] +1 234 567 8900: ‎<attached: 00001-PHOTO.jpg>

  Android  15/01/2023, 10:30 - John Doe: Hello
           1/15/23, 10:30 AM - +1 234 567 8900: IMG-20230115-WA0001.jpg (file attached)

Also copes with:
  * multi-line messages (continuation lines have no timestamp header)
  * system / notification lines (no sender, e.g. encryption notice, group events)
  * "<Media omitted>" / "image omitted" style markers when media was not exported
  * invisible LTR/RTL marks that WhatsApp sprinkles into exports
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Invisible bidi / formatting characters WhatsApp injects.
_INVISIBLE = "\u200e\u200f\u202a\u202b\u202c\u2066\u2067\u2068\u2069\ufeff"
_INVISIBLE_RE = re.compile("[" + _INVISIBLE + "]")

# iOS: leading "[date, time] "
_IOS_RE = re.compile(
    r"^\["
    r"(?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4})"
    r",?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[APap]\.?[Mm]\.?)?)"
    r"\]\s?(?P<rest>.*)$"
)

# Android: "date, time - "
_ANDROID_RE = re.compile(
    r"^"
    r"(?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4})"
    r",?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[APap]\.?[Mm]\.?)?)"
    r"\s[-\u2013]\s(?P<rest>.*)$"
)

# Media reference patterns inside a message body.
_ATTACHED_RE = re.compile(r"<attached:\s*(?P<name>[^>]+)>", re.IGNORECASE)
_FILE_ATTACHED_RE = re.compile(r"(?P<name>[\w\-. ]+\.\w{2,5})\s*\(file attached\)", re.IGNORECASE)
_OMITTED_RE = re.compile(
    r"\b("
    r"image|video|audio|voice message|sticker|gif|document|contact card|photo"
    r")\s+omitted\b",
    re.IGNORECASE,
)
_MEDIA_OMITTED_RE = re.compile(r"<\s*media omitted\s*>", re.IGNORECASE)

# A sender that is really a raw phone number (contact not saved).
_PHONE_RE = re.compile(r"^\+?[\d][\d\s\-().]{4,}$")


@dataclass
class ParsedMessage:
    timestamp: datetime | None
    sender_name: str
    sender_number: str
    message_type: str  # text | media | system
    content: str
    media_filename: str | None = None


@dataclass
class ParsedChat:
    messages: list[ParsedMessage] = field(default_factory=list)
    senders: set[str] = field(default_factory=set)  # display names of real (non-system) senders


def strip_invisibles(text: str) -> str:
    return _INVISIBLE_RE.sub("", text)


def _parse_datetime(date_str: str, time_str: str) -> datetime | None:
    """Best-effort datetime parsing across locales/formats."""
    date_str = date_str.strip()
    time_str = time_str.strip().upper().replace(".", "")
    time_str = re.sub(r"\s+", " ", time_str)

    # Split date into 3 numeric parts.
    parts = re.split(r"[./-]", date_str)
    if len(parts) != 3:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None

    # Determine year/month/day ordering.
    if len(parts[0]) == 4:  # YYYY-MM-DD
        year, month, day = nums
    else:
        a, b, c = nums
        year = c if c > 31 else (2000 + c if c < 100 else c)
        # a and b are day/month in some order.
        if a > 12 >= b or a > 12:
            day, month = a, b            # day-first (a can't be a month)
        elif b > 12:
            month, day = a, b            # month-first (b can't be a month)
        else:
            day, month = a, b            # ambiguous -> default to day-first (WhatsApp default)
    if year < 100:
        year += 2000

    # Parse time (12h or 24h).
    ampm = None
    m = re.search(r"\b([AP]M)\b", time_str)
    if m:
        ampm = m.group(1)
        time_str = time_str.replace(ampm, "").strip()
    tparts = time_str.split(":")
    try:
        hour = int(tparts[0])
        minute = int(tparts[1]) if len(tparts) > 1 else 0
        second = int(tparts[2]) if len(tparts) > 2 else 0
    except (ValueError, IndexError):
        return None
    if ampm == "PM" and hour < 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0

    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def _split_sender_body(rest: str) -> tuple[str | None, str]:
    """Split "Sender: body" -> (sender, body). No colon -> system message."""
    idx = rest.find(": ")
    if idx == -1:
        # Could still be "Sender:" with empty body at end of line.
        if rest.endswith(":") and "\n" not in rest and len(rest) < 60:
            return rest[:-1].strip(), ""
        return None, rest.strip()
    sender = rest[:idx].strip()
    body = rest[idx + 2 :]
    # Guard: senders don't contain newlines and are reasonably short.
    if "\n" in sender or len(sender) > 100:
        return None, rest.strip()
    return sender, body


def _extract_number(sender: str) -> tuple[str, str]:
    """Return (display_name, phone_number). If sender is a raw number, both reflect it."""
    s = sender.strip()
    if _PHONE_RE.match(s):
        digits = re.sub(r"[^\d+]", "", s)
        return s, digits
    return s, ""


def _detect_media(body: str) -> tuple[str, str | None, bool]:
    """Return (message_type, media_filename, is_omitted)."""
    m = _ATTACHED_RE.search(body)
    if m:
        return "media", m.group("name").strip(), False
    m = _FILE_ATTACHED_RE.search(body)
    if m:
        return "media", m.group("name").strip(), False
    if _MEDIA_OMITTED_RE.search(body) or _OMITTED_RE.search(body):
        return "media", None, True
    return "text", None, False


def guess_chat_name(txt_path: str) -> str:
    """Infer a human chat name from the txt filename / containing folder."""
    p = Path(txt_path)
    stem = p.stem
    # iOS puts messages in "_chat.txt" inside a folder named after the chat.
    if stem.lower() in {"_chat", "chat"}:
        folder = p.parent.name
        stem = folder or stem
    # Common prefixes.
    for prefix in ("WhatsApp Chat with ", "WhatsApp Chat - ", "WhatsApp Chat "):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    return strip_invisibles(stem).strip() or "WhatsApp Chat"


def parse_chat_text(text: str) -> ParsedChat:
    """Parse the full text of a WhatsApp chat export .txt file."""
    result = ParsedChat()
    current: ParsedMessage | None = None

    def flush():
        nonlocal current
        if current is not None:
            current.content = current.content.rstrip("\n")
            result.messages.append(current)
            current = None

    for raw_line in text.splitlines():
        line = strip_invisibles(raw_line)
        header = _IOS_RE.match(line) or _ANDROID_RE.match(line)
        if not header:
            # Continuation of the previous message (multi-line).
            if current is not None:
                current.content += "\n" + line
            continue

        flush()
        ts = _parse_datetime(header.group("date"), header.group("time"))
        rest = header.group("rest")
        sender, body = _split_sender_body(rest)

        if sender is None:
            current = ParsedMessage(
                timestamp=ts,
                sender_name="",
                sender_number="",
                message_type="system",
                content=body,
            )
            continue

        name, number = _extract_number(sender)
        result.senders.add(name)
        mtype, media_name, omitted = _detect_media(body)
        content = body
        if mtype == "media" and media_name:
            # Remove the raw attachment marker from the visible caption text.
            content = _ATTACHED_RE.sub("", content)
            content = _FILE_ATTACHED_RE.sub("", content)
            content = content.strip()
        elif mtype == "media" and omitted:
            content = ""  # a placeholder bubble; UI shows "media not included"

        current = ParsedMessage(
            timestamp=ts,
            sender_name=name,
            sender_number=number,
            message_type=mtype,
            content=content,
            media_filename=media_name,
        )

    flush()
    return result
