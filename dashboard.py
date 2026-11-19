"""Personal training dashboard: a local web page over your Garmin Connect data.

    python dashboard.py            # opens http://127.0.0.1:8765
    python dashboard.py --port N   # use another port

Uses the tokens saved by login.py. Data is cached in a SQLite file next to those
tokens, so the page loads instantly and Garmin is only asked for what's new.
The server listens on this computer only and is read-only towards Garmin.
"""

import argparse
import datetime as dt
import json
import re
import sqlite3
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from server import TOKEN_DIR, api

HTML_FILE = Path(__file__).with_name("dashboard.html")
DB_FILE = TOKEN_DIR / "dashboard_cache.sqlite"  # health data: kept beside the tokens, never in the project

HISTORY_YEARS = 10      # how far back the first sync looks for activities
CHUNK_DAYS = 120        # Garmin's range endpoints handle about 180 days per call
RECENT_ACTIVITY_DAYS = 30  # re-read on every sync, so edits and deletions are picked up
RECENT_WELLNESS_DAYS = 7   # last night's sleep and HRV can arrive late
PLANNED_BACK, PLANNED_AHEAD = 42, 120
CALL_PAUSE = 0.25       # seconds between Garmin calls
STALE_AFTER = 3600      # the page triggers a sync if the last one is older than this
STREAM_POINTS = 700     # per-activity chart resolution
ROUTE_POINTS = 500
DETAIL_VERSION = 2      # bump when read_details() returns new fields; older cached details are re-read
ACTIVITY_LIST_VERSION = 2  # bump when slim_activity() keeps new fields; the next sync re-reads the full list
LAP_FIELDS = (
    "startTimeGMT", "distance", "movingDuration", "duration", "averageSpeed", "averageHR", "maxHR",
    "averagePower", "normalizedPower", "averageBikeCadence", "averageRunCadence", "elevationGain",
    "swimStroke", "averageSWOLF", "averageStrokes", "totalNumberOfStrokes",
)

# Race predictions: laps of hard runs, so a hard part inside a longer run (a 5 km test
# after a warm-up, a parkrun in a long run) counts too. The page decides what is race-like.
LAP_DAYS = 400              # the model only looks back 12 months
LAP_MIN_MAX_HR = 0.90       # only runs whose max HR got this close to the user's max HR
LAP_READS_PER_SYNC = 40     # backfill is spread over a few syncs

ACTIVITY_FIELDS = (
    "activityId", "activityName", "startTimeLocal", "distance", "duration", "movingDuration",
    "averageSpeed", "maxSpeed", "averageHR", "maxHR", "calories", "elevationGain",
    "activityTrainingLoad", "aerobicTrainingEffect", "anaerobicTrainingEffect", "trainingEffectLabel",
    "avgPower", "normPower", "maxPower", "trainingStressScore", "intensityFactor", "vO2MaxValue",
    "averageRunningCadenceInStepsPerMinute", "excludeFromPowerCurveReports", "parent", "pr", "locationName",
    *(f"hrTimeInZone_{z}" for z in range(1, 6)),
    *(f"powerTimeInZone_{z}" for z in range(1, 8)),
    *(f"maxAvgPower_{s}" for s in (1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1200, 1800, 3600)),
)

# Metric key from Garmin's activity details -> short name used by the page.
STREAMS = {"directHeartRate": "hr", "directSpeed": "speed", "directPower": "power",
           "directBikeCadence": "cad", "directDoubleCadence": "cad", "directRunCadence": "cad",
           "directElevation": "ele", "sumDuration": "t", "sumDistance": "d"}


# ------------------------------------------------------------------- storage

