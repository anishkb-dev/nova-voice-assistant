/*  Nova Crawler — WOKWI SIMULATION
 *  ---------------------------------
 *  Tests the crawler "brain" in the browser: the OLED face + steer/throttle
 *  logic + servo scan-sweep + HC-SR04 auto-stop — WITHOUT the L298N/WiFi/MQTT
 *  (Wokwi's cloud can't reach your LAN broker, so inputs are local instead):
 *    Potentiometer  -> steering angle (left / center / right)
 *    Green button   -> hold = forward
 *    Red button     -> hold = back
 *    Servo (GPIO5)  -> sweeps like the Phase-B scanning sonar head
 *    HC-SR04        -> distance; auto-stops "forward" under ~15cm
 *
 *  Libraries (Wokwi auto-installs from libraries.txt):
 *    Adafruit SSD1306, Adafruit GFX, ESP32Servo
 */
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ESP32Servo.h>

#define OLED_ADDR 0x3C
Adafruit_SSD1306 oled(128, 64, &Wire, -1);
Servo scanServo;

const int POT = 34, BTN_FWD = 25, BTN_BACK = 26;   // inputs
const int SERVO_PIN = 5, TRIG = 18, ECHO = 19;     // outputs / sonar

String curThrottle = "stop", curSteer = "center";
unsigned long lastActive = 0, nextBlink = 0, blinkEnd = 0, lastFace = 0, lastScan = 0, lastServo = 0;
int  servoAngle = 90, servoDir = 1;
long distanceCm = 100;

// --- the cute robot smiley (same logic as the real firmware) ---
void showOLED() {
  unsigned long now = millis();
  if (now > nextBlink) { blinkEnd = now + 150; nextBlink = now + 2600 + random(2400); }
  bool blink = now < blinkEnd;
  bool fwd = (curThrottle == "forward"), rev = (curThrottle == "back");
  bool idle = (curThrottle == "stop" && now - lastActive > 8000);
  int  dx = (curSteer == "left") ? -8 : (curSteer == "right") ? 8 : 0;

  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE); oled.setTextSize(1);
  oled.setCursor(0, 0); oled.print("ONLINE");
  String go = idle ? "ZZZ" : fwd ? "FWD" : rev ? "REV" : "IDLE";
  if      (curSteer == "left")  go += " <";
  else if (curSteer == "right") go += " >";
  oled.setCursor(128 - go.length() * 6, 0); oled.print(go);

  const int ew = 20;
  int ch = fwd ? 20 : idle ? 8 : 26;
  int cy = idle ? 42 : 35;
  int h  = blink ? 4 : ch, y = cy - h / 2;
  oled.fillRoundRect(36 + dx, y, ew, h, 8, SSD1306_WHITE);
  oled.fillRoundRect(72 + dx, y, ew, h, 8, SSD1306_WHITE);
  if (!blink && !idle) {
    int m = rev ? -1 : 1, depth = fwd ? 5 : 3, sx = 48 + dx, sy = 56;
    oled.drawLine(sx,      sy,             sx + 6,  sy + depth * m, SSD1306_WHITE);
    oled.drawLine(sx + 6,  sy + depth * m, sx + 22, sy + depth * m, SSD1306_WHITE);
    oled.drawLine(sx + 22, sy + depth * m, sx + 28, sy,            SSD1306_WHITE);
  }
  oled.setCursor(92, 56); oled.print(distanceCm); oled.print("cm");
  oled.display();
}

long readSonar() {
  digitalWrite(TRIG, LOW);  delayMicroseconds(2);
  digitalWrite(TRIG, HIGH); delayMicroseconds(10); digitalWrite(TRIG, LOW);
  long us = pulseIn(ECHO, HIGH, 30000);
  return us ? us / 58 : 400;
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN_FWD, INPUT_PULLUP);
  pinMode(BTN_BACK, INPUT_PULLUP);
  pinMode(TRIG, OUTPUT); pinMode(ECHO, INPUT);
  Wire.begin(21, 22);
  oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
  scanServo.attach(SERVO_PIN);
  Serial.println("Nova Crawler SIM ready — pot=steer, green=fwd, red=back");
}

void loop() {
  unsigned long now = millis();

  // steering from the pot
  int steer = map(analogRead(POT), 0, 4095, -100, 100);
  curSteer = (steer < -12) ? "left" : (steer > 12) ? "right" : "center";

  // throttle from the buttons (active LOW)
  bool f = !digitalRead(BTN_FWD), b = !digitalRead(BTN_BACK);
  String t = f ? "forward" : b ? "back" : "stop";

  // sonar + obstacle auto-stop
  if (now - lastScan > 200) { lastScan = now; distanceCm = readSonar(); }
  if (t == "forward" && distanceCm < 15) { t = "stop"; Serial.println("AUTO-STOP: obstacle < 15cm"); }

  if (t != curThrottle) {
    curThrottle = t;
    Serial.printf("throttle=%s  steer=%s  dist=%ldcm\n", t.c_str(), curSteer.c_str(), distanceCm);
  }
  if (t != "stop" || curSteer != "center") lastActive = now;

  // servo sweep 45..135 (the scanning-sonar head)
  if (now - lastServo > 20) {
    lastServo = now;
    servoAngle += servoDir;
    if (servoAngle >= 135 || servoAngle <= 45) servoDir = -servoDir;
    scanServo.write(servoAngle);
  }

  if (now - lastFace > 100) { lastFace = now; showOLED(); }
}
