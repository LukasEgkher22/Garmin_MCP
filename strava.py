"""Minimal Strava API client (standard library only): token refresh + upload.

Tokens live in ~/.garminconnect/strava.json (env STRAVA_TOKENS), next to the
Garmin tokens. Create them once with `python strava_login.py`.
Strava's API cannot delete activities; this module never tries.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

TOKEN_FILE = Path(os.getenv("STRAVA_TOKENS", Path.home() / ".garminconnect" / "strava.json"))
API = "https://www.strava.com/api/v3"
OAUTH = "https://www.strava.com/oauth"
SCOPE = "activity:write,read"


class StravaError(RuntimeError):
    pass


class RateLimited(StravaError):
    pass


def _request(method: str, url: str, data: bytes | None = None, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 429:
            raise RateLimited("Strava rate limit reached; try again in 15 minutes") from e
        raise StravaError(f"HTTP {e.code} from Strava: {body[:300]}") from e


def _load() -> dict:
    if not TOKEN_FILE.exists():
        raise StravaError(f"No Strava tokens in {TOKEN_FILE}. Run 'python strava_login.py' first.")
    return json.loads(TOKEN_FILE.read_text())


def _save(tok: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok, indent=2))


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    """First login: turn the one-time code from the browser into tokens and save them."""
    body = urllib.parse.urlencode({"client_id": client_id, "client_secret": client_secret,
                                   "code": code, "grant_type": "authorization_code"}).encode()
    r = _request("POST", f"{OAUTH}/token", body)
    tok = {"client_id": client_id, "client_secret": client_secret,
           "access_token": r["access_token"], "refresh_token": r["refresh_token"],
           "expires_at": r["expires_at"], "athlete": (r.get("athlete") or {}).get("firstname")}
    _save(tok)
    return tok


def access_token() -> str:
    """A valid access token, refreshed (and saved) when it is about to expire."""
    tok = _load()
    if tok["expires_at"] - time.time() < 300:
        body = urllib.parse.urlencode({"client_id": tok["client_id"], "client_secret": tok["client_secret"],
                                       "refresh_token": tok["refresh_token"],
                                       "grant_type": "refresh_token"}).encode()
        r = _request("POST", f"{OAUTH}/token", body)
        tok.update(access_token=r["access_token"], refresh_token=r["refresh_token"], expires_at=r["expires_at"])
        _save(tok)
    return tok["access_token"]


def _multipart(fields: dict[str, str], file_field: str, path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
                 f'filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload(path: str | Path, name: str | None = None, external_id: str | None = None,
           wait_s: int = 90) -> dict:
    """Upload a .fit to Strava and wait until it is processed.

    Returns {"status": "uploaded", "strava_id": ...}, {"status": "duplicate", ...}
    when Strava already has this activity, or {"status": "processing", ...}
    if Strava hasn't finished within wait_s. Raises StravaError on other failures.
    """
    path = Path(path)
    fields = {"data_type": "fit"}
    if name:
        fields["name"] = name
    if external_id:
        fields["external_id"] = external_id
    body, ctype = _multipart(fields, "file", path)
    auth = {"Authorization": f"Bearer {access_token()}"}
    r = _request("POST", f"{API}/uploads", body, {**auth, "Content-Type": ctype})
    return _wait(r, path.name, wait_s, auth)


def upload_status(upload_id: str, wait_s: int = 0) -> dict:
    """Check an upload that was still processing (same result shape as upload())."""
    auth = {"Authorization": f"Bearer {access_token()}"}
    r = _request("GET", f"{API}/uploads/{upload_id}", headers=auth)
    return _wait(r, f"upload {upload_id}", wait_s, auth)


def _wait(r: dict, label: str, wait_s: int, auth: dict) -> dict:
    upload_id = r.get("id_str") or r.get("id")
    deadline = time.time() + wait_s
    while True:
        if r.get("error"):
            err = str(r["error"])
            if "duplicate" in err.lower():
                return {"status": "duplicate", "upload_id": upload_id, "message": err}
            raise StravaError(f"Strava rejected {label}: {err}")
        if r.get("activity_id"):
            return {"status": "uploaded", "upload_id": upload_id, "strava_id": r["activity_id"],
                    "url": f"https://www.strava.com/activities/{r['activity_id']}"}
        if time.time() > deadline:
            return {"status": "processing", "upload_id": upload_id}
        time.sleep(3)
        r = _request("GET", f"{API}/uploads/{upload_id}", headers=auth)
