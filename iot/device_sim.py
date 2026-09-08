#!/usr/bin/env python3
"""Simulated smart-room device — stands in for an ESP32 until real hardware arrives.

It behaves exactly like firmware would over MQTT:
  * subscribes to command topics and actuates (light, fan, plug)
  * publishes sensor telemetry (temperature, humidity, motion) on a timer
  * republishes actuator state (retained) so new subscribers get current status

Swapping in a real ESP32 later means flashing firmware that uses these same
topics — nothing else in the system changes.

Run:  python3 ~/anish-ai/iot/device_sim.py
"""
import json
import math
import random
import time
import threading

import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
ROOM = "room"                      # topic namespace: home/<room>/...

# actuator state
state = {"light": "off", "fan": "off", "plug": "off"}
# sensor baselines (drift around these)
_t0 = time.time()


def on_connect(client, userdata, flags, rc, properties=None):
    print("[device] connected to broker rc=%s" % rc, flush=True)
    # listen for commands to each actuator
    for dev in state:
        client.subscribe(f"home/{ROOM}/{dev}/set")
    # announce we're online + publish current state (retained)
    client.publish(f"home/{ROOM}/status", "online", retain=True)
    for dev, val in state.items():
        client.publish(f"home/{ROOM}/{dev}", val, retain=True)


def on_message(client, userdata, msg):
    dev = msg.topic.split("/")[-2]           # home/room/<dev>/set
    cmd = msg.payload.decode().strip().lower()
    if dev in state and cmd in ("on", "off", "toggle"):
        state[dev] = ("on" if state[dev] == "off" else "off") if cmd == "toggle" else cmd
        client.publish(f"home/{ROOM}/{dev}", state[dev], retain=True)
        print(f"[device] {dev} -> {state[dev]}", flush=True)


def sensor_loop(client):
    """Publish realistic-looking telemetry every 2s."""
    while True:
        t = time.time() - _t0
        # temperature drifts around 24C with a slow sine + noise; the fan cools it
        temp = 24 + 1.5 * math.sin(t / 30) + random.uniform(-0.3, 0.3) - (1.2 if state["fan"] == "on" else 0)
        humidity = 55 + 6 * math.sin(t / 45) + random.uniform(-1, 1)
        motion = 1 if random.random() < 0.12 else 0     # occasional motion blips
        client.publish(f"home/{ROOM}/temp", round(temp, 1))
        client.publish(f"home/{ROOM}/humidity", round(humidity))
        client.publish(f"home/{ROOM}/motion", motion)
        client.publish(f"home/{ROOM}/telemetry", json.dumps({
            "temp": round(temp, 1), "humidity": round(humidity), "motion": motion,
            **state}))
        time.sleep(2)


def main():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="esp32-sim")
    except Exception:
        client = mqtt.Client(client_id="esp32-sim")     # older paho
    client.on_connect = on_connect
    client.on_message = on_message
    client.will_set(f"home/{ROOM}/status", "offline", retain=True)   # last-will if it dies
    client.connect(BROKER, PORT, 60)
    threading.Thread(target=sensor_loop, args=(client,), daemon=True).start()
    print("[device] simulated smart room online — publishing telemetry", flush=True)
    client.loop_forever()


if __name__ == "__main__":
    main()
