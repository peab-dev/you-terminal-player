<p align="center">
  <img src="assets/banner.svg" alt="you-terminal-player" width="100%">
</p>

Watch **YouTube videos right inside your terminal** — rendered as colored
half-blocks at the terminal's full resolution and the video's original frame
rate, **with live, synchronized sound**.

It's fully self-contained: a small half-block renderer plus `yt-dlp`, `ffmpeg`
and `ffplay` do all the work.

---

## How it works

```
yt <youtube-url>
        │
        ├─ yt-dlp ─────────────►  resolve direct stream URLs + title / size / fps
        │     ├─ EJS + Node     →  solve YouTube's "n" signature (JS challenge)
        │     └─ bgutil PO-token →  satisfy YouTube's SABR / proof-of-origin
        │
        ├─ ffmpeg (video URL) ──►  raw rgb24 frames  ─►  half-block ANSI  ─►  terminal
        └─ ffplay (audio URL) ──►  live sound, kept in sync via the wall clock
```

- **Half-block rendering** (`▀`): every character cell carries two stacked
  pixels (top = foreground, bottom = background), doubling vertical resolution.
  That's the physical maximum for full-colour terminal graphics.
- **Original speed**: the frame loop drops frames against the wall clock so
  playback always matches real time, even if rendering can't keep up.
- **Direct ANSI output** (no Rich re-parsing) keeps it fast enough for full-frame
  playback at high resolution.
- **Streaming, not downloading**: video and audio are read straight from
  YouTube's CDN, so playback starts in ~1–2 s.

---

## Requirements

| Tool | Why | Install |
|------|-----|---------|
| `ffmpeg` / `ffplay` | decode video frames + play audio | `brew install ffmpeg` |
| Node.js ≥ 22 | solve YouTube's JS "n" challenge (via yt-dlp EJS) | `brew install node` |
| Docker Desktop | runs the bgutil PO-token server | https://docker.com |

The `install.sh` script sets up everything above that it can (it can't GUI-install
Docker Desktop, only start it).

---

## Installation

```bash
git clone https://github.com/peab-dev/you-terminal-player.git
cd you-terminal-player
./install.sh
```

The installer is **idempotent** — re-run it any time (e.g. after a reboot, to make
sure the PO-token server is running). It will:

1. check Homebrew and install `ffmpeg`/`ffplay` + Node.js (≥ 22) if missing,
2. create a `.venv` and install `yt-dlp[default]` (JS challenge solver) and the
   `bgutil` PO-token plugin,
3. start the bgutil PO-token server in Docker (port 4416, auto-restart),
4. install a global **`yt`** launcher on your `PATH` (it injects the Node path and
   makes sure the PO-token server is up on every run).

### Uninstall

```bash
./uninstall.sh
```

Removes the `yt` launcher, the Docker container and the `.venv`. Shared tools
(ffmpeg, Node, Docker) and the source are kept.

---

## Usage

```bash
yt                                            # play the default video
yt "https://www.youtube.com/watch?v=..."      # a specific video (up to 720p)
yt "https://youtu.be/..."                     # short links work too
```

### Options

| Option | Description |
|--------|-------------|
| `--res {360,480,720,1080,best}` | maximum source resolution (default `720`) |
| `--no-audio` | play silently |
| `--cookies-from-browser BROWSER` | use cookies from `safari` / `chrome` / `firefox` … if YouTube asks you to confirm you're not a bot |
| `--player-client CLIENT` | force a yt-dlp player client (`tv`, `web_safari`, `mweb`, `ios` …) |

### Controls (while playing)

| Key | Action |
|-----|--------|
| `space` | pause / resume (video **and** audio) |
| `v` | cycle display mode: **classic** (colored half-blocks) → **ASCII** (oldschool colored ASCII art) → **b&w** (black & white ASCII) → classic |
| `q` / `ESC` | quit |

The audio keeps playing in every mode, so you can flip to oldschool ASCII mid-song.

> **Tip:** make the terminal window larger and shrink the font (`Cmd` `-`) before
> launching — more cells = a sharper picture. The grid is fixed when playback
> starts.

---

## Troubleshooting

**`No video formats found!`**
YouTube needs both the JS challenge solver and a PO token. Make sure the bgutil
server is running and re-run the installer:
```bash
docker start bgutil-provider      # or: ./install.sh
```
You can also force a client: `yt --player-client tv "<url>"`.

**`Sign in to confirm you're not a bot`**
Log in to YouTube in your browser, then pass its cookies:
```bash
yt --cookies-from-browser safari "<url>"
```
On macOS, Chrome cookies need Keychain access and Safari needs your terminal to
have *Full Disk Access* (System Settings → Privacy & Security).

**Picture but no sound**
The video may have no audio track, or `ffplay` is missing (`which ffplay`).

**Picture looks small / low-res**
Enlarge the terminal window and reduce the font size *before* running `yt`.

---

## Internals

Three small modules, no external project dependency:

- `render.py` — the self-contained building blocks:
  - `fit_grid()` — fit the source into the terminal cell grid, preserving aspect.
  - `frame_to_ansi()` — turn a raw rgb24 frame into a half-block ANSI string.
  - `VideoSource` — an ffmpeg pipe that yields ready-to-render frames.
  - `AudioPlayer` — an ffplay subprocess with seek support for pause/resume.
  - `KeyReader` — non-blocking keyboard input.
- `resolve.py` — YouTube URL → direct stream URLs via yt-dlp.
- `player.py` — the single-video streaming loop (`StreamVideoSource` adds
  network auto-reconnect to `VideoSource`).

---

## Limitations

- Requires an internet connection during playback (nothing is downloaded).
- Live streams may not report an fps; a 24 fps fallback is used.
- The video grid size is fixed when playback starts (resize before launching).
- Built and tested on macOS.

---

<p align="center"><em>Terminal television, with sound. 📺🔊</em></p>
