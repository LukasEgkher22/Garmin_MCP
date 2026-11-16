"""One-time Strava login (like login.py for Garmin).

Before running this, create your own Strava API app at
https://www.strava.com/settings/api with "Authorization Callback Domain" = localhost.

Then run:  python strava_login.py
It asks for the app's Client ID and Client Secret, opens Strava in your
browser so you can approve upload access, and saves tokens to
~/.garminconnect/strava.json. Your Strava password is never seen or stored.
"""

import getpass
import http.server
import threading
import time
import urllib.parse
import webbrowser

import strava

PORT = 8722
REDIRECT = f"http://localhost:{PORT}/"


def _wait_for_code(timeout: int = 180) -> str | None:
    """Catch Strava's redirect on localhost and return the one-time code."""
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q:
                result["code"] = q["code"][0]
                msg = "Strava connected. You can close this tab."
            else:
                result["error"] = (q.get("error") or ["no code"])[0]
                msg = f"Strava login failed: {result['error']}"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())

        def log_message(self, *args):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    end = time.time() + timeout
    while time.time() < end and not result:
        time.sleep(0.5)
    srv.shutdown()
    return result.get("code")


def main() -> None:
    client_id = input("Strava Client ID: ").strip()
    client_secret = getpass.getpass("Strava Client Secret (hidden): ").strip()
    url = f"{strava.OAUTH}/authorize?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT,
        "approval_prompt": "force", "scope": strava.SCOPE,
    })
    print("\nOpening Strava in your browser. Click 'Authorize'.")
    print(f"If nothing opens, paste this link into your browser:\n{url}\n")
    webbrowser.open(url)
    code = _wait_for_code()
    if not code:
        pasted = input("Didn't receive it automatically. Paste the full address from the "
                       "browser's address bar after approving: ").strip()
        code = (urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).get("code") or [""])[0]
    if not code:
        raise SystemExit("No code received, nothing saved. Run the script again.")
    tok = strava.exchange_code(client_id, client_secret, code)
    print(f"\nConnected to Strava as {tok.get('athlete') or 'you'}.")
    print(f"Tokens saved to: {strava.TOKEN_FILE}")


if __name__ == "__main__":
    main()
