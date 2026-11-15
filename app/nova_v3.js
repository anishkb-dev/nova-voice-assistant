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
  txt("clk-t", (d.getHours() % 12 || 12) + ":" + p2(d.getMinutes())); txt("clk-s", ":" + p2(d.getSeconds()) + (d.getHours() < 12 ? " AM" : " PM")); }
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
  // reactor breathes with the same signal: brighter + bigger halo when you talk / Nova speaks
  if (rSvg) rSvg.style.filter = "brightness(" + (0.8 + amp * 0.7).toFixed(2) + ")";
  if (rGlow) { rGlow.style.opacity = (0.4 + amp * 1.6).toFixed(2); rGlow.style.transform = "scale(" + (0.95 + amp * 0.25).toFixed(3) + ")"; }
}, 50);
var rSvg = $("r-svg"), rGlow = $("r-glow");

/* ---- conversation lines + command bar ---- */
/* last 2 finished exchanges sit dimmed above the live pair */
var hist = document.createElement("div"), past = [], lastU = "";
hist.style.cssText = "display:flex;flex-direction:column;gap:1px;font-family:'JetBrains Mono',monospace;font-size:10px;opacity:.5;color:#FFD9A8";
$("c-user").parentElement.parentElement.prepend(hist);
function heard(s) {
  var prevN = $("c-nova").textContent;
  if (lastU) { past.push([lastU, prevN]); if (past.length > 2) past.shift();
    hist.innerHTML = ""; past.forEach(function (x) { var d = document.createElement("div");
      d.style.cssText = "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:900px";
      d.textContent = "“" + x[0] + "”  →  " + x[1]; hist.appendChild(d); }); }
  lastU = s || ""; txt("c-user", s ? "“" + s + "”" : "");
  var d = new Date(); txt("last-cmd", "LAST COMMAND: " + (d.getHours() % 12 || 12) + ":" + p2(d.getMinutes()) + (d.getHours() < 12 ? " AM" : " PM"));
}
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
function drive(d) {
  if (d.indexOf("speed") === 0) txt("car-spd", d.split(" ")[1] + "%"); else txt("car-cmd", d.toUpperCase());
  api("drive", d);
}
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
var flow = [], linkAt = 0;
function kb(n) { return n >= 1000 ? (n / 1024).toFixed(1) + "M" : String(n); }
function tok(n) { n = n || 0; return n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : (n / 1e3).toFixed(1) + "k"; }
function chip(id, ok) { var e = $(id); if (!e) return; e.textContent = ok ? "ONLINE" : ok === false ? "OFFLINE" : "--"; e.style.color = ok ? "" : RED; }
function upt(s) { if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s"; var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600); return d ? d + "d " + h + "h" : h + "h " + Math.floor(s % 3600 / 60) + "m"; }

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
  // design has 4 rows; the Mac has more cores -> show the 4 busiest, with their real numbers
  var rows = $("cpu-rows") ? $("cpu-rows").children : [], cs = (s.cores || []).map(function (v, i) { return [v, i]; });
  txt("cpu-title", cs.length > rows.length ? "CPU // BUSIEST " + rows.length + " OF " + cs.length : "CPU USAGE (" + cs.length + " CORES)");
  cs.sort(function (a, b) { return b[0] - a[0]; }).slice(0, rows.length).forEach(function (c, i) { var r = rows[i], sp = r.querySelectorAll("span");
    sp[0].textContent = "CORE " + c[1]; sp[1].textContent = c[0] + "%"; sp[2].textContent = ""; r.querySelector(".h-full").style.width = c[0] + "%"; });
  txt("power", "POWER: " + (b.plug ? "ADAPTER" : b.plug === false ? "BATTERY" : "--"));
  var ra = $("room-age"); ra.textContent = io.fresh ? "LIVE" : "STALE"; ra.style.color = io.fresh ? "" : RED;
  txt("top-wifi", wf.up ? "WI-FI: " + wf.ssid + " // " + wf.signal + "%" : "WI-FI: OFF");
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
  if (live && !linkAt) linkAt = Date.now(); if (!live) linkAt = 0;
  txt("car-up", linkAt ? upt(Math.floor((Date.now() - linkAt) / 1000)) : "--");
  var cst = $("car-st"); cst.textContent = live ? "ONLINE" : "OFFLINE"; cst.style.color = live ? "" : RED;
  txt("car-drv", live ? ({ forward: "FWD", back: "REV" }[c.throttle] || "IDLE") + "/" + ({ left: "L", right: "R" }[c.steer] || "C") : "--");
  txt("car-last", c.ts ? "SEEN " + Math.max(0, Math.round(Date.now() / 1000 - c.ts)) + "s AGO" : "NEVER SEEN");
}).catch(function () {}); }

