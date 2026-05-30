"""Resolve a YouTube URL to direct stream URLs and metadata via yt-dlp."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass


class ResolveError(RuntimeError):
    """Raised when a URL cannot be resolved into a playable stream."""


@dataclass
class Resolved:
    title: str
    video_url: str
    audio_url: str | None
    width: int
    height: int
    fps: float


def _format_string(max_height: int | None) -> str:
    """Build a yt-dlp -f selector. None means 'best available'."""
    if max_height is None:
        return "bv*+ba/b"
    return f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b"


# YouTube keeps changing which internal "player clients" expose formats. When
# the default yields "No video formats found", these alternatives often work.
_PLAYER_CLIENT_FALLBACKS = ["tv", "web_safari", "mweb", "ios", "android"]


def _run_ytdlp(
    url: str,
    max_height: int | None,
    cookies_from_browser: str | None,
    player_client: str | None,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "yt_dlp", "-f", _format_string(max_height),
           "-j", "--no-warnings", "--no-playlist"]
    # Enable the EJS JavaScript challenge solver (needed for YouTube's "n"
    # signature) using Node. Pass the resolved path so it works even when Node
    # is only on an interactive-shell PATH (e.g. via nvm).
    node = shutil.which("node")
    cmd += ["--js-runtimes", f"node:{node}" if node else "node"]
    if cookies_from_browser:
        cmd += ["--cookies-from-browser", cookies_from_browser]
    if player_client:
        cmd += ["--extractor-args", f"youtube:player_client={player_client}"]
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def resolve(
    url: str,
    max_height: int | None = 720,
    cookies_from_browser: str | None = None,
    player_client: str | None = None,
) -> Resolved:
    """Return direct video/audio stream URLs plus title, size and fps.

    cookies_from_browser: pass a browser name (e.g. "safari", "chrome") to let
    yt-dlp use its cookies. YouTube often demands this ("Sign in to confirm
    you're not a bot") when no session is present.

    player_client: force a specific yt-dlp YouTube player client. If omitted and
    the default reports "No video formats found", a few known-good clients are
    tried automatically.
    """
    if importlib.util.find_spec("yt_dlp") is None:
        raise ResolveError("yt-dlp is not installed (pip install yt-dlp).")

    # First the default (or an explicit client); then format-only fallbacks.
    attempts = [player_client] if player_client else [None, *_PLAYER_CLIENT_FALLBACKS]

    last_msg = "unknown error"
    proc = None
    for client in attempts:
        try:
            proc = _run_ytdlp(url, max_height, cookies_from_browser, client)
        except subprocess.TimeoutExpired as exc:
            raise ResolveError("yt-dlp timed out while resolving the URL.") from exc

        if proc.returncode == 0 and proc.stdout.strip():
            break  # success

        detail = proc.stderr.strip().splitlines()
        last_msg = detail[-1] if detail else "unknown error"

        # Missing cookies can't be fixed by switching clients — fail fast.
        if "not a bot" in last_msg or "Sign in to confirm" in last_msg:
            raise ResolveError(
                "Could not resolve video: " + last_msg
                + "\nLog in to YouTube in your browser, then add cookies, e.g.:  "
                'yt --cookies-from-browser safari "<url>"'
            )
        # Only the "no formats" case is worth retrying with another client.
        if "No video formats" not in last_msg and "Requested format" not in last_msg:
            break

    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        raise ResolveError(
            f"Could not resolve video: {last_msg}"
            "\nTry a specific client, e.g.:  yt --player-client tv \"<url>\""
            "\nor update yt-dlp:  pip install -U --pre yt-dlp"
        )

    info = json.loads(proc.stdout)

    title = info.get("title") or url
    video_url: str | None = None
    audio_url: str | None = None
    width = info.get("width") or 0
    height = info.get("height") or 0
    fps = info.get("fps")

    requested = info.get("requested_formats")
    if requested:
        for fmt in requested:
            if fmt.get("vcodec") not in (None, "none"):
                video_url = fmt.get("url")
                width = fmt.get("width") or width
                height = fmt.get("height") or height
                fps = fmt.get("fps") or fps
            elif fmt.get("acodec") not in (None, "none"):
                audio_url = fmt.get("url")
    else:
        # Single (muxed) stream: same URL carries both video and audio.
        video_url = info.get("url")
        audio_url = info.get("url")

    if not video_url:
        raise ResolveError("No playable video stream found for this URL.")

    if not width or not height:
        width, height = 1280, 720  # safe default; renderer rescales anyway

    return Resolved(
        title=title,
        video_url=video_url,
        audio_url=audio_url,
        width=int(width),
        height=int(height),
        fps=float(fps) if fps else 24.0,
    )
