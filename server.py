"""Personal Garmin Connect MCP server (runs locally, talks only to Garmin).

Claude desktop starts this script itself (see README). It uses saved sign-in
tokens; the password is only ever typed into the local sign-in page that
garmin_login opens (weblogin.py) or into login.py, never into the chat.
"""

import datetime as dt
import io
import os
import socket
import sys
import threading
import time
import webbrowser
import zipfile
from pathlib import Path
from typing import Any, Literal

from garminconnect import Garmin
from garminconnect import workout as w
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

import fitmerge
import weblogin

TOKEN_DIR = Path(os.getenv("GARMINTOKENS", Path.home() / ".garminconnect"))
FIT_DIR = Path(os.getenv("GARMIN_FIT_DIR", Path.home() / "Documents" / "Garmin FIT"))
DASHBOARD_PORT = int(os.getenv("GARMIN_DASHBOARD_PORT", "8765"))
MAX_LIST = 40  # long time series get cut so answers stay readable

mcp = MCPServer(
    "garmin",
    instructions=(
        "Personal Garmin Connect data for training coaching. If a tool says the "
        "user isn't signed in, call garmin_login: it opens a sign-in page in the "
        "user's browser. Never ask for the Garmin password in the chat. If the user "
        "seems new, says hi, or asks what this can do, call getting_started and give a "
        "short welcome. "
        "open_dashboard opens the user's training dashboard in the browser. Dates are "
        "YYYY-MM-DD. Use daily_overview for recovery (sleep, HRV, readiness, "
        "Body Battery), list_activities / activity_details for training done, "
        "training_status for load and VO2max, and create_run/bike/swim_workout to put "
        "planned sessions on the user's Garmin calendar. Workout tools: run, bike "
        "and swim; steps end after 'minutes'/'seconds' or 'meters' (neither = lap button); "
        "wrap repeats as {\"repeat\": n, \"steps\": [...]}; give 'date' to put "
        "the workout on the Garmin calendar so it syncs to the watch. "
        "To join activities that were split by accident, use combine_activities; "
        "it never deletes anything. delete_activity is permanent: always ask the "
        "user and wait for an explicit yes before calling it."
    ),
)

_api: Garmin | None = None


NOT_SIGNED_IN = ("Not signed in to Garmin. Call the garmin_login tool: it opens a "
                 "sign-in page in the user's browser (never ask for the password in the chat).")


def api() -> Garmin:
    """Log in lazily from saved tokens (no password)."""
    global _api
    if _api is None:
        if not TOKEN_DIR.exists():
            raise RuntimeError(NOT_SIGNED_IN)
        try:
            g = Garmin()
            g.login(str(TOKEN_DIR))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"{NOT_SIGNED_IN} (Details: {type(e).__name__}: {e})") from e
        _api = g
    return _api


def slim(x: Any) -> Any:
    """Drop empty values and shorten long lists (Garmin JSON is huge)."""
    if isinstance(x, dict):
        out = {k: slim(v) for k, v in x.items() if v not in (None, "", [], {})}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(x, list):
        if len(x) > MAX_LIST:
            return {"note": f"{len(x)} items, showing first {MAX_LIST}", "items": [slim(i) for i in x[:MAX_LIST]]}
        return [slim(i) for i in x]
    return x


def safe(fn, *args, **kwargs) -> Any:
    """Call Garmin; return an error note instead of failing the whole tool."""
    try:
        return slim(fn(*args, **kwargs))
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def today() -> str:
    return dt.date.today().isoformat()


# ------------------------------------------------------- sign-in and dashboard

WELCOME = {
    "what_you_can_do": [
        "Recovery: sleep, HRV, Body Battery, training readiness",
        "Training: recent activities, laps, heart rate zones, training load, VO2max, race predictions",
        "Plan workouts (run, bike, pool swim) that go on the Garmin calendar and sync to the watch",
        "Open a training dashboard with charts in the browser",
        "Join activities that were split by accident",
    ],
    "try_asking": [
        "How did I sleep this week, and am I recovered enough for a hard session today?",
        "Summarize my training of the last 4 weeks.",
        "Plan 6x800 m intervals for Thursday and put them on my watch.",
        "Open my training dashboard.",
    ],
    "for_claude": "Give the user a SHORT welcome: one sentence, the list of what they can do "
                  "(one line each), and 2-3 of the example questions. No more than that.",
}

