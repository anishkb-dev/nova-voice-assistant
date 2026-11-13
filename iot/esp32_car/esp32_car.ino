/*
 *  Nova RC Crawler — Phase A firmware (drive + OLED + Nova teleop)
 *  ----------------------------------------------------------------
 *  2nd ESP32 (NOT the room node). Same self-heal WiFi/MQTT pattern.
 *  The car is DUMB: it just executes commands. Brains live on the Mac.
 *
 *  MQTT (broker 192.168.68.110):
 *    home/car/throttle   payload: forward | back | stop
 *    home/car/steer      payload: left | right | center
 *    home/car/status     "online" (retained) + last-will "offline"
 *    home/car/telemetry  {"throttle":"stop","steer":"center","rssi":-57}
 *    home/car/odo        {"ticks":N,"tps":ticks/s} 10Hz — TCRT5000 on GPIO35 counting driveshaft tape
 *    home/car/imu        {"ax":..,"ay":..,"az":..(g),"gx":..,"gy":..,"gz":..(deg/s)} 10Hz, if the MPU6050 answers
 *
 *  DEFAULT PIN MAP (wire the L298N to match, or change these):
 *    L298N  ENA  -> GPIO13   (drive speed PWM)
 *    L298N  IN1  -> GPIO14   drive dir A
 *    L298N  IN2  -> GPIO27   drive dir B
 *    L298N  IN3  -> GPIO26   steer dir A
 *    L298N  IN4  -> GPIO25   steer dir B
 *    L298N  ENB  -> GPIO33   (steer speed PWM)
 *    OLED   SDA  -> GPIO21,  SCL -> GPIO22   (SSD1306 128x64 I2C @ 0x3C)
 *    L298N  GND  -> ESP GND (common),  motor V into L298N +12V terminal.
 *
 *  Wiring notes: ChA (OUT1/2) = front+rear drive motors PARALLELED.
 *  ChB (OUT3/4) = steering motor. ESP GPIOs are 3.3V — L298N accepts that
 *  as logic HIGH. If motor supply is only ~5V, REMOVE the L298N 5V-EN jumper
 *  and feed the L298N +5V logic pin from the ESP 5V pin instead.
 *
 *  Libraries: PubSubClient, Adafruit_SSD1306, Adafruit_GFX.
 */
#include <WiFi.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "secrets.h"          // SECRET_WIFI_SSID / _PASS / _BROKER_IP  (git-ignored)

// ---- config ----
const char* WIFI_SSID = SECRET_WIFI_SSID;
const char* WIFI_PASS = SECRET_WIFI_PASS;
const char* BROKER    = SECRET_BROKER_IP;     // fallback only — the Mac's DHCP address keeps drifting (.105/.110/.112/.111)
const char* BROKER_MDNS = "Anishs-MacBook-Air";   // the Mac's Bonjour name: found by name first, so drift can't strand the car
const char* ROOM      = "car";          // topic root: home/car/*
const IPAddress CAM_IP(192, 168, 68, 107);   // CAM 02 on the bracket (was .118). ponytail: DHCP — breaks when it moves; reserve it (roadmap 0.4)
int         driveDuty = 255;            // drive PWM 0-255 (start FULL — 5V supply is weak after the L298N drop;
                                        // tune live over MQTT: home/car/speed with payload 0..100)
const int   STEER_PWM = 255;            // steering KICK duty: swings the wheels over against the return spring
const int   STEER_HOLD = 160;           // then hold at this: a motor stalled at the end stop at 255 threw enough
                                        // noise to reset the ESP (EN glitch, "poweron", 5V + pack both steady).
                                        // Raise if the wheels creep back under hold; a 104 cap across the motor is the real fix.
int         pulseMs   = 450;            // ONE press drives this long then auto-stops (0 = latched/hold).
                                        // tune live: home/car/pulse with payload ms (e.g. 300)

// ---- pins ----
const int ENA = 13, IN1 = 14, IN2 = 27;   // drive channel A
const int IN3 = 26, IN4 = 25, ENB = 33;   // steer channel B
const int TRIG_PIN  = 18;                 // sonar fixed in the tray's front wall (servo head dropped 2026-10-09; GPIO23 free)
const int WHEEL_PIN = 35;                 // FC-51 IR OUT (module on 3V3) — input-only pin; tape strips on a rear rim
const int ECHO_PIN  = 19;                 // via 1k/1.8k divider — Echo is 5V, this pin is not 5V tolerant
#define OLED_ADDR 0x3C

