#!/bin/bash
# ─────────────────────────────────────────────
#   Downloader · Setup   (run once)
#   Double-click this file. When it says
#   "Setup complete", you can close the window.
# ─────────────────────────────────────────────

# Work inside the folder this file lives in, wherever the user put it.
cd "$(dirname "$0")" || exit 1

echo "Setting up the Downloader…"
echo "This takes about a minute the first time."
echo

# 1. Make sure Python 3 is available.
if ! command -v python3 >/dev/null 2>&1; then
  echo "▸ Python 3 isn't installed yet."
  echo "  A macOS window will pop up — click \"Install\" and wait for it to finish."
  echo "  Then double-click Setup again."
  xcode-select --install 2>/dev/null
  echo
  read -n 1 -s -r -p "Press any key to close this window."
  exit 0
fi

# 2. Create an isolated environment and install the Python pieces.
echo "▸ Preparing the app environment…"
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
python3 -m pip install --upgrade pip >/dev/null 2>&1

echo "▸ Installing the downloader (yt-dlp) and tools…"
python3 -m pip install flask yt-dlp -i https://pypi.org/simple/

# 3. Fetch ffmpeg into the app's bin/ folder (skip if already there).
if [ ! -f bin/ffmpeg ]; then
  echo "▸ Downloading ffmpeg…"
  mkdir -p bin
  curl -sL -o ffmpeg.zip https://evermeet.cx/ffmpeg/getrelease/zip
  unzip -q -o ffmpeg.zip -d bin/
  rm -f ffmpeg.zip
  chmod +x bin/ffmpeg
fi

# 4. Make sure the everyday launcher is runnable, even if downloading
#    stripped its executable flag.
chmod +x "Start Downloader.command" 2>/dev/null

echo
echo "✅  Setup complete — you won't need to do this again."
echo "    From now on, just double-click  \"Start Downloader\"."
echo
read -n 1 -s -r -p "Press any key to close this window."
