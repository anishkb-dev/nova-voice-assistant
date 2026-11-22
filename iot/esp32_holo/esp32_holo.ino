/* Nova hologram: 1.28" round GC9A01 under 45° acrylic (Pepper's ghost, ~/Desktop/hologram).
 * Draws Nova's orb; black = invisible in the glass, so only the glow floats.
 * MQTT (room login, home/room/# only): home/room/holo/set = idle | listen | think | speak | off
 *   status retained on home/room/holo ("online"/"offline" + current mode on home/room/holo/mode).
 *   Any mode but idle/off falls back to idle after 30 s without a new message.
 * Wiring (spare Robocraze ESP32, NOT the room node): VCC->3V3 GND->GND SCL->18 SDA->23 DC->2 CS->5 RST->4 BLK->15
 * Build: arduino-cli compile --fqbn esp32:esp32:esp32 esp32_holo   (secrets.h = copy of esp32_room/secrets.h)
 * OTA:   espota.py -i esp32-holo.local -p 3232 (password = SECRET_OTA_PASS) */
#include <WiFi.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <ArduinoOTA.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_GC9A01A.h>
#include "secrets.h"

#define TFT_DC 2
#define TFT_CS 5
#define TFT_RST 4
#define TFT_BLK 15
const int ORB = 120;                 // canvas size (px); orb drawn into it, pushed at the screen centre
const int MAX_R = 54;                // calibration knob: orb radius at full size (screen is 240 px wide)
const uint32_t MODE_TIMEOUT_MS = 30000;

Adafruit_GC9A01A tft(TFT_CS, TFT_DC, TFT_RST);   // hardware SPI: SCK 18, MOSI 23
GFXcanvas16 canvas(ORB, ORB);
WiFiClient net;
PubSubClient mqtt(net);
String mode = "idle";
uint32_t modeAt = 0;

uint16_t rgb(float r, float g, float b) {        // 0..1 floats -> RGB565
  auto c = [](float v) { return v < 0 ? 0 : v > 1 ? 1 : v; };
  return ((uint16_t)(c(r) * 31) << 11) | ((uint16_t)(c(g) * 63) << 5) | (uint16_t)(c(b) * 31);
}

// Glowing ball: rings from outside in, brightness rising toward a hot core.
void drawOrb(float radius, float bright, float r, float g, float b) {
  canvas.fillScreen(0);
  for (int k = (int)radius; k > 0; k -= 2) {
    float t = 1.0f - (float)k / radius;           // 0 at the rim, 1 at the centre
    float v = bright * (0.15f + 0.85f * t * t);
    canvas.fillCircle(ORB / 2, ORB / 2, k, rgb(r * v + t * t * 0.5f * v, g * v + t * t * 0.5f * v, b * v + t * t * 0.5f * v));
  }
}

void render(uint32_t ms) {
  float s = ms / 1000.0f;
  if (mode == "off") return;
  if (mode == "listen") {
    drawOrb(MAX_R * (0.92f + 0.08f * sinf(s * 6)), 1.0f, 0.1f, 0.5f, 1.0f);            // big, bright blue
  } else if (mode == "think") {
    drawOrb(MAX_R * 0.55f, 0.7f, 1.0f, 0.6f, 0.1f);                                     // amber core + orbiting dots
    for (int i = 0; i < 3; i++) {
      float a = s * 3 + i * 2.094f;
      canvas.fillCircle(ORB / 2 + cosf(a) * 44, ORB / 2 + sinf(a) * 44, 5, rgb(1, 0.7f, 0.2f));
    }
  } else if (mode == "speak") {
    float j = 0.75f + 0.25f * fabsf(sinf(s * 11) * sinf(s * 4.3f));                   // speech-like flutter
    drawOrb(MAX_R * j, 1.0f, 0.3f, 0.9f, 1.0f);
  } else {                                                                              // idle: slow breathing cyan
    drawOrb(MAX_R * (0.62f + 0.06f * sinf(s * 1.4f)), 0.55f + 0.15f * sinf(s * 1.4f), 0.0f, 0.75f, 0.9f);
  }
  tft.drawRGBBitmap(120 - ORB / 2, 120 - ORB / 2, canvas.getBuffer(), ORB, ORB);
}

void setMode(const String& m) {
  if (m != "idle" && m != "listen" && m != "think" && m != "speak" && m != "off") return;   // ignore junk
  mode = m; modeAt = millis();
  digitalWrite(TFT_BLK, m == "off" ? LOW : HIGH);
  if (m == "off") tft.fillScreen(0);
  mqtt.publish("home/room/holo/mode", m.c_str(), true);
}

void onMsg(char* topic, byte* p, unsigned int n) {
  String m; for (unsigned i = 0; i < n && i < 12; i++) m += (char)tolower(p[i]);
  m.trim(); setMode(m);
}

void connectMqtt() {
  static uint32_t lastTry = 0;
  if (mqtt.connected() || millis() - lastTry < 5000) return;   // non-blocking: the orb keeps animating
  lastTry = millis();
  IPAddress ip = MDNS.queryHost("nova-hub", 1500);
  if (ip == IPAddress()) ip.fromString(SECRET_BROKER_IP);
  mqtt.setServer(ip, 1883);
  if (mqtt.connect("esp32-holo", SECRET_MQTT_USER, SECRET_MQTT_PASS, "home/room/holo", 0, true, "offline")) {
    mqtt.publish("home/room/holo", "online", true);
    mqtt.subscribe("home/room/holo/set");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(TFT_BLK, OUTPUT); digitalWrite(TFT_BLK, HIGH);
  tft.begin(40000000);
  tft.fillScreen(0);
  WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true);
  WiFi.begin(SECRET_WIFI_SSID, SECRET_WIFI_PASS);
  MDNS.begin("esp32-holo");
  mqtt.setCallback(onMsg);
  mqtt.setKeepAlive(60);
  ArduinoOTA.setHostname("esp32-holo");
  ArduinoOTA.setPassword(SECRET_OTA_PASS);
  ArduinoOTA.setMdnsEnabled(false);
  ArduinoOTA.begin();
}

void loop() {
  ArduinoOTA.handle();
  if (WiFi.status() == WL_CONNECTED) { connectMqtt(); mqtt.loop(); }
  if (mode != "idle" && mode != "off" && millis() - modeAt > MODE_TIMEOUT_MS) setMode("idle");
  render(millis());
  delay(16);                                     // ~30-60 fps; the SPI push is the real limit
}