// ---- battery sense (2S pack via a divider on an ADC1 pin) ----
const int   VBAT_PIN = 32;          // ADC1 pin (safe with WiFi on); pack+ -[R1]- pin -[R2]- GND. Was 34: its ADC now clips at ~1.25 V (damaged by the 5.4V-on-3V3 incident?)
const float VBAT_R1  = 99000.0;     // top resistor  (pack+ -> the ADC node)
const float VBAT_R2  = 26500.0;     // bottom resistor (node -> GND)
const float LOW_CUT_V = 6.4;        // motors lock out below this (smoothed): 3.2V/cell under load
const bool  VBAT_OK  = false;       // ponytail: this ESP's pins clamp at ~1.25 V (5.4V-on-3V3 damage), so the divider reads a
                                    // fixed 5.95 V and tripped the low-battery lock. Off until the INA3221 (I2C) replaces it.
float       vbatCal  = 1.0;         // fudge: set to (multimeter V / reading) and reflash. Was 1.373 = papering over the clipped ADC below

// ---- autonomy tuning ----
const float STOP_CM   = 15.0;   // hard stop, enforced in BOTH modes
const float AVOID_CM  = 35.0;   // "something in front" — start avoiding
const int   PING_MS   = 60;     // HC-SR04 needs ~60ms between pings or it hears the last echo
const int   BACK_MS   = 600;    // reverse burst when boxed in
const int   TURN_MS   = 700;    // how long to hold the escape heading
const int   AUTO_DUTY = 200;    // gentler than teleop full duty; autonomy shouldn't bolt
const int   SLOW_DUTY = 150;    // creep when something is getting close (sonar < SLOW_CM or the camera sees clutter ahead)
const float SLOW_CM   = 70.0;
const int   VIS_BLOCK = 60;     // camera clutter score 0-99 (Mac vision_avoid.py) above which "ahead" counts as blocked
const int   VIS_SLOW  = 35;
const int   STALL_MS  = 900;    // driving but wheel ticks ~0 this long = wedged on something the sonar missed
const float BUMP_G    = 1.8;    // |accel| spike = hit something
const float TILT_STOP = 35.0;   // degrees off level: about to roll — stop autonomy

Adafruit_SSD1306 oled(128, 64, &Wire, -1);
WiFiClient net;
PubSubClient mqtt(net);
char topic[48], payload[192];   // telemetry JSON hits 100 chars (forward + pct 100); 96 truncated it

String curThrottle = "stop", curSteer = "center";
bool oledOK = false;

// ---- MPU6050 (GY-521) on the OLED's I2C bus, raw registers — no library ----
const uint8_t MPU = 0x68;               // AD0 floating/low
bool imuOK = false;
float imu[6];                           // ax ay az (g, +-2g)  gx gy gz (deg/s, +-250)
unsigned long lastImu = 0;
volatile uint32_t wheelTicks = 0, lastTickUs = 0;
void IRAM_ATTR onWheel() {               // one tick per tape stripe passing the TCRT5000
  uint32_t t = micros();
  if (t - lastTickUs > 1500) { wheelTicks++; lastTickUs = t; }   // LM393 chatters at the threshold: 1.5ms debounce
}
bool imuRead() {
  Wire.beginTransmission(MPU); Wire.write(0x3B);          // ACCEL_XOUT_H .. GYRO_ZOUT_L = 14 bytes
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(MPU, (uint8_t)14) != 14) return false;
  int16_t r[7];
  for (int i = 0; i < 7; i++) r[i] = (Wire.read() << 8) | Wire.read();
  for (int i = 0; i < 3; i++) { imu[i] = r[i] / 16384.0; imu[3 + i] = r[4 + i] / 131.0; }  // r[3] = temp
  return true;
}
float vbat = 0;                           // last battery reading, volts (refreshed ~1Hz)
int   vpct = -1;                          // battery %, -1 = no pack sensed (the one number OLED + app show)
float vbatRaw = 0;                        // unsmoothed pack volts from the last readVbat()
int   lowCount = 0;                       // consecutive 1Hz raw readings under LOW_CUT_V
bool  lowBatt = false;                    // latched: pack hit the floor, motors locked out until power-cycle

// ---- autonomy state ----
bool  autoMode = false;                   // starts OFF on purpose: a car that drives itself at boot is a runaway
float aheadDist = -1;                     // latest sonar cm, -1 = no echo
unsigned long lastPing = 0;
enum AutoState { A_FORWARD, A_BACK, A_TURN };
AutoState autoState = A_FORWARD;
unsigned long stateStart = 0;
int   escapeDir = 1;                      // -1 left, +1 right — which way we're escaping
int   visL = 0, visC = 0, visR = 0;        // camera clutter per third, 0-99, from home/car/vision "l,c,r"
unsigned long visAt = 0;                  // when the last vision msg came; stale after 800 ms -> sonar-only
int   manualDuty = 255;                   // drive duty to restore when autonomy ends
unsigned long lastTele = 0, lastFace = 0, thrStart = 0, steerStart = 0;
bool  camOK = false;                      // CAM answers on :80 (probed every 5s)
float tps = 0;                            // wheel ticks/s, latest 10Hz sample (for the HUD)

