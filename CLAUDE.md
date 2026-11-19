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
| `weblogin.py` | Local browser sign-in page used by the `garmin_login` tool (password goes straight to Garmin) |
| `login.py` | Terminal login for the manual setup; saves tokens to `~/.garminconnect` (never the password) |
| `dashboard.py` / `dashboard.html` | Local dashboard at `http://127.0.0.1:8765`, cache in `~/.garminconnect/dashboard_cache.sqlite` |
| `manifest.json` / `pyproject.toml` / `uv.lock` / `.python-version` / `.mcpbignore` | Desktop Extension (`.mcpb`) packaging, `uv` runtime |
| `requirements.txt` | Pinned: garminconnect 0.3.20, mcp 2.3.0, starlette, uvicorn (keep in sync with `pyproject.toml`) |
| `start_dashboard.bat` / `.command` | Start the dashboard without Claude (manual setup, Windows / Mac) |

## Conventions
- Tools are plain functions with `@mcp.tool()`. Short docstrings matter, because Claude reads them.
- Garmin calls go through `api()` (lazy login from tokens). Wrap calls in
  `safe(...)` or try/except so a tool returns `{"error": ...}` instead of crashing.
- `slim()` trims Garmin's large JSON responses before they are returned.
- After changing `server.py`, the user must fully quit and reopen Claude desktop.
- Never ask for or handle the Garmin password in the chat; the user types it into the
  `weblogin.py` browser page (or `login.py` in the manual setup).
- Nothing may write to stdout in the server process (MCP uses stdio): the login page
  silences its logs and the in-process dashboard runs uvicorn with `access_log=False`.
- Build the extension: `npx @anthropic-ai/mcpb pack . dist/garmin-mcp.mcpb`. New files
  that the server needs must not be excluded in `.mcpbignore`.
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
- The Strava API now needs a paid Strava subscription (since 2026), which the user doesn't have.
  Don't build on the Strava API; Strava only gets data via Garmin Connect's own connection.
- Garmin's `get_activity_splits` for a pool swim: every swim block is a lap with `lengthDTOs`
  (strokes, SWOLF, stroke type per length); every rest is a 0 m lap with one 0 m length.
  Drill laps have `swimStroke` DRILL and 0 strokes.

## History

### 2026-11-19: README for job hunting, race estimate note (uncommitted)
- The user wants to show the project for job hunting (software developer roles) and
  tested the extension on a Mac on 2026-11-18: it works. Manifest version is 1.1.0.
