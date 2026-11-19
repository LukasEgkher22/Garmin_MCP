# garmin-mcp

**An AI training coach for your Garmin data, running in the Claude desktop app.**

A small MCP server that lets the Claude desktop app read your Garmin Connect
data and put planned workouts on your Garmin calendar. It works on **Mac and
Windows** with the free Claude plan. The server runs on your computer and talks
only to Garmin. Anything Claude reads through it, including health data, also goes
to Anthropic. You type your password into a Garmin sign-in page in your own
browser, never into the chat, and it is never stored.

## Why I built this
I didn't want to pay for a coaching app just to get workouts planned for me. My
Garmin watch already records everything a coach would need: sleep, HRV, every
lap of every run, ride and swim. So I connected it to Claude and built my own
coach that looks at my data and puts planned workouts straight on my watch.

Once the base worked, I fixed a few things that had bothered me for a long time:
activities that got split in two by accident, and pool swims that showed as one
long line instead of the intervals I actually swam.

When I told friends about it, they wanted it too. Most of them don't code, use
Git or like installing things, so I made it as easy as possible: one file,
dragged into Claude, and you're signed in through your browser.

**Found a problem, or have an idea for the dashboard or the workout planner?**
Email me at [lukas@egkher.at](mailto:lukas@egkher.at).

> Unofficial personal project, not affiliated with or endorsed by Garmin. It uses
> unofficial access that may break or may conflict with Garmin's terms, so use it
> at your own risk.

**Contents:** [Tools](#tools) · [Install](#install-mac-and-windows-no-technical-knowledge-needed) · [How to use it](#how-to-use-it) ·
[Dashboard](#dashboard) · [Updating](#updating) · [If something breaks](#if-something-breaks) ·
[For developers](#for-developers)

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

You don't call the tools yourself. Ask Claude in normal words and it picks the
right ones. Claude asks for your OK the first time it uses each tool.

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
4. **Use it:** see [How to use it](#how-to-use-it) below.

The first time Claude starts the extension, it downloads Python and a few
libraries by itself (about a minute, once). You don't need to install anything else.
Claude asks for your OK the first time it uses each tool. Allow it.

## How to use it
Open a new chat in Claude. The first time, type *"Get started with Garmin"*: Claude
signs you in and shows you what you can do. After that, just ask.

### Recovery and health
- *"How did I sleep this week?"*
- *"Am I recovered enough for a hard session today?"*
- *"How is my HRV compared to my normal range?"*

### Looking back at training
- *"Summarize my training of the last 4 weeks."*
- *"How did my long run on Sunday go? Show me the laps."*
- *"What's my VO2max, and what does Garmin predict for a 10k?"*

### Planning workouts
Tell Claude your goal, and it suggests workouts based on recent training science,
your goal and your current form (recent training, recovery, VO2max). Then it puts
the ones you pick on your watch.
- *"My goal is a half marathon under 1:45 in March. What should I do this week?"*
- *"I want to get faster over 5k. Suggest two key sessions for next week, based on
  current research and how I've been training."*
- *"Plan 6×800 m intervals for Thursday and put them on my watch."*
- *"Create a 90-minute endurance ride at 65 % FTP for Saturday."*
- *"Make a 2 km pool swim with 4×200 m at 2:00/100 m."*
- *"What's on my training calendar this month?"*

With a date, the workout goes on your Garmin Connect calendar and syncs to the
watch. On the watch it shows up under Training → Workouts / Training Calendar,
ready to start. Without a date, it's only saved in your Garmin workouts.

Bike `% FTP` targets are stored as % FTP (not fixed watts), so the watch
recalculates the watts if your FTP changes. Set or check your FTP in Garmin
Connect (User Settings → Power Zones) so the watts are right.

### The dashboard
- *"Open my training dashboard."* See [Dashboard](#dashboard) for what's on it.

### Realistic race time estimates
Garmin's race predictions can be far too optimistic. The dashboard adds its own
estimate for 5 km, 10 km, half marathon and marathon, based on runs you really did.
1. Ask Claude *"open my training dashboard"* and go to the **Performance** tab.
2. Each *Predicted …* tile shows the estimate ("Claude model") above Garmin's.
   The charts below show both over time; hover to see which runs were used.
3. No estimate yet? Run one hard effort (a race, a parkrun or a time trial of
   3 km or more), then press **Sync**. See [how it works](#race-time-predictions).

### Joining activities that were split by accident
Ask something like *"combine my two runs from Sunday into one"*. Claude finds
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

### Tips
- Say which dates you mean (*"since Monday"*, *"in October"*). Claude works with
  exact dates.
- You can ask *"What can I do with Garmin?"* at any time.

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

### Race time predictions
For 5 km, 10 km, half marathon and marathon. Garmin's own predictions can be far
off: for me it often predicted a 5 km under 12 minutes, faster than the world
record. So the Performance tab shows my own estimate ("Claude model") next to Garmin's.

**How it works:**
1. **It finds your race-like runs** from the last 12 months: 3 km or more and 12 minutes
   or more, with an average heart rate close to your max. The bar is strict for short
   efforts, so tempo runs stay out, and gentler for long ones:

   | Effort length | Average heart rate needed |
   |---|---|
   | 15 min | 95 % of max HR |
   | 30 min | 92.5 % |
   | 75 min | 88 % |
   | 2.5 h | 84 % |
   | 4 h | 80 % |

   Runs you mark as a **race** in Garmin Connect always count, whatever the heart rate.
2. **It also looks inside longer runs.** A 5 km test after a warm-up, or a parkrun in
   the middle of a long run, is found from the laps, so you don't have to save it
   as its own activity. New hard runs are picked up automatically at the next sync.
3. **Each run is scaled to the race distance** with Riegel's rule: twice the distance
   takes about 2.1 times as long. (Formula: T = t × (D/d)^1.06.)
4. **The results are averaged**, and some runs count more than others:
   - Recent runs count more: a run counts half as much after about 2 months.
   - Runs close to the race distance count more: a 10 km run counts half as much for
     a 5 km estimate as a 5 km run would.
5. **Your easy runs set the trend.** Hard runs give the level, but they're rare. Your
   normal runs show whether you got fitter since then: for each one, your pace is
   compared with your heart rate. A single easy run says little (heat, tiredness and
   heart rate drift all make it look slower), so it takes the middle value of 4 weeks of
   runs and compares two dates: around the hard run, and now. If you've got 2 % fitter
   since a race, that race's result is moved about 2 % faster, at most ±3 %.

Hover over a prediction chart to see which runs were used, how much each one counts,
what each one predicts on its own, and how much the trend moved it.

Tested on my own races: predicted from only the data before each race, the error
dropped from 2.6 % to 1.2 % on average with the trend (Vienna half, Copenhagen
marathon, a 5 km test). Three races is a small test, so take it as a good sign, not proof.

**No estimate, or a strange one?** You need at least one race-like run in the last
12 months: a race, parkrun or time trial run hard. Easy runs only set the trend, they
never give an estimate on their own. The max heart
rate comes from your heart rate zones in Garmin Connect; if it's set too high, hard
runs don't count, so check it there. The note under the charts shows the value used.

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

## For developers

### Manual setup
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

## License
MIT, see [LICENSE](LICENSE).
