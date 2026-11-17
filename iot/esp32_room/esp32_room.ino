/*  Nova Smart Room — ESP32 + DHT22 firmware
 *  FLASH WITH: --fqbn esp32:esp32:esp32:PartitionScheme=min_spiffs  (1.9 MB app; the default 1.3 MB is ~86% full)
 *  Reads real temperature/humidity and publishes to the SAME MQTT topics as
 *  device_sim.py, so dashboard.html and Nova (iot_status) light up unchanged.
 *
 *  Publishes (broker: your Mac's Mosquitto, anonymous):
 *    home/room/temp        e.g. "24.3"   (1 decimal, matches the sim)
 *    home/room/humidity    e.g. "55"     (integer)
 *    home/room/telemetry   {"temp":24.3,"humidity":55,"motion":0}
 *    home/room/status      "online" (retained) + last-will "offline"
 *
 *  Libraries (Arduino IDE -> Library Manager):
 *    - "PubSubClient" (Nick O'Leary)
 *    - "DHT sensor library" (Adafruit)  + "Adafruit Unified Sensor"
 *  Board: install "esp32 by Espressif" in Boards Manager, pick your ESP32 board.
 */
#include <WiFi.h>
#include <ESPmDNS.h>   // find the Mac by name -> DHCP IP drift no longer breaks the node
#include <PubSubClient.h>
#include <DHT.h>
#include <IRremoteESP8266.h>
#include <IRac.h>
#include <IRrecv.h>
#include <IRutils.h>   // learn mode: VS1838B OUT -> D14, GND -> G, VCC -> 3V (NOT 5V)      // LG AC over IR: D13 -> 1k -> 2N2222 base; 5V -> 47R -> IR LED -> collector
#include <ESP_I2S.h>    // table mic: INMP441 -> UDP :5005 on the hub (app/netmic.py), same format as esp32_bedmic
#include <WiFiUdp.h>
#include <ArduinoOTA.h>  // wireless updates: arduino-cli upload --port esp32-room.local (password = SECRET_OTA_PASS)
#include "secrets.h"   // copy secrets.h.example -> secrets.h and fill in your values (git-ignored)

// ---- credentials come from secrets.h (git-ignored) ----
const char* WIFI_SSID = SECRET_WIFI_SSID;      // must be 2.4GHz — ESP32 can't join 5GHz
const char* WIFI_PASS = SECRET_WIFI_PASS;
const char* BROKER_IP = SECRET_BROKER_IP;      // your Mac's LAN IP (may change on DHCP — see README)
// --------------------------------------------------------

const int   BROKER_PORT = 1883;
const char* BROKER_HOST = "nova-hub";            // always-on hub (old Air) mDNS name; IP above is the fallback
const char* ROOM        = "room";
const int   DHT_PIN     = 4;          // DATA -> GPIO4
#define     DHT_TYPE      DHT22       // change to DHT11 if that's your sensor
const unsigned long PUBLISH_MS = 2000;

// --- tuning knobs ---
const float SMOOTH      = 0.4;    // EMA weight per new reading: low-pass filter. 1.0=raw, 0.1=very smooth/slow.
const float TEMP_OFFSET = 0.0;    // sensor settled to ~real once self-heating stabilized; no offset needed
const float HUM_OFFSET  = 0.0;    // same, in %RH

// --- relay control (light / fan / plug). Set pins to your relay's IN channels. ---
const bool RELAY_ACTIVE_LOW = true;   // most blue opto-isolated relay boards are ACTIVE-LOW (IN=LOW => relay ON)
const int  LIGHT_PIN = 25;            // safe ESP32 output GPIOs (avoid 0,2,6-11,12,15)
const int  FAN_PIN   = 26;
const int  PLUG_PIN  = 27;
bool lightOn = false, fanOn = false, plugOn = false;

// --- PIR motion sensor (HC-SR501: VCC->5V, OUT->GPIO34, GND->GND). GPIO34 is input-only. ---
const int  PIR_PIN = 34;
bool motionState = false;

