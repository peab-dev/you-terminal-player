"""Play a streamed video (rgb24 frames + audio) in the terminal.

Builds on the self-contained half-block renderer, ffmpeg frame pipe and ffplay
audio in `render.py`; this module adds network-stream handling and a
single-video playback loop.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time

from .render import (
    AudioPlayer,
    KeyReader,
    VideoSource,
    fit_grid,
    frame_to_ansi,
)
from .resolve import Resolved


class StreamVideoSource(VideoSource):
    """VideoSource that reads a network URL, with ffmpeg auto-reconnect."""

    def _start(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return
        self.proc = subprocess.Popen(
            [ffmpeg, "-loglevel", "quiet",
             "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
             "-i", str(self.path),
             "-vf", f"scale={self.width}:{self.height * 2},fps={self.fps}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )


def _status_bar(title: str, paused: bool) -> str:
    state = "⏸ paused" if paused else "▶ playing"
    keys = "[space] pause  [q] quit"
    return f"\x1b[1m {title} \x1b[0m  \x1b[36m{state}\x1b[0m\x1b[2m   {keys}\x1b[0m"


def _compose(body: str, title: str, paused: bool) -> str:
    """Full-screen ANSI frame: centered body + a one-line status bar."""
    size = shutil.get_terminal_size(fallback=(80, 24))
    term_h = size.lines
    avail = max(term_h - 1, 1)  # reserve the last line for the status bar

    body_lines = body.split("\n")
    if len(body_lines) > avail:
        body_lines = body_lines[:avail]

    top = max(0, (avail - len(body_lines)) // 2)
    lines: list[str] = [""] * top + body_lines
    while len(lines) < term_h - 1:
        lines.append("")
    lines = lines[: term_h - 1]
    lines.append(_status_bar(title, paused))

    parts = ["\x1b[H"]
    for i, line in enumerate(lines):
        parts.append("\x1b[0m" + line + "\x1b[0m\x1b[K")
        if i < len(lines) - 1:
            parts.append("\n")
    return "".join(parts)


def play(resolved: Resolved, want_audio: bool = True) -> None:
    """Stream and play the resolved video in the terminal until it ends or 'q'."""
    size = shutil.get_terminal_size(fallback=(80, 24))
    w, h = fit_grid(
        resolved.width, resolved.height, size.columns, size.lines,
        reserve_bottom_lines=1,
    )

    video = StreamVideoSource(resolved.video_url, w, h, fps=resolved.fps)
    audio: AudioPlayer | None = None
    if want_audio and resolved.audio_url:
        audio = AudioPlayer(resolved.audio_url)

    body = ""
    sys.stdout.write("\x1b[?25l\x1b[2J")  # hide cursor, clear
    sys.stdout.flush()

    key_reader = KeyReader()
    key_reader.start()

    paused = False
    last = time.time()
    play_elapsed = 0.0
    frame_idx = 0
    try:
        # Prime the first frame so something shows while audio spins up.
        first = video.read_frame()
        if first is not None:
            body = frame_to_ansi(first, w, h)
            frame_idx = 1
        sys.stdout.write(_compose(body, resolved.title, paused))
        sys.stdout.flush()
        if audio:
            audio.start(0.0)

        while True:
            now = time.time()
            dt = now - last
            last = now
            redraw = False

            if not paused:
                play_elapsed += dt
                target = play_elapsed * video.fps
                latest: bytes | None = None
                while frame_idx < target:
                    buf = video.read_frame()
                    if buf is None:  # stream ended
                        if latest is not None:
                            body = frame_to_ansi(latest, w, h)
                            sys.stdout.write(_compose(body, resolved.title, paused))
                            sys.stdout.flush()
                        return
                    latest = buf
                    frame_idx += 1
                if latest is not None:
                    body = frame_to_ansi(latest, w, h)
                    redraw = True

            key = key_reader.get_key()
            while key is not None:
                if key in ("q", "QUIT", "ESC"):
                    return
                if key in ("SPACE", " "):
                    paused = not paused
                    if audio:
                        if paused:
                            audio.stop()
                        else:
                            audio.start(play_elapsed)
                    redraw = True
                key = key_reader.get_key()

            if redraw:
                sys.stdout.write(_compose(body, resolved.title, paused))
                sys.stdout.flush()

            if not paused:
                time.sleep(max(0.0, 1.0 / video.fps - (time.time() - now)))
            else:
                time.sleep(0.02)

    except KeyboardInterrupt:
        pass
    finally:
        if audio:
            audio.stop()
        video.close()
        key_reader.stop()
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")  # show cursor, clear
        sys.stdout.flush()
