/*  Jarvis Smart Room — ESP32 + DHT22 firmware
 *  Reads real temperature/humidity and publishes to the SAME MQTT topics as
 *  device_sim.py, so dashboard.html and Jarvis (iot_status) light up unchanged.
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
#include <PubSubClient.h>
#include <DHT.h>
#include "secrets.h"   // copy secrets.h.example -> secrets.h and fill in your values (git-ignored)

// ---- credentials come from secrets.h (git-ignored) ----
const char* WIFI_SSID = SECRET_WIFI_SSID;      // must be 2.4GHz — ESP32 can't join 5GHz
const char* WIFI_PASS = SECRET_WIFI_PASS;
const char* BROKER_IP = SECRET_BROKER_IP;      // your Mac's LAN IP (may change on DHCP — see README)
// --------------------------------------------------------

const int   BROKER_PORT = 1883;
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

DHT dht(DHT_PIN, DHT_TYPE);
WiFiClient net;
PubSubClient mqtt(net);
char topic[48], payload[96];

int relayLevel(bool on) { return (on != RELAY_ACTIVE_LOW) ? HIGH : LOW; }  // invert for active-low boards

void applyAndReport(const char* dev, int pin, bool state) {
  digitalWrite(pin, relayLevel(state));
  char t[48]; snprintf(t, sizeof(t), "home/%s/%s", ROOM, dev);
  mqtt.publish(t, state ? "on" : "off", true);   // retained -> dashboard + Jarvis stay in sync
  Serial.printf("%s -> %s\n", dev, state ? "on" : "off");
}

// home/room/<dev>/set  with payload on|off|toggle  (published by Jarvis + the dashboard)
void onMqtt(char* topic, byte* payload, unsigned int len) {
  char cmd[12] = {0}; memcpy(cmd, payload, len < 11 ? len : 11);
  String tp = topic, c = cmd;
  int a = tp.indexOf("/room/") + 6, b = tp.indexOf("/set");
  if (a < 6 || b < 0) return;
  String dev = tp.substring(a, b);
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

void connectMqtt() {
  mqtt.setServer(BROKER_IP, BROKER_PORT);
  int fails = 0;
  while (!mqtt.connected()) {
    if (WiFi.status() != WL_CONNECTED) connectWifi();   // make sure WiFi is up before trying the broker
    Serial.print("MQTT...");
    snprintf(topic, sizeof(topic), "home/%s/status", ROOM);
    // last-will: broker publishes "offline" (retained) if this device drops
    if (mqtt.connect("esp32-room", nullptr, nullptr, topic, 0, true, "offline")) {
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

void setup() {
  Serial.begin(115200);
  dht.begin();
  pinMode(PIR_PIN, INPUT);                      // PIR output is a driven 3.3V digital signal
  pinMode(LIGHT_PIN, OUTPUT); pinMode(FAN_PIN, OUTPUT); pinMode(PLUG_PIN, OUTPUT);
  digitalWrite(LIGHT_PIN, relayLevel(false));   // start all relays OFF (before anything can switch)
  digitalWrite(FAN_PIN,   relayLevel(false));
  digitalWrite(PLUG_PIN,  relayLevel(false));
  mqtt.setCallback(onMqtt);
  connectWifi();
  connectMqtt();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  // Motion: read every loop (not just every 2s) and publish the instant it changes -> instant HUD/Jarvis update.
  bool m = digitalRead(PIR_PIN) == HIGH;
  if (m != motionState) {
    motionState = m;
    snprintf(topic, sizeof(topic), "home/%s/motion", ROOM);
    mqtt.publish(topic, m ? "1" : "0", true);   // retained so new subscribers get the current state
    Serial.printf("motion -> %d\n", m);
  }

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
