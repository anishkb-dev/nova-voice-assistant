#!/bin/bash
# Hub Wi-Fi watchdog (launchd com.nova.wifi-watchdog, every 60 s).
# 2026-11-16: the hub dropped off Wi-Fi at 13:05 for hours while still running, and its system log
# kept nothing. Now: router unreachable for 2 checks in a row -> power-cycle Wi-Fi, and log it.
# ponytail: if the router itself is down this cycles Wi-Fi every 2 min (harmless, just log noise);
# FAILS_BEFORE_RESET is the knob.
LOG=~/anish-ai/wifi_watchdog.log
CNT=/tmp/nova-wifi-fails
FAILS_BEFORE_RESET=2
GW=$(route -n get default 2>/dev/null | awk '/gateway/{print $2}')
GW=${GW:-192.168.68.1}            # no default route at all = Wi-Fi is down -> still test the usual router
if ping -c 2 -t 3 -q "$GW" >/dev/null 2>&1; then
  [ -s "$CNT" ] && echo "$(date '+%F %T') ok again (router $GW back after $(cat $CNT) failed checks)" >> "$LOG"
  rm -f "$CNT"; exit 0
fi
n=$(( $(cat "$CNT" 2>/dev/null || echo 0) + 1 )); echo $n > "$CNT"
echo "$(date '+%F %T') router $GW unreachable ($n) ssid=$(networksetup -getairportnetwork en0 | sed 's/.*: //')" >> "$LOG"
if [ "$n" -ge "$FAILS_BEFORE_RESET" ]; then
  echo "$(date '+%F %T') cycling Wi-Fi" >> "$LOG"
  networksetup -setairportpower en0 off; sleep 3; networksetup -setairportpower en0 on
  echo 0 > "$CNT"
fi
# keep the log small
[ "$(wc -l < "$LOG")" -gt 2000 ] && tail -1000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
exit 0