_login_page: weblogin.LoginPage | None = None


@mcp.prompt(title="Get started with Garmin",
            description="Sign in to Garmin and see what you can do with this connection")
def get_started() -> str:
    return ("I just installed the Garmin connection. Sign me in to Garmin if I'm not signed in "
            "yet, then tell me very briefly what I can do with it and give me a few example "
            "questions I could ask.")


@mcp.tool()
def getting_started() -> dict:
    """What this Garmin connection can do, with example questions. Use it when the
    user is new, asks what they can do, or asks for help with Garmin."""
    try:
        name = api().get_full_name()
        status = {"signed_in": True, "name": name}
    except Exception:  # noqa: BLE001
        status = {"signed_in": False, "next": "Offer to sign them in with garmin_login first."}
    return {**status, **WELCOME}


@mcp.tool()
def garmin_login(switch_account: bool = False) -> dict:
    """Sign the user in to Garmin Connect. Opens a sign-in page in the user's web
    browser where THEY type their Garmin email, password and (if Garmin asks) a
    security code. Never ask for the password in the chat. Waits up to ~50 s for
    them to finish; if it's not finished yet, ask the user to complete it and then
    call this again. switch_account=True signs in again even if already signed in."""
    global _api, _login_page
    if not switch_account and (_login_page is None or not _login_page.active):
        try:
            return {"signed_in": True, "name": api().get_full_name()}
        except Exception:  # noqa: BLE001
            pass  # no or expired tokens: open the page
    opened = False
    if _login_page is None or not _login_page.active:
        _login_page = weblogin.LoginPage(TOKEN_DIR)
        opened = webbrowser.open(_login_page.url)
    if _login_page.done.wait(50):
        _api = None  # use the new tokens from now on
        return {"signed_in": True, "name": _login_page.name, "just_signed_in": True, **WELCOME}
    return {
        "signed_in": False,
        "sign_in_page": _login_page.url,
        "browser_opened": opened,
        "next": "Tell the user a Garmin sign-in page is open in their browser (if they "
                "can't see it, give them the link). When they say they're done, call "
                "garmin_login again. Never ask for their password here.",
    }


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


_dashboard_started = False


@mcp.tool()
def open_dashboard() -> dict:
    """Open the user's training dashboard (training load, activities, sleep, HRV,
    swim intervals, calendar) in their web browser. It runs on this computer while
    the Claude app is open. The first load can take a few minutes while it reads
    the history from Garmin."""
    global _dashboard_started
    url = f"http://127.0.0.1:{DASHBOARD_PORT}"
    try:
        api()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    if not _dashboard_started and not _port_open(DASHBOARD_PORT):
        try:
            import uvicorn
            sys.modules.setdefault("server", sys.modules[__name__])  # dashboard shares this login
            import dashboard
            srv = uvicorn.Server(uvicorn.Config(
                dashboard.app, host="127.0.0.1", port=DASHBOARD_PORT,
                log_level="warning", access_log=False))  # stdout belongs to MCP
            threading.Thread(target=srv.run, daemon=True).start()
            for _ in range(50):
                if srv.started:
                    break
                time.sleep(0.2)
            else:
                return {"error": f"The dashboard didn't start (is port {DASHBOARD_PORT} in use?)."}
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}
    _dashboard_started = True
    opened = webbrowser.open(url)
    return {"url": url, "browser_opened": opened,
            "note": "Runs while the Claude app is open. If the browser didn't open, give the user the link."}


# ---------------------------------------------------------------- read tools

