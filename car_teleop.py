#!/usr/bin/env python3
"""
Nova Crawler — WASD keyboard teleop.
Run in a REAL terminal (Terminal.app):  python3 ~/anish-ai/car_teleop.py

  W forward   S back     X / space  stop
  A left      D right     C  center (straighten)
  1..9 speed (10-90%)     0  100%
  Q quit  (auto-stops on exit; 3s idle failsafe stops the motors)
"""
import sys, tty, termios, select, time
import paho.mqtt.client as mqtt

BROKER = "localhost"   # runs on the broker Mac — an IP here drifts with DHCP
try:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except Exception:
    c = mqtt.Client()
c.connect(BROKER, 1883, 5)
c.loop_start()

def pub(topic, val):
    c.publish(f"home/car/{topic}", val)

print(__doc__)
throttle, steer = "stop", "center"

def status():
    sys.stdout.write(f"\r  throttle: {throttle:<7}  steer: {steer:<6}   (Q to quit)   ")
    sys.stdout.flush()

fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
last = time.time()
status()
try:
    tty.setcbreak(fd)
    while True:
        r, _, _ = select.select([sys.stdin], [], [], 0.1)
        if r:
            k = sys.stdin.read(1).lower()
            last = time.time()
            if   k == "q": break
            elif k == "w": throttle = "forward"; pub("throttle", "forward")
            elif k == "s": throttle = "back";    pub("throttle", "back")
            elif k in ("x", " "): throttle = "stop"; pub("throttle", "stop")
            elif k == "a": steer = "left";   pub("steer", "left")
            elif k == "d": steer = "right";  pub("steer", "right")
            elif k == "c": steer = "center"; pub("steer", "center")
            elif k in "1234567890":
                pct = 100 if k == "0" else int(k) * 10
                pub("speed", str(pct))
            status()
        elif throttle != "stop" and time.time() - last > 3:   # idle failsafe
            throttle = "stop"; pub("throttle", "stop"); status()
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
    pub("throttle", "stop"); pub("steer", "center")
    time.sleep(0.2)
    c.loop_stop()
    print("\nstopped. bye, sir.")
