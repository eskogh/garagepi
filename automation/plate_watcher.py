import os
import time
import io

try:
    import requests
except Exception:
    requests = None

try:
    import cv2
except Exception:
    cv2 = None

RTSP_URL = os.getenv("RTSP_URL")  # e.g. rtsp://user:pass@ip:554/stream
PLATE_API_TOKEN = os.getenv("PLATE_API_TOKEN")  # Plate Recognizer API key
APPROVED_PLATES = set(
    p.strip().upper() for p in os.getenv("APPROVED_PLATES", "").split(",") if p.strip()
)

GARAGEPI_URL = os.getenv("GARAGEPI_URL", "http://localhost:5000")
GARAGEPI_TOKEN = os.getenv("GARAGEPI_TOKEN", "")
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.85"))
SAMPLE_SECS = float(os.getenv("SAMPLE_SECS", "1.5"))
OPEN_COOLDOWN_S = float(os.getenv("OPEN_COOLDOWN_S", "30"))

last_open_ts = 0.0


def authorized_headers():
    return {"Authorization": f"Bearer {GARAGEPI_TOKEN}"} if GARAGEPI_TOKEN else {}


def take_snapshot(rtsp):
    if cv2 is None:
        raise RuntimeError("OpenCV (cv2) is required for RTSP snapshots")
    cap = cv2.VideoCapture(rtsp)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    # JPEG encode
    ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return None
    return jpg.tobytes()


def alpr_lookup(jpeg_bytes):
    if requests is None:
        raise RuntimeError("requests is required for Plate Recognizer calls")
    url = "https://api.platerecognizer.com/v1/plate-reader/"
    headers = {"Authorization": f"Token {PLATE_API_TOKEN}"}
    files = {"upload": ("frame.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
    resp = requests.post(url, headers=headers, files=files, timeout=10)
    resp.raise_for_status()
    return resp.json()


def door_status():
    if requests is None:
        return "Unknown"
    try:
        r = requests.get(f"{GARAGEPI_URL}/status", timeout=4)
        return r.json().get("status", "Unknown")
    except Exception:
        return "Unknown"


def open_door():
    if requests is None:
        raise RuntimeError("requests is required for GaragePi calls")
    resp = requests.post(
        f"{GARAGEPI_URL}/toggle", headers=authorized_headers(), timeout=4
    )
    resp.raise_for_status()


def safe_to_open(now):
    global last_open_ts
    if now - last_open_ts < OPEN_COOLDOWN_S:
        return False
    st = door_status()
    return st == "Closed"  # don't toggle if state is open, moving, or unknown


def main():
    global last_open_ts
    assert (
        RTSP_URL and PLATE_API_TOKEN and APPROVED_PLATES
    ), "Set RTSP_URL, PLATE_API_TOKEN, APPROVED_PLATES (comma-separated)."

    while True:
        try:
            jpg = take_snapshot(RTSP_URL)
            if not jpg:
                time.sleep(SAMPLE_SECS)
                continue

            data = alpr_lookup(jpg)
            results = data.get("results", [])
            for r in results:
                plate = (r.get("plate", "") or "").upper()
                score = float(r.get("score") or 0.0)
                if plate in APPROVED_PLATES and score >= MIN_SCORE:
                    now = time.time()
                    if safe_to_open(now):
                        print(f"[ALPR] Match {plate} (score {score:.2f}) → opening")
                        open_door()
                        last_open_ts = now
                    else:
                        print(f"[ALPR] Match {plate} but not safe/cooldown")
                    break
        except Exception as e:
            print("Watcher error:", e)
        time.sleep(SAMPLE_SECS)


if __name__ == "__main__":
    main()
