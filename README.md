# garmin-mcp (personal, local)

**Found a problem, or have an idea for the dashboard or the workout planner?**
Email me at [lukas@egkher.at](mailto:lukas@egkher.at).

A small MCP server that lets the Claude desktop app read your Garmin Connect
data and put planned workouts on your Garmin calendar. The server runs on your PC
and talks only to Garmin. Anything Claude reads through it, including health data,
also goes to Anthropic. Your password is used once by `login.py` and never stored.

> Unofficial personal project, not affiliated with or endorsed by Garmin. It uses
> unofficial access that may break or may conflict with Garmin's terms, so use it
> at your own risk.

## Tools
| Tool | What it does |
|---|---|
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

All `create_*` tools take an optional `date`. With a date, the workout goes on
your Garmin Connect calendar and syncs to the watch. On the watch it shows up
under Training → Workouts / Training Calendar, ready to start.

Bike `% FTP` targets are stored as % FTP (not fixed watts), so the watch
recalculates the watts if your FTP changes. Set or check your FTP in Garmin
Connect (User Settings → Power Zones) so the watts are right.

## Easy setup with Claude

Not technical? Claude can do most of the setup for you. This needs a version of
Claude that can run commands on your PC, such as the Code tab in the desktop app
or Claude Code. A normal chat can't do it. This route hasn't been fully tested
yet, so if it gets stuck, use the manual steps below.

1. On the GitHub page, click **Code → Download ZIP**, then unzip it somewhere fixed,
   e.g. `C:\Users\<you>\code\garmin-mcp`.
2. Open that folder in Claude and paste this prompt:

   ```text
   This folder contains garmin-mcp, a tool that connects my Garmin data to the
   Claude desktop app. I'm not technical, so please set it up for me on Windows
   and explain each step in one simple sentence.

   First read README.md, server.py and login.py, and tell me briefly what the tool
   does and whether anything looks unsafe. Wait for my OK before you continue.

   Then:
   1. Check that Python 3.11 or newer is installed. If it isn't, help me install it.
   2. Create the virtual environment in this folder and install requirements.txt.
   3. Garmin login: never ask for my password or MFA code, and don't run the login
      yourself. Give me the exact command to paste into my own PowerShell window,
      using the full path to this folder. Wait until I tell you it worked.
   4. Check that server.py starts without errors, then stop it again.
   5. Add the "garmin" server to my claude_desktop_config.json, using the real paths
      on this PC. If you can't find the file, ask me to open it through Settings →
      Developer → Edit Config. Make a backup first, and keep everything already in
      the file.
   6. Last, tell me to fully quit Claude (right-click the tray icon → Quit), reopen
      it, and look for "garmin" in the connectors menu of a new chat. Warn me that
      quitting will end this session.

   Ask me if anything is unclear or fails. Don't do anything that isn't on this list.
   ```

You still do three things yourself: approve the actions Claude asks about, type
your Garmin password in your own PowerShell window (never in the chat), and restart
Claude at the end.

## Setup on Windows

1. **Install Python 3.11+** from python.org (tick "Add python.exe to PATH").
2. **Put the folder somewhere fixed**, e.g. `C:\Users\<you>\code\garmin-mcp`, and open it in VS Code.
3. **Create a virtual environment and install** (VS Code terminal, PowerShell):
   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   If PowerShell blocks the activate script:
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
4. **Log in once:**
   ```powershell
   python login.py
   ```
   Tokens go to `C:\Users\<you>\.garminconnect`. Treat that folder like a password.
5. **Test the server starts** (it will just wait silently; stop with Ctrl+C):
   ```powershell
   python server.py
   ```
6. **Register it in the Claude desktop app:** Settings → Developer → Edit Config.
   That opens `claude_desktop_config.json`. Add this (use YOUR path, with double backslashes):
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
7. **Fully quit Claude** (right-click the tray icon → Quit) and reopen it.
   "garmin" should appear under the tools/connectors menu in a new chat.

## Dashboard
A local training dashboard in your browser, in the spirit of intervals.icu and
Strava's premium charts:
```powershell
.venv\Scripts\python.exe dashboard.py
```
It opens `http://127.0.0.1:8765`. The first sync reads your whole history and
takes about a minute; after that the page syncs itself when the data is over an
hour old, or when you press **Sync**. Stop it with Ctrl+C.

| Tab | What's on it |
|---|---|
| Fitness | Form, fitness and fatigue, weekly load by sport, today's recovery numbers |
| Training | Hours and distance by sport, time in HR and power zones, year-over-year totals |
| Recovery | HRV against your normal range, resting HR, sleep stages and score, Body Battery, stress |
| Performance | Power curve, FTP, VO2max, race predictions, efficiency trends, personal records |
| Calendar | 12-month load heatmap, month view with completed and planned workouts |
| Activities | Searchable, sortable list; click one for its charts, route shape and laps |

The date range and sport filters at the top apply to everything below them.

- **Fitness numbers won't match other apps.** Fitness and fatigue are 42- and 7-day
  exponential averages of Garmin's training load, which is not TSS.
- **Privacy:** it listens on this PC only, makes no requests except to Garmin, and
  never changes anything on your Garmin account. The cached data is in
  `.garminconnect\dashboard_cache.sqlite` in your user folder, next to your tokens.
  Delete that file to start over; the next sync rebuilds it.
- It doesn't need Claude running, and the MCP server doesn't need it.

## Updating
Replace `server.py` with a new version, then fully quit and reopen Claude.

## If something breaks
- *"No tokens … run login.py"*: do step 4.
- Login errors after weeks/months: run `python login.py` again.
- Server not showing in Claude: Settings → Developer shows the server's log/error.
- Garmin changed something: `pip install -U garminconnect` (this uses Garmin's
  unofficial access, so occasional breakage is normal).

## License
MIT, see [LICENSE](LICENSE).