@mcp.tool()
def daily_overview(date: str | None = None) -> dict:
    """Recovery snapshot for one day: sleep, HRV, training readiness,
    Body Battery, resting HR, stress and steps. date = YYYY-MM-DD (default today)."""
    d = date or today()
    g = api()
    sleep = safe(g.get_sleep_data, d)
    if isinstance(sleep, dict):  # keep the summary, drop minute-by-minute data
        sleep = {k: v for k, v in sleep.items() if k in ("dailySleepDTO", "avgOvernightHrv", "hrvStatus", "restingHeartRate", "avgSleepStress", "bodyBatteryChange")}
    summary = safe(g.get_user_summary, d)
    if isinstance(summary, dict):
        keep = ("restingHeartRate", "averageStressLevel", "totalSteps", "activeKilocalories",
                "bodyBatteryHighestValue", "bodyBatteryLowestValue", "bodyBatteryMostRecentValue",
                "moderateIntensityMinutes", "vigorousIntensityMinutes")
        summary = {k: v for k, v in summary.items() if k in keep}
    hrv = safe(g.get_hrv_data, d)
    if isinstance(hrv, dict):
        hrv = hrv.get("hrvSummary", hrv)
    return {
        "date": d,
        "sleep": sleep,
        "hrv": hrv,
        "training_readiness": safe(g.get_training_readiness, d),
        "day_summary": summary,
    }


@mcp.tool()
def list_activities(start_date: str, end_date: str | None = None) -> list | dict:
    """Activities between two dates (YYYY-MM-DD), with the key numbers:
    type, distance, duration, pace/speed, HR, training effect, load."""
    acts = api().get_activities_by_date(start_date, end_date or today())
    keep = ("activityId", "activityName", "startTimeLocal", "distance", "duration",
            "averageSpeed", "averageHR", "maxHR", "calories", "elevationGain",
            "aerobicTrainingEffect", "anaerobicTrainingEffect", "activityTrainingLoad",
            "trainingEffectLabel", "avgPower", "normPower", "averageRunningCadenceInStepsPerMinute")
    out = []
    for a in acts:
        row = {k: a.get(k) for k in keep if a.get(k) is not None}
        row["type"] = (a.get("activityType") or {}).get("typeKey")
        out.append(row)
    return slim(out)


@mcp.tool()
def activity_details(activity_id: str) -> dict:
    """One activity in depth: summary, laps/splits and time in HR zones."""
    g = api()
    return {
        "summary": safe(lambda: g.get_activity(activity_id).get("summaryDTO")),
        "splits": safe(lambda: (g.get_activity_splits(activity_id) or {}).get("lapDTOs")),
        "hr_zones": safe(g.get_activity_hr_in_timezones, activity_id),
    }


@mcp.tool()
def training_status(date: str | None = None) -> dict:
    """Training status, load balance, VO2max and race predictions."""
    d = date or today()
    g = api()
    return {
        "date": d,
        "training_status": safe(g.get_training_status, d),
        "race_predictions": safe(g.get_race_predictions),
    }


@mcp.tool()
def scheduled_workouts(year: int, month: int) -> dict:
    """Workouts already on the Garmin calendar for a month."""
    return safe(api().get_scheduled_workouts, year, month)


# --------------------------------------------------------------- write tools
#
# One step model for all sports. A step ends after `minutes`, after `meters`,
# or (if neither is given) when you press the lap button.

STEP_TYPES = {  # Garmin step type id, key
    "warmup": (1, "warmup"),
    "cooldown": (2, "cooldown"),
    "work": (3, "interval"),
    "recovery": (4, "recovery"),
    "rest": (5, "rest"),
}

# Fallback only; normally the ids come live from Garmin (see _stroke_types).
FALLBACK_STROKES = {"any": 1, "back": 2, "breast": 3, "drill": 4, "fly": 5, "free": 6, "im": 7, "mixed": 8}
STROKE_ALIASES = {"any": "any_stroke", "back": "backstroke", "breast": "breaststroke",
                  "fly": "fly", "free": "free", "drill": "drill", "im": "individual_medley", "mixed": "mixed"}

