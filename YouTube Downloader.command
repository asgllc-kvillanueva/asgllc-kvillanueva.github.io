#!/bin/bash
# ─────────────────────────────────────────────
#   YouTube Downloader
#   Double-click to open.
#   • First run sets everything up (~1 minute).
#   • Every run grabs the latest yt-dlp so
#     downloads keep working when YouTube changes.
#   • Close this window to stop the app.
# ─────────────────────────────────────────────

# Run from this file's own folder, wherever it lives.
cd "$(dirname "$0")" || exit 1

# 1. Need Python 3.
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 isn't installed yet."
  echo "A macOS window will appear — click Install, wait for it to finish,"
  echo "then open YouTube Downloader again."
  xcode-select --install 2>/dev/null
  echo
  read -n 1 -s -r -p "Press any key to close this window."
  exit 0
fi

# 2. First run only: build the environment and install the app's pieces.
if [ ! -d venv ]; then
  echo "First-time setup — this takes about a minute…"
  python3 -m venv venv
  # shellcheck disable=SC1091
  source venv/bin/activate
  python3 -m pip install --upgrade pip >/dev/null 2>&1
  python3 -m pip install flask yt-dlp -i https://pypi.org/simple/
else
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

# 3. Make sure ffmpeg is present.
if [ ! -f bin/ffmpeg ]; then
  echo "Downloading ffmpeg…"
  mkdir -p bin
  curl -sL -o ffmpeg.zip https://evermeet.cx/ffmpeg/getrelease/zip
  unzip -q -o ffmpeg.zip -d bin/
  rm -f ffmpeg.zip
  chmod +x bin/ffmpeg
fi

# 4. Keep yt-dlp current — this is the update that keeps YouTube working.
#    Non-fatal: if you're offline, we just use the version already installed.
echo "Checking for the latest version…"
if python3 -m pip install --upgrade yt-dlp -i https://pypi.org/simple/ >/dev/null 2>&1; then
  echo "Up to date."
else
  echo "Couldn't check for updates (offline?) — using the installed version."
fi

# 5. Launch. app.py opens your browser at http://127.0.0.1:5001 by itself.
echo
echo "Starting… your browser will open in a moment."
echo "Keep this window open while you work — closing it stops the app."
echo
python3 app.py
