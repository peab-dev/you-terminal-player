"""GPU image-protocol output for terminals that render real pixels.

Supports the kitty graphics protocol (kitty, WezTerm, Ghostty) and the iTerm2
inline-image protocol (iTerm2) — both let the terminal draw true pixel video
with its GPU instead of character cells. Detection falls back to None on
terminals without support (e.g. Apple Terminal), so the player keeps using the
half-block / ASCII renderers.
"""

from __future__ import annotations

import base64
import fcntl
import os
import struct
import sys
import termios
import zlib


def detect_image_protocol() -> str | None:
    """Return "kitty", "iterm", or None depending on terminal support."""
    term = os.environ.get("TERM", "")
    prog = os.environ.get("TERM_PROGRAM", "")
    if os.environ.get("KITTY_WINDOW_ID") or term == "xterm-kitty":
        return "kitty"
    if prog in ("WezTerm", "ghostty") or "ghostty" in term:
        return "kitty"  # both implement the kitty graphics protocol
    if prog == "iTerm.app":
        return "iterm"
    return None


def terminal_pixel_size() -> tuple[int, int] | None:
    """Return the terminal's (width, height) in pixels via TIOCGWINSZ, if known."""
    try:
        packed = fcntl.ioctl(
            sys.stdout.fileno(), termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0)
        )
        _rows, _cols, xpix, ypix = struct.unpack("HHHH", packed)
        if xpix > 0 and ypix > 0:
            return xpix, ypix
    except Exception:
        pass
    return None


def fit_pixels(src_w: int, src_h: int, max_w: int, max_h: int) -> tuple[int, int]:
    """Largest (w, h) <= (max_w, max_h) keeping src aspect; even dimensions."""
    scale = min(max_w / src_w, max_h / src_h)
    w = max(2, int(src_w * scale) & ~1)
    h = max(2, int(src_h * scale) & ~1)
    return w, h


def kitty_frame(rgb: bytes, width: int, height: int) -> str:
    """Build a kitty-graphics escape sequence that draws one RGB frame at home.

    Deletes the previous image first and redraws at the top-left cell, so
    successive frames play in place.
    """
    payload = base64.b64encode(rgb)
    parts = ["\x1b_Ga=d\x1b\\", "\x1b[H"]  # delete all images, cursor home
    chunk = 4096
    i = 0
    first = True
    n = len(payload)
    while i < n:
        piece = payload[i:i + chunk].decode("ascii")
        i += chunk
        more = 1 if i < n else 0
        if first:
            ctrl = f"a=T,f=24,s={width},v={height},q=2,m={more}"
            first = False
        else:
            ctrl = f"m={more}"
        parts.append(f"\x1b_G{ctrl};{piece}\x1b\\")
    return "".join(parts)


def _png(rgb: bytes, width: int, height: int) -> bytes:
    """Encode raw rgb24 bytes to a minimal PNG (stdlib only, no Pillow)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (none) per scanline
        raw += rgb[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 1))  # level 1 = fast
        + chunk(b"IEND", b"")
    )


def iterm_frame(rgb: bytes, width: int, height: int, cols: int, rows: int) -> str:
    """Build an iTerm2 inline-image escape that draws one RGB frame at home.

    The frame is PNG-encoded and scaled into a cols x rows cell box (aspect
    preserved), redrawn each frame from the top-left for in-place playback.
    """
    png = _png(rgb, width, height)
    b64 = base64.b64encode(png).decode("ascii")
    args = f"inline=1;width={cols};height={rows};preserveAspectRatio=1;size={len(png)}"
    return f"\x1b[H\x1b]1337;File={args}:{b64}\x07"