SPORTS = {
    "running": {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
    "cycling": {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2},
    "swimming": {"sportTypeId": 4, "sportTypeKey": "swimming", "displayOrder": 3},
}


class Step(BaseModel):
    kind: Literal["warmup", "work", "run", "recovery", "rest", "cooldown"] = Field(
        description="Step type ('run' = 'work')")
    minutes: float | None = Field(None, gt=0, description="End after this many minutes")
    seconds: float | None = Field(None, gt=0, description="End after this many seconds (can add to minutes)")
    meters: float | None = Field(None, gt=0, description="End after this distance (swim lengths, run/bike distance)")
    note: str | None = Field(None, description="Short text shown on the watch for this step")
    # --- targets (use one primary target per step)
    hr_zone: int | None = Field(None, ge=1, le=5, description="Heart-rate zone 1-5")
    pace_fast: str | None = Field(None, description="Run: fastest pace 'm:ss' per km")
    pace_slow: str | None = Field(None, description="Run: slowest pace 'm:ss' per km")
    ftp_low: float | None = Field(None, gt=0, description="Bike: lower power bound in % of FTP, e.g. 88")
    ftp_high: float | None = Field(None, gt=0, description="Bike: upper power bound in % of FTP, e.g. 94")
    power_zone: int | None = Field(None, ge=1, le=7, description="Bike: Garmin power zone 1-7")
    speed_low: float | None = Field(None, gt=0, description="Bike: lower speed in km/h")
    speed_high: float | None = Field(None, gt=0, description="Bike: upper speed in km/h")
    cadence_low: int | None = Field(None, gt=0, description="Bike/run: lower cadence (rpm/spm), secondary target")
    cadence_high: int | None = Field(None, gt=0, description="Bike/run: upper cadence, secondary target")
    swim_pace_fast: str | None = Field(None, description="Swim: fastest pace 'm:ss' per 100 m")
    swim_pace_slow: str | None = Field(None, description="Swim: slowest pace 'm:ss' per 100 m")
    stroke: Literal["free", "back", "breast", "fly", "im", "drill", "mixed", "any"] | None = Field(
        None, description="Swim: stroke for this step")


class Repeat(BaseModel):
    repeat: int = Field(ge=2, description="How many times to repeat")
    steps: list[Step]


def _secs(p: str) -> int:
    m, s = p.strip().split(":")
    return int(m) * 60 + int(s)


def _range_target(type_id: int, key: str, low: float, high: float, unit: dict | None = None) -> dict:
    low, high = sorted((low, high))
    d = {"targetType": {"workoutTargetTypeId": type_id, "workoutTargetTypeKey": key, "displayOrder": 1},
         "targetValueOne": low, "targetValueTwo": high}
    if unit:
        d["targetValueUnit"] = unit
    return d


def _primary_target(st: Step) -> dict:
    if st.ftp_low and st.ftp_high:  # native "% FTP": Garmin converts with your current FTP
        return _range_target(2, "power.zone", st.ftp_low, st.ftp_high, {"unitKey": "percent"})
    if st.power_zone:
        return {"targetType": {"workoutTargetTypeId": 2, "workoutTargetTypeKey": "power.zone", "displayOrder": 1},
                "zoneNumber": st.power_zone}
    if st.speed_low and st.speed_high:
        return _range_target(5, "speed.zone", st.speed_low / 3.6, st.speed_high / 3.6)
    if st.pace_fast and st.pace_slow:
        return _range_target(6, "pace.zone", 1000 / _secs(st.pace_slow), 1000 / _secs(st.pace_fast))
    if st.swim_pace_fast and st.swim_pace_slow:
        return _range_target(6, "pace.zone", 100 / _secs(st.swim_pace_slow), 100 / _secs(st.swim_pace_fast))
    if st.hr_zone:
        return {"targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 1},
                "zoneNumber": st.hr_zone}
    return {"targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}}


_stroke_cache: dict[str, int] | None = None


def _stroke_types() -> dict[str, int]:
    """strokeTypeKey -> id, read from Garmin's own workout type list."""
    global _stroke_cache
    if _stroke_cache is None:
        found: dict[str, int] = {}

        def walk(x: Any) -> None:
            if isinstance(x, dict):
                if "strokeTypeKey" in x and "strokeTypeId" in x:
                    found[x["strokeTypeKey"]] = x["strokeTypeId"]
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        try:
            walk(api().get_workout_types())
        except Exception:  # noqa: BLE001
            pass
        _stroke_cache = found
    return _stroke_cache


def _stroke(name: str) -> dict:
    key = STROKE_ALIASES[name]
    live = _stroke_types()
    if key in live:
        return {"strokeTypeId": live[key], "strokeTypeKey": key, "displayOrder": live[key]}
    sid = FALLBACK_STROKES[name]
    return {"strokeTypeId": sid, "strokeTypeKey": key, "displayOrder": sid}


def _build_step(st: Step, order: int, sport: str) -> w.ExecutableStep:
    tid, tkey = STEP_TYPES["work" if st.kind == "run" else st.kind]
    if st.minutes or st.seconds:
        end = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
        val = (st.minutes or 0) * 60 + (st.seconds or 0)
    elif st.meters:
        end, val = {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 3, "displayable": True}, st.meters
    else:
        end, val = {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True}, None
    data: dict[str, Any] = {
        "stepOrder": order,
        "stepType": {"stepTypeId": tid, "stepTypeKey": tkey, "displayOrder": tid},
        "endCondition": end,
        "endConditionValue": val,
        "description": st.note,
        **_primary_target(st),
    }
    if st.cadence_low and st.cadence_high:
        lo, hi = sorted((st.cadence_low, st.cadence_high))
        data |= {"secondaryTargetType": {"workoutTargetTypeId": 3, "workoutTargetTypeKey": "cadence", "displayOrder": 2},
                 "secondaryTargetValueOne": lo, "secondaryTargetValueTwo": hi}
    if sport == "swimming":
        data["strokeType"] = _stroke(st.stroke or "free")
        data["equipmentType"] = {"equipmentTypeId": 0, "displayOrder": 0}
    return w.ExecutableStep(**data)


def _estimate_secs(st: Step, sport: str) -> float:
    if st.minutes or st.seconds:
        return (st.minutes or 0) * 60 + (st.seconds or 0)
    if st.meters:
        if sport == "swimming":
            per100 = _secs(st.swim_pace_slow) if st.swim_pace_slow else 120
            return st.meters / 100 * per100
        if sport == "running":
            return st.meters / 1000 * (_secs(st.pace_slow) if st.pace_slow else 330)
        return st.meters / 1000 * (3600 / (st.speed_low or 28))
    return 0


def _create(sport: str, name: str, steps: list[Step | Repeat], date: str | None,
            description: str | None, extra: dict | None = None) -> dict:
    order, total, built = 0, 0.0, []
    for item in steps:
        order += 1
        if isinstance(item, Repeat):
            group_order, inner = order, []
            for st in item.steps:
                order += 1
                inner.append(_build_step(st, order, sport))
                total += _estimate_secs(st, sport) * item.repeat
            built.append(w.create_repeat_group(item.repeat, inner, group_order))
        else:
            built.append(_build_step(item, order, sport))
            total += _estimate_secs(item, sport)

    workout = w.BaseWorkout(
        workoutName=name,
        sportType=SPORTS[sport],
        description=description,
        estimatedDurationInSecs=int(total),
        workoutSegments=[w.WorkoutSegment(segmentOrder=1, sportType=SPORTS[sport], workoutSteps=built)],
        **(extra or {}),
    )
    g = api()
    created = g.upload_workout(workout.to_dict())
    wid = created.get("workoutId")
    result = {"workoutId": wid, "name": name, "sport": sport, "estimated_minutes": round(total / 60)}
    if date and wid:
        result["scheduled"] = safe(g.schedule_workout, wid, date)
    return result




@mcp.tool()
def create_run_workout(name: str, steps: list[Step | Repeat], date: str | None = None,
                       description: str | None = None) -> dict:
    """Create a structured RUN workout. Targets: pace_fast/pace_slow ('m:ss' per km),
    hr_zone, or cadence. Example: [{"kind":"warmup","minutes":15},
    {"repeat":5,"steps":[{"kind":"work","minutes":4,"pace_fast":"4:10","pace_slow":"4:20"},
    {"kind":"recovery","minutes":2}]},{"kind":"cooldown","minutes":10}]"""
    return _create("running", name, steps, date, description)


@mcp.tool()
def create_bike_workout(name: str, steps: list[Step | Repeat], date: str | None = None,
                        description: str | None = None) -> dict:
    """Create a structured BIKE workout. Targets: ftp_low/ftp_high (% of FTP; the watch
    shows the matching watts from the user's current FTP), power_zone 1-7,
    speed_low/speed_high (km/h), hr_zone; optional cadence_low/high.
    Example sweet spot: [{"kind":"warmup","minutes":15,"ftp_low":50,"ftp_high":65},
    {"repeat":3,"steps":[{"kind":"work","minutes":12,"ftp_low":88,"ftp_high":94},
    {"kind":"recovery","minutes":5,"ftp_low":45,"ftp_high":55}]},
    {"kind":"cooldown","minutes":10,"ftp_low":40,"ftp_high":55}]"""
    return _create("cycling", name, steps, date, description)


@mcp.tool()
def create_swim_workout(name: str, steps: list[Step | Repeat], pool_length_m: float = 25,
                        date: str | None = None, description: str | None = None) -> dict:
    """Create a structured POOL SWIM workout. Use 'meters' for swim steps and 'rest'
    steps with 'seconds' (e.g. 20) between reps. Per step: stroke
    (free/back/breast/fly/im/drill/mixed/any), optional swim_pace_fast/slow
    ('m:ss' per 100 m), note. Example: [{"kind":"warmup","meters":300,"stroke":"free"},
    {"repeat":8,"steps":[{"kind":"work","meters":100,"stroke":"free","swim_pace_fast":"1:45","swim_pace_slow":"1:50"},
    {"kind":"rest","seconds":20}]},{"kind":"cooldown","meters":200,"stroke":"any"}]"""
    extra = {"poolLength": float(pool_length_m),
             "poolLengthUnit": {"unitId": 1, "unitKey": "meter", "factor": 100.0}}
    return _create("swimming", name, steps, date, description, extra)


@mcp.tool()
def delete_workout(workout_id: str) -> dict:
    """Delete a workout (and its calendar entries) from Garmin Connect."""
    return safe(api().delete_workout, workout_id)


@mcp.tool()
def cycling_ftp() -> dict:
    """The user's current cycling FTP from Garmin (watts)."""
    return safe(api().get_cycling_ftp)


# ------------------------------------------------------------- FIT file tools
#
# Files live in FIT_DIR on this computer (default Documents/Garmin FIT) and never
# leave it except to go to Garmin.

def _fit_path(p: str) -> Path:
    """Relative names are inside FIT_DIR; '.fit' is added if missing."""
    path = Path(p)
    if not path.is_absolute():
        path = FIT_DIR / path
    return path if path.suffix.lower() == ".fit" else path.with_suffix(".fit")


def _download_fit(activity_id: str) -> Path:
    data = api().download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
    FIT_DIR.mkdir(parents=True, exist_ok=True)
    out = FIT_DIR / f"{activity_id}_ACTIVITY.fit"
    if data[:2] == b"PK":  # Garmin sends the original as a zip
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            fits = [n for n in z.namelist() if n.lower().endswith(".fit")]
            if not fits:
                raise RuntimeError(f"Activity {activity_id} has no original .fit file "
                                   "(it was probably uploaded as GPX/TCX or entered manually)")
            data = z.read(fits[0])
    out.write_bytes(data)
    return out


def _start_utc(path: Path) -> dt.datetime:
    f = fitmerge.read_fit(path)
    s = f.of(fitmerge.SESSION)
    ts = s[0].get(2) if s else None
    if ts is None:
        ts = next(m.get(fitmerge.TIMESTAMP) for m in f.messages if m.num == fitmerge.RECORD)
    return dt.datetime.fromtimestamp(ts + fitmerge.FIT_EPOCH, dt.timezone.utc)


def _upload(path: Path, exclude: set[str] = frozenset()) -> dict:
    """Upload a .fit and find the new activity id (Garmin may process it async)."""
    g = api()
    resp = g.upload_activity(str(path))
    body = resp.json() if hasattr(resp, "json") else resp
    result = (body or {}).get("detailedImportResult", body) or {}
    failures = result.get("failures") or []
    if failures:
        msgs = [m.get("content") for f in failures for m in (f.get("messages") or [])]
        return {"uploaded": False, "error": "; ".join(filter(None, msgs)) or str(failures)}
    ids = [str(s["internalId"]) for s in result.get("successes") or [] if s.get("internalId")]
    if not ids:  # not processed yet: look it up by start time
        start = _start_utc(path)
        day = start.date()
        for _ in range(10):
            time.sleep(3)
            acts = g.get_activities_by_date((day - dt.timedelta(days=1)).isoformat(),
                                            (day + dt.timedelta(days=1)).isoformat())
            for a in acts:
                gmt = a.get("startTimeGMT")
                if gmt and str(a.get("activityId")) not in exclude:
                    t = dt.datetime.fromisoformat(gmt).replace(tzinfo=dt.timezone.utc)
                    if abs((t - start).total_seconds()) < 5:
                        ids.append(str(a["activityId"]))
            if ids:
                break
    out = {"uploaded": True, "activity_id": ids[0] if ids else None}
    if not ids:
        out["note"] = "Garmin accepted the file but is still processing it; check list_activities in a minute."
    return out


@mcp.tool()
def download_fit(activity_id: str) -> dict:
    """Save an activity's original .fit file to the local FIT folder on this computer.
    Returns the file path (use it with merge_fit / upload_fit)."""
    try:
        p = _download_fit(activity_id)
        return {"path": str(p), "kb": round(p.stat().st_size / 1024)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def merge_fit(paths: list[str], out_path: str | None = None) -> dict:
    """Merge 2+ local .fit activity files (same sport, not overlapping in time) into
    one activity. The time between them becomes a pause; all laps, GPS and sensor
    data are kept and the totals are recalculated. Relative paths are in the FIT
    folder. Does not upload anything."""
    try:
        return _merge([_fit_path(p) for p in paths], _fit_path(out_path) if out_path else None)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def _merge(files: list[Path], out: Path | None = None) -> dict:
    out = out or FIT_DIR / ("merged_" + "_".join(f.stem.replace("_ACTIVITY", "") for f in files) + ".fit")
    out.parent.mkdir(parents=True, exist_ok=True)
    return fitmerge.merge_fit_files(files, out)


def _rename(activity_id: str, name: str) -> bool:
    try:
        api().set_activity_name(activity_id, name)
        return True
    except Exception:  # noqa: BLE001
        return False


@mcp.tool()
def upload_fit(path: str, name: str | None = None) -> dict:
    """Upload a local .fit file to Garmin Connect as a new activity (it then syncs to
    Strava etc. like a watch upload). Optional name sets the activity title."""
    try:
        res = _upload(_fit_path(path))
        if name and res.get("activity_id"):
            res["renamed"] = _rename(res["activity_id"], name)
        return res
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def delete_activity(activity_id: str) -> dict:
    """PERMANENTLY delete an activity from Garmin Connect. Only call this after the
    user has explicitly said yes to deleting this specific activity in the chat.
    A backup of the original .fit is saved to the FIT folder first; if the backup
    fails, nothing is deleted. Does not delete it on Strava."""
    try:
        backup = FIT_DIR / f"{activity_id}_ACTIVITY.fit"
        if not backup.exists():
            backup = _download_fit(activity_id)
    except Exception as e:  # noqa: BLE001
        return {"deleted": False, "error": f"Backup failed, nothing deleted: {type(e).__name__}: {e}"}
    res = safe(api().delete_activity, activity_id)
    if isinstance(res, dict) and "error" in res:
        return {"deleted": False, "backup": str(backup), **res}
    return {"deleted": True, "activity_id": activity_id, "backup": str(backup)}


@mcp.tool()
def combine_activities(activity_ids: list[str], name: str | None = None) -> dict:
    """Join 2+ Garmin activities that were split by accident into one: downloads the
    originals, merges them (gaps become pauses, laps kept) and uploads the result.
    The originals are NOT deleted: afterwards, ask the user whether to delete them
    with delete_activity. name = title for the new activity (default: the first
    original's title)."""
    try:
        g = api()
        paths = [_download_fit(a) for a in activity_ids]
        merged = _merge(paths)
        if name is None:
            starts = sorted(zip((_start_utc(p) for p in paths), activity_ids))
            name = (safe(g.get_activity, starts[0][1]) or {}).get("activityName")
        up = _upload(Path(merged["out_path"]), exclude=set(map(str, activity_ids)))
        if name and up.get("activity_id"):
            up["renamed"] = _rename(up["activity_id"], name)
        return {
            "merged": merged,
            "upload": up,
            "name": name,
            "originals_still_in_garmin": activity_ids,
            "next": "Ask the user before deleting the originals with delete_activity. "
                    "On Strava the originals must be deleted by hand (Strava's API can't delete).",
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    mcp.run()  # stdio, which is what Claude desktop expects
