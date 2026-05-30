"""Play a streamed video (rgb24 frames + audio) in the terminal.

Builds on the self-contained half-block renderer, ffmpeg frame pipe and ffplay
audio in `render.py`; this module adds network-stream handling and a
single-video playback loop.
"""

from __future__ import annotations

import shutil
import sys
import time

from . import gpu
from .render import (
    AudioPlayer,
    KeyReader,
    VideoSource,
    fit_grid,
    frame_to_ansi,
    frame_to_ascii,
    frame_to_digits,
    frame_to_fullblocks,
    frame_to_matrix,
)
from .resolve import Resolved

# Display modes, cycled with the "v" key.
MODES = ("classic", "ascii", "bw", "digit16", "fullblock", "matrix")
_MODE_LABELS = {
    "classic": "classic",
    "ascii": "ascii",
    "bw": "b&w",
    "digit16": "16-color digits",
    "fullblock": "full-blocks",
    "matrix": "matrix",
}


def _render_body(buf: bytes, w: int, h: int, mode: str) -> str:
    """Render a raw frame in the chosen display mode."""
    if mode == "ascii":
        return frame_to_ascii(buf, w, h, color=True)
    if mode == "bw":
        return frame_to_ascii(buf, w, h, color=False)
    if mode == "digit16":
        return frame_to_digits(buf, w, h)
    if mode == "fullblock":
        return frame_to_fullblocks(buf, w, h)
    if mode == "matrix":
        return frame_to_matrix(buf, w, h)
    return frame_to_ansi(buf, w, h)  # classic colored half-blocks


class StreamVideoSource(VideoSource):
    """VideoSource that reads a network URL, with ffmpeg auto-reconnect.

    Inherits seek support (``start``) from VideoSource, so it can resume at the
    current position after a terminal resize rebuilds the decoder.
    """

    def _ffmpeg_cmd(self, ffmpeg: str) -> list[str]:
        cmd = super()._ffmpeg_cmd(ffmpeg)
        i = cmd.index("-i")  # reconnect flags are input options -> before -i
        reconnect = ["-reconnect", "1", "-reconnect_streamed", "1",
                     "-reconnect_delay_max", "5"]
        return cmd[:i] + reconnect + cmd[i:]


def _status_bar(title: str, paused: bool, mode: str, note: str = "") -> str:
    state = "⏸ paused" if paused else "▶ playing"
    mode_label = _MODE_LABELS.get(mode, mode)
    if note:
        info = f"\x1b[33m{note}\x1b[0m"
    else:
        info = "\x1b[2m[space] pause  [v] mode  [g] gpu  [q] quit\x1b[0m"
    return (
        f"\x1b[1m {title} \x1b[0m  \x1b[36m{state}\x1b[0m"
        f"  \x1b[35m{mode_label}\x1b[0m   {info}"
    )


