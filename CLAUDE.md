# Playground Tools — project context for Claude Code

This repo is a GitHub Pages site that also ships small macOS desktop tools to a YouTube
creative studio. The person maintaining it (Kevin) is not a developer — keep end-user-facing
copy plain and short, and explain changes in plain language. Make direct edits to files and
state the exact repo path of anything you change.

## The repo
- GitHub: `asgllc-kvillanueva/asgllc-kvillanueva.github.io` (a **user** Pages site).
- Live site: https://asgllc-kvillanueva.github.io/
- Pages is served from the **`main` branch `/docs` folder**. Only files under `docs/` are
  web-reachable. Default branch is `main`.

## What it is
A "Playground Tools" hub: the person double-clicks one launcher, a local hub page opens in
the browser, and they pick which tool to run. Two tools today, both **Flask** apps:
- `apps/universal-downloader/` — yt-dlp downloader (downloader.py, port 5001).
- `apps/asset-compressor/` — crop/compress video → WebP/GIF/MOV/PNG (compressor.py, port 5002).
  Templates in `templates/`, assets in `static/`, multi-file batch export with one universal
  crop/setting set applied to every file.

## Structure
```
hub/hub_server.py                  stdlib HTTP server (port 8765): landing page + lazy per-app venv setup + launch
hub/web/hub.html                   landing page
apps/<app>/                        each app: <app>.py, templates/, static/, requirements.txt
launcher/YouTube Downloader.command  bootstrapper the user double-clicks (SOURCE)
docs/index.html                    the setup guide (Pages homepage)
docs/YouTube-Downloader.zip        the file users download (contains the .command, exec bit 755 baked into the zip)
docs/instructions/*                guide screenshots
```

## How it runs / deploys
- App + hub code is **re-fetched from GitHub on every launch** by the bootstrapper, so most
  changes ship with a plain `git push` — no redistribution needed.
- Each app has its **own venv**, created lazily on first click. The hub rebuilds a venv when
  `requirements.txt` changes (it stores a sha1 of requirements in a `.setup_ok` marker).
- The **launcher itself** (`YouTube Downloader.command`) is the one thing NOT auto-updated —
  it's already running. Changing it means rebuilding `docs/YouTube-Downloader.zip` and having
  people re-download. When rebuilding that zip, the `.command` must have mode **755 baked into
  the zip entry** (the exec bit survives inside a committed zip but is stripped from loose
  downloaded files).
- Keep the launcher/zip named "YouTube Downloader" — the guide screenshots reference that name.

## Hard platform constraints (this is the crux of the whole project)
Tested on a **locked-down corporate Mac running Santa** (binary authorization) + likely MDM.
**Build every feature to these rules UP FRONT.** Santa problems do not show up on a normal dev
Mac — they only appear when the corp Mac runs the code, so a feature can look "done" and then
get blocked in the field. Design for these constraints before writing code, not after.

### What Santa blocks vs. allows
- **BLOCKS: spawning/executing any untrusted Mach-O binary.** This covers binaries we ship or
  download **and Homebrew binaries** — do **NOT** assume `/opt/homebrew` or `/usr/local` are
  trusted. Observed on the corp Mac: Santa blocked `/opt/homebrew/Cellar/deno/.../deno` and
  `/opt/homebrew/Cellar/ffmpeg/.../ffmpeg` when a Python process (yt-dlp) tried to spawn them.
  The popup reads "trustworthiness cannot be determined" with the binary path and a Python
  parent. (This corrects an earlier wrong assumption that Santa trusts Homebrew paths — it
  does not on this machine.)
- **BLOCKS: on-machine compilation** — the `./configure`/build step runs test binaries Santa
  blocks. No building C extensions from source.
- **ALLOWS: dylib loads into an Apple-signed interpreter.** Python itself is Apple-signed, and
  loading a `.so`/`.dylib` (a prebuilt wheel's C extension, or libav/libwebp living inside the
  `av`/`Pillow` wheels) is **not** a spawn — it's allowed. **This is the key escape hatch: do
  the work as an in-process library, not by shelling out to a binary.**
- **ALLOWS: Apple-signed system tools** — `osascript`, `curl`, `unzip`, the system `python3`,
  etc. Use these for glue.