// ---- motor helpers ----
void drive(bool fwd, bool on) {
  static int lastDir = 0;                 // -1 back, 0 stopped, +1 forward
  on = on && !lowBatt;                    // flat pack: no drive, whatever asked for it
  int dir = on ? (fwd ? 1 : -1) : 0;
  if (dir != 0 && dir != lastDir) {       // same soft start as steer(): a full-duty drive kick reset the ESP
    analogWrite(ENA, 0);                  // (boot sw/wdt right after "forward", 2026-11-12) — ramp ~80 ms
    digitalWrite(IN1, fwd);
    digitalWrite(IN2, !fwd);
    for (int d = 60; d < driveDuty; d += 20) { analogWrite(ENA, d); delay(8); }
  }
  lastDir = dir;
  digitalWrite(IN1, on && fwd);           // rebuilt motor wiring: forward is now IN1 high
  digitalWrite(IN2, on && !fwd);
  analogWrite(ENA, on ? driveDuty : 0);   // drive speed (portable across ESP32 cores)
}
void steer(int dir, int pwm) {            // -1 left, +1 right, 0 center; pwm 0-255
  static int lastDir = 0;
  if (lowBatt) dir = 0;
  if (dir != 0 && dir != lastDir) {       // soft start: a full-power kick from standstill spiked the rail and
    analogWrite(ENB, 0);                  // crashed the ESP (SW_CPU_RESET / OWDT_RESET, no backtrace) — ramp 40 ms
    digitalWrite(IN3, dir > 0);           // rebuilt steering wiring: swap the former mirrored mapping
    digitalWrite(IN4, dir < 0);
    for (int d = 60; d < pwm; d += 40) { analogWrite(ENB, d); delay(8); }
  }
  digitalWrite(IN3, dir > 0);
  digitalWrite(IN4, dir < 0);
  analogWrite(ENB, dir == 0 ? 0 : pwm);
  lastDir = dir;
}
void stopAll() { drive(true, false); steer(0, 0); }

// ---- sonar (fixed, facing ahead) ----
float pingCm() {                                  // -1 on no echo / out of range
  digitalWrite(TRIG_PIN, LOW);  delayMicroseconds(3);
  digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long us = pulseIn(ECHO_PIN, HIGH, 30000UL);   // 30ms ~= 5m ceiling
  if (us == 0) return -1;
  float cm = us / 58.0;
  return (cm < 2 || cm > 400) ? -1 : cm;
}

// One ping per call at most (<=30ms block) — loop() must keep servicing MQTT/teleop.
void pingTick() {
  if (millis() - lastPing < (unsigned long)PING_MS) return;
  lastPing = millis();
  aheadDist = pingCm();
}

float aheadCm() { return aheadDist; }
bool  blocked(float d, float limit) { return d > 0 && d < limit; }   // -1 (no echo) = open air

// ---- battery ----
float readVbat() {                                  // volts at the pack, undoing the divider
  static float ema = -1;                            // smoothed across calls (~1Hz): ADC + WiFi noise is ±0.4V raw
  uint32_t mv = 0;
  // jitters ±0.07V. ponytail: a 100nF cap node->GND would steady it.
  analogReadMilliVolts(VBAT_PIN);                   // throwaway read
  for (int i = 0; i < 16; i++) { delayMicroseconds(500); mv += analogReadMilliVolts(VBAT_PIN); }
  float vnode = (mv / 16) / 1000.0;                 // volts at the ADC pin
  float v = vnode * (VBAT_R1 + VBAT_R2) / VBAT_R2 * vbatCal;   // scale back up to pack volts
  vbatRaw = v;
  ema = (ema < 0 || fabsf(v - ema) > 2) ? v : ema * 0.95f + v * 0.05f;   // ~20s smoothing at 1Hz (0.1V = 5.5% on the OLED); big jump (plug in/out) = snap
  return ema;
}

// 2S Li-ion resting-voltage curve (per cell ×2), piecewise linear. 0% = 3.3V/cell, the safe floor.
int battPct(float v) {
  static const float V[] = {6.60, 7.04, 7.24, 7.44, 7.66, 7.96, 8.30};
  static const int   P[] = {   0,   10,   20,   40,   60,   80,  100};
  if (v <= V[0]) return 0;
  for (int i = 1; i < 7; i++)
    if (v < V[i]) return P[i-1] + (int)((v - V[i-1]) / (V[i] - V[i-1]) * (P[i] - P[i-1]));
  return 100;
}

