"""Self-contained terminal half-block rendering, video and audio helpers.

These building blocks keep this project independent (no external project
dependency). They turn raw rgb24 frames into colored half-block ANSI, stream a
video through ffmpeg, play its audio through ffplay, fit a source into the
terminal grid, and read keys without blocking.
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path


class KeyReader:
    """Non-blocking keyboard reader running in a background thread (Unix/macOS)."""

    def __init__(self):
        self._queue: queue.Queue[str] = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._read_keys, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_key(self) -> str | None:
        """Returns the next key if available, otherwise None."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def _read_keys(self):
        import termios
        import tty

        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
        except Exception:
            return  # no real TTY (e.g. piped) — just don't read keys
        try:
            # cbreak (not raw): one key at a time without line buffering, but
            # keep output post-processing (OPOST/ONLCR) on so "\n" still
            # carriage-returns and the picture doesn't stair-step.
            tty.setcbreak(fd)
            while self._running:
                try:
                    ch = sys.stdin.read(1)
                    if ch == "\x1b":  # escape sequence (arrows etc.)
                        ch2 = sys.stdin.read(1)
                        if ch2 == "[":
                            ch3 = sys.stdin.read(1)
                            if ch3 == "A":
                                self._queue.put("UP")
                            elif ch3 == "B":
                                self._queue.put("DOWN")
                            elif ch3 == "C":
                                self._queue.put("RIGHT")
                            elif ch3 == "D":
                                self._queue.put("LEFT")
                            else:
                                self._queue.put("ESC")
                        else:
                            self._queue.put("ESC")
                    elif ch == "\x03":  # Ctrl+C
                        self._queue.put("QUIT")
                    elif ch in ("\r", "\n"):
                        self._queue.put("ENTER")
                    elif ch == " ":
                        self._queue.put("SPACE")
                    else:
                        self._queue.put(ch.lower())
                except Exception:
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def fit_grid(
    src_w: int,
    src_h: int,
    term_w: int,
    term_h: int,
    reserve_bottom_lines: int = 0,
    max_width: int = 100_000,
    max_height: int = 100_000,
) -> tuple[int, int]:
    """Fit a (src_w x src_h) source into terminal cells, preserving aspect.

    Each cell holds two stacked half-block pixels, so it covers one column and
    two rows of the source. Returns (width_cells, height_cells), guaranteed to
    fit within the columns and the rows the renderer will actually display.
    """
    available_width = max(term_w - 2, 1)
    row_budget = max(term_h - reserve_bottom_lines, 1)
    available_height = max(row_budget - 2, 1)

    # On small terminals, be a touch more conservative vertically.
    if term_h <= 40:
        available_height = max(int(term_h * 0.65) - reserve_bottom_lines, 1)

    # Never claim more rows than the renderer will display.
    available_height = min(available_height, row_budget)

    aspect = src_h / src_w  # two source rows per cell -> divide by 2 below
    fit_width = min(available_width, max_width)
    fit_height_from_width = int(fit_width * aspect / 2)
    fit_height = min(available_height, max_height)
    fit_width_from_height = int(fit_height * 2 / aspect) if aspect else fit_width

    if fit_height_from_width <= available_height:
        width, height = fit_width, fit_height_from_width
    else:
        width, height = fit_width_from_height, fit_height

    # Clamp to the available space (a hard-coded fallback would overflow tiny
    # terminals and get the image truncated).
    width = max(1, min(width, available_width))
    height = max(1, min(height, available_height))
    return width, height


def frame_to_ansi(buf: bytes, width: int, height: int) -> str:
    """Render a raw rgb24 frame (width x height*2 pixels) to an ANSI string.

    Each terminal cell is an upper half-block '▀': the top source pixel becomes
    the foreground, the bottom pixel the background, doubling vertical
    resolution. Written straight to the terminal (no Rich parsing) so high
    resolutions can still play at full frame rate.
    """
    row_stride = width * 3
    out: list[str] = []
    for ty in range(height):
        top = ty * 2 * row_stride
        bot = (ty * 2 + 1) * row_stride
        cells: list[str] = []
        for tx in range(width):
            ti = top + tx * 3
            bi = bot + tx * 3
            cells.append(
                f"\x1b[38;2;{buf[ti]};{buf[ti + 1]};{buf[ti + 2]};"
                f"48;2;{buf[bi]};{buf[bi + 1]};{buf[bi + 2]}m▀"
            )
        out.append("".join(cells))
    return "\n".join(out)


