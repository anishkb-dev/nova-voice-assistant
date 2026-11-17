# Nova cleanup — change log (started 2026-11-17)

Each fix: what changed, why, consequences checked, how to undo.

## Fix 1 — one-command deploy (`./deploy.sh`)
- **What:** `deploy.sh` copies every committed file Mac → hub (rsync), writes `.version` on the hub, and restarts only what changed:
  supervisor.py → supervisor; other code/UI → hub Nova (+ light panel if `light_panel.py` changed); routines/automations JSON, `iot/`, docs → nothing (read live / not run on the hub).
  Refuses to run with uncommitted changes. `./deploy.sh -n` = dry run (lists what would change).
- Telegram **📊 Status** now ends with the version line (`🏷 <commit> (<time>)`).
- `.dev_last.json` and `.wiz_ip` are runtime state written by Nova — removed from git (still on disk) so a deploy never overwrites the hub's live copy.
- **Drift found before switching:** 15 files on the hub were older than the Mac's (doctor/filecheck/findmy, wall UI clock, projector IR codes, firmware copies). No hub-only edits existed, so nothing was lost.
- **Consequences checked:** nothing on the hub writes routines.json/automations.json/projector_ir.json, so deploys can't clobber Nova's own edits. Secrets are git-ignored → never copied. findmy.py's new cookie folder only matters where iCloud is signed in (the Mac, not the hub). A Nova restart re-arms pending `.later.json` steps (existing behaviour).
- **Undo:** keep using scp; delete `deploy.sh`.