def db() -> sqlite3.Connection:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_FILE, timeout=30)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS activities (id INTEGER PRIMARY KEY, day TEXT, json TEXT);
        CREATE INDEX IF NOT EXISTS activities_day ON activities (day);
        CREATE TABLE IF NOT EXISTS days (day TEXT PRIMARY KEY, json TEXT);
        CREATE TABLE IF NOT EXISTS details (id INTEGER PRIMARY KEY, json TEXT);
        CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, json TEXT);
    """)
    return con


def kv_get(con: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = con.execute("SELECT json FROM kv WHERE k = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def kv_set(con: sqlite3.Connection, key: str, value: Any) -> None:
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, json.dumps(value)))
    con.commit()


def merge_days(con: sqlite3.Connection, updates: dict[str, dict]) -> None:
    """Add fields to day rows, keeping what other endpoints already filled in."""
    for day, fields in updates.items():
        row = con.execute("SELECT json FROM days WHERE day = ?", (day,)).fetchone()
        merged = json.loads(row[0]) if row else {}
        merged.update({k: v for k, v in fields.items() if v is not None})
        con.execute("INSERT OR REPLACE INTO days VALUES (?, ?)", (day, json.dumps(merged)))
    con.commit()


# ---------------------------------------------------------- reading from Garmin

def slim_activity(a: dict) -> dict:
    row = {k: a[k] for k in ACTIVITY_FIELDS if a.get(k) not in (None, "")}
    row["type"] = (a.get("activityType") or {}).get("typeKey") or "other"
    if (a.get("eventType") or {}).get("typeKey") == "race":  # marked as "Race" in Garmin Connect
        row["race"] = True
    return row


def wellness_endpoints() -> dict[str, Any]:
    """Each one reads a date range and returns {day: fields}."""
    g = api()

    def sleep(s: str, e: str) -> dict:
        out = {}
        for row in g.get_sleep_daily(s, e) or []:
            v = row.get("values") or {}
            out[row["calendarDate"]] = {
                "sleep": v.get("totalSleepTimeInSeconds"), "sleepScore": v.get("sleepScore"),
                "deep": v.get("deepTime"), "light": v.get("lightTime"), "rem": v.get("remTime"),
                "awake": v.get("awakeTime"), "hrv": v.get("avgOvernightHrv"), "hrvStatus": v.get("hrvStatus"),
                "sleepRhr": v.get("restingHeartRate"), "resp": v.get("respiration"),
            }
        return out

    def summaries(s: str, e: str) -> dict:
        out = {}
        for row in (g.get_daily_summaries(s, e) or {}).get("data") or []:
            hr, stress = row.get("heartRate") or {}, row.get("stress") or {}
            bb, im = row.get("bodyBattery") or {}, row.get("intensityMinutes") or {}
            steps = (row.get("movement") or {}).get("steps") or {}
            out[row["calendarDate"]] = {
                "rhr": hr.get("restingValue"), "stress": stress.get("avgLevel"),
                "bbMax": bb.get("maxValue"), "bbMin": bb.get("minValue"), "bbCharged": bb.get("chargedValue"),
                "steps": steps.get("value"), "imMod": im.get("moderate"), "imVig": im.get("vigorous"),
            }
        return out

    def vo2(s: str, e: str) -> dict:
        out: dict[str, dict] = {}
        for row in g.get_max_metrics_range(s, e) or []:
            for sport, name in (("generic", "vo2run"), ("cycling", "vo2bike")):
                m = row.get(sport) or {}
                if m.get("calendarDate") and m.get("vo2MaxPreciseValue"):
                    out.setdefault(m["calendarDate"], {})[name] = m["vo2MaxPreciseValue"]
        return out

    def race(s: str, e: str) -> dict:
        out = {}
        for row in g.get_race_predictions(s, e, "daily") or []:
            out[row["calendarDate"]] = {"r5k": row.get("time5K"), "r10k": row.get("time10K"),
                                        "rHalf": row.get("timeHalfMarathon"), "rFull": row.get("timeMarathon")}
        return out

    return {"sleep": sleep, "daily summary": summaries, "VO2max": vo2, "race predictions": race}


def garmin_load(today: dt.date) -> dict | None:
    """Garmin's own verdict: training status and acute:chronic load ratio."""
    data = api().get_training_status(today.isoformat()) or {}
    devices = ((data.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}).values()
    row = next((d for d in devices if d.get("primaryTrainingDevice")), next(iter(devices), None))
    if not row:
        return None
    acute = row.get("acuteTrainingLoadDTO") or {}
    return {"status": row.get("trainingStatusFeedbackPhrase"), "day": row.get("calendarDate"),
            "ratio": acute.get("dailyAcuteChronicWorkloadRatio"), "ratioStatus": acute.get("acwrStatus"),
            "acute": acute.get("dailyTrainingLoadAcute"), "chronic": acute.get("dailyTrainingLoadChronic")}


