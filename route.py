from dataclasses import dataclass, field
import math

from app.route.route_point import RoutePoint


@dataclass
class Route:
    ACTION_TYPES = {
        "KEY_DOWN",
        "KEY_UP",
        "MOUSE_MOVE",
        "MOUSE_SCROLL",
        "MOUSE_BUTTON_DOWN",
        "MOUSE_BUTTON_UP",
    }
    POINT_TYPES = {"DOOR"}

    name: str = "Halloween Route"
    start: dict = field(default_factory=lambda: {
        "type": "START_POINT",
        "timestamp": 0.0,
        "action_index": 0,
    })
    points: list[RoutePoint] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    version: int = 1

    def to_dict(self):
        return {
            "version": self.version,
            "name": self.name,
            "start": self.start,
            "points": [point.to_dict() for point in self.points],
            "actions": self.actions,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or not isinstance(data.get("actions", []), list):
            raise ValueError("Invalid route file: expected an object with an actions list.")
        points_data = data.get("points", [])
        if not isinstance(points_data, list):
            raise ValueError("Invalid route file: points must be a list.")
        actions = data.get("actions", [])
        if any(not isinstance(action, dict) for action in actions):
            raise ValueError("Invalid route file: each action must be an object.")
        start = data.get("start", {
            "type": "START_POINT",
            "timestamp": 0.0,
            "action_index": 0,
        })
        if not isinstance(start, dict):
            raise ValueError("Invalid route file: start metadata must be an object.")
        start = dict(start)
        start.pop("respawn_hash", None)
        start.pop("respawn_hash_mode", None)

        normalized_actions = []
        previous_timestamp = 0.0
        for index, action in enumerate(actions):
            normalized = dict(action)
            action_type = str(normalized.get("type", "")).upper()
            if action_type not in cls.ACTION_TYPES:
                raise ValueError(
                    f"Invalid route action #{index + 1}: unsupported type {action_type!r}."
                )
            normalized["type"] = action_type
            timestamp = cls._finite_number(
                normalized.get("timestamp", 0.0),
                f"action #{index + 1} timestamp",
            )
            if timestamp < previous_timestamp:
                raise ValueError(
                    f"Invalid route action #{index + 1}: timestamps must not decrease."
                )
            previous_timestamp = timestamp

            if action_type in {"KEY_DOWN", "KEY_UP"}:
                key = normalized.get("key")
                if not isinstance(key, str) or not key.strip():
                    raise ValueError(f"Invalid route action #{index + 1}: key is required.")
            elif action_type in {"MOUSE_MOVE", "MOUSE_SCROLL"}:
                for field_name in ("dx", "dy"):
                    cls._finite_number(
                        normalized.get(field_name),
                        f"action #{index + 1} {field_name}",
                    )
                if action_type == "MOUSE_MOVE":
                    has_x = "x" in normalized
                    has_y = "y" in normalized
                    if has_x != has_y:
                        raise ValueError(
                            f"Invalid route action #{index + 1}: x and y must be paired."
                        )
                    if has_x:
                        cls._finite_number(normalized["x"], f"action #{index + 1} x")
                        cls._finite_number(normalized["y"], f"action #{index + 1} y")
                    if "duration" in normalized and cls._finite_number(
                        normalized["duration"], f"action #{index + 1} duration"
                    ) < 0:
                        raise ValueError(
                            f"Invalid route action #{index + 1}: duration cannot be negative."
                        )
            else:
                button = normalized.get("button")
                if not isinstance(button, str) or button.lower() not in {
                    "left", "right", "middle"
                }:
                    raise ValueError(
                        f"Invalid route action #{index + 1}: unsupported mouse button."
                    )
                normalized["button"] = button.lower()
                if action_type == "MOUSE_BUTTON_UP" and cls._finite_number(
                    normalized.get("hold_duration", 0.0),
                    f"action #{index + 1} hold_duration",
                ) < 0:
                    raise ValueError(
                        f"Invalid route action #{index + 1}: hold_duration cannot be negative."
                    )
            normalized_actions.append(normalized)

        points = []
        for point_data in points_data:
            if not isinstance(point_data, dict):
                raise ValueError("Invalid route file: each point must be an object.")
            point_type = str(point_data.get("type", "")).upper()
            if point_type in {"WAYPOINT", "DEATH", "DEAD"}:
                continue
            points.append(RoutePoint.from_dict(point_data))
        point_ids = set()
        for point in points:
            if point.id <= 0 or point.id in point_ids:
                raise ValueError("Invalid route file: point ids must be unique positive integers.")
            point_ids.add(point.id)
            if point.type not in cls.POINT_TYPES:
                raise ValueError(f"Invalid route file: unsupported point type {point.type!r}.")
            if not 0 <= point.action_index <= len(normalized_actions):
                raise ValueError(
                    f"Invalid route file: point #{point.id} action_index is out of range."
                )
            if cls._finite_number(point.timestamp, f"point #{point.id} timestamp") < 0:
                raise ValueError(f"Invalid route file: point #{point.id} timestamp cannot be negative.")

        return cls(
            version=int(data.get("version", 1)),
            name=str(data.get("name", "Halloween Route")),
            start=start,
            points=points,
            actions=normalized_actions,
        )

    @staticmethod
    def _finite_number(value, description):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid route: {description} must be numeric.") from exc
        if not math.isfinite(number):
            raise ValueError(f"Invalid route: {description} must be finite.")
        return number