## Fix 3 — automations test works again, runs before every deploy
- **What:** `test_automations.py` crashed (`'F' object has no attribute '_AWAY_F'`) since away mode was added — so nothing was checking the rules. Fixed the stand-in, gave it its own temp flag files, added an **away-mode check** (no AC-on / no walk-in lights while you're out).
- `deploy.sh` now runs `test_automations.py` + `app/netmic.py` first and refuses to deploy if either fails.
- **Consequences checked:** the test uses temp copies of `.away` / `.auto_state.json`, so running it can never flip the real hub flags or rule memory. Adds ~1 s to a deploy.
- **Undo:** remove the `for t in ...` block in deploy.sh.

## Fix 4 — broker persistence: SKIPPED (decided against)
- The broker has run once and never exited since the hub booted; it only restarts on a hub reboot — which usually means a power cut.
- After a power cut the AC/devices lose power, so a *persisted* state ("AC on 21") would be **wrong**, and wrong blocks rules ("AC on when hot" needs ac=off). Unknown is safer than wrong. Revisit only if the broker starts restarting on its own.

## Fix 2 — typing at the Mac counts as "you're in the room"
- **What:** the Mac's Nova checks keyboard/mouse idle time every 60 s; if you used it in the last 90 s it tells the hub (`home/hub/present`). The hub's empty-room rules treat that like motion, so lights/AC don't switch off while you sit still at the desk.
- **Guard:** the Mac is a MacBook Air (it can leave the room). Typing only counts within **90 min** of the camera/motion sensor last seeing you (`MAC_PRESENCE_MAX` in nova_app.py, a calibration knob).
- **Consequences checked:** only real key/mouse input counts — a video playing on the Mac does NOT keep the room "occupied". Carrying the laptop to another room keeps the room "occupied" for up to 90 min (lights/AC stay on longer than they should). The walk-in welcome won't fire while you're typing (correct: you never left). Needs the **Mac's Nova restarted** to start pinging; until then nothing changes.
- Tests: typing blocks lights-off; typing 200 min after the room last saw you does not.
- **Undo:** set `MAC_PRESENCE_MAX = 0`.

## Fix 6 — automation conflicts
- **"AC off when cool": 21° → 20°** (re-arms above 22°, was 23°). It used to switch the AC off whenever you set it to 21° yourself and the room got there.
- **"AC off when the room is empty": only 07:00–23:30.** At night it could switch the AC off while you slept without saying goodnight (sleeping = no motion).
- **Goodnight: projector off after 60 min** (new delayed step).
- **Consequences checked:**
  - Room can now get down to 20° before the AC turns itself off (more cooling, more power).
  - If you leave the room at night without saying "I'm leaving", the AC stays on until 07:30.
  - Projector off is an IR *toggle* tracked by Nova: if you switch it off with the physical remote after goodnight, the 60-min step would switch it back **on**. The morning routine's "projector off" now just finds it already off.
  - JSON is read live — no restart needed; tests still pass.
- **Undo:** edit the numbers back in automations.json / delete the step in routines.json.

## Fix 8 — "stop the music" works after a restart on the hub too
- **What:** the backup stop only killed `mpv`; the hub plays music with `afplay`, so a song left playing by a Nova restart couldn't be stopped. Now it matches the track file (`/tmp/nova_track.*`) for both "is music playing" and "stop".
- **Consequences checked:** Nova's own voice also uses `afplay` but never plays `nova_track`, so speech isn't cut (a blanket `pkill afplay` would have). Saying stop while a song is still downloading now also cancels the download (it matches the same file name) — intended.
- **Undo:** revert the two lines in nova.py `music_playing` / `stop_music`.

## Fix 7 — dead files deleted
- **Deleted** (nothing referenced them; checked with `git grep`): old UIs `app/nova_hud.html`, `nova_stitch.html`, `index.html`, `index_reactor.html`, `index_scifi_backup.html`, `index_stitch_backup.html`, `index_stark.html`, `index_processor.html`, Stitch design sources `app/stitch_v3/`, `app/stitch_wall/`, `stitch_wall_prompt.md`, `design.md`, and the old `jarvis_run.log` (100 KB, Jarvis era, untracked).
- Same files removed from the hub (deploy.sh only adds/updates, never deletes).
- **Kept on purpose:** `nova_v3.html` (Mac UI), `nova_wall.html` (hub wall), `car_control.html` + `nova_vision.html` (RC car chat owns them), `Modelfile` / `Nova.Modelfile` (recipes for the local "nova" Ollama model — needed to rebuild it).
- **Consequences checked:** the light panel's "/index.html" is its own built-in page, not app/index.html. Nova loads only nova_v3.html / nova_wall.html.
- **Undo:** `git checkout <commit before this> -- <file>` — everything is in git history.

## Fix 5 — the Mac's Nova runs as its own app (no Terminal needed)
- **What:** `~/Applications/NovaMac.app` (ad-hoc signed; copy in `iot/NovaMac.app`) runs `nova_app.py` with Homebrew Python 3.14 and logs to `app/nova.log`. LaunchAgent `com.nova.mac` (`iot/com.nova.mac.plist` → `~/Library/LaunchAgents/`) starts it at login and brings it back ~20 s after it exits.
- macOS ties the mic/camera permission to **"Nova"** (asked once) instead of Terminal — so it can be restarted without you, including by me after a change.
- Terminal aliases in `~/.zshrc`: `nova-restart`, `nova-stop`, `nova-start`, `nova-log`.
- **Consequences checked:**
  - It restarts after *any* exit — closing Nova's window brings it back in 20 s. To really stop it: `nova-stop`.
  - Nova's own "switch mics" self-restart (exit 3) used to leave it dead in Terminal; now it comes back by itself.
  - Only one Nova can run (`.nova.lock`): the Terminal copy must be quit first, or the app copy exits and retries every 20 s.
  - Output goes to `app/nova.log` instead of the Terminal window (`nova-log` to watch).
  - If the permission prompt is missed/denied, macOS gives silent audio (rms=1) instead of an error — check System Settings → Privacy → Microphone → Nova.
- **Undo:** `nova-stop`, delete `~/Library/LaunchAgents/com.nova.mac.plist`, start it from Terminal as before.
- **Result (16:40):** running under launchd as "Nova" (`com.nova.mac`), window up, room data live. No mic prompt appeared — by design the Mac's Nova doesn't use the mic (`ON_SENSES` is hub-only; the hub mics do the listening), so the old "must start from Terminal" rule no longer applies. Restart = `nova-restart`.

## Old Nova.app removed + icon
- `~/Applications/Nova.app` (Jarvis-era launcher, bundle id com.svpreme.jarvis, logged to app/jarvis.log) **moved to Trash** as `Nova-old-jarvis.app`, and its login item "Jarvis" removed. It started at every login and raced the new launcher (source of the repeated "another instance is already running" lines).
- New icon (amber HUD rings + star): `NovaMac.app/Contents/Resources/nova.icns`, and the Mac's Dock icon is set at runtime from `app/nova_icon.png` (the process is Python.app, so the bundle icon alone doesn't reach the Dock).
- **Undo:** drag Nova-old-jarvis.app back from the Trash.