def hr_max(profile: dict) -> float:
    """Max HR from Garmin's heart rate zones (same choice as hrMax() in dashboard.html)."""
    zones = profile.get("hrZones")
    zones = zones if isinstance(zones, list) else [zones] if zones else []
    zones = [z for z in zones if isinstance(z, dict) and z.get("maxHeartRateUsed")]
    pick = next((z for z in zones if re.search("RUN|DEFAULT", z.get("sport") or "", re.I)), zones[0] if zones else None)
    return pick["maxHeartRateUsed"] if pick else 192


def read_run_laps(con: sqlite3.Connection, today: dt.date, profile: dict) -> None:
    """Cache [distance m, duration s, avg HR] per lap for hard runs, once per run."""
    store = kv_get(con, "run_laps", {})
    floor = LAP_MIN_MAX_HR * hr_max(profile)
    todo = []
    for (j,) in con.execute("SELECT json FROM activities WHERE day >= ? ORDER BY day DESC",
                            ((today - dt.timedelta(days=LAP_DAYS)).isoformat(),)):
        a = json.loads(j)
        if ("run" in a.get("type", "") and str(a["activityId"]) not in store
                and (a.get("maxHR") or 0) >= floor and (a.get("distance") or 0) >= 3000):
            todo.append(a["activityId"])
    g = api()
    for i, aid in enumerate(todo[:LAP_READS_PER_SYNC]):
        set_status(message=f"Reading laps of hard runs ({i + 1} of {min(len(todo), LAP_READS_PER_SYNC)})")
        try:
            laps = (g.get_activity_splits(aid) or {}).get("lapDTOs") or []
        except Exception as e:  # noqa: BLE001
            if "TooManyRequests" in type(e).__name__:
                raise
            with status_lock:
                status["warnings"].append(f"laps of {aid}: {e}")
            continue
        store[str(aid)] = [[round(x["distance"], 1), round(x["duration"], 1), x.get("averageHR")]
                           for x in laps if x.get("distance") and x.get("duration")]
        kv_set(con, "run_laps", store)
        time.sleep(CALL_PAUSE)


def chunks(start: dt.date, end: dt.date) -> list[list[str]]:
    """Date windows from newest to oldest, so recent data appears first."""
    out, hi = [], end
    while hi >= start:
        lo = max(start, hi - dt.timedelta(days=CHUNK_DAYS - 1))
        out.append([lo.isoformat(), hi.isoformat()])
        hi = lo - dt.timedelta(days=1)
    return out


status_lock = threading.Lock()
status: dict[str, Any] = {"running": False, "message": "", "error": None, "warnings": []}


def set_status(**kw: Any) -> None:
    with status_lock:
        status.update(kw)


def read_window(con: sqlite3.Connection, endpoints: dict, window: list[str]) -> bool:
    """Store one date window from every endpoint. False if any endpoint failed."""
    ok = True
    for name, fetch in endpoints.items():
        try:
            merge_days(con, fetch(*window))
        except Exception as e:  # noqa: BLE001
            if "TooManyRequests" in type(e).__name__:
                raise  # back off completely; the next sync carries on
            ok = False
            with status_lock:
                status["warnings"].append(f"{name} {window[0]}..{window[1]}: {e}")
        time.sleep(CALL_PAUSE)
    return ok