// Sci-fi HUD, 128x64, minimal text. Yellow strip: NET signal bar | battery bar + % ; mode | CAM dot.
// Blue area (corner-bracket frame): D-pad showing drive direction, big SPD (wheel ticks/s),
// DST sonar + bar with the stop line, and a tilt horizon from the accelerometer.
static void segBar(int x, int y, int n, int lit) {                   // n segments, 4x5px, 1px gaps
  for (int i = 0; i < n; i++)
    if (i < lit) oled.fillRect(x + i * 5, y, 4, 5, SSD1306_WHITE);
    else         oled.drawRect(x + i * 5, y, 4, 5, SSD1306_WHITE);
}
static void tri(int x0, int y0, int x1, int y1, int x2, int y2, bool on) {
  if (on) oled.fillTriangle(x0, y0, x1, y1, x2, y2, SSD1306_WHITE);
  else    oled.drawTriangle(x0, y0, x1, y1, x2, y2, SSD1306_WHITE);
}
void showOLED() {
  if (!oledOK) return;
  static float roll0 = NAN, pitch0 = NAN;      // ponytail: "level" = whatever it read first — boot the car on flat ground
  bool tick = (millis() / 400) % 2;            // shared blink phase
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE); oled.setTextSize(1);
  char b[16];

  // ---- yellow strip ----
  bool link = mqtt.connected();
  int rssi = WiFi.RSSI();
  int net = link ? constrain((rssi + 95) / 9, 1, 5) : 0;             // -50dBm+ = 5 segments
  oled.setCursor(0, 0); oled.print("NET");
  if (link || tick) segBar(20, 1, 5, net);                            // no broker -> empty bar blinks
  int pct = max(vpct, 0);
  if (vpct < 0) strcpy(b, "USB"); else snprintf(b, sizeof(b), "%d%%", vpct);
  int tx = 128 - strlen(b) * 6;
  oled.setCursor(tx, 0); oled.print(b);
  int bx = tx - 30;
  if (!lowBatt || tick) segBar(bx, 1, 5, (pct + 19) / 20);            // LOW -> blinks
  oled.fillRect(bx + 25, 2, 2, 3, SSD1306_WHITE);                     // battery tip
  oled.setCursor(0, 8); oled.print(autoMode ? "AUTO" : "MANUAL");
  oled.setCursor(104, 8); oled.print("CAM");
  if (camOK && tick) oled.fillCircle(100, 11, 2, SSD1306_WHITE);      // live -> blinks like a REC light
  else if (!camOK) oled.drawCircle(100, 11, 2, SSD1306_WHITE);        // down -> hollow

  // ---- frame: corner brackets round the blue area ----
  const int L = 5;
  oled.drawFastHLine(0, 17, L, SSD1306_WHITE);  oled.drawFastVLine(0, 17, L, SSD1306_WHITE);
  oled.drawFastHLine(123, 17, L, SSD1306_WHITE); oled.drawFastVLine(127, 17, L, SSD1306_WHITE);
  oled.drawFastHLine(0, 63, L, SSD1306_WHITE);  oled.drawFastVLine(0, 59, L, SSD1306_WHITE);
  oled.drawFastHLine(123, 63, L, SSD1306_WHITE); oled.drawFastVLine(127, 59, L, SSD1306_WHITE);

  // ---- D-pad: lit arrows = where it's driving ----
  const int px = 19, py = 41;
  tri(px, py - 17, px - 6, py - 10, px + 6, py - 10, curThrottle == "forward");
  tri(px, py + 17, px - 6, py + 10, px + 6, py + 10, curThrottle == "back");
  tri(px - 17, py, px - 10, py - 6, px - 10, py + 6, curSteer == "left");
  tri(px + 17, py, px + 10, py - 6, px + 10, py + 6, curSteer == "right");
  if (curThrottle == "stop") oled.fillCircle(px, py, 3, SSD1306_WHITE); else oled.drawCircle(px, py, 3, SSD1306_WHITE);

  // ---- centre: speed big, distance small ----
  oled.setCursor(42, 19); oled.print("SPD");
  oled.setTextSize(2); oled.setCursor(42, 28);
  snprintf(b, sizeof(b), tps < 10 ? "%3.1f" : "%3.0f", tps); oled.print(b);
  oled.setTextSize(1);
  float d = aheadCm();
  if (d < 0) strcpy(b, "DST --"); else snprintf(b, sizeof(b), "DST %d", (int)d);
  oled.setCursor(42, 47); oled.print(b);
  oled.drawRect(42, 57, 46, 4, SSD1306_WHITE);
  oled.fillRect(43, 58, d < 0 ? 44 : constrain((int)(d * 44 / 200), 0, 44), 2, SSD1306_WHITE);   // full = open road
  oled.drawFastVLine(43 + (int)(STOP_CM * 44 / 200), 55, 8, SSD1306_WHITE);                     // hard-stop line

  // ---- right: tilt horizon ----
  const int cx = 110, cy = 36, r = 14;
  oled.drawCircle(cx, cy, r, SSD1306_WHITE);
  for (int a = 0; a < 360; a += 45)                                    // bezel ticks
    oled.drawPixel(cx + (r + 2) * cosf(a * 0.01745f), cy + (r + 2) * sinf(a * 0.01745f), SSD1306_WHITE);
  if (imuOK) {
    float roll  = atan2f(imu[1], imu[2]);
    float pitch = atan2f(-imu[0], sqrtf(imu[1] * imu[1] + imu[2] * imu[2]));
    if (isnan(roll0)) { roll0 = roll; pitch0 = pitch; }
    roll -= roll0; pitch -= pitch0;
    float off = constrain(pitch * 30, -r + 2, r - 2);                 // ~0.5px per degree
    float c = cosf(roll), s2 = sinf(roll);
    oled.drawLine(cx - c * (r - 2) - s2 * off, cy + s2 * (r - 2) - c * off,
                  cx + c * (r - 2) - s2 * off, cy - s2 * (r - 2) - c * off, SSD1306_WHITE);
  }
  oled.drawFastHLine(cx - 6, cy, 4, SSD1306_WHITE); oled.drawFastHLine(cx + 3, cy, 4, SSD1306_WHITE);   // fixed wings
  oled.drawPixel(cx, cy, SSD1306_WHITE);
  oled.display();
}