// --- LG AC over IR (replaces the Tuya cloud blaster). IR is one-way: we keep the state ourselves. ---
// Table mic (INMP441): VDD -> D23 S-pin (GPIO set HIGH = 3.3V; the one 3V pin feeds the DHT22, V-rail is 5V),
//   GND -> G, L/R -> G, SCK -> D18, WS -> D19, SD -> D21.
const bool MIC_ON = true;                  // false = no mic wired -> don't stream 32 KB/s of silence
const int  MIC_PWR = 23, MIC_SCK = 18, MIC_WS = 19, MIC_SD = 21, MIC_N = 512;   // 32 ms per packet @ 16 kHz
int GAIN_SHIFT = 14;                       // calibration knob (as bedmic): lower = louder, raise if speech clips
I2SClass i2s;
WiFiUDP udp;
IPAddress hubIP;                           // = the broker (hub), set by pickBroker
bool micOk = false;
int32_t micRaw[MIC_N];
uint8_t micPkt[16 + MIC_N * 2];
float micDc = 0;

const int IR_PIN = 13;
IRac irac(IR_PIN);
const uint16_t LG_OFF_RAW[60] = {2932,9783,437,1616,437,586,437,586,437,586,437,1616,437,586,437,586,437,586,437,1616,437,1616,437,586,437,586,437,586,437,586,437,586,437,586,437,586,437,586,437,586,437,586,437,586,437,1616,437,586,437,1616,437,586,437,586,437,586,437,1616,437,64464};   // learned via Tuya blaster
IRsend irsend(IR_PIN);            // exact learned LG2 frames: "send 88C0051"
stdAc::state_t acs;                 // power/mode/temp/fan sent as one full LG frame
const int IR_RX_PIN = 14;
IRrecv irrecv(IR_RX_PIN, 1024, 50, true);   // big buffer: AC frames are long
decode_results irres;

DHT dht(DHT_PIN, DHT_TYPE);
WiFiClient net;
PubSubClient mqtt(net);
char topic[48], payload[96];

int relayLevel(bool on) { return (on != RELAY_ACTIVE_LOW) ? HIGH : LOW; }  // invert for active-low boards

void applyAndReport(const char* dev, int pin, bool state) {
  digitalWrite(pin, relayLevel(state));
  char t[48]; snprintf(t, sizeof(t), "home/%s/%s", ROOM, dev);
  mqtt.publish(t, state ? "on" : "off", true);   // retained -> dashboard + Nova stay in sync
  Serial.printf("%s -> %s\n", dev, state ? "on" : "off");
}

void acSend() {
  irac.sendAc(acs, nullptr);
  const char* m = acs.mode == stdAc::opmode_t::kCool ? "cool" : acs.mode == stdAc::opmode_t::kHeat ? "heat" :
                  acs.mode == stdAc::opmode_t::kDry ? "dry" : acs.mode == stdAc::opmode_t::kFan ? "fan" : "auto";
  const char* f = acs.fanspeed == stdAc::fanspeed_t::kLow ? "low" : acs.fanspeed == stdAc::fanspeed_t::kMedium ? "mid" :
                  acs.fanspeed == stdAc::fanspeed_t::kHigh ? "high" : "auto";
  char t[48], v[48];
  snprintf(t, sizeof(t), "home/%s/ac", ROOM);
  snprintf(v, sizeof(v), "%s %d %s %s %s m%d", acs.power ? "on" : "off", (int)acs.degrees, m, f,
           acs.protocol == decode_type_t::LG2 ? "lg2" : "lg", (int)acs.model);
  mqtt.publish(t, v, true);
  Serial.printf("ac -> %s\n", v);
}

