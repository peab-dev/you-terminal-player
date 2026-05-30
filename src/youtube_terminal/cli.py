"""Command-line entry point for the `yt` command."""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys

from .player import play
from .resolve import ResolveError, resolve

_RES_CHOICES = {"360": 360, "480": 480, "720": 720, "1080": 1080, "best": None}
_DEFAULT_URL = "https://www.youtube.com/watch?v=V014WV2l-Uk"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="yt",
        description="Play a YouTube video in the terminal as colored half-blocks, with sound.",
    )
    parser.add_argument(
        "url", nargs="?", default=_DEFAULT_URL,
        help="YouTube video URL (without one, a default video is played)",
    )
    parser.add_argument(
        "--res", choices=sorted(_RES_CHOICES), default="720",
        help="Maximum source resolution to stream (default: 720)",
    )
    parser.add_argument(
        "--no-audio", action="store_true", help="Play without the soundtrack",
    )
    parser.add_argument(
        "--cookies-from-browser", metavar="BROWSER", default=None,
        help="Use cookies from this browser (safari, chrome, firefox, ...) if "
             "YouTube asks to confirm you're not a bot",
    )
    parser.add_argument(
        "--player-client", metavar="CLIENT", default=None,
        help="Force a yt-dlp YouTube player client (e.g. tv, web_safari, mweb, "
             "ios). Use if you see 'No video formats found'.",
    )
    args = parser.parse_args()

    missing = [t for t in ("ffmpeg", "ffplay") if not shutil.which(t)]
    if missing:
        print(f"Error: required tool(s) not found on PATH: {', '.join(missing)}")
        print("Install ffmpeg (provides both ffmpeg and ffplay), e.g. brew install ffmpeg.")
        sys.exit(1)
    if importlib.util.find_spec("yt_dlp") is None:
        print("Error: yt-dlp is not installed (pip install yt-dlp).")
        sys.exit(1)

    try:
        resolved = resolve(
            args.url,
            max_height=_RES_CHOICES[args.res],
            cookies_from_browser=args.cookies_from_browser,
            player_client=args.player_client,
        )
    except ResolveError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    play(resolved, want_audio=not args.no_audio)


if __name__ == "__main__":
    main()
