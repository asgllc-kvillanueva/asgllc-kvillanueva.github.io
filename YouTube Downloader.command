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

# 1. Need a WORKING Python 3. On a fresh Mac, /usr/bin/python3 is only a stub
#    that pops Apple's "install the command line developer tools" dialog the
#    first time it runs. We trigger that, then WAIT and continue on our own.
if ! python3 -c "" >/dev/null 2>&1; then
  echo "One-time setup: macOS needs Apple's Command Line Developer Tools."
  echo "  1. Click Install on the popup that appears"
  echo "  2. Agree to the license"
  echo
  echo "Leave this window open — it will continue by itself once that finishes."
  xcode-select --install 2>/dev/null
  printf "Waiting for the install to finish"
  tries=0
  until python3 -c "" >/dev/null 2>&1; do
    printf "."
    sleep 5
    tries=$((tries + 1))
    if [ "$tries" -ge 360 ]; then
      echo
      echo "This is taking a while. Once the tools finish installing,"
      echo "just double-click YouTube Downloader again."
      read -n 1 -s -r -p "Press any key to close this window."
      exit 0
    fi
  done
  echo
  echo "Python is ready — continuing…"
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