### Design rules for ANY new feature (decide these BEFORE writing code)
1. **Do heavy / media / CPU work with a Python library that ships as a prebuilt wheel and runs
   in-process** — never by calling an external CLI binary. In use today: `av` (PyAV = libav)
   and `Pillow` do *all* video/image work in Asset Compressor (no ffmpeg binary). Reach for a
   library before a CLI tool.
2. **Every pip dependency must install as a prebuilt wheel.** The hub installs with
   `--only-binary=:all:`. If a dep has no macOS wheel for the target Python and would compile
   from source, it is a non-starter — pick another library. (Why the compressor was ported off
   Eel/gevent to pure-Python Flask.)
3. **Never download a binary** (static ffmpeg, etc.) and never bundle one as the default —
   it's unknown to Santa and gets blocked.
4. **If you must shell out to a tool that itself spawns helper binaries** — the prime example
   is `yt-dlp`, which spawns **deno** to solve YouTube's JS ("nsig") challenge and **ffmpeg**
   to merge adaptive streams — do BOTH of these so it degrades gracefully instead of popping
   Santa:
   - **Remove the need:** pick options that avoid the spawn. For yt-dlp that means a single
     **pre-muxed / progressive** format (no ffmpeg merge) and a player client that needs no JS
     challenge. Trade-off: progressive caps at ~360p (sometimes 720p); higher resolutions only
     exist as adaptive streams that require the blocked deno/ffmpeg.
   - **Make the binary unreachable:** run the subprocess with a **sanitized PATH** — venv `bin`
     plus `/usr/bin`, `/bin`, `/usr/sbin`, `/sbin` only, **excluding** `/opt/homebrew/bin` and
     `/usr/local/bin`. The tool then physically can't launch deno/ffmpeg, logs a warning, and
     still works. Reference implementation: `_yt_env()` + `YT_FORMAT` in
     `apps/asset-compressor/compressor.py`.
5. **Prefer Apple-signed system tools for glue** (file pickers via `osascript`, downloads via
   `curl`, unzip) — they're allowed.

### Remaining ffmpeg exposure
Asset Compressor no longer uses ffmpeg at all (PyAV does everything in-process). The
**Universal Downloader still relies on ffmpeg** via yt-dlp to merge adaptive streams for >360p,
so it can still trip Santa on the corp Mac for high-res videos. The launcher/hub still put
system/Homebrew ffmpeg on PATH for the downloader's sake — but remember Homebrew ffmpeg itself
may be blocked. If this becomes a problem, the durable fixes are the same two levers as rule 4:
merge in-process with PyAV (allowed), or go progressive-only like the compressor.

### Other macOS gotchas
- **Gatekeeper:** downloaded files are quarantined. On recent macOS the right-click→Open
  trick is gone; unblock via System Settings → Privacy & Security → "Open Anyway".
- App data lives under `~/Library/Application Support/Playground Tools/` to avoid TCC prompts
  on Desktop/Documents/Downloads.

## Open items / next up
- **Asset Compressor YouTube path is now Santa-safe (done).** It uses a sanitized PATH
  (`_yt_env()`) so yt-dlp can never spawn deno/ffmpeg, plus a single progressive `YT_FORMAT`
  so no merge is needed. Cost: compressor YouTube grabs are ~360p (best progressive). The
  **Universal Downloader has NOT had this treatment** — it still merges adaptive streams with
  ffmpeg for higher res and can still pop Santa on the corp Mac.
- **YouTube 403 + "Python 3.9 deprecated"** on the corp Mac: separate from Santa. The corp Mac
  runs Python 3.9, which pins yt-dlp to older builds that YouTube 403s more often. Option to
  explore: get Python 3.10+ onto that Mac.
- **Export with no output folder chosen**: requested default to `~/Downloads` (note: may trigger
  a one-time TCC prompt) and enable the Export button once files are selected.
- **Per-video crop**: today the crop is universal (pixel crop assumes all selected files share
  dimensions); mismatched sizes are reported per-file. A per-video crop is a future upgrade.
- Confirm whether a non-admin teammate's normal password works for "Open Anyway" (only an admin
  password has been confirmed).

## Conventions
- Minimal, non-condescending end-user copy. Don't explain internal mechanics to end users.
- Unique filenames across apps (downloader.* / compressor.* / hub.html), namespaced by folder.
- Prefer `git push` to ship; only touch `docs/YouTube-Downloader.zip` when the launcher changes.