// ---- autonomy ----
// A crawler steers with a steering motor, so it cannot pivot in place: every heading
// change costs forward or reverse travel. Hence back-up-then-turn rather than spin.
void autoOff(const char* why) {
  autoMode = false; stopAll(); driveDuty = manualDuty; curThrottle = "stop"; curSteer = "center";
  Serial.printf("auto OFF: %s\n", why);
}

// Escape: back out (with opposite lock if too close), then drive out on the chosen side.
void escape(bool reverseFirst, unsigned long now) {
  bool vis = now - visAt < 800;
  escapeDir = vis ? (visL <= visR ? -1 : 1)   // camera: turn toward the less cluttered side
                  : -escapeDir;               // no camera: alternate so a corner can't trap it
  if (reverseFirst) { drive(false, true); steer(-escapeDir, STEER_PWM); curThrottle = "back"; autoState = A_BACK; }
  else              { drive(true, true);  steer(escapeDir, STEER_PWM);  curThrottle = "forward"; autoState = A_TURN; }
  curSteer = escapeDir < 0 ? "left" : "right";
  stateStart = now;
}

void autoTick() {
  if (!autoMode) return;
  unsigned long now = millis();
  bool vis = now - visAt < 800;
  float d = aheadCm();

  if (imuOK) {                                         // MPU safety, every state
    float g = sqrtf(imu[0] * imu[0] + imu[1] * imu[1] + imu[2] * imu[2]);
    float tilt = g > 0.2f ? acosf(constrain(imu[2] / g, -1.0f, 1.0f)) * 57.3f : 0;   // assumes the MPU sits flat
    if (tilt > TILT_STOP) { autoOff("tilt"); return; }
    if (g > BUMP_G && autoState == A_FORWARD) { escape(true, now); return; }          // jolt = collision
  }

  switch (autoState) {
    case A_FORWARD: {
      bool camBlocked = vis && visC > VIS_BLOCK;
      if (blocked(d, STOP_CM)) { escape(true, now); break; }
      if (blocked(d, AVOID_CM) || camBlocked) { escape(false, now); break; }
      if (wheelTicks > 0 && now - stateStart > (unsigned long)STALL_MS && tps < 1.0f) { escape(true, now); break; }   // wheels not turning
      driveDuty = (blocked(d, SLOW_CM) || (vis && visC > VIS_SLOW)) ? SLOW_DUTY : AUTO_DUTY;
      drive(true, true); steer(0, 0);
      curThrottle = "forward"; curSteer = "center";
      break;
    }
    case A_BACK:
      if (now - stateStart > (unsigned long)BACK_MS) {
        drive(true, true); steer(escapeDir, STEER_PWM);
        curThrottle = "forward"; curSteer = escapeDir < 0 ? "left" : "right";
        autoState = A_TURN; stateStart = now;
      }
      break;
    case A_TURN:
      if (now - stateStart > (unsigned long)TURN_MS) { autoState = A_FORWARD; stateStart = now; }
      break;
  }
}

