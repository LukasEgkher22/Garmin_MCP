#!/bin/sh
# Starts the local training dashboard at http://127.0.0.1:8765 (close this window to stop it).
# Mac, manual setup only: double-click this file in Finder. If macOS says it can't be opened,
# right-click it -> Open once, or run: chmod +x start_dashboard.command
cd "$(dirname "$0")" || exit 1
.venv/bin/python3 dashboard.py
