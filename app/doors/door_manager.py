import math
import time

from app.doors.door import Door, DoorState


class DoorManager:
    def __init__(self, clock=None, wall_clock=None):
        self._clock = clock or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._doors = {}

    @property
    def doors(self):
        self.refresh_states()
        return tuple(sorted(self._doors.values(), key=lambda door: door.route_order))

    def sync_from_points(self, points):
        door_points = sorted(
            (point for point in points if point.type.upper() == "DOOR"),
            key=lambda point: (point.action_index, point.timestamp, point.id),
        )
        previous = self._doors
        self._doors = {}
        for route_order, point in enumerate(door_points, start=1):
            door = previous.get(point.id) or Door(
                id=point.id,
                route_order=route_order,
                timestamp=point.timestamp,
                action_index=point.action_index,
            )
            door.route_order = route_order
            door.timestamp = point.timestamp
            door.action_index = point.action_index
            self._doors[door.id] = door
        self.refresh_states()

    def clear(self):
        self._doors.clear()

    def get(self, door_id):
        self.refresh_states()
        return self._doors.get(int(door_id))

    def refresh_states(self):
        now = self._clock()
        for door in self._doors.values():
            if door.state == DoorState.COOLDOWN and door.cooldown_until is not None:
                if now >= door.cooldown_until:
                    door.state = DoorState.AVAILABLE
                    door.cooldown_until = None
                    door.last_result = "COOLDOWN_EXPIRED"

    def cooldown_remaining(self, door_id):
        door = self.get(door_id)
        if door is None or door.state != DoorState.COOLDOWN:
            return 0.0
        return max(0.0, door.cooldown_until - self._clock())

    def available_doors(self):
        return tuple(door for door in self.doors if door.state == DoorState.AVAILABLE)

    def export_cooldowns(self):
        self.refresh_states()
        wall_now = self._wall_clock()
        monotonic_now = self._clock()
        return {
            str(door.id): wall_now + door.cooldown_until - monotonic_now
            for door in self._doors.values()
            if door.state == DoorState.COOLDOWN and door.cooldown_until is not None
        }

    def restore_cooldowns(self, points, expires_at_by_door):
        self._doors.clear()
        self.sync_from_points(points)
        wall_now = self._wall_clock()
        monotonic_now = self._clock()
        restored = 0
        for door_id, expires_at in expires_at_by_door.items():
            try:
                door = self._doors.get(int(door_id))
                expiration = float(expires_at)
            except (TypeError, ValueError, OverflowError):
                continue
            if door is None or not math.isfinite(expiration):
                continue
            remaining = expiration - wall_now
            if not math.isfinite(remaining) or remaining <= 0:
                continue
            door.state = DoorState.COOLDOWN
            door.cooldown_until = monotonic_now + remaining
            door.last_result = f"COOLDOWN {remaining:g}s (restored)"
            restored += 1
        return restored

    def record_ocr_result(
        self,
        door_id,
        cooldown=None,
        candy_event=None,
        candy_events=None,
        stable=True,
    ):
        door = self.get(door_id)
        if door is None:
            return None

        now = self._clock()
        door.last_attempt = now
        if not stable:
            door.state = DoorState.UNKNOWN
            door.cooldown_until = None
            door.failed_ocr_count += 1
            door.last_result = "OCR_UNSTABLE"
        elif cooldown is not None:
            seconds = max(0.0, float(cooldown))
            door.state = DoorState.COOLDOWN if seconds > 0 else DoorState.AVAILABLE
            door.cooldown_until = now + seconds if seconds > 0 else None
            door.failed_ocr_count = 0
            door.last_result = f"COOLDOWN {seconds:g}s"
        elif candy_events or candy_event is not None:
            events = candy_events or [candy_event]
            last_event = events[-1]
            door.state = DoorState.SUCCESS
            door.cooldown_until = None
            door.failed_ocr_count = 0
            door.last_candy_amount = int(last_event["amount"])
            if len(events) == 1:
                event_type = last_event["type"].upper()
                door.last_result = f"{event_type} +{door.last_candy_amount}"
            else:
                door.last_result = "; ".join(
                    f"{event['type'].upper()} +{int(event['amount'])} "
                    f"(total {int(event['total'])})"
                    for event in events
                )
        else:
            door.state = DoorState.UNKNOWN
            door.cooldown_until = None
            door.failed_ocr_count += 1
            door.last_result = "OCR_UNRECOGNIZED"
        return door