# CLAUDE.md

Notes for Claude: what this project is, how it's built, and what has been done
so far. Add a new entry to the **History** section whenever you make changes.

## What this is
`garmin-mcp`: a personal, local MCP server that lets the Claude desktop app
read Garmin Connect data and write to it, plus a local training dashboard.
Windows, Python 3.13, venv in `.venv`.

| File | Role |
|---|---|
| `server.py` | MCP server (stdio), started by Claude desktop. Every tool is in this file. |
| `fitmerge.py` | FIT file reader, writer and merger, using only the standard library |
| `swimfit.py` | Pool swim → "interval" FIT for Strava (built on fitmerge) |
| `strava.py` | Strava API client, stdlib only: token refresh, upload, upload status |
| `strava_login.py` | One-time Strava OAuth; tokens in `~/.garminconnect/strava.json` |
| `sync_strava.py` | Garmin → Strava sync; state + log in the token folder (`GARMINTOKENS`, default `~/.garminconnect/`) |
| `.github/workflows/strava-sync.yml` | Runs `sync_strava.py` hourly on GitHub Actions; tokens + state in the Actions cache |
| `export_secrets.py` | Prints the `GARMIN_TOKENS` / `STRAVA_TOKENS` values for the GitHub secrets |
| `login.py` | One-time Garmin login; saves tokens to `~/.garminconnect` (never the password) |
| `dashboard.py` / `dashboard.html` | Local dashboard at `http://127.0.0.1:8765`, cache in `~/.garminconnect/dashboard_cache.sqlite` |
| `requirements.txt` | Pinned: garminconnect 0.3.20, mcp 2.3.0, starlette, uvicorn |

## Conventions
- Tools are plain functions with `@mcp.tool()`. Short docstrings matter, because Claude reads them.
- Garmin calls go through `api()` (lazy login from tokens). Wrap calls in
  `safe(...)` or try/except so a tool returns `{"error": ...}` instead of crashing.
- `slim()` trims Garmin's large JSON responses before they are returned.
- After changing `server.py`, the user must fully quit and reopen Claude desktop.
- Never ask for or handle the Garmin password; the user runs `login.py` themselves.
- Never commit tokens, `.env` or `*.sqlite` (already in `.gitignore`).

## Gotchas
- `fit-tool` (PyPI) **cannot read** this user's fenix 6X files: it fails with a UTF-8
  decode error. That is why `fitmerge.py` exists. Don't switch back to it.
- `garminconnect.import_activity` is **not** forwarded to Strava. Use
  `upload_activity` when the upload should sync to Strava.
- `download_activity(..., ORIGINAL)` returns a zip; the .fit is inside.
- Uploads may be processed asynchronously. `_upload()` then finds the new activity by start time.
- The merged file gets a new `file_id.time_created`, so Garmin doesn't reject the
  upload as a duplicate of the first original.
- Strava's API can't delete activities; the user deletes those by hand.
- `delete_activity` is permanent. Always get the user's explicit yes first.
- Garmin's official decoder `garmin-fit-sdk` is useful for checking FIT output.
  Install it into the scratchpad, not the project.
- Strava draws pool swims from `length` messages. With those removed it uses
  `record.distance`; without record distances it spreads distance over time incl.
  rests. The **website** ignores record distance and folds rests into the next lap
  unless the rest is its own 0 m lap; even then the website view isn't clean. The
  phone app shows the interval version correctly. Tested by hand 2026-11-16.
- Garmin Connect DOES forward `upload_activity` uploads to Strava, but it can take ~20 min.

## History

### 2026-11-16: Garmin → Strava sync with interval swims
Goal: every swim on Strava shows one flat block per interval (between rests),
fully automatic, Garmin untouched.
- Manual experiments on the 16 Nov pool swim (Garmin id 25095714915, now re-uploaded
  as 25097131586 without lengths). v1 (lengths dropped) looked wrong on Strava,
  v2 (+ record distance/speed) fixed the phone app, v3 (+ 0 m rest laps) is the final format.
- Added `swimfit.py` (v3 as a function: `to_intervals`, `is_pool_swim`), `strava.py`,
  `strava_login.py`, `sync_strava.py`, and MCP tools `strava_upload` / `strava_sync`.
- Design: Garmin's own Strava connection gets turned off; `sync_strava.py` uploads
  everything (swims converted, other sports as the original). Nothing is deleted anywhere.
  First run stores `since` = now so history isn't re-uploaded; `--since` backfills.
  `external_id = garmin_<id>`; "duplicate" from Strava is treated as done; errors retry ≤5 runs.
