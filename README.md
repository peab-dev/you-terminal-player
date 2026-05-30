# you-terminal-player

**Watch YouTube in your terminal** — video as colored half-blocks at full
resolution and original frame rate, **with live, synchronized sound**. 📺🔊

> 📖 **Full documentation:** https://peab-dev.github.io/you-terminal-player/

```
┌──────────────────────────────────────────┐
│  yt "https://youtu.be/..."                │
│                                            │
│   ▀▀▀▀▀  half-block video + live audio,    │
│   ▀▀▀▀▀  streamed straight from YouTube    │
└──────────────────────────────────────────┘
```

## Quick start

```bash
git clone https://github.com/peab-dev/you-terminal-player.git
cd you-terminal-player
./install.sh
yt           # play the default video
```

`install.sh` is idempotent — it installs `ffmpeg`/`ffplay`, Node.js, the Python
venv, the `yt-dlp` + PO-token pieces, the bgutil Docker server, and a global `yt`
command on your `PATH`. Re-run it anytime.

> **Requires Docker Desktop** (for the PO-token server). Everything else is
> self-contained.

## Usage

```bash
yt                                         # default video
yt "https://www.youtube.com/watch?v=..."   # a specific video
yt --res 1080 "<url>"                       # higher resolution
yt --no-audio "<url>"                       # silent
yt --cookies-from-browser safari "<url>"    # if YouTube says "confirm you're not a bot"
```

**Controls:** `space` = pause/resume · `q` / `ESC` = quit
**Tip:** enlarge the window + shrink the font (`Cmd` `-`) for a sharper picture.

Uninstall with `./uninstall.sh`. See the
[docs](https://peab-dev.github.io/you-terminal-player/) for options, internals
and troubleshooting.

## License

MIT