def _compose(body: str, title: str, paused: bool, mode: str, note: str = "") -> str:
    """Full-screen ANSI frame: centered body + a one-line status bar."""
    term_h = shutil.get_terminal_size(fallback=(80, 24)).lines
    avail = max(term_h - 1, 1)  # reserve the last line for the status bar

    body_lines = body.split("\n")
    if len(body_lines) > avail:
        body_lines = body_lines[:avail]

    top = max(0, (avail - len(body_lines)) // 2)
    lines: list[str] = [""] * top + body_lines
    while len(lines) < term_h - 1:
        lines.append("")
    lines = lines[: term_h - 1]
    lines.append(_status_bar(title, paused, mode, note))

    parts = ["\x1b[H"]
    for i, line in enumerate(lines):
        parts.append("\x1b[0m" + line + "\x1b[0m\x1b[K")
        if i < len(lines) - 1:
            parts.append("\n")
    return "".join(parts)


def play(resolved: Resolved, want_audio: bool = True) -> None:
    """Stream and play the resolved video in the terminal until it ends or 'q'."""
    img_proto = gpu.detect_image_protocol()  # "kitty" or None
    image_mode = False                       # toggled with "g"
    mode_idx = 0                             # index into MODES (block renderers)
    w = h = 0                                # current decoder dimensions
    paused = False
    last_buf: bytes | None = None
    notice = ""
    notice_until = 0.0

    def make_decoder(start: float) -> StreamVideoSource:
        """Build a decoder for the current state (image vs block) at `start`."""
        nonlocal w, h
        sz = shutil.get_terminal_size(fallback=(80, 24))
        if image_mode and img_proto:
            px = gpu.terminal_pixel_size() or (sz.columns * 10, sz.lines * 20)
            w, h = gpu.fit_pixels(resolved.width, resolved.height, px[0], px[1])
            return StreamVideoSource(
                resolved.video_url, w, h, fps=resolved.fps, start=start, pixels=True
            )
        w, h = fit_grid(
            resolved.width, resolved.height, sz.columns, sz.lines, reserve_bottom_lines=1
        )
        return StreamVideoSource(resolved.video_url, w, h, fps=resolved.fps, start=start)

    def render_current() -> None:
        if last_buf is None:
            return
        if image_mode and img_proto:
            sys.stdout.write(gpu.kitty_frame(last_buf, w, h))
        else:
            note = notice if time.time() < notice_until else ""
            body = _render_body(last_buf, w, h, MODES[mode_idx])
            sys.stdout.write(_compose(body, resolved.title, paused, MODES[mode_idx], note))
        sys.stdout.flush()

    audio: AudioPlayer | None = None
    if want_audio and resolved.audio_url:
        audio = AudioPlayer(resolved.audio_url)

    sys.stdout.write("\x1b[?25l\x1b[2J")  # hide cursor, clear
    sys.stdout.flush()

    key_reader = KeyReader()
    key_reader.start()

    video = make_decoder(0.0)
    term_size = shutil.get_terminal_size(fallback=(80, 24))
    term_size = (term_size.columns, term_size.lines)
    last = time.time()
    play_elapsed = 0.0
    frame_idx = 0
    try:
        first = video.read_frame()  # prime first frame
        if first is not None:
            last_buf = first
            frame_idx = 1
        render_current()
        if audio:
            audio.start(0.0)

        while True:
            now = time.time()
            dt = now - last
            last = now
            dirty = False

            # Terminal resize -> rebuild decoder at current size + position.
            sz = shutil.get_terminal_size(fallback=(80, 24))
            if (sz.columns, sz.lines) != term_size:
                term_size = (sz.columns, sz.lines)
                video.close()
                video = make_decoder(play_elapsed)
                frame_idx = int(play_elapsed * video.fps)
                last_buf = video.read_frame()
                if last_buf is not None:
                    frame_idx += 1
                sys.stdout.write("\x1b[2J")
                dirty = True

            # Advance video to the wall-clock position (drop frames if behind).
            if not paused:
                play_elapsed += dt
                target = play_elapsed * video.fps
                latest: bytes | None = None
                while frame_idx < target:
                    buf = video.read_frame()
                    if buf is None:  # stream ended
                        if latest is not None:
                            last_buf = latest
                            render_current()
                        return
                    latest = buf
                    frame_idx += 1
                if latest is not None:
                    last_buf = latest
                    dirty = True

            key = key_reader.get_key()
            while key is not None:
                if key in ("q", "QUIT", "ESC"):
                    return
                if key in ("SPACE", " "):
                    paused = not paused
                    if audio:
                        audio.stop() if paused else audio.start(play_elapsed)
                    dirty = True
                elif key == "v":
                    mode_idx = (mode_idx + 1) % len(MODES)
                    dirty = True
                elif key == "g":
                    if img_proto is None:
                        notice = "GPU image mode needs kitty / WezTerm / Ghostty"
                        notice_until = now + 2.5
                    else:
                        image_mode = not image_mode
                        video.close()
                        video = make_decoder(play_elapsed)
                        frame_idx = int(play_elapsed * video.fps)
                        if img_proto == "kitty":
                            sys.stdout.write("\x1b_Ga=d\x1b\\")  # clear images
                        sys.stdout.write("\x1b[2J")
                        last_buf = video.read_frame()
                        if last_buf is not None:
                            frame_idx += 1
                    dirty = True
                key = key_reader.get_key()

            if time.time() < notice_until:
                dirty = True  # keep the notice visible briefly

            if dirty:
                render_current()

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
        if img_proto == "kitty":
            sys.stdout.write("\x1b_Ga=d\x1b\\")  # delete any leftover images
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")  # show cursor, clear
        sys.stdout.flush()
