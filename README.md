# garmin-mcp (personal, local)

**Found a problem, or have an idea for the dashboard or the workout planner?**
Email me at [lukas@egkher.at](mailto:lukas@egkher.at).

A small MCP server that lets the Claude desktop app read your Garmin Connect
data and put planned workouts on your Garmin calendar. It works on **Mac and
Windows** with the free Claude plan. The server runs on your computer and talks
only to Garmin. Anything Claude reads through it, including health data, also goes
to Anthropic. You type your password into a Garmin sign-in page in your own
browser, never into the chat, and it is never stored.

> Unofficial personal project, not affiliated with or endorsed by Garmin. It uses
> unofficial access that may break or may conflict with Garmin's terms, so use it
> at your own risk.

## Tools
| Tool | What it does |
|---|---|
| `garmin_login` | Opens a sign-in page in your browser (password never goes through the chat) |
| `getting_started` | What you can do with this connection, with example questions |
| `update_extension` | Checks for a newer version and downloads it |
| `open_dashboard` | Opens the training dashboard in your browser |
| `daily_overview` | Sleep, HRV, training readiness, Body Battery, resting HR, stress, steps |
| `list_activities` | Activities in a date range with the key numbers |
| `activity_details` | One activity: summary, laps, time in HR zones |
| `training_status` | Training status/load, VO2max, race predictions |
| `scheduled_workouts` | What's on the Garmin calendar for a month |
| `create_run_workout` | Structured run: pace (min/km), HR zone, cadence |
| `create_bike_workout` | Structured ride: % of FTP, power zone, speed (km/h), HR zone, cadence |
| `create_swim_workout` | Pool swim: distances, rests, stroke, pace per 100 m, pool length |
| `cycling_ftp` | Your current FTP from Garmin |
| `delete_workout` | Remove a workout |
| `download_fit` | Save an activity's original `.fit` file to a folder on your computer |
| `merge_fit` | Join several `.fit` files into one activity (gaps become pauses, laps kept) |
| `upload_fit` | Upload a `.fit` file to Garmin Connect as a new activity |
| `delete_activity` | Delete an activity in Garmin (saves a `.fit` backup first) |
| `combine_activities` | Download, merge and upload in one step |

### Joining activities that were split by accident
Ask Claude something like *"combine my two runs from Sunday into one"*. It finds
the activities, runs `combine_activities`, and uploads the combined one. Your
Garmin Connect's Strava connection then sends it to Strava like any watch upload.

- The originals are **not** deleted automatically. Claude asks you first and then
  uses `delete_activity`, which saves a backup `.fit` before deleting.
- **Strava:** Strava's API can't delete activities, so delete the single
  activities on Strava yourself. If Strava refuses the combined activity as a
  duplicate, delete the singles there first and upload the merged `.fit` from the
  folder by hand.
- Files go to `Documents/Garmin FIT` (change it in the extension's settings, or
  with the `GARMIN_FIT_DIR` environment variable). They only leave your computer
  when uploaded to Garmin.
- The merge works only for activities of the same sport that don't overlap in time.
  All GPS, heart rate, power and sensor data is kept. Session totals (distance,
  time, calories, average HR, cadence and power) are recalculated. The watch's own
  summaries of each activity (training effect, splits, time in zones) are dropped
  because they'd be wrong for the combined activity. Garmin Connect recomputes some
  of these from the data; any it doesn't are missing.

All `create_*` tools take an optional `date`. With a date, the workout goes on
your Garmin Connect calendar and syncs to the watch. On the watch it shows up
under Training → Workouts / Training Calendar, ready to start.

Bike `% FTP` targets are stored as % FTP (not fixed watts), so the watch
recalculates the watts if your FTP changes. Set or check your FTP in Garmin
Connect (User Settings → Power Zones) so the watts are right.

## Install (Mac and Windows, no technical knowledge needed)

