#!/usr/bin/env python
from importlib import import_module
import json
import hashlib
import os
import re
from flask import Flask, Response, send_from_directory, jsonify, request
from flask_cors import *
# import camera driver

from modules.camera import Camera
import threading

from modules import battery_monitor
from modules import servo_calibration
from modules import servo_steps
from core.events import event_bus

# Raspberry Pi camera module (requires picamera package)
# from camera_pi import Camera

app = Flask(__name__)
CORS(app, supports_credentials=True)
camera = Camera()


def _calibration_snapshot():
    status = battery_monitor.sample_status()
    cal = battery_monitor.get_calibration()
    return {
        "calibration": cal,
        "voltage": round(status.get("voltage", 0.0) or 0.0, 3),
        "raw_voltage": round(status.get("raw_voltage", 0.0) or 0.0, 3),
    }


def _calibration_etag(payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(data).hexdigest()

def gen(camera):
    """Video streaming generator function."""
    while True:
        frame = camera.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    """Video streaming route. Put this in the src attribute of an img tag."""
    return Response(gen(camera),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/calibration', methods=['GET', 'POST'])
def calibration_api():
    if request.method == 'GET':
        snapshot = _calibration_snapshot()
        etag = _calibration_etag(snapshot)
        if request.headers.get("If-None-Match") == etag:
            resp = Response(status=304)
            resp.set_etag(etag)
            return resp
        resp = jsonify(snapshot)
        resp.set_etag(etag)
        return resp

    payload = request.get_json(force=True) or {}
    try:
        actual_voltage = float(payload.get("voltage", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid voltage value"}), 400

    if actual_voltage <= 0:
        return jsonify({"error": "Voltage must be greater than zero"}), 400

    try:
        result = battery_monitor.calibrate_to_voltage(actual_voltage)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    status = battery_monitor.sample_status()
    calibration_payload = {
        "scale": result.get("scale"),
        "factor": result.get("factor"),
        "offset": result.get("offset"),
        "min_voltage": result.get("min_voltage"),
        "max_voltage": result.get("max_voltage"),
    }
    response = {
        "success": True,
        "calibration": calibration_payload,
        "actual_voltage": result.get("actual_voltage"),
        "raw_sample": result.get("raw_voltage"),
        "voltage": round(status.get("voltage", 0.0) or 0.0, 3),
        "raw_voltage": round(status.get("raw_voltage", 0.0) or 0.0, 3),
    }
    payload_for_etag = {
        "calibration": response["calibration"],
        "voltage": response["voltage"],
        "raw_voltage": response["raw_voltage"],
    }
    etag = _calibration_etag(payload_for_etag)
    flask_response = jsonify(response)
    flask_response.set_etag(etag)
    event_bus.publish("battery_status", {"voltage": response["voltage"], "raw_voltage": response["raw_voltage"]})
    event_bus.publish("battery_calibration", response["calibration"])
    return flask_response


@app.route('/api/servo/shoulder', methods=['GET', 'POST'])
def shoulder_servo_calibration():
    if request.method == 'GET':
        data = servo_calibration.get_shoulder_calibration()
        return jsonify({"calibration": data})

    payload = request.get_json(force=True) or {}
    try:
        base_angle = float(payload.get("base_angle", 0))
        raise_angle = float(payload.get("raise_angle", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Angles must be numeric."}), 400

    try:
        result = servo_calibration.update_shoulder_calibration(
            base_angle=base_angle,
            raise_angle=raise_angle,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive
        return jsonify({"error": str(exc)}), 500

    event_bus.publish("shoulder_calibration", result)
    return jsonify({"success": True, "calibration": result})


@app.route('/api/servo/steps', methods=['GET', 'POST'])
def servo_step_settings():
    if request.method == 'GET':
        return jsonify({"steps": servo_steps.get_steps(), "limits": servo_steps.get_limits()})

    payload = request.get_json(force=True) or {}
    updates = {key: payload.get(key) for key in servo_steps.SERVO_STEP_KEYS if key in payload}
    try:
        result = servo_steps.update_steps(updates)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    event_bus.publish("servo_steps", {"steps": result, "limits": servo_steps.get_limits()})
    return jsonify({"success": True, "steps": result, "limits": servo_steps.get_limits()})


@app.route('/api/events')
def sse_events():
    """Server-sent events stream for UI updates."""
    def stream():
        queue = event_bus.listen()
        queue.put({
            "type": "shoulder_calibration",
            "payload": servo_calibration.get_shoulder_calibration(),
        })
        queue.put({
            "type": "battery_status",
            "payload": battery_monitor.sample_status(),
        })
        queue.put({
            "type": "servo_steps",
            "payload": {"steps": servo_steps.get_steps(), "limits": servo_steps.get_limits()},
        })
        try:
            while True:
                message = queue.get()
                event_type = message.get("type", "message")
                payload = message.get("payload", {})
                yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
        except GeneratorExit:
            event_bus.remove(queue)

    return Response(stream(), mimetype='text/event-stream')

dir_path = os.path.dirname(os.path.realpath(__file__))
dist_dir = os.path.join(dir_path, "dist")
default_index = "index.html"
mobile_index = "index.mobile.html"
mobile_user_agent = re.compile(
    r"(iphone|ipod|ipad|android|blackberry|windows phone|opera mini|mobile)",
    re.IGNORECASE,
)


def _is_mobile_request() -> bool:
    """Basic user-agent check to decide whether to serve the mobile-friendly page."""
    if request.args.get("desktop") == "1":
        return False
    if request.args.get("mobile") == "1":
        return True
    ua = request.headers.get("User-Agent", "") or ""
    return bool(mobile_user_agent.search(ua))


def _resolve_index_file() -> str:
    """Return the correct index file depending on device type and availability."""
    target = default_index
    if _is_mobile_request():
        mobile_path = os.path.join(dist_dir, mobile_index)
        if os.path.exists(mobile_path):
            target = mobile_index
    return target

@app.route('/api/img/<path:filename>')
def sendimg(filename):
    return send_from_directory(os.path.join(dist_dir, 'img'), filename)

@app.route('/js/<path:filename>')
def sendjs(filename):
    return send_from_directory(os.path.join(dist_dir, 'js'), filename)

@app.route('/css/<path:filename>')
def sendcss(filename):
    return send_from_directory(os.path.join(dist_dir, 'css'), filename)

@app.route('/api/img/icon/<path:filename>')
def sendicon(filename):
    return send_from_directory(os.path.join(dist_dir, 'img', 'icon'), filename)

@app.route('/fonts/<path:filename>')
def sendfonts(filename):
    return send_from_directory(os.path.join(dist_dir, 'fonts'), filename)

@app.route('/<path:filename>')
def sendgen(filename):
    if filename == "index.html":
        return send_from_directory(dist_dir, _resolve_index_file())
    return send_from_directory(dist_dir, filename)

@app.route('/')
def index():
    return send_from_directory(dist_dir, _resolve_index_file())

class webapp:
    def __init__(self):
        self.camera = camera

    def modeselect(self, modeInput):
        Camera.modeSelect = modeInput

    def colorFindSet(self, H, S, V):
        camera.colorFindSet(H, S, V)

    def thread(self):
        app.run(host='0.0.0.0', port=5000,threaded=True)

    def startthread(self):
        fps_threading=threading.Thread(target=self.thread)         #Define a thread for FPV and OpenCV
        # fps_threading.setDaemon(False)                             #'True' means it is a front thread,it would close when the mainloop() closes
        fps_threading.daemon = False
        fps_threading.start()                                     #Thread starts


if __name__ == "__main__":
    WEB = webapp()
    try:
        WEB.startthread()
    except:
        print("exit")