# Brightness ramp for ASCII mode, dark -> light (classic "oldschool" look).
_ASCII_RAMP = " .:-=+*#%@"


def frame_to_ascii(buf: bytes, width: int, height: int, color: bool = True) -> str:
    """Render a raw rgb24 frame as ASCII art (one character per cell).

    The two stacked pixels of each cell are averaged (so the aspect ratio stays
    correct), then mapped to a character by brightness. With ``color`` the
    character takes the pixel's truecolor; otherwise a grayscale (black & white)
    shade based on its luminance.
    """
    ramp = _ASCII_RAMP
    last = len(ramp) - 1
    row_stride = width * 3
    out: list[str] = []
    for ty in range(height):
        top = ty * 2 * row_stride
        bot = (ty * 2 + 1) * row_stride
        cells: list[str] = []
        for tx in range(width):
            ti = top + tx * 3
            bi = bot + tx * 3
            r = (buf[ti] + buf[bi]) >> 1
            g = (buf[ti + 1] + buf[bi + 1]) >> 1
            b = (buf[ti + 2] + buf[bi + 2]) >> 1
            lum = (r * 299 + g * 587 + b * 114) // 1000
            ch = ramp[lum * last // 255]
            if color:
                cells.append(f"\x1b[38;2;{r};{g};{b}m{ch}")
            else:
                cells.append(f"\x1b[38;2;{lum};{lum};{lum}m{ch}")
        out.append("".join(cells))
    return "\n".join(out)


class VideoSource:
    """Streams a video as raw rgb24 half-block frames using an ffmpeg pipe.

    ffmpeg scales/resamples to exactly the cell grid we need (width columns x
    height*2 rows) at the requested fps, so each read is one ready frame.
    """

    def __init__(self, path: str | Path, width: int, height: int, fps: float = 24.0):
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_bytes = width * (height * 2) * 3
        self.proc: subprocess.Popen[bytes] | None = None
        self._start()

    def _start(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return
        self.proc = subprocess.Popen(
            [ffmpeg, "-loglevel", "quiet", "-i", str(self.path),
             "-vf", f"scale={self.width}:{self.height * 2},fps={self.fps}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

    def read_frame(self) -> bytes | None:
        """Read exactly one frame, or None at end-of-stream."""
        if not self.proc or not self.proc.stdout:
            return None
        buf = bytearray()
        while len(buf) < self.frame_bytes:
            chunk = self.proc.stdout.read(self.frame_bytes - len(buf))
            if not chunk:
                return None
            buf += chunk
        return bytes(buf)

    def restart(self) -> None:
        """Rewind by relaunching ffmpeg from the start (simple loop)."""
        self.close()
        self._start()

    def close(self) -> None:
        if self.proc:
            try:
                if self.proc.stdout:
                    self.proc.stdout.close()
                self.proc.kill()
                self.proc.wait(timeout=1)
            except Exception:
                pass
            self.proc = None


def has_audio(path: str | Path) -> bool:
    """True if the file/URL has at least one audio stream (per ffprobe)."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return False
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


class AudioPlayer:
    """Plays an audio track via an ffplay subprocess (no window).

    Decoupled from frame rendering: started/stopped when the video clock is
    reset so audio and picture stay in sync. ffplay's -ss enables resume.
    """

    def __init__(self, path: str | Path):
        self.path = path
        self.available = has_audio(path) and shutil.which("ffplay") is not None
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self, offset: float = 0.0) -> None:
        if not self.available:
            return
        self.stop()
        ffplay = shutil.which("ffplay")
        self.proc = subprocess.Popen(
            [ffplay, "-nodisp", "-autoexit", "-vn", "-loglevel", "quiet",
             "-ss", f"{max(0.0, offset):.3f}", str(self.path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self.proc:
            try:
                self.proc.kill()
                self.proc.wait(timeout=1)
            except Exception:
                pass
            self.proc = None