// ---- MQTT command handler ----
void onMqtt(char* t, byte* p, unsigned int len) {
  char cmd[12] = {0}; memcpy(cmd, p, len < 11 ? len : 11);
  String tp = t, c = cmd;

  if (tp.endsWith("/vision")) {               // "l,c,r" clutter 0-99 from the Mac's camera script
    sscanf(cmd, "%d,%d,%d", &visL, &visC, &visR); visAt = millis();
    return;
  }
  if (tp.endsWith("/mode")) {
    if (c == "auto" && !autoMode) { manualDuty = driveDuty; driveDuty = AUTO_DUTY; autoMode = true; autoState = A_FORWARD; stateStart = millis(); }
    else if (c != "auto" && autoMode) autoOff("mode manual");
    Serial.printf("mode = %s\n", autoMode ? "auto" : "manual");
    showOLED();
    return;
  }
  // any manual command drops autonomy — the human always wins
  if (autoMode && (tp.endsWith("/throttle") || tp.endsWith("/steer"))) {
    autoOff("manual command");
  }

  if (tp.endsWith("/throttle")) {
    if      (c == "forward") { drive(true, true);  curThrottle = "forward"; thrStart = millis(); }
    else if (c == "back")    { drive(false, true); curThrottle = "back";    thrStart = millis(); }
    else                     { drive(true, false); curThrottle = "stop";    thrStart = 0; }  // stop / anything else
  } else if (tp.endsWith("/steer")) {
    if      (c == "center") { steer(0, 0);         curSteer = "center"; steerStart = 0; }
    else if (c == "left")   { steer(-1, curSteer == "left"  ? STEER_HOLD : STEER_PWM); curSteer = "left";  steerStart = millis(); }
    else if (c == "right")  { steer(1,  curSteer == "right" ? STEER_HOLD : STEER_PWM); curSteer = "right"; steerStart = millis(); }
    else {                                  // numeric -100..100 (phone joystick: sign=dir, magnitude=angle)
      int v = c.toInt(); v = v < -100 ? -100 : (v > 100 ? 100 : v);
      int mag = v < 0 ? -v : v;
      if (mag < 12) { steer(0, 0); curSteer = "center"; steerStart = 0; }
      else {
        int dir = v < 0 ? -1 : 1;
        int pwm = map(mag, 12, 100, 205, 255);  // 205 (80%) floor: 130 strained against the spring on the floor. Tune here.
        steer(dir, pwm); curSteer = dir < 0 ? "left" : "right"; steerStart = millis();
      }
    }
  } else if (tp.endsWith("/speed")) {
    int pct = c.toInt(); pct = pct < 0 ? 0 : (pct > 100 ? 100 : pct);
    driveDuty = map(pct, 0, 100, 0, 255);              // live drive-speed tune, 0..100%
    if (curThrottle == "forward") drive(true, true);   // apply immediately if already driving
    else if (curThrottle == "back") drive(false, true);
  } else if (tp.endsWith("/pulse")) {
    pulseMs = c.toInt(); if (pulseMs < 0) pulseMs = 0;  // 0 = latched/hold mode
  }
  Serial.printf("cmd %s = %s\n", t, cmd);
  // no showOLED() here: a full frame blocks ~25-100ms and the phone sends many msgs/sec — redrawing per
  // command queued them up (control lag + deadman expiring). loop() already redraws every 120ms.
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                 // low latency, no dropped packets
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(400); Serial.print("."); showOLED(); feedLoopWDT();
    if (++tries > 50) { Serial.println(" timeout -> reboot"); delay(200); ESP.restart(); }
  }
  Serial.printf(" connected: %s\n", WiFi.localIP().toString().c_str());
}

