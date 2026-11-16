"""Garmin -> Strava sync. Runs on GitHub Actions every hour
(.github/workflows/strava-sync.yml), or on the PC with Windows Task Scheduler.

For every new Garmin activity it downloads the original .fit and uploads it to
Strava. Pool swims are converted first (swimfit.py): one flat block per
interval instead of per-length data. Garmin itself is never changed and
nothing is ever deleted.

Use this INSTEAD of Garmin Connect's own Strava connection (turn that off),
otherwise Strava gets every activity twice.

    python sync_strava.py                 # normal run (what the scheduler calls)
    python sync_strava.py --dry-run       # show what would be uploaded
    python sync_strava.py --since 2026-11-01   # also upload older activities
    python sync_strava.py --activity 25095714915  # upload one activity now

The first run only remembers the current time: activities from before the
sync existed are not uploaded unless you pass --since.
State and log: ~/.garminconnect/strava_sync.json and strava_sync.log.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
from pathlib import Path
from typing import Callable

import strava
import swimfit

STATE_DIR = Path(os.getenv("GARMINTOKENS", Path.home() / ".garminconnect"))
STATE_FILE = STATE_DIR / "strava_sync.json"
LOG_FILE = STATE_DIR / "strava_sync.log"
LOCK_FILE = STATE_DIR / "strava_sync.lock"
LOOKBACK_DAYS = 7  # how far back each run looks for activities it hasn't handled yet
MAX_TRIES = 5
DONE = {"uploaded", "duplicate", "skipped"}

log = logging.getLogger("sync_strava")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(STATE_FILE)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def upload_one(g, download: Callable[[str], Path], fit_dir: Path, activity: dict,
               dry_run: bool = False) -> dict:
    """Download one Garmin activity, convert it if it's a pool swim, upload it."""
    gid = str(activity["activityId"])
    name = activity.get("activityName")
    try:
        original = download(gid)
    except RuntimeError as e:
        if "no original .fit" not in str(e):
            raise
        return {"status": "skipped", "reason": str(e)}  # manual entry, GPX import ...
    to_send, converted = original, False
    if swimfit.is_pool_swim(original):
        to_send = fit_dir / f"{gid}_STRAVA.fit"
        swimfit.to_intervals(original, to_send)
        converted = True
    if dry_run:
        return {"status": "dry-run", "file": str(to_send), "swim_converted": converted}
    res = strava.upload(to_send, name=name, external_id=f"garmin_{gid}")
    return {**res, "swim_converted": converted}


def run(g, download: Callable[[str], Path], fit_dir: Path, since: str | None = None,
        only: str | None = None, dry_run: bool = False) -> dict:
    """One sync pass. Returns a summary of what happened."""
    state = load_state()
    acts_state = state.setdefault("activities", {})
    if since:
        state["since"] = dt.datetime.fromisoformat(since).replace(
            tzinfo=dt.timezone.utc).isoformat(timespec="seconds")
    if "since" not in state:  # first run ever: start from now
        state["since"] = _now()
        if not dry_run:
            save_state(state)
        log.info("First run: syncing activities that start after %s", state["since"])
        return {"first_run": True, "since": state["since"], "handled": []}

    since_dt = dt.datetime.fromisoformat(state["since"])
    today = dt.date.today()
    start = max(since_dt.date(), today - dt.timedelta(days=LOOKBACK_DAYS)) if not only else None
    if only:
        a = g.get_activity(only)
        summ = a.get("summaryDTO") or {}
        acts = [{"activityId": only, "activityName": a.get("activityName"),
                 "startTimeGMT": summ.get("startTimeGMT")}]
    else:
        acts = g.get_activities_by_date(start.isoformat(), today.isoformat())
        acts.sort(key=lambda a: a.get("startTimeGMT") or "")

    handled = []
    for a in acts:
        gid = str(a["activityId"])
        st = acts_state.get(gid, {})
        gmt = a.get("startTimeGMT")
        if not only:
            if gmt and dt.datetime.fromisoformat(gmt).replace(tzinfo=dt.timezone.utc) < since_dt:
                continue
            if st.get("status") in DONE or st.get("tries", 0) >= MAX_TRIES:
                continue
        try:
            if st.get("status") == "processing" and st.get("upload_id") and not only:
                res = strava.upload_status(st["upload_id"])
            else:
                res = upload_one(g, download, fit_dir, a, dry_run)
        except strava.RateLimited as e:
            log.warning("%s", e)
            break
        except Exception as e:  # noqa: BLE001
            res = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            log.error("%s %s: %s", gid, a.get("activityName"), res["error"])
        if dry_run:
            handled.append({"activity_id": gid, "name": a.get("activityName"), **res})
            continue
        if res["status"] == "error":
            res["tries"] = st.get("tries", 0) + 1
        acts_state[gid] = {**res, "name": a.get("activityName"), "start": gmt, "at": _now()}
        save_state(state)
        log.info("%s %s -> %s %s", gid, a.get("activityName"), res["status"], res.get("strava_id", ""))
        handled.append({"activity_id": gid, "name": a.get("activityName"), **res})
    return {"since": state["since"], "handled": handled}


def _locked() -> bool:
    """True if another run is active (lock younger than 30 min)."""
    if LOCK_FILE.exists():
        age = dt.datetime.now().timestamp() - LOCK_FILE.stat().st_mtime
        if age < 1800:
            return True
    LOCK_FILE.write_text(str(os.getpid()))
    return False


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since", help="also upload activities from this date (YYYY-MM-DD) on")
    p.add_argument("--activity", help="upload this one Garmin activity id now")
    p.add_argument("--dry-run", action="store_true", help="show what would happen, upload nothing")
    args = p.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _trim_log()
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if sys.stdout:  # pythonw (no console window) has no stdout
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    if _locked():
        log.info("Another sync is still running; skipping this one.")
        return
    server = None
    try:
        import server  # Garmin login + download helpers
        result = run(server.api(), server._download_fit, server.FIT_DIR,
                     since=args.since, only=args.activity, dry_run=args.dry_run)
        if (args.dry_run or args.activity) and sys.stdout:
            print(json.dumps(result, indent=1, default=str))
    except Exception:
        log.exception("Sync failed")
        raise
    finally:
        LOCK_FILE.unlink(missing_ok=True)
        if server is not None and server._api is not None:
            try:  # keep refreshed Garmin tokens (matters on GitHub Actions)
                server._api.client.dump(str(server.TOKEN_DIR))
            except Exception:  # noqa: BLE001
                log.warning("Could not save refreshed Garmin tokens", exc_info=True)


def _trim_log(max_bytes: int = 500_000) -> None:
    """Keep the log small (it travels in the Actions cache)."""
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > max_bytes:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        LOG_FILE.write_text("\n".join(lines[-2000:]) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