def run_sync() -> None:
    con = db()
    today = dt.date.today()
    try:
        g = api()
        first_sync = kv_get(con, "last_sync") is None
        # slim_activity() gained a field: read the whole list again once, so old rows get it too.
        full_list = first_sync or kv_get(con, "activity_list_version", 1) < ACTIVITY_LIST_VERSION

        # Activities: full history once, then just the recent window.
        set_status(message="Reading activities")
        since = today - dt.timedelta(days=365 * HISTORY_YEARS if full_list else RECENT_ACTIVITY_DAYS)
        acts = g.get_activities_by_date(since.isoformat(), today.isoformat())
        seen = set()
        for a in acts:
            row = slim_activity(a)
            seen.add(row["activityId"])
            con.execute("INSERT OR REPLACE INTO activities VALUES (?, ?, ?)",
                        (row["activityId"], row["startTimeLocal"][:10], json.dumps(row)))
        kept = con.execute("SELECT id FROM activities WHERE day >= ?", (since.isoformat(),)).fetchall()
        for (aid,) in kept:  # deleted on Garmin since the last sync
            if aid not in seen:
                con.execute("DELETE FROM activities WHERE id = ?", (aid,))
        con.commit()
        kv_set(con, "activity_list_version", ACTIVITY_LIST_VERSION)

        # Wellness: the recent window every time, plus whatever backfill is still pending.
        endpoints = wellness_endpoints()
        set_status(message="Reading recent recovery data")
        read_window(con, endpoints, [(today - dt.timedelta(days=RECENT_WELLNESS_DAYS)).isoformat(), today.isoformat()])

        pending = kv_get(con, "pending_windows")
        if pending is None:
            oldest = con.execute("SELECT MIN(day) FROM activities").fetchone()[0]
            start = dt.date.fromisoformat(oldest) if oldest else today - dt.timedelta(days=365)
            pending = chunks(start, today)
        failed = []
        for i, window in enumerate(pending):
            set_status(message=f"Reading history {window[0][:7]} ({i + 1} of {len(pending)})")
            if not read_window(con, endpoints, window):
                failed.append(window)
            kv_set(con, "pending_windows", failed + pending[i + 1:])  # safe to stop at any point

        # Current values and the calendar.
        set_status(message="Reading profile and calendar")
        profile = kv_get(con, "profile", {})
        readers = {
            "ftp": g.get_cycling_ftp,
            "threshold": lambda: g.get_lactate_threshold().get("speed_and_heart_rate"),
            "hrZones": g.get_heart_rate_zones,
            "garminLoad": lambda: garmin_load(today),
            "records": g.get_personal_record,
            "recordTypes": g.get_personal_record_types,
            "planned": lambda: [
                {"day": p.get("calendarDate"), "name": (p.get("workout") or {}).get("workoutName"),
                 "sport": ((p.get("workout") or {}).get("sportType") or {}).get("sportTypeKey"),
                 "secs": (p.get("workout") or {}).get("estimatedDurationInSecs"),
                 "done": p.get("associatedActivityId")}
                for p in g.get_scheduled_workouts_by_period(
                    (today - dt.timedelta(days=PLANNED_BACK)).isoformat(),
                    (today + dt.timedelta(days=PLANNED_AHEAD)).isoformat())
            ],
        }
        for key, read in readers.items():
            try:
                profile[key] = read()
            except Exception as e:  # noqa: BLE001
                with status_lock:
                    status["warnings"].append(f"{key}: {e}")
            time.sleep(CALL_PAUSE)
        kv_set(con, "profile", profile)
        read_run_laps(con, today, profile)
        kv_set(con, "last_sync", time.time())
        set_status(message="Up to date", error=None)
    except Exception as e:  # noqa: BLE001
        hint = " Run 'python login.py' again." if "auth" in f"{type(e).__name__} {e}".lower() else ""
        set_status(message="Sync failed", error=f"{type(e).__name__}: {e}.{hint}")
    finally:
        con.close()
        set_status(running=False)


def start_sync() -> bool:
    with status_lock:
        if status["running"]:
            return False
        status.update(running=True, message="Starting", error=None, warnings=[])
    threading.Thread(target=run_sync, daemon=True).start()
    return True


def thin(indices: range | list[int], limit: int) -> list[int]:
    idx = list(indices)
    if len(idx) <= limit:
        return idx
    step = len(idx) / limit
    return [idx[int(i * step)] for i in range(limit)]


