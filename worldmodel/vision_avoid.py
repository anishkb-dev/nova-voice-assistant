"""Camera -> obstacle hint for the car's autonomy.

Pulls frames from the car's ESP32-CAM, scores how cluttered the left / centre / right of the view is
(0 = clear floor, 99 = wall), and publishes "l,c,r" to home/car/vision ~4x/s. The car turns toward the
lower score and treats a high centre score as blocked (see autoTick in esp32_car.ino).

    python3 vision_avoid.py [cam_ip]        # default 192.168.68.107
    python3 vision_avoid.py --selftest

Score = how different each third is from the floor patch right in front of the car, plus its edge
density. ponytail: plain heuristic, no ML — fooled by patterned rugs and by glare; GAIN/EDGE are the
calibration knobs (watch the printed scores while pointing the car at open floor vs a wall).
"""
import sys, time, urllib.request
import numpy as np, cv2

GAIN, EDGE = 1.6, 0.6        # scale the floor-difference and edge terms into 0-99


def scores(gray):
    g = cv2.resize(gray, (120, 120)).astype(np.float32)
    floor = np.median(g[100:120, 45:75])                 # patch just ahead of the bumper = "what floor looks like"
    band = g[45:100]                                     # middle of the view: where obstacles show up
    edges = np.abs(cv2.Sobel(band, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(band, cv2.CV_32F, 0, 1))
    out = []
    for third in range(3):
        sl = slice(third * 40, third * 40 + 40)
        diff = np.mean(np.abs(band[:, sl] - floor))
        out.append(int(min(99, GAIN * diff + EDGE * np.mean(edges[:, sl]))))
    return out                                           # [left, centre, right]


def selftest():
    img = np.full((240, 240), 120, np.uint8)             # flat floor everywhere
    assert max(scores(img)) < 10, scores(img)
    img[60:200, 170:240] = 230                           # bright box on the right
    l, c, r = scores(img)
    assert r > 50 and r > l and r > c, (l, c, r)
    print("selftest ok", (l, c, r))


def main(cam):
    import paho.mqtt.client as mqtt
    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="vision-avoid")
    cli.connect("localhost", 1883); cli.loop_start()
    url = f"http://{cam}/capture"
    while True:
        try:
            buf = urllib.request.urlopen(url, timeout=2).read()
            gray = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_GRAYSCALE)
            l, c, r = scores(gray)
            cli.publish("home/car/vision", f"{l},{c},{r}")
            print(f"\rL {l:2d}  C {c:2d}  R {r:2d}   ", end="", flush=True)
        except Exception as e:                           # cam rebooting / DHCP moved: keep trying, car falls back to sonar
            print(f"\rcam {cam}: {e}            ", end="", flush=True)
            time.sleep(1)
        time.sleep(0.05)


if __name__ == "__main__":
    if "--selftest" in sys.argv: selftest()
    else: main(sys.argv[1] if len(sys.argv) > 1 else "192.168.68.107")