- Rename to "Stride Coach" was tried and reverted (the user didn't like it); the repo is
  still `Garmin_MCP` and a new name may come. If the repo gets renamed: change `REPO` in
  server.py, manifest URLs and README, but keep `manifest.name` (`garmin-mcp`, so Claude
  treats it as the same extension), the release file `garmin-mcp.mcpb` (installs ≤1.0.1
  look for that name) and the MCP server name `garmin`. Old installs then reach the repo
  through GitHub's redirect, so the old name must never be reused for a new repo.
- Name decision: repo stays `Garmin_MCP`; only `display_name` changed to
  "Training Coach for Garmin (unofficial)" (never "Garmin Coach": that's Garmin's product).
- License stays MIT (the user's copyright is already in LICENSE).
- dashboard.html: a note under the race prediction charts explains the Claude model, how to
  get an estimate (a hard race-like run, then Sync) and shows the max HR in use. It starts
  with "No Claude estimate yet" when no model estimate exists.
- Race model finds hard parts inside runs: `dashboard.py` `read_run_laps()` caches
  `[m, s, avg HR]` per lap (kv `run_laps`, served as `runLaps`) for runs ≤400 days old whose
  max HR ≥ 90 % of max HR (≤40 Garmin calls per sync, once per run). `hardestStretch()` in
  dashboard.html picks the lap stretch (3+ km, 12+ min) that passes the HR rule and projects
  to the fastest 10 km. Runs with laps no longer use the whole-run rule. Motivation: the
  17 Nov 5k test (25106461851: warm-up + 5 km in 16:42) was missed before. Checked on real
  data: it now counts 72 % of the 5 km estimate (16:39). Tooltip explains the weights in words.
- Race model, same day: HR bar is now `hrNeeded(min)` = 0.95 − 0.030x − 0.0087x², x = ln(min/15)
  (95 % at 15 min … 84 % at 2.5 h, 80 % at 4 h; the user's marathon at 87.0 % had only just
  passed the old bar). Runs marked "race" in Garmin (`eventType.typeKey`, stored as `race: true`,
  `ACTIVITY_LIST_VERSION = 2` forces one full list re-read) always count. None are marked yet.
- Trend (the user's idea: easy runs move the hard efforts): `steadyRuns()` estimates fitness per
  steady run (65–88 % HRmax, 20+ min, outdoor run types) as Daniels VO2 cost of pace ÷ share of
  heart rate reserve (resting HR = 4-week median). `fitnessOn(day)` = 4-week median (≥4 runs).
  Each effort's projection × (fitness then / now)^0.85, capped ±3 %. Plain HR weighting was
  rejected: HR-based estimates of the user's easy runs read 40 s–1:30 slow on 5 km and scatter
  16:25–21:00 (that's Garmin's failure mode). Backtest on 3 races (prediction from data before
  each): mean abs error 2.6 % → 1.2 %. Harness for this: load `/api/data`, eval the model block
  in node with stub helpers (rebuilt in the scratchpad each time, not kept in the repo).
- Dashboard polish: tooltip rows with long text keep the value on one line (`long: true` rows,
  `.r.long` CSS); cycling VO2max tile got its 180-day sparkline (was missing); Fitness tab
  charts have plain-language descriptions and its note no longer mentions intervals.icu.
- Released as v1.1.0 (tag pushed; the release workflow builds the .mcpb).
- README restructured (the user's order): intro → "Why I built this" → Tools → Install → How to use it (example
  questions by topic, workout notes, joining activities, tips) → Dashboard → Updating →
  If something breaks → For developers (manual setup, building, releases) → License.
  Nothing removed, only moved and grouped.
- README: "Planning workouts" now explains goal-based suggestions; Dashboard section
  explains the race prediction model (Garmin often predicted a sub-12-min 5 km for the user).
  Note: `KEY_EFFORTS` / `SKIP_EFFORTS` in dashboard.html are the user's own activity ids;
  for other users only the automatic heart-rate rule applies.

### 2026-11-17: Mac support and one-click Desktop Extension (uncommitted)
Goal: non-technical users on Mac or Windows install it by opening one file; the free
Claude desktop plan is enough (ChatGPT Free can't add custom MCP servers, and
ChatGPT can't start local servers at all, so it was ruled out).
- `.mcpb` bundle with `server.type = "uv"`: Claude desktop downloads Python (pinned
  3.13 via `.python-version`) and the packages from `uv.lock` itself. Bundle is 118 kB,
  10 files. `user_config.fit_dir` (default `${DOCUMENTS}/Garmin FIT`) → `GARMIN_FIT_DIR`.
- New tool `garmin_login`: opens `weblogin.py`'s page on 127.0.0.1 (random port,
  secret path, Host check, closes after sign-in or 15 min), supports Garmin MFA via
  `return_on_mfa` + `resume_login`, dumps tokens and checks them. Waits ≤50 s, then
  tells Claude to ask the user and call again. `api()` errors now point Claude to it.
- New tool `open_dashboard`: runs the dashboard in a thread inside the MCP process
  (`sys.modules["server"]` aliased so it shares the login), or just opens the browser if
  port 8765 is already in use.
- Onboarding (an extension can't open a chat by itself, so the first step leads into it):
  MCP prompt `get_started` ("Get started with Garmin", in Claude's + menu), tool
  `getting_started` (capabilities + example questions, `WELCOME` in server.py; the server
  instructions tell Claude to use it for new users), `garmin_login` returns `WELCOME`
  after a fresh sign-in, and the browser "Signed in" page lists example questions with
  Copy buttons.
- Updates: tool `update_extension` reads the latest GitHub release of `REPO`, compares it
  with `manifest.json`'s version, downloads `garmin-mcp.mcpb` to ~/Downloads and opens it
  shows it in Explorer/Finder; the user drags it into Settings → Extensions (double-click /
  `os.startfile` doesn't work: Claude isn't registered for `.mcpb` on the user's Windows PC,
  found 2026-11-17). A background check at startup lets `garmin_login` /
  `getting_started` mention new versions. Releases: bump `manifest.json` version, push tag
  `vX.Y.Z`; `.github/workflows/release.yml` builds and publishes (refuses on version
  mismatch). Needs a public repo (unauthenticated download). `pyproject.toml`'s version
  doesn't matter (changing it would need `uv lock`).
- Released v1.0.0 (repo made public by the user) and v1.0.1 (update tool shows the
  file in Explorer/Finder instead of opening it).
- README: new "Install" section for everyone, manual setup for Windows and Mac,
  build steps. Old "Easy setup with Claude" prompt removed. `start_dashboard.command` added.
- Tested on Windows: bundle unpacked and run with `uv run` and empty uv caches
  (Python downloaded automatically, real Garmin data read); login page flow incl.
  wrong password, MFA, Host/secret checks with a fake Garmin; `open_dashboard` serves
  the page; no stdout output. **Not tested:** installing the `.mcpb` in Claude desktop
  itself, a real browser sign-in, and anything on a Mac.

### 2026-11-16: Strava sync dropped, swim intervals in the dashboard (uncommitted)
- The Strava API needs a paid subscription, so the Strava sync (built earlier today) can't
  work for this user. Chosen instead: show swims as intervals in the dashboard.
- Removed `strava.py`, `strava_login.py`, `sync_strava.py`, `export_secrets.py`, `swimfit.py`,
  `.github/workflows/strava-sync.yml`, the MCP tools `strava_upload` / `strava_sync` and the
  README sync section. All of it is still in git history (eda6e0d, e88e963) if a subscription
  ever makes it useful again. No Strava app, logins or GitHub secrets had been created.
- `dashboard.py`: laps now carry `startTimeGMT`, swim stroke, SWOLF, strokes and a `lengths`
  list. Details have a version (`DETAIL_VERSION = 2`); older cached details are re-read from
  Garmin when opened (falls back to the old cache if Garmin fails).
- `dashboard.html`: pool swims (`lap_swimming`) show an **Intervals** chart (bar per block,
  width = duration on a time axis, height = pace /100m, drills in muted gray, rests are gaps),
  a **Per length** chart (Strokes / SWOLF / Time toggle, grouped by interval) and an
  interval table (stroke, time, pace, rest after, SWOLF, strokes/length, HR) instead of the laps table.
- Checked with the 9 Nov swim (25016505235): 19 intervals, 2,400 m, light + dark screenshots fine.
- The 16 Nov swim (25097131586) was re-uploaded without lengths, so it has no per-length data.
  The original .fit was uploaded again as **25097837471** ("Pool Swim – 2.5k", 100 lengths).
  Garmin first refused it with 409 "Duplicate Activity" (same `file_id` as 25097131586), so
  the upload is a copy with a new `file_id.time_created` (`25095714915_REUPLOAD.fit` in FIT_DIR).
  25097131586 is still in Garmin until the user says yes to deleting it.

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