- Tested offline only: swimfit output decodes with garmin-fit-sdk (25 laps, 0 lengths,
  2328 records, distance 0 → 2500 m, never decreasing), same structure as the hand-made v3;
  sync and Strava client tested with fakes. **Not yet tested against live Strava.**
- GitHub Actions (the user's choice, so it runs without the PC): workflow
  `strava-sync.yml` (hourly at :17 + manual button). GitHub has its own Garmin and Strava
  login (`GARMINTOKENS=~/.garminconnect-github`, then `export_secrets.py` → repo secrets),
  because both services renew tokens and a shared login would break one side.
  Renewed tokens, `strava_sync.json` and the log travel in the Actions cache
  (`sync-state-<run_id>`, restored by prefix); secrets only seed an empty cache.
  `sync_strava.py` dumps the refreshed Garmin tokens after every run.
  `strava.TOKEN_FILE` now follows `GARMINTOKENS` (env `STRAVA_TOKENS` still overrides).
  Repo is private: ~750 of 2,000 free Action minutes/month at hourly runs.
- Task Scheduler on the PC stays documented as option B.
- garminconnect 0.3.20 stores tokens in `<tokenstore>/garmin_tokens.json`
  (`di_token`, `di_refresh_token`, `di_client_id`).
- Next: user creates the Strava API app, does the GitHub login + secrets, disconnects
  Garmin's Strava connection, and runs the workflow once by hand (README option A).

### 2026-11-14: dashboard tweaks (uncommitted)
- New `1w` range (last 7 days, daily buckets and daily axis ticks via `useDays()`).
- The range now always starts at `6w` on page load (no longer remembered in localStorage).
- Calendar: unfinished planned workouts from before today are hidden.
- 12-month heatmap labels every weekday (min cell size raised from 8 to 10 px so labels fit).
- Performance prediction tiles: "Claude model" and "Garmin: <time>" on separate lines.
- "Best 20-min power by month": x axis now labels months itself (it used the range's weekly/daily
  ticks, which stacked several labels on one bar for short ranges).
- Prediction formula unchanged on purpose; the user runs a test next week to check it.

### 2026-11-12: activity merge tools (uncommitted)
Goal: join activities that were split by accident (e.g. a run stopped and
restarted) into one Garmin activity that also syncs to Strava.
- Added `fitmerge.py`. It parses raw FIT messages and expands compressed
  timestamps, so all data, including Garmin's undocumented messages, is copied byte for byte.
  Merge rules:
  - settings messages (file_id etc.) are taken from the first file only
  - record distances are offset so they keep increasing
  - laps are renumbered
  - gaps between files become pauses
  - per-file session, activity, split and time-in-zone summaries are dropped
  - one new session + activity is written, with recalculated totals (time-weighted HR, cadence and power)
  - mixed sports, overlapping times and multisport files are rejected
- Added 5 tools to `server.py`: `download_fit`, `merge_fit`, `upload_fit`,
  `delete_activity` (saves a backup .fit first, deletes nothing if the backup fails),
  `combine_activities` (download + merge + upload; never deletes).
  Files go to `FIT_DIR` = `~/Documents/Garmin FIT` (env `GARMIN_FIT_DIR`).
- README: new tools listed, plus a "Joining activities that were split by accident" section.
- Tested offline on `~/Downloads/21880820500_ACTIVITY.fit` + `21880821287_ACTIVITY.fit`
  (two runs on 2026-02-15). The output decodes cleanly with garmin-fit-sdk:
  24.22 km, 25 laps, 122.6 min moving / 219 min elapsed, distance never decreases.
  A read → write round trip reproduces the original messages exactly.
- **Not yet tested against live Garmin** (download, upload, delete).
  Next: the user restarts Claude desktop and tries `combine_activities` on those two runs.
- The user also had uncommitted changes to `dashboard.html`; they were left untouched.

### 0e6de79: update README with a prompt
Added the "Easy setup with Claude" section and a copy-paste setup prompt to the README.

### 6905022: first commit
Initial project: MCP server with read tools (`daily_overview`, `list_activities`,
`activity_details`, `training_status`, `scheduled_workouts`, `cycling_ftp`),
workout tools (`create_run/bike/swim_workout`, `delete_workout`), `login.py`,
the dashboard (`dashboard.py` / `dashboard.html`), README and MIT license.
