#!/bin/bash
# Mac -> hub: copy every committed file, then restart only what changed.   usage: ./deploy.sh [-n]  (-n = dry run)
# Replaces hand-copying with scp, which let the two machines drift apart (2026-11-17 cleanup, fix 1).
set -euo pipefail
cd "$(dirname "$0")"
HUB=nova-hub
if ! git diff --quiet HEAD; then echo "Uncommitted changes - commit first so the hub runs a known version:"; git status --short; exit 1; fi
DRY=""; [ "${1:-}" = "-n" ] && DRY="-n"

# rsync prints one line per file it actually changed (">f..." = file content/size/time differs)
CHANGED=$(git ls-files | rsync -aic -e "ssh -o LogLevel=ERROR" $DRY --files-from=- . "$HUB:anish-ai/" | awk '/^[<>]f/ {print $2}')
echo "${CHANGED:-(nothing changed)}"
[ -n "$DRY" ] && exit 0
VER="$(git log -1 --format='%h %s' | tr -d "'\\" | cut -c1-60) ($(date '+%d %b %H:%M'))"
ssh "$HUB" "echo '$VER' > ~/anish-ai/.version"
[ -z "$CHANGED" ] && exit 0

hub() { ssh "$HUB" "$1" 2>&1 | grep -v -i "quantum\|store now\|upgraded" || true; }
if echo "$CHANGED" | grep -q '^supervisor\.py$'; then
  hub 'launchctl kickstart -k gui/$(id -u)/com.nova.supervisor'; echo "restarted supervisor"
fi
# Nova restarts for code/UI; routines.json + automations.json are re-read live, iot/ + docs need nothing
if echo "$CHANGED" | grep -vE '^(supervisor\.py|iot/|test_)' | grep -qE '\.(py|html|js|css)$'; then
  # light_panel holds the Bluetooth strips; Nova (re)starts it, so it gets the new code too
  echo "$CHANGED" | grep -q '^light_panel\.py$' && hub 'pkill -f "light_panel[.]py"'
  hub 'cd ~/anish-ai/app; N=$(wc -l < nova.log); pkill -f "app/nova_app[.]py"; pkill -f "cam_presence[.]py";
       for i in $(seq 1 60); do sed -n "$((N+1)),\$p" nova.log | grep -q "listening (floor" && echo "hub Nova back up" && exit; sleep 3; done;
       echo "WARNING: hub Nova not listening after 3 min - check app/nova.log"'
fi
echo "hub now on: $VER"
