"""Generate a synthetic WhatsApp export .zip for end-to-end testing.

Produces an Android-style export containing a chat .txt plus a few small but
*real* media files (a valid PNG, a tiny WAV, a text document) so media
extraction, classification and serving can be verified.
"""
import struct
import zipfile
import zlib
from pathlib import Path

OUT = Path(__file__).parent / "sample_export.zip"


def png_bytes(w=8, h=8, rgb=(37, 211, 102)) -> bytes:
    """Build a minimal valid PNG (solid colour)."""
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = b""
    for _ in range(h):
        raw += b"\x00" + bytes(rgb) * w
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def wav_bytes(seconds=1, rate=8000) -> bytes:
    """Build a minimal valid silent WAV file."""
    n = seconds * rate
    data = b"\x00\x00" * n
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


CHAT = """15/01/2024, 09:30 - Messages and calls are end-to-end encrypted. No one outside of this chat, not even WhatsApp, can read or listen to them.
15/01/2024, 09:31 - Alice Johnson: Good morning! How are you today?
15/01/2024, 09:32 - +1 555 010 2020: Doing great, thanks for asking 😊
15/01/2024, 09:33 - Alice Johnson: Check out this photo from the trip
15/01/2024, 09:33 - Alice Johnson: IMG-20240115-WA0001.png (file attached)
15/01/2024, 09:34 - +1 555 010 2020: Wow that looks amazing!
15/01/2024, 09:35 - Alice Johnson: Here is the voice note
15/01/2024, 09:35 - Alice Johnson: PTT-20240115-WA0002.wav (file attached)
16/01/2024, 18:05 - +1 555 010 2020: Sending over the report
16/01/2024, 18:05 - +1 555 010 2020: Quarterly-Report.txt (file attached)
16/01/2024, 18:06 - Alice Johnson: Got it, thanks!
16/01/2024, 18:07 - +1 555 010 2020: <Media omitted>
16/01/2024, 18:10 - Alice Johnson: See you tomorrow. Visit https://example.com for details
"""


def main():
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("WhatsApp Chat with Alice Johnson.txt", CHAT)
        z.writestr("IMG-20240115-WA0001.png", png_bytes())
        z.writestr("PTT-20240115-WA0002.wav", wav_bytes())
        z.writestr("Quarterly-Report.txt", "Q4 numbers look strong.\nRevenue up 20%.\n")
    print("Wrote", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
