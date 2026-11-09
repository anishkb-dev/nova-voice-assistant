// TCRT5000 bench test: prints D0 (0 = sees something) and A0 (raw IR level) 5x/s.
// Module VCC -> 3V3 (NOT 5V: A0 swings up to VCC), GND -> GND, D0 -> GPIO35, A0 -> GPIO34.
void setup() { Serial.begin(115200); pinMode(35, INPUT); }
void loop() {
  Serial.printf("D0=%d  A0=%4d\n", digitalRead(35), analogRead(34));
  delay(200);
}
