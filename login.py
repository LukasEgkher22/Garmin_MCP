"""One-time Garmin Connect login.

Run this once in a terminal:  python login.py
It asks for your Garmin email, password and (if enabled) MFA code, then saves
session tokens to the token folder. Your password is NOT saved anywhere.
The MCP server only ever uses the saved tokens.
"""

import getpass
import os
from pathlib import Path

from garminconnect import Garmin

TOKEN_DIR = Path(os.getenv("GARMINTOKENS", Path.home() / ".garminconnect"))


def main() -> None:
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password (hidden): ")

    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    api = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: input("MFA code from Garmin: ").strip(),
    )
    api.login(str(TOKEN_DIR))
    api.client.dump(str(TOKEN_DIR))  # make sure tokens are written

    print(f"\nLogged in as: {api.get_full_name()}")
    print(f"Tokens saved to: {TOKEN_DIR}")
    print("You can now start the MCP server (Claude desktop does this for you).")


if __name__ == "__main__":
    main()
