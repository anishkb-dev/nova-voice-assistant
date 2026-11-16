// Nova bedside mic: INMP441 (I2S) -> 16 kHz mono int16 -> UDP -> hub (app/netmic.py).
// Wiring (6 F-F jumpers, keep them short): VDD->3V3 (NOT 5V), GND->GND, L/R->GND,
//   SCK->GPIO33, WS->GPIO25, SD->GPIO32. Power: USB from a decent 5V charger.
// Board: esp32:esp32:esp32 (core 3.x). Copy secrets.h.example -> secrets.h first.
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESPmDNS.h>
#include <ESP_I2S.h>
#include "secrets.h"

const int PIN_SCK = 33, PIN_WS = 25, PIN_SD = 32;
const int RATE = 16000, N = 512;            // 32 ms per packet
const int PORT = 5005;
const char* HUB_HOST = "nova-hub";          // mDNS; SECRET_HUB_IP is the fallback
int GAIN_SHIFT = 14;                        // calibration knob: 24-bit sample >> 14 = +12 dB over plain 16-bit.
                                            // Lower = louder (13 = +18 dB). Raise if speech clips.

I2SClass i2s;
WiFiUDP udp;
IPAddress hub;
void findHub();
int32_t raw[N];
uint8_t pkt[16 + N * 2];                    // 16-byte key, then int16 little-endian samples
float dc = 0;

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                     // modem-sleep = stutter / dropped audio
  WiFi.setAutoReconnect(true);
  WiFi.begin(SECRET_WIFI_SSID, SECRET_WIFI_PASS);
  for (int t = 0; WiFi.status() != WL_CONNECTED; t++) {
    delay(400); Serial.print(".");
    if (t > 50) ESP.restart();              // ~20 s stuck -> self-heal
  }
  Serial.printf(" wifi %s\n", WiFi.localIP().toString().c_str());
  findHub();
}

// Booting while the hub was down left us streaming to a dead fallback IP for hours (2026-11-16):
// re-resolve every 5 min, and keep the last good address when a lookup fails.
void findHub() {
  static bool md = false;
  if (!md) md = MDNS.begin("esp32-bedmic");
  IPAddress ip = md ? MDNS.queryHost(HUB_HOST, 2000) : IPAddress();
  if (ip != IPAddress()) hub = ip;
  else if (hub == IPAddress()) hub.fromString(SECRET_HUB_IP);
  Serial.printf("hub = %s\n", hub.toString().c_str());
}

void setup() {
  Serial.begin(115200);
  memcpy(pkt, SECRET_MIC_KEY, 16);
  i2s.setPins(PIN_SCK, PIN_WS, -1, PIN_SD);
  if (!i2s.begin(I2S_MODE_STD, RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT)) {
    Serial.println("I2S init failed -> check wiring"); delay(2000); ESP.restart();
  }
  connectWifi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  static uint32_t lastFind = 0;
  if (millis() - lastFind > 300000) { lastFind = millis(); findHub(); }   // ~2 s gap in audio every 5 min
  size_t got = i2s.readBytes((char*)raw, sizeof(raw));
  int n = got / 4;
  int16_t* out = (int16_t*)(pkt + 16);
  for (int i = 0; i < n; i++) {
    float s = (float)(raw[i] >> 8);         // 24-bit signed sample sits in the top of the 32-bit slot
    dc += 0.001f * (s - dc);                // DC blocker: the INMP441 has a small offset
    float v = (s - dc) / (float)(1 << (GAIN_SHIFT - 8));
    out[i] = (int16_t)constrain(v, -32768.0f, 32767.0f);
  }
  udp.beginPacket(hub, PORT);
  udp.write(pkt, 16 + n * 2);
  udp.endPacket();
}
