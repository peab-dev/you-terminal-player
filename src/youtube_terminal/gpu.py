"""GPU image-protocol output for terminals that render real pixels.

Currently supports the kitty graphics protocol (kitty, WezTerm, Ghostty), which
the terminal draws with its GPU — true video, not character cells. Detection
falls back to None on terminals without support (e.g. Apple Terminal), so the
player can keep using the half-block / ASCII renderers.
"""

from __future__ import annotations

import base64
import fcntl
import os
import struct
import sys
import termios


def detect_image_protocol() -> str | None:
    """Return "kitty" if the terminal supports the kitty graphics protocol."""
    term = os.environ.get("TERM", "")
    prog = os.environ.get("TERM_PROGRAM", "")
    if os.environ.get("KITTY_WINDOW_ID") or term == "xterm-kitty":
        return "kitty"
    if prog in ("WezTerm", "ghostty") or "ghostty" in term:
        return "kitty"  # both implement the kitty graphics protocol
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
