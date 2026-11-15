/* Nova bridge for nova_v3.html (Stitch v3 design). Markup only got ids; all behaviour lives here. */
(function () {
"use strict";
var $ = function (id) { return document.getElementById(id); };
function txt(id, v) { var e = $(id); if (e) e.textContent = v; }
function w(id, pct) { var e = $(id); if (e) e.style.width = Math.max(0, Math.min(100, pct)) + "%"; }
function api(m, a) {
  try { var A = window.pywebview && window.pywebview.api; if (A && A[m]) return a !== undefined ? A[m](a) : A[m](); } catch (e) {}
  return Promise.reject();
}
var RED = "#FF4B3A", AMB = "#FF9A42", DIM = "#9A4A12";

/* ---- fill the window: zoom uniformly, then let the grid stretch into the leftover axis ---- */
function fit() {
  var z = Math.min(innerWidth / 1120, innerHeight / 740), b = document.body.style;
  b.zoom = z; b.width = b.maxWidth = (innerWidth / z) + "px"; b.height = b.maxHeight = (innerHeight / z) + "px";
}
document.documentElement.style.background = "#050302";
fit(); addEventListener("resize", fit);

/* ---- clock ---- */
var D = ["SUN","MON","TUE","WED","THU","FRI","SAT"], M = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
function p2(n) { return (n < 10 ? "0" : "") + n; }
function clock() { var d = new Date();
  txt("clk-d", D[d.getDay()] + " " + d.getDate() + " " + M[d.getMonth()]);
  txt("clk-t", p2(d.getHours()) + ":" + p2(d.getMinutes())); txt("clk-s", ":" + p2(d.getSeconds())); }
clock(); setInterval(clock, 1000);

/* ---- gauges: arc from (12,52) round a r=38 circle centred (50,52); 0..1 -> 0..180deg ---- */
function gauge(arc, ndl, f) {
  f = Math.max(0.001, Math.min(1, f)); var a = Math.PI * (1 - f), x = 50 + 38 * Math.cos(a), y = 52 - 38 * Math.sin(a);
  var A = $(arc), N = $(ndl);
  if (A) A.setAttribute("d", "M 12 52 A 38 38 0 0 1 " + x.toFixed(1) + " " + y.toFixed(1));
  if (N) { N.setAttribute("x1", x.toFixed(1)); N.setAttribute("y1", y.toFixed(1));
    N.setAttribute("x2", (50 + 44 * Math.cos(a)).toFixed(1)); N.setAttribute("y2", (52 - 44 * Math.sin(a)).toFixed(1)); }
}
gauge("t-arc", "t-ndl", 0); gauge("h-arc", "h-ndl", 0);

/* ---- voice state strip ---- */
var state = "listening", busy = false, sayT = 0;
function setState(s) { state = s;
  [].forEach.call(document.querySelectorAll("[data-vs]"), function (g) {
    var on = g.getAttribute("data-vs") === s, dot = g.firstElementChild;
    g.style.opacity = on ? "1" : "0.4";
    if (dot) { dot.style.background = on ? AMB : DIM; dot.classList.toggle("animate-ping", on && s === "listening"); }
  });
  txt("ai-st", "AI ENGINE: ONLINE // " + ({ listening: "AWAITING COMMAND", thinking: "PROCESSING", speaking: "RESPONDING" }[s] || "STANDBY"));
}
function idleSoon(ms) { clearTimeout(sayT); sayT = setTimeout(function () { if (!busy) setState("listening"); }, ms); }
setState("listening");

/* waveform: real mic level when Python pushes it, otherwise state-driven */
var bars = $("wave") ? [].slice.call($("wave").children) : [], lvl = 0, lvlT = 0, amp = 0.3, t = 0;
bars.forEach(function (b) { b.classList.remove("wave-bar"); });
window.novaLevel = function (v) { if (typeof v !== "number") return; if (v > 1) v /= 100; lvl = Math.max(0, Math.min(1, v)); lvlT = Date.now(); };
setInterval(function () {
  var target = Date.now() - lvlT < 400 ? 0.1 + lvl * 0.9 : ({ speaking: 0.9, thinking: 0.45, listening: 0.25 }[state] || 0.2);
  amp += (target - amp) * 0.2; t += 0.12;
  bars.forEach(function (b, i) { var k = 0.5 + 0.5 * Math.sin(t * 2 + i * 0.7) * Math.cos(t + i * 0.3); b.style.height = (3 + amp * 16 * k).toFixed(1) + "px"; });
}, 50);

/* ---- conversation lines + command bar ---- */
function heard(s) { txt("c-user", s ? "“" + s + "”" : ""); }
function said(s) { txt("c-nova", s || "…"); }
var sentAt = 0;
function submit() {
  var inp = $("nv-cmd"), s = inp.value.trim(); if (!s || busy) return;
  inp.value = ""; heard(s); busy = true; setState("thinking"); sentAt = Date.now();
  api("chat", s).then(function (r) {
    busy = false; said(r && r.reply); txt("lat", "REPLY: " + ((Date.now() - sentAt) / 1000).toFixed(1) + "s");
    setState("speaking"); idleSoon(3000);
  }).catch(function () { busy = false; said("I couldn't reach my core, sir."); setState("listening"); });
}
$("nv-cmd").addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); submit(); } });
function stop() { api("stop_speaking"); busy = false; setState("listening"); }
$("nv-stop").addEventListener("click", stop);
if ($("core")) $("core").addEventListener("click", stop);