void connectMqtt() {
  int fails = 0;
  while (!mqtt.connected()) {
    stopAll();                          // FAILSAFE: motors off whenever we're not linked
    IPAddress mac = MDNS.queryHost(BROKER_MDNS, 1500);   // re-resolve every attempt: the Mac may have moved
    bool good = mac != IPAddress(0, 0, 0, 0) && mac[0] != 127;   // the Mac also advertises 127.0.0.1 — that's the car itself
    if (good) mqtt.setServer(mac, 1883); else mqtt.setServer(BROKER, 1883);
    Serial.printf("broker %s (%s)\n", good ? mac.toString().c_str() : BROKER, good ? "mdns" : "fallback");
    feedLoopWDT();
    snprintf(topic, sizeof(topic), "home/%s/status", ROOM);
    if (mqtt.connect("esp32-car", nullptr, nullptr, topic, 0, true, "offline")) {
      mqtt.publish(topic, "online", true);
      static const char* RR[] = {"unknown","poweron","ext","sw","panic","int_wdt","task_wdt","wdt","deepsleep","brownout","sdio"};
      int rr = (int)esp_reset_reason();   // why did we (re)boot? retained so it survives the reconnect
      snprintf(topic, sizeof(topic), "home/%s/boot", ROOM);
      snprintf(payload, sizeof(payload), "%s up=%lus", rr < 11 ? RR[rr] : "?", millis() / 1000);
      mqtt.publish(topic, payload, true);
      snprintf(topic, sizeof(topic), "home/%s/status", ROOM);
      snprintf(topic, sizeof(topic), "home/%s/+", ROOM);   // throttle + steer
      mqtt.subscribe(topic);
      Serial.println("MQTT up");
    } else {
      Serial.printf("MQTT rc=%d retry\n", mqtt.state());
      delay(1500); feedLoopWDT();
      if (++fails > 8) { Serial.println("MQTT stuck -> reboot"); ESP.restart(); }
    }
    showOLED();
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT);
  pinMode(ENA, OUTPUT); pinMode(ENB, OUTPUT);   // analogWrite() drives these (auto LEDC)
  stopAll();                          // start dead-stopped

  pinMode(TRIG_PIN, OUTPUT); pinMode(ECHO_PIN, INPUT);
  pinMode(WHEEL_PIN, INPUT);              // module drives the line (LM393 + pull-up), no internal pull needed
  attachInterrupt(digitalPinToInterrupt(WHEEL_PIN), onWheel, FALLING);
  digitalWrite(TRIG_PIN, LOW);

  Wire.begin(21, 22);
  Wire.setClock(400000);              // SSD1306 fast mode: a frame takes ~25ms instead of ~100ms at 100kHz
  // begin() returns true even with NO OLED attached (reported oled=ok i2c=none), so loop() blasted frames
  // down floating SDA/SCL every 150ms — suspected I2C hang -> watchdog reset after motor noise. Probe first.
  auto ack = [](uint8_t a) { Wire.beginTransmission(a); return Wire.endTransmission() == 0; };
  oledOK = (ack(0x3C) && oled.begin(SSD1306_SWITCHCAPVCC, 0x3C)) ||   // try the common address...
           (ack(0x3D) && oled.begin(SSD1306_SWITCHCAPVCC, 0x3D));     // ...then the alternate
  if (oledOK) { oled.clearDisplay(); oled.display(); }
  Wire.beginTransmission(MPU); Wire.write(0x6B); Wire.write(0);   // PWR_MGMT_1: wake from sleep
  imuOK = Wire.endTransmission() == 0;
  if (imuOK) { Wire.beginTransmission(MPU); Wire.write(0x1A); Wire.write(3); Wire.endTransmission(); }
                                      // CONFIG DLPF=3 (~44Hz): cuts motor/gear vibration out of the readings

  analogSetPinAttenuation(VBAT_PIN, ADC_11db);   // full ~0-3.1V range. Without it this pin clipped at ~1.25V, so the
                                      // reading sat frozen at 8.17V for days and the old "27% low" cal hid it
  if (VBAT_OK) vbat = readVbat();     // prime the reading so the first frame isn't 0.0V (and vbatRaw stays 0 when off: no lock)

  enableLoopWDT();                    // loop() stuck >5s (seen after a brownout: OLED frozen, WiFi pingable,
                                      // MQTT dead for minutes) -> task_wdt reset. Enabled before the connect loops, which feed it (fed-before-enabled = log spam)
  connectWifi();
  MDNS.begin("esp32-car");
  mqtt.setServer(BROKER, 1883);
  mqtt.setCallback(onMqtt);
  mqtt.setSocketTimeout(4);           // a dead connect() can't block past the loop watchdog
  connectMqtt();

  // publish an I2C scan + OLED status so the display can be debugged remotely
  { String f = "";
    for (byte a = 1; a < 127; a++) {
      Wire.beginTransmission(a);
      if (Wire.endTransmission() == 0) { char b[8]; snprintf(b, 8, "0x%02X ", a); f += b; }
    }
    snprintf(payload, sizeof(payload), "oled=%s i2c=%s",
             oledOK ? "ok" : "FAIL", f.length() ? f.c_str() : "none");
    snprintf(topic, sizeof(topic), "home/%s/i2c", ROOM);
    mqtt.publish(topic, payload, true);
  }
  showOLED();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) { stopAll(); connectWifi(); }
  if (!mqtt.connected())            { if (autoMode) autoOff("link lost"); connectMqtt(); }   // no link, no autonomy
  mqtt.loop();

  pingTick();

  // Hard floor, enforced in BOTH modes: never keep driving forward into something.
  if (curThrottle == "forward" && blocked(aheadCm(), STOP_CM)) {
    drive(true, false); curThrottle = "stop"; thrStart = 0;
    if (autoMode && autoState == A_FORWARD) { autoState = A_FORWARD; }   // autoTick picks the escape next pass
  }

  autoTick();

  // momentary control: auto-stop a short time after each press (hold/key-repeat keeps it going)
  if (pulseMs > 0 && !autoMode) {     // autonomy drives continuously; the pulse timer is a teleop safety
    if (thrStart   && millis() - thrStart   > (unsigned long)pulseMs) { drive(true, false); curThrottle = "stop";   thrStart = 0; }
    if (steerStart && millis() - steerStart > (unsigned long)pulseMs) { steer(0, 0);        curSteer = "center";   steerStart = 0; }
  }

  if (millis() - lastFace > 150) { lastFace = millis(); showOLED(); }   // HUD refresh ~7Hz

  if (millis() - lastImu >= 100) {       // 10Hz motion + wheel odometry for the world-model recorder
    unsigned long dt = millis() - lastImu; lastImu = millis();
    if (imuOK && imuRead()) {
      snprintf(payload, sizeof(payload), "{\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"gx\":%.1f,\"gy\":%.1f,\"gz\":%.1f}",
               imu[0], imu[1], imu[2], imu[3], imu[4], imu[5]);
      snprintf(topic, sizeof(topic), "home/%s/imu", ROOM);
      mqtt.publish(topic, payload);
    }
    static uint32_t prevTicks = 0;
    uint32_t tk = wheelTicks;             // raw ticks; cm per tick gets calibrated once the tape is on
    tps = (tk - prevTicks) * 1000.0 / dt;
    snprintf(payload, sizeof(payload), "{\"ticks\":%lu,\"tps\":%.1f}", (unsigned long)tk, tps);
    prevTicks = tk;
    snprintf(topic, sizeof(topic), "home/%s/odo", ROOM);
    mqtt.publish(topic, payload);
  }

  if (millis() - lastTele > 1000) {   // heartbeat telemetry
    lastTele = millis();
    vbat = VBAT_OK ? readVbat() : 0;  // refresh the cached battery voltage ~1Hz (0 = unknown: app/OLED show "--")
    static uint8_t camTick = 0;
    if (++camTick >= 5) { camTick = 0; WiFiClient c; camOK = c.connect(CAM_IP, 80, 150); c.stop(); }   // <=150ms block every 5s
    if (vbat < 3) vpct = -1;          // no pack (USB only / divider off)
    else { int p = battPct(vbat);     // hysteresis: ADC drift is ~±4%, move only on a real 5-point change
           if (vpct < 0 || abs(p - vpct) >= 5 || p == 0 || p == 100) vpct = p; }
    // cutoff: pack under 6.4V (3.2V/cell loaded) for 30 CONSECUTIVE raw readings — a wiggled wire or a
    // motor dip lasts seconds and must not trip it (one did, via the smoothed value). Skip the first minute
    // (ADC settles low after boot) and <5V (USB-only ~0.9, USB+pack ~4.5 — both bogus). Latched: a
    // resting pack bounces back up, which must not re-arm the motors.
    lowCount = (vbatRaw > 5 && vbatRaw < LOW_CUT_V) ? lowCount + 1 : 0;
    if (!lowBatt && millis() > 60000 && lowCount >= 30) {
      lowBatt = true; autoMode = false; stopAll(); curThrottle = "stop"; curSteer = "center";
    }
    snprintf(payload, sizeof(payload),
             "{\"throttle\":\"%s\",\"steer\":\"%s\",\"mode\":\"%s\",\"vbat\":%.2f,\"pct\":%d,\"low\":%s,\"rssi\":%d,\"cam\":%s}",
             curThrottle.c_str(), curSteer.c_str(), autoMode ? "auto" : "manual", vbat, vpct,
             lowBatt ? "true" : "false", WiFi.RSSI(), camOK ? "true" : "false");
    snprintf(topic, sizeof(topic), "home/%s/telemetry", ROOM);
    mqtt.publish(topic, payload);

    snprintf(payload, sizeof(payload), "%.2f", vbat);   // also its own topic for the dashboard
    snprintf(topic, sizeof(topic), "home/%s/battery", ROOM);
    mqtt.publish(topic, payload);

    snprintf(payload, sizeof(payload), "%.0f", aheadCm());
    snprintf(topic, sizeof(topic), "home/%s/distance", ROOM);
    mqtt.publish(topic, payload);
  }
}
