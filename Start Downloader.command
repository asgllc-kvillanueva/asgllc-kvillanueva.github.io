#!/bin/bash
# ─────────────────────────────────────────────
#   Downloader · Start
#   Double-click whenever you want to download.
#   Your browser opens by itself.
#   Close this window when you're finished.
# ─────────────────────────────────────────────

cd "$(dirname "$0")" || exit 1

# If setup hasn't run, point the user at it instead of erroring out.
if [ ! -d venv ]; then
  echo "It looks like Setup hasn't run yet."
  echo "Please double-click \"Setup\" first, then try again."
  echo
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi

# shellcheck disable=SC1091
source venv/bin/activate

echo "Starting the Downloader…"
echo "Your browser will open in a moment."
echo "Keep this window open while you work — closing it stops the app."
echo

# app.py opens http://127.0.0.1:5001 in the browser on its own.
python3 app.py