// home/room/ac/set: on | off | temp 24 | cool|heat|dry|fan|auto | speed low|mid|high|auto | lg | lg2
void onAc(String c) {
  if (c.startsWith("rawoff")) { int k = c.length() > 7 ? c.substring(7).toInt() : 38;   // "rawoff 36": test carrier kHz
    irrecv.disableIRIn(); irsend.sendRaw(LG_OFF_RAW, sizeof(LG_OFF_RAW)/2, k); irrecv.enableIRIn(); return; }
  if (c.startsWith("send ")) { irsend.sendLG2(strtoul(c.substring(5).c_str(), nullptr, 16), 28); return; }
  if (c.startsWith("nec ")) {   // "nec 07FD 10": NEC address (hex) + command (dec), e.g. the star projector
    int sp = c.indexOf(' ', 4);
    uint16_t a = strtoul(c.substring(4, sp).c_str(), nullptr, 16); uint8_t n = c.substring(sp + 1).toInt();
    irrecv.disableIRIn(); irsend.sendNEC(irsend.encodeNEC(a, n)); irrecv.enableIRIn(); return; }
  if      (c == "on")  acs.power = true;
  else if (c == "off") acs.power = false;
  else if (c.startsWith("temp ")) { int t = c.substring(5).toInt(); if (t < 16 || t > 30) return; acs.degrees = t; acs.power = true; }
  else if (c == "cool") acs.mode = stdAc::opmode_t::kCool;
  else if (c == "heat") acs.mode = stdAc::opmode_t::kHeat;
  else if (c == "dry")  acs.mode = stdAc::opmode_t::kDry;
  else if (c == "fan")  acs.mode = stdAc::opmode_t::kFan;
  else if (c == "auto") acs.mode = stdAc::opmode_t::kAuto;
  else if (c == "speed low")  acs.fanspeed = stdAc::fanspeed_t::kLow;
  else if (c == "speed mid")  acs.fanspeed = stdAc::fanspeed_t::kMedium;
  else if (c == "speed high") acs.fanspeed = stdAc::fanspeed_t::kHigh;
  else if (c == "speed auto") acs.fanspeed = stdAc::fanspeed_t::kAuto;
  else if (c == "lg")  acs.protocol = decode_type_t::LG;    // test knob: which LG IR protocol your AC speaks
  else if (c == "lg2") acs.protocol = decode_type_t::LG2;
  else if (c.startsWith("model ")) acs.model = c.substring(6).toInt();   // test knob: LG remote variant 1-4
  else return;
  acSend();
}

// home/room/<dev>/set  with payload on|off|toggle  (published by Nova + the dashboard)
void onMqtt(char* topic, byte* payload, unsigned int len) {
  char cmd[24] = {0}; memcpy(cmd, payload, len < 23 ? len : 23);
  String tp = topic, c = cmd;
  int a = tp.indexOf("/room/") + 6, b = tp.indexOf("/set");
  if (a < 6 || b < 0) return;
  String dev = tp.substring(a, b);
  if (dev == "ac") { c.trim(); c.toLowerCase(); onAc(c); return; }
  bool *st; int pin;
  if      (dev == "light") { st = &lightOn; pin = LIGHT_PIN; }
  else if (dev == "fan")   { st = &fanOn;   pin = FAN_PIN;   }
  else if (dev == "plug")  { st = &plugOn;  pin = PLUG_PIN;  }
  else return;
  if      (c == "on")     *st = true;
  else if (c == "off")    *st = false;
  else if (c == "toggle") *st = !*st;
  else return;
  applyAndReport(dev.c_str(), pin, *st);
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                 // disable modem-sleep: fixes the 100-400ms latency / dropped packets / rc=-2
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(400); Serial.print(".");
    if (++tries > 50) { Serial.println(" WiFi timeout -> reboot"); delay(200); ESP.restart(); }  // ~20s stuck -> self-heal
  }
  Serial.printf(" connected: %s\n", WiFi.localIP().toString().c_str());
}

// Resolve the Mac via mDNS ("<name>.local"); fall back to the hard-coded IP if mDNS fails.
void pickBroker() {
  static bool mdnsUp = false;
  if (!mdnsUp) mdnsUp = MDNS.begin("esp32-room");
  IPAddress ip = mdnsUp ? MDNS.queryHost(BROKER_HOST, 2000) : IPAddress();
  hubIP = ip != IPAddress() ? ip : (hubIP != IPAddress() ? hubIP : IPAddress());
  if (hubIP == IPAddress()) hubIP.fromString(BROKER_IP);
  if (ip != IPAddress()) { mqtt.setServer(ip, BROKER_PORT); Serial.printf("broker %s.local = %s\n", BROKER_HOST, ip.toString().c_str()); }
  else                   { mqtt.setServer(BROKER_IP, BROKER_PORT); Serial.printf("mDNS miss -> fallback %s\n", BROKER_IP); }
}

