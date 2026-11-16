"""Print the two GitHub secrets the Strava sync workflow needs.

GitHub Actions should have its OWN Garmin and Strava login (tokens renew
themselves; a login shared with this PC would keep breaking one side). So in
PowerShell, in this folder:

    $env:GARMINTOKENS = "$HOME\\.garminconnect-github"
    .venv\\Scripts\\python.exe login.py
    .venv\\Scripts\\python.exe strava_login.py
    .venv\\Scripts\\python.exe export_secrets.py

Then paste each value into GitHub: repo -> Settings -> Secrets and variables ->
Actions -> New repository secret. Close the terminal afterwards so
GARMINTOKENS goes back to normal for this PC.
"""

import os
from pathlib import Path

TOKEN_DIR = Path(os.getenv("GARMINTOKENS", Path.home() / ".garminconnect"))
FILES = {"GARMIN_TOKENS": "garmin_tokens.json", "STRAVA_TOKENS": "strava.json"}


def main() -> None:
    if TOKEN_DIR == Path.home() / ".garminconnect":
        print("Note: GARMINTOKENS is not set, so these are this PC's own logins.\n"
              "Better: give GitHub its own (see the top of this file).\n")
    for secret, name in FILES.items():
        p = TOKEN_DIR / name
        if not p.exists():
            raise SystemExit(f"{p} is missing. Run login.py / strava_login.py first.")
        print(f"===== Secret name: {secret}")
        print(p.read_text().strip())
        print()
    print("Treat these values like passwords: paste them only into GitHub secrets.")


if __name__ == "__main__":
    main()