You need the **Claude desktop app** ([claude.ai/download](https://claude.ai/download)).
The free plan is enough; you don't need Claude Code or a paid plan.

1. **Download [garmin-mcp.mcpb](https://github.com/LukasEgkher22/Garmin_MCP/releases/latest/download/garmin-mcp.mcpb)**
   (always the newest version), or use the file someone sent you.
2. **Install it:** open Claude → **Settings → Extensions**, drag the file into that
   window and click **Install**. (Double-clicking the file usually doesn't work,
   because Windows doesn't know to open it with Claude.)
3. **Get started:** open a new chat and type *"Get started with Garmin"*. Claude
   opens a Garmin sign-in page in your web browser. Type your email and password
   there (and the code Garmin sends you, if it asks). *Never type your password
   into the chat itself.* The page then shows a few example questions, and back in
   Claude you get a short overview of what you can do.
4. **Use it:** ask things like *"How did I sleep this week?"*, *"Plan 5×1 km
   intervals for Thursday"* or *"Open my training dashboard"*. You can ask
   *"What can I do with Garmin?"* at any time.

The first time Claude starts the extension, it downloads Python and a few
libraries by itself (about a minute, once). You don't need to install anything else.
Claude asks for your OK the first time it uses each tool. Allow it.

## Manual setup (developers)

Use this if you want to change the code. It needs Python 3.12+.

1. **Get the code** and put the folder somewhere fixed, e.g. `~/code/garmin-mcp`.
2. **Create a virtual environment and install:**

   Windows (PowerShell):
   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   If PowerShell blocks the activate script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

   Mac (Terminal):
   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Sign in once:** `python login.py` (or later, ask Claude to sign you in).
   Tokens go to `.garminconnect` in your home folder. Treat that folder like a password.
4. **Register it in the Claude desktop app:** Settings → Developer → Edit Config.
   That opens `claude_desktop_config.json`. Add this, with YOUR path:

   Windows (double backslashes):
   ```json
   {
     "mcpServers": {
       "garmin": {
         "command": "C:\\Users\\<you>\\code\\garmin-mcp\\.venv\\Scripts\\python.exe",
         "args": ["C:\\Users\\<you>\\code\\garmin-mcp\\server.py"]
       }
     }
   }
   ```
   Mac:
   ```json
   {
     "mcpServers": {
       "garmin": {
         "command": "/Users/<you>/code/garmin-mcp/.venv/bin/python3",
         "args": ["/Users/<you>/code/garmin-mcp/server.py"]
       }
     }
   }
   ```
5. **Fully quit Claude** (Windows: right-click the tray icon → Quit; Mac: Cmd+Q)
   and reopen it. "garmin" should appear under the connectors menu in a new chat.

Don't use the extension and the manual setup at the same time, or Claude has
every tool twice.

### Building the extension
The `.mcpb` file is a zip of the server code plus `manifest.json`. Claude
desktop runs it with `uv`, which installs Python and the packages from
`pyproject.toml` / `uv.lock`. `.mcpbignore` decides what goes in. You need Node.js:
```sh
npx @anthropic-ai/mcpb pack . dist/garmin-mcp.mcpb
```
After changing dependencies, update `pyproject.toml` and `requirements.txt`, then
run `uv lock`.

### Making a release
1. Raise `version` in `manifest.json` (e.g. `1.0.0` → `1.1.0`) and commit it.
2. Tag and push:
   ```sh
   git tag v1.1.0
   git push origin main v1.1.0
   ```
GitHub Actions ([release.yml](.github/workflows/release.yml)) then builds
`garmin-mcp.mcpb` and publishes the release (about a minute). It refuses to run if
the tag and `manifest.json` disagree. Users get the new version by asking Claude to
*"update Garmin"*; Claude also mentions it when they sign in or ask for help.
The repo must be public for this, because users download without a GitHub login.

## Dashboard
A local training dashboard in your browser, in the spirit of intervals.icu and
Strava's premium charts. Ask Claude *"open my training dashboard"*; it runs while
the Claude app is open. With the manual setup you can also start it without
Claude: double-click `start_dashboard.bat` (Windows) or `start_dashboard.command`
(Mac), or run `python dashboard.py`.

It opens `http://127.0.0.1:8765`. The first sync reads your whole history and
takes about a minute; after that the page syncs itself when the data is over an
hour old, or when you press **Sync**.

| Tab | What's on it |
|---|---|
| Fitness | Form, fitness and fatigue, weekly load by sport, today's recovery numbers |
| Training | Hours and distance by sport, time in HR and power zones, year-over-year totals |
| Recovery | HRV against your normal range, resting HR, sleep stages and score, Body Battery, stress |
| Performance | Power curve, FTP, VO2max, race predictions, efficiency trends, personal records |
| Calendar | 12-month load heatmap, month view with completed and planned workouts |
| Activities | Searchable, sortable list; click one for its charts, route shape and laps |

Pool swims open with an **Intervals** chart (one bar per block you swam between
two rests, as wide as it lasted, taller = faster pace), a **Per length** chart
(strokes, SWOLF or time for every length) and an interval table with the rest
after each block. It all comes from Garmin's own lap data; nothing is uploaded.

The date range and sport filters at the top apply to everything below them.

- **Fitness numbers won't match other apps.** Fitness and fatigue are 42- and 7-day
  exponential averages of Garmin's training load, which is not TSS.
- **Privacy:** it listens on this computer only, makes no requests except to
  Garmin, and never changes anything on your Garmin account. The cached data is in
  `.garminconnect/dashboard_cache.sqlite` in your home folder, next to your tokens.
  Delete that file to start over; the next sync rebuilds it.
- The Garmin tools in Claude work without the dashboard.

## Updating
- **Extension:** tell Claude *"update Garmin"*. It checks for a new version, downloads
  it to your Downloads folder and shows it there. Drag it into **Settings →
  Extensions**, click **Install** and start a new chat. You stay signed in.
- **Manual setup:** replace the files, then fully quit and reopen Claude.

## If something breaks
- *"Not signed in to Garmin"*, or sign-in errors after weeks or months: tell
  Claude *"sign me in to Garmin"* again.
- The sign-in page didn't open: Claude gives you a link to it. Open it in your browser.
- *"Garmin is temporarily blocking sign-ins"*: wait 15 minutes and try again.
- Extension not working: Settings → Extensions shows whether it's enabled;
  Settings → Developer shows the server's log.
- Garmin changed something: this uses Garmin's unofficial access, so occasional
  breakage is normal. Install the newest release (manual setup:
  `pip install -U garminconnect`).
- Sign out: delete the `.garminconnect` folder in your home folder.

## License
MIT, see [LICENSE](LICENSE).