void connectMqtt() {
  int fails = 0;
  while (!mqtt.connected()) {
    if (WiFi.status() != WL_CONNECTED) connectWifi();   // make sure WiFi is up before trying the broker
    pickBroker();                                         // re-resolve every attempt: follows the Mac if its IP moved
    Serial.print("MQTT...");
    snprintf(topic, sizeof(topic), "home/%s/status", ROOM);
    // last-will: broker publishes "offline" (retained) if this device drops
    if (mqtt.connect("esp32-room", SECRET_MQTT_USER, SECRET_MQTT_PASS, topic, 0, true, "offline")) {
      mqtt.publish(topic, "online", true);      // retained: new subscribers see we're up
      snprintf(topic, sizeof(topic), "home/%s/+/set", ROOM);
      mqtt.subscribe(topic);                    // listen for light/fan/plug commands
      applyAndReport("light", LIGHT_PIN, lightOn);   // re-announce current states on (re)connect
      applyAndReport("fan",   FAN_PIN,   fanOn);
      applyAndReport("plug",  PLUG_PIN,  plugOn);
      Serial.println(" connected");
    } else {
      fails++;
      Serial.printf(" failed rc=%d (fail %d), retry in 2s\n", mqtt.state(), fails);
      // SELF-HEAL: a stale WiFi association is the usual cause of the rc=-2 loop that only a reset fixed.
      if (fails == 5)  { Serial.println("  -> re-associating WiFi"); WiFi.disconnect(); delay(500); connectWifi(); }
      if (fails >= 15) { Serial.println("  -> rebooting to recover"); delay(300); ESP.restart(); }  // ~30s stuck -> reboot
      delay(2000);
    }
  }
}

void streamMic() {
  size_t got = i2s.readBytes((char*)micRaw, sizeof(micRaw));
  int n = got / 4;
  if (n <= 0) return;
  int16_t* out = (int16_t*)(micPkt + 16);
  for (int i = 0; i < n; i++) {
    float s = (float)(micRaw[i] >> 8);        // 24-bit sample in the top of the 32-bit slot
    micDc += 0.001f * (s - micDc);            // DC blocker
    out[i] = (int16_t)constrain((s - micDc) / (float)(1 << (GAIN_SHIFT - 8)), -32768.0f, 32767.0f);
  }
  udp.beginPacket(hubIP, 5005);
  udp.write(micPkt, 16 + n * 2);
  udp.endPacket();
}

void setup() {
  irsend.begin();
  Serial.begin(115200);
  dht.begin();
  pinMode(PIR_PIN, INPUT);                      // PIR output is a driven 3.3V digital signal
  irrecv.enableIRIn(); pinMode(IR_RX_PIN, INPUT_PULLUP);   // pull-up: no receiver wired = no noise "codes"
  acs.protocol = decode_type_t::LG; acs.model = -1; acs.celsius = true; acs.degrees = 24; acs.power = false;
  acs.mode = stdAc::opmode_t::kCool; acs.fanspeed = stdAc::fanspeed_t::kAuto;
  acs.swingv = stdAc::swingv_t::kOff; acs.swingh = stdAc::swingh_t::kOff;
  pinMode(LIGHT_PIN, OUTPUT); pinMode(FAN_PIN, OUTPUT); pinMode(PLUG_PIN, OUTPUT);
  digitalWrite(LIGHT_PIN, relayLevel(false));   // start all relays OFF (before anything can switch)
  digitalWrite(FAN_PIN,   relayLevel(false));
  digitalWrite(PLUG_PIN,  relayLevel(false));
  mqtt.setCallback(onMqtt);
  if (MIC_ON) {                                 // a mic problem must never take the room node (AC, fan, sensors) down
    pinMode(MIC_PWR, OUTPUT); digitalWrite(MIC_PWR, HIGH); delay(100);   // power the mic (~1.4 mA) before I2S starts
    memcpy(micPkt, SECRET_MIC_KEY, 16);
    i2s.setPins(MIC_SCK, MIC_WS, -1, MIC_SD);
    micOk = i2s.begin(I2S_MODE_STD, 16000, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT);
    Serial.println(micOk ? "table mic on" : "table mic: I2S init failed -> mic off, rest of the node runs");
  }
  connectWifi();
  connectMqtt();
  ArduinoOTA.setHostname("esp32-room");              // also its mDNS name; must match the MDNS.begin name
  ArduinoOTA.setPassword(SECRET_OTA_PASS);
  ArduinoOTA.setMdnsEnabled(false);             // the sketch already runs mDNS under this name
  ArduinoOTA.begin();
}

