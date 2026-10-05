import json
import time
from pathlib import Path

from app.route.route import Route
from app.route.route_point import RoutePoint


class RouteManager:
    POINT_TYPES = {"DOOR"}

    def __init__(self):
        self.route = Route()
        self.file_path = None
        self.recording_started_at = None
        self.paused_at = None
        self.paused_total = 0.0

    @property
    def recording(self):
        return self.recording_started_at is not None

    def start_recording(self, name="Halloween Route", cursor_position=None, screen_size=None):
        start = {
            "type": "START_POINT",
            "timestamp": 0.0,
            "action_index": 0,
        }
        if cursor_position is not None:
            start["cursor_position"] = {
                "x": int(cursor_position["x"]),
                "y": int(cursor_position["y"]),
            }
        if isinstance(screen_size, dict) and screen_size.get("width") and screen_size.get("height"):
            start["screen_size"] = {
                "width": int(screen_size["width"]),
                "height": int(screen_size["height"]),
            }
        self.route = Route(name=name, start=start)
        self.file_path = None
        self.recording_started_at = time.monotonic()
        self.paused_at = None
        self.paused_total = 0.0

    def stop_recording(self):
        self.recording_started_at = None
        self.paused_at = None
        self.paused_total = 0.0

    def pause_recording(self):
        if self.recording and self.paused_at is None:
            self.paused_at = time.monotonic()

    def resume_recording(self):
        if self.recording and self.paused_at is not None:
            self.paused_total += time.monotonic() - self.paused_at
            self.paused_at = None

    def elapsed(self):
        if self.recording_started_at is None:
            return 0.0
        current = self.paused_at if self.paused_at is not None else time.monotonic()
        return round(current - self.recording_started_at - self.paused_total, 6)

    def add_action(self, action):
        if not self.recording:
            return
        recorded = dict(action)
        recorded["timestamp"] = self.elapsed()
        self.route.actions.append(recorded)

    def add_point(self, point_type):
        if not self.recording:
            raise RuntimeError("Start recording before adding route markers.")
        point_type = point_type.upper()
        if point_type not in self.POINT_TYPES:
            raise ValueError(f"Unsupported point type: {point_type}")
        point = RoutePoint(
            id=len(self.route.points) + 1,
            type=point_type,
            timestamp=self.elapsed(),
            action_index=len(self.route.actions),
        )
        self.route.points.append(point)
        return point

    def save(self, path):
        path = Path(path)
        path.write_text(
            json.dumps(self.route.to_dict(), indent=2),
            encoding="utf-8",
        )
        self.file_path = path

    def load(self, path):
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.route = Route.from_dict(data)
        self.file_path = path
        return self.route

    def get_point(self, point_id):
        return next((point for point in self.route.points if point.id == point_id), None)

    def delete(self):
        if self.file_path is not None:
            self.file_path.unlink(missing_ok=True)
        self.route = Route()
        self.stop_recording()
        self.file_path = None