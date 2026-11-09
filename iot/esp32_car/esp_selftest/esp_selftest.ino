// ESP32 health check: prints every ADC1 pin (mV) twice a second + WiFi scan count once.
// Touch a pin to GND (expect ~0-150), to 3V3 (expect ~3100+), or to the battery divider middle
// (expect the meter's value). A pin stuck near 1250 mV whatever you touch = clamped/damaged.
#include <WiFi.h>
const int PINS[] = {32, 33, 34, 35, 36, 39};
void setup() {
  Serial.begin(115200);
  for (int p : PINS) analogSetPinAttenuation(p, ADC_11db);
  WiFi.mode(WIFI_STA);
  Serial.printf("\nWiFi scan: %d networks (0 = radio problem)\n", WiFi.scanNetworks());
}
void loop() {
  for (int p : PINS) Serial.printf("G%d:%4lu  ", p, (unsigned long)analogReadMilliVolts(p));
  Serial.println();
  delay(500);
}