void loop() {
  ArduinoOTA.handle();                          // wireless update check (~free when idle)
  if (irrecv.decode(&irres)) {                  // a remote pressed near the receiver -> report what it sent
    if (irres.decode_type != decode_type_t::UNKNOWN || irres.rawlen > 60) {
      char t[48], v[160];
      snprintf(t, sizeof(t), "home/%s/ir/rx", ROOM);
      snprintf(v, sizeof(v), "%s 0x%s %d bits rawlen=%d", typeToString(irres.decode_type).c_str(),
               uint64ToString(irres.value, 16).c_str(), irres.bits, irres.rawlen);
      mqtt.publish(t, v);
      Serial.println(resultToSourceCode(&irres));  // full raw timings on USB serial for unknown protocols
    }
    irrecv.resume();
  }
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  // Motion: read every loop (not just every 2s) and publish the instant it changes -> instant HUD/Nova update.
  bool m = digitalRead(PIR_PIN) == HIGH;
  if (m != motionState) {
    motionState = m;
    snprintf(topic, sizeof(topic), "home/%s/motion", ROOM);
    mqtt.publish(topic, m ? "1" : "0", true);   // retained so new subscribers get the current state
    Serial.printf("motion -> %d\n", m);
  }

  if (micOk && hubIP != IPAddress()) streamMic();   // blocks ~32 ms per packet: also paces this loop

  static unsigned long last = 0;
  if (millis() - last < PUBLISH_MS) return;
  last = millis();

  float tRaw = dht.readTemperature();  // Celsius
  float hRaw = dht.readHumidity();
  if (isnan(tRaw) || isnan(hRaw)) {    // DHT read can occasionally fail — skip, don't publish garbage
    Serial.println("DHT read failed, skipping");
    return;
  }
  tRaw += TEMP_OFFSET;                 // calibration correction (see knobs at top)
  hRaw += HUM_OFFSET;
  // exponential moving average — smooths jitter across the 2s readings without faking extra samples
  static float t = NAN, h = NAN;
  t = isnan(t) ? tRaw : SMOOTH * tRaw + (1 - SMOOTH) * t;
  h = isnan(h) ? hRaw : SMOOTH * hRaw + (1 - SMOOTH) * h;
  int hum = (int) round(h);

  snprintf(topic, sizeof(topic), "home/%s/temp", ROOM);
  snprintf(payload, sizeof(payload), "%.1f", t);
  mqtt.publish(topic, payload);

  snprintf(topic, sizeof(topic), "home/%s/humidity", ROOM);
  snprintf(payload, sizeof(payload), "%d", hum);
  mqtt.publish(topic, payload);

  snprintf(topic, sizeof(topic), "home/%s/telemetry", ROOM);
  snprintf(payload, sizeof(payload), "{\"temp\":%.1f,\"humidity\":%d,\"motion\":%d}", t, hum, motionState ? 1 : 0);
  mqtt.publish(topic, payload);

  Serial.printf("published  temp=%.1fC  humidity=%d%%  motion=%d\n", t, hum, motionState);
}