/* ---- Python -> page ---- */
window.novaHeard = function (s) { heard(s); if (!busy) { setState("thinking"); sentAt = Date.now(); } };
window.novaSay = function (s) { said(s); setState("speaking"); idleSoon(3500); };
window.setCoreState = function (s) { setState(s === "standby" ? "listening" : s); };
window.novaVolume = function (v, muted) { txt("nv-vol", muted ? "MUTE" : "VOL " + Math.round(v)); };
window.novaMicReset = function () { txt("mic-st", "MIC: RESET"); setTimeout(function () { txt("mic-st", "MIC: ON"); }, 4000); };
var motAt = 0;
window.novaMotion = function () { motAt = Date.now(); paintMotion(); };
function paintMotion(stale) {
  var on = Date.now() - motAt < 4000, e = $("mot"), d = $("mot-dot");
  if (e) { e.textContent = stale ? "MOTION: NO DATA" : on ? "MOTION: DETECTED" : "MOTION: CLEAR"; e.style.color = on ? "#FFD9A8" : ""; }
  if (d) d.style.background = on ? AMB : "rgba(255,154,66,.4)";
}

/* ---- RC crawler ---- */
function drive(d) { txt("car-last", "SENT: " + d.toUpperCase()); api("drive", d); }
[].forEach.call(document.querySelectorAll("[data-d]"), function (b) { b.addEventListener("click", function () { drive(b.getAttribute("data-d")); }); });
var prof = [].slice.call(document.querySelectorAll("[data-sp]")), ON = "px-1 py-0.5 border border-[#FF9A42] bg-[#FF9A42] text-[#140600] font-bold text-center",
    OFF = "px-1 py-0.5 border border-[#9A4A12]/50 bg-[#160601] text-[#FFD9A8]/70 text-center hover:border-[#FF9A42]";
prof.forEach(function (b) { b.addEventListener("click", function () {
  prof.forEach(function (o) { o.className = o === b ? ON : OFF; }); drive("speed " + b.getAttribute("data-sp")); }); });
var KEYS = { w: "forward", s: "back", a: "left", d: "right", x: "stop", " ": "stop", c: "center" };
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") { stop(); return; }
  if (document.activeElement === $("nv-cmd")) return;
  var k = KEYS[e.key.toLowerCase()]; if (k) { e.preventDefault(); drive(k); }
});

/* ---- live stats ---- */
var flow = [];
function kb(n) { return n >= 1000 ? (n / 1024).toFixed(1) + "M" : String(n); }
function tok(n) { n = n || 0; return n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : (n / 1e3).toFixed(1) + "k"; }
function chip(id, ok) { var e = $(id); if (!e) return; e.textContent = ok ? "ONLINE" : ok === false ? "OFFLINE" : "--"; e.style.color = ok ? "" : RED; }
function upt(s) { var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600); return d ? d + "d " + h + "h" : h + "h " + Math.floor(s % 3600 / 60) + "m"; }