function pollHud() { api("hud").then(function (h) { if (!h) return; chip("hub-st", h.hub);
  txt("bulb", "BULB: " + (h.bulb ? h.bulb.toUpperCase() : "--")); }).catch(function () {}); }

function start() { poll(); pollHud(); setInterval(poll, 2500); setInterval(pollHud, 5000); }
if (window.pywebview && window.pywebview.api) start(); else window.addEventListener("pywebviewready", start);
})();

/* ===== rotating 3D wireframe rock-crawler (realistic build; same holo theme) ===== */
(function(){var svg=null;[].forEach.call(document.querySelectorAll("div"),function(d){if(!svg&&d.children.length===0&&d.textContent.trim()==="TRX-4 CHASSIS")svg=d.parentElement.querySelector("svg");});if(!svg)return;
  var cv=document.createElement("canvas");cv.width=300;cv.height=200;cv.style.cssText="width:100%;height:100%;display:block;filter:drop-shadow(0 0 3px rgba(255,150,70,.5))";
  svg.parentNode.replaceChild(cv,svg);
  var x=cv.getContext("2d"),CX=150,CY=112,SC=2.2,tilt=0.16,t=0,TAU=6.28318;
  function tf(p,ay){var X=p[0],Y=p[1],Z=p[2],cy=Math.cos(ay),sy=Math.sin(ay),x1=X*cy+Z*sy,z1=-X*sy+Z*cy,cx=Math.cos(tilt),sx=Math.sin(tilt),y1=Y*cx-z1*sx,z2=Y*sx+z1*cx;return [CX+x1*SC,CY-y1*SC,z2];}
  function edge(a,b,ay,base){var p=tf(a,ay),q=tf(b,ay),zc=(p[2]+q[2])/2,al=(base||.7)*(0.36+0.64*(zc+95)/190);al=Math.max(.08,Math.min(1,al));x.strokeStyle="rgba(255,162,80,"+al+")";x.beginPath();x.moveTo(p[0],p[1]);x.lineTo(q[0],q[1]);x.stroke();}
  function box(x0,x1,y0,y1,z0,z1,ay,b){var v=[[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],[x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]];[[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]].forEach(function(e){edge(v[e[0]],v[e[1]],ay,b);});}
  function ring(cx,cy,cz,R,ay){var pv=null;for(var i=0;i<=12;i++){var a=i/12*TAU,pt=[cx,cy+Math.cos(a)*R,cz+Math.sin(a)*R];if(pv)edge(pv,pt,ay,.5);pv=pt;}}
  /* big knobby tire with 5-spoke star hub (matches the gold-rim wheels) */
  function wheel(wx,wy,wz,R,ay){var N=13,w=6.5,i,a,f=(wx<0?-1:1),io=wx-w*f,oo=wx+w*f,cy,sz;
    for(var s=0;s<2;s++){var xf=(s?oo:io),pv=null;for(i=0;i<=N;i++){a=i/N*TAU;var pt=[xf,wy+Math.cos(a)*R,wz+Math.sin(a)*R];if(pv)edge(pv,pt,ay,.84);pv=pt;}}
    for(i=0;i<N;i++){a=i/N*TAU;cy=Math.cos(a);sz=Math.sin(a);
      if(i%2===0)edge([io,wy+cy*R,wz+sz*R],[oo,wy+cy*R,wz+sz*R],ay,.32);
      edge([wx,wy+cy*R,wz+sz*R],[wx,wy+cy*(R+2.6),wz+sz*(R+2.6)],ay,.5);}                              /* knobby lugs */
    var hr=R*.5;ring(oo,wy,wz,hr,ay);                                                                   /* rim */
    for(i=0;i<5;i++){a=i/5*TAU+.3;edge([oo,wy,wz],[oo,wy+Math.cos(a)*hr,wz+Math.sin(a)*hr],ay,.5);}     /* 5 spokes */
  }
  function axle(z,ay){var y=-11;edge([-31,y,z],[31,y,z],ay,.7);ring(-5,y,z,5,ay);ring(5,y,z,5,ay);edge([-5,y,z],[5,y,z],ay,.4);} /* solid axle + gearbox barrel */
  /* coil-over shock: a real helix spring between chassis mount a and axle mount b */
  function coil(a,b,turns,R,spt,ay){var dx=b[0]-a[0],dy=b[1]-a[1],dz=b[2]-a[2],L=Math.hypot(dx,dy,dz)||1,ux=dx/L,uy=dy/L,uz=dz/L;
    var hx=Math.abs(uy)<.9?0:1,hy=Math.abs(uy)<.9?1:0;
    var px=-uz*hy,py=uz*hx,pz=ux*hy-uy*hx,pl=Math.hypot(px,py,pz)||1;px/=pl;py/=pl;pz/=pl;
    var qx=uy*pz-uz*py,qy=uz*px-ux*pz,qz=ux*py-uy*px,M=Math.round(turns*spt),pv=null;
    for(var i=0;i<=M;i++){var tt=i/M,an=tt*turns*TAU,c=Math.cos(an),s=Math.sin(an);
      var pt=[a[0]+dx*tt+(px*c+qx*s)*R,a[1]+dy*tt+(py*c+qy*s)*R,a[2]+dz*tt+(pz*c+qz*s)*R];
      if(pv)edge(pv,pt,ay,.6);pv=pt;}}
  function shock(sx,zc,ay){coil([sx*13,9,zc*.55],[sx*25,-11,zc],5,3.1,6,ay);edge([sx*12,-3,zc*.5],[sx*27,-11,zc],ay,.4);} /* spring + lower link */
  function base(ay){var pv=null,i,a;for(i=0;i<=40;i++){a=i/40*TAU;var pt=[Math.cos(a)*64,-30,Math.sin(a)*64];if(pv)edge(pv,pt,ay,.16);pv=pt;}for(i=0;i<20;i++){a=i/20*TAU;edge([Math.cos(a)*54,-30,Math.sin(a)*54],[Math.cos(a)*64,-30,Math.sin(a)*64],ay,.18);}}
  var _last=0;(function d(ts){requestAnimationFrame(d);if(ts-_last<32)return;_last=ts;t+=.012;var ay=t;x.clearRect(0,0,300,200);x.lineWidth=1.15;
    base(ay*.5);
    var xr=14,yb=-4,yt=1;                                            /* flat open chassis: 2 side rails + crossmembers */
    edge([-xr,yb,-30],[-xr,yb,30],ay,.82);edge([xr,yb,-30],[xr,yb,30],ay,.82);
    edge([-xr,yt,-28],[-xr,yt,28],ay,.5);edge([xr,yt,-28],[xr,yt,28],ay,.5);
    [-28,-12,4,20,28].forEach(function(z){edge([-xr,yb,z],[xr,yb,z],ay,.44);edge([-xr,yb,z],[-xr,yt,z],ay,.3);edge([xr,yb,z],[xr,yt,z],ay,.3);});
    edge([-xr,yb,30],[0,yb-3,37],ay,.5);edge([xr,yb,30],[0,yb-3,37],ay,.5);                          /* front skid taper */
    edge([-xr,yb,-30],[0,yb-2,-36],ay,.45);edge([xr,yb,-30],[0,yb-2,-36],ay,.45);                    /* rear taper */
    box(-11,11,yt,9,-13,13,ay,.6);[-8,-4,0,4,8].forEach(function(z){edge([-11,9,z],[11,9,z],ay,.28);}); /* battery box + ribs */
    axle(26,ay);axle(-26,ay);
    shock(-1,26,ay);shock(1,26,ay);shock(-1,-26,ay);shock(1,-26,ay);               /* 4 coil-over shocks */
    edge([-3,9,2],[0,15,-3],ay,.5);edge([0,15,-3],[4,14,-7],ay,.5);edge([4,14,-7],[6,9,-9],ay,.45);   /* draped wires */
    var ap=tf([6,15,-8],ay);x.fillStyle="#ffd7a0";x.beginPath();x.arc(ap[0],ap[1],1.8,0,TAU);x.fill();
    wheel(-30,-11,26,17,ay);wheel(30,-11,26,17,ay);wheel(-30,-11,-26,17,ay);wheel(30,-11,-26,17,ay);
  })(0);
})();
