/* Nova bridge for nova_wall.html (Stitch "NOVA Wall Display"): display-only, read from across the room. */
(function () {
"use strict";
var $ = function (id) { return document.getElementById(id); };
function txt(id, v) { var e = $(id); if (e) e.textContent = v; }
function api(m) { try { var A = window.pywebview && window.pywebview.api; if (A && A[m]) return A[m](); } catch (e) {} return Promise.reject(); }
var RED = "#FF4B3A", AMB = "#ff9a42";

/* exact 1920x1080 frame -> scale to whatever the screen really is */
function fit() { var z = Math.min(innerWidth / 1920, innerHeight / 1080); document.body.style.zoom = z; document.body.style.overflow = "hidden"; }
fit(); addEventListener("resize", fit);

/* ---- clock ---- */
var D = ["SUN","MON","TUE","WED","THU","FRI","SAT"], M = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
function p2(n) { return (n < 10 ? "0" : "") + n; }
function clock() { var d = new Date();
  txt("clk-t", p2(d.getHours()) + ":" + p2(d.getMinutes())); txt("clk-s", ":" + p2(d.getSeconds()));
  txt("clk-d", D[d.getDay()] + " " + d.getDate() + " " + M[d.getMonth()]);
  var u = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); u.setUTCDate(u.getUTCDate() + 4 - (u.getUTCDay() || 7));
  txt("clk-w", "// WK_" + p2(Math.ceil(((u - Date.UTC(u.getUTCFullYear(), 0, 1)) / 864e5 + 1) / 7)));   // ISO week
}
clock(); setInterval(clock, 1000);

/* 270deg arc gauge, r=40 (circumference 251.2) */
function arc(id, f) { var e = $(id); if (e) e.setAttribute("stroke-dashoffset", (251.2 - 188.4 * Math.max(0, Math.min(1, f))).toFixed(1)); }

/* ---- voice state + waveform + reactor ---- */
var state = "listening", sayT = 0, VS = [].slice.call(document.querySelectorAll("[data-vs]"));
var dot = VS[0].querySelector("span"), lbl = VS[0].querySelector("span:last-child");
var ON_C = lbl.className, OFF_C = VS[1].className;
VS.forEach(function (g) { if (g !== VS[0]) { var w = document.createElement("div"); w.setAttribute("data-vs", g.getAttribute("data-vs"));
  w.className = VS[0].className; g.removeAttribute("data-vs"); g.parentNode.replaceChild(w, g); w.appendChild(g); } });
VS = [].slice.call(document.querySelectorAll("[data-vs]"));
function setState(s) { state = s;
  VS.forEach(function (g) { var on = g.getAttribute("data-vs") === s, t = g.querySelector("span:last-child");
    t.className = on ? ON_C : OFF_C; if (on) g.insertBefore(dot, t); });
}
function idleSoon(ms) { clearTimeout(sayT); sayT = setTimeout(function () { setState("listening"); }, ms); }
setState("listening");

var bars = [].slice.call($("wave").children), lvl = 0, lvlT = 0, amp = 0.3, t = 0, rSvg = $("r-svg"), rGlow = $("r-glow");
window.novaLevel = function (v) { if (typeof v !== "number") return; if (v > 1) v /= 100; lvl = Math.max(0, Math.min(1, v)); lvlT = Date.now(); };
setInterval(function () {
  var target = Date.now() - lvlT < 400 ? 0.1 + lvl * 0.9 : ({ speaking: 0.9, thinking: 0.45, listening: 0.2 }[state] || 0.2);
  amp += (target - amp) * 0.2; t += 0.12;
  bars.forEach(function (b, i) { var k = 0.5 + 0.5 * Math.sin(t * 2 + i * 0.7) * Math.cos(t + i * 0.3); b.style.height = (3 + amp * 21 * k).toFixed(1) + "px"; });
  if (!isNight) rSvg.style.opacity = (0.7 + amp * 0.3).toFixed(2);   // opacity, not filter: composited, cheap on the 2015 GPU
  rGlow.style.opacity = (0.4 + amp * 1.6).toFixed(2);
  rGlow.style.transform = "translate(-50%,-50%) scale(" + (0.95 + amp * 0.3).toFixed(3) + ")";
}, 100);
rSvg.style.willChange = rGlow.style.willChange = "opacity, transform";

/* ---- conversation (Python -> page) ---- */
var lastAt = 0;
window.novaHeard = function (s) { txt("c-user", s ? "“" + s + "”" : "—"); lastAt = Date.now(); setState("thinking"); };
window.novaSay = function (s) { txt("c-nova", s || "…"); setState("speaking"); idleSoon(3500); };
window.setCoreState = function (s) { setState(s === "standby" ? "listening" : s); };
window.novaVolume = function (v, muted) { txt("r-a", muted ? "VOLUME: MUTED" : "VOLUME: " + Math.round(v)); };
window.novaMicReset = function () { txt("mic", "MIC: RESET"); setTimeout(function () { txt("mic", "MIC: ON"); }, 4000); };
var motAt = 0;
window.novaMotion = function () { motAt = Date.now(); paintMotion(true); };
function paintMotion(fresh) {
  var on = Date.now() - motAt < 4000;
  txt("mot", !fresh ? "PIR SENSOR: NO DATA" : on ? "PIR SENSOR: MOTION DETECTED" : "PIR SENSOR: MOTION CLEAR");
  $("mot").style.color = on ? "#ffdcc4" : "";
  $("mot-dot").style.opacity = on ? "1" : "0.35";
  txt("mot-ago", motAt ? "LAST " + ago(motAt / 1000) : "");
}
function ago(ts) { var s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 60 ? s + "s AGO" : s < 3600 ? Math.floor(s / 60) + "m AGO" : Math.floor(s / 3600) + "h AGO"; }
setInterval(function () { txt("r-b", lastAt ? "LAST COMMAND " + ago(lastAt / 1000) : "NO COMMANDS YET"); }, 1000);

/* ---- stats ---- */
function tok(n) { n = n || 0; return n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : Math.round(n / 1e3) + "K"; }
function upt(s) { var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return (d ? d + "D " : "") + h + "H " + m + "M"; }
function chip(id, ok) { var e = $(id); e.textContent = ok ? "ONLINE" : "OFFLINE"; e.style.color = ok ? "" : RED; }
function bar(id, pct) { $(id).style.width = Math.max(0, Math.min(100, pct)) + "%"; }

function poll() { api("stats").then(function (s) { if (!s) return;
  var io = s.iot || {}, cl = s.claude || {}, c = s.car || {}, wf = s.wifi || {}, b = s.bat || {}, vt = s.vitals || {};
  chip("room-st", !!io.fresh); txt("room-age", io.fresh ? "LIVE" : "STALE"); $("room-age").style.color = io.fresh ? "" : RED;
  if (io.fresh && io.temp != null) { txt("t-v", (+io.temp).toFixed(1)); arc("t-arc", (io.temp - 10) / 30); }
  if (io.fresh && io.humidity != null) { txt("h-v", Math.round(io.humidity)); arc("h-arc", io.humidity / 100); }
  if (io.motion === true || io.motion === 1 || io.motion === "1") motAt = Date.now();
  paintMotion(!!io.fresh);
  txt("cpu-v", s.cpu + "%"); bar("cpu-b", s.cpu);
  txt("ram-t", "RAM (" + s.mem_gb + " / " + s.mem_tot + " GB)"); txt("ram-v", s.mem + "%"); bar("ram-b", s.mem);
  txt("load", "LOAD " + s.load);
  txt("ssid", wf.up ? wf.ssid : "OFF"); txt("sig", wf.up ? wf.signal + "%" : "--");
  var live = c.online && c.fresh;
  txt("car-link", live ? "LINKED" : "NO LINK"); $("car-link").style.color = live ? "" : RED;
  txt("car-st", live ? "ONLINE" : "OFFLINE"); $("car-st").style.color = live ? "" : RED;
  txt("car-last", c.ts ? ago(c.ts) : "NEVER"); txt("car-rssi", c.rssi != null ? c.rssi + " dBm" : "--");
  // Claude runs on the Mac: the hub has no transcript, so show -- rather than a fake 0
  txt("ctx", cl.ctx ? tok(cl.ctx) + " / 200K (" + Math.min(100, cl.ctx / 2000).toFixed(1) + "%)" : "-- (MAC)");
  txt("tok", cl.today ? tok(cl.today) : "-- (MAC)"); txt("uptime", upt(s.uptime || 0));
  txt("hubtemp", vt.temp != null ? "HUB TEMP: " + Math.round(vt.temp) + "°C" : "");
  txt("power", "POWER: " + (b.plug ? "ADAPTER" : b.plug === false ? "BATTERY " + b.pct + "%" : "--"));
  txt("disk", "DISK: " + s.disk_free + " GB FREE"); txt("procs", "PROCS: " + s.procs);
  txt("net", "NET ↓" + s.down + " ↑" + s.up + " KB/s");
}).catch(function () {}); }

/* ---- devices, weather, next routine, night ---- */
var DEVS = [].slice.call(document.querySelectorAll("[data-dev]"));
function devRow(row, on, val) {
  var sp = row.querySelectorAll("span"), val_el = row.lastElementChild;
  val_el.textContent = val; row.style.opacity = on ? "1" : "0.45";
  sp[0].textContent = on ? "◆" : "◇";
}
function pollWall() {
  api("hud").then(function (h) { if (!h) return; chip("hub-st", h.hub !== false);
    var row = DEVS.filter(function (r) { return r.getAttribute("data-dev") === "bulb"; })[0];
    devRow(row, h.bulb === "on", h.bulb ? h.bulb.toUpperCase() : "UNREACHABLE"); }).catch(function () {});
  api("wall").then(function (w) { if (!w) return;
    var dv = w.dev || {};
    DEVS.forEach(function (r) { var k = r.getAttribute("data-dev"); if (k === "bulb") return; var d = dv[k];
      if (!d) { devRow(r, false, "--"); return; }
      var cmd = d[0], off = /\boff\b/.test(cmd), rest = cmd.replace(/^(turn |switch )?on\b\s*/, "").toUpperCase();
      if (k === "ac" && /\d+/.test(cmd)) rest = cmd.match(/\d+/)[0] + "°C";
      devRow(r, !off, off ? "OFF" : rest ? "ON · " + rest : "ON");
    });
    var x = w.wx;
    if (x) { txt("wx-t", x.temp); txt("wx-c", x.cond.toUpperCase()); txt("wx-r", "RAIN " + x.rain + "%");
      txt("wx-hi", x.hi + "°C"); txt("wx-lo", x.lo + "°C"); txt("wx-w", x.wind + " KM/H " + x.dir); txt("wx-place", x.place.toUpperCase()); }
    txt("next", w.next ? w.next[0] + " " + w.next[1] : "NONE SCHEDULED");
    night(w.night);
  }).catch(function () {});
}

/* night: only the clock, faint reactor and room temp stay readable */
var isNight = null;
function night(on) { if (on === isNight) return; isNight = on;
  [].forEach.call(document.querySelectorAll("[data-n]"), function (e) { e.style.transition = "opacity 2s"; e.style.opacity = on ? "0.06" : ""; });
  ["h-v"].forEach(function (id) { var e = $(id).closest(".flex.flex-col"); e.style.opacity = on ? "0.1" : ""; });
  document.querySelector("#room > .flex.items-center.justify-between.pt-space-sm").style.opacity = on ? "0.1" : "";
  rSvg.style.opacity = on ? "0.25" : ""; document.body.style.filter = on ? "brightness(0.45)" : "";
}

function start() { poll(); pollWall(); setInterval(poll, 5000); setInterval(pollWall, 10000); }
if (window.pywebview && window.pywebview.api) start(); else window.addEventListener("pywebviewready", start);
})();