def read_details(activity_id: int) -> dict:
    """Streams, route and laps for one activity (fetched once, then cached)."""
    g = api()
    raw = g.get_activity_details(activity_id)
    columns = {m["key"]: m["metricsIndex"] for m in raw.get("metricDescriptors") or []}
    samples = raw.get("activityDetailMetrics") or []
    picks = thin(range(len(samples)), STREAM_POINTS)
    streams: dict[str, list] = {}
    for key, short in STREAMS.items():
        if key in columns and short not in streams:
            values = [samples[i]["metrics"][columns[key]] for i in picks]
            if any(v is not None for v in values):
                streams[short] = [round(v, 3) if isinstance(v, float) else v for v in values]
    poly = (raw.get("geoPolylineDTO") or {}).get("polyline") or []
    route = [[p["lat"], p["lon"]] for p in (poly[i] for i in thin(range(len(poly)), ROUTE_POINTS))
             if p.get("lat") is not None and p.get("lon") is not None]
    laps = []
    for lap in (g.get_activity_splits(activity_id) or {}).get("lapDTOs") or []:
        row = {k: lap.get(k) for k in LAP_FIELDS if lap.get(k) is not None}
        # Pool swims: one entry per length (rests are 0 m laps without real lengths).
        lengths = [{"distance": x.get("distance"), "duration": x.get("duration"),
                    "strokes": x.get("totalNumberOfStrokes"), "swolf": x.get("averageSWOLF"),
                    "stroke": x.get("swimStroke"), "hr": x.get("averageHR")}
                   for x in lap.get("lengthDTOs") or [] if x.get("distance")]
        if lengths:
            row["lengths"] = lengths
        laps.append(row)
    return {"v": DETAIL_VERSION, "streams": streams, "route": route, "laps": laps}


# ------------------------------------------------------------------- web pages

async def home(_: Request) -> FileResponse:
    # Everything the page needs is served from here; the browser refuses anything else.
    csp = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:"
    return FileResponse(HTML_FILE, headers={"Content-Security-Policy": csp, "Cache-Control": "no-cache"})


async def data(_: Request) -> JSONResponse:
    con = db()
    try:
        return JSONResponse({
            "activities": [json.loads(r[0]) for r in con.execute("SELECT json FROM activities ORDER BY day")],
            "days": {r[0]: json.loads(r[1]) for r in con.execute("SELECT day, json FROM days ORDER BY day")},
            "profile": kv_get(con, "profile", {}),
            "runLaps": kv_get(con, "run_laps", {}),
            "lastSync": kv_get(con, "last_sync"),
            "staleAfter": STALE_AFTER,
            "today": dt.date.today().isoformat(),
        })
    finally:
        con.close()


async def sync_status(_: Request) -> JSONResponse:
    with status_lock:
        return JSONResponse(dict(status))


async def sync(request: Request) -> JSONResponse:
    # A custom header can't be sent cross-site, so other websites can't trigger this.
    if request.headers.get("x-dashboard") != "1":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return JSONResponse({"started": start_sync()})


async def activity(request: Request) -> JSONResponse:
    aid = request.path_params["id"]
    con = db()
    try:
        row = con.execute("SELECT json FROM details WHERE id = ?", (aid,)).fetchone()
        cached = json.loads(row[0]) if row else None
        if cached and cached.get("v", 1) >= DETAIL_VERSION:
            return JSONResponse(cached)
        known = con.execute("SELECT 1 FROM activities WHERE id = ?", (aid,)).fetchone()
        if not known:
            return JSONResponse({"error": "unknown activity"}, status_code=404)
        try:
            detail = read_details(aid)
        except Exception as e:  # noqa: BLE001
            if cached:  # offline or Garmin hiccup: the older cached version is still useful
                return JSONResponse(cached)
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=502)
        con.execute("INSERT OR REPLACE INTO details VALUES (?, ?)", (aid, json.dumps(detail)))
        con.commit()
        return JSONResponse(detail)
    finally:
        con.close()


app = Starlette(
    routes=[
        Route("/", home),
        Route("/api/data", data),
        Route("/api/status", sync_status),
        Route("/api/sync", sync, methods=["POST"]),
        Route("/api/activity/{id:int}", activity),
    ],
    # Rejects requests that arrive under any other hostname (DNS rebinding).
    middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])],
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Garmin training dashboard")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    print(f"Dashboard: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
