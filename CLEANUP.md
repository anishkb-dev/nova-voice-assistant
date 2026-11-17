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
