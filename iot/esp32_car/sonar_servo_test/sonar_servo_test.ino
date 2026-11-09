/*
 *  Scanning head: HC-SR04 on an SG90, looking away from whatever is closest.
 *  No WiFi, no MQTT, no motors.  Serial Monitor at 115200.
 *
 *    SG90  signal -> GPIO23   5V -> EXTERNAL supply (UBEC / power bank), GND -> common
 *    HC-SR04 Trig -> GPIO18   VCC -> 5V   GND -> GND
 *    HC-SR04 Echo -> [1k] -> GPIO19 -> [1.8k] -> GND   <-- divider is NOT optional,
 *                                                          Echo swings 5V, GPIOs die at 3.3V
 *
 *  The servo must NOT draw from the ESP's 5V pin: its surge browns the board into a
 *  reset loop.  Native ledc PWM, so no ESP32Servo library to install.
 */

#define SERVO_PIN 23
#define TRIG_PIN  18
#define ECHO_PIN  19

#define SERVO_MIN_US 500     // ponytail: nominal SG90 range; trim if the ends buzz
#define SERVO_MAX_US 2500

#define AVOID_CM   35.0      // closer than this counts as "something in front"
#define CENTER     90

static const int  SCAN[] = {40, CENTER, 140};      // left, ahead, right
static const int  NSCAN  = sizeof(SCAN) / sizeof(SCAN[0]);

// ---------- servo ----------
void servoWrite(int deg) {
  deg = constrain(deg, 0, 180);
  long us = map(deg, 0, 180, SERVO_MIN_US, SERVO_MAX_US);
  ledcWrite(SERVO_PIN, (us * 65535L) / 20000L);
}

// ---------- sonar ----------
float readDistance() {                       // cm, or -1 on no echo / out of range
  digitalWrite(TRIG_PIN, LOW);  delayMicroseconds(3);
  digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  unsigned long us = pulseIn(ECHO_PIN, HIGH, 30000UL);   // 30ms ~= 5m ceiling
  if (us == 0) return -1;
  float cm = us / 58.0;
  return (cm < 2 || cm > 400) ? -1 : cm;
}

float readDistanceStable() {                 // median of 3 — a single ping lies often enough
  float a = readDistance(); delay(60);
  float b = readDistance(); delay(60);
  float c = readDistance();
  if (a < 0 || b < 0 || c < 0) return (a > 0) ? a : (b > 0 ? b : c);
  return max(min(a, b), min(max(a, b), c));
}

// ---------- the behaviour ----------
// Point away from the nearest thing: an obstacle at 40 sends the head to 140, and
// vice versa.  Dead ahead has no mirror image, so pick whichever side has more room.
// Pure function of its inputs so selfTest() below can check it without hardware.
int chooseTarget(const int *ang, const float *dist, int n, float avoidCm) {
  int nearest = -1;
  for (int i = 0; i < n; i++)
    if (dist[i] > 0 && (nearest < 0 || dist[i] < dist[nearest])) nearest = i;

  if (nearest < 0 || dist[nearest] >= avoidCm) return CENTER;   // nothing close, look ahead

  if (ang[nearest] != CENTER) return 180 - ang[nearest];        // mirror it

  int roomiest = -1;                                            // blocked dead ahead
  for (int i = 0; i < n; i++)
    if (ang[i] != CENTER && dist[i] > 0 &&
        (roomiest < 0 || dist[i] > dist[roomiest])) roomiest = i;
  return roomiest < 0 ? CENTER : ang[roomiest];
}

void selfTest() {
  const int a[3] = {40, 90, 140};
  float d1[3] = {12, 200, 180};   // close on the left      -> look right
  float d2[3] = {180, 200, 15};   // close on the right     -> look left
  float d3[3] = {150, 10, 190};   // blocked ahead, right roomier -> look right
  float d4[3] = {150, 200, 190};  // all clear              -> centre
  float d5[3] = {-1, -1, -1};     // no echo at all         -> centre
  bool ok = chooseTarget(a, d1, 3, AVOID_CM) == 140
         && chooseTarget(a, d2, 3, AVOID_CM) == 40
         && chooseTarget(a, d3, 3, AVOID_CM) == 140
         && chooseTarget(a, d4, 3, AVOID_CM) == CENTER
         && chooseTarget(a, d5, 3, AVOID_CM) == CENTER;
  Serial.printf("selfTest: %s\n", ok ? "PASS" : "FAIL");
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n== scanning head: look away from the nearest thing ==");

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  selfTest();

  bool attached = ledcAttach(SERVO_PIN, 50, 16);
  Serial.printf("ledcAttach(GPIO%d, 50Hz, 16bit) -> %s\n", SERVO_PIN, attached ? "OK" : "FAILED");

  // one gentle move at boot — a big sweep here is what tips a weak supply into brownout
  servoWrite(CENTER);
  delay(600);
  Serial.printf("centred at %d. threshold %.0f cm.\n\n", CENTER, AVOID_CM);
}

void loop() {
  float d[NSCAN];

  for (int i = 0; i < NSCAN; i++) {
    servoWrite(SCAN[i]);
    delay(320);                              // let the horn arrive before pinging
    d[i] = readDistanceStable();
  }

  int target = chooseTarget(SCAN, d, NSCAN, AVOID_CM);

  Serial.printf("L%-6s A%-6s R%-6s -> %d deg%s\n",
    d[0] < 0 ? "  --" : (String(d[0], 0) + "cm").c_str(),
    d[1] < 0 ? "  --" : (String(d[1], 0) + "cm").c_str(),
    d[2] < 0 ? "  --" : (String(d[2], 0) + "cm").c_str(),
    target,
    target == CENTER ? "  (clear)" : "  (avoiding)");

  servoWrite(target);
  delay(700);                                // hold the new heading so it doesn't jitter
}