function poll() { api("stats").then(function (s) { if (!s) return;
  var io = s.iot || {}, b = s.bat || {}, vt = s.vitals || {}, cl = s.claude || {}, c = s.car || {}, wf = s.wifi || {};
  // header
  chip("room-st", !!io.fresh);
  txt("bat-v", b.pct != null ? b.pct + "%" + (b.plug ? "+" : "") : "--");
  var seg = $("bat-seg"); if (seg && b.pct != null) [].forEach.call(seg.children, function (x, i) { x.style.background = b.pct > i * 25 ? (b.pct < 20 ? RED : AMB) : "rgba(154,74,18,.4)"; });
  // room
  if (io.fresh && io.temp != null) { txt("t-v", (+io.temp).toFixed(1) + "°C"); gauge("t-arc", "t-ndl", (io.temp - 10) / 30); }
  if (io.fresh && io.humidity != null) { txt("h-v", Math.round(io.humidity) + "%"); gauge("h-arc", "h-ndl", io.humidity / 100); }
  if (io.motion === true || io.motion === 1 || io.motion === "1") motAt = Date.now();
  paintMotion(!io.fresh);
  // vitals
  if (vt.integrity != null) { txt("vi-v", vt.integrity + "%"); w("vi-b", vt.integrity); }
  if (vt.temp != null) { txt("vt-v", (+vt.temp).toFixed(1) + "°C"); w("vt-b", vt.temp); }
  if (vt.voltage != null) { txt("vv-v", (+vt.voltage).toFixed(1) + "V"); w("vv-b", vt.voltage / 13 * 100); }
  if (vt.status) { var st = $("vs-v"); st.textContent = vt.status; st.style.color = vt.status === "CRITICAL" ? RED : "";
    txt("vs-sub", vt.status === "CRITICAL" ? "CHECK HEAT / LOAD" : vt.status === "ELEVATED" ? "UNDER LOAD" : "NOMINAL // STABLE"); }
  if (s.uptime) txt("uptime", "UP: " + upt(s.uptime));
  // cpu
  txt("cpu-avg", "AVG " + s.cpu + "%");
  var rows = $("cpu-rows") ? $("cpu-rows").children : [];
  (s.cores || []).slice(0, rows.length).forEach(function (v, i) { var r = rows[i], sp = r.querySelectorAll("span");
    sp[1].textContent = v + "%"; sp[2].textContent = ""; r.querySelector(".h-full").style.width = v + "%"; });
  txt("cpu-load", "LOAD: " + s.load); txt("cpu-top", "TOP: " + (s.top || {}).name);
  // memory + claude
  txt("ram-t", "RAM: " + s.mem_gb + " / " + s.mem_tot + " GB"); txt("ram-v", s.mem + "%"); w("ram-b", s.mem);
  txt("swap-v", s.swap + "%"); w("swap-b", s.swap);
  var cp = Math.min(100, (cl.ctx || 0) / 2000);
  txt("ctx-v", tok(cl.ctx) + " / 200k (" + cp.toFixed(1) + "%)"); w("ctx-b", cp); $("ctx-b").style.background = cp > 80 ? RED : "";
  txt("tok-today", "TODAY: " + tok(cl.today)); txt("tok-calls", "CALLS: " + (cl.calls || 0));
  txt("disk", "DISK: " + s.disk_free + " GB FREE"); txt("procs", "PROCS: " + s.procs);
  // network
  txt("net-up", kb(s.up)); txt("net-dn", kb(s.down));
  txt("net-sig", wf.up ? wf.signal + "%" : "OFF"); txt("net-ssid", (wf.ssid || "--").slice(0, 12));
  flow.push(s.down || 0); if (flow.length > 24) flow.shift();
  var mx = Math.max.apply(null, flow.concat([1])), pts = flow.map(function (v, i) { return (i * 200 / 23).toFixed(1) + "," + (22 - v / mx * 18).toFixed(1); });
  if (pts.length > 1) { $("flow-l").setAttribute("d", "M" + pts.join(" L")); $("flow-f").setAttribute("d", "M" + pts.join(" L") + " L" + pts[pts.length - 1].split(",")[0] + ",24 L0,24 Z"); }
  txt("net-peak", "PEAK " + kb(mx) + " KB/s");
  // car
  var live = c.online && c.fresh, lk = $("car-link");
  lk.textContent = live ? "TX: LINKED" : "TX: NO LINK"; lk.style.color = live ? "" : RED;
  txt("car-rssi", c.rssi != null ? c.rssi + " dBm" : "--");
  var th = c.throttle === "forward" || c.throttle === "back"; $("car-thr-b").style.height = (th ? 100 : 0) + "%";
  txt("car-thr", { forward: "FWD", back: "REV" }[c.throttle] || "IDLE");
  $("car-dot").style.transform = "translateX(" + ({ left: -14, right: 14 }[c.steer] || 0) + "px)";
  txt("car-steer", "STEER: " + ({ left: "LEFT", right: "RIGHT" }[c.steer] || "CENTER"));
}).catch(function () {}); }

function pollHud() { api("hud").then(function (h) { if (!h) return; chip("hub-st", h.hub);
  txt("bulb", "BULB: " + (h.bulb ? h.bulb.toUpperCase() : "--")); }).catch(function () {}); }

function start() { poll(); pollHud(); setInterval(poll, 2500); setInterval(pollHud, 5000); }
if (window.pywebview && window.pywebview.api) start(); else window.addEventListener("pywebviewready", start);
})();
