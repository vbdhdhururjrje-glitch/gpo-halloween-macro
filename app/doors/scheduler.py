import math

from app.doors.door import DoorState


class DoorScheduler:
    def __init__(self, door_manager):
        self.door_manager = door_manager

    def choose_next(self, distance_by_door=None):
        distances = distance_by_door or {}
        candidates = self.door_manager.available_doors()
        return min(
            candidates,
            key=lambda door: (
                self._distance(distances.get(door.id)),
                door.route_order,
            ),
            default=None,
        )

    def seconds_until_next_available(self):
        remaining = [
            self.door_manager.cooldown_remaining(door.id)
            for door in self.door_manager.doors
            if door.state == DoorState.COOLDOWN
        ]
        return min(remaining) if remaining else None

    def door_interaction_release_indices(self, route):
        interaction_indices = {}
        actions = route.actions
        for point in route.points:
            if point.type.upper() != "DOOR":
                continue
            action_index = point.action_index
            if action_index + 1 >= len(actions):
                continue
            press, release = actions[action_index:action_index + 2]
            if (
                press.get("type") == "KEY_DOWN"
                and self._is_interaction_key(press.get("key"))
                and release.get("type") == "KEY_UP"
                and self._is_interaction_key(release.get("key"))
            ):
                interaction_indices[action_index + 1] = (
                    point.id,
                    press.get("key"),
                )
        return interaction_indices

    def door_interaction_start_indices(self, route):
        interaction_indices = {}
        actions = route.actions
        for point in route.points:
            if point.type.upper() != "DOOR":
                continue
            action_index = point.action_index
            if action_index + 1 >= len(actions):
                continue
            press, release = actions[action_index:action_index + 2]
            if (
                press.get("type") == "KEY_DOWN"
                and self._is_interaction_key(press.get("key"))
                and release.get("type") == "KEY_UP"
                and self._is_interaction_key(release.get("key"))
            ):
                interaction_indices[action_index] = point.id
        return interaction_indices

    @staticmethod
    def _is_interaction_key(key):
        return str(key).lower() in {"e", "vk:69"}

    @staticmethod
    def _distance(value):
        try:
            distance = float(value)
        except (TypeError, ValueError):
            return math.inf
        return distance if math.isfinite(distance) and distance >= 0 else math.inf